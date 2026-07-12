from typing import Dict, Any, List
from app.db.database import OrderRepository, AuditRepository

class OrderService:
    # Define strict state transitions
    VALID_TRANSITIONS = {
        'NEW_CHAT': ['COLLECTING_INFO', 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', 'CANCELLED'],
        'COLLECTING_INFO': ['COLLECTING_INFO', 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', 'CANCELLED'],
        'WAITING_PAYMENT': ['WAITING_PAYMENT', 'PAYMENT_PENDING_REVIEW', 'PAYMENT_CONFIRMED', 'CANCELLED'],
        'PAYMENT_PENDING_REVIEW': ['PAYMENT_CONFIRMED', 'WAITING_PAYMENT', 'CANCELLED'],
        'PAYMENT_CONFIRMED': ['READY_TO_SHIP', 'CANCELLED'],
        'READY_TO_SHIP': ['COMPLETED', 'CANCELLED'],
        'COMPLETED': [],
        'CANCELLED': ['NEW_CHAT', 'COLLECTING_INFO'] # Allow restart
    }

    def __init__(self, order_repo: OrderRepository, audit_repo: AuditRepository):
        self.order_repo = order_repo
        self.audit_repo = audit_repo

    async def get_or_create_active_order(self, chat_id: int, business_id: int, force_new: bool = False) -> Dict[str, Any]:
        if force_new:
            # If force_new is True, explicitly create a new order
            order = await self.order_repo.create_order(chat_id, business_id)
            await self.audit_repo.log_event(
                event_type="ORDER_STATUS_CHANGE",
                actor_source="system",
                description="New order created from chat (forced)",
                order_id=order["id"]
            )
            return order

        order = await self.order_repo.get_active_order_by_chat_id(chat_id)
        if not order:
            order = await self.order_repo.create_order(chat_id, business_id)
            await self.audit_repo.log_event(
                event_type="ORDER_STATUS_CHANGE",
                actor_source="system",
                description="New order created from chat",
                order_id=order["id"]
            )
        return order

    async def update_status(self, order_id: int, new_status: str, actor: str, description: str):
        order = await self.order_repo.get_order_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        
        current_status = order["status"]
        if new_status not in self.VALID_TRANSITIONS.get(current_status, []):
            raise ValueError(f"Invalid transition from {current_status} to {new_status}")
        
        # Task 2 Fix: If order is cancelled, restore stock if it was previously finalized
        if new_status == 'CANCELLED' and order.get('extracted_data', {}).get('is_finalized'):
            import json
            from app.db.database import ProductRepository
            product_repo = ProductRepository(self.order_repo.pool, order['shop_id'])
            extracted_data = order.get('extracted_data', {})
            if isinstance(extracted_data, str):
                extracted_data = json.loads(extracted_data)
            
            for item in extracted_data.get('items', []):
                product_name = item.get('name')
                quantity = item.get('qty', 0)
                if product_name and quantity > 0:
                    # Find the exact product/variant that was deducted
                    parent_product = await product_repo.get_product_by_name(product_name)
                    if parent_product:
                        product = None
                        variants = await product_repo.get_variants_for_product(parent_product["id"])
                        if variants:
                            attributes = {k: v for k, v in item.items() if k in ["size", "color", "sugar_level", "ice_level"]}
                            if attributes:
                                product = await product_repo.get_product_variant(parent_product["id"], attributes)
                            if not product:
                                details = item.get("details", "").lower()
                                for v in variants:
                                    if v["name"].lower() in details:
                                        product = v
                                        break
                        else:
                            product = parent_product
                        
                        if product:
                            # Restore stock (negative deduction)
                            await product_repo.update_product_stock(product["id"], -quantity)

        await self.order_repo.update_order_status(order_id, new_status, actor, description)
        await self.audit_repo.log_event(
            event_type="ORDER_STATUS_CHANGE",
            actor_source=actor,
            description=description,
            order_id=order_id,
            details={"old_status": current_status, "new_status": new_status}
        )
