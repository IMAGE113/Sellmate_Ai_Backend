import asyncpg
from app.core.config import DATABASE_URL

pool = None

async def get_db_pool():
    global pool
    if not pool:
        pool = await asyncpg.create_pool(DATABASE_URL)
    return pool

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS businesses (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            tg_bot_token TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            njv_client_id TEXT,
            njv_client_secret TEXT
        );
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            price INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customers (
            id SERIAL PRIMARY KEY,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            name TEXT,
            phone_no TEXT,
            address TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(business_id, chat_id)
        );
        CREATE TABLE IF NOT EXISTS task_queue (
            id SERIAL PRIMARY KEY,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            user_text TEXT NOT NULL,
            request_hash TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS pending_orders (
            chat_id BIGINT NOT NULL,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            order_data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY(chat_id, business_id)
        );
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
            chat_id BIGINT NOT NULL,
            customer_name TEXT,
            phone_no TEXT,
            address TEXT,
            payment_method TEXT,
            items TEXT NOT NULL,
            total_price INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
