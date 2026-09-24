from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import (
    burn_password_check,
    create_email_token,
    decode_email_token,
    verify_password,
)
from app.core.throttle import enforce_login_allowed, hit_limit, record_login_failure, record_login_success
from app.crud.order import claim_guest_orders
from app.crud.user import create_user, get_user_by_email
from app.models.user import User
from app.schemas.user import (
    AuthResponse,
    RegisterRequest,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth_service import (
    CUSTOMER,
    clear_refresh_cookie,
    end_session,
    no_session_response,
    refresh_session,
    start_session,
)
from app.services.email_service import send_verification_email
from app.utils.dependencies import get_current_active_user

router = APIRouter()

# Per-IP ceilings. Generous on purpose: real people share IPs (offices, mobile
# carriers), and per-account lockouts (app/core/throttle.py) are what actually
# stop password guessing.
LOGIN_LIMIT = "30/minute"
REGISTER_LIMIT = "20/hour"
REFRESH_LIMIT = "60/minute"
VERIFY_LIMIT = "20/hour"


def _queue_verification_email(background_tasks: BackgroundTasks, user: User) -> None:
    token = create_email_token(user.email, "verify_email", settings.VERIFY_EMAIL_HOURS)
    url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    background_tasks.add_task(send_verification_email, user.email, user.full_name, url)


async def _authenticate(
    request: Request, response: Response, db: AsyncSession, email: str, password: str, remember: bool
) -> dict:
    email = email.strip().lower()
    enforce_login_allowed(request, CUSTOMER.name, email)

    user = await get_user_by_email(db, email=email)
    if user is None:
        burn_password_check(password)
    if user is None or not verify_password(password, user.hashed_password):
        record_login_failure(request, CUSTOMER.name, email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    record_login_success(request, CUSTOMER.name, email)
    access_token = await start_session(db, request, response, user, CUSTOMER, remember)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(REGISTER_LIMIT)
async def register(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    user_in: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    if await get_user_by_email(db, email=user_in.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    try:
        user = await create_user(db, UserCreate(**user_in.model_dump()))
    except IntegrityError:
        # Lost a race with a concurrent sign-up for the same email.
        await db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    _queue_verification_email(background_tasks, user)
    access_token = await start_session(db, request, response, user, CUSTOMER, remember=True)
    await db.refresh(user)
    return AuthResponse(access_token=access_token, token_type="bearer", user=user)


@router.post("/login", response_model=Token)
@limiter.limit(LOGIN_LIMIT)
async def login_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    return await _authenticate(request, response, db, form_data.username, form_data.password, remember=False)


@router.post("/login/json", response_model=Token)
@limiter.limit(LOGIN_LIMIT)
async def login_json(
    request: Request,
    response: Response,
    user_in: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    return await _authenticate(request, response, db, user_in.email, user_in.password, user_in.remember_me)


@router.post("/refresh", response_model=AuthResponse)
@limiter.limit(REFRESH_LIMIT)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Trades the refresh cookie for a new access token (and rotates the cookie)."""
    result = await refresh_session(db, request, response, CUSTOMER)
    if result is None:
        return no_session_response(CUSTOMER)
    access_token, user = result
    return AuthResponse(access_token=access_token, token_type="bearer", user=user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    await end_session(db, request, CUSTOMER)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, CUSTOMER)
    return response


@router.post("/verify-email")
@limiter.limit(VERIFY_LIMIT)
async def verify_email(request: Request, body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """
    Public on purpose: the link is opened from an email, often in a different
    browser than the one signed in. The signed token is the proof.
    """
    invalid = HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    try:
        email = decode_email_token(body.token, "verify_email")
    except (JWTError, ValueError):
        raise invalid

    user = await get_user_by_email(db, email=email)
    if user is None:
        raise invalid

    claimed = 0
    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        await db.commit()
        # Only now is it safe to hand over guest orders placed with this
        # email: we know the person holds the mailbox.
        claimed = await claim_guest_orders(db, user.id, user.email)

    return {"verified": True, "claimed_orders": claimed}


@router.post("/resend-verification")
async def resend_verification(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
):
    if current_user.email_verified:
        return {"already_verified": True}
    if not hit_limit(f"resend-verification:{current_user.id}", limit=3, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again in a while.")
    _queue_verification_email(background_tasks, current_user)
    return {"sent": True}


@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user
