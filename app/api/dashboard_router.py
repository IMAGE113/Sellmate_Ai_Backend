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

# ✅ [GET PRODUCTS] DB ထဲက Column တွေနဲ့ ကိုက်အောင် SQL ကို ညှိပြီး တိုက်ရိုက်ထုတ်ပေးထားတယ် Bro
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

# ✅ [PRODUCT & VARIANT CRUD] Full implementation for Task 6
@router.post("/products")
async def create_product(product_data: dict, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    name = product_data.get("product_name") or product_data.get("name")
    price = product_data.get("price")
    stock = product_data.get("quantity", 0) or product_data.get("stock", 0)
    status = product_data.get("status", "active")
    variant_of_id = product_data.get("variant_of_id")
    attributes = product_data.get("attributes", {})
    sku = product_data.get("sku")
    
    if not name or price is None:
        raise HTTPException(status_code=400, detail="Product name and price are required")
        
    is_active = True if status == "active" else False
    
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO products (shop_id, name, price, stock, is_active, variant_of_id, attributes, sku, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, NOW())
                RETURNING id as product_id, name as product_name, price, stock as quantity,
                          CASE WHEN is_active = true THEN 'active' ELSE 'inactive' END as status,
                          variant_of_id, attributes, sku, created_at as created_date
                """,
                shop_id, name, float(price), int(stock), is_active, variant_of_id, json.dumps(attributes), sku
            )
            return {"success": True, "data": dict(row) if row else {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/products/{product_id}")
async def update_product(product_id: int, product_data: dict, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    update_fields = []
    params = [shop_id, product_id]
    
    mapping = {
        "product_name": "name",
        "name": "name",
        "price": "price",
        "quantity": "stock",
        "stock": "stock",
        "status": "is_active",
        "variant_of_id": "variant_of_id",
        "attributes": "attributes",
        "sku": "sku"
    }
    
    for key, val in product_data.items():
        if key in mapping:
            col = mapping[key]
            if key == "status":
                val = True if val == "active" else False
            elif key == "price":
                val = float(val)
            elif key in ["quantity", "stock"]:
                val = int(val)
            elif key == "attributes":
                val = json.dumps(val)
                
            params.append(val)
            update_fields.append(f"{col} = ${len(params)}")
            
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    query = f"""
        UPDATE products 
        SET {", ".join(update_fields)}
        WHERE shop_id = $1 AND id = $2
        RETURNING id as product_id, name as product_name, price, stock as quantity,
                  CASE WHEN is_active = true THEN 'active' ELSE 'inactive' END as status,
                  variant_of_id, attributes, sku, created_at as created_date
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            if not row:
                raise HTTPException(status_code=404, detail="Product not found")
            return {"success": True, "data": dict(row)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/products/{product_id}")
async def delete_product(product_id: int, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    
    try:
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM products WHERE shop_id = $1 AND id = $2", shop_id, product_id)
            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail="Product not found")
            return {"success": True, "message": "Product deleted"}
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

# ✅ [SETTINGS UPDATE] Frontend က ပို့လိုက်တဲ့ bot_token တွေကို လက်ခံပြီး Service ထံ လွှဲပေးမယ်
@router.post("/settings")
async def update_settings(settings: dict, current_merchant = Depends(get_current_merchant)):
    pool = await get_db_pool()
    shop_id = current_merchant["shop_id"]
    dashboard_repo = DashboardRepository(pool, shop_id)
    dashboard_service = DashboardService(dashboard_repo)
    return await dashboard_service.update_settings(settings)