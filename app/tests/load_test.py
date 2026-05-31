import asyncio
import time
import uuid
import random
from app.db.database import get_db_pool
from app.schemas.queue import QueuePayloadSchema

async def simulate_merchant_activity(shop_id: str, num_messages: int):
    pool = await get_db_pool()
    correlation_id = uuid.uuid4()
    
    start_time = time.time()
    success_count = 0
    
    for i in range(num_messages):
        try:
            payload = QueuePayloadSchema(
                shop_id=shop_id,
                chat_id=random.randint(1000, 9999),
                event_type="incoming_message",
                correlation_id=correlation_id,
                data={"text": f"Test message {i}"}
            )
            
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO task_queue (shop_id, queue_name, payload, correlation_id, status) VALUES ($1, $2, $3, $4, 'pending')",
                    payload.shop_id, "message_queue", payload.model_dump_json(), payload.correlation_id
                )
            success_count += 1
        except Exception as e:
            print(f"Error: {e}")
            
    end_time = time.time()
    return success_count, end_time - start_time

async def run_load_test(num_merchants: int, msgs_per_merchant: int):
    print(f"🚀 Starting Load Test: {num_merchants} merchants, {msgs_per_merchant} msgs each")
    tasks = []
    for i in range(num_merchants):
        tasks.append(simulate_merchant_activity(f"shop_{i}", msgs_per_merchant))
    
    results = await asyncio.gather(*tasks)
    
    total_success = sum(r[0] for r in results)
    total_time = max(r[1] for r in results)
    
    print(f"✅ Load Test Complete")
    print(f"Total Success: {total_success}")
    print(f"Throughput: {total_success / total_time:.2f} msgs/sec")

# To run: asyncio.run(run_load_test(100, 10))
