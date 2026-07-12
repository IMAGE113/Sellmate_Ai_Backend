import asyncio
import logging
import json
import os
from decimal import Decimal
from typing import Any
from app.db.database import get_db_pool, OrderRepository, MerchantRepository, AuditRepository, ProductRepository
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
                product_repo = ProductRepository(pool, shop_id)
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

                # Check for reset commands or new order initiation
                flow_manager_temp = FlowManager(biz, order["extracted_data"])
                if flow_manager_temp._is_reset_command(user_text):
                    logging.info(f"Reset command detected for {shop_id}:{chat_id}. Resetting order.")
                    await order_service.update_status(order["id"], "CANCELLED", "bot", "Order cancelled by user reset command")
                    await order_repo.execute(
                        "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                        json.dumps({}), order["id"]
                    )
                    # Create a new order for the next interaction
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    # Override user_text to trigger a fresh greeting
                    user_text = "Hello"
                    # Skip further processing for this cycle as a new order has been initiated
                    await queue_manager.complete(task["id"])
                    continue
                elif order.get("status") in ["CANCELLED", "FAILED", "OUT_OF_STOCK"] and flow_manager_temp.get_next_step(intent="ORDER", user_text=user_text) == "NEW_ORDER_INITIATED":
                    logging.info(f"New order initiated for {shop_id}:{chat_id} after terminal state.")
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    user_text = "Hello" # Trigger a fresh greeting for the new order
                    # Skip further processing for this cycle as a new order has been initiated
                    await queue_manager.complete(task["id"])
                    continue
                
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
                
                # 10. Handle Intent/Status Actions and Synchronize workflow status with order status
                try:
                    if status_key == "HUMAN_TAKEOVER":
                        await merchant_repo.execute("UPDATE businesses SET is_human_takeover_active = TRUE WHERE id = $1", biz["id"])
                        await audit_repo.log_event("HUMAN_TAKEOVER_START", "bot", "User requested human", order["id"])
                    elif status_key in ["GREETING", "ASK_ITEMS", "ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP", "ASK_SIZE", "ASK_COLOR", "MENU_INFO"]:
                        await order_service.update_status(order["id"], "COLLECTING_INFO", "bot", f"Bot asking for: {status_key}")
                    elif status_key in ["ASK_PAYMENT_METHOD", "ASK_PAYMENT_SCREENSHOT"]:
                        await order_service.update_status(order["id"], "WAITING_PAYMENT", "bot", f"Bot asking for: {status_key}")
                    elif status_key == "ORDER_CONFIRMED":
                        # Only finalize if the customer explicitly confirmed
                        if intent == "CONFIRM_ORDER":
                            # Duplicate protection for stock deduction and finalization
                            if not new_extracted_data.get("is_finalized", False):
                                all_stock_available = True
                                items_to_deduct = []
                                
                                for item in new_extracted_data.get("items", []):
                                    product_name = item.get("name")
                                    quantity = item.get("qty", 0)
                                    if product_name and quantity > 0:
                                        parent_product = await product_repo.get_product_by_name(product_name)
                                        if not parent_product:
                                            all_stock_available = False
                                            break
                                        
                                        # Check for variants (BUG-001 transplant)
                                        variants = await product_repo.get_variants_for_product(parent_product["id"])
                                        if variants:
                                            # Try attribute match first (Stable logic)
                                            attributes = {k: v for k, v in item.items() if k in ["size", "color", "sugar_level", "ice_level"]}
                                            product = None
                                            if attributes:
                                                product = await product_repo.get_product_variant(parent_product["id"], attributes)
                                            
                                            # If no attribute match, try keyword match in details (BUG-001 logic)
                                            if not product:
                                                details = item.get("details", "").lower()
                                                for v in variants:
                                                    if v["name"].lower() in details:
                                                        product = v
                                                        break
                                            
                                            if product:
                                                if product["stock"] < quantity:
                                                    all_stock_available = False
                                                    status_key = "OUT_OF_STOCK"
                                                    break
                                                items_to_deduct.append((product["id"], quantity))
                                            else:
                                                # Product has variants but no match found (BUG-001 fix)
                                                all_stock_available = False
                                                status_key = "INVALID_VARIANT"
                                                available_names = ", ".join([v["name"] for v in variants])
                                                reply_context = {"product_name": product_name, "available_variants": available_names}
                                                break
                                        else:
                                            # Product has NO variants. Use parent stock directly.
                                            product = parent_product
                                            if not product or product["stock"] < quantity:
                                                all_stock_available = False
                                                status_key = "OUT_OF_STOCK"
                                                break
                                            items_to_deduct.append((product["id"], quantity))
                                
                                if all_stock_available:
                                    # Calculate total price based on menu prices
                                    total_price = 0
                                    for item in new_extracted_data.get("items", []):
                                        product_name = item.get("name")
                                        quantity = item.get("qty", 0)
                                        price = next((p["price"] for p in menu if p["name"] == product_name), 0)
                                        total_price += float(price) * quantity

                                    # Deduct Stock
                                    for product_id, quantity in items_to_deduct:
                                        await product_repo.update_product_stock(product_id, quantity)
                                    
                                    # Finalize Order and Sync Dashboard
                                    new_extracted_data["is_finalized"] = True
                                    customer_name = new_extracted_data.get("customer_name") or order.get("customer_name")
                                    
                                    await order_repo.execute(
                                        """UPDATE orders SET 
                                            extracted_data = $1, 
                                            customer_name = $2,
                                            total_price = $3,
                                            status = 'COMPLETED',
                                            updated_at = CURRENT_TIMESTAMP 
                                        WHERE id = $4""",
                                        json.dumps(new_extracted_data), customer_name, Decimal(str(total_price)), order["id"]
                                    )
                                    
                                    await audit_repo.log_event("ORDER_FINALIZED", "bot", "Order confirmed, stock deducted, and finalized", order["id"], {"total_price": total_price})
                                    status_key = "ORDER_CONFIRMED" # Final success message
                                else:
                                    status_key = "OUT_OF_STOCK"
                                    await order_service.update_status(order["id"], "OUT_OF_STOCK", "bot", "Insufficient stock during confirmation")
                            else:
                                logging.info(f"Order {order['id']} already finalized. Skipping duplicate logic.")
                        else:
                            # If not explicitly confirmed, show summary
                            status_key = "ORDER_SUMMARY"
                    elif status_key == "OUT_OF_STOCK":
                        # As per Fix 5, do not cancel immediately. FlowManager will handle the response.
                        await order_service.update_status(order["id"], "OUT_OF_STOCK", "bot", "Order out of stock, asking customer to choose another item")
                    elif status_key == "PAYMENT_RECEIVED_WAITING_REVIEW":
                        # Duplicate protection for payment pending review
                        if not new_extracted_data.get("payment_pending_review", False):
                            new_extracted_data["payment_pending_review"] = True
                            await order_repo.execute(
                                "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                                json.dumps(new_extracted_data), order["id"]
                            )
                            await order_service.update_status(order["id"], "PAYMENT_PENDING_REVIEW", "bot", "Payment screenshot received, waiting for review")
                        else:
                            logging.info(f"Payment already pending review for order {order['id']}. Skipping duplicate status update.")
                    elif status_key == "ORDER_READY_TO_SHIP":
                        await order_service.update_status(order["id"], "READY_TO_SHIP", "bot", "Order ready to ship")
                    elif status_key == "ORDER_COMPLETED":
                        await order_service.update_status(order["id"], "COMPLETED", "bot", "Order completed")
                    elif status_key == "ORDER_CANCELLED":
                        await order_service.update_status(order["id"], "CANCELLED", "bot", "Order cancelled by bot")
                    else:
                        # For any other status_key that doesn't represent a final order state, keep it as COLLECTING_INFO
                        await order_service.update_status(order["id"], "COLLECTING_INFO", "bot", f"Bot asking for: {status_key}")
                except Exception as status_err:
                    logging.error(f"⚠️ Status Synchronization Error (Non-fatal): {str(status_err)}")

                # 11. Generate Response
                reply_text = ""
                if status_key == "INVALID_VARIANT" and 'reply_context' in locals():
                    # Format with extra context (BUG-001 transplant)
                    from app.core.scripts import get_script
                    reply_text = get_script(status_key, **reply_context)
                elif status_key == "ORDER_SUMMARY":
                    # Generate order summary
                    order_summary_details = []
                    total_price = 0
                    for item in new_extracted_data.get("items", []):
                        product_name = item.get("name", "Unknown Item")
                        quantity = item.get("qty", 0)
                        price = next((p["price"] for p in menu if p["name"] == product_name), 0)
                        item_total = price * quantity
                        total_price += item_total
                        order_summary_details.append(f"{product_name} x {quantity} ({item_total:.2f} ကျပ်)")
                    
                    reply_text = flow.get_response(
                        status_key,
                        biz["name"],
                        order_summary_details="\n".join(order_summary_details),
                        total_price=f"{total_price:.2f}",
                        customer_name=new_extracted_data.get("customer_name", "N/A"),
                        phone_no=new_extracted_data.get("phone_no", "N/A"),
                        address=new_extracted_data.get("address", "N/A"),
                        payment_method=new_extracted_data.get("payment_method", "N/A")
                    )
                else:
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