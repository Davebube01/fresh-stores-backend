from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.admin_orders import AdminOrderRow

# How the customer paid at the counter. "pos" = card on a POS terminal.
CounterPayment = Literal["cash", "transfer", "pos"]


class WalkInItem(BaseModel):
    product_id: str
    # How many of the chosen size. Ignored (must be 1) for a weighed line.
    quantity: int = Field(default=1, ge=1, le=1000)
    weight_option: str | None = None
    part: str | None = None
    # A weighed amount off the scale, in the product's stock unit (e.g. 1.7
    # for 1.7kg), charged at its per-unit price. Use instead of weight_option.
    amount: float | None = Field(default=None, gt=0, le=10000)

    @model_validator(mode="after")
    def _one_way_to_size(self):
        if self.amount is not None and self.weight_option is not None:
            raise ValueError("Choose a size or enter a weighed amount, not both")
        if self.amount is not None and self.quantity != 1:
            raise ValueError("A weighed line is sold once; enter the total amount instead")
        return self


class WalkInSaleCreate(BaseModel):
    items: list[WalkInItem] = Field(min_length=1, max_length=50)
    payment_method: CounterPayment
    customer_name: str | None = Field(default=None, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=30)
    discount_amount: float = Field(default=0, ge=0)
    discount_note: str | None = Field(default=None, max_length=200)
    # Cash only: what the customer handed over (for the change on the receipt).
    cash_tendered: float | None = Field(default=None, ge=0, le=100_000_000)
    # A unique key per sale from the till; retrying with it can't sell twice.
    client_ref: str | None = Field(default=None, min_length=8, max_length=64)


class VoidSaleRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class WalkInSaleRow(AdminOrderRow):
    served_by_name: str | None = None
    cash_tendered: float | None = None


class SalesSummary(BaseModel):
    count: int
    total: float
    # Money taken per payment method (cash, transfer, pos), for cashing up.
    by_payment_method: dict[str, float]
    voided_count: int
    voided_total: float


class TillCountIn(BaseModel):
    opening_float: float = Field(default=0, ge=0, le=100_000_000)
    counted_cash: float = Field(ge=0, le=100_000_000)
    note: str | None = Field(default=None, max_length=300)


class TillCountOut(BaseModel):
    day: date
    opening_float: float
    counted_cash: float
    expected_cash: float
    # counted - expected at the time of the count: negative = short.
    difference: float
    note: str | None = None
    counted_by: str | None = None
    counted_at: datetime

    model_config = {"from_attributes": True}


class TopItem(BaseModel):
    product_id: str
    name: str
    quantity: int
    total: float


class HourTotal(BaseModel):
    hour: int  # 0-23, Abuja time
    count: int
    total: float


class SalesDay(BaseModel):
    date: date
    summary: SalesSummary
    sales: list[WalkInSaleRow]
    # Cash that should be in the till before any float: the day's cash sales.
    cash_expected: float
    till: TillCountOut | None = None
    top_items: list[TopItem] = []
    hourly: list[HourTotal] = []
    # Only for roles that can see costs; None otherwise.
    profit: float | None = None
    # False when some lines have no cost price, so profit is understated.
    profit_complete: bool = True
