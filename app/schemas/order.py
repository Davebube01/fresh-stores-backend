from pydantic import BaseModel, ConfigDict
from typing import List, Any
from datetime import datetime
from app.schemas.product import ProductResponse

class OrderItemCreate(BaseModel):
    product_id: str
    quantity: int
    selected_option: str | None = None
    price_at_time: float

class OrderItemResponse(OrderItemCreate):
    id: str
    order_id: str
    product: ProductResponse
    
    model_config = ConfigDict(from_attributes=True)

class GuestInfo(BaseModel):
    fullName: str
    email: str
    phone: str

class DeliveryInfo(BaseModel):
    deliveryDate: str | None = None
    address: str
    apartment: str | None = None
    city: str
    state: str
    landmark: str | None = None
    zipCode: str | None = None
    instructions: str | None = None
    deliveryZone: str
    deliveryFee: float = 0.0
    timeSlot: str | None = None

class OrderCreate(BaseModel):
    is_guest: bool = False
    guest_info: GuestInfo | None = None
    delivery_info: DeliveryInfo | None = None
    delivery_method: str = "delivery"
    payment_method: str
    items: List[OrderItemCreate] | None = None # Can be populated from request or from DB cart
    cart_id: str | None = None # If checking out from existing cart

class OrderResponse(BaseModel):
    id: str
    user_id: str | None = None
    guest_info: Any | None = None
    status: str
    delivery_method: str = "delivery"
    payment_method: str | None = None
    payment_reference: str | None = None
    subtotal: float
    delivery_fee: float
    total_amount: float
    items: List[OrderItemResponse] = []
    created_at: datetime
    updated_at: datetime
    paid_at: datetime | None = None
    
    model_config = ConfigDict(from_attributes=True)
