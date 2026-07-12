from app.db.database import BaseRepository

class IdempotencyRepository(BaseRepository):
    async def is_processed(self, update_id: int) -> bool:
        query = "SELECT 1 FROM processed_webhooks WHERE update_id = $1"
        row = await self.fetch_one(query, update_id)
        return bool(row)

    async def mark_as_processed(self, update_id: int):
        query = "INSERT INTO processed_webhooks (update_id, shop_id) VALUES ($1, $2) ON CONFLICT DO NOTHING"
        await self.execute(query, update_id, self.shop_id)

class IdempotencyService:
    def __init__(self, idempotency_repo: IdempotencyRepository):
        self.idempotency_repo = idempotency_repo

    async def check_and_mark(self, update_id: int) -> bool:
        """Returns True if the update was already processed."""
        if await self.idempotency_repo.is_processed(update_id):
            return True
        await self.idempotency_repo.mark_as_processed(update_id)
        return False
