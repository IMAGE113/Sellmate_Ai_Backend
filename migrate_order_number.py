import asyncio
import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def migrate():
    print(f"Connecting to {DATABASE_URL}...")
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        print("Adding order_number column to orders table...")
        await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_number VARCHAR(20) UNIQUE;")
        print("Creating index on order_number...")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_number ON orders(order_number);")
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate())
