"""
Cronoi LS — Shipments API (Gerçek DB implementasyonu)
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
import time

from app.core.database import get_db
from app.models import Shipment, ShipmentProduct, Pallet, PalletProduct, Scenario

router = APIRouter()


# ── Geçici company_id (auth yokken sabit) ──────────────────────
DEMO_COMPANY_ID = "00000000-0000-0000-0000-000000000001"
DEMO_USER_ID    = "00000000-0000-0000-0000-000000000002"

# Optimizasyon durumunu RAM'de tut (Redis olmadığı için)
_opt_status: dict = {}


# ── Schemas ────────────────────────────────────────────────────

class ConstraintInput(BaseModel):
    code: str
    params: dict = {}


class ProductInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., ge=1, le=10000)
    length_cm: float = Field(..., gt=0)
    width_cm: float = Field(..., gt=0)
    height_cm: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    constraints: List[ConstraintInput] = []
    catalog_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Koltuk Takımı",
                "quantity": 5,
                "length_cm": 200,
                "width_cm": 100,
                "height_cm": 80,
                "weight_kg": 85,
                "constraints": []
            }
        }


class ShipmentCreate(BaseModel):
    pallet_type: str = "euro"
    destination: Optional[str] = None
    notes: Optional[str] = None
    loading_date: Optional[str] = None
    delivery_date: Optional[str] = None
    products: List[ProductInput] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "pallet_type": "euro",
                "destination": "İzmir, TR",
                "loading_date": "2026-03-25",
                "products": [
                    {"name": "Koltuk Takımı", "quantity": 10,
                     "length_cm": 200, "width_cm": 100, "height_cm": 80, "weight_kg": 85, "constraints": []},
                    {"name": "Yemek Masası", "quantity": 5,
                     "length_cm": 180, "width_cm": 90, "height_cm": 75, "weight_kg": 45,
                     "constraints": [{"code": "fragile", "params": {}}]}
                ]
            }
        }


class ShipmentSummary(BaseModel):
    id: str
    reference_no: str
    status: str
    pallet_type: str
    destination: Optional[str]
    total_pallets: Optional[int]
    created_at: datetime
    optimized_at: Optional[datetime]

    class Config:
        from_attributes = True


class OptimizationStatus(BaseModel):
    shipment_id: str
    status: str
    progress_pct: int = 0
    message: str = ""
    result_summary: Optional[dict] = None


# ── Yardımcı: reference_no üret ────────────────────────────────

async def _next_reference_no(db: AsyncSession) -> str:
    year = datetime.now().year
    result = await db.execute(
        select(func.count(Shipment.id)).where(
            Shipment.reference_no.like(f"SEV-{year}-%")
        )
    )
    count = result.scalar() or 0
    return f"SEV-{year}-{count + 1:04d}"


# ── Yardımcı: JS bin packing sonucunu DB'ye kaydet ──────────────

async def _save_pallets(db: AsyncSession, shipment_id: str, pallets_data: list):
    for i, p in enumerate(pallets_data):
        pallet = Pallet(
            id=str(uuid4()),
            shipment_id=shipment_id,
            pallet_number=i + 1,
            pallet_type=p.get("type", "euro"),
            total_weight_kg=p.get("totalWeight", 0),
            total_height_cm=p.get("totalHeight", 0),
            total_volume_m3=p.get("totalVolume", 0),
            fill_rate_pct=p.get("fillRate", 0),
            constraints=p.get("constraints", []),
            layout_data=p.get("layout"),
        )
        db.add(pallet)
        await db.flush()

        for pr in p.get("products", []):
            pp = PalletProduct(
                id=str(uuid4()),
                pallet_id=pallet.id,
                name=pr.get("name", ""),
                quantity=pr.get("quantity", 1),
                length_cm=pr.get("length", 0),
                width_cm=pr.get("width", 0),
                height_cm=pr.get("height", 0),
                weight_kg=pr.get("weight", 0),
                constraints=pr.get("constraints", []),
            )
            db.add(pp)


# ── Endpoints ───────────────────────────────────────────────────

@router.post("", response_model=ShipmentSummary, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Yeni sevkiyat oluştur ve ürünleri kaydet."""

    # Şirketi kontrol et / demo için oluştur
    from app.models import Company
    company = await db.get(Company, DEMO_COMPANY_ID)
    if not company:
        company = Company(
            id=DEMO_COMPANY_ID,
            name="Demo Şirketi",
            slug="demo",
            plan="growth",
            monthly_quota=100,
        )
        db.add(company)
        await db.flush()

    ref_no = await _next_reference_no(db)

    shipment = Shipment(
        id=str(uuid4()),
        company_id=DEMO_COMPANY_ID,
        created_by=DEMO_USER_ID,
        reference_no=ref_no,
        status="draft",
        pallet_type=payload.pallet_type,
        destination=payload.destination,
        notes=payload.notes,
    )
    db.add(shipment)
    await db.flush()

    for i, p in enumerate(payload.products):
        sp = ShipmentProduct(
            id=str(uuid4()),
            shipment_id=shipment.id,
            name=p.name,
            quantity=p.quantity,
            length_cm=p.length_cm,
            width_cm=p.width_cm,
            height_cm=p.height_cm,
            weight_kg=p.weight_kg,
            constraints=[c.model_dump() for c in p.constraints],
            sort_order=i,
        )
        db.add(sp)

    await db.commit()
    await db.refresh(shipment)

    return ShipmentSummary(
        id=shipment.id,
        reference_no=shipment.reference_no,
        status=shipment.status,
        pallet_type=shipment.pallet_type,
        destination=shipment.destination,
        total_pallets=None,
        created_at=shipment.created_at,
        optimized_at=None,
    )


@router.get("", response_model=List[ShipmentSummary])
async def list_shipments(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Tüm sevkiyatları listele (en yeni önce)."""
    result = await db.execute(
        select(Shipment)
        .where(
            Shipment.company_id == DEMO_COMPANY_ID,
            Shipment.deleted_at.is_(None),
        )
        .order_by(Shipment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    shipments = result.scalars().all()

    return [
        ShipmentSummary(
            id=s.id,
            reference_no=s.reference_no,
            status=s.status,
            pallet_type=s.pallet_type,
            destination=s.destination,
            total_pallets=None,
            created_at=s.created_at,
            optimized_at=s.optimized_at,
        )
        for s in shipments
    ]


@router.get("/{shipment_id}", response_model=dict)
async def get_shipment(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Sevkiyat detayı — ürünler ve paletlerle birlikte."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment or shipment.deleted_at:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # Ürünleri çek
    prod_result = await db.execute(
        select(ShipmentProduct)
        .where(ShipmentProduct.shipment_id == shipment_id)
        .order_by(ShipmentProduct.sort_order)
    )
    products = prod_result.scalars().all()

    # Paletleri çek
    pallet_result = await db.execute(
        select(Pallet)
        .where(Pallet.shipment_id == shipment_id)
        .order_by(Pallet.pallet_number)
    )
    pallets = pallet_result.scalars().all()

    return {
        "id":           shipment.id,
        "reference_no": shipment.reference_no,
        "status":       shipment.status,
        "pallet_type":  shipment.pallet_type,
        "destination":  shipment.destination,
        "notes":        shipment.notes,
        "created_at":   shipment.created_at,
        "optimized_at": shipment.optimized_at,
        "products": [
            {
                "id":          p.id,
                "name":        p.name,
                "quantity":    p.quantity,
                "length_cm":   p.length_cm,
                "width_cm":    p.width_cm,
                "height_cm":   p.height_cm,
                "weight_kg":   p.weight_kg,
                "constraints": p.constraints,
            }
            for p in products
        ],
        "pallets": [
            {
                "id":              p.id,
                "pallet_number":   p.pallet_number,
                "pallet_type":     p.pallet_type,
                "total_weight_kg": p.total_weight_kg,
                "total_height_cm": p.total_height_cm,
                "total_volume_m3": p.total_volume_m3,
                "fill_rate_pct":   p.fill_rate_pct,
                "constraints":     p.constraints,
            }
            for p in pallets
        ],
    }


@router.post("/{shipment_id}/optimize", response_model=OptimizationStatus)
async def start_optimization(
    shipment_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Optimizasyonu başlat.
    Şimdilik: status'u 'optimizing' yap, frontend JS hesaplar.
    Sprint 2: Python OR-Tools optimizer buraya gelir.
    """
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    shipment.status = "optimizing"
    await db.commit()

    _opt_status[shipment_id] = {
        "status":       "running",
        "progress_pct": 10,
        "message":      "Optimizasyon başlatıldı...",
        "started_at":   time.time(),
    }

    # Arka planda simüle et (3 saniye sonra done)
    background_tasks.add_task(_simulate_optimization, shipment_id, db)

    return OptimizationStatus(
        shipment_id=shipment_id,
        status="running",
        progress_pct=10,
        message="Optimizasyon başlatıldı...",
    )


async def _simulate_optimization(shipment_id: str, db: AsyncSession):
    """
    Geçici: optimizasyonu simüle et.
    Sprint 2'de gerçek Python optimizer ile değiştirilecek.
    """
    import asyncio
    await asyncio.sleep(3)
    _opt_status[shipment_id] = {
        "status":       "done",
        "progress_pct": 100,
        "message":      "Optimizasyon tamamlandı",
        "started_at":   time.time(),
    }
    # DB'yi güncelle
    async with db.begin():
        await db.execute(
            update(Shipment)
            .where(Shipment.id == shipment_id)
            .values(status="done", optimized_at=datetime.now(timezone.utc))
        )


@router.get("/{shipment_id}/status", response_model=OptimizationStatus)
async def get_optimization_status(shipment_id: str):
    """Frontend polling için optimizasyon durumu."""
    opt = _opt_status.get(shipment_id)
    if not opt:
        return OptimizationStatus(
            shipment_id=shipment_id,
            status="done",
            progress_pct=100,
            message="Hazır",
        )
    return OptimizationStatus(
        shipment_id=shipment_id,
        status=opt["status"],
        progress_pct=opt["progress_pct"],
        message=opt["message"],
    )


@router.post("/{shipment_id}/pallets", status_code=status.HTTP_201_CREATED)
async def save_pallets(
    shipment_id: str,
    pallets: list,
    db: AsyncSession = Depends(get_db),
):
    """
    Frontend'in hesapladığı palet sonuçlarını kaydet.
    Frontend JS bin packing yapar, sonucu buraya gönderir.
    """
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # Eski paletleri sil
    from sqlalchemy import delete
    await db.execute(delete(Pallet).where(Pallet.shipment_id == shipment_id))

    await _save_pallets(db, shipment_id, pallets)
    await db.commit()

    return {"saved": len(pallets)}


@router.delete("/{shipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shipment(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Soft delete — veri silinmez, arşivlenir."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    shipment.deleted_at = datetime.now(timezone.utc)
    await db.commit()
