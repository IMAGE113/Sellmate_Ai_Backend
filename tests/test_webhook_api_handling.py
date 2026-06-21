
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.webhook import webhook
from app.db.database import get_db_pool, MerchantRepository, AuditRepository, OrderRepository
from app.services.idempotency_service import IdempotencyRepository, IdempotencyService
from app.services.queue_manager import QueueRepository, QueueManager
from app.services.s3_service import S3Service
from app.services.telegram_service import TelegramService
from app.services.order_service import OrderService

class TestWebhookApiHandling(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_pool = AsyncMock()
        self.mock_merchant_repo = AsyncMock(spec=MerchantRepository)
        self.mock_audit_repo = AsyncMock(spec=AuditRepository)
        self.mock_order_repo = AsyncMock(spec=OrderRepository)
        self.mock_idempotency_repo = AsyncMock(spec=IdempotencyRepository)
        self.mock_queue_repo = AsyncMock(spec=QueueRepository)

        self.mock_idempotency_service = AsyncMock(spec=IdempotencyService)
        self.mock_queue_manager = AsyncMock(spec=QueueManager)
        self.mock_s3_service = AsyncMock(spec=S3Service)
        self.mock_telegram_service = AsyncMock(spec=TelegramService)
        self.mock_order_service = AsyncMock(spec=OrderService)

        # Patching dependencies for webhook
        patcher_get_db_pool = patch("app.api.webhook.get_db_pool", new_callable=AsyncMock)
        self.mock_get_db_pool = patcher_get_db_pool.start()
        self.mock_get_db_pool.return_value = self.mock_pool
        self.addCleanup(patcher_get_db_pool.stop)

        patcher_MerchantRepository = patch("app.api.webhook.MerchantRepository", return_value=self.mock_merchant_repo)
        self.mock_MerchantRepository = patcher_MerchantRepository.start()
        self.addCleanup(patcher_MerchantRepository.stop)

        patcher_AuditRepository = patch("app.api.webhook.AuditRepository", return_value=self.mock_audit_repo)
        self.mock_AuditRepository = patcher_AuditRepository.start()
        self.addCleanup(patcher_AuditRepository.stop)

        patcher_OrderRepository = patch("app.api.webhook.OrderRepository", return_value=self.mock_order_repo)
        self.mock_OrderRepository = patcher_OrderRepository.start()
        self.addCleanup(patcher_OrderRepository.stop)

        patcher_IdempotencyRepository = patch("app.api.webhook.IdempotencyRepository", return_value=self.mock_idempotency_repo)
        self.mock_IdempotencyRepository = patcher_IdempotencyRepository.start()
        self.addCleanup(patcher_IdempotencyRepository.stop)

        patcher_IdempotencyService = patch("app.api.webhook.IdempotencyService", return_value=self.mock_idempotency_service)
        self.mock_IdempotencyService = patcher_IdempotencyService.start()
        self.addCleanup(patcher_IdempotencyService.stop)

        patcher_QueueRepository = patch("app.api.webhook.QueueRepository", return_value=self.mock_queue_repo)
        self.mock_QueueRepository = patcher_QueueRepository.start()
        self.addCleanup(patcher_QueueRepository.stop)

        patcher_QueueManager = patch("app.api.webhook.QueueManager", return_value=self.mock_queue_manager)
        self.mock_QueueManager = patcher_QueueManager.start()
        self.addCleanup(patcher_QueueManager.stop)

        patcher_s3_service = patch("app.api.webhook.s3_service", new=self.mock_s3_service)
        self.mock_s3_service_patch = patcher_s3_service.start()
        self.addCleanup(patcher_s3_service.stop)

        patcher_telegram_service = patch("app.api.webhook.telegram_service", new=self.mock_telegram_service)
        self.mock_telegram_service_patch = patcher_telegram_service.start()
        self.addCleanup(patcher_telegram_service.stop)

        patcher_OrderService = patch("app.api.webhook.OrderService", return_value=self.mock_order_service)
        self.mock_OrderService = patcher_OrderService.start()
        self.addCleanup(patcher_OrderService.stop)

        # Mock Request object
        self.mock_request = AsyncMock()
        self.mock_request.json.return_value = {}

    # Test for webhook_receiver (text message)
    async def test_webhook_text_message(self):
        self.mock_request.json.return_value = {
            "update_id": 123,
            "message": {"chat": {"id": 456}, "text": "Hello"}
        }
        self.mock_idempotency_service.check_and_mark.return_value = False
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "tg_bot_token": "token"}
        self.mock_queue_manager.push.return_value = None

        response = await webhook("shop1", self.mock_request)
        self.assertEqual(response, {"ok": True})
        self.mock_idempotency_service.check_and_mark.assert_called_once_with(123)
        self.mock_merchant_repo.get_merchant_by_shop_id.assert_called_once_with()
        self.mock_queue_manager.push.assert_called_once()

    # Test for webhook_receiver (photo message - payment screenshot)
    async def test_webhook_photo_message(self):
        self.mock_request.json.return_value = {
            "update_id": 124,
            "message": {
                "chat": {"id": 457},
                "photo": [{"file_id": "file_abc", "width": 100, "height": 100}]
            }
        }
        self.mock_idempotency_service.check_and_mark.return_value = False
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = {"id": 1, "tg_bot_token": "token"}
        self.mock_telegram_service.get_file_path.return_value = "photos/file_abc.jpg"
        self.mock_telegram_service.download_file.return_value = b"image_content"
        self.mock_s3_service.upload_file.return_value = "https://s3.url/image.jpg"
        self.mock_order_service.get_or_create_active_order.return_value = {"id": 102, "extracted_data": {}}
        self.mock_order_repo.execute.return_value = None
        self.mock_audit_repo.log_event.return_value = None
        self.mock_queue_manager.push.return_value = None

        response = await webhook("shop1", self.mock_request)
        self.assertEqual(response, {"ok": True})
        self.mock_telegram_service.get_file_path.assert_called_once_with("token", "file_abc")
        self.mock_telegram_service.download_file.assert_called_once_with("token", "photos/file_abc.jpg")
        self.mock_s3_service.upload_file.assert_called_once()
        self.mock_order_service.get_or_create_active_order.assert_called_once_with(457, 1)
        self.mock_order_repo.execute.assert_called_once()
        self.mock_audit_repo.log_event.assert_called_once()
        self.mock_queue_manager.push.assert_called_once()

    # Test for webhook_receiver (duplicate update_id)
    async def test_webhook_duplicate_update_id(self):
        self.mock_request.json.return_value = {"update_id": 125, "message": {"chat": {"id": 458}, "text": "Duplicate"}}
        self.mock_idempotency_service.check_and_mark.return_value = True

        response = await webhook("shop1", self.mock_request)
        self.assertEqual(response, {"ok": True})
        self.mock_idempotency_service.check_and_mark.assert_called_once_with(125)
        self.mock_merchant_repo.get_merchant_by_shop_id.assert_not_called()

    # Test for webhook_receiver (merchant not found)
    async def test_webhook_merchant_not_found(self):
        self.mock_request.json.return_value = {"update_id": 126, "message": {"chat": {"id": 459}, "text": "Test"}}
        self.mock_idempotency_service.check_and_mark.return_value = False
        self.mock_merchant_repo.get_merchant_by_shop_id.return_value = None

        with self.assertRaises(HTTPException) as cm:
            await webhook("shop_unknown", self.mock_request)
        # It raises 500 because the exception handler catches the 404 and raises 500
        self.assertEqual(cm.exception.status_code, 500)

    # Test for webhook_receiver (internal server error)
    async def test_webhook_internal_server_error(self):
        self.mock_request.json.return_value = {"update_id": 127, "message": {"chat": {"id": 460}, "text": "Error"}}
        self.mock_idempotency_service.check_and_mark.side_effect = Exception("DB Error")

        with self.assertRaises(HTTPException) as cm:
            await webhook("shop1", self.mock_request)
        self.assertEqual(cm.exception.status_code, 500)
        self.assertEqual(cm.exception.detail, "Internal Server Error")

    # Test for S3Service.upload_file
    async def test_s3_service_upload_file(self):
        mock_s3_client = MagicMock()
        mock_s3_client.put_object.return_value = {"ResponseMetadata": {"HTTPStatusCode": 200}}
        mock_s3_client.meta.region_name = "ap-southeast-1"
        with patch("boto3.client", return_value=mock_s3_client), \
             patch.dict("os.environ", {"S3_BUCKET_NAME": "test-bucket"}):
            s3_service_instance = S3Service()
            url = await s3_service_instance.upload_file(b"test content", "test/object.txt")
            self.assertIn("test-bucket", url)
            self.assertIn("test/object.txt", url)
            mock_s3_client.put_object.assert_called_once_with(
                Bucket="test-bucket",
                Key="test/object.txt",
                Body=b"test content"
            )

    # Test for TelegramService.download_file
    async def test_telegram_service_download_file(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"downloaded content"
        
        mock_httpx_client = MagicMock()
        mock_httpx_client.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        
        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            telegram_service_instance = TelegramService()
            content = await telegram_service_instance.download_file("test_token", "file_path")
            self.assertEqual(content, b"downloaded content")

    # Test for QueueManager.push (indirectly tested by webhook_text_message and webhook_photo_message)
    # Adding a direct test for completeness
    async def test_queue_manager_push(self):
        mock_pool = AsyncMock()
        mock_queue_repo = AsyncMock(spec=QueueRepository)
        mock_queue_repo.enqueue.return_value = None
        
        with patch("app.services.queue_manager.QueueRepository", return_value=mock_queue_repo):
            queue_manager = QueueManager(mock_queue_repo, "test_worker")
            payload = MagicMock()
            await queue_manager.push("inbound_messages", payload)
            mock_queue_repo.enqueue.assert_called_once()

if __name__ == "__main__":
    unittest.main()
