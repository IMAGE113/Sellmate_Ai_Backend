import asyncio
import logging
import json
from app.db.database import get_db_pool
from app.services.ai import ai
from app.services.telegram import send

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def run_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate AI Multi-tenant Worker started...")

    while True:
        try:
            async with pool.acquire() as conn:
                # 1. Fetch pending task with row-level locking
                task = await conn.fetchrow("""
                UPDATE task_queue SET status='processing'
                WHERE id = (
                    SELECT id FROM task_queue WHERE status='pending'
                    ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                ) RETURNING * """)

                if not task:
                    await asyncio.sleep(1)
                    continue

                # 2. Fetch business info
                biz = await conn.fetchrow("SELECT id, name, tg_bot_token, category FROM businesses WHERE id=$1", task["business_id"])
                if not biz:
                    logging.error(f"Business not found for ID: {task['business_id']}")
                    await conn.execute("DELETE FROM task_queue WHERE id=$1", task["id"])
                    continue

                # 3. Fetch product menu
                menu_rows = await conn.fetch("SELECT name, price FROM products WHERE business_id=$1", task["business_id"])
                menu = [dict(m) for m in menu_rows]

                # 4. Fetch existing pending order data
                pending = await conn.fetchrow("SELECT order_data FROM pending_orders WHERE chat_id=$1 AND business_id=$2",
                                             task["chat_id"], task["business_id"])

                current_order = json.loads(pending["order_data"]) if pending else {"items": []}
                
                # 5. Process with AI
                res = await ai.process(task["user_text"], biz["name"], biz["category"], menu, current_order)
                final_data = res.get("final_order_data", {})

                # 6. Handle Confirmation vs. Pending State
                if res.get("intent") == "confirmed" and final_data.get("items"):
                    # Calculate total price
                    total_price = 0
                    for item in final_data["items"]:
                        price = next((m["price"] for m in menu if m["name"] == item["name"]), 0)
                        total_price += price * item["qty"]

                    # Insert into orders table
                    await conn.execute("""
                    INSERT INTO orders (business_id, chat_id, customer_name, phone_no, address, payment_method, items, total_price)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """, task["business_id"], task["chat_id"], final_data.get("customer_name"), final_data.get("phone_no"),
                    final_data.get("address"), final_data.get("payment_method"), json.dumps(final_data["items"]), total_price)

                    # Update or Insert Customer Info
                    await conn.execute("""
                    INSERT INTO customers (business_id, chat_id, name, phone_no, address)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (business_id, chat_id) DO UPDATE SET
                    name = EXCLUDED.name, phone_no = EXCLUDED.phone_no, address = EXCLUDED.address, updated_at = NOW()
                    """, task["business_id"], task["chat_id"], final_data.get("customer_name"), final_data.get("phone_no"), final_data.get("address"))

                    # Clear pending order
                    await conn.execute("DELETE FROM pending_orders WHERE chat_id=$1 AND business_id=$2", task["chat_id"], task["business_id"])
                else:
                    # Update pending orders
                    await conn.execute("""
                    INSERT INTO pending_orders (chat_id, business_id, order_data) VALUES ($1, $2, $3)
                    ON CONFLICT (chat_id, business_id) DO UPDATE SET order_data=$3, updated_at=NOW()
                    """, task["chat_id"], task["business_id"], json.dumps(final_data))

                # 7. Send Response back to Telegram
                markup = {
                    "inline_keyboard": [[
                        {"text": "✅ Confirm Order", "callback_data": "confirm"},
                        {"text": "🔄 Restart", "callback_data": "restart"}
                    ]]
                } if res.get("ui") == "confirm_buttons" else None
                
                await send(biz["tg_bot_token"], task["chat_id"], res.get("reply_text", "နားမလည်ပါဘူးခင်ဗျာ။"), reply_markup=markup)
                
                # 8. Mark task as completed (by deleting it from the queue)
                await conn.execute("DELETE FROM task_queue WHERE id=$1", task["id"])

        except Exception as e:
            logging.error(f"🔥 Worker Error: {str(e)}")
            await asyncio.sleep(2)
        
        await asyncio.sleep(0.1)
