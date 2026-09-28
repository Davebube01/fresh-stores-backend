from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.pagination import MAX_PAGE_SIZE
from app.crud.customer import (
    CustomerSort, get_admin_customer_by_id, get_admin_customers, get_customers_summary, set_customer_active,
)
from app.schemas.customer import (
    CustomerDetailResponse, CustomerResponse, CustomersSummary, CustomerStatusUpdate,
)
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=List[CustomerResponse])
async def list_admin_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    search: Optional[str] = Query(None, max_length=100),
    status: Optional[Literal["active", "inactive"]] = None,
    sort: CustomerSort = "recent",
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """
    List non-superuser customers with stats, paginated. Search matches name,
    email or phone.
    """
    return await get_admin_customers(db, skip=skip, limit=limit, search=search, status=status, sort=sort)


@router.get("/summary", response_model=CustomersSummary)
async def admin_customers_summary(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """Headline numbers for the Customers page."""
    return await get_customers_summary(db)


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


@router.patch("/{customer_id}/status", response_model=CustomerDetailResponse)
async def update_admin_customer_status(
    customer_id: str,
    body: CustomerStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_active_superuser)
):
    """Deactivate (blocks sign-in, ends their sessions) or reactivate a customer."""
    user = await set_customer_active(db, customer_id, body.is_active)
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")
    return await get_admin_customer_by_id(db, customer_id)
