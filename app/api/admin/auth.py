from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.crud.user import get_user_by_email
from app.schemas.user import UserLogin, Token, UserResponse
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()

@router.post("/login", response_model=Token)
async def admin_login(
    user_in: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    user = await get_user_by_email(db, email=user_in.email)
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough privileges",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token = create_access_token(subject=user.email)
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
async def get_admin_me(current_admin = Depends(get_current_active_superuser)):
    return current_admin
