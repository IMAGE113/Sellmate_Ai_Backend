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
        
        await self.order_repo.update_order_status(order_id, new_status, actor, description)
        await self.audit_repo.log_event(
            event_type="ORDER_STATUS_CHANGE",
            actor_source=actor,
            description=description,
            order_id=order_id,
            details={"old_status": current_status, "new_status": new_status}
        )
