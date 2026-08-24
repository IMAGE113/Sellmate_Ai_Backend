from typing import Dict, Any, List
from app.db.database import OrderRepository, AuditRepository

class OrderService:
    # Define strict state transitions
    VALID_TRANSITIONS = {
        'NEW_CHAT': ['COLLECTING_INFO', 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', 'CANCELLED', 'OUT_OF_STOCK', 'INVALID_VARIANT'],
        'COLLECTING_INFO': ['COLLECTING_INFO', 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', 'CANCELLED', 'OUT_OF_STOCK', 'INVALID_VARIANT'],
        'WAITING_PAYMENT': ['WAITING_PAYMENT', 'PAYMENT_PENDING_REVIEW', 'PAYMENT_CONFIRMED', 'CANCELLED'],
        'PAYMENT_PENDING_REVIEW': ['PAYMENT_CONFIRMED', 'WAITING_PAYMENT', 'CANCELLED'],
        'PAYMENT_CONFIRMED': ['READY_TO_SHIP', 'CANCELLED', 'COMPLETED'],
        'READY_TO_SHIP': ['COMPLETED', 'CANCELLED'],
        'OUT_OF_STOCK': ['COLLECTING_INFO', 'CANCELLED'],
        'INVALID_VARIANT': ['COLLECTING_INFO', 'CANCELLED'],
        'COMPLETED': ['CANCELLED'], # BUG-30: Allow cancellation within grace period
        'CANCELLED': ['NEW_CHAT', 'COLLECTING_INFO'] # Allow restart
    }

    def __init__(self, order_repo: OrderRepository, audit_repo: AuditRepository):
        self.order_repo = order_repo
        self.audit_repo = audit_repo

    async def get_or_create_active_order(self, chat_id: int, business_id: int, force_new: bool = False) -> Dict[str, Any]:
        # Bug Fix: Active order duplication. Always check for existing active order first unless force_new is requested.
        # Even with force_new, we should ensure existing orders are handled or transitioned.
        existing_order = await self.order_repo.get_active_order_by_chat_id(chat_id)
        
        if force_new and existing_order:
            # If force_new is True, we cancel the old one first to maintain single active order invariant
            await self.update_status(existing_order["id"], "CANCELLED", "system", "New order requested, cancelling old active order")
            existing_order = None

        if not existing_order:
            order = await self.order_repo.create_order(chat_id, business_id)
            await self.audit_repo.log_event(
                event_type="ORDER_STATUS_CHANGE",
                actor_source="system",
                description="New order created from chat" + (" (forced)" if force_new else ""),
                order_id=order["id"]
            )
            return order

        return existing_order

    async def update_status(self, order_id: int, new_status: str, actor: str, description: str):
        order = await self.order_repo.get_order_by_id(order_id)
        if not order:
            raise ValueError("Order not found")
        
        current_status = order["status"]
        
        # Bug Fix: Invalid order lifecycle transitions. Allow same-status updates for metadata, but block illegal jumps.
        if current_status == new_status:
            return
            
        if new_status not in self.VALID_TRANSITIONS.get(current_status, []):
            # Log violation attempt
            await self.audit_repo.log_event(
                event_type="INVALID_TRANSITION_ATTEMPT",
                actor_source=actor,
                description=f"Attempted invalid transition from {current_status} to {new_status}",
                order_id=order_id
            )
            raise ValueError(f"Invalid transition from {current_status} to {new_status}")
        
        # Task 2 Fix: If order is cancelled, restore stock if it was previously finalized
        extracted_data = order.get('extracted_data', {})
        if isinstance(extracted_data, str):
            import json
            try:
                extracted_data = json.loads(extracted_data)
            except:
                extracted_data = {}
        
        if new_status == 'CANCELLED' and extracted_data.get('is_finalized'):
            from app.db.database import ProductRepository
            product_repo = ProductRepository(self.order_repo.pool, order['shop_id'])
            reservations = extracted_data.get("inventory_reservations") or []
            if reservations:
                restorations = [
                    (entry.get("product_id"), entry.get("qty"))
                    for entry in reservations
                    if entry.get("product_id") is not None
                ]
                if not await product_repo.restore_stock_batch(restorations):
                    raise RuntimeError("Unable to restore finalized order inventory")
            else:
                # Legacy finalized orders lack reservation IDs. Restore only unambiguous
                # parent products; never guess a variant from free-form details.
                for item in extracted_data.get('items', []):
                    product_name = item.get('name')
                    quantity = item.get('qty', 0)
                    attributes = {k: v for k, v in item.items() if k in ["size", "color", "sugar_level", "ice_level"] and v}
                    if product_name and quantity > 0 and not attributes:
                        parent_product = await product_repo.get_product_by_name(product_name)
                        if parent_product and not await product_repo.get_variants_for_product(parent_product["id"]):
                            await product_repo.restore_stock_batch([(parent_product["id"], quantity)])

        await self.order_repo.update_order_status(order_id, new_status, actor, description)
        await self.audit_repo.log_event(
            event_type="ORDER_STATUS_CHANGE",
            actor_source=actor,
            description=description,
            order_id=order_id,
            details={"old_status": current_status, "new_status": new_status}
        )
