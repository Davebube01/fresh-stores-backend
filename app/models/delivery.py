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

    # Courier is assigned manually by the admin at dispatch time — there's
    # no live courier API, so this is just a record of who's carrying the
    # order, shown to the customer so they know who to expect and pay.
    courier_name = Column(String, nullable=True)
    courier_phone = Column(String, nullable=True)
    courier_service = Column(String, nullable=True)  # e.g. "Bolt", "Personal Rider", "In-house"
    courier_reference = Column(String, nullable=True)  # optional trip/receipt reference from the courier

    # The customer holds this, shown on their tracking page. The courier
    # must collect it on handoff and relay it back — only entering the
    # matching PIN flips the order to "delivered", so that status means
    # someone actually confirmed the order reached the customer instead of
    # just an admin's guess.
    delivery_pin = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    order = relationship("Order", back_populates="delivery")
