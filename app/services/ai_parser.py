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
        greetings = ["hi", "hello", "hey", "မင်္ဂလာပါ", "ဟိုင်း", "morning", "evening"]
        # Use word boundaries or strict matching to avoid false positives
        words = text.lower().strip().split()
        if not words: return False
        return any(w in greetings for w in words[:2])

    @staticmethod
    def detect_screenshot(msg: Dict[str, Any]) -> bool:
        return "photo" in msg

    async def parse_message(self, text: str, context: Dict[str, Any], menu: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 1. Deterministic Rule: Greeting Check
        if self.detect_greeting(text):
            return {"intent": "GREETING"}

        # 2. Deterministic Rule: Confirmation Check
        if self.detect_confirmation(text):
            return {"intent": "CONFIRM_ORDER"}

        # 2. AI Extraction Fallback
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
