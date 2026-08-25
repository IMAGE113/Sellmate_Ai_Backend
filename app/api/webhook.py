import hashlib
import logging
import httpx
import json
import time
import unicodedata
from collections import defaultdict, deque
from fastapi import APIRouter, Request, HTTPException
import uuid
from app.db.database import get_db_pool, MerchantRepository, AuditRepository, OrderRepository
from app.services.idempotency_service import IdempotencyRepository, IdempotencyService
from app.services.queue_manager import QueueRepository, QueueManager
from app.schemas.queue import QueuePayloadSchema
from app.services.s3_service import s3_service
from app.services.telegram_service import telegram_service
from app.services.order_service import OrderService
from app.services.telegram import send
from app.core.config import TELEGRAM_WEBHOOK_SECRET

router = APIRouter()
_MAX_TEXT_LENGTH = 4000
_DUPLICATE_WINDOW_SECONDS = 3
_CHAT_WINDOW_SECONDS = 60
_CHAT_MESSAGE_LIMIT = 30
_MAX_RECENT_KEYS = 10000
_MAX_CHAT_WINDOWS = 10000
_recent_messages = {}
_chat_message_windows = defaultdict(deque)


def _has_meaningful_text(value: str) -> bool:
    return bool(value and any(unicodedata.category(ch)[0] in {"L", "N"} for ch in value))


def _is_duplicate_or_spam(shop_id: str, chat_id: int, text: str) -> bool:
    now = time.monotonic()
    # Bound the process-local cache so long-running workers do not retain old chat data.
    expired = [key for key, seen_at in _recent_messages.items() if now - seen_at > _DUPLICATE_WINDOW_SECONDS]
    for old_key in expired:
        _recent_messages.pop(old_key, None)
    key = (shop_id, chat_id, text)
    if key not in _recent_messages and len(_recent_messages) >= _MAX_RECENT_KEYS:
        oldest_key = min(_recent_messages, key=_recent_messages.get)
        _recent_messages.pop(oldest_key, None)
    previous = _recent_messages.get(key)
    _recent_messages[key] = now
    if previous is not None and now - previous <= _DUPLICATE_WINDOW_SECONDS:
        return True

    chat_key = (shop_id, chat_id)
    if chat_key not in _chat_message_windows and len(_chat_message_windows) >= _MAX_CHAT_WINDOWS:
        oldest_chat = min(
            _chat_message_windows,
            key=lambda stored_key: _chat_message_windows[stored_key][-1] if _chat_message_windows[stored_key] else 0,
        )
        _chat_message_windows.pop(oldest_chat, None)
    window = _chat_message_windows[chat_key]
    while window and now - window[0] > _CHAT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _CHAT_MESSAGE_LIMIT:
        return True
    window.append(now)
    return False

@router.post("/webhook/{shop_id}")
async def webhook(shop_id: str, request: Request):
    idempotency_claimed = False
    update_id = None
    idempotency_service = None
    try:
        if TELEGRAM_WEBHOOK_SECRET:
            provided_secret = getattr(request, "headers", {}).get("X-Telegram-Bot-Api-Secret-Token")
            if provided_secret != TELEGRAM_WEBHOOK_SECRET:
                raise HTTPException(status_code=401, detail="Invalid webhook secret")
        try:
            data = await request.json()
        except Exception:
            logging.error("Failed to parse webhook JSON payload")
            raise HTTPException(status_code=400, detail="Invalid JSON")

        if not isinstance(data, dict):
            logging.error(f"Webhook payload is not a dictionary: {type(data)}")
            return {"ok": True}

        update_id = data.get("update_id")
        if update_id is not None and (
            isinstance(update_id, bool)
            or not isinstance(update_id, int)
            or update_id < 0
            or update_id > 9223372036854775807
        ):
            logging.warning("Webhook update_id is invalid")
            return {"ok": True}
        
        pool = await get_db_pool()
        
        merchant_repo = MerchantRepository(pool, shop_id)
        audit_repo = AuditRepository(pool, shop_id)
        
        biz = await merchant_repo.get_merchant_by_shop_id()
        if not biz:
            logging.warning(f"🚫 Unauthorized shop_id attempt: {shop_id}")
            raise HTTPException(status_code=404, detail="Shop not found")

        # Claim only after tenant validation, preventing unknown paths from filling the idempotency table.
        idempotency_repo = IdempotencyRepository(pool, shop_id)
        idempotency_service = IdempotencyService(idempotency_repo)
        if update_id is not None:
            if await idempotency_service.check_and_mark(update_id):
                logging.info(f"Skipping already claimed update_id: {update_id}")
                return {"ok": True}
            idempotency_claimed = True

        token = biz["tg_bot_token"]

        # 2. Callback Query Logic
        if "callback_query" in data:
            cb = data["callback_query"]
            if not isinstance(cb, dict):
                logging.warning("Callback query payload is not an object")
                return {"ok": True}
            callback_id = cb.get("id")
            if not callback_id:
                logging.warning("Callback query missing ID")
                return {"ok": True}

            # Validate the callback structure before making any external request.
            cb_msg = cb.get("message", {})
            if not isinstance(cb_msg, dict):
                logging.warning("Callback message payload is not an object")
                return {"ok": True}
            cb_chat = cb_msg.get("chat", {})
            if not isinstance(cb_chat, dict):
                logging.warning("Callback chat payload is not an object")
                return {"ok": True}
            cb_chat_id = cb_chat.get("id")
            if not isinstance(cb_chat_id, int) or isinstance(cb_chat_id, bool) or not cb_chat_id:
                logging.warning("Callback chat ID is invalid")
                return {"ok": True}
            cb_data = cb.get("data")
            if not isinstance(cb_data, str) or not cb_data:
                logging.warning("Callback data is not text")
                return {"ok": True}
            cb_from = cb.get("from")

            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                        json={"callback_query_id": callback_id}
                    )
            except Exception:
                logging.exception("Callback acknowledgement failed")

            data["message"] = {
                "chat": {"id": cb_chat_id},
                "text": cb_data,
                "from": cb_from
            }

        edited_message = data.get("edited_message")
        msg = data.get("message") or edited_message
        if not msg:
            return {"ok": True}
        if not isinstance(msg, dict):
            logging.warning("Webhook message payload is not an object")
            return {"ok": True}

        chat = msg.get("chat", {})
        if not isinstance(chat, dict):
            logging.warning("Webhook chat payload is not an object")
            return {"ok": True}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int) or isinstance(chat_id, bool) or not chat_id:
            return {"ok": True}

        # Edited Telegram messages are not replayed as new customer answers. Acknowledge
        # them explicitly so the customer can resend the correction as a new message.
        if edited_message is not None:
            await send(token, chat_id, "Please send corrections as a new text message.")
            if update_id is not None:
                idempotency_claimed = False
            return {"ok": True}

        # Forwarded text is not a reliable answer for the active checkout state.
        if "text" in msg and (msg.get("forward_origin") or msg.get("forward_from")):
            await send(token, chat_id, "Please type your answer as a new message instead of forwarding it.")
            if update_id is not None:
                idempotency_claimed = False
            return {"ok": True}

        # Reject blank, emoji-only, and punctuation-only text before queueing it.
        if "text" in msg:
            user_text = msg.get("text") or ""
            if not isinstance(user_text, str):
                logging.warning("Webhook text payload is not a string")
                return {"ok": True}
            if not _has_meaningful_text(user_text):
                await send(token, chat_id, "Please type your answer using text.")
                if update_id:
                    await idempotency_service.check_and_mark(update_id)
                return {"ok": True}
            if len(user_text) > _MAX_TEXT_LENGTH:
                await send(token, chat_id, "That message is too long. Please send a shorter answer.")
                if update_id:
                    await idempotency_service.check_and_mark(update_id)
                return {"ok": True}
            if _is_duplicate_or_spam(shop_id, chat_id, user_text.strip()):
                await send(token, chat_id, "Please wait a moment and send one message at a time.")
                if update_id:
                    await idempotency_service.check_and_mark(update_id)
                return {"ok": True}
        
        # Handle Photo Uploads (Screenshots)
        if "photo" in msg:
            # Defensive validation: Ensure photo list is not empty
            if not isinstance(msg["photo"], list) or len(msg["photo"]) == 0:
                logging.warning(f"Empty photo array received for chat_id {chat_id}")
                return {"ok": True}

            from app.services.lock_manager import LockRepository, LockManager
            lock_repo = LockRepository(pool, shop_id)
            lock_manager = LockManager(lock_repo)
            
            # Lock Retry Strategy: Try up to 3 times with small delay for transient locks
            lock_acquired = False
            for _ in range(3):
                if await lock_manager.acquire(chat_id):
                    lock_acquired = True
                    break
                import asyncio
                await asyncio.sleep(0.1)

            if not lock_acquired:
                logging.warning(f"Lock busy for chat_id {chat_id} after retries, skipping photo processing")
                return {"ok": True} # Telegram will retry
            
            try:
                # Update order with screenshot URL and payment_screenshot_received flag
                order_repo = OrderRepository(pool, shop_id)
                order_service = OrderService(order_repo, audit_repo)
                order = await order_service.get_or_create_active_order(chat_id, biz["id"])
                
                # BUG-26: Only process screenshots for Prepaid orders
                extracted_data = order.get("extracted_data", {})
                if isinstance(extracted_data, str):
                    try: extracted_data = json.loads(extracted_data)
                    except: extracted_data = {}
                
                if extracted_data.get("payment_method") != "Prepaid":
                    logging.info(f"Ignoring photo for COD/unset order {order['id']}")
                    await send(token, chat_id, "This order is not using prepaid payment. Please continue by typing your answer.")
                    if update_id:
                        await idempotency_service.check_and_mark(update_id)
                    return {"ok": True}

                # Get the largest photo only when Telegram supplied valid photo objects.
                photo_sizes = msg["photo"]
                if not all(isinstance(photo, dict) for photo in photo_sizes):
                    logging.warning("Photo payload contains a non-object entry")
                    return {"ok": True}
                file_id = photo_sizes[-1].get("file_id")
                if not isinstance(file_id, str) or not file_id:
                    logging.warning("Photo object missing valid file_id")
                    return {"ok": True}
                
                # Get file path from Telegram
                file_path = await telegram_service.get_file_path(token, file_id)
                
                # Download file content
                file_content = await telegram_service.download_file(token, file_path)
                
                # Generate a unique object name for S3
                object_name = f"uploads/{shop_id}/{chat_id}/payment_screenshot_{uuid.uuid4()}.jpg"
                
                # Upload to S3
                screenshot_url = await s3_service.upload_file(file_content, object_name)
                
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

                if update_id:
                    await idempotency_service.check_and_mark(update_id)

                return {"ok": True}
            except Exception as e:
                logging.error(f"🔥 Error processing payment screenshot: {str(e)}", exc_info=True)
                raise HTTPException(status_code=500, detail="Error processing payment screenshot")
            finally:
                await lock_manager.release(chat_id)

        # BUG-28: Handle unsupported message types with an explicit recovery reply.
        if "text" not in msg:
            logging.info(f"Received unsupported message type for chat_id {chat_id}")
            await send(token, chat_id, "I can only understand text messages right now. Please type your answer.")
            if update_id is not None:
                idempotency_claimed = False
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

        if update_id is not None:
            idempotency_claimed = False

        return {"ok": True}

    except HTTPException as he:
        raise he
    except Exception as e:
        if idempotency_claimed and idempotency_service is not None and update_id is not None:
            try:
                await idempotency_service.release_claim(update_id)
            except Exception:
                logging.exception("Failed to release webhook idempotency claim")
        logging.error(f"🔥 Webhook Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")
