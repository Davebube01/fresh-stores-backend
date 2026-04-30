import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Cart(Base):
    __tablename__ = "carts"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    # If guest cart, user_id might be null, but keeping it simple for now, we'll optionalize it.
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    session_id = Column(String, index=True, nullable=True) # for guest carts
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")
    user = relationship("User")

class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    cart_id = Column(String, ForeignKey("carts.id"), nullable=False)
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    selected_option = Column(String, nullable=True) # e.g. "1kg" or "Leg"

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    cart = relationship("Cart", back_populates="items")
    product = relationship("Product")
