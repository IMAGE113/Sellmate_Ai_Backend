import os
import json
import httpx
import re
import logging
from app.core.config import GROQ_API_KEY

http_client = httpx.AsyncClient(timeout=20.0)

class AI:
    def get_system_prompt(self, shop_name, category, menu, current_order):
        menu_names = [m["name"] for m in menu]
        
        # Category-specific instructions
        category_instructions = ""
        if category == 'clothing':
            category_instructions = "STRICT: You MUST ask for 'Size' and 'Color' if they are not provided for each item."
        elif category == 'beauty':
            category_instructions = "STRICT: You MUST ask for 'Skin Type' if it is not provided."
        elif category == 'cafe':
            category_instructions = "STRICT: You MUST ask for 'Sugar Level' or 'Ice Level' if applicable."

        return f"""
        Role: Senior Order Management AI for {shop_name} ({category} shop).
        
        {category_instructions}
        
        STRICT RULES:
        1. DO NOT translate or change any PRODUCT NAMES from the menu.
        2. Use the EXACT spelling from this list: {json.dumps(menu_names)}
        3. DO NOT translate the Shop Name.
        4. Extract customer_name, phone_no, address, and payment_method.
        5. If the user mentions items in Burmese, map them to the corresponding English menu names from the menu.
        6. Return ONLY a JSON object with the key 'final_order_data'.
        
        CONTEXT (Current Order State): {json.dumps(current_order, ensure_ascii=False)}
        MENU (Available Products): {json.dumps(menu, ensure_ascii=False)}
        
        The JSON should look like this:
        {{
            "final_order_data": {{
                "customer_name": "...",
                "phone_no": "...",
                "address": "...",
                "payment_method": "...",
                "items": [
                    {{"name": "Product A", "qty": 1, "details": "Size: M, Color: Blue"}}
                ]
            }}
        }}
        """

    def pick(self, new, old):
        if isinstance(new, str) and new.strip():
            return new.strip()
        if isinstance(new, (int, float)):
            return new
        return old

    def build_summary_layout(self, order):
        item_lines = []
        for item in order.get('items', []):
            details = f" ({item['details']})" if item.get('details') else ""
            item_lines.append(f"• {item['name']} x {item['qty']}{details}")
        
        item_text = "\n".join(item_lines)
        return f"""📝 **အော်ဒါအနှစ်ချုပ်**
━━━━━━━━━━━━━━
🛒 **မှာယူသည့်ပစ္စည်းများ:**
{item_text}

👤 **အမည်:** {order.get('customer_name', 'မသိရသေးပါ')}
📞 **ဖုန်း:** {order.get('phone_no', 'မသိရသေးပါ')}
📍 **လိပ်စာ:** {order.get('address', 'မသိရသေးပါ')}
💳 **ငွေပေးချေမှု:** {order.get('payment_method', 'မသိရသေးပါ')}
━━━━━━━━━━━━━━
မှန်ကန်ပါက **Confirm** နှိပ်ပေးပါ။ ပြင်ချင်တာရှိပါကလည်း ပြောနိုင်ပါတယ်ခင်ဗျာ။ 🙏"""

    def safe_parse(self, content, current_order, menu, user_input):
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            json_text = match.group() if match else content
            data = json.loads(json_text)
            ai_data = data.get("final_order_data", {})
        except Exception as e:
            logging.error(f"JSON Parse Error: {e}")
            return current_order

        # Handle item merging and edits
        edit_triggers = ["မဟုတ်", "မယူ", "မသောက်", "ပြင်", "change", "replace", "remove", "အစား", "ဖြုတ်"]
        is_edit_mode = any(word in user_input.lower() for word in edit_triggers)
        
        current_items = {item["name"]: item for item in current_order.get("items", [])}
        new_items = ai_data.get("items", [])

        if new_items:
            if is_edit_mode:
                # In edit mode, we might want to be more selective, but for simplicity, 
                # let's assume the AI provides the intended new state of items.
                updated_items = {}
                for item in new_items:
                    name_raw = str(item.get("name", "")).strip()
                    original_name = next((m["name"] for m in menu if m["name"].lower() == name_raw.lower()), None)
                    if original_name:
                        updated_items[original_name] = {
                            "name": original_name,
                            "qty": max(1, int(item.get("qty", 1))),
                            "details": item.get("details", "")
                        }
                if updated_items:
                    current_items = updated_items
            else:
                for item in new_items:
                    name_raw = str(item.get("name", "")).strip()
                    original_name = next((m["name"] for m in menu if m["name"].lower() == name_raw.lower()), None)
                    if original_name:
                        current_items[original_name] = {
                            "name": original_name,
                            "qty": max(1, int(item.get("qty", 1))),
                            "details": item.get("details", "")
                        }

        return {
            "customer_name": self.pick(ai_data.get("customer_name"), current_order.get("customer_name", "")),
            "phone_no": self.pick(ai_data.get("phone_no"), current_order.get("phone_no", "")),
            "address": self.pick(ai_data.get("address"), current_order.get("address", "")),
            "payment_method": self.pick(ai_data.get("payment_method"), current_order.get("payment_method", "")),
            "items": list(current_items.values())
        }

    async def process(self, text, shop_name, category, menu, current_order):
        clean_text = text.strip().lower()
        
        greetings = ["hi", "hello", "hey", "မင်္ဂလာပါ", "start", "/start", "restart"]
        if any(clean_text == g for g in greetings):
            return {
                "reply_text": f"မင်္ဂလာပါ! {shop_name} ({category}) မှ ကြိုဆိုပါတယ်။ 🙏\nဒီနေ့ ဘာများ မှာယူမလဲခင်ဗျာ?",
                "final_order_data": {"customer_name": "", "phone_no": "", "address": "", "payment_method": "", "items": []}
            }

        updated_order = current_order
        try:
            system_prompt = self.get_system_prompt(shop_name, category, menu, current_order)
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
                content = res.json()["choices"][0]["message"]["content"]
                updated_order = self.safe_parse(content, current_order, menu, text)
            else:
                logging.error(f"Groq API Error: {res.status_code} - {res.text}")
        except Exception as e:
            logging.error(f"AI Process Error: {e}")

        # Logic for missing information
        if not updated_order.get("items"):
            return {"reply_text": "ဘာများ မှာယူမလဲခင်ဗျာ? မှာချင်တဲ့ ပစ္စည်းနဲ့ အရေအတွက်လေး ပြောပေးပါ။", "final_order_data": updated_order}

        # Category specific missing info checks
        if category == 'clothing':
            for item in updated_order['items']:
                if not item.get('details') or 'size' not in item['details'].lower() or 'color' not in item['details'].lower():
                    return {"reply_text": f"{item['name']} အတွက် Size နဲ့ Color လေး ပြောပေးပါဦးခင်ဗျာ။", "final_order_data": updated_order}
        elif category == 'beauty':
            for item in updated_order['items']:
                if not item.get('details') or 'skin' not in item['details'].lower():
                    return {"reply_text": f"{item['name']} အတွက် Skin Type လေး ပြောပေးပါဦးခင်ဗျာ။", "final_order_data": updated_order}

        if not all([updated_order.get("customer_name"), updated_order.get("phone_no"), updated_order.get("address")]):
            return {"reply_text": "ဟုတ်ကဲ့ပါခင်ဗျာ။ အော်ဒါပို့ပေးဖို့အတွက် 'အမည်၊ ဖုန်းနံပါတ် နဲ့ လိပ်စာ' လေးတစ်ခါတည်း ပြောပေးပါဦးခင်ဗျာ။", "final_order_data": updated_order}

        if not updated_order.get("payment_method"):
            return {"reply_text": "ငွေပေးချေမှုကို 'COD (ပစ္စည်းရောက်ငွေချေ)' လား 'Prepaid (ကြိုတင်ငွေလွှဲ)' လားဘယ်လိုလုပ်မလဲခင်ဗျာ?", "final_order_data": updated_order}

        confirm_words = ["confirm", "ok", "ဟုတ်", "မှန်တယ်", "မှာမယ်", "အိုကေ", "yes"]
        clean_input = re.sub(r"[^\w]+", "", clean_text)
        
        if any(w in clean_input for w in confirm_words):
            return {
                "reply_text": "အော်ဒါကို အတည်ပြုလိုက်ပါပြီ။ ကျေးဇူးတင်ပါတယ်! 🙏",
                "intent": "confirmed",
                "final_order_data": updated_order
            }

        return {
            "reply_text": self.build_summary_layout(updated_order),
            "final_order_data": updated_order,
            "ui": "confirm_buttons"
        }

ai = AI()
