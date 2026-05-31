from pydantic import BaseModel, Field
from typing import List, Optional

class OrderItemSchema(BaseModel):
    name: str
    qty: int = Field(gt=0)
    size: Optional[str] = None
    color: Optional[str] = None

class AIParserOutputSchema(BaseModel):
    intent: str
    items: List[OrderItemSchema] = []
    customer_name: Optional[str] = None
    phone_no: Optional[str] = None
    address: Optional[str] = None
    payment_method: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    error: Optional[str] = None
