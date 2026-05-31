import os
import json
import httpx
import re
import logging
from typing import Dict, List, Optional
from app.core.config import GROQ_API_KEY

http_client = httpx.AsyncClient(timeout=20.0)

class AI:
    def get_system_prompt(self, shop_name: str, menu: List[Dict], current_data: Dict, merchant_requirements: str = None):
        menu_names = [m["name"] for m in menu]
        
        req_instruction = ""
        if merchant_requirements:
            req_instruction = f"MERCHANT CUSTOM REQUIREMENTS: {merchant_requirements}"

        return f"""
Role: Structured Data Extractor for {shop_name}.
{req_instruction}

TASK:
Extract order details and customer information from the user's message.
Return a JSON object with the extracted fields. 
DO NOT generate a response to the user. ONLY extract data.

EXTRACTABLE FIELDS:
- customer_name
- phone_no
- address
- township
- items: list of {{ "name": "...", "qty": ..., "details": "..." }}
- payment_method: 'COD' or 'Prepaid'
- intent: 'ORDER', 'CANCEL', 'HUMAN_TAKEOVER', 'MENU_QUERY', 'GREETING', 'OTHER'

STRICT RULES:
1. PRODUCT NAMES must match EXACTLY from this list: {json.dumps(menu_names)}
2. If the user mentions items in Burmese, map them to the corresponding English menu names.
3. If the user wants to talk to a human/admin, set intent to 'HUMAN_TAKEOVER'.
4. If the user asks for products/menu/price, set intent to 'MENU_QUERY'.

CURRENT DATA: {json.dumps(current_data, ensure_ascii=False)}
MENU: {json.dumps(menu, ensure_ascii=False)}
"""

    async def extract_data(self, text: str, shop_name: str, menu: List[Dict], current_data: Dict, merchant_requirements: str = None) -> Dict:
        try:
            system_prompt = self.get_system_prompt(shop_name, menu, current_data, merchant_requirements)
            res = await http_client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    "temperature": 0, 
                    "response_format": {"type": "json_object"}
                }
            )
            if res.status_code == 200:
                return res.json()["choices"][0]["message"]["content"]
            else:
                logging.error(f"Groq API Error: {res.status_code} - {res.text}")
                return {}
        except Exception as e:
            logging.error(f"AI Extraction Error: {e}")
            return {}

    def merge_data(self, old_data: Dict, new_data: Dict) -> Dict:
        merged = old_data.copy()
        for key, value in new_data.items():
            if key == "items":
                # Basic item merging logic
                current_items = {item["name"]: item for item in merged.get("items", [])}
                for item in value:
                    name = item.get("name")
                    if name:
                        current_items[name] = item
                merged["items"] = list(current_items.values())
            elif value and value != "unknown":
                merged[key] = value
        return merged

ai = AI()
