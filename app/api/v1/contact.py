from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.contact import ContactMessage
from app.models.notification import AdminNotification
from app.models.user import User
from app.schemas.contact import TOPIC_LABELS, ContactIn
from app.utils.dependencies import get_optional_current_user

router = APIRouter()


@router.post("", status_code=201)
@limiter.limit("5/hour")
async def send_contact_message(
    request: Request,
    body: ContactIn,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Store a message from the Contact page and flag it in the admin bell."""
    if body.website:
        # A bot filled the hidden field. Look successful so it doesn't retry.
        return {"ok": True}

    msg = ContactMessage(
        name=body.name, email=body.email.lower(), phone=body.phone, topic=body.topic,
        order_ref=body.order_ref, message=body.message, user_id=user.id if user else None,
    )
    db.add(msg)
    await db.flush()
    db.add(AdminNotification(
        kind="contact_message",
        title=f"New message from {body.name}",
        body=f"{TOPIC_LABELS[body.topic]}: {body.message[:120]}",
        link=f"/admin/messages?open={msg.id}",
    ))
    await db.commit()
    return {"ok": True}
