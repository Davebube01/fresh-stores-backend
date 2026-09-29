from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.core.database import Base


class LegalPage(Base):
    """The store's own text for a legal page. No row = the built-in default."""
    __tablename__ = "legal_pages"

    slug = Column(String, primary_key=True)  # "terms" | "privacy"
    body = Column(String, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by = Column(String, nullable=True)  # admin's name, for the record
