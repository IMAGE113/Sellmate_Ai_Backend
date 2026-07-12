from typing import Dict, Optional, List
from app.core.scripts import get_script

class FlowManager:
    def __init__(self, merchant_settings: Dict, order_data: Dict):
        self.settings = merchant_settings
        self.order_data = order_data

    def get_next_step(self, intent: str, user_text: Optional[str] = None) -> str:
        """
        Determine the next status_key based on intent and missing fields.
        """
        # Check for conversation reset commands
        if user_text and self._is_reset_command(user_text):
            return "CONVERSATION_RESET"

        if intent == "HUMAN_TAKEOVER":
            return "HUMAN_TAKEOVER"
        
        if intent == "MENU_QUERY":
            return "MENU_INFO"
        
        if intent == "GREETING" and not self.order_data.get("items"):
            return "GREETING"

        # If the intent is to view or edit the summary, return ORDER_SUMMARY
        if intent in ["VIEW_SUMMARY", "EDIT_ORDER"]:
            return "ORDER_SUMMARY"

        # Check for missing required fields in a specific order
        if not self.order_data.get("items"):
            return "ASK_ITEMS"
        
        # Task 1: Enforce required customer information
        if not self.order_data.get("customer_name"):
            return "ASK_NAME"
        
        if not self.order_data.get("phone_no"):
            return "ASK_PHONE"
        
        if not self.order_data.get("address"):
            return "ASK_ADDRESS"
        
        if not self.order_data.get("township"):
            return "ASK_TOWNSHIP"
        
        if self.settings.get("setting_require_size") and not self.has_all_attributes("size"):
            return "ASK_SIZE"
            
        if self.settings.get("setting_require_color") and not self.has_all_attributes("color"):
            return "ASK_COLOR"

        if self.settings.get("setting_require_sugar_level") and not self.has_all_attributes("sugar_level"):
            return "ASK_SUGAR_LEVEL"

        if self.settings.get("setting_require_ice_level") and not self.has_all_attributes("ice_level"):
            return "ASK_ICE_LEVEL"

        if not self.order_data.get("payment_method"):
            return "ASK_PAYMENT_METHOD"
        
        if self.order_data.get("payment_method") == "Prepaid" and \
           self.settings.get("setting_require_payment_screenshot") and \
           not self.order_data.get("payment_screenshot_received"):
            return "ASK_PAYMENT_SCREENSHOT"

        # If the order is in a terminal state, allow a new order to start
        if self.order_data.get("status") in ["CANCELLED", "FAILED", "OUT_OF_STOCK", "CONVERSATION_RESET"]:
            return "NEW_ORDER_INITIATED"

        return "ORDER_CONFIRMED"

    def has_all_attributes(self, attribute_name: str) -> bool:
        for item in self.order_data.get("items", []):
            # If the item itself doesn't have the attribute, we check if it's required for this product
            # For now, we assume if the setting is on, it's required for all items in the order
            if not item.get(attribute_name):
                return False
        return True

    def get_response(self, status_key: str, shop_name: str, **kwargs) -> str:
        # kwargs will contain order_summary_details, total_price, customer_name, etc.
        return get_script(status_key, shop_name=shop_name, **kwargs)

    def _is_reset_command(self, user_text: str) -> bool:
        reset_keywords = ["restart", "new order", "start over", "cancel order"]
        return any(keyword in user_text.lower() for keyword in reset_keywords)
