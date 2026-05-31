from datetime import date
from app.db.database import BaseRepository

class AnalyticsRepository(BaseRepository):
    async def aggregate_daily_stats(self, shop_id: str, target_date: date):
        # Aggregate messages
        msg_count = await self.fetch_one(
            "SELECT COUNT(*) FROM audit_logs WHERE shop_id=$1 AND DATE(created_at)=$2",
            shop_id, target_date
        )
        
        # Aggregate orders
        order_stats = await self.fetch_one(
            "SELECT COUNT(*) as count, SUM(total_price) as sales FROM orders WHERE shop_id=$1 AND DATE(created_at)=$2",
            shop_id, target_date
        )
        
        # Aggregate AI failures
        ai_failures = await self.fetch_one(
            "SELECT COUNT(*) FROM system_metrics WHERE dimensions->>'shop_id'=$1 AND metric_name='success_rate' AND metric_value=0 AND dimensions->>'operation'='ai_parse' AND DATE(created_at)=$2",
            shop_id, target_date
        )

        query = """
            INSERT INTO daily_analytics (shop_id, date, total_messages, total_orders, total_sales, ai_failure_count)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (shop_id, date) DO UPDATE SET
            total_messages = EXCLUDED.total_messages,
            total_orders = EXCLUDED.total_orders,
            total_sales = EXCLUDED.total_sales,
            ai_failure_count = EXCLUDED.ai_failure_count
        """
        await self.execute(query, shop_id, target_date, msg_count['count'], order_stats['count'], order_stats['sales'] or 0, ai_failures['count'])

class AnalyticsService:
    def __init__(self, repo: AnalyticsRepository):
        self.repo = repo

    async def run_daily_aggregation(self, shop_id: str):
        today = date.today()
        await self.repo.aggregate_daily_stats(shop_id, today)
