from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.push import PushSubscribeRequest, PushUnsubscribeRequest, VapidPublicKeyResponse
from app.services import push_service
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("/public-key", response_model=VapidPublicKeyResponse)
async def get_public_key(current_admin: User = Depends(get_current_active_superuser)):
    """The frontend passes this to PushManager.subscribe(); null means push isn't set up yet."""
    return VapidPublicKeyResponse(public_key=settings.VAPID_PUBLIC_KEY)


@router.post("/subscribe", status_code=204)
async def push_subscribe(
    body: PushSubscribeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_active_superuser),
):
    await push_service.subscribe(db, current_admin.id, body, request.headers.get("user-agent"))


@router.post("/unsubscribe", status_code=204)
async def push_unsubscribe(
    body: PushUnsubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_active_superuser),
):
    await push_service.unsubscribe(db, current_admin.id, body.endpoint)
