import logging
import json
from typing import Dict, Any, Optional
from app.db.database import BaseRepository

class MetricsRepository(BaseRepository):
    async def record_metric(self, name: str, value: float, dimensions: Dict[str, Any]):
        query = """
            INSERT INTO system_metrics (metric_name, metric_value, dimensions)
            VALUES ($1, $2, $3)
        """
        await self.execute(query, name, value, json.dumps(dimensions))

class MetricsService:
    def __init__(self, repo: MetricsRepository):
        self.repo = repo

    async def track_latency(self, operation: str, duration_ms: float, shop_id: str):
        await self.repo.record_metric("latency", duration_ms, {
            "operation": operation,
            "shop_id": shop_id
        })

    async def track_success_rate(self, operation: str, success: bool, shop_id: str):
        await self.repo.record_metric("success_rate", 1.0 if success else 0.0, {
            "operation": operation,
            "shop_id": shop_id
        })

    async def track_ai_parse(self, confidence: float, success: bool, shop_id: str):
        await self.repo.record_metric("ai_parse_confidence", confidence, {
            "shop_id": shop_id,
            "success": success
        })

    async def track_queue_lag(self, queue_name: str, lag_seconds: float):
        await self.repo.record_metric("queue_lag", lag_seconds, {
            "queue_name": queue_name
        })
