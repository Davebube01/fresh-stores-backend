import re
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.contact import ContactMessage, ContactReply
from app.models.notification import AdminNotification
from app.models.order import Order
from app.schemas.contact import ContactInbox, ContactOut, ContactReplyIn, ContactStatusUpdate, Topic
from app.services.activity_service import actor_label, log_activity
from app.services.email_service import send_contact_reply_email
from app.services.settings_service import get_store_settings
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

# What an order number can look like once "#" is dropped: the start of an order id.
_ORDER_REF = re.compile(r"^[0-9a-f-]{6,36}$")


async def _order_id_for(db: AsyncSession, ref: Optional[str]) -> Optional[str]:
    """The order a message's "order number" points at, if it's unambiguous."""
    if not ref:
        return None
    ref = ref.strip().lstrip("#").lower()
    if not _ORDER_REF.match(ref):
        return None
    ids = (await db.execute(select(Order.id).where(func.lower(Order.id).like(f"{ref}%")).limit(2))).scalars().all()
    return ids[0] if len(ids) == 1 else None


async def _out(db: AsyncSession, msg: ContactMessage) -> dict:
    out = ContactOut.model_validate(msg).model_dump()
    out["order_id"] = await _order_id_for(db, msg.order_ref)
    return out


async def _get(db: AsyncSession, message_id: str) -> ContactMessage:
    msg = await db.get(ContactMessage, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return msg


async def _clear_notification(db: AsyncSession, message_id: str) -> None:
    """Once a message is dealt with, its bell notification has done its job."""
    await db.execute(
        update(AdminNotification)
        .where(AdminNotification.kind == "contact_message", AdminNotification.link.like(f"%open={message_id}"),
               AdminNotification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )


def _mark(msg: ContactMessage, status: str, admin) -> None:
    msg.status = status
    if status == "handled":
        msg.handled_at = datetime.now(timezone.utc)
        msg.handled_by = actor_label(admin)
    else:
        msg.handled_at = None
        msg.handled_by = None


@router.get("", response_model=ContactInbox)
async def list_messages(
    status: Literal["new", "handled", "all"] = "all",
    topic: Optional[Topic] = None,
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_active_superuser),
):
    """Contact-page messages, newest first. Counts ignore the status tab but follow the search."""
    filters = []
    if topic:
        filters.append(ContactMessage.topic == topic)
    if q and q.strip():
        term = f"%{q.strip().lstrip('#')}%"
        filters.append(or_(
            ContactMessage.name.ilike(term), ContactMessage.email.ilike(term), ContactMessage.phone.ilike(term),
            ContactMessage.message.ilike(term), ContactMessage.order_ref.ilike(term),
        ))

    query = select(ContactMessage).where(*filters).order_by(ContactMessage.created_at.desc()).limit(limit)
    if status != "all":
        query = query.where(ContactMessage.status == status)
    rows = (await db.execute(query)).scalars().all()

    counts = dict((await db.execute(
        select(ContactMessage.status, func.count(ContactMessage.id)).where(*filters).group_by(ContactMessage.status)
    )).all())
    return {
        "messages": [await _out(db, m) for m in rows],
        "new_count": counts.get("new", 0),
        "handled_count": counts.get("handled", 0),
    }


@router.get("/{message_id}", response_model=ContactOut)
async def get_message(message_id: str, db: AsyncSession = Depends(get_db), admin=Depends(get_current_active_superuser)):
    return await _out(db, await _get(db, message_id))


@router.patch("/{message_id}", response_model=ContactOut)
async def update_message(
    message_id: str,
    body: ContactStatusUpdate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_active_superuser),
):
    msg = await _get(db, message_id)
    _mark(msg, body.status, admin)
    if body.status == "handled":
        await _clear_notification(db, msg.id)
    await db.commit()
    await db.refresh(msg)
    return await _out(db, msg)


@router.post("/{message_id}/reply", response_model=ContactOut)
async def reply_to_message(
    message_id: str,
    body: ContactReplyIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_active_superuser),
):
    """Email a reply to the customer and keep it on the message."""
    msg = await _get(db, message_id)
    store = await get_store_settings(db)
    msg.replies.append(ContactReply(body=body.body, sent_by=actor_label(admin)))
    if body.mark_handled:
        _mark(msg, "handled", admin)
    await _clear_notification(db, msg.id)
    await db.commit()
    await db.refresh(msg)
    background_tasks.add_task(send_contact_reply_email, msg.email, msg.name, body.body, msg.message, store.store_name)
    await log_activity(db, admin, "message.replied", "message", f"Replied to {msg.name}'s message",
                       entity_id=msg.id, entity_label=msg.name)
    return await _out(db, msg)


@router.delete("/{message_id}", status_code=204)
async def delete_message(message_id: str, db: AsyncSession = Depends(get_db), admin=Depends(get_current_active_superuser)):
    """For spam and mistakes. Replies go with it."""
    msg = await _get(db, message_id)
    name = msg.name
    await _clear_notification(db, msg.id)
    await db.delete(msg)
    await db.commit()
    await log_activity(db, admin, "message.deleted", "message", f"Deleted a message from {name}", entity_label=name)
    return Response(status_code=204)
