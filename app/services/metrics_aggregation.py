from datetime import datetime, timedelta
from app.db.database import BaseRepository

class MetricsAggregationRepository(BaseRepository):
    async def aggregate_rollup(self, rollup_type: str, interval_minutes: int):
        # Example: Rollup 1m, 5m, 1h
        query = """
            INSERT INTO metrics_rollups (metric_name, rollup_type, metric_value, dimensions, period_start)
            SELECT 
                metric_name, 
                $1 as rollup_type, 
                AVG(metric_value) as metric_value, 
                dimensions, 
                date_trunc('minute', created_at) as period_start
            FROM system_metrics
            WHERE created_at >= NOW() - $2 * INTERVAL '1 minute'
            GROUP BY metric_name, dimensions, period_start
            ON CONFLICT (metric_name, rollup_type, period_start, dimensions) DO UPDATE SET
            metric_value = EXCLUDED.metric_value
        """
        await self.execute(query, rollup_type, interval_minutes)

class MetricsAggregationService:
    def __init__(self, repo: MetricsAggregationRepository):
        self.repo = repo

    async def run_aggregations(self):
        # Run 1m rollup
        await self.repo.aggregate_rollup("1m", 2)
        # Run 1h rollup
        await self.repo.aggregate_rollup("1h", 65)
