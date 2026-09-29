from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.faq import FaqAdminList, FaqOut, FaqUpdate
from app.services.activity_service import log_activity
from app.services.faq_service import list_admin, replace_faqs
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=FaqAdminList)
async def get_faqs(db: AsyncSession = Depends(get_db), admin=Depends(get_current_active_superuser)):
    """Every question, hidden ones included. The defaults until the store saves its own."""
    return await list_admin(db)


@router.put("", response_model=list[FaqOut])
async def put_faqs(body: FaqUpdate, db: AsyncSession = Depends(get_db), admin=Depends(get_current_active_superuser)):
    """Replace the whole list, in display order."""
    items = await replace_faqs(db, body.items)
    shown = sum(1 for f in items if f.is_published)
    await log_activity(db, admin, "settings.faqs_updated", "settings",
                       f"Updated the FAQ page ({shown} of {len(items)} questions shown)",
                       entity_label="FAQ page")
    return items
