"""
Cronoi LS — Taşıma Birimleri API (Palet Tipleri + Araç Tipleri)
Dinamik kütüphane yönetimi: CRUD, aktif/pasif, seed data
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.database import get_db
from app.models import PalletDefinition, VehicleDefinition, Company

router = APIRouter()

DEMO_COMPANY_ID = "00000000-0000-0000-0000-000000000001"

# ════════════════════════════════════════════════════════════════
# SEED DATA — Gerçek lojistik değerleri
# ════════════════════════════════════════════════════════════════

SEED_PALLETS = [
    {"code": "P1", "name": "P1 – Euro Standart", "icon": "🟦", "length_cm": 120, "width_cm": 80,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 1},
    {"code": "P2", "name": "P2 – Özel Boy (80×170)", "icon": "📦", "length_cm": 170, "width_cm": 80,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 2},
    {"code": "P3", "name": "P3 – Özel Boy (80×200)", "icon": "📦", "length_cm": 200, "width_cm": 80,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 3},
    {"code": "P4", "name": "P4 – Özel Boy (80×230)", "icon": "📦", "length_cm": 230, "width_cm": 80,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 4},
    {"code": "P5", "name": "P5 – Standart Geniş", "icon": "🟫", "length_cm": 120, "width_cm": 100,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 5},
    {"code": "P6", "name": "P6 – Özel Boy (100×170)", "icon": "📦", "length_cm": 170, "width_cm": 100,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 6},
    {"code": "P7", "name": "P7 – Özel Boy (100×200)", "icon": "📦", "length_cm": 200, "width_cm": 100,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 7},
    {"code": "P8", "name": "P8 – Özel Boy Uzun (100×250)", "icon": "📦", "length_cm": 250, "width_cm": 100,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 8},
    {"code": "P9", "name": "P9 – Kareye Yakın (120×130)", "icon": "🔲", "length_cm": 130, "width_cm": 120,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 9},
    {"code": "P10", "name": "P10 – Büyük Boy (120×200)", "icon": "🟪", "length_cm": 200, "width_cm": 120,
     "max_height_cm": 250, "max_weight_kg": 700, "tare_weight_kg": 25, "sort_order": 10},
]

SEED_VEHICLES = [
    {"code": "panelvan", "name": "Panelvan", "type": "panelvan", "icon": "🚐",
     "length_cm": 350, "width_cm": 180, "height_cm": 180, "max_weight_kg": 1500,
     "usable_volume_m3": 9.0,
     "pallet_capacity": 2, "base_cost": 2000, "fuel_per_km": 1.5,
     "driver_per_hour": 100, "opportunity_cost": 500, "sort_order": 1},
    {"code": "kamyonet", "name": "Kamyonet", "type": "kamyonet", "icon": "🛻",
     "length_cm": 450, "width_cm": 210, "height_cm": 210, "max_weight_kg": 3500,
     "usable_volume_m3": 16.5,
     "pallet_capacity": 4, "base_cost": 3000, "fuel_per_km": 2.0,
     "driver_per_hour": 120, "opportunity_cost": 800, "sort_order": 2},
    {"code": "kamyon_mid", "name": "Kamyon (Orta)", "type": "kamyon", "icon": "🚚",
     "length_cm": 700, "width_cm": 240, "height_cm": 240, "max_weight_kg": 8000,
     "usable_volume_m3": 34.0,
     "pallet_capacity": 12, "base_cost": 5000, "fuel_per_km": 3.5,
     "driver_per_hour": 150, "opportunity_cost": 1500, "sort_order": 3},
    {"code": "kamyon_buyuk", "name": "Kamyon (Büyük)", "type": "kamyon", "icon": "🚚",
     "length_cm": 960, "width_cm": 245, "height_cm": 250, "max_weight_kg": 14000,
     "usable_volume_m3": 50.0,
     "pallet_capacity": 18, "base_cost": 6500, "fuel_per_km": 4.5,
     "driver_per_hour": 170, "opportunity_cost": 2000, "sort_order": 4},
    {"code": "tir_standart", "name": "TIR (13.6m Standart)", "type": "tir", "icon": "🚛",
     "length_cm": 1360, "width_cm": 245, "height_cm": 270, "max_weight_kg": 24000,
     "usable_volume_m3": 82.0,
     "pallet_capacity": 33, "base_cost": 8000, "fuel_per_km": 5.5,
     "driver_per_hour": 200, "opportunity_cost": 2500, "sort_order": 5},
    {"code": "tir_mega", "name": "TIR Mega (3m Yüksek)", "type": "tir", "icon": "🚛",
     "length_cm": 1360, "width_cm": 245, "height_cm": 300, "max_weight_kg": 24000,
     "usable_volume_m3": 92.0,
     "pallet_capacity": 33, "base_cost": 9000, "fuel_per_km": 5.8,
     "driver_per_hour": 200, "opportunity_cost": 2800, "sort_order": 6},
    {"code": "konteyner20", "name": "Konteyner 20ft", "type": "konteyner", "icon": "📦",
     "length_cm": 589, "width_cm": 235, "height_cm": 239, "max_weight_kg": 21600,
     "usable_volume_m3": 28.0,
     "pallet_capacity": 10, "base_cost": 12000, "fuel_per_km": 4.0,
     "driver_per_hour": 180, "opportunity_cost": 3000, "sort_order": 7},
    {"code": "konteyner40", "name": "Konteyner 40ft", "type": "konteyner", "icon": "📦",
     "length_cm": 1203, "width_cm": 235, "height_cm": 239, "max_weight_kg": 26500,
     "usable_volume_m3": 56.0,
     "pallet_capacity": 21, "base_cost": 18000, "fuel_per_km": 6.0,
     "driver_per_hour": 200, "opportunity_cost": 4000, "sort_order": 8},
    {"code": "konteyner40hc", "name": "Konteyner 40ft HC", "type": "konteyner", "icon": "📦",
     "length_cm": 1203, "width_cm": 235, "height_cm": 269, "max_weight_kg": 26300,
     "usable_volume_m3": 66.0,
     "pallet_capacity": 21, "base_cost": 20000, "fuel_per_km": 6.2,
     "driver_per_hour": 200, "opportunity_cost": 4500, "sort_order": 9},
]


# ════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ════════════════════════════════════════════════════════════════

class PalletDefOut(BaseModel):
    id: str
    code: str
    name: str
    icon: str
    length_cm: float
    width_cm: float
    max_height_cm: float
    max_weight_kg: float
    usable_area_m2: Optional[float]
    tare_weight_kg: float
    is_system_default: bool
    is_active: bool
    sort_order: int
    notes: Optional[str]

class PalletDefCreate(BaseModel):
    code: str = Field(..., max_length=30)
    name: str = Field(..., max_length=100)
    icon: str = Field(default="📦", max_length=10)
    length_cm: float = Field(..., gt=0)
    width_cm: float = Field(..., gt=0)
    max_height_cm: float = Field(default=180, gt=0)
    max_weight_kg: float = Field(..., gt=0)
    tare_weight_kg: float = Field(default=25, ge=0)
    notes: Optional[str] = None

class PalletDefUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    max_height_cm: Optional[float] = None
    max_weight_kg: Optional[float] = None
    tare_weight_kg: Optional[float] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None

class VehicleDefOut(BaseModel):
    id: str
    code: str
    name: str
    type: str
    icon: str
    length_cm: float
    width_cm: float
    height_cm: float
    max_weight_kg: float
    usable_volume_m3: Optional[float] = None
    pallet_capacity: int
    base_cost: float
    fuel_per_km: float
    driver_per_hour: float
    opportunity_cost: float
    is_system_default: bool
    is_active: bool
    sort_order: int
    notes: Optional[str]

class VehicleDefCreate(BaseModel):
    code: str = Field(..., max_length=30)
    name: str = Field(..., max_length=100)
    type: str = Field(..., max_length=30)
    icon: str = Field(default="🚛", max_length=10)
    length_cm: float = Field(..., gt=0)
    width_cm: float = Field(..., gt=0)
    height_cm: float = Field(..., gt=0)
    max_weight_kg: float = Field(..., gt=0)
    usable_volume_m3: Optional[float] = Field(default=None, ge=0)
    pallet_capacity: int = Field(default=0, ge=0)
    base_cost: float = Field(default=0, ge=0)
    fuel_per_km: float = Field(default=0, ge=0)
    driver_per_hour: float = Field(default=0, ge=0)
    opportunity_cost: float = Field(default=0, ge=0)
    notes: Optional[str] = None

class VehicleDefUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    type: Optional[str] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    max_weight_kg: Optional[float] = None
    usable_volume_m3: Optional[float] = None
    pallet_capacity: Optional[int] = None
    base_cost: Optional[float] = None
    fuel_per_km: Optional[float] = None
    driver_per_hour: Optional[float] = None
    opportunity_cost: Optional[float] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    notes: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# SEED ENDPOINT — Auto-populate on first call
# ════════════════════════════════════════════════════════════════

@router.post("/seed", summary="Seed default pallet & vehicle definitions")
async def seed_defaults(db: AsyncSession = Depends(get_db)):
    """Boş firmaya varsayılan palet ve araç tipleri ekler."""
    company_id = DEMO_COMPANY_ID

    # Company yoksa oluştur
    company = await db.get(Company, company_id)
    if not company:
        company = Company(id=company_id, name="Demo Şirket", slug="demo", plan="growth", monthly_quota=999)
        db.add(company)
        await db.flush()

    # Palet seed
    existing_pallets = (await db.execute(
        select(PalletDefinition).where(PalletDefinition.company_id == company_id)
    )).scalars().all()
    existing_pallet_codes = {p.code for p in existing_pallets}

    pallet_count = 0
    for seed in SEED_PALLETS:
        if seed["code"] not in existing_pallet_codes:
            pd = PalletDefinition(
                company_id=company_id,
                is_system_default=True,
                usable_area_m2=round(seed["length_cm"] * seed["width_cm"] / 10000, 3),
                **seed
            )
            db.add(pd)
            pallet_count += 1

    # Araç seed
    existing_vehicles = (await db.execute(
        select(VehicleDefinition).where(VehicleDefinition.company_id == company_id)
    )).scalars().all()
    existing_vehicle_codes = {v.code for v in existing_vehicles}

    vehicle_count = 0
    for seed in SEED_VEHICLES:
        if seed["code"] not in existing_vehicle_codes:
            vd = VehicleDefinition(
                company_id=company_id,
                is_system_default=True,
                **seed
            )
            db.add(vd)
            vehicle_count += 1

    await db.commit()
    return {
        "message": f"{pallet_count} palet, {vehicle_count} araç tipi eklendi",
        "pallets_added": pallet_count,
        "vehicles_added": vehicle_count
    }


# ════════════════════════════════════════════════════════════════
# PALLET DEFINITIONS CRUD
# ════════════════════════════════════════════════════════════════

@router.get("/pallets", response_model=List[PalletDefOut])
async def list_pallet_definitions(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    q = select(PalletDefinition).where(
        PalletDefinition.company_id == DEMO_COMPANY_ID
    ).order_by(PalletDefinition.sort_order, PalletDefinition.name)
    if active_only:
        q = q.where(PalletDefinition.is_active == True)
    rows = (await db.execute(q)).scalars().all()
    return rows


@router.post("/pallets", response_model=PalletDefOut, status_code=201)
async def create_pallet_definition(
    body: PalletDefCreate,
    db: AsyncSession = Depends(get_db)
):
    # Code uniqueness
    existing = (await db.execute(
        select(PalletDefinition).where(
            PalletDefinition.company_id == DEMO_COMPANY_ID,
            PalletDefinition.code == body.code
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"'{body.code}' kodu zaten mevcut")

    pd = PalletDefinition(
        company_id=DEMO_COMPANY_ID,
        usable_area_m2=round(body.length_cm * body.width_cm / 10000, 3),
        **body.model_dump()
    )
    db.add(pd)
    await db.commit()
    await db.refresh(pd)
    return pd


@router.patch("/pallets/{pallet_def_id}", response_model=PalletDefOut)
async def update_pallet_definition(
    pallet_def_id: str,
    body: PalletDefUpdate,
    db: AsyncSession = Depends(get_db)
):
    pd = await db.get(PalletDefinition, pallet_def_id)
    if not pd or pd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Palet tipi bulunamadı")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(pd, k, v)

    # Recalculate area if dimensions changed
    if "length_cm" in data or "width_cm" in data:
        pd.usable_area_m2 = round(pd.length_cm * pd.width_cm / 10000, 3)

    await db.commit()
    await db.refresh(pd)
    return pd


@router.delete("/pallets/{pallet_def_id}")
async def delete_pallet_definition(
    pallet_def_id: str,
    db: AsyncSession = Depends(get_db)
):
    pd = await db.get(PalletDefinition, pallet_def_id)
    if not pd or pd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Palet tipi bulunamadı")
    if pd.is_system_default:
        raise HTTPException(400, "Sistem varsayılan palet tipi silinemez. Pasife alabilirsiniz.")
    await db.delete(pd)
    await db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════
# VEHICLE DEFINITIONS CRUD
# ════════════════════════════════════════════════════════════════

@router.get("/vehicles", response_model=List[VehicleDefOut])
async def list_vehicle_definitions(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    q = select(VehicleDefinition).where(
        VehicleDefinition.company_id == DEMO_COMPANY_ID
    ).order_by(VehicleDefinition.sort_order, VehicleDefinition.name)
    if active_only:
        q = q.where(VehicleDefinition.is_active == True)
    rows = (await db.execute(q)).scalars().all()
    return rows


@router.post("/vehicles", response_model=VehicleDefOut, status_code=201)
async def create_vehicle_definition(
    body: VehicleDefCreate,
    db: AsyncSession = Depends(get_db)
):
    existing = (await db.execute(
        select(VehicleDefinition).where(
            VehicleDefinition.company_id == DEMO_COMPANY_ID,
            VehicleDefinition.code == body.code
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, f"'{body.code}' kodu zaten mevcut")

    vd = VehicleDefinition(
        company_id=DEMO_COMPANY_ID,
        **body.model_dump()
    )
    db.add(vd)
    await db.commit()
    await db.refresh(vd)
    return vd


@router.patch("/vehicles/{vehicle_def_id}", response_model=VehicleDefOut)
async def update_vehicle_definition(
    vehicle_def_id: str,
    body: VehicleDefUpdate,
    db: AsyncSession = Depends(get_db)
):
    vd = await db.get(VehicleDefinition, vehicle_def_id)
    if not vd or vd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Araç tipi bulunamadı")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(vd, k, v)

    await db.commit()
    await db.refresh(vd)
    return vd


@router.delete("/vehicles/{vehicle_def_id}")
async def delete_vehicle_definition(
    vehicle_def_id: str,
    db: AsyncSession = Depends(get_db)
):
    vd = await db.get(VehicleDefinition, vehicle_def_id)
    if not vd or vd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Araç tipi bulunamadı")
    if vd.is_system_default:
        raise HTTPException(400, "Sistem varsayılan araç tipi silinemez. Pasife alabilirsiniz.")
    await db.delete(vd)
    await db.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════
# TOGGLE ACTIVE/PASSIVE
# ════════════════════════════════════════════════════════════════

@router.patch("/pallets/{pallet_def_id}/toggle")
async def toggle_pallet_active(pallet_def_id: str, db: AsyncSession = Depends(get_db)):
    pd = await db.get(PalletDefinition, pallet_def_id)
    if not pd or pd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Palet tipi bulunamadı")
    pd.is_active = not pd.is_active
    await db.commit()
    return {"id": pd.id, "is_active": pd.is_active}


@router.patch("/vehicles/{vehicle_def_id}/toggle")
async def toggle_vehicle_active(vehicle_def_id: str, db: AsyncSession = Depends(get_db)):
    vd = await db.get(VehicleDefinition, vehicle_def_id)
    if not vd or vd.company_id != DEMO_COMPANY_ID:
        raise HTTPException(404, "Araç tipi bulunamadı")
    vd.is_active = not vd.is_active
    await db.commit()
    return {"id": vd.id, "is_active": vd.is_active}
