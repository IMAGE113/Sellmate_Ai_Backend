from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from app.db.database import get_db_pool, BaseRepository
from app.api.auth_router import get_super_admin
from app.services.lifecycle_service import LifecycleService, LifecycleRepository

router = APIRouter(prefix="/api/ops", tags=["ops"])

class OpsRepository(BaseRepository):
    async def get_all_merchants(self, status: Optional[str] = None) -> List[dict]:
        query = "SELECT id, shop_id, name, owner_name, phone, status, created_at FROM businesses"
        if status:
            query += " WHERE status = $1"
            return await self.fetch_all(query, status)
        return await self.fetch_all(query)

    async def get_system_stats(self) -> dict:
        query = """
            SELECT 
                (SELECT COUNT(*) FROM businesses) as total_merchants,
                (SELECT COUNT(*) FROM orders) as total_orders,
                (SELECT COUNT(*) FROM task_queue WHERE status = 'pending') as pending_tasks,
                (SELECT COUNT(*) FROM task_queue WHERE status = 'failed') as failed_tasks
        """
        return await self.fetch_one(query)

    async def get_audit_logs(self, limit: int = 50) -> List[dict]:
        query = "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT $1"
        return await self.fetch_all(query, limit)

@router.get("/merchants")
async def list_merchants(status: Optional[str] = None, admin = Depends(get_super_admin)):
    pool = await get_db_pool()
    repo = OpsRepository(pool, "SYSTEM")
    return await repo.get_all_merchants(status)

@router.get("/stats")
async def system_stats(admin = Depends(get_super_admin)):
    pool = await get_db_pool()
    repo = OpsRepository(pool, "SYSTEM")
    return await repo.get_system_stats()

@router.post("/merchants/{shop_id}/suspend")
async def suspend_merchant(shop_id: str, admin = Depends(get_super_admin)):
    pool = await get_db_pool()
    lifecycle_service = LifecycleService(LifecycleRepository(pool, "SYSTEM"))
    await lifecycle_service.suspend_merchant(shop_id)
    return {"success": True, "message": f"Merchant {shop_id} suspended"}

@router.post("/merchants/{shop_id}/activate")
async def activate_merchant(shop_id: str, admin = Depends(get_super_admin)):
    pool = await get_db_pool()
    lifecycle_service = LifecycleService(LifecycleRepository(pool, "SYSTEM"))
    await lifecycle_service.activate_merchant(shop_id)
    return {"success": True, "message": f"Merchant {shop_id} activated"}

@router.get("/audit-logs")
async def get_global_audit_logs(limit: int = 50, admin = Depends(get_super_admin)):
    pool = await get_db_pool()
    repo = OpsRepository(pool, "SYSTEM")
    return await repo.get_audit_logs(limit)
