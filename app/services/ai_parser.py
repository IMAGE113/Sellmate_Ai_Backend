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
        confirm_words = ["confirm", "ok", "ဟုတ်", "မှန်တယ်", "မှာမယ်", "အိုကေ", "yes", "အတည်ပြု"]
        return any(w in text.lower() for w in confirm_words)

    @staticmethod
    def detect_screenshot(msg: Dict[str, Any]) -> bool:
        return "photo" in msg

    async def parse_message(self, text: str, context: Dict[str, Any], menu: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 1. Deterministic Rule: Confirmation Check
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
