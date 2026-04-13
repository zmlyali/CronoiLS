"""
Cronoi LS — Vehicle Plans API
POST   /api/v1/vehicle-plans                 → Araç planı oluştur (onaylandığında)
GET    /api/v1/vehicle-plans                 → Tüm planları listele
GET    /api/v1/vehicle-plans/{plan_id}       → Plan detayı (araçlar, paletler, siparişler)
PATCH  /api/v1/vehicle-plans/{plan_id}       → Plan güncelle (notlar, araç bilgileri)
PATCH  /api/v1/vehicle-plans/{plan_id}/status→ Durum değiştir
DELETE /api/v1/vehicle-plans/{plan_id}       → Plan sil (soft)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from app.core.database import get_db
from app.models import VehiclePlan, Shipment, Scenario, Order, OrderShipment, Pallet

router = APIRouter()


# ── Pydantic Schemas ─────────────────────────────────────────

class VehicleItemSchema(BaseModel):
    vehicle_name: str = ""
    vehicle_type: str = ""
    vehicle_code: str = ""
    length_cm: float = 1360
    width_cm: float = 245
    height_cm: float = 270
    max_weight_kg: float = 24000
    pallet_ids: list = Field(default_factory=list)
    pallet_count: int = 0
    fill_rate_pct: float = 0
    cost: float = 0
    current_weight_kg: float = 0
    # User-editable notes
    plate_no: str = ""
    company_name: str = ""
    driver_name: str = ""
    planned_date: str = ""
    planned_time: str = ""
    notes: str = ""


class VehiclePlanCreateRequest(BaseModel):
    shipment_id: str
    scenario_id: Optional[str] = None
    reference_no: Optional[str] = None
    destination: Optional[str] = None
    total_cost: float = 0
    total_vehicles: int = 0
    total_pallets: int = 0
    total_weight_kg: float = 0
    notes: Optional[str] = None
    vehicles: List[VehicleItemSchema] = Field(default_factory=list)
    order_ids: List[str] = Field(default_factory=list)


class VehiclePlanUpdateRequest(BaseModel):
    notes: Optional[str] = None
    vehicles: Optional[List[VehicleItemSchema]] = None


class StatusUpdateRequest(BaseModel):
    status: str  # approved, loading, completed, cancelled


# ── Helpers ──────────────────────────────────────────────────

VALID_STATUSES = {"approved", "loading", "completed", "cancelled"}
VALID_TRANSITIONS = {
    "approved": {"loading", "cancelled"},
    "loading": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


def _plan_to_dict(plan: VehiclePlan, orders=None, pallets=None) -> dict:
    d = {
        "id": plan.id,
        "company_id": plan.company_id,
        "shipment_id": plan.shipment_id,
        "scenario_id": plan.scenario_id,
        "reference_no": plan.reference_no,
        "status": plan.status,
        "total_cost": plan.total_cost,
        "total_vehicles": plan.total_vehicles,
        "total_pallets": plan.total_pallets,
        "total_weight_kg": plan.total_weight_kg,
        "destination": plan.destination,
        "notes": plan.notes,
        "vehicles": plan.vehicles or [],
        "order_ids": plan.order_ids or [],
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }
    if orders is not None:
        d["orders"] = orders
    if pallets is not None:
        d["pallets"] = pallets
    return d


# ── Endpoints ────────────────────────────────────────────────

@router.post("")
async def create_vehicle_plan(
    payload: VehiclePlanCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Araç planı onaylandığında oluştur."""
    shipment = await db.get(Shipment, payload.shipment_id)
    if not shipment:
        raise HTTPException(404, "Sevkiyat bulunamadı")

    plan = VehiclePlan(
        company_id=shipment.company_id,
        shipment_id=payload.shipment_id,
        scenario_id=payload.scenario_id,
        reference_no=payload.reference_no or shipment.reference_no,
        status="approved",
        total_cost=payload.total_cost,
        total_vehicles=payload.total_vehicles or len(payload.vehicles),
        total_pallets=payload.total_pallets,
        total_weight_kg=payload.total_weight_kg,
        destination=payload.destination or shipment.destination,
        notes=payload.notes,
        vehicles=[v.model_dump() for v in payload.vehicles],
        order_ids=payload.order_ids,
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)
    return _plan_to_dict(plan)


@router.get("")
async def list_vehicle_plans(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """Tüm araç planlarını listele (filtrelenebilir)."""
    q = select(VehiclePlan).order_by(desc(VehiclePlan.approved_at))
    if status:
        q = q.where(VehiclePlan.status == status)
    q = q.offset(offset).limit(limit)

    result = await db.execute(q)
    plans = result.scalars().all()

    # Her plan için sipariş adlarını da al
    out = []
    for plan in plans:
        order_names = []
        if plan.order_ids:
            ords = await db.execute(
                select(Order.id, Order.order_no, Order.customer_name, Order.city, Order.status)
                .where(Order.id.in_(plan.order_ids))
            )
            order_names = [
                {"id": r.id, "order_no": r.order_no, "customer_name": r.customer_name,
                 "city": r.city, "status": r.status}
                for r in ords
            ]
        d = _plan_to_dict(plan, orders=order_names)
        out.append(d)

    return out


@router.get("/{plan_id}")
async def get_vehicle_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Plan detayı: araçlar, paletler, siparişler."""
    plan = await db.get(VehiclePlan, plan_id)
    if not plan:
        raise HTTPException(404, "Araç planı bulunamadı")

    # Siparişler
    orders_data = []
    if plan.order_ids:
        ords = await db.execute(
            select(Order).where(Order.id.in_(plan.order_ids))
        )
        for o in ords.scalars().all():
            orders_data.append({
                "id": o.id, "order_no": o.order_no,
                "customer_name": o.customer_name, "city": o.city,
                "status": o.status, "priority": o.priority,
                "requested_ship_date": o.requested_ship_date,
                "deadline_date": o.deadline_date,
            })

    # Paletler
    pallets_data = []
    if plan.shipment_id:
        pals = await db.execute(
            select(Pallet).where(Pallet.shipment_id == plan.shipment_id)
            .order_by(Pallet.pallet_number)
        )
        for p in pals.scalars().all():
            pallets_data.append({
                "id": p.id, "pallet_number": p.pallet_number,
                "pallet_type": p.pallet_type, "fill_rate_pct": p.fill_rate_pct,
                "total_weight_kg": p.total_weight_kg,
                "total_height_cm": p.total_height_cm,
                "total_volume_m3": p.total_volume_m3,
            })

    return _plan_to_dict(plan, orders=orders_data, pallets=pallets_data)


@router.patch("/{plan_id}")
async def update_vehicle_plan(
    plan_id: str,
    payload: VehiclePlanUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Plan notlarını veya araç bilgilerini güncelle."""
    plan = await db.get(VehiclePlan, plan_id)
    if not plan:
        raise HTTPException(404, "Araç planı bulunamadı")
    if plan.status in ("completed", "cancelled"):
        raise HTTPException(400, "Tamamlanmış veya iptal edilmiş plan güncellenemez")

    if payload.notes is not None:
        plan.notes = payload.notes
    if payload.vehicles is not None:
        plan.vehicles = [v.model_dump() for v in payload.vehicles]
        plan.total_vehicles = len(payload.vehicles)

    await db.flush()
    return _plan_to_dict(plan)


@router.patch("/{plan_id}/status")
async def update_plan_status(
    plan_id: str,
    payload: StatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Plan durumunu değiştir."""
    plan = await db.get(VehiclePlan, plan_id)
    if not plan:
        raise HTTPException(404, "Araç planı bulunamadı")

    new_status = payload.status
    if new_status not in VALID_STATUSES:
        raise HTTPException(400, f"Geçersiz durum: {new_status}")

    allowed = VALID_TRANSITIONS.get(plan.status, set())
    if new_status not in allowed:
        raise HTTPException(400, f"'{plan.status}' → '{new_status}' geçişi yapılamaz")

    plan.status = new_status
    await db.flush()
    return _plan_to_dict(plan)


@router.delete("/{plan_id}")
async def delete_vehicle_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Araç planını sil."""
    plan = await db.get(VehiclePlan, plan_id)
    if not plan:
        raise HTTPException(404, "Araç planı bulunamadı")
    await db.delete(plan)
    return {"deleted": True}
