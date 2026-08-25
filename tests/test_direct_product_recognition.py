import json
import unittest
from unittest.mock import AsyncMock, patch

from app.services.ai_parser import AIParser


class TestDirectProductRecognition(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.parser = AIParser()
        self.menu = [{"name": "Integration QA Product", "price": 10, "stock": 7}]
        self.context = {"shop_name": "Integration QA Merchant", "previous_data": {}}

    async def test_exact_product_request_enters_order_flow_without_ai(self):
        with patch("app.services.ai_parser.ai.extract_data", new=AsyncMock()) as extract:
            result = await self.parser.parse_message(
                "Integration QA Product",
                self.context,
                self.menu,
                current_state="WELCOME",
            )

        self.assertEqual(result["intent"], "ORDER")
        self.assertEqual(result["items"][0]["name"], "Integration QA Product")
        self.assertEqual(result["items"][0]["qty"], 1)
        extract.assert_not_awaited()

    async def test_direct_product_request_preserves_explicit_quantity(self):
        for text, expected_qty in (
            ("2 Integration QA Product", 2),
            ("Integration QA Product x 3", 3),
            ("I want Integration QA Product", 1),
        ):
            with self.subTest(text=text), patch(
                "app.services.ai_parser.ai.extract_data",
                new=AsyncMock(return_value=json.dumps({"intent": "OTHER", "items": []})),
            ) as extract:
                result = await self.parser.parse_message(
                    text,
                    self.context,
                    self.menu,
                    current_state="WELCOME",
                )

            self.assertEqual(result["intent"], "ORDER")
            self.assertEqual(result["items"][0]["name"], "Integration QA Product")
            self.assertEqual(result["items"][0]["qty"], expected_qty)
            extract.assert_not_awaited()

    async def test_unknown_product_still_uses_existing_ai_path(self):
        with patch(
            "app.services.ai_parser.ai.extract_data",
            new=AsyncMock(return_value=json.dumps({"intent": "OTHER", "items": []})),
        ) as extract:
            result = await self.parser.parse_message(
                "Unknown QA Product",
                self.context,
                self.menu,
                current_state="WELCOME",
            )

        self.assertEqual(result["intent"], "OTHER")
        extract.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
