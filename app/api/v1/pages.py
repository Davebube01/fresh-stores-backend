from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.legal import LegalPageOut, LegalSlug
from app.services.legal_service import get_public_page

router = APIRouter()


@router.get("/{slug}", response_model=LegalPageOut)
async def read_legal_page(slug: LegalSlug, db: AsyncSession = Depends(get_db)):
    """Public: the Terms or Privacy page, with the store's details filled in."""
    return await get_public_page(db, slug)
