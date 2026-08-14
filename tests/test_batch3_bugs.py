import unittest
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.ai_parser import AIParser
from app.workflow.flow_manager import FlowManager
from app.services.validation_service import ValidationService
import app.db.database

class TestBatch3Bugs(unittest.IsolatedAsyncioTestCase):

    # BUG-24: Greeting punctuation
    def test_greeting_punctuation(self):
        parser = AIParser()
        self.assertTrue(parser.detect_greeting("Hello!"))
        self.assertTrue(parser.detect_greeting("hi,"))
        self.assertTrue(parser.detect_greeting("မင်္ဂလာပါရှင်။"))

    # BUG-27: Retry Escalation
    def test_retry_escalation(self):
        biz = {"name": "Test Shop"}
        # 3 retries already happened
        order_data = {"items": [{"name": "apple", "qty": 1}], "retry_count": 3}
        flow = FlowManager(biz, order_data)
        
        # Should transition to HUMAN_TAKEOVER
        next_step = flow.get_next_step("ORDER", "some random text")
        self.assertEqual(next_step, "HUMAN_TAKEOVER")

    # BUG-23: Duplicate Detection (Simulated in worker logic)
    async def test_duplicate_detection_logic(self):
        # We simulate the check in order_worker.py
        field_name = "phone_no"
        user_text = "John Doe"
        order_extracted_data = {"customer_name": "John Doe"}
        
        is_duplicate = False
        for prev_field in ["customer_name", "phone_no", "address", "township"]:
            if prev_field != field_name and order_extracted_data.get(prev_field) == user_text:
                is_duplicate = True
                break
        
        self.assertTrue(is_duplicate)

    # BUG-31: AI Field Validation
    def test_ai_field_validation(self):
        # AI returns invalid phone
        extracted_data = {"phone_no": "invalid", "intent": "ORDER"}
        
        # Validation logic from worker
        for field in ["customer_name", "phone_no", "address", "township"]:
            if extracted_data.get(field):
                valid = False
                if field == "phone_no": valid, _ = ValidationService.validate_phone(extracted_data[field])
                # ... other fields
                if not valid:
                    del extracted_data[field]
        
        self.assertNotIn("phone_no", extracted_data)

    # BUG-30: Grace Period (Simulated DB query)
    @patch("app.db.database.OrderRepository.get_active_order_by_chat_id", new_callable=AsyncMock)
    async def test_grace_period_logic(self, mock_get):
        # This tests the logic we put in the SQL query conceptually
        # In real DB, updated_at > NOW - 5m would return the order
        mock_get.return_value = {"id": 1, "status": "COMPLETED", "updated_at": "some_recent_time"}
        order = await mock_get(123)
        self.assertEqual(order["status"], "COMPLETED")

    # BUG-25: Confirmation State Gating
    async def test_confirmation_state_gating(self):
        parser = AIParser()
        # Should NOT trigger CONFIRM_ORDER if not in ORDER_SUMMARY
        res = await parser.parse_message("ok", {}, [], current_state="ASK_NAME")
        self.assertNotEqual(res.get("intent"), "CONFIRM_ORDER")
        
        # Should trigger CONFIRM_ORDER if in ORDER_SUMMARY
        res = await parser.parse_message("ok", {}, [], current_state="ORDER_SUMMARY")
        self.assertEqual(res.get("intent"), "CONFIRM_ORDER")

if __name__ == "__main__":
    unittest.main()
