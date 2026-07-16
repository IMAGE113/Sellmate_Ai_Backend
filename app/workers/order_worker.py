import asyncio
import logging
import json
import os
from decimal import Decimal
from typing import Any
from app.db.database import get_db_pool, OrderRepository, MerchantRepository, AuditRepository, ProductRepository
from app.services.ai import ai
from app.services.ai_parser import ai_parser
from app.services.order_service import OrderService
from app.workflow.flow_manager import FlowManager
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.rate_limiter import rate_limiter
from app.services.lifecycle_service import LifecycleService, LifecycleRepository

# ==========================================
# 🛡️ [SAFE UTILITIES]
# ==========================================
def make_json_safe(data: Any) -> Any:
    if isinstance(data, list):
        return [make_json_safe(item) for item in data]
    if isinstance(data, dict):
        return {k: make_json_safe(v) for k, v in data.items()}
    if isinstance(data, Decimal):
        return float(data)
    return data

def force_dict(data: Any) -> dict:
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
                
            lifecycle_service = LifecycleService(LifecycleRepository(pool, shop_id))
            try:
                await lifecycle_service.validate_active(shop_id)
                rate_limiter.validate_merchant_message(shop_id)
                rate_limiter.validate_ai_usage(shop_id)
            except Exception as e:
                logging.warning(f"Validation failed for {shop_id}: {e}")
                await queue_manager.fail(task["id"], str(e), can_retry=False)
                continue

            lock_repo = LockRepository(pool, shop_id)
            lock_manager = LockManager(lock_repo)
            if not await lock_manager.acquire(chat_id):
                await queue_manager.fail(task["id"], "Lock acquisition failed", can_retry=True)
                continue

            try:
                order_repo = OrderRepository(pool, shop_id)
                merchant_repo = MerchantRepository(pool, shop_id)
                audit_repo = AuditRepository(pool, shop_id)
                product_repo = ProductRepository(pool, shop_id)
                order_service = OrderService(order_repo, audit_repo)

                biz_raw = await merchant_repo.get_merchant_by_shop_id()
                if not biz_raw:
                    await queue_manager.fail(task["id"], f"Merchant {shop_id} not found", can_retry=False)
                    continue
                
                biz = dict(biz_raw)
                workflow_config = biz.get("workflow_config") or {}
                if isinstance(workflow_config, str):
                    try: workflow_config = json.loads(workflow_config)
                    except: workflow_config = {}
                biz.update(workflow_config)

                if biz.get("is_human_takeover_active"):
                    await queue_manager.complete(task["id"])
                    continue

                # Production bug fix: Handle greeting before fetching/creating order
                # Rule 4: If no active order and user says greeting, start Welcome Flow.
                greetings = ["hi", "hello", "hey", "မင်္ဂလာပါ"]
                is_greeting = any(g in user_text.lower() for g in greetings)
                
                order_raw = await order_repo.get_active_order_by_chat_id(chat_id)
                if not order_raw and is_greeting:
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    # Force intent to GREETING for new flow
                    user_text = "Hello"
                elif not order_raw:
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"])
                
                order = dict(order_raw) if order_raw else {}
                order["extracted_data"] = force_dict(order.get("extracted_data", {}))

                # Initialize FlowManager
                flow = FlowManager(biz, order["extracted_data"])
                
                # 1. Handle Reset Command
                if flow._is_reset_command(user_text):
                    await order_service.update_status(order["id"], "CANCELLED", "bot", "Order reset by user")
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    flow = FlowManager(biz, order["extracted_data"])
                    user_text = "Hello" # Trigger greeting

                # 2. Determine Current State
                current_state = flow.get_current_state()
                
                # 3. Handle Required Fields (Rule 3: Priority Bypass AI Extraction)
                extracted_data = {}
                intent = "ORDER"
                
                if current_state in ["ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP"]:
                    # Direct assignment for required fields - ignore all other intents
                    field_map = {
                        "ASK_NAME": "customer_name",
                        "ASK_PHONE": "phone_no",
                        "ASK_ADDRESS": "address",
                        "ASK_TOWNSHIP": "township"
                    }
                    field_name = field_map[current_state]
                    extracted_data = {field_name: user_text, "intent": "ORDER"}
                    intent = "ORDER"
                else:
                    # Normal AI Extraction
                    menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                    menu = make_json_safe([dict(m) for m in menu_rows])
                    
                    ai_context = {
                        "shop_name": biz["name"],
                        "previous_data": order.get("extracted_data", {}),
                        "requirements_text": biz.get("requirements_text")
                    }
                    extracted_data = await ai_parser.parse_message(user_text, ai_context, menu)
                    intent = extracted_data.get("intent", "ORDER")

                # 4. Merge Data & Update Order
                # Production bug fix: Defensive validation is now inside merge_data()
                new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
                
                # Update DB
                await order_repo.execute(
                    "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    json.dumps(new_extracted_data), order["id"]
                )
                
                # Refresh flow with new data
                flow.order_data = new_extracted_data
                status_key = flow.get_next_step(intent, user_text)
                reply_context = {}

                # 5. Handle Terminal Actions (Confirmation/Stock/etc.)
                if status_key == "ORDER_CONFIRMED":
                    # Finalization logic (deduct stock, etc.)
                    if not new_extracted_data.get("is_finalized"):
                        all_stock_available = True
                        items_to_deduct = []
                        menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                        menu = make_json_safe([dict(m) for m in menu_rows])
                        
                        for item in new_extracted_data.get("items", []):
                            p_name = item.get("name")
                            qty = item.get("qty", 0)
                            if p_name and qty > 0:
                                p = await product_repo.get_product_by_name(p_name)
                                if not p or p["stock"] < qty:
                                    all_stock_available = False
                                    status_key = "OUT_OF_STOCK"
                                    reply_context = {"product_name": p_name, "available_stock": p["stock"] if p else 0}
                                    break
                                items_to_deduct.append((p["id"], qty))
                        
                        if all_stock_available:
                            for p_id, q in items_to_deduct:
                                await product_repo.update_product_stock(p_id, q)
                            
                            from app.services.id_generator import generate_order_number
                            order_num = await generate_order_number(pool)
                            new_extracted_data["is_finalized"] = True
                            new_extracted_data["order_number"] = order_num
                            
                            await order_repo.execute(
                                "UPDATE orders SET extracted_data = $1, status = 'COMPLETED', order_number = $2 WHERE id = $3",
                                json.dumps(new_extracted_data), order_num, order["id"]
                            )
                            reply_context["order_id"] = order_num
                        else:
                            await order_service.update_status(order["id"], status_key, "bot", f"Failed: {status_key}")

                elif status_key == "ORDER_CANCELLED":
                    await order_service.update_status(order["id"], "CANCELLED", "bot", "Cancelled by user")

                # 6. Generate & Send Response
                if status_key == "ORDER_SUMMARY":
                    menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                    menu = make_json_safe([dict(m) for m in menu_rows])
                    summary = []
                    total = 0
                    for item in new_extracted_data.get("items", []):
                        p_name = item.get("name")
                        qty = item.get("qty", 0)
                        price = next((p["price"] for p in menu if p["name"] == p_name), 0)
                        total += price * qty
                        summary.append(f"{p_name} x {qty} ({price * qty:.2f})")
                    
                    reply_text = flow.get_response(
                        status_key, biz["name"],
                        order_summary_details="\n".join(summary),
                        total_price=f"{total:.2f}",
                        customer_name=new_extracted_data.get("customer_name", "N/A"),
                        phone_no=new_extracted_data.get("phone_no", "N/A"),
                        address=new_extracted_data.get("address", "N/A"),
                        payment_method=new_extracted_data.get("payment_method", "N/A")
                    )
                else:
                    reply_text = flow.get_response(status_key, biz["name"], **reply_context)

                await send(biz["tg_bot_token"], chat_id, reply_text)
                await queue_manager.complete(task["id"])

            finally:
                await lock_manager.release(chat_id)

        except Exception as e:
            logging.error(f"🔥 Worker Error: {str(e)}", exc_info=True)
            if 'task' in locals() and task:
                await queue_manager.fail(task["id"], str(e))
            await asyncio.sleep(2)
        
        await asyncio.sleep(0.1)
