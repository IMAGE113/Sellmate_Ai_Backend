import importlib
import unittest
from unittest.mock import AsyncMock, patch

from app.services.ai import AI
from app.services.ai_parser import AIParser
from app.services.script_service import ScriptService
from app.services.telegram import send
from app.workflow.flow_manager import FlowManager

webhook_module = importlib.import_module("app.api.webhook")


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class TestBatch6Readiness(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        webhook_module._recent_messages.clear()
        webhook_module._chat_message_windows.clear()

    def test_conversation_walkthrough_has_no_skipped_core_states(self):
        settings = {"setting_require_payment_screenshot": True}
        states = [
            "ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP",
            "ASK_PAYMENT_METHOD", "ASK_PAYMENT_SCREENSHOT", "ORDER_SUMMARY",
        ]
        data = {"items": [{"name": "shirt", "qty": 1}]}
        observed = []
        for field, value in [
            ("customer_name", "Aung"),
            ("phone_no", "09123456789"),
            ("address", "No. 1 Main Road"),
            ("township", "Bahan"),
            ("payment_method", "Prepaid"),
        ]:
            flow = FlowManager(settings, data)
            observed.append(flow.get_current_state())
            data[field] = value
        observed.append(FlowManager(settings, data).get_current_state())
        data["payment_screenshot_received"] = True
        observed.append(FlowManager(settings, data).get_current_state())
        self.assertEqual(observed, states)

    async def test_intent_fast_paths_are_state_gated(self):
        parser = AIParser()
        for state, text in (("ASK_NAME", "hello"), ("ASK_PHONE", "ok"), ("ORDER_SUMMARY", "look at this")):
            result = await parser.parse_message(text, {}, [], current_state=state)
            self.assertNotIn(result.get("intent"), {"GREETING", "CONFIRM_ORDER"})

    def test_cart_limit_is_enforced(self):
        normalized = AI().normalize_extracted_data({
            "items": [{"name": f"item-{i}", "qty": 1} for i in range(150)]
        })
        self.assertEqual(len(normalized["items"]), AI.MAX_CART_LINES)

    async def test_script_formatting_does_not_expose_unknown_placeholder(self):
        repo = AsyncMock()
        repo.shop_id = "shop"
        repo.get_merchant_script.return_value = "Hello {known} {missing}"
        service = ScriptService(repo)
        result = await service.get_script("GREETING", known="customer")
        self.assertEqual(result, "Hello customer ")
        self.assertNotIn("{missing}", result)

    async def test_telegram_send_caps_outbound_text(self):
        response = type("Response", (), {"status_code": 200, "json": lambda self: {}})()
        with patch("app.services.telegram.http_client.post", new=AsyncMock(return_value=response)) as post:
            await send("token", 1, "x" * 5000)
            sent_text = post.call_args.kwargs["json"]["text"]
            self.assertEqual(len(sent_text), 4096)
            self.assertTrue(sent_text.endswith("..."))

    async def test_forwarded_text_gets_recovery_reply(self):
        request = FakeRequest({
            "update_id": 6100,
            "message": {"chat": {"id": 61}, "text": "my address", "forward_origin": {"type": "user"}},
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
            self.assertIn("forwarding", send_mock.await_args.args[2])


if __name__ == "__main__":
    unittest.main()
