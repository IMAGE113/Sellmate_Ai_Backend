import hashlib
import logging
import httpx
import json
from fastapi import APIRouter, Request, HTTPException
import uuid
from app.db.database import get_db_pool, MerchantRepository, AuditRepository, OrderRepository
from app.services.idempotency_service import IdempotencyRepository, IdempotencyService
from app.services.queue_manager import QueueRepository, QueueManager
from app.schemas.queue import QueuePayloadSchema
from app.services.s3_service import s3_service
from app.services.telegram_service import telegram_service
from app.services.order_service import OrderService

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
            try:
                # Get the largest photo
                file_id = msg["photo"][-1]["file_id"]
                
                # Get file path from Telegram
                file_path = await telegram_service.get_file_path(token, file_id)
                
                # Download file content
                file_content = await telegram_service.download_file(token, file_path)
                
                # Generate a unique object name for S3
                object_name = f"uploads/{shop_id}/{chat_id}/payment_screenshot_{uuid.uuid4()}.jpg"
                
                # Upload to S3
                screenshot_url = await s3_service.upload_file(file_content, object_name)
                
                # Update order with screenshot URL and payment_screenshot_received flag
                order_repo = OrderRepository(pool, shop_id)
                order_service = OrderService(order_repo, audit_repo)
                order = await order_service.get_or_create_active_order(chat_id, biz["id"])
                
                # Update extracted_data with payment_screenshot_received and screenshot_url
                extracted_data = order.get("extracted_data", {})
                extracted_data["payment_screenshot_received"] = True
                extracted_data["payment_screenshot_url"] = screenshot_url
                
                await order_repo.execute(
                    "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    json.dumps(extracted_data), order["id"]
                )

                await audit_repo.log_event(
                    event_type="PAYMENT_SCREENSHOT_UPLOADED",
                    actor_source="customer",
                    description="Payment screenshot uploaded and processed",
                    order_id=order["id"],
                    details={"screenshot_url": screenshot_url}
                )

                # Re-queue the message to trigger workflow re-evaluation
                payload = QueuePayloadSchema(
                    shop_id=shop_id,
                    chat_id=chat_id,
                    event_type="MESSAGE",
                    correlation_id=uuid.uuid4(),
                    data={"user_text": "Payment screenshot uploaded"} # Dummy text to re-trigger flow
                )
                queue_repo = QueueRepository(pool, shop_id)
                queue_manager = QueueManager(queue_repo, worker_id=f"webhook-{shop_id}")
                await queue_manager.push("inbound_messages", payload)

                return {"ok": True}
            except Exception as e:
                logging.error(f"🔥 Error processing payment screenshot: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail="Error processing payment screenshot")

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
        logging.error(f"🔥 Webhook Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")
