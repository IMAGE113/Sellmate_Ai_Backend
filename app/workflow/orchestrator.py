import logging
import json
from typing import Dict, Any, Optional
from app.db.database import MerchantRepository, OrderRepository, AuditRepository
from app.services.order_service import OrderService
from app.services.lifecycle_service import LifecycleService, LifecycleRepository
from app.workflow.flow_manager import FlowManager
from app.services.ai import ai
from app.services.validation_service import ValidationService
from app.services.script_service import ScriptService, ScriptRepository

class ConversationOrchestrator:
    """
    Centralized orchestration layer for SellMate SaaS.
    Handles the end-to-end flow from incoming message to response.
    """
    def __init__(self, pool, shop_id: str):
        self.pool = pool
        self.shop_id = shop_id
        self.merchant_repo = MerchantRepository(pool, shop_id)
        self.order_repo = OrderRepository(pool, shop_id)
        self.audit_repo = AuditRepository(pool, shop_id)
        self.script_repo = ScriptRepository(pool, shop_id)
        self.order_service = OrderService(self.order_repo, self.audit_repo)
        self.lifecycle_service = LifecycleService(LifecycleRepository(pool, shop_id))
        
    async def process_message(self, chat_id: int, user_text: str, correlation_id: str) -> str:
        # 0. Global Lifecycle Check (Hardening Phase)
        await self.lifecycle_service.validate_active(self.shop_id)

        # 1. Load Merchant Config
        biz = await self.merchant_repo.get_merchant_by_shop_id()
        if not biz:
            raise ValueError(f"Merchant {self.shop_id} not found")
            
        # 2. Check Human Takeover
        if biz.get("is_human_takeover_active"):
            return None # Bot is silent in human mode
            
        # 3. Get or Create Order
        order = await self.order_service.get_or_create_active_order(chat_id, biz["id"])
        
        # 4. Intent Classification & AI Parsing
        # (Hybrid: Deterministic rules first, then AI fallback)
        menu_rows = await self.merchant_repo.fetch_all("SELECT name, price, stock FROM products WHERE shop_id = $1", self.shop_id)
        menu = [dict(m) for m in menu_rows]
        
        extracted_json = await ai.extract_data(
            user_text, 
            biz["name"], 
            menu, 
            order.get("extracted_data", {}),
            biz.get("requirements_text")
        )
        extracted_data = json.loads(extracted_json)
        
        # 5. Merge & Validate Data
        new_extracted_data = ai.merge_data(order.get("extracted_data", {}), extracted_data)
        is_valid, errors = ValidationService.validate_extracted_data(new_extracted_data)
        
        # 6. Update Order State
        await self.order_repo.execute(
            "UPDATE orders SET extracted_data = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2",
            json.dumps(new_extracted_data), order["id"]
        )
        
        # DEBUG: Data အဝင်ကို စစ်မယ်
        print(f"DEBUG_DATA: {new_extracted_data}")

        # 7. Workflow Resolution
        intent = extracted_data.get("intent", "ORDER")
        flow = FlowManager(biz, new_extracted_data)
        status_key = flow.get_next_step(intent)
        
        # DEBUG: ဘယ် state ထွက်လဲ စစ်မယ်
        print(f"DEBUG_STATUS: {status_key}")
        
        # 8. Scripted Response Building
        # ... (ကျန်တာတွေ အတိုင်းပဲ)
        script_service = ScriptService(self.script_repo)
        response_text = await script_service.get_script(status_key, shop_name=biz["name"])
        
        # 9. Audit Logging
        await self.audit_repo.log_event(
            event_type="BOT_REPLY",
            actor_source="bot",
            description=f"Orchestrated reply for {status_key}",
            order_id=order["id"],
            details={
                "correlation_id": correlation_id,
                "intent": intent,
                "status_key": status_key,
                "errors": errors
            }
        )
        
        return response_text
