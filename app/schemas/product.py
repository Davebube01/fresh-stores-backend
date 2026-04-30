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
    stock_quantity: float | None = None
    is_active: bool | None = None

class ProductResponse(ProductBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
