"""
When an unpaid online order stops being payable.

Measured from the last payment attempt (updated_at moves whenever a payment
is initialised), so a customer who starts paying near the deadline isn't cut
off mid-payment — but never past a hard cap from creation, so retrying can't
hold stock forever. Cash-on-delivery orders have no deadline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.core.config import settings

UNPAID_STATUSES = ("pending", "awaiting_verification")


def payment_deadline(status, payment_method: Optional[str], created_at: datetime, updated_at: Optional[datetime]) -> Optional[datetime]:
    status = getattr(status, "value", status)
    if status not in UNPAID_STATUSES or payment_method == "cod":
        return None
    window = timedelta(minutes=settings.ORDER_PAYMENT_WINDOW_MINUTES)
    cap = timedelta(minutes=settings.ORDER_MAX_PAYMENT_HOLD_MINUTES)
    return min((updated_at or created_at) + window, created_at + cap)
