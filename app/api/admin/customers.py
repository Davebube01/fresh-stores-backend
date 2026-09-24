from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.crud.customer import get_admin_customers, get_admin_customer_by_id
from app.schemas.customer import CustomerResponse, CustomerDetailResponse
from app.utils.dependencies import get_current_active_superuser
from typing import List

router = APIRouter()

@router.get("", response_model=List[CustomerResponse])
async def list_admin_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """
    List non-superuser customers with stats, paginated.
    """
    return await get_admin_customers(db, skip=skip, limit=limit)

@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_admin_customer_profile(
    customer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """
    Get a specific customer's profile and order history.
    """
    customer = await get_admin_customer_by_id(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer
