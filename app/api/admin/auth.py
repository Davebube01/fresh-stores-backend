from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import burn_password_check, verify_password
from app.core.throttle import enforce_login_allowed, record_login_failure, record_login_success
from app.crud.user import get_user_by_email
from app.schemas.staff import AdminAuthResponse, AdminUserResponse, PasswordChange
from app.schemas.user import Token, UserLogin
from app.services.auth_service import (
    ADMIN,
    clear_refresh_cookie,
    end_session,
    no_session_response,
    refresh_session,
    start_session,
)
from app.utils.dependencies import get_current_active_superuser

from app.services.activity_service import log_activity
from app.services.staff_service import change_own_password

router = APIRouter()

# The admin session is deliberately separate from the customer one: its own
# login, its own "admin"-scope token, its own cookie, and a fixed working-day
# lifetime with no "keep me signed in".

@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def admin_login(
    request: Request,
    response: Response,
    user_in: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    email = user_in.email
    enforce_login_allowed(request, ADMIN.name, email)

    user = await get_user_by_email(db, email=email)
    if user is None:
        burn_password_check(user_in.password)
    # Same message for "no such account", "wrong password" and "not an admin",
    # so this endpoint can't be used to discover which emails are staff.
    if user is None or not verify_password(user_in.password, user.hashed_password) or not user.is_superuser:
        record_login_failure(request, ADMIN.name, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    record_login_success(request, ADMIN.name, email)
    access_token = await start_session(db, request, response, user, ADMIN, remember=False)
    await log_activity(db, user, "admin.signed_in", "admin", "Signed in to the admin",
                       entity_id=user.id, entity_label=user.full_name or user.email)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=AdminAuthResponse)
@limiter.limit("60/minute")
async def admin_refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    result = await refresh_session(db, request, response, ADMIN)
    if result is None:
        return no_session_response(ADMIN)
    access_token, user = result
    return AdminAuthResponse(access_token=access_token, token_type="bearer", user=AdminUserResponse.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(request: Request, db: AsyncSession = Depends(get_db)):
    await end_session(db, request, ADMIN)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, ADMIN)
    return response


@router.get("/me", response_model=AdminUserResponse)
async def get_admin_me(current_admin = Depends(get_current_active_superuser)):
    return current_admin


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/hour")
async def change_admin_password(
    request: Request,
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_admin = Depends(get_current_active_superuser),
):
    """Any staff member can change their own password (e.g. the one the owner gave them)."""
    if not verify_password(data.current_password, current_admin.hashed_password):
        raise HTTPException(status_code=400, detail="Your current password is incorrect")
    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="Choose a password different from your current one")
    await change_own_password(db, current_admin, data.new_password)
    await log_activity(db, current_admin, "staff.password_changed", "staff", "Changed their own password",
                       entity_id=current_admin.id, entity_label=current_admin.full_name or current_admin.email)
