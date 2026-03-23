"""
Cronoi LS — FastAPI Backend v2.0
Python 3.12 | FastAPI | SQLAlchemy 2.0 | PostgreSQL
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import shipments, constraints


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Cronoi LS API başlatılıyor...")
    await init_db()   # Tabloları oluştur (migration yoksa)
    print("✅ Veritabanı bağlantısı hazır")
    yield
    print("👋 Cronoi LS API kapatılıyor...")


app = FastAPI(
    title="Cronoi LS API",
    description="Lojistik Sevkiyat Sistemi — B2B SaaS",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mevcut router'lar
app.include_router(shipments.router,   prefix="/api/v1/shipments",   tags=["Shipments"])
app.include_router(constraints.router, prefix="/api/v1/constraints", tags=["Constraints"])

# TODO Sprint 2: auth, catalog, vehicles, scenarios, loading_plans


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "2.0.0", "mode": "local"}
