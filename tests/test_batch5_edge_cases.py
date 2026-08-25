import importlib
import unittest
from unittest.mock import AsyncMock, patch

webhook_module = importlib.import_module("app.api.webhook")


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class TestBatch5EdgeCases(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        webhook_module._recent_messages.clear()
        webhook_module._chat_message_windows.clear()

    def test_meaningful_text_preserves_burmese_and_mixed_input(self):
        self.assertFalse(webhook_module._has_meaningful_text("   "))
        self.assertFalse(webhook_module._has_meaningful_text("🙂👍"))
        self.assertTrue(webhook_module._has_meaningful_text("မင်္ဂလာပါ hello"))
        self.assertTrue(webhook_module._has_meaningful_text("09-123456789"))

    def test_duplicate_and_spam_guard(self):
        self.assertFalse(webhook_module._is_duplicate_or_spam("shop", 1, "hello"))
        self.assertTrue(webhook_module._is_duplicate_or_spam("shop", 1, "hello"))
        for index in range(webhook_module._CHAT_MESSAGE_LIMIT - 1):
            self.assertFalse(webhook_module._is_duplicate_or_spam("shop", 2, f"message-{index}"))
        self.assertFalse(webhook_module._is_duplicate_or_spam("shop", 2, "message-final"))
        self.assertTrue(webhook_module._is_duplicate_or_spam("shop", 2, "message-over-limit"))

    async def test_empty_and_emoji_text_are_acknowledged_without_queueing(self):
        for update_id, text in ((1001, "   "), (1002, "🙂👍")):
            request = FakeRequest({
                "update_id": update_id,
                "message": {"chat": {"id": 10 + update_id}, "text": text},
            })
            with patch.object(webhook_module, "get_db_pool", new=AsyncMock(return_value=object())), \
                 patch.object(webhook_module, "MerchantRepository") as merchant_cls, \
                 patch.object(webhook_module, "IdempotencyRepository") as idem_repo_cls, \
                 patch.object(webhook_module, "IdempotencyService") as idem_service_cls, \
                 patch.object(webhook_module, "send", new=AsyncMock()) as send_mock:
                merchant_cls.return_value.get_merchant_by_shop_id = AsyncMock(return_value={"tg_bot_token": "token"})
                idem_repo_cls.return_value.is_processed = AsyncMock(return_value=False)
                idem_service_cls.return_value.check_and_mark = AsyncMock(return_value=False)
                result = await webhook_module.webhook("shop", request)
                self.assertEqual(result, {"ok": True})
                send_mock.assert_awaited_once()

    async def test_unsupported_voice_gets_recovery_reply(self):
        request = FakeRequest({
            "update_id": 1100,
            "message": {"chat": {"id": 20}, "voice": {"file_id": "voice-1"}},
        })
        with patch.object(webhook_module, "get_db_pool", new=AsyncMock(return_value=object())), \
             patch.object(webhook_module, "MerchantRepository") as merchant_cls, \
             patch.object(webhook_module, "IdempotencyRepository") as idem_repo_cls, \
                 patch.object(webhook_module, "IdempotencyService") as idem_service_cls, \
                 patch.object(webhook_module, "send", new=AsyncMock()) as send_mock:
            merchant_cls.return_value.get_merchant_by_shop_id = AsyncMock(return_value={"tg_bot_token": "token"})
            idem_repo_cls.return_value.is_processed = AsyncMock(return_value=False)
            idem_service_cls.return_value.check_and_mark = AsyncMock(return_value=False)
            result = await webhook_module.webhook("shop", request)
            self.assertEqual(result, {"ok": True})
            self.assertIn("text messages", send_mock.await_args.args[2])

    async def test_cod_photo_is_not_uploaded_as_payment_screenshot(self):
        request = FakeRequest({
            "update_id": 1200,
            "message": {"chat": {"id": 30}, "photo": [{"file_id": "photo-1"}]},
        })
        with patch.object(webhook_module, "get_db_pool", new=AsyncMock(return_value=object())), \
             patch.object(webhook_module, "MerchantRepository") as merchant_cls, \
             patch.object(webhook_module, "IdempotencyRepository") as idem_repo_cls, \
                              patch.object(webhook_module, "IdempotencyService") as idem_service_cls, \
             patch.object(webhook_module, "OrderRepository"), \
             patch.object(webhook_module, "OrderService") as order_service_cls, \
             patch.object(webhook_module, "send", new=AsyncMock()) as send_mock, \
             patch("app.services.lock_manager.LockRepository"), \
             patch("app.services.lock_manager.LockManager") as lock_cls:

            merchant_cls.return_value.get_merchant_by_shop_id = AsyncMock(return_value={"id": 1, "tg_bot_token": "token"})
            idem_repo_cls.return_value.is_processed = AsyncMock(return_value=False)
            idem_service_cls.return_value.check_and_mark = AsyncMock(return_value=False)
            order_service_cls.return_value.get_or_create_active_order = AsyncMock(return_value={"id": 1, "extracted_data": {"payment_method": "COD"}})
            lock_cls.return_value.acquire = AsyncMock(return_value=True)
            lock_cls.return_value.release = AsyncMock()
            result = await webhook_module.webhook("shop", request)
            self.assertEqual(result, {"ok": True})
            self.assertIn("not using prepaid", send_mock.await_args.args[2])

    def test_worker_malformed_input_recovery_guard_exists(self):
        from app.workers.order_worker import has_meaningful_text
        self.assertFalse(has_meaningful_text("🙂"))
        self.assertTrue(has_meaningful_text("မြန်မာ English"))


if __name__ == "__main__":
    unittest.main()
