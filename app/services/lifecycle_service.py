from typing import Optional
from app.db.database import BaseRepository, MerchantRepository
from app.core.errors import WorkflowError

class MerchantSuspendedError(WorkflowError):
    """Raised when an operation is attempted for a suspended merchant."""
    pass

class LifecycleRepository(BaseRepository):
    async def get_status(self, shop_id: str) -> str:
        query = "SELECT status FROM businesses WHERE shop_id = $1"
        row = await self.fetch_one(query, shop_id)
        return row['status'] if row else 'ARCHIVED'

    async def update_status(self, shop_id: str, new_status: str):
        query = "UPDATE businesses SET status = $1, updated_at = NOW() WHERE shop_id = $2"
        await self.execute(query, new_status, shop_id)

class LifecycleService:
    def __init__(self, repo: LifecycleRepository):
        self.repo = repo

    async def validate_active(self, shop_id: str):
        """Global check for merchant activity. Stop everything if suspended."""
        status = await self.repo.get_status(shop_id)
        if status == 'SUSPENDED':
            raise MerchantSuspendedError(f"Merchant {shop_id} is suspended. All processing halted.")
        if status == 'ARCHIVED':
            raise MerchantSuspendedError(f"Merchant {shop_id} is archived.")

    async def suspend_merchant(self, shop_id: str):
        await self.repo.update_status(shop_id, 'SUSPENDED')
        # Log this significant event
        
    async def activate_merchant(self, shop_id: str):
        await self.repo.update_status(shop_id, 'ACTIVE')

    async def archive_merchant(self, shop_id: str):
        """Soft delete enforcement."""
        await self.repo.update_status(shop_id, 'ARCHIVED')
