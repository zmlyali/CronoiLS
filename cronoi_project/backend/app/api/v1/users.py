"""
Cronoi LS — User Management API
GET    /api/v1/users         → Firma kullanıcılarını listele (owner/admin)
POST   /api/v1/users         → Yeni kullanıcı oluştur (owner/admin, user_seats limitine göre)
PATCH  /api/v1/users/{id}    → Rol / aktiflik güncelle (owner/admin)
DELETE /api/v1/users/{id}    → Hesabı devre dışı bırak (owner)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.auth import hash_password, get_current_active_user
from app.models import User, Company

router = APIRouter()

ALLOWED_ROLES = {"owner", "admin", "operator", "viewer"}


# ── Schemas ──────────────────────────────────────────────────

class UserCreate(BaseModel):
    email:     EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password:  str = Field(min_length=8, max_length=200)
    role:      str = Field(default="operator")


class UserUpdate(BaseModel):
    full_name:  Optional[str] = Field(None, min_length=2, max_length=200)
    role:       Optional[str] = None
    is_active:  Optional[bool] = None


def _user_out(u: User) -> dict:
    return {
        "id":            u.id,
        "email":         u.email,
        "full_name":     u.full_name,
        "role":          u.role,
        "is_active":     u.is_active,
        "is_system_admin": u.is_system_admin,
        "company_id":    u.company_id,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at":    u.created_at.isoformat() if u.created_at else None,
    }


def _require_manager(current_user: User) -> None:
    """Only owner or admin can manage users."""
    if current_user.role not in ("owner", "admin") and not current_user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için owner veya admin yetkisi gereklidir",
        )


def _require_owner(current_user: User) -> None:
    """Only owner can perform destructive actions."""
    if current_user.role != "owner" and not current_user.is_system_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için owner yetkisi gereklidir",
        )


# ── Endpoints ────────────────────────────────────────────────

@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Firma içindeki kullanıcıları listele."""
    _require_manager(current_user)

    result = await db.execute(
        select(User)
        .where(User.company_id == current_user.company_id)
        .order_by(User.created_at)
    )
    users = result.scalars().all()
    return [_user_out(u) for u in users]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Firmaya yeni kullanıcı ekle — user_seats limiti kontrol edilir."""
    _require_manager(current_user)

    if payload.role not in ALLOWED_ROLES:
        raise HTTPException(400, f"Geçersiz rol. İzin verilenler: {', '.join(ALLOWED_ROLES)}")

    # Email benzersizliği
    existing = (await db.execute(
        select(User).where(User.email == payload.email.lower())
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Bu e-posta adresi zaten kullanımda")

    # Koltuk limiti kontrolü
    company = await db.get(Company, current_user.company_id)
    if company:
        active_count = (await db.execute(
            select(func.count()).where(
                User.company_id == current_user.company_id,
                User.is_active == True,  # noqa: E712
            )
        )).scalar_one()
        if active_count >= company.user_seats:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Kullanıcı koltuğu doldu ({company.user_seats} koltuk). "
                       "Planınızı yükseltin veya mevcut bir kullanıcıyı devre dışı bırakın.",
            )

    new_user = User(
        company_id=current_user.company_id,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
        is_system_admin=False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return _user_out(new_user)


@router.patch("/{user_id}")
async def update_user(
    user_id: str,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Kullanıcı rol veya aktifliğini güncelle."""
    _require_manager(current_user)

    user = await db.get(User, user_id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(404, "Kullanıcı bulunamadı")

    # Kendi rolünü değiştiremesin
    if user.id == current_user.id and payload.role and payload.role != current_user.role:
        raise HTTPException(400, "Kendi rolünüzü değiştiremezsiniz")

    # Son owner korunmalı
    if user.role == "owner" and payload.role and payload.role != "owner":
        owner_count = (await db.execute(
            select(func.count()).where(
                User.company_id == current_user.company_id,
                User.role == "owner",
                User.is_active == True,  # noqa: E712
            )
        )).scalar_one()
        if owner_count <= 1:
            raise HTTPException(400, "Firmada en az bir owner kalmalıdır")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        if payload.role not in ALLOWED_ROLES:
            raise HTTPException(400, f"Geçersiz rol: {payload.role}")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await db.commit()
    await db.refresh(user)
    return _user_out(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Kullanıcıyı devre dışı bırak (soft delete — owner only)."""
    _require_owner(current_user)

    if user_id == current_user.id:
        raise HTTPException(400, "Kendi hesabınızı devre dışı bırakamazsınız")

    user = await db.get(User, user_id)
    if not user or user.company_id != current_user.company_id:
        raise HTTPException(404, "Kullanıcı bulunamadı")

    user.is_active = False
    await db.commit()
