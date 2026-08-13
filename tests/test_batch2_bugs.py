import unittest
from app.services.ai import AI
from app.workflow.flow_manager import FlowManager
from app.services.ai_parser import AIParser

class TestBatch2Bugs(unittest.TestCase):

    # BUG-12, BUG-13, BUG-14: Quantity Normalization
    def test_quantity_normalization(self):
        ai_service = AI()
        
        # BUG-12, BUG-14: Zero/Negative should be rejected
        data = {"items": [{"name": "apple", "qty": 0}, {"name": "banana", "qty": -1}]}
        norm = ai_service.normalize_extracted_data(data)
        self.assertEqual(len(norm["items"]), 0)
        
        # BUG-13: Decimals should be preserved
        data = {"items": [{"name": "rice", "qty": 2.5}]}
        norm = ai_service.normalize_extracted_data(data)
        self.assertEqual(norm["items"][0]["qty"], 2.5)
        
        # Invalid string to 1.0
        data = {"items": [{"name": "apple", "qty": "a lot"}]}
        norm = ai_service.normalize_extracted_data(data)
        self.assertEqual(norm["items"][0]["qty"], 1.0)

    # BUG-15: Item De-duplication with Variants
    def test_item_deduplication_variants(self):
        ai_service = AI()
        existing = {"items": [{"name": "Shirt", "qty": 1, "size": "M"}]}
        new_data = {"items": [{"name": "Shirt", "qty": 1, "size": "L"}]}
        merged = ai_service.merge_data(existing, new_data)
        # Should have 2 shirts now
        self.assertEqual(len(merged["items"]), 2)
        
        # Overlapping same variant should update
        new_data_2 = {"items": [{"name": "Shirt", "qty": 2, "size": "M"}]}
        merged_2 = ai_service.merge_data(merged, new_data_2)
        self.assertEqual(len(merged_2["items"]), 2)
        for item in merged_2["items"]:
            if item["size"] == "M":
                self.assertEqual(item["qty"], 2)

    # BUG-18: Quantity Change to 0 as Removal
    def test_quantity_change_zero(self):
        ai_service = AI()
        existing = {"items": [{"name": "apple", "qty": 5}]}
        # Request change to 0
        new_data = {"item_to_change_qty": "apple", "new_quantity": 0}
        merged = ai_service.merge_data(existing, new_data)
        self.assertEqual(len(merged["items"]), 0)

    # BUG-19, BUG-20, BUG-22: Cancel and Reset Intents
    def test_cancel_and_reset(self):
        # BUG-19: Cancel during ASK_X
        flow = FlowManager({}, {"items": [{"name": "apple", "qty": 1}]}) # State will be ASK_NAME
        self.assertEqual(flow.get_current_state(), "ASK_NAME")
        
        # Cancel should work
        next_step = flow.get_next_step("CANCEL", "cancel")
        self.assertEqual(next_step, "ORDER_CANCELLED")
        
        # BUG-20: Plain "cancel" reset command
        next_step_reset = flow.get_next_step("ORDER", "cancel")
        self.assertEqual(next_step_reset, "CONVERSATION_RESET")
        
        # BUG-22: Burmese reset command
        next_step_my = flow.get_next_step("ORDER", "အစကပြန်စ")
        self.assertEqual(next_step_my, "CONVERSATION_RESET")

    # BUG-18: Substring confirmation trap fix
    def test_confirmation_substring_trap(self):
        parser = AIParser()
        # "book" should NOT trigger "ok"
        self.assertFalse(parser.detect_confirmation("I want to book a table"))
        self.assertFalse(parser.detect_confirmation("cookbook"))
        
        # Real "ok" should work
        self.assertTrue(parser.detect_confirmation("ok"))
        self.assertTrue(parser.detect_confirmation("Confirm please"))
        self.assertTrue(parser.detect_confirmation("ဟုတ်ကဲ့"))

if __name__ == "__main__":
    unittest.main()
