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
            # Backfill columns on databases created before these columns were
            # added to schema.sql. CREATE TABLE IF NOT EXISTS does not add new
            # columns to a pre-existing table, which caused
            # 'column "sku" does not exist' on drifted deployments.
            await conn.execute("""
                ALTER TABLE products ADD COLUMN IF NOT EXISTS category VARCHAR(50);
                ALTER TABLE products ADD COLUMN IF NOT EXISTS sku VARCHAR(50) UNIQUE;
                ALTER TABLE products ADD COLUMN IF NOT EXISTS variant_of_id INTEGER REFERENCES products(id) ON DELETE CASCADE;
                ALTER TABLE products ADD COLUMN IF NOT EXISTS attributes JSONB DEFAULT '{}'::jsonb;
                ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
                ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_number VARCHAR(20) UNIQUE;
                CREATE INDEX IF NOT EXISTS idx_orders_order_number ON orders(order_number);
            """)

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
        query = "SELECT * FROM products WHERE name = $1 AND shop_id = $2 AND variant_of_id IS NULL"
        return await self.fetch_one(query, product_name, self.shop_id)

    async def get_product_variant(self, parent_id: int, attributes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Find a specific variant of a product based on attributes.
        attributes is a dict like {'size': 'L', 'color': 'Red'}
        """
        query = "SELECT * FROM products WHERE variant_of_id = $1 AND shop_id = $2 AND attributes @> $3"
        return await self.fetch_one(query, parent_id, self.shop_id, json.dumps(attributes))

    async def update_product_stock(self, product_id: int, quantity: int) -> None:
        query = "UPDATE products SET stock = stock - $1 WHERE id = $2 AND shop_id = $3 AND stock >= $1"
        await self.execute(query, quantity, product_id, self.shop_id)

    async def get_variants_for_product(self, parent_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM products WHERE variant_of_id = $1 AND shop_id = $2 AND is_active = TRUE"
        return await self.fetch_all(query, parent_id, self.shop_id)


class AuditRepository(BaseRepository):
    async def log_event(self, event_type: str, actor_source: str, description: str = None, order_id: int = None, details: Dict = None):
        query = """
            INSERT INTO audit_logs (business_id, shop_id, order_id, event_type, description, actor_source, details)
            SELECT id, shop_id, $1::int, $2::varchar, $3::text, $4::varchar, $5::jsonb FROM businesses WHERE shop_id = $6
        """
        await self.execute(query, order_id, event_type, description, actor_source, json.dumps(details or {}), self.shop_id)

    async def get_logs_by_order(self, order_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM audit_logs WHERE order_id = $1 AND shop_id = $2 ORDER BY created_at DESC"
        return await self.fetch_all(query, order_id, self.shop_id)
