import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional
from openai import OpenAI
from app.core.errors import WorkflowError

# Pre-configured OpenAI client
client = OpenAI()

class AIResilientService:
    """
    Resilient AI service with timeout handling, exponential backoff retries,
    malformed JSON recovery, and graceful fallback.
    """
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, timeout: float = 10.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout

    async def extract_data(self, user_text: str, shop_name: str, menu: List[Dict], previous_data: Dict, requirements: str = None) -> str:
        """
        Extract structured data with full resilience.
        """
        prompt = self._build_prompt(user_text, shop_name, menu, previous_data, requirements)
        
        for attempt in range(self.max_retries):
            try:
                # 1. Timeout handling
                response = await asyncio.wait_for(
                    self._call_provider(prompt),
                    timeout=self.timeout
                )
                
                # 2. Malformed JSON recovery
                return self._sanitize_and_validate_json(response)
                
            except (asyncio.TimeoutError, Exception) as e:
                logging.warning(f"AI Attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    # 3. Graceful fallback when all retries fail
                    return self._get_safe_fallback_json()
                
                # 4. Exponential backoff
                await asyncio.sleep(self.base_delay * (2 ** attempt))

    async def _call_provider(self, prompt: str) -> str:
        # Using gpt-4.1-mini as per pre-configured model list
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    def _sanitize_and_validate_json(self, content: str) -> str:
        try:
            data = json.loads(content)
            # Ensure required fields exist in the structured output
            if "intent" not in data: data["intent"] = "ORDER"
            return json.dumps(data)
        except json.JSONDecodeError:
            logging.error(f"Malformed JSON from AI: {content}")
            return self._get_safe_fallback_json()

    def _get_safe_fallback_json(self) -> str:
        """Deterministic fallback response."""
        return json.dumps({
            "intent": "ORDER",
            "items": [],
            "confidence": 0.0,
            "error": "AI_UNAVAILABLE_FALLBACK"
        })

    def _build_prompt(self, user_text, shop_name, menu, previous_data, requirements):
        return f"""
        Extract structured order data from the user message for {shop_name}.
        Menu: {json.dumps(menu)}
        Current Data: {json.dumps(previous_data)}
        Requirements: {requirements}
        User Message: "{user_text}"
        Return ONLY a JSON object with intent, items, and confidence score.
        """

ai_resilient = AIResilientService()
