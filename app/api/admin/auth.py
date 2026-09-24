from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import burn_password_check, verify_password
from app.core.throttle import enforce_login_allowed, record_login_failure, record_login_success
from app.crud.user import get_user_by_email
from app.schemas.user import AuthResponse, Token, UserLogin, UserResponse
from app.services.auth_service import (
    ADMIN,
    clear_refresh_cookie,
    end_session,
    no_session_response,
    refresh_session,
    start_session,
)
from app.utils.dependencies import get_current_active_superuser

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
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit("60/minute")
async def admin_refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    result = await refresh_session(db, request, response, ADMIN)
    if result is None:
        return no_session_response(ADMIN)
    access_token, user = result
    return AuthResponse(access_token=access_token, token_type="bearer", user=user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(request: Request, db: AsyncSession = Depends(get_db)):
    await end_session(db, request, ADMIN)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, ADMIN)
    return response


@router.get("/me", response_model=UserResponse)
async def get_admin_me(current_admin = Depends(get_current_active_superuser)):
    return current_admin
