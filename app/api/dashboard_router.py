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

# ✅ [NEW ENDPOINT] Product အသစ်ဆောက်ဖို့နဲ့ Quantity လက်ခံဖို့အတွက် POST Endpoint ထည့်လိုက်ပြီ Bro
@router.post("/products")
async def create_product(product_data: dict, current_merchant = Depends(get_current_merchant)):
    """
    Create a new product with quantity, strictly scoped by shop_id.
    """
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    # Frontend က ပို့လိုက်တဲ့ Data တွေကို ဖတ်မယ်
    product_name = product_data.get("product_name")
    price = product_data.get("price")
    quantity = product_data.get("quantity", 0) # Quantity ကို လက်ခံထားတယ်
    status = product_data.get("status", "active")
    
    if not product_name or price is None:
        raise HTTPException(status_code=400, detail="Product name and price are required")
        
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    
    try:
        # dashboard_service (သို့) dashboard_repo ထဲက create_product ကို လှမ်းခေါ်မယ်
        # (မင်းရဲ့ service structure အလိုက် အဆင်ပြေအောင် repo ကို တိုက်ရိုက် ခေါ်ခိုင်းထားတယ် Bro)
        if hasattr(dashboard_service, 'create_product'):
            result = await dashboard_service.create_product(product_name, price, quantity, status)
        elif hasattr(dashboard_repo, 'create_product'):
            result = await dashboard_repo.create_product(product_name, price, quantity, status)
        else:
            # တကယ်လို့ service/repo ထဲမှာ ဆောက်တဲ့မက်သတ် မရှိသေးရင် တိုက်ရိုက် SQL run ခိုင်းလိုက်မယ် (Defensive Fallback)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO products (shop_id, product_name, price, quantity, status, created_date)
                    VALUES ($1, $2, $3, $4, $5, NOW())
                    RETURNING product_id, product_name, price, quantity, status, created_date
                    """,
                    shop_id, product_name, float(price), int(quantity), status
                )
                result = dict(row) if row else {"success": False}
                
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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