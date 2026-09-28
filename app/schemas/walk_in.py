from datetime import date
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


class VoidSaleRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class WalkInSaleRow(AdminOrderRow):
    served_by_name: str | None = None


class SalesSummary(BaseModel):
    count: int
    total: float
    # Money taken per payment method (cash, transfer, pos), for cashing up.
    by_payment_method: dict[str, float]
    voided_count: int
    voided_total: float


class SalesDay(BaseModel):
    date: date
    summary: SalesSummary
    sales: list[WalkInSaleRow]
