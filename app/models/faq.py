import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.core.database import Base


class FaqItem(Base):
    """One question on the storefront's FAQ page, edited in admin Settings."""
    __tablename__ = "faq_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # "ordering" | "delivery" | "payment" | "account"
    section = Column(String, nullable=False, default="ordering")
    question = Column(String, nullable=False)
    answer = Column(String, nullable=False)
    position = Column(Integer, nullable=False, default=0)
    is_published = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
