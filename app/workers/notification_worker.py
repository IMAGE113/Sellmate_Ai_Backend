import asyncio
import logging
import httpx
from app.db.database import get_db_pool

async def run_notification_worker():
    pool = await get_db_pool()
    logging.info("🚀 SellMate Notification Worker started with Exponential Backoff...")

    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    WITH candidates AS (
                        SELECT n.id
                        FROM notifications n
                        WHERE n.status IN ('PENDING', 'RETRYING')
                        AND n.retry_count < 5
                        AND (
                            n.updated_at IS NULL
                            OR n.updated_at < NOW() - (POWER(2, n.retry_count) * INTERVAL '1 minute')
                        )
                        ORDER BY n.created_at ASC
                        LIMIT 10
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE notifications n
                    SET updated_at = NOW()
                    FROM candidates c
                    JOIN notifications source_n ON source_n.id = c.id
                    JOIN businesses b ON source_n.business_id = b.id
                    WHERE n.id = c.id
                    RETURNING n.*, b.tg_bot_token
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
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={"chat_id": chat_id, "text": str(text or "")[:4096]},
            )
        if response.status_code != 200:
            logging.error("Telegram notification failed with status %s", response.status_code)
            return False
        body = response.json()
        return bool(body.get("ok"))
    except Exception:
        logging.exception("Telegram notification request failed")
        return False
