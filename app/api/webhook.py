import hashlib
import logging
import httpx
from fastapi import APIRouter, Request, HTTPException
from app.db.database import get_db_pool

router = APIRouter()

@router.post("/webhook/{shop_id}")
async def webhook(shop_id: int, request: Request):
    try:
        data = await request.json()
        pool = await get_db_pool()

        async with pool.acquire() as conn:
            # Fetch business details by shop_id
            biz = await conn.fetchrow(
                "SELECT id, tg_bot_token FROM businesses WHERE id=$1", 
                shop_id
            )
            
            if not biz:
                logging.warning(f"🚫 Unauthorized shop_id attempt: {shop_id}")
                raise HTTPException(status_code=404, detail="Shop not found")

            token = biz["tg_bot_token"]

            # 1. Callback Query Logic (Confirm/Restart Buttons)
            if "callback_query" in data:
                cb = data["callback_query"]
                callback_id = cb["id"]

                # Answer Callback to stop Telegram loading spinner
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                        json={"callback_query_id": callback_id}
                    )

                # Transform callback into a message-like structure for the worker
                data["message"] = {
                    "chat": {"id": cb["message"]["chat"]["id"]},
                    "text": cb["data"],
                    "from": cb["from"]
                }

            msg = data.get("message")
            if not msg or "text" not in msg:
                return {"ok": True}

            chat_id = msg["chat"]["id"]
            user_text = msg["text"]

            # 2. Queue the task
            h = hashlib.md5(f"{chat_id}{user_text}".encode()).hexdigest()

            await conn.execute("""
                INSERT INTO task_queue (business_id, chat_id, user_text, request_hash, status)
                VALUES ($1, $2, $3, $4, 'pending')
                ON CONFLICT (request_hash) DO NOTHING
            """, biz["id"], chat_id, user_text, h)

        return {"ok": True}

    except Exception as e:
        logging.error(f"🔥 Webhook Error: {str(e)}")
        # We return 200 to Telegram to avoid retries on our side, but log the error
        return {"ok": True}

@router.post("/register-bot")
async def register_bot(token: str, name: str, category: str):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO businesses (name, tg_bot_token, category) VALUES ($1, $2, $3) RETURNING id",
                name, token, category
            )
            shop_id = row["id"]
            
            # Set webhook automatically
            webhook_url = f"https://{os.getenv('DOMAIN')}/webhook/{shop_id}"
            async with httpx.AsyncClient() as client:
                await client.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": webhook_url})
            
            return {"status": "success", "message": f"Bot {name} registered!", "shop_id": shop_id, "webhook_url": webhook_url}
        except Exception as e:
            logging.error(f"Registration Error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
