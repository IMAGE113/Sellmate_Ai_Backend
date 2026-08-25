import asyncio
import logging
import json
import os
import unicodedata
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
from app.services.worker_monitor import WorkerMonitor, WorkerMonitorRepository

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


def has_meaningful_text(value: str) -> bool:
    return bool(value and any(unicodedata.category(ch)[0] in {"L", "N"} for ch in value))
# ==========================================

async def run_worker():
    pool = await get_db_pool()
    worker_id = f"worker-{os.getpid()}"
    logging.info(f"🚀 SellMate AI Multi-tenant Workflow Worker {worker_id} started...")
    
    monitor = WorkerMonitor(WorkerMonitorRepository(pool, "SYSTEM"))
    last_recovery = 0

    async def safely_fail(manager, task_id, error, can_retry=True):
        try:
            await manager.fail(task_id, error, can_retry=can_retry)
        except Exception:
            logging.exception("Failed to update queue task %s after worker error", task_id)

    while True:
        task = None
        try:
            # Run recovery periodically (every 60 seconds)
            current_time = asyncio.get_event_loop().time()
            if current_time - last_recovery > 60:
                await monitor.run_recovery()
                last_recovery = current_time

            # Use None for global worker to fetch tasks for all shops
            queue_repo = QueueRepository(pool, None) 
            queue_manager = QueueManager(queue_repo, worker_id)
            
            # Update heartbeat before popping
            await monitor.heartbeat(worker_id, 0)
            
            task = await queue_manager.pop("inbound_messages")

            if not task:
                await asyncio.sleep(1)
                continue

            # Update heartbeat with active job
            await monitor.heartbeat(worker_id, 1)
            
            shop_id = task["shop_id"]
            payload = json.loads(task["payload"])
            chat_id = payload["chat_id"]
            user_text = payload["data"].get("user_text", "")
            
            # BUG-11: Unicode normalization for all incoming text
            from app.services.validation_service import ValidationService
            user_text = ValidationService.normalize_unicode(user_text)
                
            lifecycle_service = LifecycleService(LifecycleRepository(pool, shop_id))
            try:
                await lifecycle_service.validate_active(shop_id)
                rate_limiter.validate_merchant_message(shop_id)
                rate_limiter.validate_ai_usage(shop_id)
            except Exception as e:
                logging.warning(f"Validation failed for {shop_id}: {e}")
                # Bug Fix: Improve Rate Limit UX by notifying the user instead of silent drop
                from app.services.rate_limiter import RateLimitExceeded
                if isinstance(e, RateLimitExceeded):
                    biz_raw = await MerchantRepository(pool, shop_id).get_merchant_by_shop_id()
                    if biz_raw and biz_raw.get("tg_bot_token"):
                        from app.core.scripts import get_script
                        reply_text = get_script("RATE_LIMIT_EXCEEDED")
                        await send(biz_raw["tg_bot_token"], chat_id, reply_text)
                
                await safely_fail(queue_manager, task["id"], str(e), can_retry=False)
                continue

            lock_repo = LockRepository(pool, shop_id)
            lock_manager = LockManager(lock_repo)
            
            # Lock Retry Strategy: Try up to 3 times with small delay for transient locks
            lock_acquired = False
            for _ in range(3):
                if await lock_manager.acquire(chat_id):
                    lock_acquired = True
                    break
                await asyncio.sleep(0.1)

            if not lock_acquired:
                await safely_fail(queue_manager, task["id"], "Lock acquisition failed after retries", can_retry=True)
                continue

            try:
                order_repo = OrderRepository(pool, shop_id)
                merchant_repo = MerchantRepository(pool, shop_id)
                audit_repo = AuditRepository(pool, shop_id)
                product_repo = ProductRepository(pool, shop_id)
                order_service = OrderService(order_repo, audit_repo)

                biz_raw = await merchant_repo.get_merchant_by_shop_id()
                if not biz_raw:
                    await safely_fail(queue_manager, task["id"], f"Merchant {shop_id} not found", can_retry=False)
                    continue
                
                biz = dict(biz_raw)
                workflow_config = biz.get("workflow_config") or {}
                if isinstance(workflow_config, str):
                    try: workflow_config = json.loads(workflow_config)
                    except: workflow_config = {}
                
                # Bug Fix: Protect critical merchant fields from being overwritten by workflow_config
                protected_fields = ["id", "shop_id", "tg_bot_token", "owner_name", "phone", "password_hash", "status"]
                safe_config = {k: v for k, v in workflow_config.items() if k not in protected_fields}
                biz.update(safe_config)

                if biz.get("is_human_takeover_active"):
                    # Bug Fix: Handle human takeover flow by notifying user instead of silent discard
                    reply_text = FlowManager(biz, {}).get_response("HUMAN_TAKEOVER", biz["name"])
                    await send(biz["tg_bot_token"], chat_id, reply_text)
                    await queue_manager.complete(task["id"])
                    continue

                # Production bug fix: Handle greeting before fetching/creating order
                # Rule 4: If no active order and user says greeting, start Welcome Flow.
                is_greeting = ai_parser.detect_greeting(user_text)
                
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
                    # Bug Fix: Ensure transition to CANCELLED is valid before creating new order
                    try:
                        await order_service.update_status(order["id"], "CANCELLED", "bot", "Order reset by user")
                    except ValueError:
                        logging.warning(f"Could not transition order {order['id']} to CANCELLED during reset, proceeding anyway.")
                    
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    flow = FlowManager(biz, order["extracted_data"])
                    user_text = "Hello" # Trigger greeting
                    status_key = "CONVERSATION_RESET" # Set status_key explicitly to avoid crash later

                # 2. Determine Current State
                current_state = flow.get_current_state()

                # Batch 5: malformed queue payloads must not reach the AI or overwrite data.
                if not has_meaningful_text(user_text) or len(user_text) > 4000:
                    await send(biz["tg_bot_token"], chat_id, flow.get_response(current_state, biz["name"]))
                    await queue_manager.complete(task["id"])
                    continue
                
                # 3. Handle Required Fields (Rule 3: Priority Bypass AI Extraction)
                extracted_data = {}
                intent = "ORDER"
                
                if current_state in ["ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP"]:
                    # Bug Fix: Check for exit intents (CANCEL, HUMAN) before trapping in field collection
                    # This ensures users have a recovery path.
                    menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                    menu = make_json_safe([dict(m) for m in menu_rows])
                    
                    ai_context = {
                        "shop_name": biz["name"],
                        "previous_data": order.get("extracted_data", {}),
                        "requirements_text": biz.get("requirements_text")
                    }
                    extracted_data = await ai_parser.parse_message(user_text, ai_context, menu, current_state)
                    intent = extracted_data.get("intent", "ORDER")
                    
                    # BUG-21: Expand exemption list to include MENU_QUERY and VIEW_SUMMARY
                    if intent not in ["CANCEL", "HUMAN_TAKEOVER", "GREETING", "MENU_QUERY", "VIEW_SUMMARY"]:
                        # If not an exit intent, treat as field input
                        field_map = {
                            "ASK_NAME": "customer_name",
                            "ASK_PHONE": "phone_no",
                            "ASK_ADDRESS": "address",
                            "ASK_TOWNSHIP": "township"
                        }
                        field_name = field_map[current_state]
                        
                        # BUG-01, BUG-04, BUG-06, BUG-10: Apply validation
                        from app.services.validation_service import ValidationService
                        valid = False
                        normalized_val = user_text
                        
                        if field_name == "customer_name":
                            valid, normalized_val = ValidationService.validate_name(user_text)
                        elif field_name == "phone_no":
                            valid, normalized_val = ValidationService.validate_phone(user_text)
                        elif field_name == "address":
                            valid, normalized_val = ValidationService.validate_address(user_text)
                        elif field_name == "township":
                            # BUG-10: Validate against supported townships if configured
                            supported = biz.get("supported_townships")
                            if isinstance(supported, str):
                                try: supported = json.loads(supported)
                                except: supported = None
                            valid, normalized_val = ValidationService.validate_township(user_text, supported)
                        
                        if valid:
                            # BUG-23: Duplicate detection. Reject if identical to previously collected field.
                            is_duplicate = False
                            for prev_field in ["customer_name", "phone_no", "address", "township"]:
                                if prev_field != field_name and order["extracted_data"].get(prev_field) == normalized_val:
                                    is_duplicate = True
                                    break
                            
                            if not is_duplicate:
                                extracted_data = {field_name: normalized_val, "intent": "ORDER"}
                            else:
                                logging.warning(f"Duplicate field detection: {field_name} matches {normalized_val}")
                                extracted_data = {"intent": "ORDER"}
                        else:
                            # If invalid, we don't update the field, effectively re-asking
                            extracted_data = {"intent": "ORDER"}
                        
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
                    extracted_data = await ai_parser.parse_message(user_text, ai_context, menu, current_state)
                    
                    # BUG-31: Validate AI-extracted fields even in normal extraction path
                    from app.services.validation_service import ValidationService
                    for field in ["customer_name", "phone_no", "address", "township"]:
                        if extracted_data.get(field):
                            valid = False
                            if field == "customer_name": valid, _ = ValidationService.validate_name(extracted_data[field])
                            elif field == "phone_no": valid, _ = ValidationService.validate_phone(extracted_data[field])
                            elif field == "address": valid, _ = ValidationService.validate_address(extracted_data[field])
                            elif field == "township": valid, _ = ValidationService.validate_township(extracted_data[field])
                            
                            if not valid:
                                del extracted_data[field]

                    intent = extracted_data.get("intent", "ORDER")

                # 4. Merge Data & Update Order
                new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
                
                # BUG-27: Retry/Attempt Counter for loop detection
                new_state = FlowManager(biz, new_extracted_data).get_current_state()
                if new_state == current_state and intent not in ["GREETING", "MENU_QUERY", "VIEW_SUMMARY", "HUMAN_TAKEOVER", "CANCEL"]:
                    new_extracted_data["retry_count"] = new_extracted_data.get("retry_count", 0) + 1
                    if new_extracted_data["retry_count"] >= 3:
                        intent = "HUMAN_TAKEOVER"
                else:
                    new_extracted_data["retry_count"] = 0

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
                        # Batch 4: aggregate by resolved product ID so duplicate items cannot
                        # bypass the stock check or deduct the same stock twice.
                        deductions_by_product = {}
                        menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                        menu = make_json_safe([dict(m) for m in menu_rows])
                        
                        for item in new_extracted_data.get("items", []):
                            p_name = item.get("name")
                            try:
                                qty = float(item.get("qty", 0))
                            except (TypeError, ValueError):
                                qty = 0
                            if not p_name or qty <= 0:
                                all_stock_available = False
                                status_key = "OUT_OF_STOCK"
                                reply_context = {"product_name": p_name or "", "available_stock": 0}
                                break

                            attributes = {
                                "size": item.get("size"),
                                "color": item.get("color"),
                                "sugar_level": item.get("sugar_level"),
                                "ice_level": item.get("ice_level")
                            }
                            attributes = {k: v for k, v in attributes.items() if v}

                            # Variant attributes are mandatory whenever the order contains them;
                            # never fall back to the parent product by name alone.
                            if attributes:
                                p = await product_repo.get_product_variant(p_name, attributes)
                            else:
                                p = await product_repo.get_product_by_name(p_name)

                            if not p:
                                all_stock_available = False
                                status_key = "OUT_OF_STOCK"
                                reply_context = {"product_name": p_name, "available_stock": 0}
                                break

                            deductions_by_product[p["id"]] = deductions_by_product.get(p["id"], 0) + qty

                            if p["stock"] < deductions_by_product[p["id"]]:
                                all_stock_available = False
                                status_key = "OUT_OF_STOCK"
                                reply_context = {
                                    "product_name": p_name,
                                    "available_stock": p["stock"]
                                }
                                break
                        
                        if all_stock_available:
                            deductions = list(deductions_by_product.items())
                            new_extracted_data["inventory_reservations"] = [
                                {"product_id": product_id, "qty": quantity}
                                for product_id, quantity in deductions_by_product.items()
                            ]
                            from app.services.id_generator import generate_order_number
                            order_num = await generate_order_number(pool)
                            new_extracted_data["is_finalized"] = True
                            new_extracted_data["order_number"] = order_num

                            # Inventory, order metadata, status, and audit are committed atomically.
                            finalized = await order_repo.finalize_order_with_inventory(
                                order["id"], new_extracted_data, order_num, deductions
                            )
                            if not finalized:
                                status_key = "OUT_OF_STOCK"
                                reply_context = {"product_name": "", "available_stock": 0}
                            else:
                                # Preserve the existing service hook; same-status is a no-op after
                                # the atomic helper has committed the COMPLETED state.
                                await order_service.update_status(
                                    order["id"], "COMPLETED", "bot", f"Order confirmed: {order_num}"
                                )
                                reply_context["order_id"] = order_num
                        if not all_stock_available or status_key == "OUT_OF_STOCK":
                            await order_service.update_status(order["id"], status_key, "bot", f"Failed: {status_key}")

                elif status_key == "ORDER_CANCELLED":
                    await order_service.update_status(order["id"], "CANCELLED", "bot", "Cancelled by user")
                elif status_key == "HUMAN_TAKEOVER":
                    await merchant_repo.set_human_takeover(True)
                    await audit_repo.log_event(
                        event_type="HUMAN_TAKEOVER_START",
                        actor_source="bot",
                        description="User requested human",
                        order_id=order["id"],
                    )

                # 6. Generate & Send Response
                if status_key == "ORDER_SUMMARY":
                    menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                    menu = make_json_safe([dict(m) for m in menu_rows])
                    summary = []
                    total = 0
                    for item in new_extracted_data.get("items", []):
                        p_name = item.get("name")
                        qty = item.get("qty", 0)
                        normalized_name = str(p_name or "").strip().casefold()
                        price = next((p["price"] for p in menu if str(p.get("name", "")).strip().casefold() == normalized_name), 0)
                        if price == 0 and not any(str(p.get("name", "")).strip().casefold() == normalized_name for p in menu):
                            logging.warning("Summary item is missing from merchant menu: %s", p_name)
                        total += price * qty
                        summary.append(f"{p_name} x {qty} ({price * qty:.2f})")
                    
                    # BUG-08: HTML Escape user fields
                    from app.services.validation_service import ValidationService
                    reply_text = flow.get_response(
                        status_key, biz["name"],
                        order_summary_details="\n".join(summary), # items are from menu, but details might need escaping if user-provided
                        total_price=f"{total:.2f}",
                        customer_name=ValidationService.escape_html(new_extracted_data.get("customer_name", "N/A")),
                        phone_no=ValidationService.escape_html(new_extracted_data.get("phone_no", "N/A")),
                        address=ValidationService.escape_html(new_extracted_data.get("address", "N/A")),
                        payment_method=ValidationService.escape_html(new_extracted_data.get("payment_method", "N/A"))
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
                await safely_fail(queue_manager, task["id"], str(e))
            await asyncio.sleep(2)
        
        await asyncio.sleep(0.1)
