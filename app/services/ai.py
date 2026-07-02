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
            - items: list of {{ "name": "...", "qty": ..., "size": "...", "color": "...", "sugar_level": "...", "ice_level": "...", "details": "..." }} (for adding/changing items)
            - item_to_remove: string (for removing an item)
            - item_to_change_qty: string (for changing quantity of an item)
            - new_quantity: integer (for changing quantity of an item)
            - item_to_change_variant: string (name of the item to change variant for)
            - new_size: string (new size for the item)
            - new_color: string (new color for the item)
            - new_sugar_level: string (new sugar level for the item)
            - new_ice_level: string (new ice level for the item)
            - payment_method: 'COD' or 'Prepaid'
            - intent: 'ORDER', 'CANCEL', 'HUMAN_TAKEOVER', 'MENU_QUERY', 'GREETING', 'VIEW_SUMMARY', 'ADD_ITEM', 'REMOVE_ITEM', 'CHANGE_QUANTITY', 'CHANGE_NAME', 'CHANGE_PHONE', 'CHANGE_ADDRESS', 'CHANGE_ITEM_VARIANT', 'CONFIRM_ORDER', 'OTHER'

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
                return "{}"
        except Exception as e:
            logging.error(f"AI Extraction Error: {e}")
            return "{}"

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
            elif key == "item_to_remove":
                if value:
                    merged["items"] = [item for item in merged.get("items", []) if item.get("name", "").lower() != value.lower()]
            elif key == "item_to_change_qty":
                if value and new_data.get("new_quantity") is not None:
                    for item in merged.get("items", []):
                        if item.get("name", "").lower() == value.lower():
                            item["qty"] = new_data["new_quantity"]
                            break
            elif key == "item_to_change_variant":
                item_name = value
                for item in merged.get("items", []):
                    if item.get("name", "").lower() == item_name.lower():
                        if new_data.get("new_size") is not None: item["size"] = new_data["new_size"]
                        if new_data.get("new_color") is not None: item["color"] = new_data["new_color"]
                        if new_data.get("new_sugar_level") is not None: item["sugar_level"] = new_data["new_sugar_level"]
                        if new_data.get("new_ice_level") is not None: item["ice_level"] = new_data["new_ice_level"]
                        break
            elif key in ["customer_name", "phone_no", "address", "payment_method"]:
                if value and value != "unknown":
                    merged[key] = value
            elif value and value != "unknown" and key not in ["item_to_change_qty", "new_quantity", "new_size", "new_color", "new_sugar_level", "new_ice_level", "item_to_change_variant"]:
                merged[key] = value
        return merged

ai = AI()
