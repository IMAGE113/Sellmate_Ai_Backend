import os
import json
import httpx
import re
import logging
from typing import Dict, List, Optional, Any

http_client = httpx.AsyncClient(timeout=20.0)

class AI:
    def get_system_prompt(self, shop_name: str, menu: List[Dict], current_data: Dict, merchant_requirements: str = None):
        menu_names = [m["name"] for m in menu]
        
        req_instruction = ""
        if merchant_requirements:
            req_instruction = f"MERCHANT CUSTOM REQUIREMENTS: {merchant_requirements}"

        # Task 5: Format menu with live stock info for AI context
        menu_with_stock = []
        for m in menu:
            item_info = f"{m['name']} (Price: {m['price']}, Stock: {m.get('stock', 0)})"
            menu_with_stock.append(item_info)

        return f"""
Role: Structured Data Extractor for {shop_name}.
{req_instruction}

TASK:
Extract order details and customer information from the user's message.
Return a JSON object with the extracted fields. 
DO NOT generate a response to the user. ONLY extract data.

INVENTORY AWARENESS:
The menu below contains live stock data. 
If the user asks about availability or stock, set intent to 'MENU_QUERY'.
If the user tries to order more than available stock, still extract the data but the system will handle the rejection.

MENU WITH LIVE STOCK:
{json.dumps(menu_with_stock, ensure_ascii=False)}

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

    async def extract_data(self, text: str, shop_name: str, menu: List[Dict], current_data: Dict, merchant_requirements: str = None) -> str:
        try:
            from app.core.config import GROQ_API_KEY
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

    def normalize_extracted_data(self, data: Any) -> Dict[str, Any]:
        """
        Production bug fix: Normalizes all fields to prevent NoneType crashes.
        Ensures merge_data() never receives None for critical fields.
        """
        if not isinstance(data, dict):
            logging.warning(f"AI returned invalid data type: {type(data)}. Normalizing to empty dict.")
            return {"intent": "UNKNOWN", "items": []}
        
        normalized = {}
        
        # 1. Normalize Intent
        valid_intents = [
            'ORDER', 'CANCEL', 'HUMAN_TAKEOVER', 'MENU_QUERY', 'GREETING', 
            'VIEW_SUMMARY', 'ADD_ITEM', 'REMOVE_ITEM', 'CHANGE_QUANTITY', 
            'CHANGE_NAME', 'CHANGE_PHONE', 'CHANGE_ADDRESS', 'CHANGE_ITEM_VARIANT', 
            'CONFIRM_ORDER', 'OTHER', 'UNKNOWN'
        ]
        intent = data.get("intent", "UNKNOWN")
        normalized["intent"] = str(intent) if intent and str(intent) in valid_intents else "UNKNOWN"
        
        # 2. Normalize Items (Critical Fix: Never iterate over None)
        items = data.get("items")
        normalized_items = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name")
                    if name: # Skip invalid items without names
                        normalized_item = {
                            "name": str(name),
                            "qty": int(item.get("qty", 1)) if str(item.get("qty", "1")).isdigit() else 1,
                            "size": str(item.get("size")) if item.get("size") else "",
                            "color": str(item.get("color")) if item.get("color") else "",
                            "sugar_level": str(item.get("sugar_level")) if item.get("sugar_level") else "",
                            "ice_level": str(item.get("ice_level")) if item.get("ice_level") else "",
                            "details": str(item.get("details")) if item.get("details") else ""
                        }
                        normalized_items.append(normalized_item)
        normalized["items"] = normalized_items

        # 3. Normalize Scalar Fields (None string -> "")
        scalar_fields = ["customer_name", "phone_no", "address", "township", "payment_method"]
        for field in scalar_fields:
            val = data.get(field)
            if val and str(val).lower() != "unknown":
                normalized[field] = str(val)
            else:
                normalized[field] = ""

        # 4. Normalize Modification Fields
        mod_fields = ["item_to_remove", "item_to_change_qty", "item_to_change_variant", 
                     "new_size", "new_color", "new_sugar_level", "new_ice_level"]
        for field in mod_fields:
            val = data.get(field)
            normalized[field] = str(val) if val else ""
            
        # Special case for numeric field
        new_qty = data.get("new_quantity")
        if new_qty is not None and str(new_qty).isdigit():
            normalized["new_quantity"] = int(new_qty)
        else:
            normalized["new_quantity"] = 0
                
        return normalized

    def merge_data(self, old_data: Dict, new_data: Dict) -> Dict:
        """
        Production bug fix: Guaranteed to never receive None values after normalization.
        """
        # Ensure old_data is also safe
        safe_old = old_data if isinstance(old_data, dict) else {}
        if "items" not in safe_old or not isinstance(safe_old["items"], list):
            safe_old["items"] = []
            
        # Normalize new data
        normalized_new = self.normalize_extracted_data(new_data)
        
        merged = safe_old.copy()
        
        # Merge Items
        if normalized_new["items"]:
            current_items = {item["name"]: item for item in merged.get("items", [])}
            for item in normalized_new["items"]:
                name = item.get("name")
                if name:
                    current_items[name] = item
            merged["items"] = list(current_items.values())
            
        # Item Removal (Critical Fix: Never call .lower() on None)
        to_remove = normalized_new.get("item_to_remove", "")
        if to_remove:
            merged["items"] = [item for item in merged.get("items", []) 
                             if str(item.get("name", "")).lower() != to_remove.lower()]
            
        # Quantity Change
        to_change_qty = normalized_new.get("item_to_change_qty", "")
        new_qty = normalized_new.get("new_quantity", 0)
        if to_change_qty and new_qty > 0:
            for item in merged.get("items", []):
                if str(item.get("name", "")).lower() == to_change_qty.lower():
                    item["qty"] = new_qty
                    break
                    
        # Variant Change
        to_change_var = normalized_new.get("item_to_change_variant", "")
        if to_change_var:
            for item in merged.get("items", []):
                if str(item.get("name", "")).lower() == to_change_var.lower():
                    if normalized_new.get("new_size"): item["size"] = normalized_new["new_size"]
                    if normalized_new.get("new_color"): item["color"] = normalized_new["new_color"]
                    if normalized_new.get("new_sugar_level"): item["sugar_level"] = normalized_new["new_sugar_level"]
                    if normalized_new.get("new_ice_level"): item["ice_level"] = normalized_new["new_ice_level"]
                    break
                    
        # Scalar Fields (Critical Fix: Never assign None)
        for field in ["customer_name", "phone_no", "address", "township", "payment_method"]:
            val = normalized_new.get(field, "")
            if val:
                merged[field] = val
                
        # Intent
        merged["intent"] = normalized_new.get("intent", "UNKNOWN")
        
        return merged

ai = AI()
