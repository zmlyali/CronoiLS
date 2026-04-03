"""
Cronoi LS — Orders API (DB destekli)
POST   /api/v1/orders                    → Yeni sipariş
GET    /api/v1/orders                    → Liste (filtreli)
GET    /api/v1/orders/{id}               → Detay
PUT    /api/v1/orders/{id}               → Sipariş güncelle (meta + ürünler)
PATCH  /api/v1/orders/{id}/status        → Durum güncelle
DELETE /api/v1/orders/{id}               → Soft delete
POST   /api/v1/orders/group-suggestions  → Gruplama önerileri
POST   /api/v1/orders/bulk               → Excel'den toplu import
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from collections import defaultdict

from app.core.database import get_db
from app.models import Order, OrderItem, OrderShipment, Company, User

router = APIRouter()

DEMO_COMPANY_ID = "00000000-0000-0000-0000-000000000001"
DEMO_USER_ID    = "00000000-0000-0000-0000-000000000002"


# ── Schemas ────────────────────────────────────────────────

class OrderItemInput(BaseModel):
    name:        str
    sku:         Optional[str] = None
    quantity:    int = Field(ge=1)
    length_cm:   float
    width_cm:    float
    height_cm:   float
    weight_kg:   float
    constraints: List[dict] = []


class OrderCreate(BaseModel):
    order_no:            str
    project_code:        Optional[str] = None
    customer_name:       str
    address:             Optional[str] = None
    city:                Optional[str] = None
    postal_code:         Optional[str] = None
    country:             str = "TR"
    contact_name:        Optional[str] = None
    contact_phone:       Optional[str] = None
    contact_email:       Optional[str] = None
    order_date:          Optional[str] = None
    requested_ship_date: Optional[str] = None
    deadline_date:       Optional[str] = None
    priority:            int = 3
    notes:               Optional[str] = None
    items:               List[OrderItemInput] = []

    class Config:
        json_schema_extra = {
            "example": {
                "order_no": "SIP-2026-001",
                "project_code": "PRJ-001",
                "customer_name": "ABC Mobilya A.Ş.",
                "city": "İzmir",
                "postal_code": "35000",
                "requested_ship_date": "2026-03-28",
                "priority": 2,
                "items": [
                    {"name": "Koltuk Takımı", "quantity": 5,
                     "length_cm": 200, "width_cm": 100, "height_cm": 80,
                     "weight_kg": 85, "constraints": []},
                    {"name": "Yemek Masası", "quantity": 3,
                     "length_cm": 180, "width_cm": 90, "height_cm": 75,
                     "weight_kg": 45,
                     "constraints": [{"code": "fragile", "params": {}}]}
                ]
            }
        }


class BulkOrderItem(BaseModel):
    """Excel satırından gelen tek bir kalem"""
    order_no:            str
    project_code:        Optional[str] = None
    customer_name:       Optional[str] = None
    city:                Optional[str] = None
    country:             Optional[str] = "TR"
    postal_code:         Optional[str] = None
    address:             Optional[str] = None
    contact_name:        Optional[str] = None
    contact_phone:       Optional[str] = None
    order_date:          Optional[str] = None
    requested_ship_date: Optional[str] = None
    deadline_date:       Optional[str] = None
    priority:            int = 3
    product_name:        str
    sku:                 Optional[str] = None
    quantity:            int = 1
    dimensions:          Optional[str] = None   # "120x80x60" (eski format — geriye uyum)
    length_cm:           Optional[float] = None
    width_cm:            Optional[float] = None
    height_cm:           Optional[float] = None
    weight_kg:           float = 0
    constraint_code:     Optional[str] = None


# CRONOI_LS_STATUS_MODEL.md v2 — kanonik sipariş statüleri
VALID_ORDER_STATUSES = [
    # Kanonik
    "pending", "in_shipment", "pallet_planned", "vehicle_planned",
    "loaded", "delivered", "in_suggestion", "cancelled",
    # Geriye dönük uyum (eski isimler)
    "planned", "load_planned", "loading_planned", "in_transit",
]
ORDER_TRANSITIONS = {
    # Kanonik geçişler
    "pending":          ["in_shipment", "in_suggestion", "pallet_planned", "vehicle_planned", "cancelled"],
    "in_suggestion":    ["in_shipment", "pallet_planned", "pending"],
    "in_shipment":      ["pallet_planned", "vehicle_planned", "pending", "cancelled"],      # plandan silindi → pending
    "pallet_planned":   ["vehicle_planned", "pending", "cancelled"],
    "vehicle_planned":  ["loaded", "pending", "cancelled"],
    "loaded":           ["delivered"],
    "delivered":        [],
    "cancelled":        [],
    # Geriye dönük uyum
    "planned":          ["pallet_planned", "loading_planned", "pending", "cancelled"],
    "load_planned":     ["vehicle_planned", "loaded", "pending"],
    "loading_planned":  ["loaded", "planned"],
    "in_transit":       ["delivered"],
}

class OrderItemUpdate(BaseModel):
    """Güncelleme için ürün kalemi — id varsa mevcut kalem güncellenir, yoksa yeni eklenir"""
    id:          Optional[str] = None   # Mevcutsa güncelleme, None ise yeni kalem
    name:        str
    sku:         Optional[str] = None
    quantity:    int = Field(ge=1)
    length_cm:   float
    width_cm:    float
    height_cm:   float
    weight_kg:   float
    constraints: List[dict] = []


class OrderUpdate(BaseModel):
    """Sipariş güncelleme — tüm alanlar opsiyonel"""
    order_no:            Optional[str] = None
    project_code:        Optional[str] = None
    customer_name:       Optional[str] = None
    address:             Optional[str] = None
    city:                Optional[str] = None
    postal_code:         Optional[str] = None
    country:             Optional[str] = None
    contact_name:        Optional[str] = None
    contact_phone:       Optional[str] = None
    contact_email:       Optional[str] = None
    order_date:          Optional[str] = None
    requested_ship_date: Optional[str] = None
    deadline_date:       Optional[str] = None
    priority:            Optional[int] = None
    notes:               Optional[str] = None
    items:               Optional[List[OrderItemUpdate]] = None  # None = dokunma, [] = hepsini sil


class OrderStatusUpdate(BaseModel):
    status: str


# ── Yardımcı ───────────────────────────────────────────────

def _order_to_dict(order: Order, shipment_ref: str = None) -> dict:
    # shipment_links üzerinden referans ve id varsa onu kullan
    shipment_id = None
    if shipment_ref is None:
        try:
            links = order.shipment_links
            if links:
                link = links[-1]
                if hasattr(link, 'shipment') and link.shipment:
                    shipment_ref = link.shipment.reference_no
                    shipment_id = str(link.shipment_id)
                else:
                    shipment_id = str(link.shipment_id)
        except Exception:
            pass  # Lazy load yapılamadıysa None kalır
    return {
        "id":                   order.id,
        "order_no":             order.order_no,
        "project_code":         order.project_code,
        "customer_name":        order.customer_name,
        "city":                 order.city,
        "postal_code":          order.postal_code,
        "address":              order.address,
        "contact_name":         order.contact_name,
        "contact_phone":        order.contact_phone,
        "requested_ship_date":  order.requested_ship_date,
        "deadline_date":        order.deadline_date,
        "priority":             order.priority,
        "notes":                order.notes,
        "status":               order.status,
        "shipment_ref":         shipment_ref,
        "shipment_id":          shipment_id,
        "created_at":           order.created_at.isoformat() if order.created_at else None,
        "deleted_at":           order.deleted_at.isoformat() if order.deleted_at else None,
        "items": [
            {
                "id":          i.id,
                "name":        i.name,
                "sku":         i.sku,
                "quantity":    i.quantity,
                "length_cm":   i.length_cm,
                "width_cm":    i.width_cm,
                "height_cm":   i.height_cm,
                "weight_kg":   i.weight_kg,
                "constraints": i.constraints,
            }
            for i in (order.items or [])
        ],
    }


def _get_week(date_str: str) -> str:
    """Tarihi ISO hafta dizisine çevir: 2026-W13"""
    if not date_str:
        return "no-date"
    try:
        from datetime import date
        d = date.fromisoformat(date_str)
        return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
    except Exception:
        return "no-date"


# ── Endpoints ───────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
):
    order = Order(
        id=str(uuid4()),
        company_id=DEMO_COMPANY_ID,
        created_by=DEMO_USER_ID,
        order_no=payload.order_no,
        project_code=payload.project_code,
        customer_name=payload.customer_name,
        address=payload.address,
        city=payload.city,
        postal_code=payload.postal_code,
        country=payload.country,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        order_date=payload.order_date or datetime.now().date().isoformat(),
        requested_ship_date=payload.requested_ship_date,
        deadline_date=payload.deadline_date,
        priority=payload.priority,
        notes=payload.notes,
        status="pending",
    )
    db.add(order)
    await db.flush()

    for i, item in enumerate(payload.items):
        db.add(OrderItem(
            id=str(uuid4()),
            order_id=order.id,
            name=item.name,
            sku=item.sku,
            quantity=item.quantity,
            length_cm=item.length_cm,
            width_cm=item.width_cm,
            height_cm=item.height_cm,
            weight_kg=item.weight_kg,
            constraints=item.constraints,
            sort_order=i,
        ))

    await db.commit()

    # Items ile birlikte yeniden çek
    result = await db.execute(
        select(Order).where(Order.id == order.id)
    )
    order = result.scalar_one()
    # eager load items
    from sqlalchemy.orm import selectinload
    result2 = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order.id)
    )
    order = result2.scalar_one()
    return _order_to_dict(order)


@router.get("")
async def list_orders(
    status: Optional[str] = None,
    city: Optional[str] = None,
    week: Optional[str] = None,   # örn: 2026-W13
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    q = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.shipment_links).selectinload(OrderShipment.shipment),
    ).where(
        Order.company_id == DEMO_COMPANY_ID,
    ).order_by(Order.priority, Order.requested_ship_date)

    if include_deleted:
        # Sadece silinenleri getir
        q = q.where(Order.deleted_at.isnot(None))
    else:
        q = q.where(Order.deleted_at.is_(None))

    if status:
        q = q.where(Order.status == status)
    if city:
        q = q.where(Order.city.ilike(f"%{city}%"))

    result = await db.execute(q)
    orders = result.scalars().all()

    data = [_order_to_dict(o) for o in orders]
    if week:
        data = [o for o in data if _get_week(o.get("requested_ship_date", "")) == week]
    return data


@router.post("/group-suggestions")
async def group_suggestions(
    db: AsyncSession = Depends(get_db),
):
    """
    Bekleyen siparişleri analiz eder, şehir+hafta bazında gruplar önerir.
    Her grup = potansiyel tek sevkiyat.
    """
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(
            Order.company_id == DEMO_COMPANY_ID,
            Order.status == "pending",
            Order.deleted_at.is_(None),
        ).order_by(Order.requested_ship_date)
    )
    orders = result.scalars().all()

    if not orders:
        return {"groups": [], "ungrouped": []}

    # Gruplama: şehir normalize + hafta
    groups: dict = defaultdict(list)
    for o in orders:
        city  = (o.city or "Belirtilmemiş").strip().title()
        week  = _get_week(o.requested_ship_date)
        key   = f"{city}|{week}"
        groups[key].append(o)

    suggestions = []
    for key, group_orders in groups.items():
        city, week = key.split("|")
        all_items = [i for o in group_orders for i in o.items]
        total_weight = sum(i.weight_kg * i.quantity for i in all_items)
        total_volume = sum(
            (i.length_cm * i.width_cm * i.height_cm * i.quantity) / 1_000_000
            for i in all_items
        )
        # TIR kapasitesi: ~80 m³, 24 ton
        tir_vol  = 13.6 * 2.45 * 2.7  # ≈ 90 m³
        tir_kg   = 24000
        fits_one = total_volume <= tir_vol * 0.85 and total_weight <= tir_kg * 0.9

        suggestions.append({
            "group_key":       key,
            "city":            city,
            "week":            week,
            "order_count":     len(group_orders),
            "total_items":     sum(i.quantity for i in all_items),
            "total_weight_kg": round(total_weight, 1),
            "total_volume_m3": round(total_volume, 3),
            "fits_one_tir":    fits_one,
            "estimated_trucks": 1 if fits_one else max(1, round(total_volume / (tir_vol * 0.8))),
            "orders": [_order_to_dict(o) for o in group_orders],
            "priority_min":    min(o.priority for o in group_orders),
            "has_urgent":      any(o.priority <= 2 for o in group_orders),
        })

    # Önce acil, sonra tarihe göre sırala
    suggestions.sort(key=lambda g: (not g["has_urgent"], g["week"], g["city"]))
    return {"groups": suggestions}


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_import(
    rows: List[BulkOrderItem],
    db: AsyncSession = Depends(get_db),
):
    """
    Excel'den parse edilmiş satırları toplu olarak sipariş olarak kaydet.
    Aynı order_no olan satırlar tek siparişe birleştirilir.
    """
    # order_no bazında grupla
    order_map: dict = {}
    for row in rows:
        if row.order_no not in order_map:
            order_map[row.order_no] = {
                "meta": row,
                "items": [],
            }
        # Boyutları parse et — önce ayrı alanlar, yoksa dimensions string'i
        lc = row.length_cm or 0
        wc = row.width_cm or 0
        hc = row.height_cm or 0
        if not (lc and wc and hc) and row.dimensions:
            parts = [p.strip() for p in row.dimensions.replace("×","x").split("x")]
            if len(parts) >= 3:
                try:
                    lc, wc, hc = float(parts[0]), float(parts[1]), float(parts[2])
                except ValueError:
                    pass
        if not lc: lc = 100.0
        if not wc: wc = 100.0
        if not hc: hc = 100.0
        constraints = []
        if row.constraint_code and row.constraint_code.strip():
            for code in row.constraint_code.split(","):
                code = code.strip()
                if code:
                    constraints.append({"code": code, "params": {}})

        order_map[row.order_no]["items"].append({
            "name":        row.product_name,
            "sku":         row.sku,
            "quantity":    row.quantity,
            "length_cm":   lc,
            "width_cm":    wc,
            "height_cm":   hc,
            "weight_kg":   row.weight_kg,
            "constraints": constraints,
        })

    saved = []
    for order_no, data in order_map.items():
        meta = data["meta"]
        order = Order(
            id=str(uuid4()),
            company_id=DEMO_COMPANY_ID,
            created_by=DEMO_USER_ID,
            order_no=order_no,
            project_code=meta.project_code,
            customer_name=meta.customer_name or "",
            city=meta.city,
            postal_code=meta.postal_code,
            address=meta.address,
            contact_name=meta.contact_name,
            contact_phone=meta.contact_phone,
            country=meta.country or "TR",
            order_date=meta.order_date or datetime.now().date().isoformat(),
            requested_ship_date=meta.requested_ship_date,
            deadline_date=meta.deadline_date,
            priority=meta.priority,
            status="pending",
        )
        db.add(order)
        await db.flush()

        for i, item in enumerate(data["items"]):
            db.add(OrderItem(
                id=str(uuid4()),
                order_id=order.id,
                name=item["name"],
                sku=item.get("sku"),
                quantity=item["quantity"],
                length_cm=item["length_cm"],
                width_cm=item["width_cm"],
                height_cm=item["height_cm"],
                weight_kg=item["weight_kg"],
                constraints=item["constraints"],
                sort_order=i,
            ))
        saved.append(order_no)

    await db.commit()
    return {"imported": len(saved), "order_nos": saved}


@router.get("/{order_id}")
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Order).options(
            selectinload(Order.items),
            selectinload(Order.shipment_links).selectinload(OrderShipment.shipment),
        ).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order or order.deleted_at:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı")
    return _order_to_dict(order)


@router.put("/{order_id}")
async def update_order(
    order_id: str,
    payload: OrderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Siparişi güncelle — meta bilgiler + ürün kalemleri.
    Sadece pending/in_shipment durumundaki siparişler düzenlenebilir.
    items gönderilirse mevcut kalemler değiştirilir:
      - id'li kalem → güncelleme
      - id'siz kalem → yeni ekleme
      - payload'da olmayan mevcut kalem → silme
    """
    from sqlalchemy.orm import selectinload
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order or order.deleted_at:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı")

    # Sadece düzenlenebilir durumlarda izin ver
    editable_statuses = ["pending", "in_shipment"]
    if order.status not in editable_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Sipariş '{order.status}' durumunda, düzenleme için '{', '.join(editable_statuses)}' durumunda olmalı."
        )

    # ── Meta alanları güncelle (sadece gönderilenleri) ──
    meta_fields = [
        "order_no", "project_code", "customer_name", "address", "city",
        "postal_code", "country", "contact_name", "contact_phone",
        "contact_email", "order_date", "requested_ship_date",
        "deadline_date", "priority", "notes",
    ]
    for field in meta_fields:
        value = getattr(payload, field, None)
        if value is not None:
            setattr(order, field, value)

    order.updated_at = datetime.now(timezone.utc)

    # ── Ürün kalemleri güncelle ──
    if payload.items is not None:
        existing_ids = {str(item.id) for item in order.items}
        incoming_ids = {item.id for item in payload.items if item.id}

        # Silinecek kalemler: DB'de var ama payload'da yok
        ids_to_delete = existing_ids - incoming_ids
        if ids_to_delete:
            await db.execute(
                sa_delete(OrderItem).where(OrderItem.id.in_(ids_to_delete))
            )

        # Güncelle veya ekle
        for i, item_data in enumerate(payload.items):
            if item_data.id and item_data.id in existing_ids:
                # Mevcut kalemi güncelle
                existing_item = await db.get(OrderItem, item_data.id)
                if existing_item:
                    existing_item.name = item_data.name
                    existing_item.sku = item_data.sku
                    existing_item.quantity = item_data.quantity
                    existing_item.length_cm = item_data.length_cm
                    existing_item.width_cm = item_data.width_cm
                    existing_item.height_cm = item_data.height_cm
                    existing_item.weight_kg = item_data.weight_kg
                    existing_item.constraints = item_data.constraints
                    existing_item.sort_order = i
            else:
                # Yeni kalem ekle
                db.add(OrderItem(
                    id=str(uuid4()),
                    order_id=order.id,
                    name=item_data.name,
                    sku=item_data.sku,
                    quantity=item_data.quantity,
                    length_cm=item_data.length_cm,
                    width_cm=item_data.width_cm,
                    height_cm=item_data.height_cm,
                    weight_kg=item_data.weight_kg,
                    constraints=item_data.constraints,
                    sort_order=i,
                ))

    await db.commit()

    # Session cache'ini temizle — yeni eklenen item'lar selectinload'da görünsün
    db.expire_all()

    # Güncel halini döndür
    result2 = await db.execute(
        select(Order).options(
            selectinload(Order.items),
            selectinload(Order.shipment_links).selectinload(OrderShipment.shipment),
        ).where(Order.id == order_id)
    )
    order = result2.scalar_one()
    return _order_to_dict(order)


@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı")

    new_status = payload.status
    if new_status not in VALID_ORDER_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz statü: {new_status}. Geçerli değerler: {VALID_ORDER_STATUSES}"
        )

    allowed = ORDER_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"'{order.status}' → '{new_status}' geçişi geçerli değil. İzin verilenler: {allowed}"
        )

    order.status = new_status
    await db.commit()
    return {"id": order_id, "status": new_status}


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
):
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı")
    if order.deleted_at:
        raise HTTPException(status_code=404, detail="Sipariş zaten silinmiş")

    # Beklemede olmayan siparişler için force parametresi gerekli
    if order.status != "pending" and not force:
        status_label = {
            "planned": "Planlanmış", "loading_planned": "Yüklemesi Planlanmış",
            "loaded": "Yüklenmiş", "delivered": "Teslim Edilmiş", "cancelled": "İptal",
        }.get(order.status, order.status)
        raise HTTPException(
            status_code=409,
            detail=f"Bu sipariş '{status_label}' durumunda. Silmek istediğinizden emin misiniz? Onaylayarak devam edebilirsiniz.",
        )

    order.deleted_at = datetime.now(timezone.utc)
    await db.commit()


@router.patch("/{order_id}/restore")
async def restore_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Soft-delete edilen siparişi geri yükle."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sipariş bulunamadı")
    if not order.deleted_at:
        raise HTTPException(status_code=400, detail="Sipariş zaten aktif")
    order.deleted_at = None
    await db.commit()
    return {"id": order_id, "status": order.status, "restored": True}
