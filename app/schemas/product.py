from pydantic import BaseModel, ConfigDict
from datetime import datetime

class ProductBase(BaseModel):
    name: str
    slug: str
    price: float
    description: str | None = None
    image_url: str | None = None
    category: str
    weight_options: list[str] = []
    parts: list[str] = []
    stock_quantity: float = 0.0
    is_active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    description: str | None = None
    image_url: str | None = None
    category: str | None = None
    weight_options: list[str] | None = None
    parts: list[str] | None = None
    # stock_quantity is deliberately absent here — once a product exists,
    # stock only changes through adjust_stock (checkout, cancellation, or
    # the admin "Adjust Stock" action), so every change gets a StockMovement
    # row. Initial stock is still set via ProductCreate.
    is_active: bool | None = None

class ProductResponse(ProductBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockAdjustmentRequest(BaseModel):
    # Positive to add stock (restock), negative to remove it (correction —
    # e.g. spoilage, a recount, damaged goods).
    change: float
    reason: str = "restock"
    note: str | None = None


class StockMovementResponse(BaseModel):
    id: str
    product_id: str
    change: float
    previous_quantity: float
    new_quantity: float
    reason: str
    note: str | None = None
    order_id: str | None = None
    admin_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
