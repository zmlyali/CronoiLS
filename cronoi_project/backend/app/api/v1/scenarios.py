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
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from app.core.database import get_db
from app.models import Shipment, Scenario

router = APIRouter()


class VehicleConfigSchema(BaseModel):
    id: str
    name: str
    type: str
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


class ScenarioGenerateRequest(BaseModel):
    shipment_id: str
    vehicle_configs: List[VehicleConfigSchema]
    engine_params: Optional[EngineParamsSchema] = None

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
):
    """3 farklı strateji için senaryo hesapla ve DB'ye kaydet (ScenarioOptimizer ile)."""
    from app.services.optimizer import (
        ScenarioOptimizer, VehicleConfig as OptVehicleConfig,
        OptimizedPallet, OptimizationParams, PALLET_BOARD_HEIGHT_CM,
    )
    from app.models import Pallet

    # Sevkiyatı kontrol et
    shipment = await db.get(Shipment, payload.shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Sevkiyat bulunamadı")

    # Paletleri al
    result = await db.execute(
        select(Pallet).where(Pallet.shipment_id == payload.shipment_id)
    )
    db_pallets = result.scalars().all()
    if not db_pallets:
        raise HTTPException(status_code=400, detail="Bu sevkiyatta palet bulunamadı")

    # DB paletlerini optimizer formatına çevir
    opt_pallets = []
    for p in db_pallets:
        opt_pallets.append(OptimizedPallet(
            pallet_number=p.pallet_number,
            pallet_type=p.pallet_type or "P1",
            total_weight_kg=p.total_weight_kg or 0,
            total_height_cm=p.total_height_cm or 0,
            total_volume_m3=p.total_volume_m3 or 0,
            fill_rate_pct=p.fill_rate_pct or 0,
            constraints=p.constraints or [],
        ))

    # Araç tanımlarını optimizer formatına çevir
    opt_vehicles = []
    for vc in payload.vehicle_configs:
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

    # Optimizasyon parametreleri
    opt_params = OptimizationParams.from_dict(
        payload.engine_params.model_dump() if payload.engine_params else {}
    )

    # ScenarioOptimizer ile 3 senaryo üret
    optimizer = ScenarioOptimizer(opt_pallets, opt_vehicles, params=opt_params)
    scenarios_result = optimizer.generate_all()

    # Sonuçları DB formatına çevir ve kaydet
    saved = []
    for sr in scenarios_result:
        vehicle_assignments = []
        for va in sr.vehicles:
            vehicle_assignments.append({
                "vehicle_id":       va.vehicle.id,
                "vehicle_name":     va.vehicle.name,
                "vehicle_type":     va.vehicle.type,
                "pallet_ids":       va.pallet_ids,
                "pallet_count":     len(va.pallet_ids),
                "current_weight_kg": round(va.current_weight_kg, 2),
                "current_volume_m3": round(va.current_volume_m3, 4),
                "fill_rate_pct":    round(va.current_weight_kg / va.vehicle.max_weight_kg * 100, 1) if va.vehicle.max_weight_kg else 0,
                "cost":             round(va.cost, 2),
                "front_weight_kg":  va.front_weight_kg,
                "rear_weight_kg":   va.rear_weight_kg,
                "front_pct":        va.front_pct,
                "balance_ok":       va.balance_ok,
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
):
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
