import json
import httpx  # Webhook လှမ်းခေါ်ဖို့အတွက် သေချာပေါက် ပါရမယ်
from typing import Dict, Any, List, Optional
from app.db.database import BaseRepository

class DashboardRepository(BaseRepository):
    async def get_order_stats(self) -> Dict[str, Any]:
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

    # ✅ Merchant Profile ကို ဆွဲထုတ်ပေးတဲ့အပိုင်း (workflow_config ကို နဂိုအတိုင်းထားတယ်)
    async def get_merchant_profile(self) -> Optional[Dict[str, Any]]:
        query = """
            SELECT id, shop_id, name, owner_name, phone, category, status, tg_bot_token, workflow_config, created_at 
            FROM businesses 
            WHERE shop_id = $1
        """
        row = await self.fetch_one(query, self.shop_id)
        if not row:
            return None
            
        res = dict(row)
        db_bot_token = res.get("tg_bot_token")
        res["bot_token"] = db_bot_token if db_bot_token else ""
        res["bot_username"] = ""

        config = res.get("workflow_config")
        if config:
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except:
                    config = {}
            if isinstance(config, dict):
                res["bot_username"] = config.get("bot_username", "")
                
        return res

    # ✅ [AUTOMATED MULTI-TENANT WEBHOOK FIX] Token သိမ်းပြီးတာနဲ့ သက်ဆိုင်ရာ /webhook/{shop_id} ဆီ အလိုအလျောက် Webhook ချိတ်ပေးမယ် ကောင်ကြီး
    async def update_merchant_settings(self, settings: Dict[str, Any]):
        bot_token = settings.get("bot_token")
        
        # ၁။ အရင်ဆုံး ဒေတာဘေ့စ်ရဲ့ tg_bot_token ထဲ ကွက်တိ သွားသိမ်းမယ်
        query = """
            UPDATE businesses 
            SET tg_bot_token = $1,
                updated_at = NOW() 
            WHERE shop_id = $2
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, bot_token, self.shop_id)
            
        # ၂။ Token ရှိတယ်ဆိုရင် Telegram API ဆီကို Webhook လှမ်းဆောက်ခိုင်းမယ် Bro
        if bot_token:
            # 💡 မင်းရဲ့ webhook.py လမ်းကြောင်းအတိုင်း /webhook/{shop_id} ကို dynamic ချိတ်ပေးလိုက်တယ်
            webhook_url = f"https://sellmate-ai-backend.onrender.com/webhook/{self.shop_id}"
            telegram_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
            
            try:
                # httpx client သုံးပြီး Telegram API ဆီ Request ပို့မယ်
                async with httpx.AsyncClient() as client:
                    response = await client.get(telegram_url, params={"url": webhook_url})
                    res_data = response.json()
                    
                    if res_data.get("ok"):
                        print(f"✅ Webhook set successfully for shop_id: {self.shop_id} to {webhook_url}")
                    else:
                        print(f"❌ Telegram Webhook Config Failed: {res_data.get('description')}")
            except Exception as e:
                print(f"⚠️ Error occurred while automating webhook: {str(e)}")

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