import uuid
from datetime import datetime, timezone
import enum
from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, Boolean, JSON, Enum
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_VERIFICATION = "awaiting_verification"
    PAID = "paid"
    PROCESSING = "processing"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class DeliveryMethod(str, enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"

class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    # user_id is optional for guest checkouts
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    
    # Guest and delivery info stored as JSON for simplicity, or we can use relationships
    guest_info = Column(JSON, nullable=True) # { fullName, email, phone }
    
    status = Column(Enum(OrderStatus, values_callable=lambda x: [e.value for e in x]), default=OrderStatus.PENDING, index=True)
    delivery_method = Column(Enum(DeliveryMethod, values_callable=lambda x: [e.value for e in x]), default=DeliveryMethod.DELIVERY, index=True)
    payment_method = Column(String, nullable=True) # paystack, flutterwave, cod
    
    # Payment tracking
    payment_reference = Column(String, unique=True, index=True, nullable=True)
    payment_gateway_response = Column(JSON, nullable=True)
    
    subtotal = Column(Float, nullable=False, default=0.0)
    delivery_fee = Column(Float, nullable=False, default=0.0)
    total_amount = Column(Float, nullable=False, default=0.0)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    paid_at = Column(DateTime(timezone=True), nullable=True)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    user = relationship("User")
    delivery = relationship("Delivery", back_populates="order", uselist=False)

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    selected_option = Column(String, nullable=True)
    price_at_time = Column(Float, nullable=False) # Important for historical records

    order = relationship("Order", back_populates="items")
    product = relationship("Product")
