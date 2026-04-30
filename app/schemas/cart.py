from pydantic import BaseModel, ConfigDict
from typing import List
from datetime import datetime
from app.schemas.product import ProductResponse

class CartItemBase(BaseModel):
    product_id: str
    quantity: int = 1
    selected_option: str | None = None

class CartItemCreate(CartItemBase):
    pass

class CartItemUpdate(BaseModel):
    quantity: int

class CartItemResponse(CartItemBase):
    id: str
    cart_id: str
    product: ProductResponse
    
    model_config = ConfigDict(from_attributes=True)

class CartResponse(BaseModel):
    id: str
    user_id: str | None = None
    session_id: str | None = None
    items: List[CartItemResponse] = []
    created_at: datetime
    updated_at: datetime
    
    @property
    def total_items(self) -> int:
        return sum(item.quantity for item in self.items)
    
    @property
    def subtotal(self) -> float:
        return sum(item.quantity * item.product.price for item in self.items)

    model_config = ConfigDict(from_attributes=True)
