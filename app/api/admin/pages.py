from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.legal import LegalPageAdmin, LegalPageUpdate, LegalSlug
from app.services.activity_service import actor_label, log_activity
from app.services.legal_service import TITLES, get_admin_page, save_page
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("/{slug}", response_model=LegalPageAdmin)
async def get_legal_page(slug: LegalSlug, db: AsyncSession = Depends(get_db), admin=Depends(get_current_active_superuser)):
    """The page's text with its {placeholders}, plus the default to reset to."""
    return await get_admin_page(db, slug)


@router.put("/{slug}", response_model=LegalPageAdmin)
async def put_legal_page(
    slug: LegalSlug,
    body: LegalPageUpdate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_active_superuser),
):
    page = await save_page(db, slug, body.body, actor_label(admin))
    what = "Reset to the default text" if page["is_default"] else "Updated"
    await log_activity(db, admin, "settings.legal_updated", "settings",
                       f"{what}: {TITLES[slug]}", entity_label=TITLES[slug])
    return page
