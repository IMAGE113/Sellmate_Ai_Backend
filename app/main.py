import asyncio
import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.db.database import get_db_pool, init_db
from app.api.webhook import router
from app.workers.order_worker import run_worker

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("🚀 Starting SellMate AI Multi-tenant SaaS...")
    
    # Initialize DB Pool and Schema
    pool = await get_db_pool()
    await init_db(pool)
    
    # Start the Background Worker
    worker_task = asyncio.create_task(run_worker())
    
    yield
    
    # Shutdown logic
    logging.info("🛑 Shutting down SellMate AI...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="SellMate AI SaaS",
    description="Multi-tenant Telegram Bot Backend for Merchants",
    version="2.0.0",
    lifespan=lifespan
)

# Include API Routes
app.include_router(router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "SellMate AI Multi-tenant SaaS",
        "version": "2.0.0"
    }

@app.get("/health")
async def health():
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logging.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
