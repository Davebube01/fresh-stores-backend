from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

DashboardRange = Literal["today", "7d", "30d"]


class DashboardKpis(BaseModel):
    revenue: float
    revenue_prev: float
    orders: int
    orders_prev: int
    avg_order_value: float
    avg_order_value_prev: float
    # Revenue minus cost, over items whose cost is known; null when none are.
    gross_profit: float | None = None
    gross_profit_prev: float | None = None
    # gross_profit / the revenue it covers (0.25 = 25%).
    profit_margin: float | None = None
    # Share of revenue with a known cost; below 1 means profit is partial.
    profit_coverage: float | None = None
    # Paid or being prepared: the admin still has to hand these to a courier
    # (or mark them ready for pickup).
    awaiting_dispatch: int
    # Of those, the ones whose delivery slot has already ended.
    overdue_dispatch: int


class RevenuePoint(BaseModel):
    date: date
    revenue: float
    orders: int
    revenue_prev: float


class StatusCount(BaseModel):
    status: str
    count: int


class DashboardOrder(BaseModel):
    id: str
    customer_name: str
    status: str
    delivery_method: str | None = None
    delivery_zone: str | None = None
    time_slot: str | None = None
    total_amount: float
    items_count: int
    created_at: datetime


class SlotGroup(BaseModel):
    time_slot: str
    # "done" = slot over and nothing left to send; "overdue" = slot over with
    # orders still not dispatched; "now" = the current slot; "upcoming".
    state: Literal["done", "overdue", "now", "upcoming"]
    orders: list[DashboardOrder]


class LowStockProduct(BaseModel):
    id: str
    name: str
    slug: str
    image_url: str | None = None
    stock_quantity: float


class TopProduct(BaseModel):
    product_id: str
    name: str
    slug: str | None = None
    image_url: str | None = None
    units: int
    revenue: float
    # Null when none of this product's sales had a known cost.
    profit: float | None = None


class DashboardResponse(BaseModel):
    range: DashboardRange
    generated_at: datetime
    low_stock_threshold: float
    kpis: DashboardKpis
    revenue_series: list[RevenuePoint]
    status_breakdown: list[StatusCount]
    todays_deliveries: list[SlotGroup]
    low_stock: list[LowStockProduct]
    low_stock_count: int
    out_of_stock_count: int
    top_products: list[TopProduct]
    recent_orders: list[DashboardOrder]
