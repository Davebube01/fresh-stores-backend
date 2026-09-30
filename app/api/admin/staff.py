from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import ROLE_LABELS
from app.schemas.staff import PasswordReset, StaffCreate, StaffList, StaffMember, StaffUpdate
from app.services.activity_service import log_activity
from app.services.staff_service import (
    StaffError, create_staff, list_staff, reset_staff_password, sign_out_staff, update_staff,
)
from app.utils.dependencies import get_current_active_superuser

router = APIRouter()


@router.get("", response_model=StaffList)
async def get_staff(db: AsyncSession = Depends(get_db), current_admin=Depends(get_current_active_superuser)):
    """Staff accounts, the roles, and what each permission allows."""
    return await list_staff(db)


@router.post("", response_model=StaffMember, status_code=201)
async def add_staff(
    data: StaffCreate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    try:
        member = await create_staff(db, data)
    except StaffError as e:
        raise HTTPException(status_code=409, detail=str(e))
    name = member["full_name"] or member["email"]
    await log_activity(db, current_admin, "staff.added", "staff", f"Added {name} as {ROLE_LABELS[data.role].lower()}",
                       entity_id=member["id"], entity_label=name)
    return member


@router.put("/{staff_id}", response_model=StaffMember)
async def edit_staff(
    staff_id: str,
    data: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    try:
        result = await update_staff(db, staff_id, data, acting=current_admin)
    except StaffError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    member, changes = result
    if changes:
        name = member["full_name"] or member["email"]
        parts = []
        if "role" in changes:
            parts.append(f"role {changes['role']['from']} → {changes['role']['to']}")
        if "is_active" in changes:
            parts.append("reactivated" if changes["is_active"]["to"] else "deactivated")
        parts += [k.replace("_", " ") for k in changes if k in ("full_name", "phone")]
        await log_activity(db, current_admin, "staff.updated", "staff", f"Updated {name}: {', '.join(parts)}",
                           entity_id=member["id"], entity_label=name, changes=changes)
    return member


@router.post("/{staff_id}/reset-password", status_code=204)
async def reset_password(
    staff_id: str,
    data: PasswordReset,
    db: AsyncSession = Depends(get_db),
    current_admin=Depends(get_current_active_superuser),
):
    """Set a new password for a staff member (e.g. they forgot theirs) and sign them out everywhere."""
    user = await reset_staff_password(db, staff_id, data.password)
    if user is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    name = user.full_name or user.email
    await log_activity(db, current_admin, "staff.password_reset", "staff", f"Reset the password for {name}",
                       entity_id=user.id, entity_label=name)


@router.post("/{staff_id}/sign-out", status_code=204)
async def sign_out(staff_id: str, db: AsyncSession = Depends(get_db), current_admin=Depends(get_current_active_superuser)):
    """Sign a staff member out of every device (they can sign straight back in with their password)."""
    if staff_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Use Sign out to end your own session")
    user = await sign_out_staff(db, staff_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    name = user.full_name or user.email
    await log_activity(db, current_admin, "staff.signed_out", "staff", f"Signed {name} out of every device",
                       entity_id=user.id, entity_label=name)
