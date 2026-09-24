from pydantic import BaseModel
from datetime import datetime

class CustomerResponse(BaseModel):
    id: str
    name: str | None = None
    email: str
    phone: str | None = None
    avatar: str | None = None
    address: str | None = None
    joinDate: datetime
    ordersCount: int
    totalSpent: float
    status: str = "active"

class CustomerOrderItem(BaseModel):
    id: str
    quantity: int


class CustomerOrderSummary(BaseModel):
    id: str
    status: str
    total_amount: float
    created_at: datetime
    items: list[CustomerOrderItem] = []


class CustomerDetailResponse(CustomerResponse):
    recent_orders: list[CustomerOrderSummary] = []
