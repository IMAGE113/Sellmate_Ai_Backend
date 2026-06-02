import hashlib
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
import uuid
from app.db.database import get_db_pool, MerchantRepository, AuditRepository
from app.services.idempotency_service import IdempotencyRepository, IdempotencyService
from app.services.queue_manager import QueueRepository, QueueManager
from app.schemas.queue import QueuePayloadSchema

router = APIRouter()

@router.post("/webhook/{shop_id}")
async def webhook(shop_id: str, request: Request):
    try:
        data = await request.json()
        update_id = data.get("update_id")
        
        pool = await get_db_pool()
        
        # 1. Idempotency Check
        if update_id:
            idempotency_repo = IdempotencyRepository(pool, shop_id)
            idempotency_service = IdempotencyService(idempotency_repo)
            if await idempotency_service.check_and_mark(update_id):
                logging.info(f"Skipping duplicate update_id: {update_id}")
                return {"ok": True}

        merchant_repo = MerchantRepository(pool, shop_id)
        audit_repo = AuditRepository(pool, shop_id)
        
        biz = await merchant_repo.get_merchant_by_shop_id()
        if not biz:
            logging.warning(f"🚫 Unauthorized shop_id attempt: {shop_id}")
            raise HTTPException(status_code=404, detail="Shop not found")

        token = biz["tg_bot_token"]

        # 2. Callback Query Logic
        if "callback_query" in data:
            cb = data["callback_query"]
            callback_id = cb["id"]
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": callback_id}
                )
            data["message"] = {
                "chat": {"id": cb["message"]["chat"]["id"]},
                "text": cb["data"],
                "from": cb["from"]
            }

        msg = data.get("message")
        if not msg:
            return {"ok": True}

        chat_id = msg["chat"]["id"]
        
        # Handle Photo Uploads (Screenshots)
        if "photo" in msg:
            await audit_repo.log_event(
                event_type="ADMIN_ACTION",
                actor_source="customer",
                description="Photo uploaded via Telegram",
                details={"chat_id": chat_id}
            )
            return {"ok": True}

        if "text" not in msg:
            return {"ok": True}

        user_text = msg["text"]

        # 3. Queue the task (Standardized for Multi-tenant)
        correlation_id = uuid.uuid4()
        queue_repo = QueueRepository(pool, shop_id)
        queue_manager = QueueManager(queue_repo, worker_id=f"webhook-{shop_id}")
        
        payload = QueuePayloadSchema(
            shop_id=shop_id,
            chat_id=chat_id,
            event_type="MESSAGE",
            correlation_id=correlation_id,
            data={"user_text": user_text}
        )
        
        await queue_manager.push("inbound_messages", payload)

        return {"ok": True}

    except Exception as e:
        logging.error(f"🔥 Webhook Error: {str(e)}")
        return {"ok": True}
