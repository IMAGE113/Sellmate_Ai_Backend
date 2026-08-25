import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers import order_worker


class TestHumanTakeoverRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_start_clears_takeover_and_resumes_greeting(self):
        class StopWorker(Exception):
            pass

        pool = MagicMock()
        queue = MagicMock()
        queue.pop = AsyncMock(return_value={
            "id": 88,
            "shop_id": "shop-a",
            "payload": json.dumps({"chat_id": 900, "data": {"user_text": "/start"}}),
        })
        queue.complete = AsyncMock()
        queue.fail = AsyncMock()

        monitor = MagicMock(run_recovery=AsyncMock(), heartbeat=AsyncMock())
        merchant_repo = MagicMock()
        merchant_repo.get_merchant_by_shop_id = AsyncMock(return_value={
            "id": 1,
            "shop_id": "shop-a",
            "name": "Shop A",
            "tg_bot_token": "token",
            "status": "ACTIVE",
            "is_human_takeover_active": True,
        })
        merchant_repo.set_human_takeover = AsyncMock()
        merchant_repo.fetch_all = AsyncMock(return_value=[])

        order_repo = MagicMock()
        order_repo.get_active_order_by_chat_id = AsyncMock(return_value={
            "id": 123,
            "status": "COLLECTING_INFO",
            "extracted_data": {"items": []},
        })
        order_repo.execute = AsyncMock()
        order_service = MagicMock()
        order_service.update_status = AsyncMock()
        order_service.get_or_create_active_order = AsyncMock(return_value={
            "id": 124,
            "status": "NEW_CHAT",
            "extracted_data": {"items": []},
        })

        lifecycle = MagicMock(validate_active=AsyncMock())
        lock = MagicMock(acquire=AsyncMock(return_value=True), release=AsyncMock())

        async def stop_sleep(_):
            raise StopWorker()

        with patch.object(order_worker, "get_db_pool", new=AsyncMock(return_value=pool)), \
             patch.object(order_worker, "WorkerMonitor", return_value=monitor), \
             patch.object(order_worker, "QueueManager", return_value=queue), \
             patch.object(order_worker, "MerchantRepository", return_value=merchant_repo), \
             patch.object(order_worker, "OrderRepository", return_value=order_repo), \
             patch.object(order_worker, "OrderService", return_value=order_service), \
             patch.object(order_worker, "LifecycleService", return_value=lifecycle), \
             patch.object(order_worker, "LockManager", return_value=lock), \
             patch.object(order_worker, "send", new=AsyncMock()) as send_mock, \
             patch.object(order_worker.ai_parser, "detect_greeting", return_value=False), \
             patch.object(order_worker.ai_parser, "parse_message", new=AsyncMock(return_value={"intent": "GREETING"})), \
             patch.object(order_worker.rate_limiter, "validate_merchant_message"), \
             patch.object(order_worker.rate_limiter, "validate_ai_usage"), \
             patch.object(order_worker.asyncio, "sleep", new=stop_sleep):
            with self.assertRaises(StopWorker):
                await order_worker.run_worker()

        merchant_repo.set_human_takeover.assert_awaited_once_with(False)
        queue.complete.assert_awaited_once_with(88)
        queue.fail.assert_not_awaited()
        lock.release.assert_awaited_once_with(900)
        self.assertNotIn("Admin", send_mock.await_args.args[2])


if __name__ == "__main__":
    unittest.main()
