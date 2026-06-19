#!/usr/bin/env python3
"""
Cronoi LS — Şifre Sıfırlama CLI
Kullanım:
    cd backend
    .\venv\Scripts\python.exe reset_password.py --email "kullanici@firma.com" --password "YeniSifre123!"
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, update

from app.core.config import settings
from app.core.auth import hash_password
from app.models import User


async def reset(email: str, new_password: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        result = await db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()

        if not user:
            print(f"HATA: '{email}' e-postasıyla kullanıcı bulunamadı.")
            sys.exit(1)

        user.password_hash = hash_password(new_password)
        await db.commit()

        print(f"✓ Şifre güncellendi")
        print(f"  Kullanıcı : {user.full_name} ({user.email})")
        print(f"  Rol       : {user.role}")
        print(f"  Aktif     : {user.is_active}")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Kullanıcı şifresini sıfırla")
    parser.add_argument("--email",    required=True,  help="Kullanıcı e-postası")
    parser.add_argument("--password", required=True,  help="Yeni şifre")
    args = parser.parse_args()

    if len(args.password) < 4:
        print("HATA: Şifre en az 4 karakter olmalı.")
        sys.exit(1)

    asyncio.run(reset(args.email, args.password))


if __name__ == "__main__":
    main()
