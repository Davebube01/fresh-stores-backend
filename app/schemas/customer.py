from pydantic import BaseModel
from datetime import datetime

# "Spent" everywhere below means money actually taken: orders paid online, plus
# cash-on-delivery orders once delivered. Unpaid and cancelled orders don't count.


class CustomerResponse(BaseModel):
    id: str
    name: str | None = None
    email: str
    phone: str | None = None
    avatar: str | None = None
    address: str | None = None
    joinDate: datetime
    # Orders placed and not cancelled (includes ones still awaiting payment).
    ordersCount: int
    totalSpent: float
    status: str = "active"
    email_verified: bool = False
    paid_orders: int = 0
    last_order_at: datetime | None = None


class CustomerOrderItem(BaseModel):
    id: str
    quantity: int


class CustomerOrderSummary(BaseModel):
    id: str
    status: str
    total_amount: float
    created_at: datetime
    items: list[CustomerOrderItem] = []
    delivery_method: str | None = None
    payment_method: str | None = None
    delivery_zone: str | None = None


class CustomerFavourite(BaseModel):
    product_id: str
    name: str
    slug: str | None = None
    image_url: str | None = None
    units: float
    times_ordered: int


class CustomerAddress(BaseModel):
    address: str
    zone: str | None = None
    times_used: int
    last_used: datetime


class CustomerDetailResponse(CustomerResponse):
    recent_orders: list[CustomerOrderSummary] = []
    cancelled_orders: int = 0
    avg_order_value: float = 0.0
    first_order_at: datetime | None = None
    favourites: list[CustomerFavourite] = []
    addresses: list[CustomerAddress] = []


class CustomersSummary(BaseModel):
    total_customers: int
    new_this_month: int
    # Placed at least one order in the last 30 days.
    active_last_30_days: int
    # Two or more paid orders.
    repeat_customers: int
    verified: int
    # Distinct emails that checked out without an account.
    guest_customers: int


class CustomerStatusUpdate(BaseModel):
    is_active: bool
