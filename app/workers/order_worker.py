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
# [SAFE UTILITIES]
# ==========================================
def make_json_safe(data: Any) -> Any:
    """ Recursively convert Decimal values to float so the payload is JSON safe. """
    if isinstance(data, list):
        return [make_json_safe(item) for item in data]
    if isinstance(data, dict):
        return {k: make_json_safe(v) for k, v in data.items()}
    if isinstance(data, Decimal):
        return float(data)
    return data

def force_dict(data: Any) -> dict:
    """ Coerce DB string/None values into a dict so downstream code is safe. """
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


# Inline keyboard offered to the customer at the confirmation gate (H3).
def _confirm_keyboard() -> dict:
    return {
        "inline_keyboard": [[
            {"text": "\u2705 Confirm", "callback_data": "confirm order"},
            {"text": "\u274C Cancel", "callback_data": "cancel order"},
        ]]
    }


def _price_for(menu, product_name):
    """ Look up a product price from the menu list; tolerate malformed menus. """
    try:
        for p in menu:
            if isinstance(p, dict) and p.get("name") == product_name:
                return p.get("price", 0) or 0
    except TypeError:
        return 0
    return 0


def _compute_summary(items, menu):
    """ Build the human-readable summary lines and numeric total for an order. """
    summary_lines = []
    total_price = 0.0
    for item in (items or []):
        product_name = item.get("name", "Unknown Item")
        quantity = item.get("qty", 0) or 0
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            quantity = 0
        price = float(_price_for(menu, product_name) or 0)
        item_total = price * quantity
        total_price += item_total
        summary_lines.append(f"{product_name} x {int(quantity)} ({item_total:.2f} \u1015\u103C\u102C\u1038)")
    return summary_lines, total_price
# ==========================================

async def run_worker():
    pool = await get_db_pool()
    worker_id = f"worker-{os.getpid()}"
    logging.info(f"SellMate AI Multi-tenant Workflow Worker {worker_id} started...")

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

                # 4b. Human Takeover Check
                if biz.get("is_human_takeover_active"):
                    logging.info(f"Human takeover active for {shop_id}, skipping AI")
                    await queue_manager.complete(task["id"])
                    continue

                # 5. Fetch/Create Order
                order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"])
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
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    user_text = "Hello"
                    await queue_manager.complete(task["id"])
                    continue
                elif order.get("status") in ["CANCELLED", "FAILED", "OUT_OF_STOCK"] and flow_manager_temp.get_next_step(intent="ORDER", user_text=user_text) == "NEW_ORDER_INITIATED":
                    logging.info(f"New order initiated for {shop_id}:{chat_id} after terminal state.")
                    order_raw = await order_service.get_or_create_active_order(chat_id, biz["id"], force_new=True)
                    order = dict(order_raw) if order_raw else {}
                    order["extracted_data"] = force_dict(order.get("extracted_data", {}))
                    user_text = "Hello"
                    await queue_manager.complete(task["id"])
                    continue

                # 6. Fetch Menu
                menu_rows = await merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                menu_raw = [dict(m) for m in menu_rows]
                menu = make_json_safe(menu_raw)

                # 7. AI Extraction
                extracted_json = await ai.extract_data(
                    user_text,
                    biz["name"],
                    menu,
                    order.get("extracted_data", {}),
                    biz.get("requirements_text")
                )
                extracted_data = force_dict(json.loads(extracted_json) if isinstance(extracted_json, str) else extracted_json)

                # 8. Merge Data & Update Order
                new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
                intent = extracted_data.get("intent", "ORDER")

                await order_repo.execute(
                    "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                    json.dumps(new_extracted_data), order["id"]
                )

                # 9. Workflow Management
                # FIX (M1): pass user_text so reset/intent/confirmation handling works.
                flow = FlowManager(biz, new_extracted_data)
                status_key = flow.get_next_step(intent, user_text=user_text)

                # Precompute the summary once; used by ORDER_SUMMARY, AWAITING_CONFIRMATION and finalize.
                summary_lines, total_price = _compute_summary(new_extracted_data.get("items", []), menu)
                summary_text = "\n".join(summary_lines)

                # 10. Handle non-terminal status synchronization.
                # NOTE: Only NON-critical status bookkeeping lives in this try/except.
                # Critical mutations (stock deduction + order finalize) are handled
                # separately below WITHOUT swallowing errors (H1).
                try:
                    if status_key == "HUMAN_TAKEOVER":
                        await merchant_repo.execute("UPDATE businesses SET is_human_takeover_active = TRUE WHERE id = $1", biz["id"])
                        await audit_repo.log_event("HUMAN_TAKEOVER_START", "bot", "User requested human", order["id"])
                    elif status_key in ["GREETING", "ASK_ITEMS", "ASK_QUANTITY", "ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP", "ASK_SIZE", "ASK_COLOR", "MENU_INFO"]:
                        await order_service.update_status(order["id"], "COLLECTING_INFO", "bot", f"Bot asking for: {status_key}")
                    elif status_key in ["ASK_PAYMENT_METHOD", "ASK_PAYMENT_SCREENSHOT"]:
                        await order_service.update_status(order["id"], "WAITING_PAYMENT", "bot", f"Bot asking for: {status_key}")
                    elif status_key in ["ORDER_SUMMARY", "AWAITING_CONFIRMATION"]:
                        # Mark that the summary has been presented so the next message
                        # is treated as an explicit confirm/cancel decision.
                        if not new_extracted_data.get("summary_shown"):
                            new_extracted_data["summary_shown"] = True
                            await order_repo.execute(
                                "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                                json.dumps(new_extracted_data), order["id"]
                            )
                        await order_service.update_status(order["id"], "COLLECTING_INFO", "bot", "Awaiting customer confirmation")
                    elif status_key == "PAYMENT_RECEIVED_WAITING_REVIEW":
                        if not new_extracted_data.get("payment_pending_review", False):
                            new_extracted_data["payment_pending_review"] = True
                            await order_repo.execute(
                                "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                                json.dumps(new_extracted_data), order["id"]
                            )
                            await order_service.update_status(order["id"], "PAYMENT_PENDING_REVIEW", "bot", "Payment screenshot received, waiting for review")
                    elif status_key == "OUT_OF_STOCK":
                        await order_service.update_status(order["id"], "OUT_OF_STOCK", "bot", "Order out of stock, asking customer to choose another item")
                    elif status_key == "ORDER_CANCELLED":
                        await order_service.update_status(order["id"], "CANCELLED", "bot", "Order cancelled by customer")
                    elif status_key in ["ORDER_CONFIRMED"]:
                        # Side effects handled in the dedicated finalize block below.
                        pass
                    else:
                        await order_service.update_status(order["id"], "COLLECTING_INFO", "bot", f"Bot asking for: {status_key}")
                except Exception as status_err:
                    logging.error(f"Status Synchronization Error (Non-fatal): {str(status_err)}")

                # 10b. CONFIRMATION -> FINALIZE (C2 / C3 / H1).
                # This runs only after an explicit confirmation reached ORDER_CONFIRMED.
                # Stock check + deduction + order finalize happen atomically. Any
                # failure here is FATAL: we must not tell the customer "success".
                finalize_failed = False
                if status_key == "ORDER_CONFIRMED":
                    if new_extracted_data.get("stock_deducted", False):
                        logging.info(f"Stock already deducted for order {order['id']}. Skipping duplicate finalize.")
                    else:
                        # Stock availability gate.
                        all_stock_available = True
                        priced_items = []
                        for item in new_extracted_data.get("items", []):
                            product_name = item.get("name")
                            quantity = item.get("qty", 0) or 0
                            if product_name and quantity > 0:
                                product = await product_repo.get_product_by_name(product_name)
                                if not product or product["stock"] < quantity:
                                    all_stock_available = False
                                    break
                                priced_items.append((product, quantity))

                        if not all_stock_available:
                            status_key = "OUT_OF_STOCK"
                            await order_service.update_status(order["id"], "OUT_OF_STOCK", "bot", "Order out of stock, asking customer to choose another item")
                        else:
                            customer_name = new_extracted_data.get("customer_name")
                            try:
                                # Atomic: deduct stock + write dashboard columns + COMPLETED.
                                await order_repo.finalize_order_with_stock(
                                    order["id"],
                                    customer_name,
                                    total_price,
                                    [(p["id"], q) for (p, q) in priced_items],
                                )
                                new_extracted_data["stock_deducted"] = True
                                new_extracted_data["payment_confirmed"] = True
                                await order_repo.execute(
                                    "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                                    json.dumps(new_extracted_data), order["id"]
                                )
                                await audit_repo.log_event(
                                    "ORDER_FINALIZED", "bot",
                                    "Order confirmed, stock deducted and order completed",
                                    order["id"],
                                    {"total_price": total_price, "customer_name": customer_name},
                                )
                            except Exception as finalize_err:
                                # FATAL: do NOT report success to the customer.
                                finalize_failed = True
                                logging.error(f"Order finalize FAILED for order {order['id']}: {finalize_err}", exc_info=True)
                                await audit_repo.log_event(
                                    "ORDER_FINALIZE_FAILED", "bot",
                                    f"Finalize failed: {finalize_err}", order["id"],
                                )

                # 11. Generate Response
                if finalize_failed:
                    # Never send the success script when persistence failed.
                    reply_text = flow.get_response("FALLBACK", biz["name"])
                    reply_markup = None
                elif status_key in ["ORDER_SUMMARY", "AWAITING_CONFIRMATION"]:
                    reply_text = flow.get_response(
                        "ORDER_SUMMARY",
                        biz["name"],
                        order_summary_details=summary_text,
                        total_price=f"{total_price:.2f}",
                        customer_name=new_extracted_data.get("customer_name", "N/A"),
                        phone_no=new_extracted_data.get("phone_no", "N/A"),
                        address=new_extracted_data.get("address", "N/A"),
                    )
                    reply_markup = _confirm_keyboard()
                else:
                    reply_text = flow.get_response(status_key, biz["name"])
                    reply_markup = None

                # 12. Send Response
                await send(biz["tg_bot_token"], chat_id, reply_text, reply_markup=reply_markup)

                # 13. Audit Log
                await audit_repo.log_event("BOT_REPLY", "bot", f"Replied with {status_key}", order["id"], {"reply": reply_text})

                # 14. Mark task as completed / failed
                if finalize_failed:
                    await queue_manager.fail(task["id"], "Order finalize failed", can_retry=True)
                else:
                    await queue_manager.complete(task["id"])

            finally:
                # Always release the lock
                await lock_manager.release(chat_id)

        except Exception as e:
            logging.error(f"Worker Error: {str(e)}", exc_info=True)
            if 'task' in locals() and task:
                await queue_manager.fail(task["id"], str(e))
            await asyncio.sleep(2)

        await asyncio.sleep(0.1)
