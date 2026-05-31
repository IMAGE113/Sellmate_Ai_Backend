import asyncio
import logging
import json
from app.db.database import get_db_pool, OrderRepository, MerchantRepository, AuditRepository
from app.services.ai import ai
from app.services.order_service import OrderService
from app.workflow.flow_manager import FlowManager
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager

async def run_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate AI Multi-tenant Workflow Worker started...")

    while True:
        try:
            async with pool.acquire() as conn:
                # 1. Fetch pending task
                task = await conn.fetchrow("""
                UPDATE task_queue SET status='processing'
                WHERE id = (
                    SELECT id FROM task_queue WHERE status='pending'
                    ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
                ) RETURNING * """)

                if not task:
                    await asyncio.sleep(1)
                    continue

                shop_id = task["shop_id"]
                chat_id = task["chat_id"]
                
                # 2. Acquire Conversation Lock
                lock_repo = LockRepository(pool, shop_id)
                lock_manager = LockManager(lock_repo)
                if not await lock_manager.acquire(chat_id):
                    logging.info(f"Could not acquire lock for {shop_id}:{chat_id}, retrying later")
                    await conn.execute("UPDATE task_queue SET status='pending' WHERE id=$1", task["id"])
                    continue

                try:
                    # Repositories
                    order_repo = OrderRepository(pool, shop_id)
                    merchant_repo = MerchantRepository(pool, shop_id)
                    audit_repo = AuditRepository(pool, shop_id)
                    order_service = OrderService(order_repo, audit_repo)

                    # 3. Fetch business info
                    biz = await merchant_repo.get_merchant_by_shop_id()
                    if not biz:
                        await conn.execute("DELETE FROM task_queue WHERE id=$1", task["id"])
                        continue

                    # 4. Human Takeover Check
                    if biz.get("is_human_takeover_active"):
                        logging.info(f"Human takeover active for {shop_id}, skipping AI")
                        await conn.execute("DELETE FROM task_queue WHERE id=$1", task["id"])
                        continue

                    # 5. Fetch/Create Order
                    order = await order_service.get_or_create_active_order(chat_id, biz["id"])
                    
                    # 6. Fetch Menu
                    menu_rows = await conn.fetch("SELECT name, price, stock FROM products WHERE shop_id=$1", shop_id)
                    menu = [dict(m) for m in menu_rows]

                    # 7. AI Extraction
                    extracted_json = await ai.extract_data(
                        task["user_text"], 
                        biz["name"], 
                        menu, 
                        order.get("extracted_data", {}),
                        biz.get("requirements_text")
                    )
                    extracted_data = json.loads(extracted_json)
                    
                    # 8. Merge Data & Update Order
                    new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
                    intent = extracted_data.get("intent", "ORDER")
                    
                    # Update order in DB
                    await conn.execute(
                        "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
                        json.dumps(new_extracted_data), order["id"]
                    )

                    # 9. Workflow Management
                    flow = FlowManager(biz, new_extracted_data)
                    status_key = flow.get_next_step(intent)
                    
                    # 10. Handle Intent/Status Actions
                    if status_key == "HUMAN_TAKEOVER":
                        await conn.execute("UPDATE businesses SET is_human_takeover_active = TRUE WHERE id = $1", biz["id"])
                        await audit_repo.log_event("HUMAN_TAKEOVER_START", "bot", "User requested human", order["id"])
                    
                    # 11. Generate Response
                    reply_text = flow.get_response(status_key, biz["name"])
                    
                    # 12. Send Response
                    await send(biz["tg_bot_token"], chat_id, reply_text)
                    
                    # 13. Audit Log
                    await audit_repo.log_event("BOT_REPLY", "bot", f"Replied with {status_key}", order["id"], {"reply": reply_text})

                    # 14. Mark task as completed
                    await conn.execute("DELETE FROM task_queue WHERE id=$1", task["id"])

                finally:
                    # Always release the lock
                    await lock_manager.release(chat_id)

        except Exception as e:
            logging.error(f"🔥 Worker Error: {str(e)}", exc_info=True)
            await asyncio.sleep(2)
        
        await asyncio.sleep(0.1)
