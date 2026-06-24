
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json

from app.workflow.flow_manager import FlowManager
from app.services.order_service import OrderService
from app.workers.order_worker import run_worker # Assuming run_worker is the entry point
from app.db.database import OrderRepository, AuditRepository, MerchantRepository, ProductRepository
from app.services.ai import AI
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.rate_limiter import RateLimiter
from app.services.lifecycle_service import LifecycleService, LifecycleRepository

class TestOrderWorkflow(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_pool = AsyncMock()
        self.mock_order_repo = AsyncMock(spec=OrderRepository)
        self.mock_audit_repo = AsyncMock(spec=AuditRepository)
        self.mock_merchant_repo = AsyncMock(spec=MerchantRepository)
        self.mock_product_repo = AsyncMock(spec=ProductRepository)
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
        patcher_get_db_pool = patch('app.workers.order_worker.get_db_pool', new_callable=AsyncMock)
        self.mock_get_db_pool = patcher_get_db_pool.start()
        self.mock_get_db_pool.return_value = self.mock_pool
        self.addCleanup(patcher_get_db_pool.stop)

        patcher_QueueRepository = patch('app.workers.order_worker.QueueRepository', return_value=self.mock_queue_repo)
        self.mock_QueueRepository = patcher_QueueRepository.start()
        self.addCleanup(patcher_QueueRepository.stop)

        patcher_QueueManager = patch('app.workers.order_worker.QueueManager', return_value=self.mock_queue_manager)
        self.mock_QueueManager = patcher_QueueManager.start()
        self.addCleanup(patcher_QueueManager.stop)

        patcher_LifecycleService = patch('app.workers.order_worker.LifecycleService', return_value=self.mock_lifecycle_service)
        self.mock_LifecycleService = patcher_LifecycleService.start()
        self.addCleanup(patcher_LifecycleService.stop)

        patcher_LockRepository = patch('app.workers.order_worker.LockRepository', return_value=self.mock_lock_repo)
        self.mock_LockRepository = patcher_LockRepository.start()
        self.addCleanup(patcher_LockRepository.stop)

        patcher_LockManager = patch('app.workers.order_worker.LockManager', return_value=self.mock_lock_manager)
        self.mock_LockManager = patcher_LockManager.start()
        self.addCleanup(patcher_LockManager.stop)

        patcher_OrderRepository = patch('app.workers.order_worker.OrderRepository', return_value=self.mock_order_repo)
        self.mock_OrderRepository = patcher_OrderRepository.start()
        self.addCleanup(patcher_OrderRepository.stop)

        patcher_MerchantRepository = patch('app.workers.order_worker.MerchantRepository', return_value=self.mock_merchant_repo)
        self.mock_MerchantRepository = patcher_MerchantRepository.start()
        self.addCleanup(patcher_MerchantRepository.stop)

        patcher_AuditRepository = patch('app.workers.order_worker.AuditRepository', return_value=self.mock_audit_repo)
        self.mock_AuditRepository = patcher_AuditRepository.start()
        self.addCleanup(patcher_AuditRepository.stop)

        patcher_ProductRepository = patch('app.workers.order_worker.ProductRepository', return_value=self.mock_product_repo)
        self.mock_ProductRepository = patcher_ProductRepository.start()
        self.addCleanup(patcher_ProductRepository.stop)

        patcher_OrderService = patch('app.workers.order_worker.OrderService', return_value=self.order_service)
        self.mock_OrderService = patcher_OrderService.start()
        self.addCleanup(patcher_OrderService.stop)

        patcher_ai = patch('app.workers.order_worker.ai', new=self.mock_ai)
        self.mock_ai_patch = patcher_ai.start()
        self.addCleanup(patcher_ai.stop)

        patcher_send = patch('app.workers.order_worker.send', new=self.mock_send)
        self.mock_send_patch = patcher_send.start()
        self.addCleanup(patcher_send.stop)

        patcher_rate_limiter = patch('app.services.rate_limiter.rate_limiter', new=self.mock_rate_limiter)
        self.mock_rate_limiter_patch = patcher_rate_limiter.start()
        self.addCleanup(patcher_rate_limiter.stop)

        patcher_asyncio_sleep = patch('asyncio.sleep', new_callable=AsyncMock)
        self.mock_asyncio_sleep = patcher_asyncio_sleep.start()
        self.addCleanup(patcher_asyncio_sleep.stop)

    # Test for FlowManager.get_next_step
    def test_flow_manager_get_next_step(self):
        # Test case 1: Human takeover intent
        flow_manager = FlowManager({}, {})
        self.assertEqual(flow_manager.get_next_step("HUMAN_TAKEOVER"), "HUMAN_TAKEOVER")

        # Test case 2: Menu query intent
        flow_manager = FlowManager({}, {})
        self.assertEqual(flow_manager.get_next_step("MENU_QUERY"), "MENU_INFO")

        # Test case 3: Greeting with no items
        flow_manager = FlowManager({}, {})
        self.assertEqual(flow_manager.get_next_step("GREETING"), "GREETING")

        # Test case 4: Ask for items
        flow_manager = FlowManager({}, {})
        self.assertEqual(flow_manager.get_next_step("ORDER"), "ASK_ITEMS")

        # Test case 5: Ask for name
        flow_manager = FlowManager({"setting_require_name": True}, {"items": [{"name": "item1"}]})
        self.assertEqual(flow_manager.get_next_step("ORDER"), "ASK_NAME")

        # Test case 6: Order confirmed
        flow_manager = FlowManager(
            {"setting_require_name": False, "setting_require_phone": False, "setting_require_address": False},
            {"items": [{"name": "item1"}], "customer_name": "test", "phone_no": "123", "address": "abc", "township": "xyz", "payment_method": "COD"}
        )
        self.assertEqual(flow_manager.get_next_step("ORDER"), "ORDER_CONFIRMED")

    # Test for OrderService.get_or_create_active_order
    async def test_order_service_get_or_create_active_order(self):
        # Case 1: Active order exists
        self.mock_order_repo.get_active_order_by_chat_id.return_value = {"id": 1, "status": "COLLECTING_INFO"}
        order = await self.order_service.get_or_create_active_order(123, 1)
        self.assertEqual(order["id"], 1)
        self.mock_order_repo.get_active_order_by_chat_id.assert_called_once_with(123)
        self.mock_order_repo.create_order.assert_not_called()

        # Case 2: No active order, new one created
        self.mock_order_repo.get_active_order_by_chat_id.return_value = None
        self.mock_order_repo.create_order.return_value = {"id": 2, "status": "NEW_CHAT"}
        order = await self.order_service.get_or_create_active_order(456, 1)
        self.assertEqual(order["id"], 2)
        self.mock_order_repo.create_order.assert_called_once_with(456, 1)
        self.mock_audit_repo.log_event.assert_called_once()

    # Test for OrderService.update_status
    async def test_order_service_update_status(self):
        # Case 1: Valid transition
        self.mock_order_repo.get_order_by_id.return_value = {"id": 1, "status": "NEW_CHAT"}
        await self.order_service.update_status(1, "COLLECTING_INFO", "bot", "test")
        self.mock_order_repo.update_order_status.assert_called_once_with(1, "COLLECTING_INFO", "bot", "test")
        self.mock_audit_repo.log_event.assert_called_once()

        # Case 2: Invalid transition
        self.mock_order_repo.get_order_by_id.return_value = {"id": 1, "status": "NEW_CHAT"}
        with self.assertRaisesRegex(ValueError, "Invalid transition from NEW_CHAT to READY_TO_SHIP"):
            await self.order_service.update_status(1, "READY_TO_SHIP", "bot", "test")

        # Case 3: Order not found
        self.mock_order_repo.get_order_by_id.return_value = None
        with self.assertRaisesRegex(ValueError, "Order not found"):
            await self.order_service.update_status(1, "COLLECTING_INFO", "bot", "test")

    # Test for order_worker.run_worker (simplified, focusing on flow)
    @patch('app.workers.order_worker.asyncio.sleep', new_callable=AsyncMock)
    async def test_run_worker_flow(self, mock_sleep):
        # Simulate a single task in the queue
        self.mock_queue_manager.pop.side_effect = [
            {"id": "task1", "shop_id": 1, "payload": '{"chat_id": 123, "data": {"user_text": "hi"}}'},
            None # Stop after one task
        ]
        self.mock_lock_manager.acquire.return_value = True
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "name": "Test Shop", "tg_bot_token": "token", "is_human_takeover_active": False}
        self.order_service.get_or_create_active_order = AsyncMock(return_value={"id": 101, "extracted_data": {}})
        self.mock_ai.extract_data.return_value = '{"intent": "GREETING"}'
        self.mock_ai.merge_data.return_value = {"intent": "GREETING"}
        self.mock_order_repo.execute.return_value = None
        self.mock_product_repo.get_product_by_name.return_value = {"id": 1, "stock": 10}
        self.mock_product_repo.update_product_stock.return_value = None
        self.order_service.update_status = AsyncMock(return_value=None)
        self.mock_send.return_value = None
        self.mock_audit_repo.log_event.return_value = None
        self.mock_queue_manager.complete.return_value = None
        self.mock_lock_manager.release.return_value = None

        # Run the worker for a short period to process the task
        with patch('app.workers.order_worker.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError] # Allow one sleep, then stop
            try:
                await run_worker()
            except asyncio.CancelledError:
                pass

        self.mock_queue_manager.pop.assert_called_with("inbound_messages")
        self.mock_lock_manager.acquire.assert_called_once_with(123)
        self.mock_merchant_repo.get_merchant_by_shop_id.assert_called_once()
        self.order_service.get_or_create_active_order.assert_called_once_with(123, 1)
        self.mock_ai.extract_data.assert_called_once()
        self.mock_ai.merge_data.assert_called_once()
        self.mock_order_repo.execute.assert_called_once()
        self.order_service.update_status.assert_called_once_with(101, "COLLECTING_INFO", "bot", "Bot asking for: GREETING")
        self.mock_send.assert_called_once()
        self.mock_audit_repo.log_event.assert_called_once()
        self.mock_queue_manager.complete.assert_called_once_with("task1")
        self.mock_lock_manager.release.assert_called_once_with(123)

if __name__ == '__main__':
    unittest.main()
