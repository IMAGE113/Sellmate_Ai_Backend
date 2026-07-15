from typing import Dict, Optional, List
from app.core.scripts import get_script

class FlowManager:
    def __init__(self, merchant_settings: Dict, order_data: Dict):
        self.settings = merchant_settings
        self.order_data = order_data

    def get_current_state(self) -> str:
        """
        Determines the current state based on the order data.
        This is the single source of truth for the workflow.
        """
        if not self.order_data or not self.order_data.get("items"):
            return "WELCOME"
        
        if not self.order_data.get("customer_name"):
            return "ASK_NAME"
        
        if not self.order_data.get("phone_no"):
            return "ASK_PHONE"
        
        if not self.order_data.get("address"):
            return "ASK_ADDRESS"
        
        if not self.order_data.get("township"):
            return "ASK_TOWNSHIP"
        
        # Attribute requirements (Size, Color, etc.)
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
            
        return "ORDER_SUMMARY"

    def get_next_step(self, intent: str, user_text: Optional[str] = None) -> str:
        """
        Determine the next status_key based on intent and the current state.
        """
        current_state = self.get_current_state()

        # 1. Global Commands (Reset/Human) take absolute priority
        if user_text and self._is_reset_command(user_text):
            return "CONVERSATION_RESET"

        if intent == "HUMAN_TAKEOVER":
            return "HUMAN_TAKEOVER"

        # 2. While waiting for a required field, ignore general AI intents
        # except for explicit cancellations/resets.
        if current_state in ["ASK_NAME", "ASK_PHONE", "ASK_ADDRESS", "ASK_TOWNSHIP"]:
            # If the user is answering a specific field, we stay in that flow
            # The worker will handle the data assignment
            return current_state

        # 3. Handle GREETING and MENU_QUERY for initial interactions
        if intent == "GREETING" and current_state == "WELCOME":
            return "GREETING"
            
        if intent == "MENU_QUERY":
            return "MENU_INFO"

        # 4. Handle Terminal States Transitions
        if intent == "CONFIRM_ORDER" and current_state == "ORDER_SUMMARY":
            return "ORDER_CONFIRMED"
        
        if intent == "CANCEL":
            return "ORDER_CANCELLED"

        # 5. Default to the current state determined by the data
        return current_state

    def has_all_attributes(self, attribute_name: str) -> bool:
        for item in self.order_data.get("items", []):
            if not item.get(attribute_name):
                return False
        return True

    def get_response(self, status_key: str, shop_name: str, **kwargs) -> str:
        return get_script(status_key, shop_name=shop_name, **kwargs)

    def _is_reset_command(self, user_text: str) -> bool:
        reset_keywords = ["restart", "new order", "start over", "cancel order", "/start"]
        return any(keyword in user_text.lower() for keyword in reset_keywords)
