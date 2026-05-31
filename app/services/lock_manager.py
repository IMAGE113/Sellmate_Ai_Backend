import asyncio
import logging
from datetime import datetime, timedelta
from app.db.database import BaseRepository

class LockRepository(BaseRepository):
    async def acquire_lock(self, chat_id: int, timeout_seconds: int = 30) -> bool:
        expires_at = datetime.now() + timedelta(seconds=timeout_seconds)
        query = """
            INSERT INTO conversation_locks (shop_id, chat_id, expires_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (shop_id, chat_id) 
            DO UPDATE SET expires_at = $3, locked_at = NOW()
            WHERE conversation_locks.expires_at < NOW()
            RETURNING TRUE
        """
        try:
            row = await self.fetch_one(query, self.shop_id, chat_id, expires_at)
            return bool(row)
        except Exception as e:
            logging.error(f"Lock acquisition error: {e}")
            return False

    async def release_lock(self, chat_id: int):
        query = "DELETE FROM conversation_locks WHERE shop_id = $1 AND chat_id = $2"
        await self.execute(query, self.shop_id, chat_id)

    async def cleanup_expired_locks(self):
        query = "DELETE FROM conversation_locks WHERE expires_at < NOW()"
        await self.execute(query)

class LockManager:
    def __init__(self, lock_repo: LockRepository):
        self.lock_repo = lock_repo

    async def acquire(self, chat_id: int, timeout: int = 30) -> bool:
        return await self.lock_repo.acquire_lock(chat_id, timeout)

    async def release(self, chat_id: int):
        await self.lock_repo.release_lock(chat_id)
