from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, String

from app.core.database import Base


class TillCount(Base):
    """
    The end-of-day cash-up for one Abuja day: what was counted in the till
    against what the day's cash sales say should be there. Counting again
    replaces it (the activity log keeps every count).
    """
    __tablename__ = "till_counts"

    day = Column(Date, primary_key=True)
    opening_float = Column(Float, nullable=False, default=0.0)
    counted_cash = Column(Float, nullable=False)
    # What the system expected (float + cash sales) when the count was saved.
    # If a sale is voided or rung up afterwards, the page says so.
    expected_cash = Column(Float, nullable=False)
    note = Column(String, nullable=True)
    counted_by_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    counted_by = Column(String, nullable=True)  # name, for the record
    counted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
