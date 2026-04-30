import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    order_id = Column(String, ForeignKey("orders.id"), unique=True, nullable=False)
    
    address = Column(String, nullable=False)
    apartment = Column(String, nullable=True)
    city = Column(String, nullable=False)
    state = Column(String, nullable=False)
    landmark = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    instructions = Column(String, nullable=True)
    
    delivery_zone = Column(String, nullable=False)
    delivery_date = Column(String, nullable=True) # Keeping as string for simplicity or DateTime
    time_slot = Column(String, nullable=True)
    
    tracking_number = Column(String, nullable=True)
    delivery_status = Column(String, default="pending") # pending, assigned, intransit, delivered
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="delivery")
