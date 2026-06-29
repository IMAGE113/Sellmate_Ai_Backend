from typing import Dict, Optional, List
from app.core.scripts import get_script


# Words that signal the customer is approving the order summary. Kept here so the
# confirmation gate works even when the customer types instead of pressing a button.
CONFIRM_KEYWORDS = [
    "confirm order", "confirm", "ok", "okay", "yes", "y", "အတည်ပြု",
    "အတည်ပြုသည်", "ဟုတ်ကဲ့", "ဟုတ်", " မှန်ပါတယ်", "မှန်ပါတယ်", "ရပြီ", "လုပ်",
]

# Words that signal the customer wants to cancel/abort while awaiting confirmation.
CANCEL_KEYWORDS = [
    "cancel order", "cancel", "no", "မလို", "မလုပ်တော့", "ပယ်ဖျက်", "ဖျက်",
]


class FlowManager:
    def __init__(self, merchant_settings: Dict, order_data: Dict):
        self.settings = merchant_settings
        self.order_data = order_data

    def get_next_step(self, intent: str, user_text: Optional[str] = None) -> str:
        """
        Determine the next status_key based on intent and missing fields.

        Phase 1: the flow now ends collection at ORDER_SUMMARY and only emits
        ORDER_CONFIRMED after the customer explicitly confirms (button press or
        confirmation text). It never auto-confirms on the last collected field.
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

        # Explicit cancel while an order is in progress.
        if intent in ["CANCEL", "CANCEL_ORDER"] or (user_text and self._is_cancel_command(user_text)):
            if self.order_data.get("items"):
                return "ORDER_CANCELLED"

        # If the intent is to view or edit the summary, return ORDER_SUMMARY
        if intent in ["VIEW_SUMMARY", "EDIT_ORDER"]:
            return "ORDER_SUMMARY"

        # Check for missing required fields in a specific order
        if not self.order_data.get("items"):
            return "ASK_ITEMS"

        # Quantity must always be collected and valid before we proceed (M3).
        if not self.has_all_quantities():
            return "ASK_QUANTITY"

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

        # If the order is in a terminal state, allow a new order to start
        if self.order_data.get("status") in ["CANCELLED", "FAILED", "OUT_OF_STOCK", "CONVERSATION_RESET"]:
            return "NEW_ORDER_INITIATED"

        # ---- Confirmation gate (C1 / H2) ----
        # All required information has been collected. We must NOT auto-confirm.
        # First time we reach this point we present the summary. We only move to
        # ORDER_CONFIRMED once the customer explicitly confirms.
        if self.is_confirmation(intent, user_text):
            return "ORDER_CONFIRMED"

        if self.is_cancellation(intent, user_text):
            return "ORDER_CANCELLED"

        # Once the summary has been shown we wait for an explicit decision.
        if self.order_data.get("summary_shown"):
            return "AWAITING_CONFIRMATION"

        # Otherwise, show the order summary and ask the customer to confirm.
        return "ORDER_SUMMARY"

    def is_confirmation(self, intent: Optional[str], user_text: Optional[str]) -> bool:
        if intent in ["CONFIRM_ORDER", "CONFIRM"]:
            return True
        return bool(user_text) and self._matches(user_text, CONFIRM_KEYWORDS)

    def is_cancellation(self, intent: Optional[str], user_text: Optional[str]) -> bool:
        if intent in ["CANCEL", "CANCEL_ORDER"]:
            return True
        return bool(user_text) and self._matches(user_text, CANCEL_KEYWORDS)

    def has_all_quantities(self) -> bool:
        items = self.order_data.get("items", [])
        if not items:
            return False
        for item in items:
            qty = item.get("qty")
            try:
                if qty is None or int(qty) <= 0:
                    return False
            except (TypeError, ValueError):
                return False
        return True

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

    def get_response(self, status_key: str, shop_name: str, order_summary: Optional[str] = None, **kwargs) -> str:
        """
        Render the response template for a status key.

        Accepts arbitrary keyword placeholders (order_summary_details, total_price,
        customer_name, phone_no, address, ...) and forwards them to get_script so
        the ORDER_SUMMARY / AWAITING_CONFIRMATION templates can be filled. This
        fixes the previous TypeError when the worker passed summary kwargs (M2).
        """
        if status_key == "ORDER_SUMMARY" and order_summary:
            # Backwards-compatible path: a fully pre-rendered summary string.
            return order_summary
        return get_script(status_key, shop_name=shop_name, **kwargs)

    def _matches(self, user_text: str, keywords: List[str]) -> bool:
        lowered = user_text.lower().strip()
        return any(keyword in lowered for keyword in keywords)

    def _is_reset_command(self, user_text: str) -> bool:
        reset_keywords = ["restart", "new order", "start over", "cancel order"]
        return any(keyword in user_text.lower() for keyword in reset_keywords)

    def _is_cancel_command(self, user_text: str) -> bool:
        return self._matches(user_text, CANCEL_KEYWORDS)
