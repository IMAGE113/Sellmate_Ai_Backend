import asyncio
import logging
from app.db.database import get_db_pool

async def run_cleanup_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate Cleanup Worker started...")
    
    while True:
        try:
            async with pool.acquire() as conn:
                # 1. Cleanup expired locks
                await conn.execute("DELETE FROM conversation_locks WHERE expires_at < NOW()")
                
                # 2. Archive/Reset stale orders (inactive for > 24 hours)
                # For now, we'll just mark them as CANCELLED or a new state STALE
                await conn.execute("""
                    UPDATE orders 
                    SET status = 'CANCELLED', 
                        updated_at = NOW(),
                        timeline = timeline || jsonb_build_object(
                            'timestamp', CURRENT_TIMESTAMP,
                            'status', 'CANCELLED',
                            'actor', 'system',
                            'description', 'Order cancelled due to 24h inactivity'
                        )
                    WHERE status NOT IN ('COMPLETED', 'CANCELLED')
                    AND updated_at < NOW() - INTERVAL '24 hours'
                """)
                
            await asyncio.sleep(3600) # Run every hour
        except Exception as e:
            logging.error(f"Cleanup worker error: {e}")
            await asyncio.sleep(60)
