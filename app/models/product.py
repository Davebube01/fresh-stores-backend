import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Boolean, DateTime, JSON
from app.core.database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, index=True, default=generate_uuid)
    name = Column(String, index=True, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    category = Column(String, nullable=False) # e.g., 'full', 'part', 'kg'
    
    # Store options as JSON arrays
    weight_options = Column(JSON, nullable=True, default=list) # e.g., ["1kg", "5kg", "Full"]
    parts = Column(JSON, nullable=True, default=list) # e.g., ["Leg", "Ribs"]
    
    stock_quantity = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
