from app.db.database import BaseRepository

class IdempotencyRepository(BaseRepository):
    async def is_processed(self, update_id: int) -> bool:
        query = "SELECT 1 FROM processed_webhooks WHERE update_id = $1 AND shop_id = $2"
        row = await self.fetch_one(query, update_id, self.shop_id)
        return bool(row)

    async def mark_as_processed(self, update_id: int):
        query = "INSERT INTO processed_webhooks (update_id, shop_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"
        await self.execute(query, update_id, self.shop_id)

    async def atomic_check_and_mark(self, update_id: int) -> bool:
        """
        Returns True if the update was already processed (conflict occurred).
        Returns False if the update was new and marked successfully.
        """
        query = """
            INSERT INTO processed_webhooks (update_id, shop_id)
            VALUES ($1, $2)
            ON CONFLICT (shop_id, update_id) DO NOTHING
            RETURNING update_id
        """
        row = await self.fetch_one(query, update_id, self.shop_id)
        if row is not None:
            return False

        # Reclaim a claim left behind by a crashed webhook process.
        reclaim_query = """
            UPDATE processed_webhooks
            SET processed_at = NOW()
            WHERE shop_id = $1
              AND update_id = $2
              AND processed_at < NOW() - INTERVAL '10 minutes'
            RETURNING update_id
        """
        reclaimed = await self.fetch_one(reclaim_query, self.shop_id, update_id)
        return reclaimed is None

    async def release_claim(self, update_id: int):
        await self.execute(
            "DELETE FROM processed_webhooks WHERE shop_id = $1 AND update_id = $2",
            self.shop_id,
            update_id,
        )

class IdempotencyService:
    def __init__(self, idempotency_repo: IdempotencyRepository):
        self.idempotency_repo = idempotency_repo

    async def check_and_mark(self, update_id: int) -> bool:
        """Returns True if the update is already claimed or processed."""
        return await self.idempotency_repo.atomic_check_and_mark(update_id)

    async def release_claim(self, update_id: int):
        await self.idempotency_repo.release_claim(update_id)
