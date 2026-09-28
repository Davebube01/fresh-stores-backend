from datetime import datetime

from pydantic import BaseModel


class InventorySummary(BaseModel):
    active_products: int
    in_stock: int
    low_stock: int  # above zero but at or below the threshold
    out_of_stock: int
    units_on_hand: float
    # stock × current price, active products only (for sized products that's
    # their cheapest size, so treat it as an estimate)
    stock_value: float
    # stock × cost price, over products that have one
    stock_cost_value: float
    # active products with no cost price yet (not in stock_cost_value)
    products_without_cost: int
    low_stock_threshold: float


class RestockItem(BaseModel):
    id: str
    name: str
    slug: str
    image_url: str | None = None
    category: str
    price: float
    stock_quantity: float
    # Units that left through orders in the last 7 days (net of cancellations).
    sold_last_7_days: float
    # Rough runway at that pace; null when nothing sold recently.
    days_left: float | None = None


class InventoryMovement(BaseModel):
    id: str
    product_id: str
    product_name: str
    product_slug: str | None = None
    change: float
    previous_quantity: float
    new_quantity: float
    reason: str
    note: str | None = None
    order_id: str | None = None
    admin_name: str | None = None
    created_at: datetime


class InventoryResponse(BaseModel):
    summary: InventorySummary
    needs_restock: list[RestockItem]
    movements: list[InventoryMovement]
    movements_total: int
