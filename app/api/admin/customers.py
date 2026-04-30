from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.crud.customer import get_admin_customers, get_admin_customer_by_id
from app.schemas.customer import CustomerResponse, CustomerDetailResponse
from app.utils.dependencies import get_current_active_superuser
from typing import List

router = APIRouter()

@router.get("", response_model=List[CustomerResponse])
async def list_admin_customers(
    db: AsyncSession = Depends(get_db),
    # current_user = Depends(get_current_active_superuser)
):
    """
    List all non-superuser customers with stats.
    """
    return await get_admin_customers(db)

@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_admin_customer_profile(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    # current_user = Depends(get_current_active_superuser)
):
    """
    Get a specific customer's profile and order history.
    """
    customer = await get_admin_customer_by_id(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
