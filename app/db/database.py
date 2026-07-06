import asyncpg
import os
import json
from typing import Any, Dict, List, Optional
from app.core.config import DATABASE_URL

pool = None

async def get_db_pool():
    global pool
    if not pool:
        pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

async def init_db(pool):
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r") as f:
            schema_sql = f.read()
        async with pool.acquire() as conn:
            await conn.execute(schema_sql)

class BaseRepository:
    def __init__(self, pool: asyncpg.Pool, shop_id: str):
        self.pool = pool
        self.shop_id = shop_id

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def execute(self, query: str, *args) -> str:
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

class OrderRepository(BaseRepository):
    async def get_order_by_id(self, order_id: int) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM orders WHERE id = $1 AND shop_id = $2"
        return await self.fetch_one(query, order_id, self.shop_id)

    async def get_active_order_by_chat_id(self, chat_id: int) -> Optional[Dict[str, Any]]:
        query = """
            SELECT * FROM orders 
            WHERE chat_id = $1 AND shop_id = $2 
            AND status NOT IN ('COMPLETED', 'CANCELLED')
            ORDER BY created_at DESC LIMIT 1
        """
        return await self.fetch_one(query, chat_id, self.shop_id)

    async def create_order(self, chat_id: int, business_id: int) -> Dict[str, Any]:
        query = """
            INSERT INTO orders (business_id, shop_id, chat_id, status)
            VALUES ($1, $2, $3, 'NEW_CHAT')
            RETURNING *
        """
        return await self.fetch_one(query, business_id, self.shop_id, chat_id)

    async def update_order_status(self, order_id: int, status: str, actor: str, description: str):
        query = """
            UPDATE orders 
            SET status = $1, 
                timeline = timeline || jsonb_build_object(
                    'timestamp', CURRENT_TIMESTAMP,
                    'status', $1,
                    'actor', $2,
                    'description', $3
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $4 AND shop_id = $5
        """
        await self.execute(query, status, actor, description, order_id, self.shop_id)

class MerchantRepository(BaseRepository):
    async def get_merchant_by_shop_id(self) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM businesses WHERE shop_id = $1"
        return await self.fetch_one(query, self.shop_id)

    async def get_admins(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM merchant_admins WHERE shop_id = $1 AND active_status = TRUE"
        return await self.fetch_all(query, self.shop_id)

    async def set_human_takeover(self, active: bool):
        query = "UPDATE businesses SET is_human_takeover_active = $1 WHERE shop_id = $2"
        await self.execute(query, active, self.shop_id)

class ProductRepository(BaseRepository):
    async def get_product_by_name(self, product_name: str) -> Optional[Dict[str, Any]]:
        query = "SELECT id, name, stock FROM products WHERE name = $1 AND shop_id = $2"
        return await self.fetch_one(query, product_name, self.shop_id)

    async def update_product_stock(self, product_id: int, quantity: int) -> None:
        query = "UPDATE products SET stock = stock - $1 WHERE id = $2 AND shop_id = $3 AND stock >= $1"
        await self.execute(query, quantity, product_id, self.shop_id)

    async def get_variants_for_product(self, product_id: int) -> List[Dict[str, Any]]:
        query = "SELECT id, variant_name, stock FROM product_variants WHERE product_id = $1 AND shop_id = $2 AND is_active = TRUE"
        return await self.fetch_all(query, product_id, self.shop_id)

    async def update_variant_stock(self, variant_id: int, quantity: int) -> None:
        query = "UPDATE product_variants SET stock = stock - $1 WHERE id = $2 AND shop_id = $3 AND stock >= $1"
        await self.execute(query, quantity, variant_id, self.shop_id)


class AuditRepository(BaseRepository):
    async def log_event(self, event_type: str, actor_source: str, description: str = None, order_id: int = None, details: Dict = None):
        query = """
            INSERT INTO audit_logs (business_id, shop_id, order_id, event_type, description, actor_source, details)
            SELECT id, shop_id, $1, $2, $3, $4, $5 FROM businesses WHERE shop_id = $6
        """
        await self.execute(query, order_id, event_type, description, actor_source, json.dumps(details or {}), self.shop_id)

    async def get_logs_by_order(self, order_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_logs WHERE order_id = $1 AND shop_id = $2 ORDER BY created_at DESC"
        return await self.fetch_all(query, order_id, self.shop_id)
