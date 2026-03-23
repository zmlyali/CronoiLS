"""
Cronoi LS — Mock API Server
FastAPI'yi taklit eden, verileri RAM'de tutan hafif test sunucusu.
Backend yazmadan frontend'in API modunu test etmek için.

Kurulum:
    pip install fastapi uvicorn

Çalıştır:
    python mock_server.py

Tarayıcıda:
    http://localhost:8000/api/docs  →  Swagger UI
    
Frontend'i açarken API base URL'i localhost:8000'e yönlendiriyor.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import time, random, uuid

app = FastAPI(title="Cronoi LS Mock API", version="2.0-mock")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store ─────────────────────────────────────────
DB: Dict[str, Any] = {"shipments": {}, "pallets": {}, "scenarios": {}}


# ── Schemas ─────────────────────────────────────────────────
class ProductInput(BaseModel):
    name: str
    quantity: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    constraints: List[Dict] = []

class ShipmentCreate(BaseModel):
    pallet_type: str = "euro"
    products: List[ProductInput]
    destination: Optional[str] = None

class OptimizeRequest(BaseModel):
    vehicle_ids: List[str] = []
    distance_km: float = 500
    duration_hours: float = 8


# ── Endpoints ────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0-mock", "mode": "mock"}


@app.post("/api/v1/shipments")
def create_shipment(payload: ShipmentCreate):
    sid = str(uuid.uuid4())
    DB["shipments"][sid] = {
        "id": sid,
        "reference_no": f"SEV-MOCK-{random.randint(1000,9999)}",
        "status": "draft",
        "pallet_type": payload.pallet_type,
        "products": [p.model_dump() for p in payload.products],
        "created_at": time.time(),
    }
    return {
        "id": sid,
        "reference_no": DB["shipments"][sid]["reference_no"],
        "status": "draft",
        "pallet_type": payload.pallet_type,
        "destination": payload.destination,
        "total_pallets": None,
        "created_at": DB["shipments"][sid]["reference_no"],
        "optimized_at": None,
    }


@app.post("/api/v1/shipments/{shipment_id}/optimize")
def optimize(shipment_id: str, req: OptimizeRequest):
    if shipment_id not in DB["shipments"]:
        raise HTTPException(404, "Shipment not found")
    DB["shipments"][shipment_id]["status"] = "optimizing"
    DB["shipments"][shipment_id]["optimize_started"] = time.time()
    return {
        "shipment_id": shipment_id,
        "status": "pending",
        "progress_pct": 0,
        "message": "Optimizasyon başlatıldı",
    }


@app.get("/api/v1/shipments/{shipment_id}/status")
def shipment_status(shipment_id: str):
    if shipment_id not in DB["shipments"]:
        raise HTTPException(404)
    ship = DB["shipments"][shipment_id]
    
    # Simulate progress: done after ~3 seconds
    elapsed = time.time() - ship.get("optimize_started", time.time())
    if elapsed > 3:
        ship["status"] = "done"
        # Generate mock pallets if not done yet
        if shipment_id not in DB["pallets"]:
            DB["pallets"][shipment_id] = _mock_pallets(ship)
        return {
            "shipment_id": shipment_id,
            "status": "done",
            "progress_pct": 100,
            "message": "Optimizasyon tamamlandı ✓",
            "result_summary": {
                "total_pallets": len(DB["pallets"].get(shipment_id, [])),
                "avg_fill_rate": 72.4,
                "best_scenario_cost": 14850,
            },
        }
    else:
        pct = min(90, int(elapsed / 3 * 90))
        msgs = ["Ürünler sıralanıyor...", "Paletlere yerleştiriliyor...", "Kısıtlar kontrol ediliyor..."]
        return {
            "shipment_id": shipment_id,
            "status": "running",
            "progress_pct": pct,
            "message": msgs[int(elapsed)],
        }


@app.get("/api/v1/shipments/{shipment_id}/pallets")
def get_pallets(shipment_id: str):
    if shipment_id not in DB["shipments"]:
        raise HTTPException(404)
    pallets = DB["pallets"].get(shipment_id, [])
    return {"shipment_id": shipment_id, "pallets": pallets}


@app.post("/api/v1/scenarios/generate")
def generate_scenarios(payload: dict):
    sid = payload.get("shipment_id")
    pallets = DB["pallets"].get(sid, []) if sid else []
    n_pallets = len(pallets) or 8

    scenarios = [
        {
            "name": "Minimum Araç",
            "strategy": "min_vehicles",
            "total_cost": 14850,
            "cost_per_pallet": round(14850 / max(n_pallets, 1), 0),
            "total_vehicles": 2,
            "avg_fill_rate_pct": 78.5,
            "is_recommended": True,
            "vehicle_assignments": [],
        },
        {
            "name": "Dengeli",
            "strategy": "balanced",
            "total_cost": 16200,
            "cost_per_pallet": round(16200 / max(n_pallets, 1), 0),
            "total_vehicles": 3,
            "avg_fill_rate_pct": 65.0,
            "is_recommended": False,
            "vehicle_assignments": [],
        },
        {
            "name": "Maksimum Verim",
            "strategy": "max_efficiency",
            "total_cost": 19500,
            "cost_per_pallet": round(19500 / max(n_pallets, 1), 0),
            "total_vehicles": 4,
            "avg_fill_rate_pct": 55.2,
            "is_recommended": False,
            "vehicle_assignments": [],
        },
    ]
    return {"scenarios": scenarios}


def _mock_pallets(shipment: dict):
    """Mock bin packing sonucu üret"""
    products = shipment.get("products", [])
    if not products:
        products = [{"name": "Örnek Ürün", "quantity": 10,
                     "length_cm": 120, "width_cm": 80, "height_cm": 60, "weight_kg": 40, "constraints": []}]
    
    # Basit grupla: her 3-4 ürüne bir palet
    pallets = []
    items_per_pallet = 4
    all_items = []
    for p in products:
        for _ in range(p["quantity"]):
            all_items.append(p)
    
    for i in range(0, len(all_items), items_per_pallet):
        chunk = all_items[i:i+items_per_pallet]
        pallet_num = (i // items_per_pallet) + 1
        pallets.append({
            "pallet_number":   pallet_num,
            "pallet_type":     shipment.get("pallet_type", "euro"),
            "total_weight_kg": round(sum(p["weight_kg"] for p in chunk), 2),
            "total_height_cm": round(sum(p["height_cm"] for p in chunk) * 0.7, 1),
            "total_volume_m3": round(sum(p["length_cm"]*p["width_cm"]*p["height_cm"] for p in chunk) / 1_000_000, 4),
            "fill_rate_pct":   round(random.uniform(58, 85), 1),
            "constraints":     list({c["code"] for p in chunk for c in p.get("constraints", [])}),
            "products": [
                {
                    "name":       p["name"],
                    "quantity":   1,
                    "length_cm":  p["length_cm"],
                    "width_cm":   p["width_cm"],
                    "height_cm":  p["height_cm"],
                    "weight_kg":  p["weight_kg"],
                    "constraints": p.get("constraints", []),
                }
                for p in chunk
            ],
        })
    return pallets


if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Cronoi LS Mock API başlatılıyor...")
    print("📍 API:  http://localhost:8000")
    print("📋 Docs: http://localhost:8000/api/docs")
    print("🌐 Frontend: frontend/Cronoi_LS_v2.html dosyasını tarayıcıda aç\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
