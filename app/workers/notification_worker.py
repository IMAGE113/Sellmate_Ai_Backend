import asyncio
import logging
from app.db.database import get_db_pool

async def run_notification_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate Notification Worker started with Exponential Backoff...")

    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT n.*, b.tg_bot_token
                    FROM notifications n
                    JOIN businesses b ON n.business_id = b.id
                    WHERE n.status IN ('PENDING', 'RETRYING')
                    AND n.retry_count < 5
                    AND (
                        n.updated_at IS NULL
                        OR n.updated_at < NOW() - (POWER(2, n.retry_count) * INTERVAL '1 minute')
                    )
                    LIMIT 10
                """)

                for row in rows:
                    try:
                        success = await send_telegram_message(
                            row["tg_bot_token"],
                            row["admin_chat_id"],
                            row["message"]
                        )

                        if success:
                            await conn.execute("""
                                UPDATE notifications
                                SET status = 'SENT',
                                    updated_at = NOW()
                                WHERE id = $1
                            """, row["id"])

                        else:
                            await conn.execute("""
                                UPDATE notifications
                                SET status = 'RETRYING',
                                    retry_count = retry_count + 1,
                                    updated_at = NOW()
                                WHERE id = $1
                            """, row["id"])

                    except Exception as e:
                        logging.error(
                            f"Error sending notification {row['id']}: {e}"
                        )

                        await conn.execute("""
                            UPDATE notifications
                            SET status = 'RETRYING',
                                retry_count = retry_count + 1,
                                updated_at = NOW()
                            WHERE id = $1
                        """, row["id"])

            await asyncio.sleep(10)

        except Exception as e:
            logging.error(f"Notification worker error: {e}")
            await asyncio.sleep(30)


async def send_telegram_message(token, chat_id, text):
    logging.info(f"Sending Telegram message to {chat_id}: {text}")
    return True