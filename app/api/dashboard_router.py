from fastapi import APIRouter, Depends, HTTPException
from app.db.database import get_db_pool
from app.services.dashboard_service import DashboardRepository
from app.services.dashboard_service import DashboardService
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
async def get_orders(limit: int = 10, offset: int = 0, status: str = None, current_merchant = Depends(get_current_merchant)):
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

# ✅ [GET PRODUCTS FIX] DB ထဲက Column တွေနဲ့ ကိုက်အောင် SQL ကို ညှိပြီး တိုက်ရိုက်ထုတ်ပေးထားတယ် Bro
@router.get("/products")
async def get_products(current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id as product_id, name as product_name, price, stock as quantity, 
                   CASE WHEN is_active = true THEN 'active' ELSE 'inactive' END as status,
                   created_at as created_date
            FROM products 
            WHERE shop_id = $1
            ORDER BY created_at DESC
            """,
            shop_id
        )
        return [dict(row) for row in rows]

# ✅ [POST PRODUCT FIX] မင်းရဲ့ Neon DB ထဲက Column အစစ်တွေဖြစ်တဲ့ (name, price, stock, is_active) ထဲ ကွက်တိ ထည့်ပေးမှာဖြစ်လို့ အာမခံတယ် Bro
@router.post("/products")
async def create_product(product_data: dict, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    product_name = product_data.get("product_name")
    price = product_data.get("price")
    quantity = product_data.get("quantity", 0)
    status = product_data.get("status", "active")
    
    if not product_name or price is None:
        raise HTTPException(status_code=400, detail="Product name and price are required")
        
    is_active_bool = True if status == "active" else False
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO products (shop_id, name, price, stock, is_active, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                RETURNING id as product_id, name as product_name, price, stock as quantity,
                          CASE WHEN is_active = true THEN 'active' ELSE 'inactive' END as status,
                          created_at as created_date
                """,
                shop_id, product_name, float(price), int(quantity), is_active_bool
            )
            return {"success": True, "data": dict(row) if row else {}}
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