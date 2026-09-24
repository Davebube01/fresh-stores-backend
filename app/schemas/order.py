from pydantic import BaseModel, ConfigDict, computed_field
from app.core.payment_window import payment_deadline
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

class DeliveryResponse(BaseModel):
    id: str
    address: str
    apartment: str | None = None
    city: str
    state: str
    landmark: str | None = None
    zip_code: str | None = None
    instructions: str | None = None
    delivery_zone: str
    delivery_date: str | None = None
    time_slot: str | None = None
    tracking_number: str | None = None
    delivery_status: str | None = None
    # Courier is assigned manually by the admin at dispatch time — there's no
    # live courier API, this is just a record of who's carrying the order.
    courier_name: str | None = None
    courier_phone: str | None = None
    courier_service: str | None = None
    courier_reference: str | None = None
    # Shown to the customer; the courier must collect it and relay it back
    # to confirm delivery. Deliberately included in the same response the
    # customer reads — they're the one who's supposed to hold this.
    delivery_pin: str | None = None

    model_config = ConfigDict(from_attributes=True)

class DispatchUpdate(BaseModel):
    courier_name: str
    courier_phone: str
    courier_service: str  # e.g. "Bolt", "Personal Rider", "In-house"
    courier_reference: str | None = None

class ConfirmDeliveryRequest(BaseModel):
    pin: str

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
    delivery: DeliveryResponse | None = None
    created_at: datetime
    updated_at: datetime
    paid_at: datetime | None = None
    cancellation_reason: str | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None

    @computed_field
    @property
    def payment_expires_at(self) -> datetime | None:
        """Until when an unpaid online order can still be paid; null if it isn't awaiting payment."""
        return payment_deadline(self.status, self.payment_method, self.created_at, self.updated_at)

    model_config = ConfigDict(from_attributes=True)


class CancelOrderRequest(BaseModel):
    reason: str


class OrderSummary(BaseModel):
    all: int = 0
    ongoing: int = 0
    completed: int = 0
    cancelled: int = 0
