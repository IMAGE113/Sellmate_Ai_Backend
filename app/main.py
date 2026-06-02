import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.db.database import get_db_pool, init_db
from app.api.webhook import router as webhook_router
from app.api.auth_router import router as auth_router
from app.api.dashboard_router import router as dashboard_router
from app.api.ops_router import router as ops_router
from app.core.observability import Observability
from starlette.middleware.base import BaseHTTPMiddleware
from app.workers.order_worker import run_worker
from app.workers.notification_worker import run_notification_worker
from app.workers.cleanup_worker import run_cleanup_worker

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
    
    # Start Background Workers
    order_worker_task = asyncio.create_task(run_worker())
    notification_worker_task = asyncio.create_task(run_notification_worker())
    cleanup_worker_task = asyncio.create_task(run_cleanup_worker())
    
    yield
    
    # Shutdown logic
    logging.info("🛑 Shutting down SellMate AI...")
    order_worker_task.cancel()
    notification_worker_task.cancel()
    cleanup_worker_task.cancel()
    try:
        await asyncio.gather(order_worker_task, notification_worker_task, cleanup_worker_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID")
        Observability.set_correlation_id(correlation_id)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = Observability.get_correlation_id()
        return response

app = FastAPI(
    title="SellMate AI SaaS",
    description="Multi-tenant Telegram Bot Backend for Merchants",
    version="2.1.0",
    lifespan=lifespan
)

app.add_middleware(CorrelationMiddleware)

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routes
app.include_router(webhook_router)
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(dashboard_router)
app.include_router(ops_router)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "SellMate AI Multi-tenant SaaS",
        "version": "2.1.0"
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
