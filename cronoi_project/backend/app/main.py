"""
Cronoi LS — FastAPI Backend v2.0
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import shipments, constraints, orders, scenarios, transport_units, vehicle_plans

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Cronoi LS API başlatılıyor...")
    await init_db()
    print("✅ Veritabanı hazır")
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
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",  # tüm localhost portları
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shipments.router,       prefix="/api/v1/shipments",       tags=["Shipments"])
app.include_router(orders.router,          prefix="/api/v1/orders",          tags=["Orders"])
app.include_router(scenarios.router,       prefix="/api/v1/scenarios",       tags=["Scenarios"])
app.include_router(constraints.router,     prefix="/api/v1/constraints",     tags=["Constraints"])
app.include_router(transport_units.router, prefix="/api/v1/transport-units", tags=["Transport Units"])
app.include_router(vehicle_plans.router,  prefix="/api/v1/vehicle-plans",  tags=["Vehicle Plans"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


# ── Frontend Serving ──────────────────────────────────
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

@app.get("/")
async def serve_frontend():
    return FileResponse(FRONTEND_DIR / "Cronoi_LS_v2.html", media_type="text/html")
