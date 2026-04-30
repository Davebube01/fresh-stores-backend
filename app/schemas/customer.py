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

class CustomerDetailResponse(CustomerResponse):
    orders: list = []
