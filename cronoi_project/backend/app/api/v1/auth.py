"""
Cronoi LS — Auth API
POST /api/v1/auth/login   → Email + şifre ile giriş → access_token + refresh_token
POST /api/v1/auth/refresh → Refresh token ile yeni access_token
POST /api/v1/auth/logout  → Refresh token'ı geçersiz kıl
GET  /api/v1/auth/me      → Mevcut kullanıcı + firma bilgisi
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_active_user,
)
from app.core.config import settings
from app.models import User, Company, RefreshToken

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user: dict
    company: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"


class LogoutRequest(BaseModel):
    refresh_token: str


# ── Helpers ──────────────────────────────────────────────────

def _hash_token(raw: str) -> str:
    """SHA-256 hash of a raw token string (for DB storage)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _build_user_dict(user: User) -> dict:
    return {
        "id":              str(user.id),
        "email":           user.email,
        "full_name":       user.full_name,
        "role":            user.role,
        "is_system_admin": user.is_system_admin,
        "company_id":      str(user.company_id),
        "last_login_at":   user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _build_company_dict(company: Company) -> dict:
    return {
        "id":              str(company.id),
        "name":            company.name,
        "slug":            company.slug,
        "plan":            company.plan,
        "user_seats":      company.user_seats,
        "plan_expires_at": company.plan_expires_at.isoformat() if company.plan_expires_at else None,
        "monthly_quota":   company.monthly_quota,
        "used_quota":      company.used_quota,
    }


# ── Endpoints ────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Email ve şifre ile giriş yap."""
    # Kullanıcıyı email ile bul
    result = await db.execute(
        select(User)
        .options(selectinload(User.company))
        .where(User.email == payload.email.lower())
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hesap devre dışı")

    # Abonelik kontrolü
    if user.company and user.company.plan_expires_at:
        if user.company.plan_expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Abonelik süresi doldu. Lütfen planınızı yenileyin.",
            )

    # Access token oluştur
    access_token = create_access_token({
        "sub":             str(user.id),
        "company_id":      str(user.company_id),
        "role":            user.role,
        "is_system_admin": user.is_system_admin,
    })

    # Refresh token oluştur + DB'de sakla
    raw_refresh = secrets.token_urlsafe(48)
    token_hash  = _hash_token(raw_refresh)
    expires_at  = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))

    # Son giriş zamanını güncelle
    user.last_login_at = datetime.now(timezone.utc)

    await db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        user=_build_user_dict(user),
        company=_build_company_dict(user.company) if user.company else {},
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh token ile yeni access token al."""
    token_hash = _hash_token(payload.refresh_token)

    result = await db.execute(
        select(RefreshToken)
        .options(selectinload(RefreshToken.user).selectinload(User.company))
        .where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()

    if not stored:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz refresh token")
    if stored.expires_at < datetime.now(timezone.utc):
        await db.delete(stored)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token süresi doldu")

    user = stored.user
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı veya devre dışı")

    access_token = create_access_token({
        "sub":            user.id,
        "company_id":     user.company_id,
        "role":           user.role,
        "is_system_admin": user.is_system_admin,
    })

    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: AsyncSession = Depends(get_db)):
    """Refresh token'ı geçersiz kıl (DB'den sil)."""
    token_hash = _hash_token(payload.refresh_token)
    await db.execute(delete(RefreshToken).where(RefreshToken.token_hash == token_hash))
    await db.commit()


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_active_user)):
    """Mevcut kullanıcı ve firma bilgisi."""
    return {
        "user":    _build_user_dict(current_user),
        "company": _build_company_dict(current_user.company) if current_user.company else {},
    }


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password:     str = Field(min_length=4)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Giriş yapılıyken şifre değiştir."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mevcut şifre hatalı",
        )
    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()
