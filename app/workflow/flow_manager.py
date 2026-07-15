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
        # 1. Global Commands (Reset/Human) take absolute priority
        if user_text and self._is_reset_command(user_text):
            return "CONVERSATION_RESET"

        if intent == "HUMAN_TAKEOVER":
            return "HUMAN_TAKEOVER"

        # 2. Check for missing required fields (Priority Flow)
        # If any required info is missing, we MUST collect it before showing summary or handling other intents
        missing_field_step = self._get_missing_field_step()
        
        # 3. If we are in the middle of collecting info, ignore MENU_QUERY or premature SUMMARY requests
        if missing_field_step:
            # If the user explicitly asks for menu while we have items but are missing info,
            # we can show menu, but otherwise we stick to collecting info.
            # However, per requirements: "Do not switch to MENU_QUERY or STOCK_QUERY until the order flow is complete."
            return missing_field_step

        # 4. If all required info is collected, handle other intents
        if intent == "MENU_QUERY":
            return "MENU_INFO"
        
        if intent == "GREETING" and not self.order_data.get("items"):
            return "GREETING"

        # 5. Summary and Confirmation (Only if all info is present)
        if intent == "CONFIRM_ORDER":
            return "ORDER_CONFIRMED"
        
        if intent == "CANCEL":
            return "ORDER_CANCELLED"

        if intent in ["VIEW_SUMMARY", "EDIT_ORDER"]:
            return "ORDER_SUMMARY"

        # 6. Terminal states
        if self.order_data.get("status") in ["CANCELLED", "FAILED", "OUT_OF_STOCK", "CONVERSATION_RESET"]:
            return "NEW_ORDER_INITIATED"

        # 7. Default behavior: Show summary if all info is present, otherwise ask for missing fields
        # This acts as a safety net for any UNKNOWN intent or unrelated text
        return "ORDER_SUMMARY"

    def _get_missing_field_step(self) -> Optional[str]:
        """
        Internal helper to identify the first missing required field.
        """
        if not self.order_data.get("items"):
            return "ASK_ITEMS"
        
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
            
        return None

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
