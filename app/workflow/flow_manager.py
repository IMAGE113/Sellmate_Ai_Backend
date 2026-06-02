from typing import Dict, Optional, List
from app.core.scripts import get_script

class FlowManager:
    def __init__(self, merchant_settings: Dict, order_data: Dict):
        self.settings = merchant_settings
        self.order_data = order_data

    def get_next_step(self, intent: str) -> str:
        """
        Determine the next status_key based on intent and missing fields.
        """
        if intent == "HUMAN_TAKEOVER":
            return "HUMAN_TAKEOVER"
        
        if intent == "MENU_QUERY":
            return "MENU_INFO"
        
        if intent == "GREETING" and not self.order_data.get("items"):
            return "GREETING"

        # Check for missing required fields in a specific order
        if not self.order_data.get("items"):
            return "ASK_ITEMS"
        
        if self.settings.get("setting_require_name") and not self.order_data.get("customer_name"):
            return "ASK_NAME"
        
        if self.settings.get("setting_require_phone") and not self.order_data.get("phone_no"):
            return "ASK_PHONE"
        
        if self.settings.get("setting_require_address") and not self.order_data.get("address"):
            return "ASK_ADDRESS"
        
        if not self.order_data.get("township"):
            return "ASK_TOWNSHIP"
        
        if self.settings.get("setting_require_size") and not self.has_all_sizes():
            return "ASK_SIZE"
            
        if self.settings.get("setting_require_color") and not self.has_all_colors():
            return "ASK_COLOR"

        if not self.order_data.get("payment_method"):
            return "ASK_PAYMENT_METHOD"
        
        if self.order_data.get("payment_method") == "Prepaid" and \
           self.settings.get("setting_require_payment_screenshot") and \
           not self.order_data.get("payment_screenshot_received"):
            return "ASK_PAYMENT_SCREENSHOT"

        return "CONFIRM_ORDER"

    def has_all_sizes(self) -> bool:
        for item in self.order_data.get("items", []):
            if not item.get("size"):
                return False
        return True

    def has_all_colors(self) -> bool:
        for item in self.order_data.get("items", []):
            if not item.get("color"):
                return False
        return True

    def get_response(self, status_key: str, shop_name: str) -> str:
        return get_script(status_key, shop_name=shop_name)
