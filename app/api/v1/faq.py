from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.faq import FaqOut
from app.services.faq_service import list_public

router = APIRouter()


@router.get("", response_model=list[FaqOut])
async def read_faqs(db: AsyncSession = Depends(get_db)):
    """Public: the FAQ page's published questions, in order."""
    return await list_public(db)
