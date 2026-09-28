"""Customer self-service endpoints (signed in)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.schemas.account import AddressIn, AddressOut, PasswordChange, ProfileUpdate
from app.schemas.user import UserResponse
from app.services.account_service import (
    AccountError, add_address, address_out, change_password, delete_address, list_addresses,
    set_default, sign_out_other_sessions, update_address, update_profile,
)
from app.utils.dependencies import get_current_active_user

# /api/v1/account/...
router = APIRouter()
# /api/v1/auth/... : the refresh cookie is only sent to this path, and these
# need it to know which session to keep.
session_router = APIRouter()


@router.patch("/profile", response_model=UserResponse)
async def patch_profile(body: ProfileUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return await update_profile(db, user, body)


@router.get("/addresses", response_model=list[AddressOut])
async def get_addresses(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return [address_out(a) for a in await list_addresses(db, user)]


@router.post("/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
async def post_address(body: AddressIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    try:
        return address_out(await add_address(db, user, body))
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/addresses/{address_id}", response_model=AddressOut)
async def put_address(address_id: str, body: AddressIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    try:
        row = await update_address(db, user, address_id, body)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail="Address not found")
    return address_out(row)


@router.post("/addresses/{address_id}/default", response_model=AddressOut)
async def post_default(address_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    row = await set_default(db, user, address_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Address not found")
    return address_out(row)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_address(address_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    if not await delete_address(db, user, address_id):
        raise HTTPException(status_code=404, detail="Address not found")


@session_router.post("/password")
@limiter.limit("10/hour")
async def post_password(request: Request, body: PasswordChange, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Change password; signs out every other session, keeps this one."""
    try:
        ended = await change_password(db, request, user, body)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "other_sessions_ended": ended}


@session_router.post("/sessions/sign-out-others")
async def post_sign_out_others(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_active_user)):
    return {"ok": True, "other_sessions_ended": await sign_out_other_sessions(db, request, user)}
