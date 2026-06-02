from typing import Dict, Optional
from app.db.database import BaseRepository
from app.core.scripts import get_script as get_default_script

class ScriptRepository(BaseRepository):
    async def get_merchant_script(self, script_key: str) -> Optional[str]:
        query = """
            SELECT content FROM merchant_scripts 
            WHERE shop_id = $1 AND script_key = $2 AND active_status = TRUE
        """
        row = await self.fetch_one(query, self.shop_id, script_key)
        return row["content"] if row else None

    async def update_script(self, script_key: str, content: str):
        query = """
            INSERT INTO merchant_scripts (shop_id, script_key, content, active_status)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (shop_id, script_key) DO UPDATE SET
            content = EXCLUDED.content,
            updated_at = NOW()
        """
        await self.execute(query, self.shop_id, script_key, content)

class ScriptService:
    _instance_cache = {} # Shared across instances if needed, or per-instance

    def __init__(self, script_repo: ScriptRepository):
        self.script_repo = script_repo

    async def get_script(self, script_key: str, **kwargs) -> str:
        cache_key = f"{self.script_repo.shop_id}:{script_key}"
        if cache_key in self._instance_cache:
            template = self._instance_cache[cache_key]
        else:
            template = await self.script_repo.get_merchant_script(script_key)
            if not template:
                template = get_default_script(script_key)
            self._instance_cache[cache_key] = template
        
        try:
            return template.format(**kwargs)
        except Exception:
            return template

    def invalidate_cache(self, script_key: Optional[str] = None):
        """Invalidate cache for a specific key or all keys for this merchant."""
        if script_key:
            cache_key = f"{self.script_repo.shop_id}:{script_key}"
            self._instance_cache.pop(cache_key, None)
        else:
            # Clear all for this merchant
            keys_to_remove = [k for k in self._instance_cache if k.startswith(f"{self.script_repo.shop_id}:")]
            for k in keys_to_remove:
                self._instance_cache.pop(k, None)

    async def rotate_bot_token(self, new_token: str):
        """Harden bot token replacement without service interruption."""
        # This would be used by an admin service to update the token in the DB
        # The Orchestrator should reload the token from the DB/Cache on the next request
        query = "UPDATE businesses SET tg_bot_token = $1, updated_at = NOW() WHERE shop_id = $2"
        await self.script_repo.execute(query, new_token, self.script_repo.shop_id)
        self.invalidate_cache() # Invalidate config-related caches
