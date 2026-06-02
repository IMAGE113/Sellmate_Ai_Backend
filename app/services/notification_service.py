from typing import Dict, Any, List, Optional
from app.db.database import BaseRepository

class NotificationRepository(BaseRepository):
    async def queue_notification(self, business_id: int, order_id: Optional[int], admin_chat_id: int, n_type: str, message: str):
        query = """
            INSERT INTO notifications (business_id, shop_id, order_id, admin_chat_id, type, message, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'PENDING')
            RETURNING *
        """
        return await self.fetch_one(query, business_id, self.shop_id, order_id, admin_chat_id, n_type, message)

    async def get_pending_notifications(self) -> List[Dict[str, Any]]:
        query = "SELECT * FROM notifications WHERE status IN ('PENDING', 'RETRYING') AND retries < 5"
        return await self.fetch_all(query)

    async def update_notification_status(self, n_id: int, status: str, retries: int = None):
        query = """
            UPDATE notifications 
            SET status = $1, retries = COALESCE($2, retries), last_attempt = CURRENT_TIMESTAMP
            WHERE id = $3
        """
        await self.execute(query, status, retries, n_id)

class NotificationService:
    def __init__(self, notification_repo: NotificationRepository):
        self.notification_repo = notification_repo

    async def notify_admins(self, business_id: int, order_id: Optional[int], n_type: str, message: str, admin_chat_ids: List[int]):
        for chat_id in admin_chat_ids:
            await self.notification_repo.queue_notification(
                business_id, order_id, chat_id, n_type, message
            )
