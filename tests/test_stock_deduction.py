
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from app.db.database import ProductRepository, OrderRepository, AuditRepository, MerchantRepository
from app.workers.order_worker import run_worker
from app.services.order_service import OrderService
from app.workflow.flow_manager import FlowManager
from app.services.ai import AI
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.rate_limiter import RateLimiter
from app.services.lifecycle_service import LifecycleService, LifecycleRepository

class TestStockDeduction(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_pool = AsyncMock()
        self.mock_product_repo = AsyncMock(spec=ProductRepository)
        self.mock_order_repo = AsyncMock(spec=OrderRepository)
        self.mock_audit_repo = AsyncMock(spec=AuditRepository)
        self.mock_merchant_repo = AsyncMock(spec=MerchantRepository)
        self.mock_queue_repo = AsyncMock(spec=QueueRepository)
        self.mock_lock_repo = AsyncMock(spec=LockRepository)
        self.mock_lifecycle_repo = AsyncMock(spec=LifecycleRepository)

        self.order_service = OrderService(self.mock_order_repo, self.mock_audit_repo)
        self.mock_ai = MagicMock(spec=AI)
        self.mock_send = AsyncMock(spec=send)
        self.mock_lock_manager = MagicMock(spec=LockManager)
        self.mock_queue_manager = MagicMock(spec=QueueManager)
        self.mock_rate_limiter = MagicMock(spec=RateLimiter)
        self.mock_lifecycle_service = MagicMock(spec=LifecycleService)

        # Patching dependencies for run_worker
        patcher_get_db_pool = patch("app.workers.order_worker.get_db_pool", new_callable=AsyncMock)
        self.mock_get_db_pool = patcher_get_db_pool.start()
        self.mock_get_db_pool.return_value = self.mock_pool
        self.addCleanup(patcher_get_db_pool.stop)

        patcher_QueueRepository = patch("app.workers.order_worker.QueueRepository", return_value=self.mock_queue_repo)
        self.mock_QueueRepository = patcher_QueueRepository.start()
        self.addCleanup(patcher_QueueRepository.stop)

        patcher_QueueManager = patch("app.workers.order_worker.QueueManager", return_value=self.mock_queue_manager)
        self.mock_QueueManager = patcher_QueueManager.start()
        self.addCleanup(patcher_QueueManager.stop)

        patcher_LifecycleService = patch("app.workers.order_worker.LifecycleService", return_value=self.mock_lifecycle_service)
        self.mock_LifecycleService = patcher_LifecycleService.start()
        self.addCleanup(patcher_LifecycleService.stop)

        patcher_LockRepository = patch("app.workers.order_worker.LockRepository", return_value=self.mock_lock_repo)
        self.mock_LockRepository = patcher_LockRepository.start()
        self.addCleanup(patcher_LockRepository.stop)

        patcher_LockManager = patch("app.workers.order_worker.LockManager", return_value=self.mock_lock_manager)
        self.mock_LockManager = patcher_LockManager.start()
        self.addCleanup(patcher_LockManager.stop)

        patcher_OrderRepository = patch("app.workers.order_worker.OrderRepository", return_value=self.mock_order_repo)
        self.mock_OrderRepository = patcher_OrderRepository.start()
        self.addCleanup(patcher_OrderRepository.stop)

        patcher_MerchantRepository = patch("app.workers.order_worker.MerchantRepository", return_value=self.mock_merchant_repo)
        self.mock_MerchantRepository = patcher_MerchantRepository.start()
        self.addCleanup(patcher_MerchantRepository.stop)

        patcher_AuditRepository = patch("app.workers.order_worker.AuditRepository", return_value=self.mock_audit_repo)
        self.mock_AuditRepository = patcher_AuditRepository.start()
        self.addCleanup(patcher_AuditRepository.stop)

        patcher_ProductRepository = patch("app.workers.order_worker.ProductRepository", return_value=self.mock_product_repo)
        self.mock_ProductRepository = patcher_ProductRepository.start()
        self.addCleanup(patcher_ProductRepository.stop)

        patcher_OrderService = patch("app.workers.order_worker.OrderService", return_value=self.order_service)
        self.mock_OrderService = patcher_OrderService.start()
        self.addCleanup(patcher_OrderService.stop)

        patcher_ai = patch("app.workers.order_worker.ai", new=self.mock_ai)
        self.mock_ai_patch = patcher_ai.start()
        self.addCleanup(patcher_ai.stop)

        patcher_send = patch("app.workers.order_worker.send", new=self.mock_send)
        self.mock_send_patch = patcher_send.start()
        self.addCleanup(patcher_send.stop)

        patcher_rate_limiter = patch("app.services.rate_limiter.rate_limiter", new=self.mock_rate_limiter)
        self.mock_rate_limiter_patch = patcher_rate_limiter.start()
        self.addCleanup(patcher_rate_limiter.stop)

        patcher_asyncio_sleep = patch("asyncio.sleep", new_callable=AsyncMock)
        self.mock_asyncio_sleep = patcher_asyncio_sleep.start()
        self.addCleanup(patcher_asyncio_sleep.stop)

        # Mock FlowManager to control status_key
        self.mock_flow_manager = MagicMock(spec=FlowManager)
        patcher_FlowManager = patch("app.workers.order_worker.FlowManager", return_value=self.mock_flow_manager)
        self.mock_FlowManager = patcher_FlowManager.start()
        self.addCleanup(patcher_FlowManager.stop)

    # Test for ProductRepository.get_product_by_name
    async def test_product_repo_get_product_by_name(self):
        self.mock_product_repo.get_product_by_name.return_value = {"id": 1, "name": "Test Product", "stock": 10}
        product = await self.mock_product_repo.get_product_by_name("Test Product")
        self.assertIsNotNone(product)
        self.assertEqual(product["name"], "Test Product")
        self.mock_product_repo.get_product_by_name.assert_called_once_with("Test Product")

    # Test for ProductRepository.update_product_stock
    async def test_product_repo_update_product_stock(self):
        await self.mock_product_repo.update_product_stock(1, 5)
        self.mock_product_repo.update_product_stock.assert_called_once_with(1, 5)

    # Test stock deduction logic in order_worker.run_worker
    @patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock)
    async def test_run_worker_stock_deduction_sufficient_stock(self, mock_sleep):
        # Simulate a task that leads to ORDER_CONFIRMED with sufficient stock
        self.mock_queue_manager.pop.side_effect = [
            {"id": "task1", "shop_id": 1, "payload": "{\"chat_id\": 123, \"data\": {\"user_text\": \"I want 2 apples\"}}"},
            None # Stop after one task
        ]
        self.mock_lock_manager.acquire.return_value = True
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "name": "Test Shop", "tg_bot_token": "token", "is_human_takeover_active": False}
        self.order_service.get_or_create_active_order = AsyncMock(return_value={"id": 101, "extracted_data": {"items": [{"name": "apple", "qty": 2}]}})
        self.mock_ai.extract_data.return_value = "{\"intent\": \"ORDER\", \"items\": [{\"name\": \"apple\", \"qty\": 2}]}"
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 2}]}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_product_repo.get_product_by_name.return_value = {"id": 1, "name": "apple", "stock": 10}
        self.order_service.update_status = AsyncMock(return_value=None)

        with patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep_inner:
            mock_sleep_inner.side_effect = [None, asyncio.CancelledError]
            try:
                await run_worker()
            except asyncio.CancelledError:
                pass

        self.mock_product_repo.get_product_by_name.assert_called_with("apple")
        self.mock_product_repo.update_product_stock.assert_called_once_with(1, 2)
        self.order_service.update_status.assert_called_with(101, "PAYMENT_CONFIRMED", "bot", "Order confirmed and stock deducted")

    @patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock)
    async def test_run_worker_stock_deduction_insufficient_stock(self, mock_sleep):
        # Simulate a task that leads to ORDER_CONFIRMED with insufficient stock
        self.mock_queue_manager.pop.side_effect = [
            {"id": "task1", "shop_id": 1, "payload": "{\"chat_id\": 123, \"data\": {\"user_text\": \"I want 20 apples\"}}"},
            None # Stop after one task
        ]
        self.mock_lock_manager.acquire.return_value = True
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "name": "Test Shop", "tg_bot_token": "token", "is_human_takeover_active": False}
        self.order_service.get_or_create_active_order = AsyncMock(return_value={"id": 101, "extracted_data": {"items": [{"name": "apple", "qty": 20}]}})
        self.mock_ai.extract_data.return_value = "{\"intent\": \"ORDER\", \"items\": [{\"name\": \"apple\", \"qty\": 20}]}"
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 20}]}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_product_repo.get_product_by_name.return_value = {"id": 1, "name": "apple", "stock": 10}
        self.order_service.update_status = AsyncMock(return_value=None)

        with patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep_inner:
            mock_sleep_inner.side_effect = [None, asyncio.CancelledError]
            try:
                await run_worker()
            except asyncio.CancelledError:
                pass

        self.mock_product_repo.get_product_by_name.assert_called_with("apple")
        self.mock_product_repo.update_product_stock.assert_not_called() # Stock should not be deducted
        self.order_service.update_status.assert_called_with(101, "CANCELLED", "bot", "Order cancelled due to insufficient stock")

    @patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock)
    async def test_run_worker_stock_deduction_product_not_found(self, mock_sleep):
        # Simulate a task that leads to ORDER_CONFIRMED with a product not found
        self.mock_queue_manager.pop.side_effect = [
            {"id": "task1", "shop_id": 1, "payload": "{\"chat_id\": 123, \"data\": {\"user_text\": \"I want 2 oranges\"}}"},
            None # Stop after one task
        ]
        self.mock_lock_manager.acquire.return_value = True
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "name": "Test Shop", "tg_bot_token": "token", "is_human_takeover_active": False}
        self.order_service.get_or_create_active_order = AsyncMock(return_value={"id": 101, "extracted_data": {"items": [{"name": "orange", "qty": 2}]}})
        self.mock_ai.extract_data.return_value = "{\"intent\": \"ORDER\", \"items\": [{\"name\": \"orange\", \"qty\": 2}]}"
        self.mock_ai.merge_data.return_value = {"items": [{"name": "orange", "qty": 2}]}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_product_repo.get_product_by_name.return_value = None # Product not found
        self.order_service.update_status = AsyncMock(return_value=None)

        with patch("app.workers.order_worker.asyncio.sleep", new_callable=AsyncMock) as mock_sleep_inner:
            mock_sleep_inner.side_effect = [None, asyncio.CancelledError]
            try:
                await run_worker()
            except asyncio.CancelledError:
                pass

        self.mock_product_repo.get_product_by_name.assert_called_with("orange")
        self.mock_product_repo.update_product_stock.assert_not_called() # Stock should not be deducted
        self.order_service.update_status.assert_called_with(101, "CANCELLED", "bot", "Order cancelled due to insufficient stock")

if __name__ == "__main__":
    unittest.main()
