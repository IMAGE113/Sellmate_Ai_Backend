from typing import Dict, Any, List
from app.db.database import BaseRepository

class DashboardRepository(BaseRepository):
    async def get_order_stats(self) -> Dict[str, Any]:
        # Optimized with indexes on shop_id and status
        query = """
            SELECT 
                COUNT(*) FILTER (WHERE status = 'PAYMENT_PENDING_REVIEW') as pending_payments,
                COUNT(*) FILTER (WHERE status = 'NEW_CHAT' OR status = 'COLLECTING_INFO') as recent_orders,
                COUNT(*) FILTER (WHERE status = 'PAYMENT_CONFIRMED') as confirmed_orders,
                COUNT(*) FILTER (WHERE status = 'CANCELLED') as cancelled_orders,
                COUNT(*) as total_orders
            FROM orders
            WHERE shop_id = $1
        """
        return await self.fetch_one(query, self.shop_id)

    async def get_recent_orders(self, limit: int = 10, offset: int = 0, status: str = None) -> List[Dict[str, Any]]:
        # Indexed query with pagination
        params = [self.shop_id, limit, offset]
        query = """
            SELECT id, chat_id, customer_name, total_price, status, created_at
            FROM orders
            WHERE shop_id = $1
        """
        if status:
            query += " AND status = $4"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
        return await self.fetch_all(query, *params)

    async def get_order_details(self, order_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM orders WHERE id = $1 AND shop_id = $2"
        return await self.fetch_one(query, order_id, self.shop_id)

    async def get_products(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM products WHERE shop_id = $1 AND is_active = TRUE"
        return await self.fetch_all(query, self.shop_id)

    async def get_analytics(self) -> Dict[str, Any]:
        query = """
            SELECT 
                COALESCE(SUM(total_price), 0) as total_revenue,
                COUNT(*) as total_orders,
                COUNT(DISTINCT chat_id) as total_customers
            FROM orders
            WHERE shop_id = $1 AND status = 'COMPLETED'
        """
        return await self.fetch_one(query, self.shop_id)

    async def get_merchant_profile(self) -> Optional[Dict[str, Any]]:
        query = "SELECT id, shop_id, name, owner_name, phone, category, status, tg_bot_token, workflow_config, created_at FROM businesses WHERE shop_id = $1"
        return await self.fetch_one(query, self.shop_id)

    async def update_merchant_settings(self, settings: Dict[str, Any]):
        query = "UPDATE businesses SET workflow_config = workflow_config || $1, updated_at = NOW() WHERE shop_id = $2"
        await self.execute(query, json.dumps(settings), self.shop_id)

class DashboardService:
    def __init__(self, dashboard_repo: DashboardRepository):
        self.dashboard_repo = dashboard_repo

    async def get_overview(self) -> Dict[str, Any]:
        stats = await self.dashboard_repo.get_order_stats()
        recent = await self.dashboard_repo.get_recent_orders(limit=5)
        return {
            "stats": stats,
            "recent_orders": recent
        }

    async def get_order_details(self, order_id: int) -> Dict[str, Any]:
        order = await self.dashboard_repo.get_order_details(order_id)
        if not order:
            raise ValueError("Order not found")
        return order

    async def get_products(self) -> List[Dict[str, Any]]:
        return await self.dashboard_repo.get_products()

    async def get_analytics(self) -> Dict[str, Any]:
        return await self.dashboard_repo.get_analytics()

    async def get_profile(self) -> Dict[str, Any]:
        profile = await self.dashboard_repo.get_merchant_profile()
        if not profile:
            raise ValueError("Merchant profile not found")
        return profile

    async def update_settings(self, settings: Dict[str, Any]):
        await self.dashboard_repo.update_merchant_settings(settings)
        return {"success": True, "message": "Settings updated"}
