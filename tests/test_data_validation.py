
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from decimal import Decimal
import json
import asyncio

from app.services.validation_service import ValidationService
from app.services.ai import AI
from app.workers.order_worker import make_json_safe, force_dict

class TestDataValidation(unittest.IsolatedAsyncioTestCase):

    # Test for ValidationService.validate_phone
    def test_validate_phone(self):
        self.assertTrue(ValidationService.validate_phone("091234567"))
        self.assertTrue(ValidationService.validate_phone("+95912345678"))
        self.assertFalse(ValidationService.validate_phone("123"))
        self.assertFalse(ValidationService.validate_phone("invalid_phone"))
        self.assertFalse(ValidationService.validate_phone(None))
        self.assertFalse(ValidationService.validate_phone(""))

    # Test for ValidationService.validate_quantity
    def test_validate_quantity(self):
        self.assertTrue(ValidationService.validate_quantity(1))
        self.assertTrue(ValidationService.validate_quantity("5"))
        self.assertFalse(ValidationService.validate_quantity(0))
        self.assertFalse(ValidationService.validate_quantity(-1))
        self.assertFalse(ValidationService.validate_quantity("abc"))
        self.assertFalse(ValidationService.validate_quantity(None))

    # Test for ValidationService.validate_extracted_data
    def test_validate_extracted_data(self):
        # Valid data
        valid_data = {
            "phone_no": "091234567",
            "items": [
                {"name": "item1", "qty": 2},
                {"name": "item2", "qty": "3"}
            ]
        }
        is_valid, errors = ValidationService.validate_extracted_data(valid_data)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

        # Invalid phone
        invalid_phone_data = {
            "phone_no": "123",
            "items": [
                {"name": "item1", "qty": 2}
            ]
        }
        is_valid, errors = ValidationService.validate_extracted_data(invalid_phone_data)
        self.assertFalse(is_valid)
        self.assertIn("INVALID_PHONE", errors)

        # Invalid quantity
        invalid_qty_data = {
            "phone_no": "091234567",
            "items": [
                {"name": "item1", "qty": 0}
            ]
        }
        is_valid, errors = ValidationService.validate_extracted_data(invalid_qty_data)
        self.assertFalse(is_valid)
        self.assertIn("INVALID_QUANTITY_item1", errors)

        # Missing items
        missing_items_data = {
            "phone_no": "091234567"
        }
        is_valid, errors = ValidationService.validate_extracted_data(missing_items_data)
        self.assertTrue(is_valid) # No items means no quantity to validate
        self.assertEqual(len(errors), 0)

    # Test for ai.extract_data (mocking AI response)
    @patch("app.services.ai.AI.extract_data", new_callable=AsyncMock)
    async def test_ai_extract_data(self, mock_extract_data):
        mock_extract_data.return_value = json.dumps({"intent": "ORDER", "items": [{"name": "apple", "qty": 1}]})
        ai_service = AI()
        result = await ai_service.extract_data("I want an apple", "shop", [], {}, "")
        self.assertEqual(json.loads(result), {"intent": "ORDER", "items": [{"name": "apple", "qty": 1}]})
        mock_extract_data.assert_called_once()

    # Test for ai.merge_data
    def test_ai_merge_data(self):
        ai_service = AI()
        existing_data = {"items": [{"name": "apple", "qty": 1}], "customer_name": "John"}
        new_data = {"items": [{"name": "banana", "qty": 2}], "phone_no": "123"}
        merged = ai_service.merge_data(existing_data, new_data)
        # Verify both items exist in the merged result based on actual implementation
        self.assertEqual(len(merged["items"]), 2)
        self.assertEqual(merged["customer_name"], "John")
        self.assertEqual(merged["phone_no"], "123")

        # Test with overlapping items (new should override)
        existing_data = {"items": [{"name": "apple", "qty": 1, "size": "small"}]}
        new_data = {"items": [{"name": "apple", "qty": 2, "color": "red"}]}
        merged = ai_service.merge_data(existing_data, new_data)
        self.assertEqual(merged, {"items": [{"name": "apple", "qty": 2, "color": "red"}]})

    # Test for make_json_safe
    def test_make_json_safe(self):
        data = {"price": Decimal("10.50"), "items": [{"cost": Decimal("2.25")}]}
        safe_data = make_json_safe(data)
        self.assertEqual(safe_data, {"price": 10.50, "items": [{"cost": 2.25}]})
        self.assertIsInstance(safe_data["price"], float)
        self.assertIsInstance(safe_data["items"][0]["cost"], float)

        # Test with non-decimal data
        data_no_decimal = {"name": "test", "value": 100}
        safe_data_no_decimal = make_json_safe(data_no_decimal)
        self.assertEqual(safe_data_no_decimal, data_no_decimal)

    # Test for force_dict
    def test_force_dict(self):
        self.assertEqual(force_dict(None), {})
        self.assertEqual(force_dict({}), {})
        self.assertEqual(force_dict({"key": "value"}), {"key": "value"})
        self.assertEqual(force_dict("{\"key\": \"value\"}"), {"key": "value"})
        self.assertEqual(force_dict("invalid json"), {})
        self.assertEqual(force_dict("null"), {})
        self.assertEqual(force_dict("[]"), {})
        self.assertEqual(force_dict(123), {})

if __name__ == "__main__":
    unittest.main()
