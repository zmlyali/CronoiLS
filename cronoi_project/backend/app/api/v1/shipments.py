"""
Cronoi LS — Shipments API (Gerçek DB implementasyonu)
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)

from app.core.database import get_db
from app.models import Shipment, ShipmentProduct, Pallet, PalletProduct, Scenario, OrderShipment, Order, OrderItem, ShipmentPhoto

router = APIRouter()


# ── Geçici company_id (auth yokken sabit) ───────────────────────
DEMO_COMPANY_ID = "00000000-0000-0000-0000-000000000001"
DEMO_USER_ID    = "00000000-0000-0000-0000-000000000002"

# Optimizasyon durumunu RAM'de tut (Redis olmadığı için)
_opt_status: dict = {}

# CRONOI_LS_STATUS_MODEL.md v2 — kanonik sevkiyat statüleri
VALID_SHIPMENT_STATUSES = [
    # Kanonik
    "draft", "plan_confirmed", "loading", "completed", "in_transit", "delivered", "cancelled",
    # Geriye dönük uyum
    "optimizing", "optimized", "planned", "done", "loaded", "shipped",
]
SHIPMENT_TRANSITIONS = {
    # Kanonik geçişler (CRONOI_LS_STATUS_MODEL.md)
    "draft":          ["plan_confirmed", "cancelled"],
    "plan_confirmed": ["loading", "loaded", "draft", "cancelled"],   # plandan direkt yüklemeye de geçebilir
    "loading":        ["completed", "plan_confirmed"],
    "completed":      ["in_transit"],
    "in_transit":     ["delivered"],
    "delivered":      [],
    "cancelled":      ["draft"],
    # Geriye dönük uyum
    "optimizing":     ["plan_confirmed", "optimized", "draft"],
    "optimized":      ["loading", "plan_confirmed", "draft", "cancelled"],
    "planned":        ["loading", "plan_confirmed", "draft", "cancelled"],
    "done":           ["in_transit", "delivered"],
    "loaded":         ["in_transit", "delivered"],
    "shipped":        ["delivered"],
}


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
    pallet_type: str = "P1"
    destination: Optional[str] = None
    notes: Optional[str] = None
    loading_date: Optional[str] = None
    delivery_date: Optional[str] = None
    order_ids: List[str] = []
    products: List[ProductInput] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "pallet_type": "P1",
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
    avg_fill_rate_pct: Optional[float] = None
    vehicle_fill_rate_pct: Optional[float] = None
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


class OptimizeRequest(BaseModel):
    vehicle_ids: Optional[list] = None
    distance_km: Optional[float] = 500
    duration_hours: Optional[float] = 8
    engine_params: Optional[dict] = None


# ── Yardımcı: reference_no üret ────────────────────────────────

async def _next_reference_no(db: AsyncSession) -> str:
    now = datetime.now()
    prefix = f"SH-{now.strftime('%y')}-{now.strftime('%m')}"
    result = await db.execute(
        select(func.count(Shipment.id)).where(
            Shipment.reference_no.like(f"{prefix}-%")
        )
    )
    count = result.scalar() or 0
    return f"{prefix}-{count + 1:05d}"


# ── Yardımcı: JS bin packing sonucunu DB'ye kaydet ──────────────

async def _save_pallets(db: AsyncSession, shipment_id: str, pallets_data: list):
    for i, p in enumerate(pallets_data):
        pallet = Pallet(
            id=str(uuid4()),
            shipment_id=shipment_id,
            pallet_number=i + 1,
            pallet_type=p.get("type", "P1"),
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
                position_x=pr.get("pos_x") or pr.get("position_x"),
                position_y=pr.get("pos_y") or pr.get("position_y"),
                position_z=pr.get("pos_z") or pr.get("position_z"),
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

    # Sipariş bağlantılarını oluştur (OrderShipment)
    for oid in (payload.order_ids or []):
        db.add(OrderShipment(order_id=oid, shipment_id=shipment.id))

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
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Tüm sevkiyatları listele (en yeni önce) — palet doluluk oranı dahil."""
    base_filter = [Shipment.company_id == DEMO_COMPANY_ID]
    if include_deleted:
        base_filter.append(Shipment.deleted_at.isnot(None))
    else:
        base_filter.append(Shipment.deleted_at.is_(None))

    scenario_sq = (
        select(
            Scenario.shipment_id,
            func.max(Scenario.avg_fill_rate_pct).label('vehicle_fill_rate'),
        )
        .where(Scenario.is_selected == True)  # noqa: E712
        .group_by(Scenario.shipment_id)
        .subquery()
    )

    q = (
        select(
            Shipment,
            func.avg(Pallet.fill_rate_pct).label('avg_fill_rate'),
            func.count(Pallet.id).label('pallet_count'),
            scenario_sq.c.vehicle_fill_rate,
        )
        .outerjoin(Pallet, Pallet.shipment_id == Shipment.id)
        .outerjoin(scenario_sq, scenario_sq.c.shipment_id == Shipment.id)
        .where(*base_filter)
        .group_by(Shipment.id, scenario_sq.c.vehicle_fill_rate)
        .order_by(Shipment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(q)
    rows = result.all()

    return [
        ShipmentSummary(
            id=row.Shipment.id,
            reference_no=row.Shipment.reference_no,
            status=row.Shipment.status,
            pallet_type=row.Shipment.pallet_type,
            destination=row.Shipment.destination,
            total_pallets=row.pallet_count or 0,
            avg_fill_rate_pct=round(float(row.avg_fill_rate), 1) if row.avg_fill_rate is not None else None,
            vehicle_fill_rate_pct=round(float(row.vehicle_fill_rate), 1) if row.vehicle_fill_rate is not None else None,
            created_at=row.Shipment.created_at,
            optimized_at=row.Shipment.optimized_at,
        )
        for row in rows
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

    # Paletleri çek (ürünlerle birlikte)
    pallet_result = await db.execute(
        select(Pallet)
        .where(Pallet.shipment_id == shipment_id)
        .order_by(Pallet.pallet_number)
        .options(selectinload(Pallet.products))
    )
    pallets = pallet_result.scalars().unique().all()

    # Bağlı siparişleri çek (order_shipments JOIN orders, ürün sayısı dahil)
    item_count_sq = (
        select(OrderItem.order_id, func.count(OrderItem.id).label('item_count'))
        .group_by(OrderItem.order_id)
        .subquery()
    )
    order_result = await db.execute(
        select(Order, item_count_sq.c.item_count)
        .join(OrderShipment, OrderShipment.order_id == Order.id)
        .outerjoin(item_count_sq, item_count_sq.c.order_id == Order.id)
        .where(OrderShipment.shipment_id == shipment_id)
        .where(Order.deleted_at.is_(None))
        .options(selectinload(Order.items))
    )
    order_rows = order_result.unique().all()

    # Seçilen senaryo çek (TIR doluluk oranı için)
    # Önce is_selected=True, sonra is_recommended=True, sonra herhangi biri
    scenario_result = await db.execute(
        select(Scenario)
        .where(Scenario.shipment_id == shipment_id, Scenario.is_selected == True)
        .limit(1)
    )
    selected_scenario = scenario_result.scalar_one_or_none()

    if not selected_scenario:
        # Fallback: is_recommended olanı dene
        rec_result = await db.execute(
            select(Scenario)
            .where(Scenario.shipment_id == shipment_id, Scenario.is_recommended == True)
            .limit(1)
        )
        selected_scenario = rec_result.scalar_one_or_none()

    if not selected_scenario:
        # Fallback: herhangi bir senaryoyu al
        any_result = await db.execute(
            select(Scenario)
            .where(Scenario.shipment_id == shipment_id)
            .order_by(Scenario.created_at)
            .limit(1)
        )
        selected_scenario = any_result.scalar_one_or_none()

    # Fotoğrafları çek
    photo_result = await db.execute(
        select(ShipmentPhoto)
        .where(ShipmentPhoto.shipment_id == shipment_id)
        .order_by(ShipmentPhoto.sort_order)
    )
    photos = photo_result.scalars().all()

    avg_pallet_fill = (
        round(sum(p.fill_rate_pct for p in pallets) / len(pallets), 1)
        if pallets else None
    )

    return {
        "id":                shipment.id,
        "reference_no":      shipment.reference_no,
        "status":            shipment.status,
        "pallet_type":       shipment.pallet_type,
        "destination":       shipment.destination,
        "notes":             shipment.notes,
        "created_at":        shipment.created_at,
        "optimized_at":      shipment.optimized_at,
        "loaded_at":         shipment.loaded_at,
        "delivered_at":      shipment.delivered_at,
        "avg_fill_rate_pct": avg_pallet_fill,
        "photos": [
            {
                "id":       ph.id,
                "filename": ph.filename,
                "data":     ph.data,
            }
            for ph in photos
        ],
        "orders": [
            {
                "id":                 row.Order.id,
                "order_no":           row.Order.order_no,
                "customer_name":      row.Order.customer_name,
                "city":               row.Order.city,
                "address":            row.Order.address,
                "project_code":       row.Order.project_code,
                "contact_name":       row.Order.contact_name,
                "contact_phone":      row.Order.contact_phone,
                "status":             row.Order.status,
                "requested_ship_date":row.Order.requested_ship_date,
                "item_count":         row.item_count or 0,
                "items": [
                    {
                        "name":       item.name,
                        "sku":        item.sku,
                        "quantity":   item.quantity,
                        "length_cm":  item.length_cm,
                        "width_cm":   item.width_cm,
                        "height_cm":  item.height_cm,
                        "weight_kg":  item.weight_kg,
                    }
                    for item in (row.Order.items or [])
                ],
            }
            for row in order_rows
        ],
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
                "layout_data":     p.layout_data,
                "products":        (
                    p.layout_data.get("products", [])
                    if p.layout_data and "products" in (p.layout_data or {})
                    else [
                        {
                            "name": pp.name, "quantity": pp.quantity,
                            "length_cm": pp.length_cm, "width_cm": pp.width_cm,
                            "height_cm": pp.height_cm, "weight_kg": pp.weight_kg,
                            "pos_x": pp.position_x, "pos_y": pp.position_y, "pos_z": pp.position_z,
                            "constraints": pp.constraints or [],
                        }
                        for pp in (p.products or [])
                    ]
                ),
            }
            for p in pallets
        ],
        "selected_scenario": {
            "name":               selected_scenario.name,
            "strategy":           selected_scenario.strategy,
            "total_cost":         selected_scenario.total_cost,
            "total_vehicles":     selected_scenario.total_vehicles,
            "avg_fill_rate_pct":  selected_scenario.avg_fill_rate_pct,
            "vehicle_assignments":selected_scenario.vehicle_assignments,
        } if selected_scenario else None,
    }


@router.post("/{shipment_id}/optimize", response_model=OptimizationStatus)
async def start_optimization(
    shipment_id: str,
    background_tasks: BackgroundTasks,
    body: OptimizeRequest = OptimizeRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    Optimizasyonu başlat — gerçek 3D bin packing çalıştırır.
    Ürünleri DB'den çeker, optimizer ile paletlere yerleştirir, sonuçları kaydeder.
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

    background_tasks.add_task(_run_optimization, shipment_id, body.engine_params, body.vehicle_ids)

    return OptimizationStatus(
        shipment_id=shipment_id,
        status="running",
        progress_pct=10,
        message="Optimizasyon başlatıldı...",
    )


async def _run_optimization(shipment_id: str, engine_params: dict = None, vehicle_ids: list = None):
    """
    Arka planda gerçek bin packing çalıştır.
    Yeni DB session açar (background task'ta request session kullanılamaz).
    """
    from app.core.database import AsyncSessionLocal
    from app.services.optimizer import BinPackingOptimizer3D, MixedBinPackingOptimizer, PalletConfig, ProductItem, ConstraintType, OptimizationParams, PALLET_BOARD_HEIGHT_CM
    from app.services.constraint_engine import get_constraint_engine
    from sqlalchemy import delete as sa_delete

    async with AsyncSessionLocal() as db:
        try:
            _opt_status[shipment_id] = {
                "status": "running", "progress_pct": 20,
                "message": "Ürünler okunuyor...", "started_at": time.time(),
            }

            # 1) Ürünleri DB'den çek
            result = await db.execute(
                select(ShipmentProduct)
                .where(ShipmentProduct.shipment_id == shipment_id)
                .order_by(ShipmentProduct.sort_order)
            )
            db_products = result.scalars().all()

            shipment = await db.get(Shipment, shipment_id)
            pallet_type = shipment.pallet_type or "P1"

            # 2) Palet konfigürasyonlarını DB'den çek (PalletDefinition tablosu)
            from app.models import PalletDefinition
            pd_result = await db.execute(
                select(PalletDefinition).where(
                    PalletDefinition.company_id == shipment.company_id,
                    PalletDefinition.is_active == True,  # noqa: E712
                )
            )
            db_pallet_defs = pd_result.scalars().all()

            pallet_configs = {}
            for pd in db_pallet_defs:
                pallet_configs[pd.code] = PalletConfig(
                    type=pd.code,
                    width_cm=pd.width_cm,
                    length_cm=pd.length_cm,
                    max_height_cm=pd.max_height_cm,
                    max_weight_kg=pd.max_weight_kg,
                )

            # DB'de tanım yoksa fallback olarak hardcoded kullan
            if not pallet_configs:
                pallet_configs = {
                    "P1": PalletConfig("P1", 80, 120, 250, 700),
                    "P5": PalletConfig("P5", 100, 120, 250, 700),
                    "P10": PalletConfig("P10", 120, 200, 250, 700),
                }

            config = pallet_configs.get(pallet_type, next(iter(pallet_configs.values())))

            # 3) Ürünleri optimizer formatına çevir — TÜM kısıtlar eşlenir
            CONSTRAINT_MAP = {
                "fragile": ConstraintType.FRAGILE,
                "heavy": ConstraintType.HEAVY,
                "temp": ConstraintType.TEMP,
                "no_stack": ConstraintType.NO_STACK,
                "must_bottom": ConstraintType.MUST_BOTTOM,
                "must_top": ConstraintType.MUST_TOP,
                "horizontal_only": ConstraintType.HORIZONTAL_ONLY,
                "horizontal": ConstraintType.HORIZONTAL_ONLY,
                "vertical_only": ConstraintType.VERTICAL_ONLY,
                "vertical": ConstraintType.VERTICAL_ONLY,
                "this_side_up": ConstraintType.THIS_SIDE_UP,
                "cold_chain": ConstraintType.COLD_CHAIN,
                "hazmat": ConstraintType.HAZMAT,
                "keep_dry": ConstraintType.KEEP_DRY,
                "load_first": ConstraintType.LOAD_FIRST,
                "load_last": ConstraintType.LOAD_LAST,
                "veh_front": ConstraintType.VEH_FRONT,
                "veh_rear": ConstraintType.VEH_REAR,
            }
            items = []
            for p in db_products:
                mapped_constraints = []
                primary_constraint = None
                if p.constraints and isinstance(p.constraints, list):
                    for c_entry in p.constraints:
                        code = c_entry.get("code", "") if isinstance(c_entry, dict) else str(c_entry)
                        ct = CONSTRAINT_MAP.get(code)
                        if ct:
                            mapped_constraints.append(ct)
                            if primary_constraint is None:
                                primary_constraint = ct
                items.append(ProductItem(
                    name=p.name, quantity=p.quantity,
                    length_cm=p.length_cm, width_cm=p.width_cm,
                    height_cm=p.height_cm, weight_kg=p.weight_kg,
                    constraint=primary_constraint,
                    constraints=mapped_constraints,
                ))

            _opt_status[shipment_id]["progress_pct"] = 50
            _opt_status[shipment_id]["message"] = "3D bin packing çalışıyor..."

            # Optimizasyon parametrelerini yükle (request body → shipment meta → default)
            engine_meta = engine_params or {}
            if not engine_meta:
                engine_meta = (shipment.meta or {}).get("engine_params", {}) if hasattr(shipment, 'meta') and shipment.meta else {}

            # ── Araç yükseklik limitini hesapla ──
            # Seçili araçların en küçük iç yüksekliği → palet yükseklik üst sınırı
            if vehicle_ids and "vehicleMaxHeightCm" not in engine_meta:
                try:
                    from app.models import VehicleDefinition
                    vd_result = await db.execute(
                        select(VehicleDefinition.height_cm).where(
                            VehicleDefinition.company_id == shipment.company_id,
                            VehicleDefinition.is_active == True,  # noqa: E712
                        )
                    )
                    db_vehicle_heights = [row[0] for row in vd_result.fetchall() if row[0]]
                    if db_vehicle_heights:
                        min_vehicle_h = min(db_vehicle_heights)
                        engine_meta["vehicleMaxHeightCm"] = min_vehicle_h
                        logger.info(f"Araç yükseklik limiti: {min_vehicle_h}cm (en küçük aktif araç)")
                except Exception:
                    pass  # DB'de araç tablosu yoksa devam

            opt_params = OptimizationParams.from_dict(engine_meta)

            # ── Constraint Engine yükle (DB'den varsa, yoksa defaults) ──
            constraint_engine = get_constraint_engine()
            try:
                from app.models import ConstraintDefinition, ConstraintCompatibility
                cd_result = await db.execute(
                    select(ConstraintDefinition).where(
                        ConstraintDefinition.company_id == shipment.company_id,
                        ConstraintDefinition.is_active == True,  # noqa: E712
                    )
                )
                db_constraints = cd_result.scalars().all()
                if db_constraints:
                    constraint_defs = []
                    for cd in db_constraints:
                        constraint_defs.append({
                            "id": str(cd.id), "code": cd.code, "name": cd.name,
                            "category": cd.category, "scope": cd.scope,
                            "optimizer_rules": cd.optimizer_rules or {},
                        })
                    cc_result = await db.execute(select(ConstraintCompatibility))
                    compat_rows = cc_result.scalars().all()
                    compat_rules = []
                    for cr in compat_rows:
                        compat_rules.append({
                            "constraint_a_id": str(cr.constraint_a_id),
                            "constraint_b_id": str(cr.constraint_b_id),
                            "rule_type": cr.rule_type,
                            "severity": cr.severity,
                            "description": getattr(cr, 'description', ''),
                            "is_symmetric": getattr(cr, 'is_symmetric', True),
                        })
                    from app.services.constraint_engine import ConstraintEngine
                    constraint_engine = ConstraintEngine()
                    constraint_engine.load_from_dicts(constraint_defs, compat_rules)
            except Exception:
                # DB'de kısıt tabloları yoksa defaults ile devam et
                pass

            # 4) Optimizer çalıştır — birden fazla aktif palet tipi varsa karma optimizasyon
            active_configs = list(pallet_configs.values())
            if len(active_configs) > 1:
                mixed_optimizer = MixedBinPackingOptimizer(
                    active_configs, default_type=config, params=opt_params,
                    constraint_engine=constraint_engine,
                )
                opt_result = mixed_optimizer.optimize(items)
            else:
                optimizer = BinPackingOptimizer3D(
                    config, params=opt_params, constraint_engine=constraint_engine,
                )
                opt_result = optimizer.optimize(items)

            _opt_status[shipment_id]["progress_pct"] = 80
            _opt_status[shipment_id]["message"] = "Paletler kaydediliyor..."

            # 5) Eski paletleri sil
            await db.execute(sa_delete(Pallet).where(Pallet.shipment_id == shipment_id))

            # 6) Yeni paletleri DB'ye yaz
            for op in opt_result.pallets:
                pallet = Pallet(
                    id=str(uuid4()),
                    shipment_id=shipment_id,
                    pallet_number=op.pallet_number,
                    pallet_type=op.pallet_type,
                    total_weight_kg=op.total_weight_kg,
                    total_height_cm=op.total_height_cm,
                    total_volume_m3=op.total_volume_m3,
                    fill_rate_pct=op.fill_rate_pct,
                    constraints=[c.value if hasattr(c, 'value') else str(c) for c in op.constraints],
                    layout_data={
                        "products": [
                            {
                                "name": pr.name, "quantity": pr.quantity,
                                "length_cm": pr.length_cm, "width_cm": pr.width_cm,
                                "height_cm": pr.height_cm, "weight_kg": pr.weight_kg,
                                "pos_x": pr.pos_x, "pos_y": pr.pos_y, "pos_z": pr.pos_z,
                                "rotated": pr.rotated,
                                "constraint": pr.constraint.value if pr.constraint else None,
                                "constraints": [c.value if hasattr(c, 'value') else str(c) for c in (pr.constraints or [])],
                            }
                            for pr in op.products
                        ],
                        "stability": op.layout_data.get("stability"),
                    },
                )
                db.add(pallet)

            # 7) Sevkiyat durumunu güncelle
            shipment.status = "optimized"
            shipment.optimized_at = datetime.now(timezone.utc)

            await db.commit()

            _opt_status[shipment_id] = {
                "status": "done", "progress_pct": 100,
                "message": f"Tamamlandı — {opt_result.total_pallets} palet oluşturuldu"
                    + (f" ({len(opt_result.rejected_items)} ürün reddedildi)" if opt_result.rejected_items else "")
                    + (f" | Kısıt doğrulaması: {'✅ Geçti' if opt_result.constraints_satisfied else '⛔ İhlal var'}" if opt_result.constraint_validations else ""),
                "started_at": time.time(),
                "rejected_items": [
                    {"name": r.name, "reason": r.reason} for r in opt_result.rejected_items
                ] if opt_result.rejected_items else [],
                "warnings": opt_result.warnings or [],
                "pallet_type_breakdown": [
                    {"pallet_type": b.pallet_type, "count": b.count,
                     "total_weight_kg": b.total_weight_kg, "avg_fill_rate_pct": b.avg_fill_rate_pct}
                    for b in opt_result.pallet_type_breakdown
                ] if opt_result.pallet_type_breakdown else [],
                "constraints_satisfied": opt_result.constraints_satisfied,
                "constraint_validations": [
                    {"pallet_number": v.pallet_number, "passed": v.passed,
                     "violations": v.violations, "warnings": v.warnings}
                    for v in opt_result.constraint_validations
                ] if opt_result.constraint_validations else [],
                "quantity_audit": opt_result.quantity_audit or {},
                "actionable_errors": [
                    {"code": e.code, "message": e.message, "action_label": e.action_label,
                     "affected_pallet_id": e.affected_pallet_id, "severity": e.severity}
                    for e in opt_result.actionable_errors
                ] if opt_result.actionable_errors else [],
                "compliance": opt_result.compliance or [],
                "binding_dimension": opt_result.binding_dimension or "",
            }

        except Exception as e:
            await db.rollback()
            _opt_status[shipment_id] = {
                "status": "failed", "progress_pct": 0,
                "message": f"Hata: {str(e)}", "started_at": time.time(),
            }
            # Shipment'ı draft'a döndür
            try:
                await db.execute(
                    update(Shipment).where(Shipment.id == shipment_id).values(status="draft")
                )
                await db.commit()
            except Exception:
                pass


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


@router.get("/{shipment_id}/pallets")
async def get_pallets(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Sevkiyata ait hesaplanmış paletleri döndür.
    Frontend optimizasyon sonrası bu endpoint'i çağırır.
    """
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    result = await db.execute(
        select(Pallet)
        .where(Pallet.shipment_id == shipment_id)
        .order_by(Pallet.pallet_number)
    )
    pallets = result.scalars().all()

    # Her palet için ürünleri çek
    pallet_list = []
    for p in pallets:
        products = []
        if p.layout_data and "products" in p.layout_data:
            products = p.layout_data["products"]
        else:
            # layout_data yoksa pallet_products tablosundan çek
            pp_result = await db.execute(
                select(PalletProduct).where(PalletProduct.pallet_id == p.id)
            )
            for pp in pp_result.scalars().all():
                products.append({
                    "name": pp.name, "quantity": pp.quantity,
                    "length_cm": pp.length_cm, "width_cm": pp.width_cm,
                    "height_cm": pp.height_cm, "weight_kg": pp.weight_kg,
                    "pos_x": pp.position_x, "pos_y": pp.position_y, "pos_z": pp.position_z,
                    "constraint": None, "constraints": pp.constraints or [],
                })

        pallet_list.append({
            "pallet_number":   p.pallet_number,
            "pallet_type":     p.pallet_type,
            "total_weight_kg": p.total_weight_kg,
            "total_height_cm": p.total_height_cm,
            "total_volume_m3": p.total_volume_m3,
            "fill_rate_pct":   p.fill_rate_pct,
            "constraints":     p.constraints or [],
            "products":        products,
            "stability":       (p.layout_data or {}).get("stability"),
        })

    return {"pallets": pallet_list, "total": len(pallet_list)}


@router.post("/{shipment_id}/pallets", status_code=status.HTTP_201_CREATED)
async def save_pallets(
    shipment_id: str,
    pallets: list = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Frontend'in hesapladığı palet sonuçlarını kaydet (local mod fallback).
    """
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    from sqlalchemy import delete
    await db.execute(delete(Pallet).where(Pallet.shipment_id == shipment_id))

    await _save_pallets(db, shipment_id, pallets)
    await db.commit()

    return {"saved": len(pallets)}


@router.delete("/{shipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shipment(
    shipment_id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Soft delete — veri silinmez, arşivlenir."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")
    if shipment.deleted_at:
        raise HTTPException(status_code=404, detail="Sevkiyat zaten silinmiş")

    # draft dışındaki sevkiyatlar için force gerekli
    if shipment.status not in ("draft",) and not force:
        status_label = {
            "optimizing": "Optimize Ediliyor", "optimized": "Optimize Edildi",
            "loading": "Yükleniyor", "loaded": "Yüklendi",
            "delivered": "Teslim Edildi", "cancelled": "İptal",
        }.get(shipment.status, shipment.status)
        raise HTTPException(
            status_code=409,
            detail=f"Bu sevkiyat '{status_label}' durumunda. Silmek istediğinizden emin misiniz? Onaylayarak devam edebilirsiniz.",
        )

    shipment.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.patch("/{shipment_id}/restore")
async def restore_shipment(shipment_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete edilen sevkiyatı geri yükle."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")
    if not shipment.deleted_at:
        raise HTTPException(status_code=400, detail="Sevkiyat zaten aktif")
    shipment.deleted_at = None
    await db.commit()
    return {"id": shipment_id, "status": shipment.status, "restored": True}


@router.post("/{shipment_id}/complete")
async def complete_shipment(
    shipment_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Sevkiyatı yüklendi olarak işaretle.
    Bağlı siparişlerin statüsünü günceller.
    """
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # Statü geçiş kontrolü — tüm tamamlanabilir durumlar
    completable = ["optimized", "loading", "plan_confirmed", "planned", "draft"]
    if shipment.status not in completable:
        raise HTTPException(
            status_code=400,
            detail=f"Sevkiyat '{shipment.status}' durumundan 'loaded' durumuna geçemez. İzin verilen: {completable}"
        )

    shipment.status = "loaded"
    shipment.loaded_at = datetime.now(timezone.utc)
    if payload.get("notes"):
        shipment.notes = payload["notes"]

    # Seçili senaryo yoksa, mevcut senaryolardan birini otomatik seç
    selected_check = await db.execute(
        select(Scenario).where(
            Scenario.shipment_id == shipment_id,
            Scenario.is_selected == True
        ).limit(1)
    )
    if not selected_check.scalar_one_or_none():
        # Recommended veya ilk senaryoyu seç
        fallback = await db.execute(
            select(Scenario).where(Scenario.shipment_id == shipment_id)
            .order_by(Scenario.created_at).limit(1)
        )
        fallback_scenario = fallback.scalar_one_or_none()
        if fallback_scenario:
            fallback_scenario.is_selected = True
        elif payload.get("selected_scenario"):
            # DB'de hiç senaryo yok — frontend'den gelen veriyle oluştur
            sc_data = payload["selected_scenario"]
            new_scenario = Scenario(
                id=str(uuid4()),
                shipment_id=shipment_id,
                name=sc_data.get("name", "Araç Planı"),
                strategy=sc_data.get("strategy", "manual"),
                total_cost=sc_data.get("total_cost", 0),
                cost_per_pallet=sc_data.get("cost_per_pallet", 0),
                total_vehicles=sc_data.get("total_vehicles", 0),
                avg_fill_rate_pct=sc_data.get("avg_fill_rate_pct", 0),
                is_recommended=True,
                is_selected=True,
                vehicle_assignments=sc_data.get("vehicle_assignments", []),
            )
            db.add(new_scenario)

    # Bağlı siparislerin statüsünü güncelle
    order_ids = payload.get("order_ids", [])
    updated_orders = []

    if order_ids:
        # Tüm tamamlanabilir sipariş statüleri (kanonik + geriye dönük uyum)
        loadable_statuses = [
            "pending", "in_shipment", "pallet_planned", "vehicle_planned",
            "planned", "loading_planned", "load_planned",
        ]
        for oid in order_ids:
            order = await db.get(Order, oid)
            if order and order.status in loadable_statuses:
                order.status = "loaded"
                updated_orders.append({"id": order.id, "order_no": order.order_no, "status": "loaded"})

                # OrderShipment bağlantısı oluştur (eğer yoksa)
                existing = await db.execute(
                    select(OrderShipment).where(
                        OrderShipment.order_id == oid,
                        OrderShipment.shipment_id == shipment_id
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(OrderShipment(order_id=oid, shipment_id=shipment_id))

    # Fotoğrafları kaydet (base64 data URL'ler)
    photos_data = payload.get("photos", [])
    for idx, photo_url in enumerate(photos_data):
        if not isinstance(photo_url, str) or not photo_url.startswith("data:"):
            continue
        db.add(ShipmentPhoto(
            shipment_id=shipment_id,
            filename=f"photo_{idx+1}.jpg",
            mime_type="image/jpeg",
            data=photo_url,
            sort_order=idx,
        ))

    await db.commit()

    return {
        "id": shipment_id,
        "reference_no": shipment.reference_no,
        "status": "loaded",
        "loaded_at": shipment.loaded_at.isoformat() if shipment.loaded_at else None,
        "updated_orders": updated_orders,
        "message": f"Sevkiyat yüklendi, {len(updated_orders)} sipariş güncellendi"
    }


@router.patch("/{shipment_id}/status")
async def update_shipment_status(
    shipment_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Sevkiyat statüsünü geçerli geçiş kurallarına göre güncelle."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    new_status = payload.get("status")
    if new_status not in VALID_SHIPMENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Geçersiz statü: {new_status}. Geçerli değerler: {VALID_SHIPMENT_STATUSES}")

    allowed = SHIPMENT_TRANSITIONS.get(shipment.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"'{shipment.status}' → '{new_status}' geçişi geçerli değil. İzin verilenler: {allowed}"
        )

    shipment.status = new_status

    # Zaman damgalarını otomatik ayarla
    now = datetime.now(timezone.utc)
    if new_status == "optimized":
        shipment.optimized_at = now
    elif new_status == "loaded":
        shipment.loaded_at = now
    elif new_status == "delivered":
        shipment.delivered_at = now

    await db.commit()
    return {"id": shipment_id, "status": new_status}


# ── Haftalık Özet Rapor ─────────────────────────────────────────

@router.get("/reports/weekly-summary")
async def weekly_summary_report(
    db: AsyncSession = Depends(get_db),
):
    """
    Araç planlaması yapılmış (vehicle_planned) siparişler için haftalık özet:
    1. Ürün → Palet eşleştirmesi (depo ekibi için)
    2. Araç tipleri ve plan (lojistik ekibi için)
    """
    # vehicle_planned veya loaded/plan_confirmed durumdaki aktif sevkiyatları çek
    shipment_result = await db.execute(
        select(Shipment)
        .where(
            Shipment.company_id == DEMO_COMPANY_ID,
            Shipment.deleted_at.is_(None),
            Shipment.status.in_(["plan_confirmed", "loading", "optimized", "loaded"]),
        )
        .order_by(Shipment.created_at.desc())
        .limit(50)
    )
    shipments = shipment_result.scalars().all()

    report_shipments = []
    total_pallets_count = 0
    vehicle_type_counts = {}

    for sh in shipments:
        # Paletleri çek
        pallet_result = await db.execute(
            select(Pallet)
            .where(Pallet.shipment_id == sh.id)
            .order_by(Pallet.pallet_number)
        )
        pallets = pallet_result.scalars().all()

        # Seçili senaryodaki araç bilgilerini çek
        scenario_result = await db.execute(
            select(Scenario)
            .where(Scenario.shipment_id == sh.id, Scenario.is_selected == True)  # noqa: E712
            .limit(1)
        )
        selected_scenario = scenario_result.scalar_one_or_none()

        # Palet-ürün eşleştirmesi
        pallet_details = []
        for p in pallets:
            products = []
            if p.layout_data and "products" in p.layout_data:
                products = p.layout_data["products"]
            else:
                pp_res = await db.execute(
                    select(PalletProduct).where(PalletProduct.pallet_id == p.id)
                )
                products = [
                    {"name": pp.name, "quantity": pp.quantity,
                     "length_cm": pp.length_cm, "width_cm": pp.width_cm,
                     "height_cm": pp.height_cm, "weight_kg": pp.weight_kg}
                    for pp in pp_res.scalars().all()
                ]

            pallet_details.append({
                "pallet_number": p.pallet_number,
                "pallet_type": p.pallet_type,
                "total_weight_kg": p.total_weight_kg,
                "fill_rate_pct": p.fill_rate_pct,
                "products": products,
            })
            total_pallets_count += 1

        # Araç bilgileri
        vehicles_info = []
        if selected_scenario and selected_scenario.vehicle_assignments:
            for va in selected_scenario.vehicle_assignments:
                v_name = va.get("vehicle_name", "Bilinmiyor")
                vehicle_type_counts[v_name] = vehicle_type_counts.get(v_name, 0) + 1
                vehicles_info.append({
                    "vehicle_name": v_name,
                    "pallet_count": va.get("pallet_count", len(va.get("pallet_ids", []))),
                    "fill_rate_pct": va.get("fill_rate_pct", 0),
                    "cost": va.get("cost", 0),
                })

        # Bağlı siparişleri çek
        order_result = await db.execute(
            select(Order)
            .join(OrderShipment, OrderShipment.order_id == Order.id)
            .where(OrderShipment.shipment_id == sh.id)
        )
        orders = order_result.scalars().all()

        report_shipments.append({
            "shipment_id": sh.id,
            "reference_no": sh.reference_no,
            "status": sh.status,
            "destination": sh.destination,
            "created_at": sh.created_at.isoformat() if sh.created_at else None,
            "pallets": pallet_details,
            "vehicles": vehicles_info,
            "order_count": len(orders),
            "orders": [{"id": o.id, "order_no": o.order_no, "status": o.status} for o in orders],
        })

    return {
        "summary": {
            "total_shipments": len(report_shipments),
            "total_pallets": total_pallets_count,
            "vehicle_type_counts": vehicle_type_counts,
        },
        "shipments": report_shipments,
    }
