from app.db.database import BaseRepository

class IdempotencyRepository(BaseRepository):
    async def is_processed(self, update_id: int) -> bool:
        query = "SELECT 1 FROM processed_webhooks WHERE update_id = $1"
        row = await self.fetch_one(query, update_id)
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
            ON CONFLICT (update_id) DO NOTHING 
            RETURNING update_id
        """
        row = await self.fetch_one(query, update_id, self.shop_id)
        return row is None

class IdempotencyService:
    def __init__(self, idempotency_repo: IdempotencyRepository):
        self.idempotency_repo = idempotency_repo

    async def check_and_mark(self, update_id: int) -> bool:
        """Returns True if the update was already processed."""
        return await self.idempotency_repo.atomic_check_and_mark(update_id)
