from typing import Dict, Any
from app.services.script_service import ScriptService

class ResponseBuilder:
    """
    Builds deterministic responses using merchant scripts and dynamic placeholders.
    """
    def __init__(self, script_service: ScriptService):
        self.script_service = script_service

    async def build_response(self, status_key: str, context: Dict[str, Any]) -> str:
        # 1. Fetch template (Merchant override -> Default)
        template = await self.script_service.get_script(status_key)
        
        # 2. Resolve Placeholders
        placeholders = {
            "shop_name": context.get("shop_name", ""),
            "customer_name": context.get("customer_name", "Customer"),
            "order_total": context.get("order_total", 0),
            "missing_fields": ", ".join(context.get("missing_fields", [])),
            "payment_methods": context.get("payment_methods", "KBZPay, WavePay")
        }
        
        # 3. Dynamic Replacement
        try:
            return template.format(**placeholders)
        except Exception:
            # Fallback if template formatting fails
            return template
