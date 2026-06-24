import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json
import logging
import os

# Configure logging for better visibility during simulation
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Mock environment variables for database connection and other services
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
os.environ["GROQ_API_KEY"] = "dummy"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy"
os.environ["S3_BUCKET"] = "dummy"
os.environ["S3_ACCESS_KEY"] = "dummy"
os.environ["S3_SECRET_KEY"] = "dummy"

# Import necessary modules from the application
from app.db.database import get_db_pool, OrderRepository, MerchantRepository, AuditRepository, ProductRepository
from app.services.ai import ai
from app.services.order_service import OrderService
from app.workflow.flow_manager import FlowManager
from app.services.telegram import send
from app.services.lock_manager import LockRepository, LockManager
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.rate_limiter import rate_limiter
from app.services.lifecycle_service import LifecycleService, LifecycleRepository
from app.workers.order_worker import run_worker # The main worker function to simulate
from app.api.webhook import webhook # The webhook entry point

class BetaLaunchSimulation(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Mock database pool and repositories
        self.mock_pool = AsyncMock()
        self.mock_order_repo = AsyncMock(spec=OrderRepository)
        self.mock_merchant_repo = AsyncMock(spec=MerchantRepository)
        self.mock_audit_repo = AsyncMock(spec=AuditRepository)
        self.mock_product_repo = AsyncMock(spec=ProductRepository)
        self.mock_queue_repo = AsyncMock(spec=QueueRepository)
        self.mock_lock_repo = AsyncMock(spec=LockRepository)
        self.mock_lifecycle_repo = AsyncMock(spec=LifecycleRepository)

        # Patch get_db_pool to return our mock pool
        self.patcher_get_db_pool = patch("app.db.database.get_db_pool", new_callable=AsyncMock)
        self.mock_get_db_pool = self.patcher_get_db_pool.start()
        self.mock_get_db_pool.return_value = self.mock_pool
        self.addCleanup(self.patcher_get_db_pool.stop)

        # Patch repository constructors to return our mock repository instances
        self.patcher_OrderRepository = patch("app.db.database.OrderRepository", return_value=self.mock_order_repo)
        self.mock_OrderRepository = self.patcher_OrderRepository.start()
        self.addCleanup(self.patcher_OrderRepository.stop)

        self.patcher_MerchantRepository = patch("app.db.database.MerchantRepository", return_value=self.mock_merchant_repo)
        self.mock_MerchantRepository = self.patcher_MerchantRepository.start()
        self.addCleanup(self.patcher_MerchantRepository.stop)

        self.patcher_AuditRepository = patch("app.db.database.AuditRepository", return_value=self.mock_audit_repo)
        self.mock_AuditRepository = self.patcher_AuditRepository.start()
        self.addCleanup(self.patcher_AuditRepository.stop)

        self.patcher_ProductRepository = patch("app.db.database.ProductRepository", return_value=self.mock_product_repo)
        self.mock_ProductRepository = self.patcher_ProductRepository.start()
        self.addCleanup(self.patcher_ProductRepository.stop)

        self.patcher_QueueRepository = patch("app.services.queue_manager.QueueRepository", return_value=self.mock_queue_repo)
        self.mock_QueueRepository = self.patcher_QueueRepository.start()
        self.addCleanup(self.patcher_QueueRepository.stop)

        self.patcher_LockRepository = patch("app.services.lock_manager.LockRepository", return_value=self.mock_lock_repo)
        self.mock_LockRepository = self.patcher_LockRepository.start()
        self.addCleanup(self.patcher_LockRepository.stop)

        self.patcher_LifecycleRepository = patch("app.services.lifecycle_service.LifecycleRepository", return_value=self.mock_lifecycle_repo)
        self.mock_LifecycleRepository = self.patcher_LifecycleRepository.start()
        self.addCleanup(self.patcher_LifecycleRepository.stop)

        # Mock services
        self.mock_order_service = AsyncMock(spec=OrderService)
        self.patcher_OrderService = patch("app.workers.order_worker.OrderService", return_value=self.mock_order_service)
        self.mock_OrderService_instance = self.patcher_OrderService.start()
        self.addCleanup(self.patcher_OrderService.stop)

        self.mock_ai = AsyncMock(spec=ai)
        self.patcher_ai = patch("app.workers.order_worker.ai", new=self.mock_ai)
        self.mock_ai_instance = self.patcher_ai.start()
        self.addCleanup(self.patcher_ai.stop)

        self.mock_flow_manager = MagicMock(spec=FlowManager)
        self.patcher_FlowManager = patch("app.workers.order_worker.FlowManager", return_value=self.mock_flow_manager)
        self.mock_FlowManager_instance = self.patcher_FlowManager.start()
        self.addCleanup(self.patcher_FlowManager.stop)

        self.mock_send = AsyncMock()
        self.patcher_send = patch("app.workers.order_worker.send", new=self.mock_send)
        self.mock_send_instance = self.patcher_send.start()
        self.addCleanup(self.patcher_send.stop)

        self.mock_rate_limiter = MagicMock(spec=rate_limiter)
        self.patcher_rate_limiter = patch("app.workers.order_worker.rate_limiter", new=self.mock_rate_limiter)
        self.mock_rate_limiter_instance = self.patcher_rate_limiter.start()
        self.addCleanup(self.patcher_rate_limiter.stop)

        self.mock_lifecycle_service = AsyncMock(spec=LifecycleService)
        self.patcher_LifecycleService = patch("app.workers.order_worker.LifecycleService", return_value=self.mock_lifecycle_service)
        self.mock_LifecycleService_instance = self.patcher_LifecycleService.start()
        self.addCleanup(self.patcher_LifecycleService.stop)

        # Mock webhook dependencies
        self.mock_idempotency_service = AsyncMock()
        self.patcher_IdempotencyService = patch("app.api.webhook.IdempotencyService", return_value=self.mock_idempotency_service)
        self.mock_IdempotencyService_instance = self.patcher_IdempotencyService.start()
        self.addCleanup(self.patcher_IdempotencyService.stop)

        self.mock_s3_service = AsyncMock()
        self.patcher_s3_service = patch("app.api.webhook.s3_service", new=self.mock_s3_service)
        self.mock_s3_service_instance = self.patcher_s3_service.start()
        self.addCleanup(self.patcher_s3_service.stop)

        self.mock_telegram_service = AsyncMock()
        self.patcher_telegram_service = patch("app.api.webhook.telegram_service", new=self.mock_telegram_service)
        self.mock_telegram_service_instance = self.patcher_telegram_service.start()
        self.addCleanup(self.patcher_telegram_service.stop)

        self.mock_queue_manager_webhook = AsyncMock()
        self.patcher_queue_manager_webhook = patch("app.api.webhook.QueueManager", return_value=self.mock_queue_manager_webhook)
        self.mock_QueueManager_webhook_instance = self.patcher_queue_manager_webhook.start()
        self.addCleanup(self.patcher_queue_manager_webhook.stop)

        # Common mock return values
        self.mock_lock_manager.acquire.return_value = True
        self.mock_lock_manager.release.return_value = True
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "name": "Test Shop", "tg_bot_token": "token", "is_human_takeover_active": False, "requirements_text": ""}
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 101, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [] # No menu by default
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": []})
        self.mock_ai.merge_data.return_value = {"items": []}
        self.mock_flow_manager.get_next_step.return_value = "GREETING"
        self.mock_flow_manager.get_response.return_value = "Hello! How can I help you?"
        self.mock_order_repo.execute.return_value = None
        self.mock_order_service.update_status.return_value = None
        self.mock_queue_manager_webhook.push.return_value = None
        self.mock_idempotency_service.check_and_mark.return_value = False # Not a duplicate

        # Simulate 10 merchants
        self.merchants = []
        for i in range(1, 11):
            self.merchants.append({"id": i, "name": f"Shop {i}", "tg_bot_token": f"token_{i}", "is_human_takeover_active": False, "requirements_text": ""})

    async def _simulate_worker_cycle(self, task_payload):
        # Simulate webhook receiving a message and enqueuing it
        update_id = "12345" # Dummy update_id
        chat_id = task_payload["chat_id"]
        shop_id = task_payload["shop_id"]
        
        # Mock the webhook's interaction with idempotency and queue
        self.mock_idempotency_service.check_and_mark.return_value = False # Ensure it's not seen as duplicate for this test
        
        # Mock the request for webhook
        mock_request = AsyncMock()
        mock_request.json.return_value = {
            "update_id": update_id,
            "message": {
                "chat": {"id": chat_id},
                "text": task_payload["data"].get("user_text", "")
            }
        }
        
        # Simulate the webhook call
        await webhook(shop_id=shop_id, request=mock_request)

        # The webhook pushes to the queue, so we need to mock queue_manager.pop to return this task
        # For simplicity in simulation, we'll directly set the task for the worker to pick up
        # In a real system, the worker would pop from the queue that the webhook pushed to.
        # Here, we'll bypass the actual queue and feed the worker directly.
        
        # Mock the queue_manager.pop to return the task we just 
        self.mock_queue_repo.fetch_job.return_value = {
            "id": "task_id_123",
            "shop_id": shop_id,
            "payload": json.dumps(task_payload)
        }
        self.mock_queue_repo.mark_completed.return_value = None
        self.mock_queue_repo.mark_failed.return_value = None

        # Run the worker once to process this task
        await run_worker()

    async def test_merchant_onboarding_flow(self):
        logging.info("--- Simulating Merchant Onboarding Flow ---")
        # Simulate a new merchant setting up their shop
        merchant_id = 11 # New merchant
        shop_name = "New Test Shop"
        tg_bot_token = "new_token"

        # Mock the merchant repository to simulate no existing merchant
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = None

        # Simulate the webhook receiving an initial message from a new merchant
        # In a real scenario, this would trigger merchant creation/onboarding flow
        # For this simulation, we'll assume the merchant is created via an admin panel
        # and then starts interacting.
        
        # Simulate merchant creation (admin action, not part of bot flow directly)
        await self.mock_merchant_repo.execute(
            "INSERT INTO businesses (id, name, tg_bot_token) VALUES ($1, $2, $3)",
            merchant_id, shop_name, tg_bot_token
        )
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": merchant_id, "name": shop_name, "tg_bot_token": tg_bot_token, "is_human_takeover_active": False, "requirements_text": ""}

        # Simulate the first message from the new merchant
        task_payload = {"chat_id": 1001, "shop_id": merchant_id, "data": {"user_text": "Hello"}}
        await self._simulate_worker_cycle(task_payload)

        self.mock_send.assert_called_once_with(tg_bot_token, 1001, "Hello! How can I help you?")
        logging.info("Merchant Onboarding Flow: PASSED")

    async def test_customer_order_flow_cod(self):
        logging.info("--- Simulating Customer Order Flow (COD) ---")
        merchant_id = self.merchants[0]["id"]
        tg_bot_token = self.merchants[0]["tg_bot_token"]
        chat_id = 2001

        # Mock initial state
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 102, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "apple", "price": 1.0, "stock": 10},
            {"name": "banana", "price": 0.5, "stock": 5}
        ]

        # 1. Customer says hello
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "Hello"}}
        self.mock_flow_manager.get_next_step.return_value = "GREETING"
        self.mock_flow_manager.get_response.return_value = "Hello! What would you like to order?"
        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Hello! What would you like to order?")
        self.mock_send.reset_mock()

        # 2. Customer orders items
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 2 apples and 1 banana"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "apple", "qty": 2}, {"name": "banana", "qty": 1}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 2}, {"name": "banana", "qty": 1}]}
        self.mock_flow_manager.get_next_step.return_value = "ASK_NAME"
        self.mock_flow_manager.get_response.return_value = "What is your name?"
        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "What is your name?")
        self.mock_send.reset_mock()

        # 3. Customer provides name
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "My name is John Doe"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "INFO", "name": "John Doe"})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 2}, {"name": "banana", "qty": 1}], "name": "John Doe"}
        self.mock_flow_manager.get_next_step.return_value = "ASK_PHONE"
        self.mock_flow_manager.get_response.return_value = "What is your phone number?"
        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "What is your phone number?")
        self.mock_send.reset_mock()

        # 4. Customer provides phone number
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "091234567"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "INFO", "phone": "091234567"})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 2}, {"name": "banana", "qty": 1}], "name": "John Doe", "phone": "091234567"}
        self.mock_flow_manager.get_next_step.return_value = "ASK_ADDRESS"
        self.mock_flow_manager.get_response.return_value = "What is your address?"
        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "What is your address?")
        self.mock_send.reset_mock()

        # 5. Customer provides address
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "123 Main St, Yangon"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "INFO", "address": "123 Main St, Yangon"})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "apple", "qty": 2}, {"name": "banana", "qty": 1}], "name": "John Doe", "phone": "091234567", "address": "123 Main St, Yangon"}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_flow_manager.get_response.return_value = "Your order for 2 apples and 1 banana has been confirmed. Total: $2.50. Payment on delivery."
        
        # Mock product repo for stock deduction
        self.mock_product_repo.get_product_by_name.side_effect = [
            {"id": 1, "name": "apple", "stock": 10},
            {"id": 2, "name": "banana", "stock": 5}
        ]
        self.mock_product_repo.update_product_stock.return_value = None

        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Your order for 2 apples and 1 banana has been confirmed. Total: $2.50. Payment on delivery.")
        self.mock_product_repo.update_product_stock.assert_any_call(1, 2)
        self.mock_product_repo.update_product_stock.assert_any_call(2, 1)
        logging.info("Customer Order Flow (COD): PASSED")

    async def test_customer_order_flow_prepaid(self):
        logging.info("--- Simulating Customer Order Flow (Prepaid) ---")
        merchant_id = self.merchants[1]["id"]
        tg_bot_token = self.merchants[1]["tg_bot_token"]
        chat_id = 2002

        # Mock initial state
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 103, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "orange", "price": 2.0, "stock": 8}
        ]

        # 1. Customer orders items and specifies prepaid
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 3 oranges, prepaid"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "orange", "qty": 3}], "payment_method": "prepaid"})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "orange", "qty": 3}], "payment_method": "prepaid"}
        self.mock_flow_manager.get_next_step.return_value = "ASK_PAYMENT_METHOD"
        self.mock_flow_manager.get_response.return_value = "Please send payment to our QR code."
        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Please send payment to our QR code.")
        self.mock_send.reset_mock()

        # 2. Customer uploads payment screenshot (simulated via webhook)
        # The webhook will enqueue a message, which the worker will then process
        update_id = "67890"
        photo_url = "https://example.com/payment.jpg"
        
        # Mock webhook behavior
        self.mock_idempotency_service.check_and_mark.return_value = False
        self.mock_s3_service.upload_file.return_value = photo_url
        self.mock_telegram_service.get_file_path.return_value = "photos/file_1.jpg"
        self.mock_telegram_service.download_file.return_value = b"dummy_image_data"
        
        # Mock the request for webhook with photo
        mock_request = AsyncMock()
        mock_request.json.return_value = {
            "update_id": update_id,
            "message": {
                "chat": {"id": chat_id},
                "photo": [{"file_id": "file_1", "width": 100, "height": 100}]
            }
        }
        
        # Simulate webhook call for photo upload
        await webhook(shop_id=merchant_id, request=mock_request)

        # Mock the queue_manager.pop to return the task for payment screenshot
        self.mock_queue_repo.fetch_job.return_value = {
            "id": "task_id_456",
            "shop_id": merchant_id,
            "payload": json.dumps({"chat_id": chat_id, "shop_id": merchant_id, "data": {"photo_url": photo_url}})
        }
        
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 103, "extracted_data": {"items": [{"name": "orange", "qty": 3}], "payment_method": "prepaid"}}
        self.mock_flow_manager.get_next_step.return_value = "PAYMENT_RECEIVED_WAITING_REVIEW"
        self.mock_flow_manager.get_response.return_value = "Payment received, waiting for review."
        
        await run_worker()
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Payment received, waiting for review.")
        logging.info("Customer Order Flow (Prepaid): PASSED")

    async def test_stock_deduction_flow(self):
        logging.info("--- Simulating Stock Deduction Flow ---")
        merchant_id = self.merchants[2]["id"]
        tg_bot_token = self.merchants[2]["tg_bot_token"]
        chat_id = 2003

        # Mock initial state with available stock
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 104, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "grape", "price": 3.0, "stock": 15}
        ]

        # Customer orders an item
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 5 grapes"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "grape", "qty": 5}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "grape", "qty": 5}]}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_flow_manager.get_response.return_value = "Order confirmed, 5 grapes deducted from stock."
        
        self.mock_product_repo.get_product_by_name.return_value = {"id": 3, "name": "grape", "stock": 15}
        self.mock_product_repo.update_product_stock.return_value = None

        await self._simulate_worker_cycle(task_payload)
        self.mock_product_repo.update_product_stock.assert_called_once_with(3, 5)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Order confirmed, 5 grapes deducted from stock.")
        logging.info("Stock Deduction Flow: PASSED")

    async def test_out_of_stock_flow(self):
        logging.info("--- Simulating Out of Stock Flow ---")
        merchant_id = self.merchants[3]["id"]
        tg_bot_token = self.merchants[3]["tg_bot_token"]
        chat_id = 2004

        # Mock initial state with insufficient stock
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 105, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "mango", "price": 4.0, "stock": 2}
        ]

        # Customer orders an item with insufficient stock
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 5 mangos"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "mango", "qty": 5}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "mango", "qty": 5}]}
        self.mock_flow_manager.get_next_step.return_value = "OUT_OF_STOCK"
        self.mock_flow_manager.get_response.return_value = "Sorry, mangos are out of stock."
        
        self.mock_product_repo.get_product_by_name.return_value = {"id": 4, "name": "mango", "stock": 2}
        self.mock_product_repo.update_product_stock.reset_mock() # Ensure it's not called

        await self._simulate_worker_cycle(task_payload)
        self.mock_product_repo.update_product_stock.assert_not_called()
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Sorry, mangos are out of stock.")
        logging.info("Out of Stock Flow: PASSED")

    async def test_multi_tenant_isolation(self):
        logging.info("--- Simulating Multi-Tenant Isolation ---")
        merchant_id_1 = self.merchants[4]["id"]
        tg_bot_token_1 = self.merchants[4]["tg_bot_token"]
        chat_id_1 = 2005

        merchant_id_2 = self.merchants[5]["id"]
        tg_bot_token_2 = self.merchants[5]["tg_bot_token"]
        chat_id_2 = 2006

        # Mock data for merchant 1
        self.mock_merchant_repo.get_merchant_by_shop_id.side_effect = [
            {"id": merchant_id_1, "name": "Shop 5", "tg_bot_token": tg_bot_token_1, "is_human_takeover_active": False, "requirements_text": ""},
            {"id": merchant_id_2, "name": "Shop 6", "tg_bot_token": tg_bot_token_2, "is_human_takeover_active": False, "requirements_text": ""}
        ]
        self.mock_order_service.get_or_create_active_order.side_effect = [
            {"id": 106, "extracted_data": {}},
            {"id": 107, "extracted_data": {}}
        ]
        self.mock_merchant_repo.fetch_all.side_effect = [
            [{"name": "item_A", "price": 10.0, "stock": 10}],
            [{"name": "item_B", "price": 20.0, "stock": 5}]
        ]
        self.mock_ai.extract_data.side_effect = [
            json.dumps({"intent": "ORDER", "items": [{"name": "item_A", "qty": 1}]}),
            json.dumps({"intent": "ORDER", "items": [{"name": "item_B", "qty": 1}]})
        ]
        self.mock_ai.merge_data.side_effect = [
            {"items": [{"name": "item_A", "qty": 1}]},
            {"items": [{"name": "item_B", "qty": 1}]}
        ]
        self.mock_flow_manager.get_next_step.side_effect = ["ORDER_CONFIRMED", "ORDER_CONFIRMED"]
        self.mock_flow_manager.get_response.side_effect = [
            "Shop 5: Order for item A confirmed.",
            "Shop 6: Order for item B confirmed."
        ]
        self.mock_product_repo.get_product_by_name.side_effect = [
            {"id": 5, "name": "item_A", "stock": 10},
            {"id": 6, "name": "item_B", "stock": 5}
        ]
        self.mock_product_repo.update_product_stock.return_value = None

        # Simulate order for merchant 1
        task_payload_1 = {"chat_id": chat_id_1, "shop_id": merchant_id_1, "data": {"user_text": "I want item A"}}
        await self._simulate_worker_cycle(task_payload_1)
        self.mock_send.assert_called_with(tg_bot_token_1, chat_id_1, "Shop 5: Order for item A confirmed.")
        self.mock_product_repo.update_product_stock.assert_any_call(5, 1)
        self.mock_send.reset_mock()
        self.mock_product_repo.update_product_stock.reset_mock()

        # Simulate order for merchant 2
        task_payload_2 = {"chat_id": chat_id_2, "shop_id": merchant_id_2, "data": {"user_text": "I want item B"}}
        await self._simulate_worker_cycle(task_payload_2)
        self.mock_send.assert_called_with(tg_bot_token_2, chat_id_2, "Shop 6: Order for item B confirmed.")
        self.mock_product_repo.update_product_stock.assert_any_call(6, 1)
        logging.info("Multi-Tenant Isolation: PASSED")

    async def test_worker_concurrency_issues(self):
        logging.info("--- Simulating Worker Concurrency Issues (Negative Stock) ---")
        merchant_id = self.merchants[6]["id"]
        tg_bot_token = self.merchants[6]["tg_bot_token"]
        chat_id_1 = 2007
        chat_id_2 = 2008

        # Mock initial state with limited stock
        self.mock_order_service.get_or_create_active_order.side_effect = [
            {"id": 108, "extracted_data": {}},
            {"id": 109, "extracted_data": {}}
        ]
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "limited_item", "price": 100.0, "stock": 1}
        ]

        # Two customers try to order the same item, exceeding stock
        task_payload_1 = {"chat_id": chat_id_1, "shop_id": merchant_id, "data": {"user_text": "I want 1 limited_item"}}
        task_payload_2 = {"chat_id": chat_id_2, "shop_id": merchant_id, "data": {"user_text": "I want 1 limited_item"}}

        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "limited_item", "qty": 1}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "limited_item", "qty": 1}]}
        
        # Simulate the race condition for stock deduction
        # The first worker to acquire the lock and process should succeed, the second should fail
        
        # Mock product repo for stock deduction
        product_stock = {"id": 7, "name": "limited_item", "stock": 1}
        self.mock_product_repo.get_product_by_name.return_value = product_stock

        # Simulate the first order succeeding
        self.mock_flow_manager.get_next_step.side_effect = ["ORDER_CONFIRMED", "OUT_OF_STOCK"]
        self.mock_flow_manager.get_response.side_effect = [
            "Order confirmed, 1 limited_item deducted from stock.",
            "Sorry, limited_item is out of stock."
        ]

        # First order
        await self._simulate_worker_cycle(task_payload_1)
        self.mock_product_repo.update_product_stock.assert_called_once_with(7, 1) # Stock deducted
        self.mock_send.assert_called_with(tg_bot_token, chat_id_1, "Order confirmed, 1 limited_item deducted from stock.")
        self.mock_product_repo.update_product_stock.reset_mock()
        self.mock_send.reset_mock()

        # Update mock stock for the second order to reflect deduction
        product_stock["stock"] = 0
        self.mock_product_repo.get_product_by_name.return_value = product_stock

        # Second order (should fail due to out of stock)
        await self._simulate_worker_cycle(task_payload_2)
        self.mock_product_repo.update_product_stock.assert_not_called() # No further deduction
        self.mock_send.assert_called_with(tg_bot_token, chat_id_2, "Sorry, limited_item is out of stock.")
        logging.info("Worker Concurrency Issues (Negative Stock): PASSED")

    async def test_queue_handling_and_retries(self):
        logging.info("--- Simulating Queue Handling and Retries ---")
        merchant_id = self.merchants[7]["id"]
        tg_bot_token = self.merchants[7]["tg_bot_token"]
        chat_id = 2009

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "Test message"}}

        # Simulate a transient failure in the worker (e.g., DB connection issue)
        self.mock_order_service.get_or_create_active_order.side_effect = [Exception("DB Connection Error"), {"id": 110, "extracted_data": {}}]
        
        # First attempt: should fail and be marked for retry
        self.mock_queue_repo.fetch_job.return_value = {
            "id": "task_id_789",
            "shop_id": merchant_id,
            "payload": json.dumps(task_payload),
            "retry_count": 0
        }
        self.mock_queue_repo.mark_failed.return_value = None
        self.mock_queue_repo.mark_completed.return_value = None

        await run_worker()
        self.mock_queue_repo.mark_failed.assert_called_once_with("task_id_789", "DB Connection Error", can_retry=True)
        self.mock_queue_repo.mark_failed.reset_mock()

        # Second attempt: should succeed
        self.mock_queue_repo.fetch_job.return_value = {
            "id": "task_id_789",
            "shop_id": merchant_id,
            "payload": json.dumps(task_payload),
            "retry_count": 1
        }
        self.mock_flow_manager.get_next_step.return_value = "GREETING"
        self.mock_flow_manager.get_response.return_value = "Hello again!"
        
        await run_worker()
        self.mock_queue_repo.mark_completed.assert_called_once_with("task_id_789")
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Hello again!")
        logging.info("Queue Handling and Retries: PASSED")

    async def test_state_transition_bugs(self):
        logging.info("--- Simulating State Transition Bugs ---")
        merchant_id = self.merchants[8]["id"]
        tg_bot_token = self.merchants[8]["tg_bot_token"]
        chat_id = 2010

        # Simulate an order that tries to transition from NEW_CHAT to PAYMENT_CONFIRMED directly
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 111, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "item_C", "price": 1.0, "stock": 10}
        ]

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 1 item_C and here is my payment"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "item_C", "qty": 1}], "payment_method": "prepaid"})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "item_C", "qty": 1}], "payment_method": "prepaid"}
        
        # Simulate a direct jump to ORDER_CONFIRMED without intermediate steps
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_flow_manager.get_response.return_value = "Order confirmed, but payment not yet reviewed."

        self.mock_product_repo.get_product_by_name.return_value = {"id": 8, "name": "item_C", "stock": 10}
        self.mock_product_repo.update_product_stock.return_value = None

        await self._simulate_worker_cycle(task_payload)
        # The system should handle this gracefully, potentially by correcting the state or logging a warning
        # The previous fix for state transition bugs should prevent a crash here.
        self.mock_order_service.update_status.assert_called_with(111, "PAYMENT_CONFIRMED", "bot", "Order confirmed and stock deducted")
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "Order confirmed, but payment not yet reviewed.")
        logging.info("State Transition Bugs: PASSED (handled gracefully)")

    async def test_data_corruption_risks(self):
        logging.info("--- Simulating Data Corruption Risks (Invalid JSON) ---")
        merchant_id = self.merchants[9]["id"]
        tg_bot_token = self.merchants[9]["tg_bot_token"]
        chat_id = 2011

        # Simulate AI returning malformed JSON
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 112, "extracted_data": {}}
        self.mock_ai.extract_data.return_value = "{invalid json"
        self.mock_flow_manager.get_next_step.return_value = "GREETING"
        self.mock_flow_manager.get_response.return_value = "I didn't understand that. Can you please rephrase?"

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "Some text"}}
        await self._simulate_worker_cycle(task_payload)

        # The system should handle the invalid JSON gracefully and not crash
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "I didn't understand that. Can you please rephrase?")
        logging.info("Data Corruption Risks (Invalid JSON): PASSED (handled gracefully)")

    async def test_ai_extraction_failure_cases(self):
        logging.info("--- Simulating AI Extraction Failure Cases ---")
        merchant_id = self.merchants[0]["id"]
        tg_bot_token = self.merchants[0]["tg_bot_token"]
        chat_id = 2012

        # Simulate AI raising an exception during extraction
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 113, "extracted_data": {}}
        self.mock_ai.extract_data.side_effect = Exception("AI Service Down")
        self.mock_flow_manager.get_next_step.return_value = "GREETING"
        self.mock_flow_manager.get_response.return_value = "I'm sorry, I'm having trouble understanding right now. Please try again later."

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "Order some food"}}
        await self._simulate_worker_cycle(task_payload)

        # The system should catch the AI exception and send a fallback message
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "I'm sorry, I'm having trouble understanding right now. Please try again later.")
        logging.info("AI Extraction Failure Cases: PASSED (handled gracefully)")

    async def test_human_takeover_flow(self):
        logging.info("--- Simulating Human Takeover Flow ---")
        merchant_id = self.merchants[1]["id"]
        tg_bot_token = self.merchants[1]["tg_bot_token"]
        chat_id = 2013

        # Simulate a user requesting human takeover
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 114, "extracted_data": {}}
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": merchant_id, "name": "Shop 2", "tg_bot_token": tg_bot_token, "is_human_takeover_active": False, "requirements_text": ""}
        self.mock_flow_manager.get_next_step.return_value = "HUMAN_TAKEOVER"
        self.mock_flow_manager.get_response.return_value = "A human agent will be with you shortly."

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want to talk to a human"}}
        await self._simulate_worker_cycle(task_payload)

        # Verify human takeover flag is set and audit log is created
        self.mock_merchant_repo.execute.assert_called_with("UPDATE businesses SET is_human_takeover_active = TRUE WHERE id = $1", merchant_id)
        self.mock_audit_repo.log_event.assert_called_with("HUMAN_TAKEOVER_START", "bot", "User requested human", 114)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "A human agent will be with you shortly.")
        logging.info("Human Takeover Flow: PASSED")

    async def test_duplicate_webhook_messages(self):
        logging.info("--- Simulating Duplicate Webhook / Duplicate Message Cases ---")
        merchant_id = self.merchants[2]["id"]
        chat_id = 2014
        update_id = "duplicate_123"
        message_text = "Duplicate message test"

        # Mock the request for webhook
        mock_request = AsyncMock()
        mock_request.json.return_value = {
            "update_id": update_id,
            "message": {
                "chat": {"id": chat_id},
                "text": message_text
            }
        }

        # First message: should be processed normally
        self.mock_idempotency_service.check_and_mark.return_value = False
        self.mock_queue_manager_webhook.push.return_value = None
        await webhook(shop_id=merchant_id, request=mock_request)
        self.mock_queue_manager_webhook.push.assert_called_once()
        self.mock_queue_manager_webhook.push.reset_mock()

        # Second message with same update_id: should be ignored by idempotency service
        self.mock_idempotency_service.check_and_mark.return_value = True
        await webhook(shop_id=merchant_id, request=mock_request)
        self.mock_queue_manager_webhook.push.assert_not_called()
        logging.info("Duplicate Webhook Messages: PASSED")

    async def test_abandoned_order_cases(self):
        logging.info("--- Simulating Abandoned Order Cases ---")
        merchant_id = self.merchants[3]["id"]
        tg_bot_token = self.merchants[3]["tg_bot_token"]
        chat_id = 2015

        # Simulate an order that is started but not completed
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 115, "extracted_data": {"items": [{"name": "item_D", "qty": 1}]}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "item_D", "price": 1.0, "stock": 10}
        ]

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 1 item_D"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "item_D", "qty": 1}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "item_D", "qty": 1}]}
        self.mock_flow_manager.get_next_step.return_value = "ASK_NAME"
        self.mock_flow_manager.get_response.return_value = "What is your name?"

        await self._simulate_worker_cycle(task_payload)
        self.mock_send.assert_called_with(tg_bot_token, chat_id, "What is your name?")
        
        # Simulate no further interaction for a long time (worker should not process again)
        # This scenario is more about external cleanup or timeout mechanisms, which are not directly in the worker loop
        # For simulation, we'll assert that no further actions are taken by the worker for this order
        self.mock_send.reset_mock()
        self.mock_order_service.update_status.reset_mock()

        # If the worker runs again for this order without new input, it should ideally not send a new message
        # or change status unless a specific timeout mechanism is implemented.
        # For this simulation, we'll just ensure no new messages are sent.
        task_payload_no_input = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": ""}}
        self.mock_queue_repo.fetch_job.return_value = {
            "id": "task_id_abandoned",
            "shop_id": merchant_id,
            "payload": json.dumps(task_payload_no_input)
        }
        self.mock_flow_manager.get_next_step.return_value = "ASK_NAME" # Still waiting for name
        self.mock_flow_manager.get_response.return_value = "What is your name?"
        
        await run_worker()
        self.mock_send.assert_not_called() # No new message should be sent if no new input
        logging.info("Abandoned Order Cases: PASSED (no new messages sent)")

    async def test_merchant_dashboard_visibility(self):
        logging.info("--- Simulating Merchant Dashboard & Internal Ops Console Visibility ---")
        merchant_id = self.merchants[4]["id"]
        chat_id = 2016

        # Simulate an order being processed
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 116, "extracted_data": {}}
        self.mock_merchant_repo.fetch_all.return_value = [
            {"name": "item_E", "price": 1.0, "stock": 10}
        ]
        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "I want 1 item_E"}}
        self.mock_ai.extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "item_E", "qty": 1}]})
        self.mock_ai.merge_data.return_value = {"items": [{"name": "item_E", "qty": 1}]}
        self.mock_flow_manager.get_next_step.return_value = "ORDER_CONFIRMED"
        self.mock_flow_manager.get_response.return_value = "Order confirmed."
        self.mock_product_repo.get_product_by_name.return_value = {"id": 9, "name": "item_E", "stock": 10}
        self.mock_product_repo.update_product_stock.return_value = None

        await self._simulate_worker_cycle(task_payload)

        # Verify that order status updates and audit logs are recorded
        self.mock_order_service.update_status.assert_called_with(116, "PAYMENT_CONFIRMED", "bot", "Order confirmed and stock deducted")
        self.mock_audit_repo.log_event.assert_called_with("BOT_REPLY", "bot", "Replied with ORDER_CONFIRMED", 116, {"reply": "Order confirmed."})
        logging.info("Merchant Dashboard & Internal Ops Console Visibility: PASSED (status and audit logs recorded)")

    async def test_audit_logs_correctness(self):
        logging.info("--- Simulating Audit Logs Correctness ---")
        merchant_id = self.merchants[5]["id"]
        chat_id = 2017

        # Simulate a human takeover event
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 117, "extracted_data": {}}
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": merchant_id, "name": "Shop 6", "tg_bot_token": "token_6", "is_human_takeover_active": False, "requirements_text": ""}
        self.mock_flow_manager.get_next_step.return_value = "HUMAN_TAKEOVER"
        self.mock_flow_manager.get_response.return_value = "Human takeover initiated."

        task_payload = {"chat_id": chat_id, "shop_id": merchant_id, "data": {"user_text": "Human help"}}
        await self._simulate_worker_cycle(task_payload)

        # Verify that the audit log for human takeover is correctly recorded
        self.mock_audit_repo.log_event.assert_called_with("HUMAN_TAKEOVER_START", "bot", "User requested human", 117)
        logging.info("Audit Logs Correctness: PASSED (human takeover logged)")


if __name__ == "__main__":
    unittest.main()
