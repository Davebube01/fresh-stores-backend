from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, true

from app.core.database import Base


class StoreSettings(Base):
    """The store's editable details. There is only ever one row (id=1)."""
    __tablename__ = "store_settings"

    id = Column(Integer, primary_key=True, default=1)
    store_name = Column(String, nullable=False, default="Everything Fresh")
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)
    address = Column(String, nullable=True)
    # Where customers collect pickup orders, and what they should know.
    pickup_address = Column(String, nullable=True)
    pickup_instructions = Column(String, nullable=True)
    # The public About page. Empty = the page's neutral default wording.
    about_headline = Column(String, nullable=True)
    about_story = Column(String, nullable=True)
    # Products at or below this count as "low stock" on the dashboard/inventory.
    low_stock_threshold = Column(Float, nullable=False, default=5.0, server_default="5")

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DeliveryZone(Base):
    """
    An area we deliver to and its ESTIMATED courier fee. The fee is shown at
    checkout and recorded on the order, but paid to the courier in cash —
    never charged online.
    """
    __tablename__ = "delivery_zones"

    # Stable slug: orders store it in deliveries.delivery_zone.
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    fee = Column(Float, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=true())
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
