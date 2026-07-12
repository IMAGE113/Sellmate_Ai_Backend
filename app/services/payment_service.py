from typing import Dict, Any, Optional
from app.db.database import BaseRepository, OrderRepository, AuditRepository

class PaymentRepository(BaseRepository):
    async def create_review(self, order_id: int, business_id: int, screenshot_url: str) -> Dict[str, Any]:
        query = """
            INSERT INTO payment_reviews (business_id, shop_id, order_id, screenshot_url, status)
            VALUES ($1, $2, $3, $4, 'PENDING')
            RETURNING *
        """
        return await self.fetch_one(query, business_id, self.shop_id, order_id, screenshot_url)

    async def update_review_status(self, review_id: int, status: str, reviewer_id: int, notes: str = None):
        query = """
            UPDATE payment_reviews 
            SET status = $1, reviewer_id = $2, review_notes = $3, updated_at = CURRENT_TIMESTAMP
            WHERE id = $4 AND shop_id = $5
            RETURNING *
        """
        return await self.fetch_one(query, status, reviewer_id, notes, review_id, self.shop_id)

class PaymentService:
    def __init__(self, payment_repo: PaymentRepository, order_repo: OrderRepository, audit_repo: AuditRepository):
        self.payment_repo = payment_repo
        self.order_repo = order_repo
        self.audit_repo = audit_repo

    async def submit_screenshot(self, order_id: int, business_id: int, screenshot_url: str):
        review = await self.payment_repo.create_review(order_id, business_id, screenshot_url)
        
        # Update order status
        await self.order_repo.update_order_status(
            order_id, 'PAYMENT_PENDING_REVIEW', 'customer', 'Payment screenshot uploaded'
        )
        
        await self.audit_repo.log_event(
            event_type="ADMIN_ACTION",
            actor_source="customer",
            description="Payment screenshot submitted for review",
            order_id=order_id,
            details={"review_id": review["id"]}
        )
        return review

    async def review_payment(self, review_id: int, status: str, reviewer_id: int, notes: str = None):
        review = await self.payment_repo.update_review_status(review_id, status, reviewer_id, notes)
        if not review:
            raise ValueError("Review record not found")
        
        order_id = review["order_id"]
        if status == 'CONFIRMED':
            await self.order_repo.update_order_status(
                order_id, 'PAYMENT_CONFIRMED', 'admin', 'Payment confirmed by admin'
            )
            event_type = "PAYMENT_CONFIRMED"
        else:
            await self.order_repo.update_order_status(
                order_id, 'WAITING_PAYMENT', 'admin', 'Payment rejected by admin'
            )
            event_type = "PAYMENT_REJECTED"
            
        await self.audit_repo.log_event(
            event_type=event_type,
            actor_source="admin",
            description=f"Payment review {status.lower()}",
            order_id=order_id,
            details={"review_id": review_id, "notes": notes}
        )
        return review
