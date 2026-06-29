"""
Cronoi LS — Scenarios API
POST /api/v1/scenarios/generate  → 3 senaryo hesapla ve kaydet (ScenarioOptimizer ile)
GET  /api/v1/scenarios/{shipment_id} → Sevkiyatın senaryolarını getir
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.auth import get_current_active_user
from app.models import Shipment, Scenario, User
import asyncio
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class VehicleConfigSchema(BaseModel):
    id: str
    name: str
    type: str
    code: str = ""          # araç tipi kodu (konteyner40 vb.) — allowed_vehicle_types eşleşmesi için

    # Sayısal/None id/code/name/type gelse bile string'e çevir (her istemciye dayanıklı;
    # FE bazen v.id'yi sayı gönderiyordu → 422 "Input should be a valid string")
    @field_validator("id", "name", "type", "code", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return "" if v is None else str(v)
    length_cm: float = 1360
    width_cm: float = 245
    height_cm: float = 270
    max_weight_kg: float = 24000
    pallet_capacity: int = 33
    base_cost: float = 0
    fuel_per_km: float = 0
    driver_per_hour: float = 0
    opportunity_cost: float = 0
    distance_km: float = 500
    duration_hours: float = 8


class EngineParamsSchema(BaseModel):
    heightSafetyMargin: float = 0
    palletGapCm: float = 3
    enforceConstraints: bool = True
    weightBalanceTarget: float = 0.60
    weightBalanceTolerance: float = 0.10
    maxIterations: int = 12
    optimalityTarget: float = 90.0
    # Solver-sınıfı zemin-duyarlı filo araması: süre bütçesi (ms) + kullanılabilir hacim faktörü
    optimizerTimeBudgetMs: int = 3000
    usableVolumeFactorPct: float = 90.0


class PalletInputSchema(BaseModel):
    """Doğrudan payload ile gönderilen palet (prepack: DB'de palet satırı yoktur).
    Footprint + stackable zaten frontend'de hesaplanmış olarak gelir."""
    pallet_number: int
    pallet_type: str = "PP"
    total_weight_kg: float = 0
    total_height_cm: float = 0
    total_volume_m3: float = 0
    fill_rate_pct: float = 100
    constraints: List[str] = Field(default_factory=list)
    footprint_w_cm: float
    footprint_l_cm: float
    phys_height_cm: float = 0       # 0 → total_height_cm
    stackable: bool = True
    source: str = ""


class ScenarioGenerateRequest(BaseModel):
    shipment_id: str
    vehicle_configs: List[VehicleConfigSchema]
    engine_params: Optional[EngineParamsSchema] = None
    # Sipariş araç-tipi kısıtı (allowed_vehicle_types kesişimi). Doluysa SADECE bu tipler
    # değerlendirilir (HARD filtre). Boş = serbest.
    allowed_vehicle_types: List[str] = []
    # Prepack: paletleri doğrudan payload ile gönder (DB'de palet satırı yok). Doluysa
    # DB paletleri yerine bunlar kullanılır (footprint/stackable hazır gelir).
    pallets: Optional[List[PalletInputSchema]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "shipment_id": "uuid-here",
                "vehicle_configs": [{
                    "id": "tir-1", "name": "Tır #1", "type": "tir",
                    "max_weight_kg": 24000, "base_cost": 8000,
                    "fuel_per_km": 5.5, "driver_per_hour": 200,
                    "distance_km": 500, "duration_hours": 8
                }]
            }
        }


@router.post("/generate")
async def generate_scenarios(
    payload: ScenarioGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """3 farklı strateji için senaryo hesapla ve DB'ye kaydet (ScenarioOptimizer ile)."""
    from app.services.optimizer import (
        ScenarioOptimizer, VehicleConfig as OptVehicleConfig,
        OptimizedPallet, OptimizationParams, OptimizerSettings, PALLET_BOARD_HEIGHT_CM,
    )
    from app.models import Pallet, PalletDefinition, OrderShipment, OrderPalletGroup

    # Sevkiyatı kontrol et — sadece kendi firmasının sevkiyatları
    shipment = await db.get(Shipment, payload.shipment_id)
    if not shipment or (not current_user.is_system_admin and shipment.company_id != current_user.company_id):
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # ── PREPACK YOLU: paletler payload'dan gelir (DB'de palet satırı yok) ──────────
    # Footprint + stackable hazır → doğrudan OptimizedPallet kur, footprint çözümü gerekmez.
    if payload.pallets:
        opt_pallets = []
        for ip in payload.pallets:
            opt_pallets.append(OptimizedPallet(
                pallet_number=ip.pallet_number,
                pallet_type=ip.pallet_type or "PP",
                total_weight_kg=ip.total_weight_kg or 0,
                total_height_cm=ip.total_height_cm or 0,
                total_volume_m3=ip.total_volume_m3 or 0,
                fill_rate_pct=ip.fill_rate_pct or 100,
                constraints=ip.constraints or [],
                footprint_w_cm=ip.footprint_w_cm,
                footprint_l_cm=ip.footprint_l_cm,
                phys_height_cm=(ip.phys_height_cm or ip.total_height_cm or 0),
                stackable=bool(ip.stackable),
                source=ip.source or "prepack",
            ))
        if not opt_pallets:
            raise HTTPException(status_code=400, detail="Palet listesi boş")
        return await _run_scenarios(db, payload, shipment, opt_pallets)

    # Paletleri al (normal sipariş — DB'den)
    result = await db.execute(
        select(Pallet).where(Pallet.shipment_id == payload.shipment_id)
    )
    db_pallets = result.scalars().all()
    if not db_pallets:
        raise HTTPException(status_code=400, detail="Bu sevkiyatta palet bulunamadı")

    # ── Palet AYAK İZİ / istif verisi (zemin-duyarlı filo motoru için) ───────────
    # Kaynak önceliği: (1) prepack order_pallet_groups (gerçek boyut + stackable),
    # (2) pallet_definitions (palet tipi boyutu), (3) layout_data bbox (son çare).
    # Footprint çözülemezse motor güvenli legacy greedy'e düşer.
    pdef_rows = (await db.execute(
        select(PalletDefinition).where(PalletDefinition.company_id == shipment.company_id)
    )).scalars().all()
    pdef_by_code = {pd.code: pd for pd in pdef_rows}

    # Sevkiyatın siparişlerindeki prepack palet grupları (pallet_code → grup)
    # NOT: Order'da shipment_id KOLONU YOK — sipariş↔sevkiyat many-to-many (OrderShipment).
    # Bu yüzden order_id'leri association tablosundan al (yanlış kullanım → AttributeError → 500 idi).
    grp_by_code: dict = {}
    order_ids = (await db.execute(
        select(OrderShipment.order_id).where(OrderShipment.shipment_id == payload.shipment_id)
    )).scalars().all()
    if order_ids:
        grp_rows = (await db.execute(
            select(OrderPalletGroup).where(OrderPalletGroup.order_id.in_(order_ids))
        )).scalars().all()
        for g in grp_rows:
            grp_by_code.setdefault(g.pallet_code, g)

    _NO_STACK_CONS = {"no_stack", "fragile", "this_side_up", "vertical", "must_top"}
    # Yerleşik varsayılan palet ayak izleri (pallet_definitions boşken bile footprint çözülsün;
    # optimize ucundaki P1/P5/P10 fallback'i ile aynı → FE render boyutlarıyla tutarlı)
    _DEFAULT_PALLET_DIMS = {
        "P1": (80, 120), "euro": (80, 120), "eur": (80, 120),
        "P5": (100, 120), "standard": (100, 120),
        "P10": (120, 200),
        "half_euro": (60, 80), "P2": (60, 80),
    }

    def _bbox_from_products(p) -> tuple:
        prods = (p.layout_data or {}).get("products") or []
        if not prods:
            return (0.0, 0.0)
        l = max((float(pr.get("pos_x", 0) or 0) + float(pr.get("length_cm", 0) or 0)) for pr in prods)
        w = max((float(pr.get("pos_z", 0) or 0) + float(pr.get("width_cm", 0) or 0)) for pr in prods)
        return (w, l)

    def _footprint_for(p) -> tuple:
        """(w_cm, l_cm, phys_height_cm, stackable, source) — palet için ayak izi çöz."""
        cons = p.constraints or []
        ptype = p.pallet_type or ""
        stack = not any(c in _NO_STACK_CONS for c in cons)
        tare = float(PALLET_BOARD_HEIGHT_CM)
        # 1) Prepack grup (pallet_type == pallet_code) — gerçek boyut + stackable
        g = grp_by_code.get(ptype)
        if g:
            st = bool(g.stackable) and stack
            return (g.width_cm, g.length_cm, p.total_height_cm or g.height_cm or 0, st, "prepack")
        # 2) Palet tipi tanımı (pallet_definitions)
        pd = pdef_by_code.get(ptype)
        if pd:
            return (pd.width_cm, pd.length_cm, (p.total_height_cm or 0) + tare, stack, "")
        # 3) Yerleşik varsayılan palet boyutu (tanım tablosu boş olsa bile)
        dims = _DEFAULT_PALLET_DIMS.get(ptype)
        if dims:
            return (dims[0], dims[1], (p.total_height_cm or 0) + tare, stack, "")
        # 4) layout_data ürün bbox'ı (kargo ölçüsü ≤ palet tabanı; son çare)
        bw, bl = _bbox_from_products(p)
        if bw > 0 and bl > 0:
            return (bw, bl, (p.total_height_cm or 0) + tare, stack, "")
        # 5) En son: yaygın europalet (motor legacy'e düşmesin diye)
        return (80.0, 120.0, (p.total_height_cm or 0) + tare, stack, "")

    # DB paletlerini optimizer formatına çevir
    opt_pallets = []
    for p in db_pallets:
        try:
            fw, fl, phys, stack, src = _footprint_for(p)
        except Exception:   # bozuk tek palet tüm isteği düşürmesin → güvenli europalet
            logger.warning("[Scenarios] footprint çözülemedi palet#%s → varsayılan 80×120",
                           getattr(p, "pallet_number", "?"))
            fw, fl, phys, stack, src = 80.0, 120.0, (p.total_height_cm or 0) + 15.0, True, ""
        opt_pallets.append(OptimizedPallet(
            pallet_number=p.pallet_number,
            pallet_type=p.pallet_type or "P1",
            total_weight_kg=p.total_weight_kg or 0,
            total_height_cm=p.total_height_cm or 0,
            total_volume_m3=p.total_volume_m3 or 0,
            fill_rate_pct=p.fill_rate_pct or 0,
            constraints=p.constraints or [],
            footprint_w_cm=fw, footprint_l_cm=fl, phys_height_cm=phys,
            stackable=stack, source=src,
        ))

    return await _run_scenarios(db, payload, shipment, opt_pallets)


async def _run_scenarios(db, payload, shipment, opt_pallets):
    """_run_scenarios_impl etrafında hata sarmalayıcı: HER istisnayı hem uvicorn konsoluna
    (tam traceback) hem FE'ye (HTTP 500 detail) taşır → 'bare 500' körlüğü biter."""
    try:
        return await _run_scenarios_impl(db, payload, shipment, opt_pallets)
    except HTTPException:
        raise
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        logger.exception("[Scenarios] _run_scenarios çöktü (%d palet)", len(opt_pallets))
        raise HTTPException(status_code=500,
                            detail=f"Senaryo hatası: {type(e).__name__}: {e}")


async def _run_scenarios_impl(db, payload, shipment, opt_pallets):
    """Araç config + ScenarioOptimizer + DB kaydı — hem normal (DB paletleri) hem
    prepack (payload paletleri) yolu bunu çağırır."""
    from app.services.optimizer import (
        ScenarioOptimizer, VehicleConfig as OptVehicleConfig,
        OptimizationParams, OptimizerSettings,
    )

    # ── SİPARİŞ ARAÇ-TİPİ KISITI (HARD FİLTRE + CROSS-CHECK) ──────────────────
    # Sipariş "40'lık konteyner" diyorsa optimizer SADECE konteyner40 değerlendirmeli.
    # Eşleşme: önce code (konteyner40), sonra id/type. İzinli yoksa NET hata (sessizce
    # yanlış araç seçilmesin — kullanıcı talebi: robust, cross-check).
    allowed = {str(a).strip() for a in (payload.allowed_vehicle_types or []) if str(a).strip()}
    vehicle_configs = payload.vehicle_configs
    if allowed:
        def _vc_allowed(vc) -> bool:
            return (vc.code and vc.code in allowed) or (vc.id in allowed) or (vc.type in allowed)
        filtered = [vc for vc in vehicle_configs if _vc_allowed(vc)]
        if not filtered:
            raise HTTPException(
                status_code=400,
                detail=("Sipariş araç-tipi kısıtı (" + ", ".join(sorted(allowed)) +
                        ") için filoda uygun araç tanımı yok. Araçlar ekranından bu tipi ekleyin."),
            )
        logger.info("[Scenarios] Araç kısıtı uygulandı: %d→%d araç (izinli: %s)",
                    len(vehicle_configs), len(filtered), ", ".join(sorted(allowed)))
        vehicle_configs = filtered

    # Araç tanımlarını optimizer formatına çevir
    opt_vehicles = []
    for vc in vehicle_configs:
        opt_vehicles.append(OptVehicleConfig(
            id=vc.id, name=vc.name, type=vc.type,
            length_cm=vc.length_cm, width_cm=vc.width_cm, height_cm=vc.height_cm,
            max_weight_kg=vc.max_weight_kg,
            pallet_capacity=vc.pallet_capacity,
            base_cost=vc.base_cost, fuel_per_km=vc.fuel_per_km,
            driver_per_hour=vc.driver_per_hour, opportunity_cost=vc.opportunity_cost,
            distance_km=vc.distance_km, duration_hours=vc.duration_hours,
        ))

    if not opt_vehicles:
        raise HTTPException(status_code=400, detail="En az 1 araç tanımı gerekli")

    # Optimizasyon parametreleri (+ solver süre bütçesi settings üzerinden akar)
    engine_dict = payload.engine_params.model_dump() if payload.engine_params else {}
    opt_params = OptimizationParams.from_dict(engine_dict)
    opt_settings = OptimizerSettings.from_dict(engine_dict)

    # ScenarioOptimizer ile 3 senaryo üret (footprint varsa zemin-duyarlı ALNS, yoksa legacy)
    optimizer = ScenarioOptimizer(opt_pallets, opt_vehicles, params=opt_params, settings=opt_settings)
    try:
        # KRİTİK: ALNS CPU-yoğun (saniyeler) → AYRI THREAD'de çalıştır (asyncio.to_thread).
        # Aksi halde async event loop'u bloklar; asyncpg bağlantısı/commit bozulur → canlı istekte
        # 500 (offline tek-task'ta görünmez). Bu sayede motor "arka planda" çalışır, sunucu responsive
        # kalır ve diğer istekler/DB sağlıklı sürer.
        scenarios_result = await asyncio.to_thread(optimizer.generate_all)
    except Exception as e:   # gerçek hatayı hem konsola (traceback) hem FE'ye (detail) ver
        logger.exception("[Scenarios] generate_all çöktü (%d palet, %d araç)",
                         len(opt_pallets), len(opt_vehicles))
        raise HTTPException(status_code=500, detail=f"Senaryo motoru hatası: {type(e).__name__}: {e}")

    # Sonuçları DB formatına çevir ve kaydet
    saved = []
    for sr in scenarios_result:
        vehicle_assignments = []
        for va in sr.vehicles:
            vehicle_assignments.append({
                "vehicle_id":       va.vehicle.id,
                "vehicle_name":     va.vehicle.name,
                "vehicle_type":     va.vehicle.type,
                "length_cm":        va.vehicle.length_cm,
                "width_cm":         va.vehicle.width_cm,
                "height_cm":        va.vehicle.height_cm,
                "max_weight_kg":    va.vehicle.max_weight_kg,
                "pallet_capacity":  va.vehicle.pallet_capacity,
                "pallet_ids":       va.pallet_ids,
                "pallet_count":     len(va.pallet_ids),
                "current_weight_kg": round(va.current_weight_kg, 2),
                "current_volume_m3": round(va.current_volume_m3, 4),
                "vehicle_volume_m3": round(va.vehicle.volume_m3, 4),
                "fill_rate_pct":    round(va.vol_utilization_pct, 1),
                "weight_fill_pct":  round(va.weight_utilization_pct, 1),
                "cost":             round(va.cost, 2),
                "front_weight_kg":  va.front_weight_kg,
                "rear_weight_kg":   va.rear_weight_kg,
                "front_pct":        va.front_pct,
                "balance_ok":       va.balance_ok,
                "stacked_pairs":    va.stacked_pairs if hasattr(va, 'stacked_pairs') else [],
                "used_len_cm":      round(getattr(va, "used_len_cm", 0.0), 1),
                "ldm":              getattr(va, "ldm", 0.0),
                "ldm_fill_pct":     getattr(va, "ldm_fill_pct", 0.0),
            })

        scenario_data = {
            "id":                  str(uuid4()),
            "name":                sr.name,
            "strategy":            sr.strategy.value,
            "total_cost":          round(sr.total_cost, 2),
            "cost_per_pallet":     round(sr.cost_per_pallet, 2),
            "total_vehicles":      sr.total_vehicles,
            "avg_fill_rate_pct":   round(sr.avg_fill_rate_pct, 1),
            "avg_balance_pct":     sr.avg_balance_pct,
            "is_recommended":      sr.is_recommended,
            "vehicle_assignments": vehicle_assignments,
            # Solver metadata: alt-sınır, kanıtlanmış optimum, motor, iterasyon sayısı
            "lower_bound":         getattr(sr, "lower_bound", 0),
            "proven_optimal":      getattr(sr, "proven_optimal", False),
            "engine":              getattr(sr, "engine", "binding-greedy"),
            "vehicle_type_id":     getattr(sr, "vehicle_type_id", ""),
            "iterations":          getattr(sr, "iterations", 0),
        }

        scenario = Scenario(
            id=scenario_data["id"],
            shipment_id=payload.shipment_id,
            name=sr.name,
            strategy=sr.strategy.value,
            total_cost=sr.total_cost,
            cost_per_pallet=sr.cost_per_pallet,
            total_vehicles=sr.total_vehicles,
            avg_fill_rate_pct=sr.avg_fill_rate_pct,
            is_recommended=sr.is_recommended,
            is_selected=sr.is_recommended,
            vehicle_assignments=vehicle_assignments,
        )
        db.add(scenario)
        saved.append(scenario_data)

    await db.commit()
    return {"scenarios": saved}


class ScenarioSaveRequest(BaseModel):
    name: str = "Araç Planı"
    strategy: str = "manual"
    total_cost: float = 0
    cost_per_pallet: float = 0
    total_vehicles: int = 0
    avg_fill_rate_pct: float = 0
    vehicle_assignments: list = Field(default_factory=list)


@router.post("/{shipment_id}/save")
async def save_scenario_from_frontend(
    shipment_id: str,
    payload: ScenarioSaveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Frontend'den gelen senaryo verisini DB'ye kaydet (local optimizasyon sonucu)."""
    shipment = await db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # Aynı sevkiyat için önceki senaryoları kaldır (seçili değil yap)
    await db.execute(
        update(Scenario)
        .where(Scenario.shipment_id == shipment_id)
        .values(is_selected=False)
    )

    scenario_id = str(uuid4())
    scenario = Scenario(
        id=scenario_id,
        shipment_id=shipment_id,
        name=payload.name,
        strategy=payload.strategy,
        total_cost=payload.total_cost,
        cost_per_pallet=payload.cost_per_pallet,
        total_vehicles=payload.total_vehicles or len(payload.vehicle_assignments),
        avg_fill_rate_pct=payload.avg_fill_rate_pct,
        is_recommended=True,
        is_selected=True,
        vehicle_assignments=payload.vehicle_assignments,
    )
    db.add(scenario)
    await db.commit()
    return {"id": scenario_id, "saved": True}


@router.patch("/{scenario_id}/select")
async def select_scenario(
    scenario_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Bir senaryoyu seçili olarak işaretle (aynı sevkiyattaki diğerlerini kaldır)."""
    try:
        scenario = await db.get(Scenario, scenario_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz senaryo ID")
    if not scenario:
        raise HTTPException(status_code=404, detail="Senaryo bulunamadı")
    # Aynı sevkiyattaki diğer senaryoları kaldır
    await db.execute(
        update(Scenario)
        .where(Scenario.shipment_id == scenario.shipment_id)
        .values(is_selected=False)
    )
    scenario.is_selected = True
    await db.commit()
    return {"id": scenario.id, "is_selected": True}


@router.get("/{shipment_id}")
async def get_scenarios(
    shipment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # Tenant isolation check
    shipment = await db.get(Shipment, shipment_id)
    if not shipment or (not current_user.is_system_admin and shipment.company_id != current_user.company_id):
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    result = await db.execute(
        select(Scenario)
        .where(Scenario.shipment_id == shipment_id)
        .order_by(Scenario.total_cost)
    )
    scenarios = result.scalars().all()
    return [
        {
            "id":                 s.id,
            "name":               s.name,
            "strategy":           s.strategy,
            "total_cost":         s.total_cost,
            "cost_per_pallet":    s.cost_per_pallet,
            "total_vehicles":     s.total_vehicles,
            "avg_fill_rate_pct":  s.avg_fill_rate_pct,
            "is_recommended":     s.is_recommended,
            "vehicle_assignments": s.vehicle_assignments,
        }
        for s in scenarios
    ]
