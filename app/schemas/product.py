from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from datetime import datetime
from app.core.product_options import normalize_weight_options


class WeightOption(BaseModel):
    """One size a product is sold in, with its own price and stock usage."""
    label: str = Field(min_length=1, max_length=40)
    price: float = Field(ge=0)
    # How much of the product's stock_quantity one of these uses up, in the
    # product's stock unit (e.g. 2 for "2kg" of a cut stocked in kg).
    stock_units: float = Field(gt=0)


def _check_options(options: list[WeightOption] | None) -> list[WeightOption] | None:
    """Rules for options an admin is saving (reads tolerate older data)."""
    if options:
        if any(o.price <= 0 for o in options):
            raise ValueError("Every size needs a price above zero")
        labels = [o.label.strip().lower() for o in options]
        if len(labels) != len(set(labels)):
            raise ValueError("Each size needs a different label")
    return options


class ProductBase(BaseModel):
    name: str
    slug: str
    price: float
    description: str | None = None
    image_url: str | None = None
    category: str
    weight_options: list[WeightOption] = []
    parts: list[str] = []
    stock_quantity: float = 0.0
    is_active: bool = True

    @field_validator("weight_options", mode="before")
    @classmethod
    def _upgrade_legacy_options(cls, value, info: ValidationInfo):
        # Rows saved before sizes had prices hold bare labels; price them
        # from the product's base price so reads and checkout stay consistent.
        return normalize_weight_options(value, info.data.get("price") or 0)

class ProductCreate(ProductBase):
    price: float = Field(gt=0)
    stock_quantity: float = Field(default=0.0, ge=0)
    # Cost per unit of stock. Never sent to customers.
    cost_price: float | None = Field(default=None, ge=0)
    # Null = use the store-wide default.
    low_stock_threshold: float | None = Field(default=None, ge=0)

    @field_validator("weight_options")
    @classmethod
    def _validate_options(cls, value):
        return _check_options(value)

class ProductUpdate(BaseModel):
    name: str | None = None
    price: float | None = Field(default=None, gt=0)
    description: str | None = None
    image_url: str | None = None
    category: str | None = None
    weight_options: list[WeightOption] | None = None
    parts: list[str] | None = None
    cost_price: float | None = Field(default=None, ge=0)
    low_stock_threshold: float | None = Field(default=None, ge=0)
    # stock_quantity is deliberately absent here — once a product exists,
    # stock only changes through adjust_stock (checkout, cancellation, or
    # the admin "Adjust Stock" action), so every change gets a StockMovement
    # row. Initial stock is still set via ProductCreate.
    is_active: bool | None = None

    @field_validator("weight_options")
    @classmethod
    def _validate_options(cls, value):
        return _check_options(value)

class ProductResponse(ProductBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminProductResponse(ProductResponse):
    """ProductResponse plus fields only the admin may see."""
    cost_price: float | None = None
    # The product's own threshold (null = store default) and the one in effect.
    low_stock_threshold: float | None = None
    effective_low_stock_threshold: float | None = None


class ProductDetailResponse(BaseModel):
    """Everything the storefront product page needs, in one request."""
    product: ProductResponse
    # Display name of product.category (a slug); null if it isn't a known,
    # active category.
    category_name: str | None = None
    related: list[ProductResponse] = []


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
