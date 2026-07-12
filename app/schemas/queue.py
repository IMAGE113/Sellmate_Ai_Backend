from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from uuid import UUID

class QueuePayloadSchema(BaseModel):
    shop_id: str
    chat_id: int
    event_type: str
    correlation_id: UUID
    data: Dict[str, Any] = {}

class NotificationPayloadSchema(BaseModel):
    shop_id: str
    admin_chat_id: int
    message: str
    priority: str = "normal"
