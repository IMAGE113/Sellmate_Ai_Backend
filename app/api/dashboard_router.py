from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db_pool
from app.services.dashboard_service import DashboardRepository
from app.services.dashboard_service import DashboardService
# Assuming an auth middleware exists that provides current_merchant
from app.api.auth_router import get_current_merchant 

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/overview")
async def get_dashboard_overview(current_merchant = Depends(get_current_merchant)):
    """
    Get overview statistics for the current merchant.
    Strictly scoped by shop_id from JWT.
    """
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    # Repository pattern ensures shop_id isolation
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    
    return await dashboard_service.get_overview()

@router.get("/orders")
async def get_orders(limit: int = 10, offset: int = 0, status: str = None, current_merchant = Depends(get_current_merchant)):
    """
    Get paginated orders for the current merchant.
    Strictly scoped by shop_id from JWT.
    """
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    return await dashboard_repo.get_recent_orders(limit=limit, offset=offset, status=status)

@router.get("/orders/{order_id}")
async def get_order_details(order_id: int, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    try:
        return await dashboard_service.get_order_details(order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/products")
async def get_products(current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    return await dashboard_service.get_products()

@router.get("/analytics")
async def get_analytics(current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    return await dashboard_service.get_analytics()

@router.get("/profile")
async def get_profile(current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    try:
        return await dashboard_service.get_profile()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/settings")
async def update_settings(settings: dict, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    return await dashboard_service.update_settings(settings)
