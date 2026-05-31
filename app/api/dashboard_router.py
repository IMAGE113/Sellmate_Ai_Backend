from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db_pool, DashboardRepository
from app.services.dashboard_service import DashboardService
# Assuming an auth middleware exists that provides current_merchant
from app.api.auth_router import get_current_merchant 

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/overview")
async def get_dashboard_overview(current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    
    return await dashboard_service.get_overview()

@router.get("/orders")
async def get_orders(limit: int = 10, offset: int = 0, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    return await dashboard_repo.get_recent_orders(limit, offset)
