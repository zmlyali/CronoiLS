"""
Cronoi LS — Shipments API
POST   /api/v1/shipments              → Yeni sevkiyat oluştur
GET    /api/v1/shipments              → Şirketin sevkiyatlarını listele
GET    /api/v1/shipments/{id}         → Sevkiyat detayı
PUT    /api/v1/shipments/{id}         → Güncelle
DELETE /api/v1/shipments/{id}         → Soft delete
POST   /api/v1/shipments/{id}/optimize → Bin packing çalıştır (async)
GET    /api/v1/shipments/{id}/status  → Optimizasyon durumu
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

router = APIRouter()


# ============================================================
# Pydantic Schemas
# ============================================================

class PalletTypeEnum(str, Enum):
    euro = "euro"
    standard = "standard"
    uk = "uk"
    custom = "custom"


class ConstraintEnum(str, Enum):
    fragile = "fragile"
    heavy = "heavy"
    temp = "temp"


class ProductInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(..., ge=1, le=10000)
    length_cm: float = Field(..., gt=0, le=1000)
    width_cm: float = Field(..., gt=0, le=1000)
    height_cm: float = Field(..., gt=0, le=500)
    weight_kg: float = Field(..., gt=0, le=5000)
    constraint: Optional[ConstraintEnum] = None
    catalog_id: Optional[UUID] = None  # Katalogdan seçilmişse


class ShipmentCreate(BaseModel):
    reference_no: Optional[str] = None  # Boş bırakılırsa otomatik: SEV-2026-0001
    pallet_type: PalletTypeEnum = PalletTypeEnum.euro
    destination: Optional[str] = None
    notes: Optional[str] = None
    products: List[ProductInput] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "pallet_type": "euro",
                "destination": "İzmir, TR",
                "products": [
                    {
                        "name": "Koltuk Takımı 3+2+1",
                        "quantity": 10,
                        "length_cm": 200,
                        "width_cm": 100,
                        "height_cm": 80,
                        "weight_kg": 85,
                        "constraint": None
                    },
                    {
                        "name": "Yemek Masası",
                        "quantity": 5,
                        "length_cm": 180,
                        "width_cm": 90,
                        "height_cm": 75,
                        "weight_kg": 45,
                        "constraint": "fragile"
                    }
                ]
            }
        }


class ShipmentSummary(BaseModel):
    id: UUID
    reference_no: str
    status: str
    pallet_type: str
    destination: Optional[str]
    total_pallets: Optional[int]
    created_at: datetime
    optimized_at: Optional[datetime]

    class Config:
        from_attributes = True


class OptimizeRequest(BaseModel):
    vehicle_ids: List[UUID] = Field(..., min_length=1)
    distance_km: float = Field(default=500, gt=0)
    duration_hours: float = Field(default=8, gt=0)


class OptimizationStatus(BaseModel):
    shipment_id: UUID
    status: str  # "pending" | "running" | "done" | "failed"
    progress_pct: int = 0
    message: str = ""
    result_summary: Optional[dict] = None


# ============================================================
# Bağımlılıklar (gerçek implementasyonda DB session eklenecek)
# ============================================================

def get_current_company_id() -> UUID:
    """JWT token'dan company_id çıkar — middleware ile gelir"""
    pass  # Gerçek implementasyonda auth middleware


# ============================================================
# Endpoints
# ============================================================

@router.post("", response_model=ShipmentSummary, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    payload: ShipmentCreate,
    background_tasks: BackgroundTasks,
    # db: AsyncSession = Depends(get_db),
    # current_user = Depends(get_current_user),
):
    """
    Yeni sevkiyat oluştur.
    
    - Ürün listesini kaydet
    - reference_no otomatik üretilir (SEV-YYYY-NNNN)
    - Optimizasyonu arka planda başlat (Celery)
    """
    # TODO: DB'ye kayıt
    # shipment = Shipment(
    #     company_id=current_user.company_id,
    #     created_by=current_user.id,
    #     pallet_type=payload.pallet_type,
    #     destination=payload.destination,
    #     notes=payload.notes,
    # )
    # db.add(shipment)
    # await db.flush()
    
    # for product in payload.products:
    #     sp = ShipmentProduct(shipment_id=shipment.id, **product.dict())
    #     db.add(sp)
    
    # await db.commit()
    
    # Arka planda optimizasyon başlat
    # background_tasks.add_task(run_optimization_task, shipment.id)
    
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "reference_no": "SEV-2026-0001",
        "status": "optimizing",
        "pallet_type": payload.pallet_type,
        "destination": payload.destination,
        "total_pallets": None,
        "created_at": datetime.utcnow(),
        "optimized_at": None,
    }


@router.get("", response_model=List[ShipmentSummary])
async def list_shipments(
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
):
    """
    Şirkete ait sevkiyatları listele.
    Filtre: status, tarih aralığı, sayfalama
    """
    # TODO: DB sorgusu
    # query = select(Shipment).where(
    #     Shipment.company_id == current_user.company_id,
    #     Shipment.deleted_at.is_(None)
    # )
    # if status:
    #     query = query.where(Shipment.status == status)
    # query = query.order_by(Shipment.created_at.desc()).limit(limit).offset(offset)
    return []


@router.get("/{shipment_id}", response_model=dict)
async def get_shipment(shipment_id: UUID):
    """
    Sevkiyat detayı:
    - Ürün listesi
    - Oluşturulan paletler (accordion için)
    - Seçilen senaryo
    - Yükleme planı
    """
    # TODO: JOIN ile tam detay
    raise HTTPException(status_code=404, detail="Shipment not found")


@router.post("/{shipment_id}/optimize", response_model=OptimizationStatus)
async def optimize_shipment(
    shipment_id: UUID,
    payload: OptimizeRequest,
    background_tasks: BackgroundTasks,
):
    """
    3D Bin Packing optimizasyonunu başlat.
    
    İşlem Celery worker'da arka planda çalışır.
    Sonucu polling veya WebSocket ile takip et:
    GET /api/v1/shipments/{id}/status
    
    Adımlar:
    1. Ürünleri al
    2. BinPackingOptimizer3D çalıştır (OR-Tools)
    3. Paletleri DB'ye kaydet
    4. ScenarioOptimizer çalıştır
    5. Senaryoları DB'ye kaydet
    6. Loading plan oluştur
    7. Status → "done"
    """
    # background_tasks.add_task(
    #     celery_optimize.delay, str(shipment_id), payload.dict()
    # )
    
    return OptimizationStatus(
        shipment_id=shipment_id,
        status="pending",
        progress_pct=0,
        message="Optimizasyon kuyruğa alındı..."
    )


@router.get("/{shipment_id}/status", response_model=OptimizationStatus)
async def get_optimization_status(shipment_id: UUID):
    """
    Optimizasyon durumunu sorgula (frontend polling için).
    WebSocket alternatifi: /ws/shipments/{id}
    """
    # TODO: Redis'ten status oku
    # status = await redis.get(f"opt:status:{shipment_id}")
    return OptimizationStatus(
        shipment_id=shipment_id,
        status="done",
        progress_pct=100,
        message="Optimizasyon tamamlandı",
        result_summary={
            "total_pallets": 8,
            "avg_fill_rate": 73.5,
            "best_scenario_cost": 14850
        }
    )


@router.delete("/{shipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shipment(shipment_id: UUID):
    """Soft delete — veri silinmez, arşivlenir"""
    # await db.execute(
    #     update(Shipment)
    #     .where(Shipment.id == shipment_id)
    #     .values(deleted_at=datetime.utcnow())
    # )
    pass
