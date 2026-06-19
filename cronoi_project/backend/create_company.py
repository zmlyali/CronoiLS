#!/usr/bin/env python3
"""
Cronoi LS — Firma Oluşturma CLI
Kullanım:
    python create_company.py \
        --name "ABC Mobilya A.Ş." \
        --slug "abc-mobilya" \
        --plan starter \
        --seats 5 \
        --email admin@abc.com \
        --full-name "Mehmet Yılmaz" \
        --password "GucluSifre123!" \
        [--expires-days 30]

Çıktı: company_id ve user_id yazdırır.
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Project root'u sys.path'e ekle
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from app.core.config import settings
from app.core.auth import hash_password
from app.models import Company, User, Base


async def create_company_and_owner(
    name: str,
    slug: str,
    plan: str,
    seats: int,
    email: str,
    full_name: str,
    password: str,
    expires_days: int,
) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Slug benzersizliği
        existing = (await db.execute(
            select(Company).where(Company.slug == slug)
        )).scalar_one_or_none()
        if existing:
            print(f"HATA: '{slug}' slug'ı zaten kullanımda (company_id: {existing.id})")
            sys.exit(1)

        # Email benzersizliği
        existing_user = (await db.execute(
            select(User).where(User.email == email.lower())
        )).scalar_one_or_none()
        if existing_user:
            print(f"HATA: '{email}' e-postası zaten kayıtlı (user_id: {existing_user.id})")
            sys.exit(1)

        # Abonelik süresi
        plan_expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

        # Şirket oluştur
        company = Company(
            name=name,
            slug=slug,
            plan=plan,
            user_seats=seats,
            monthly_quota=_quota_for_plan(plan),
            plan_expires_at=plan_expires_at,
            settings={},
        )
        db.add(company)
        await db.flush()  # company.id alınır

        # Owner kullanıcı oluştur
        owner = User(
            company_id=company.id,
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            role="owner",
            is_active=True,
            is_system_admin=False,
        )
        db.add(owner)
        await db.commit()
        await db.refresh(company)
        await db.refresh(owner)

        print("\n✅ Firma ve kullanıcı başarıyla oluşturuldu!\n")
        print(f"  Firma Adı   : {company.name}")
        print(f"  company_id  : {company.id}")
        print(f"  Slug        : {company.slug}")
        print(f"  Plan        : {company.plan} ({seats} koltuk)")
        print(f"  Son Kullanım: {plan_expires_at.strftime('%Y-%m-%d')}")
        print()
        print(f"  Kullanıcı   : {owner.full_name} <{owner.email}>")
        print(f"  user_id     : {owner.id}")
        print(f"  Rol         : {owner.role}")
        print()
        print("  Giriş bilgileri müşteriye iletilmeye hazır.")
        print()

    await engine.dispose()


def _quota_for_plan(plan: str) -> int:
    return {"free": 5, "starter": 50, "growth": 200, "enterprise": 9999}.get(plan, 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cronoi LS — Yeni firma ve owner kullanıcı oluştur"
    )
    parser.add_argument("--name",         required=True,  help="Firma tam adı")
    parser.add_argument("--slug",         required=True,  help="URL slug (küçük harf, tire)")
    parser.add_argument("--plan",         default="starter",
                        choices=["free", "starter", "growth", "enterprise"],
                        help="Abonelik planı (varsayılan: starter)")
    parser.add_argument("--seats",        type=int, default=3,  help="Kullanıcı koltuk sayısı")
    parser.add_argument("--email",        required=True,  help="Owner e-posta adresi")
    parser.add_argument("--full-name",    required=True,  dest="full_name", help="Owner adı soyadı")
    parser.add_argument("--password",     required=True,  help="Owner şifresi (min 8 karakter)")
    parser.add_argument("--expires-days", type=int, default=30, dest="expires_days",
                        help="Abonelik süresi (gün, varsayılan: 30)")

    args = parser.parse_args()

    if len(args.password) < 8:
        print("HATA: Şifre en az 8 karakter olmalıdır")
        sys.exit(1)

    asyncio.run(create_company_and_owner(
        name=args.name,
        slug=args.slug,
        plan=args.plan,
        seats=args.seats,
        email=args.email,
        full_name=args.full_name,
        password=args.password,
        expires_days=args.expires_days,
    ))


if __name__ == "__main__":
    main()
