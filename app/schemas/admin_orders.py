from typing import Literal

from pydantic import BaseModel

from app.schemas.order import OrderResponse

# Tabs on the admin Orders page. "needs_action" = the admin has to do
# something: paid/processing orders, and accepted cash-on-delivery orders.
OrderView = Literal[
    "all", "needs_action", "unpaid", "paid", "processing", "in_transit", "delivered", "cancelled",
]


class AdminOrderRow(OrderResponse):
    """An order plus who placed it, so the list needs no second request."""
    customer_name: str
    customer_email: str | None = None
    customer_phone: str | None = None
    is_guest: bool
    # The delivery slot has ended but the order hasn't gone out yet.
    overdue: bool = False
    delivery_zone_name: str | None = None
    # Statuses PUT /status will accept right now (dispatch, PIN confirmation
    # and cancelling have their own endpoints).
    allowed_moves: list[str] = []


class OrdersSummary(BaseModel):
    counts: dict[str, int]  # one per OrderView
    overdue: int
