from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class OrderUpdateSchema(BaseModel):
    status: str
    actor: str
    description: str
    metadata: Optional[Dict[str, Any]] = None

class OrderTimelineEventSchema(BaseModel):
    timestamp: datetime
    status: str
    actor: str
    description: str
