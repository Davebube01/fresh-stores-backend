import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String

from app.core.database import Base


class SavedAddress(Base):
    """A customer's saved delivery address, offered at checkout."""
    __tablename__ = "saved_addresses"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String, nullable=False)  # "Home", "Office", ...
    # Delivery zone id (see app.core.delivery_zones); decides the courier fee.
    zone_id = Column(String, nullable=False)
    address = Column(String, nullable=False)
    apartment = Column(String, nullable=True)
    landmark = Column(String, nullable=True)
    instructions = Column(String, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
