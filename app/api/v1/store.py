from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.settings import PublicStoreInfo
from app.services.settings_service import get_store_settings

router = APIRouter()


@router.get("", response_model=PublicStoreInfo)
async def read_store_info(db: AsyncSession = Depends(get_db)):
    """Public: the store's contact and pickup details, as set in admin Settings."""
    return PublicStoreInfo.model_validate(await get_store_settings(db), from_attributes=True)
