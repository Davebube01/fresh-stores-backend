from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False
)


async def _user_from_token(db: AsyncSession, token: str, scope: str) -> User | None:
    """Resolves an access token to its user, or None if it's invalid, expired, or for the other audience."""
    try:
        payload = decode_access_token(token)
    except JWTError:
        return None
    if payload.get("type") != "access" or payload.get("scope") != scope:
        return None
    email = payload.get("sub")
    if not email:
        return None
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await _user_from_token(db, token, "customer")
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_optional_current_user(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User | None:
    if not token:
        return None
    return await _user_from_token(db, token, "customer")


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_active_superuser(
    db: AsyncSession = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    Admin API guard. Requires an "admin"-scope token — which only the
    separate admin login issues — so a customer-scope token, even one belonging
    to a superuser account, is refused here.
    """
    user = await _user_from_token(db, token, "admin") if token else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="The user doesn't have enough privileges")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user
