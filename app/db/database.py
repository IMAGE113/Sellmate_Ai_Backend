import asyncpg
import asyncio
import math
import os
import json
from typing import Any, Dict, List, Optional
from app.core.config import DATABASE_URL

pool = None
_pool_init_lock = asyncio.Lock()

async def get_db_pool():
    global pool
    if pool is None:
        async with _pool_init_lock:
            if pool is None:
                pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

async def close_db_pool():
    global pool
    if pool is not None:
        await pool.close()
        pool = None

async def init_db(pool):
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path, "r") as f:
            schema_sql = f.read()
        async with pool.acquire() as conn:
            # Task 1 Fix: Backfill columns BEFORE schema.sql to avoid UndefinedColumnError on existing tables
            await conn.execute("""
                ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS category VARCHAR(50);
                ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS sku VARCHAR(50) UNIQUE;
                ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS variant_of_id INTEGER REFERENCES products(id) ON DELETE CASCADE;
                ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS attributes JSONB DEFAULT '{}'::jsonb;
                ALTER TABLE IF EXISTS products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
                ALTER TABLE IF EXISTS orders ADD COLUMN IF NOT EXISTS order_number VARCHAR(20) UNIQUE;
                CREATE TABLE IF NOT EXISTS processed_webhooks (
                    update_id BIGINT NOT NULL,
                    shop_id VARCHAR(50) NOT NULL,
                    processed_at TIMESTAMP DEFAULT NOW()
                );
                ALTER TABLE processed_webhooks DROP CONSTRAINT IF EXISTS processed_webhooks_pkey;
                ALTER TABLE processed_webhooks ADD CONSTRAINT processed_webhooks_pkey PRIMARY KEY (shop_id, update_id);
            """)
            
            try:
                await conn.execute(schema_sql)
            except Exception as e:
                import logging
                logging.error("Schema initialization failed: %s", e)
                raise
            # Separate index creation to avoid issues if column doesn't exist yet in a single transaction block.
            # Enforce schema-declared uniqueness for legacy tables where ADD COLUMN IF NOT EXISTS
            # does not add a constraint to an already-existing column.
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_number ON orders(order_number);")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS products_sku_key ON products(sku) WHERE sku IS NOT NULL;")
            await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS orders_order_number_key ON orders(order_number) WHERE order_number IS NOT NULL;")

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
        """
        BUG-30: Allow finding recently completed orders (5-minute grace period) 
        to handle post-order edits/cancellations.
        """
        query = """
            SELECT * FROM orders 
            WHERE chat_id = $1 AND shop_id = $2 
            AND (
                status NOT IN ('COMPLETED', 'CANCELLED')
                OR (status = 'COMPLETED' AND updated_at > CURRENT_TIMESTAMP - INTERVAL '5 minutes')
            )
            ORDER BY updated_at DESC LIMIT 1
        """
        return await self.fetch_one(query, chat_id, self.shop_id)

    async def create_order(self, chat_id: int, business_id: int) -> Dict[str, Any]:
        query = """
            INSERT INTO orders (business_id, shop_id, chat_id, status)
            VALUES ($1, $2, $3, 'NEW_CHAT')
            RETURNING *
        """
        return await self.fetch_one(query, business_id, self.shop_id, chat_id)

    async def finalize_order_with_inventory(
        self,
        order_id: int,
        extracted_data: Dict[str, Any],
        order_number: str,
        deductions: List[tuple[int, Any]],
    ) -> bool:
        """Finalize an order and deduct all inventory in one PostgreSQL transaction."""
        aggregated: Dict[int, int] = {}
        for product_id, quantity in deductions:
            if isinstance(quantity, bool):
                return False
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
                return False
            quantity = int(quantity)
            aggregated[product_id] = aggregated.get(product_id, 0) + quantity

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for product_id, quantity in aggregated.items():
                    row = await conn.fetchrow(
                        "SELECT stock FROM products WHERE id = $1 AND shop_id = $2 FOR UPDATE",
                        product_id,
                        self.shop_id,
                    )
                    if row is None or row["stock"] < quantity:
                        return False

                for product_id, quantity in aggregated.items():
                    result = await conn.execute(
                        "UPDATE products SET stock = stock - $1 WHERE id = $2 AND shop_id = $3",
                        quantity,
                        product_id,
                        self.shop_id,
                    )
                    if result != "UPDATE 1":
                        raise RuntimeError("Inventory update failed during order finalization")

                result = await conn.execute(
                    """
                    UPDATE orders
                    SET extracted_data = $1,
                        customer_name = $2,
                        total_price = $3,
                        order_number = $4,
                        status = 'COMPLETED',
                        timeline = timeline || jsonb_build_object(
                            'timestamp', CURRENT_TIMESTAMP,
                            'status', 'COMPLETED',
                            'actor', 'bot',
                            'description', $5::text
                        ),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = $6 AND shop_id = $7
 AND status <> 'COMPLETED'
                    """,
                    json.dumps(extracted_data),
                    extracted_data.get("customer_name") or None,
                    extracted_data.get("total_price", 0),
                    order_number,
                    f"Order confirmed: {order_number}",
                    order_id,
                    self.shop_id,
                )
                if result != "UPDATE 1":
                    raise ValueError("Order finalization failed")

                await conn.execute(
                    """
                    INSERT INTO audit_logs
                        (business_id, shop_id, order_id, event_type, description, actor_source, details)
                    SELECT business_id, shop_id, $1, 'ORDER_STATUS_CHANGE', $2, 'bot', $3::jsonb
                    FROM orders
                    WHERE id = $1 AND shop_id = $4
                    """,
                    order_id,
                    f"Order confirmed: {order_number}",
                    json.dumps({"old_status": "ORDER_SUMMARY", "new_status": "COMPLETED"}),
                    self.shop_id,
                )
        return True

    async def update_order_status(self, order_id: int, status: str, actor: str, description: str):
        query = """
            UPDATE orders 
            SET status = $1, 
                timeline = timeline || jsonb_build_object(
                    'timestamp', CURRENT_TIMESTAMP,
                    'status', $1::varchar,
                    'actor', $2::varchar,
                    'description', $3::text
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
        """
        BUG-17: Case-insensitive, whitespace-trimmed lookup for product name.
        """
        query = "SELECT * FROM products WHERE LOWER(TRIM(name)) = LOWER(TRIM($1)) AND shop_id = $2 AND variant_of_id IS NULL"
        return await self.fetch_one(query, product_name, self.shop_id)

    async def get_product_variant(self, product_name: str, attributes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        BUG-16, BUG-17: Find a specific variant by parent name (case-insensitive) and attributes.
        """
        query = """
            SELECT v.* FROM products v
            JOIN products p ON v.variant_of_id = p.id
            WHERE LOWER(TRIM(p.name)) = LOWER(TRIM($1)) 
            AND v.shop_id = $2 
            AND v.attributes @> $3::jsonb
        """
        return await self.fetch_one(query, product_name, self.shop_id, json.dumps(attributes))

    async def update_product_stock(self, product_id: int, quantity: int) -> None:
        if isinstance(quantity, bool):
            raise ValueError("Stock deduction quantity must be a positive integer")
        try:
            numeric_quantity = float(quantity)
        except (TypeError, ValueError):
            raise ValueError("Stock deduction quantity must be a positive integer")
        if not math.isfinite(numeric_quantity) or numeric_quantity <= 0 or not numeric_quantity.is_integer():
            raise ValueError("Stock deduction quantity must be a positive integer")
        quantity = int(numeric_quantity)
        query = "UPDATE products SET stock = stock - $1 WHERE id = $2 AND shop_id = $3 AND stock >= $1"
        await self.execute(query, quantity, product_id, self.shop_id)

    async def deduct_stock_batch(self, deductions: List[tuple[int, Any]]) -> bool:
        """Deduct all requested stock atomically, refusing invalid quantities and oversell."""
        aggregated: Dict[int, int] = {}
        for product_id, quantity in deductions:
            if isinstance(quantity, bool):
                return False
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
                return False
            quantity = int(quantity)
            aggregated[product_id] = aggregated.get(product_id, 0) + quantity

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for product_id, quantity in aggregated.items():
                    row = await conn.fetchrow(
                        "SELECT stock FROM products WHERE id = $1 AND shop_id = $2 FOR UPDATE",
                        product_id,
                        self.shop_id,
                    )
                    if row is None or row["stock"] < quantity:
                        return False

                for product_id, quantity in aggregated.items():
                    await conn.execute(
                        "UPDATE products SET stock = stock - $1 WHERE id = $2 AND shop_id = $3",
                        quantity,
                        product_id,
                        self.shop_id,
                    )
        return True

    async def restore_stock_batch(self, restorations: List[tuple[int, Any]]) -> bool:
        aggregated: Dict[int, int] = {}
        for product_id, quantity in restorations:
            if isinstance(quantity, bool):
                return False
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
                return False
            quantity = int(quantity)
            aggregated[product_id] = aggregated.get(product_id, 0) + quantity
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for product_id, quantity in aggregated.items():
                    result = await conn.execute(
                        "UPDATE products SET stock = stock + $1 WHERE id = $2 AND shop_id = $3",
                        quantity, product_id, self.shop_id
                    )
                    if result == "UPDATE 0":
                        return False
        return True

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
