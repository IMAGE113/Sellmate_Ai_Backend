import json
import logging
from typing import Dict, Any, Optional, List
from app.services.ai import ai

class AIParser:
    """
    Hybrid architecture: Rule-based detection + AI extraction fallback.
    Ensures deterministic results for common patterns.
    """
    
    @staticmethod
    def detect_confirmation(text: str) -> bool:
        """
        BUG-18: Strict confirmation detection to avoid substring traps like 'book' or 'cookbook'.
        """
        import re
        confirm_words = ["confirm", "ok", "ဟုတ်", "မှန်တယ်", "မှာမယ်", "အိုကေ", "yes", "အတည်ပြု", "ဟုတ်ကဲ့"]
        # Use word boundaries and strict matching
        text = text.lower().strip()
        # Check if any confirm word is in the text as a full word
        for w in confirm_words:
            pattern = rf"\b{re.escape(w)}\b"
            # For Burmese, word boundaries might not work well, so we check if it's the whole string or surrounded by whitespace
            if re.search(pattern, text) or w == text:
                return True
        return False

    @staticmethod
    def detect_greeting(text: str) -> bool:
        """
        BUG-24: Greeting detection with punctuation stripping.
        """
        import re
        greetings = ["hi", "hello", "hey", "မင်္ဂလာပါ", "ဟိုင်း", "morning", "evening"]
        # Strip punctuation
        clean_text = re.sub(r'[^\w\s\u1000-\u109F]', '', text.lower()).strip()
        if not clean_text: return False
        
        # Check for English words (split by whitespace)
        words = clean_text.split()
        for w in words[:2]:
            if w in greetings: return True
            
        # Check for Burmese greetings (might be part of a larger word due to lack of spaces)
        for g in greetings:
            if g in clean_text[:10]: # Check start of string
                return True
                
        return False

    @staticmethod
    def detect_screenshot(msg: Dict[str, Any]) -> bool:
        return "photo" in msg

    @staticmethod
    def _extract_direct_menu_item(text: str, menu: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Recognize an unambiguous initial product request without relying on AI."""
        import re

        prefixes = r"(?:i\s+want|want|order|buy|please(?:\s+(?:order|give\s+me))?)"
        quantity_unit = r"(?:x|×|pcs?|pieces?|units?)?"
        cleaned = text.strip().rstrip(".!?").strip()

        for product in menu:
            name = str(product.get("name", "")).strip() if isinstance(product, dict) else ""
            if not name:
                continue
            name_pattern = re.escape(name)
            patterns = (
                rf"^(?:{prefixes}\s+)?{name_pattern}$",
                rf"^(?:{prefixes}\s+)?(?P<qty>[1-9]\d*)\s*{quantity_unit}\s+{name_pattern}$",
                rf"^(?:{prefixes}\s+)?{name_pattern}\s*{quantity_unit}\s*(?P<qty>[1-9]\d*)$",
            )
            for pattern in patterns:
                match = re.fullmatch(pattern, cleaned, flags=re.IGNORECASE)
                if match:
                    qty = int(match.groupdict().get("qty") or 1)
                    return {"intent": "ORDER", "items": [{"name": name, "qty": qty}]}
        return None

    async def parse_message(self, text: str, context: Dict[str, Any], menu: List[Dict[str, Any]], current_state: Optional[str] = None) -> Dict[str, Any]:
        # 1. Deterministic Rule: Greeting Check
        # BUG-43: A greeting fast-path is meaningful only at the start of a flow.
        if current_state == "WELCOME" and self.detect_greeting(text):
            return {"intent": "GREETING"}

        # 2. Deterministic Rule: Confirmation Check
        # BUG-25: Only fire confirmation fast-path when in ORDER_SUMMARY to avoid false positives
        if current_state == "ORDER_SUMMARY" and self.detect_confirmation(text):
            return {"intent": "CONFIRM_ORDER"}

        # 3. Deterministic Rule: Payment-method answers should not depend on AI availability/output.
        if current_state == "ASK_PAYMENT_METHOD":
            import re
            payment_text = text.strip().rstrip(".!?").strip().lower()
            if re.search(r"\bcod\b", payment_text) and not re.search(r"\bprepaid\b", payment_text):
                return {"intent": "ORDER", "payment_method": "COD"}
            if re.search(r"\bprepaid\b", payment_text):
                return {"intent": "ORDER", "payment_method": "Prepaid"}

        # 4. Deterministic Rule: Exact initial product requests should not depend on AI availability/output.
        if current_state == "WELCOME":
            direct_item = self._extract_direct_menu_item(text, menu)
            if direct_item:
                return direct_item

        # 5. AI Extraction Fallback
        try:
            extracted_json = await ai.extract_data(
                text, 
                context.get("shop_name", "Shop"), 
                menu, 
                context.get("previous_data", {}),
                context.get("requirements_text")
            )
            data = json.loads(extracted_json)
            
            # Production bug fix: Use normalization to guarantee no None values
            return ai.normalize_extracted_data(data)
            
        except Exception as e:
            logging.error(f"AI Parser Error: {e}")
            # Fallback to safe structure
            return {"intent": "UNKNOWN", "items": [], "error": str(e)}

ai_parser = AIParser()
