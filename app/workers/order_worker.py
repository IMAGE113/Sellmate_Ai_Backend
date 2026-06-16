import asyncio
import logging
import json
import os
from decimal import Decimal
from typing import Any
from app.db.database import get_db_pool, OrderRepository, MerchantRepository, AuditRepository
from app.services.ai import ai
from app.services.order_service import OrderService
from app.workflow.flow_manager import FlowManager
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.rate_limiter import rate_limiter
from app.services.lifecycle_service import LifecycleService, LifecycleRepository

# ==========================================
# 🛡️ [SAFE UTILITIES] ဘာဒေတာပဲလာလာ Error မတက်အောင် ကြိုတင်သန့်စင်ပေးမယ့် Functions
# ==========================================
def make_json_safe(data: Any) -> Any:
    """ Decimal တွေကို float အဖြစ် အလိုအလျောက် ပြောင်းပေးတဲ့ စနစ် """
    if isinstance(data, list):
        return [make_json_safe(item) for item in data]
    if isinstance(data, dict):
        return {k: make_json_safe(v) for k, v in data.items()}
    if isinstance(data, Decimal):
        return float(data)
    return data

def force_dict(data: Any) -> dict:
    """ Database က String သို့မဟုတ် None ထွက်လာရင်တောင် dict ဖြစ်အောင် အတင်းပြောင်းပေးမယ့် စနစ် """
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else {}
        except:
            return {}
    return {}
# ==========================================

async def run_worker():
    pool = await get_db_pool()
    worker_id = f"worker-{os.getpid()}"
    logging.info(f"🚀 SellMate AI Multi-tenant Workflow Worker {worker_id} started...")

    while True:
        try:
            # 1. Fetch pending task using QueueManager
            queue_repo = QueueRepository(pool, "SYSTEM") 
            queue_manager = QueueManager(queue_repo, worker_id)
            
            task = await queue_manager.pop("inbound_messages")

            if not task:
                await asyncio.sleep(1)
                continue

            shop_id = task["shop_id"]
            payload = json.loads(task["payload"])
            chat_id = payload["chat_id"]
            user_text = payload["data"].get("user_text", "")
                
            # 2. Global Lifecycle & Rate Limit Check
            lifecycle_service = LifecycleService(LifecycleRepository(pool, shop_id))
            try:
                await lifecycle_service.validate_active(shop_id)
                rate_limiter.validate_merchant_message(shop_id)
                rate_limiter.validate_ai_usage(shop_id)
            except Exception as e:
                logging.warning(f"Validation failed for {shop_id}: {e}")
                await queue_manager.fail(task["id"], str(e), can_retry=False)
                continue

            # 3. Acquire Conversation Lock
            lock_repo = LockRepository(pool, shop_id)
            lock_manager = LockManager(lock_repo)
            if not await lock_manager.acquire(chat_id):
                logging.info(f"Could not acquire lock for {shop_id}:{chat_id}, retrying later")
                await queue_manager.fail(task["id"], "Lock acquisition failed", can_retry=True)
                continue

            try:
                # Repositories
                order_repo = OrderRepository(pool, shop_id)
                merchant_repo = MerchantRepository(pool, shop_id)
                audit_repo = AuditRepository(pool, shop_id)
                order_service = OrderService(order_repo, audit_repo)

                # 4. Fetch business info
                biz = await merchant_repo.get_merchant_by_shop_id()
                if not biz:
                    await queue_manager.fail(task["id"], f"Merchant {shop_id} not found", can_retry=False)
                    continue

                # 4. Human Takeover Check
                if biz.get("is_human_takeover_active"):
                    logging.info(f"Human takeover active for {shop_id}, skipping AI")
                    await queue_manager.complete(task["id"])
                    continue

                # 5. Fetch/Create Order
                order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"])
                
                # 🛡️ [SAFE FIX 1] Order ရဲ့ extracted_data က String ဖြစ်နေရင် dict ဖြစ်အောင် အတင်းပြောင်းလိုက်မယ်
                order = dict(order_raw) if order_raw else {}
                order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                
                # 6. Fetch Menu
                menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                menu_raw = [dict(m) for m in menu_rows]
                
                # 🛡️ [SAFE FIX 2] Menu ထဲက Decimal စျေးနှုန်းတွေကို အလိုအလျောက် JSON Safe ဖြစ်အောင် float ပြောင်းပေးမယ်
                menu = make_json_safe(menu_raw)

                # 7. AI Extraction
                extracted_json = await ai.extract_data(
                    user_text, 
                    biz["name"], 
                    menu, 
                    order.get("extracted_data", {}),
                    biz.get("requirements_text")
                )
                
                # 🛡️ [SAFE FIX 3] AI ဆီက ပြန်လာတဲ့ Json ကို loads လုပ်ပြီး ဒေတာသန့်စင်မယ်
                extracted_data = force_dict(json.loads(extracted_json) if isinstance(extracted_json, str) else extracted_json)
                
                # 8. Merge Data & Update Order
                new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
                intent = extracted_data.get("intent", "ORDER")
                
                # Update order in DB
                await order_repo.execute(
                    "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    json.dumps(new_extracted_data), order["id"]
                )

                # 9. Workflow Management
                flow = FlowManager(biz, new_extracted_data)
                status_key = flow.get_next_step(intent)
                
                # 10. Handle Intent/Status Actions
                if status_key == "HUMAN_TAKEOVER":
                    await merchant_repo.execute("UPDATE businesses SET is_human_takeover_active = TRUE WHERE id = $1", biz["id"])
                    await audit_repo.log_event("HUMAN_TAKEOVER_START", "bot", "User requested human", order["id"])
                
                # 11. Generate Response
                reply_text = flow.get_response(status_key, biz["name"])
                
                # 12. Send Response
                await send(biz["tg_bot_token"], chat_id, reply_text)
                
                # 13. Audit Log
                await audit_repo.log_event("BOT_REPLY", "bot", f"Replied with {status_key}", order["id"], {"reply": reply_text})

                # 14. Mark task as completed
                await queue_manager.complete(task["id"])

            finally:
                # Always release the lock
                await lock_manager.release(chat_id)

        except Exception as e:
            logging.error(f"🔥 Worker Error: {str(e)}", exc_info=True)
            if 'task' in locals() and task:
                await queue_manager.fail(task["id"], str(e))
            await asyncio.sleep(2)
        
        await asyncio.sleep(0.1)