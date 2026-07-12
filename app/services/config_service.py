import json
from typing import Any, Dict, Optional
from app.db.database import BaseRepository

class ConfigRepository(BaseRepository):
    async def update_config(self, shop_id: str, key: str, value: Any, actor_id: int, actor_type: str):
        # 1. Get current value
        current = await self.fetch_one(
            "SELECT workflow_config FROM businesses WHERE shop_id = $1", shop_id
        )
        old_value = current['workflow_config'].get(key) if current else None
        
        # 2. Update config
        query = """
            UPDATE businesses 
            SET workflow_config = jsonb_set(workflow_config, ARRAY[$2], $3::jsonb),
                updated_at = NOW()
            WHERE shop_id = $1
        """
        await self.execute(query, shop_id, key, json.dumps(value))
        
        # 3. Record history
        history_query = """
            INSERT INTO merchant_config_history (shop_id, config_key, old_value, new_value, actor_id, actor_type)
            VALUES ($1, $2, $3, $4, $5, $6)
        """
        await self.execute(history_query, shop_id, key, json.dumps(old_value), json.dumps(value), actor_id, actor_type)

class ConfigService:
    def __init__(self, repo: ConfigRepository):
        self.repo = repo

    async def update_merchant_setting(self, shop_id: str, key: str, value: Any, actor_id: int, actor_type: str = 'admin'):
        await self.repo.update_config(shop_id, key, value, actor_id, actor_type)
        # Invalidation trigger for Cache would go here
