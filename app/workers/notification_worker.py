import asyncio
import logging
import math
from datetime import datetime, timedelta
from app.db.database import get_db_pool

async def run_notification_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate Notification Worker started with Exponential Backoff...")
    
    while True:
        try:
            async with pool.acquire() as conn:
                # Fetch notifications that are pending or ready for retry
                # Exponential backoff: 2^retries * 60 seconds
                rows = await conn.fetch("""
                    SELECT n.*, b.tg_bot_token 
                    FROM notifications n
                    JOIN businesses b ON n.business_id = b.id
                    WHERE n.status IN ('PENDING', 'RETRYING') 
                    AND n.retries < 5
                    AND (n.last_attempt IS NULL OR n.last_attempt < NOW() - (POWER(2, n.retries) * INTERVAL '1 minute'))
                    LIMIT 10
                """)
                
                for row in rows:
                    try:
                        success = await send_telegram_message(row['tg_bot_token'], row['admin_chat_id'], row['message'])
                        
                        if success:
                            await conn.execute("UPDATE notifications SET status = 'SENT', last_attempt = NOW() WHERE id = $1", row['id'])
                        else:
                            await conn.execute("UPDATE notifications SET status = 'RETRYING', retries = retries + 1, last_attempt = NOW() WHERE id = $1", row['id'])
                    except Exception as e:
                        logging.error(f"Error sending notification {row['id']}: {e}")
                        await conn.execute("UPDATE notifications SET status = 'RETRYING', retries = retries + 1, last_attempt = NOW() WHERE id = $1", row['id'])
            
            await asyncio.sleep(10) 
        except Exception as e:
            logging.error(f"Notification worker error: {e}")
            await asyncio.sleep(30)

async def send_telegram_message(token, chat_id, text):
    # Mock implementation of telegram send
    logging.info(f"Sending Telegram message to {chat_id}: {text}")
    return True
