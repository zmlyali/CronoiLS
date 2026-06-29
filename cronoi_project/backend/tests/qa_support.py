"""
Cronoi Packris — QA / İleri Regresyon Test Altyapısı (destek kütüphanesi)
=========================================================================
"State-of-the-Art Kalite Güvence ve İleri Regresyon Test Protokolü" dokümanının
parametrik, yalın iskeleti. Üç bağımsız katman içerir:

  1) KATALOG     — araç tipleri + palet üreticisi (mk) + senaryo kayıt defteri (SCENARIOS)
  2) ÇÖZÜCÜ      — motoru çalıştırıp (search_fleet_of_type) sonucu önbellekleyen solve()
  3) DOĞRULAYICI — kod DIŞI bağımsız geometrik/fiziksel kapılar (check_*),
                   motor çıktısını (yerleşim matrisi) denetler.

DEĞİŞMEZ KURAL (memory r21c): doğrulayıcılar motorun kullandığı AYNI gap/margin
(ENGINE_GAP=1, ENGINE_MARGIN=1) ile yerleşimi yeniden kurar → "render == kapasite"
garantisi bağımsız olarak teyit edilir. Test fonksiyonları için bkz. test_qa_protocol.py.
"""

import os
import sys
import time
import random
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Any, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.fleet_packer import (   # noqa: E402
    FleetPallet, FleetVehicleType, pack_floor, stack_pallets,
    search_fleet_of_type, _col_items,
)

EPS = 1e-6


class Settings:
    """fleet_packer'ın okuduğu ayar nesnesi (OptimizerSettings'in test eşdeğeri)."""
    def __init__(self, pallet_gap_cm=1.0, wall_margin_cm=1.0,
                 weight_front_ratio_pct=60.0, weight_front_tolerance_pct=5.0,
                 balance_axle_load=True):
        self.pallet_gap_cm = pallet_gap_cm
        self.wall_margin_cm = wall_margin_cm
        self.weight_front_ratio_pct = weight_front_ratio_pct
        self.weight_front_tolerance_pct = weight_front_tolerance_pct
        self.balance_axle_load = balance_axle_load
        self.min_support_ratio_pct = 70.0


def effective_gap(s) -> float:
    return max(0.0, min(getattr(s, "pallet_gap_cm", 1.0), 1.0))


def effective_margin(s) -> float:
    return max(0.0, float(getattr(s, "wall_margin_cm", 1.0)))


# ════════════════════════════════════════════════════════════════════
# 1) KATALOG — araç tipleri + palet üreticisi + senaryolar
# ════════════════════════════════════════════════════════════════════

# Doküman Bölüm 2 araç konfigürasyonları (W × L × H biçiminde verilmiştir):
KONT40HC = FleetVehicleType(
    id="kont40hc", name="40' HC Konteyner", type="container",
    length_cm=1198, width_cm=233, height_cm=255,
    max_weight_kg=26000, usable_volume_m3=0, total_cost=9000, icon="📦")

TIR = FleetVehicleType(
    id="tir", name="Standart TIR Dorsesi", type="truck",
    length_cm=1360, width_cm=244, height_cm=300,
    max_weight_kg=24000, usable_volume_m3=0, total_cost=10000, icon="🚛")

# 3 akslı çekici+dorse (Test 3). wheelbase = kingpin↔dingil mesafesi (yaklaşık).
TIR_3AKS = FleetVehicleType(
    id="tir3", name="3 Akslı TIR", type="truck",
    length_cm=1360, width_cm=244, height_cm=300,
    max_weight_kg=24000, usable_volume_m3=0, total_cost=11000, icon="🚛")

_pid = 0


def mk(n: int, w: float, l: float, h: float, *, stackable: bool = True,
       weight: float = 100.0, cons: Optional[List[str]] = None) -> List[FleetPallet]:
    """n adet özdeş palet üret. w=across/z (en), l=along/x (boy), h=fiziksel yükseklik."""
    global _pid
    out = []
    for _ in range(n):
        _pid += 1
        out.append(FleetPallet(
            id=_pid, w_cm=w, l_cm=l, h_cm=h, weight_kg=weight,
            volume_m3=(w * l * h) / 1e6, stackable=stackable,
            constraints=list(cons or [])))
    return out


# ── Doküman test veri kümeleri ──
def make_perfect_cube() -> List[FleetPallet]:
    """TEST 1: konteyner iç hacmine kusursuz bölünen 8 palet (2×2×2 = tek konteyner)."""
    return mk(8, 116.5, 599, 127.5, stackable=True, weight=1500)


def make_backfilling() -> List[FleetPallet]:
    """TEST 2: asimetrik boy derinlikleri (geriye-doğru doldurma / diş yapısı)."""
    return (mk(10, 90, 245, 201, stackable=False, weight=400) +    # Grup A (istiflenemez)
            mk(10, 108, 130, 124, stackable=True, weight=300))     # Grup B (çift kat)


def make_axle_load() -> List[FleetPallet]:
    """TEST 3: uç ağırlık farkı — 5 ağır kurşun + 30 hafif hacimli."""
    return (mk(5, 100, 120, 100, stackable=False, weight=2500) +
            mk(30, 100, 120, 220, stackable=False, weight=80))


def make_93_mixed() -> List[FleetPallet]:
    """TEST 4 / KPI: 93 adet asimetrik karma palet (stokastik kararlılık + süre stresi)."""
    return (
        mk(20, 80, 120, 144) +
        mk(15, 100, 120, 180) +
        mk(12, 120, 100, 200) +
        mk(10, 90, 245, 201, stackable=False) +
        mk(8, 108, 130, 124) +
        mk(10, 116, 116, 150) +
        mk(8, 100, 120, 220, stackable=False) +
        mk(6, 123, 123, 183, stackable=False) +
        mk(4, 100, 120, 100, weight=1200)
    )  # 20+15+12+10+8+10+8+6+4 = 93


def make_quick_stable() -> List[FleetPallet]:
    """Hızlı permütasyon kapısı: kanıtlanmış-optimum (0 iter) → milisaniyede biter."""
    return mk(40, 80, 120, 220, stackable=False)


def make_constraint_mix() -> List[FleetPallet]:
    """Kısıt kapısı: NO_STACK / MUST_BOTTOM / istiflenebilir karışık."""
    return (mk(6, 100, 120, 110, stackable=True, weight=200) +
            mk(4, 100, 120, 90, stackable=True, weight=150, cons=["no_stack"]) +
            mk(3, 120, 100, 100, stackable=True, weight=900, cons=["must_bottom"]))


@dataclass
class Scenario:
    """Parametrik test senaryosu + doğrulama kapıları (Validation Gates)."""
    id: str
    title: str
    vt: FleetVehicleType
    make: Callable[[], List[FleetPallet]]
    expect_vehicles: Optional[int] = None          # kesin araç sayısı (None → sadece ≥LB)
    min_floor_pct: Optional[float] = None           # araç-başı min zemin doluluğu
    min_ldm_pct: Optional[float] = None             # araç-başı min LDM doluluğu
    front_pct_range: Optional[Tuple[float, float]] = None   # aks ön-yük aralığı
    max_void_gap_cm: Optional[float] = None         # boy ekseni max iç boşluk
    # Clearance politikası (tailored/sıfır-fire yük → 0; normal → 1cm güvenlik):
    gap_cm: float = 1.0
    margin_cm: float = 1.0
    usable_factor_pct: float = 90.0                 # tailored tam-dolum → 100
    seed: int = 42
    budget_s: float = 4.0
    xfail: Optional[str] = None                     # bilinen motor açığı → strict xfail sebebi

    def settings(self) -> "Settings":
        return Settings(pallet_gap_cm=self.gap_cm, wall_margin_cm=self.margin_cm,
                        weight_front_ratio_pct=60.0, weight_front_tolerance_pct=5.0,
                        balance_axle_load=True)


SCENARIOS: List[Scenario] = [
    Scenario(
        id="t1_perfect_cube", title="TEST 1 — Mükemmel Küp / Sıfır Fire",
        vt=KONT40HC, make=make_perfect_cube,
        # Tailored yük: sıfır clearance (gap=margin=0) + tam-dolum (faktör %100).
        gap_cm=0.0, margin_cm=0.0, usable_factor_pct=100.0,
        expect_vehicles=1, min_floor_pct=99.0, min_ldm_pct=99.0,
    ),
    Scenario(
        id="t2_backfilling", title="TEST 2 — Prepack Asimetrik Taban / Backfilling",
        vt=TIR, make=make_backfilling,
        max_void_gap_cm=15.0,
    ),
    Scenario(
        id="t3_axle_load", title="TEST 3 — Dinamik Aks Yükü / Kantar Momenti",
        vt=TIR_3AKS, make=make_axle_load,
        front_pct_range=(55.0, 65.0),
    ),
    Scenario(
        id="t4_stochastic", title="TEST 4 — Stokastik Kararlılık (93 palet)",
        vt=TIR, make=make_93_mixed, budget_s=8.0,
    ),
    Scenario(
        id="k_constraints", title="KISIT — NO_STACK / MUST_BOTTOM kapısı",
        vt=TIR, make=make_constraint_mix,
    ),
]


# ════════════════════════════════════════════════════════════════════
# 2) ÇÖZÜCÜ — motoru çalıştır + önbellekle
# ════════════════════════════════════════════════════════════════════

_SOLVE_CACHE: Dict[str, Dict[str, Any]] = {}


def solve(sc: Scenario) -> Dict[str, Any]:
    """Senaryoyu motora ver, sonucu önbellekle (deterministik → tek kez yeter)."""
    if sc.id in _SOLVE_CACHE:
        return _SOLVE_CACHE[sc.id]
    pallets = sc.make()
    st = sc.settings()
    t0 = time.perf_counter()
    res = search_fleet_of_type(
        pallets, sc.vt, st, time.time() + sc.budget_s, random.Random(sc.seed),
        usable_factor_pct=sc.usable_factor_pct)
    res = res or {"fleet": [], "count": 0, "lower_bound": 0,
                  "proven_optimal": False, "iterations": 0}
    res["duration_ms"] = (time.perf_counter() - t0) * 1000.0
    res["n_pallets"] = len(pallets)
    res["gap"] = effective_gap(st)            # doğrulayıcılar motorla AYNI clearance'ı kullanır
    res["margin"] = effective_margin(st)
    _SOLVE_CACHE[sc.id] = res
    return res


# ════════════════════════════════════════════════════════════════════
# 3) DOĞRULAYICILAR — kod-dışı bağımsız geometrik/fiziksel kapılar
# ════════════════════════════════════════════════════════════════════

def vehicle_layout(vehicle: Dict[str, Any], vt: FleetVehicleType,
                   gap: float = 1.0, margin: float = 1.0) -> List[Dict[str, Any]]:
    """Aracın sütunlarını AYNI motor parametreleriyle zemine yerleştir; her yerleşime
    ait ağırlık/kısıt/istif bilgisini ekle. id = sütun indeksi."""
    cols = vehicle["cols"]
    pf = pack_floor(_col_items(cols), vt.length_cm, vt.width_cm, gap, margin)
    out = []
    for p in pf["placed"]:
        col = cols[p["id"]]
        out.append({**p,
                    "weight": col["weight"], "volume": col["volume"],
                    "objs": col["objs"], "usedH": col.get("usedH", 0)})
    return out, pf["unplaced"]


def rect_of(p: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """Yerleşim → (x0, x1, z0, z1) ayak izi dikdörtgeni (merkezden köşeye)."""
    return (p["xCm"] - p["lCm"] / 2, p["xCm"] + p["lCm"] / 2,
            p["zCm"] - p["wCm"] / 2, p["zCm"] + p["wCm"] / 2)


def check_overlap(placed: List[Dict[str, Any]]) -> List[Tuple]:
    """Geometrik kapı: 3B hacim ihlali (ayak izi çakışması). İhlal listesi döndürür."""
    viol = []
    for i in range(len(placed)):
        ax0, ax1, az0, az1 = rect_of(placed[i])
        for j in range(i + 1, len(placed)):
            bx0, bx1, bz0, bz1 = rect_of(placed[j])
            ox = min(ax1, bx1) - max(ax0, bx0)
            oz = min(az1, bz1) - max(az0, bz0)
            if ox > EPS and oz > EPS:
                viol.append((placed[i]["id"], placed[j]["id"], round(min(ox, oz), 3)))
    return viol


def check_bounds(placed: List[Dict[str, Any]], vt: FleetVehicleType) -> List[Any]:
    """Geometrik kapı: araç dışına taşma. Taşan yerleşim id'leri döndürür."""
    out = []
    L, W = vt.length_cm, vt.width_cm
    for p in placed:
        x0, x1, z0, z1 = rect_of(p)
        if x0 < -L / 2 - EPS or x1 > L / 2 + EPS or z0 < -W / 2 - EPS or z1 > W / 2 + EPS:
            out.append(p["id"])
    return out


def void_gaps_x(placed: List[Dict[str, Any]]) -> List[float]:
    """Boy (x) ekseni boyunca, hiçbir palet kaplamayan İÇ boşlukların uzunlukları.
    Baş/son slack hariç (yalnızca dolu bölgeler arasındaki sahipsiz hava boşlukları)."""
    if not placed:
        return []
    ivs = sorted((p["xCm"] - p["lCm"] / 2, p["xCm"] + p["lCm"] / 2) for p in placed)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a <= merged[-1][1] + EPS:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [round(merged[k + 1][0] - merged[k][1], 2) for k in range(len(merged) - 1)]


_BLOCK_BOTTOM = {"fragile", "no_stack", "must_top", "this_side_up", "vertical"}


def check_stacking(vehicle: Dict[str, Any], vt: FleetVehicleType) -> List[str]:
    """Kısıt kapısı: NO_STACK / MUST_BOTTOM / ağır-alta / footprint-küçülme / yükseklik.
    Bağımsız yeniden denetim (motorun can_stack_pallet'ından ayrı mantık)."""
    viol = []
    for ci, col in enumerate(vehicle["cols"]):
        objs = col["objs"]
        if col.get("usedH", 0) > vt.height_cm + EPS:
            viol.append(f"col{ci}: usedH {col['usedH']:.1f} > araç {vt.height_cm}")
        for k, p in enumerate(objs):
            cons = {(c.value if hasattr(c, "value") else str(c)) for c in (p.constraints or [])}
            is_bottom = (k == 0)
            is_top = (k == len(objs) - 1)
            if not is_top and (p.stackable is False or cons & _BLOCK_BOTTOM):
                viol.append(f"col{ci}[{k}] id={p.id}: istiflenemez/NO_STACK ama altta yük var")
            if "must_bottom" in cons and not is_bottom:
                viol.append(f"col{ci}[{k}] id={p.id}: MUST_BOTTOM ama tabanda değil")
            if k > 0:
                b = objs[k - 1]
                if (p.weight_kg or 0) > (b.weight_kg or 0) + EPS:
                    viol.append(f"col{ci}[{k}] id={p.id}: ağır palet hafifin üstünde")
                if p.w_cm > b.w_cm * 1.02 + EPS or p.l_cm > b.l_cm * 1.02 + EPS:
                    viol.append(f"col{ci}[{k}] id={p.id}: üst footprint alttan büyük")
    return viol


def axle_metrics(placed: List[Dict[str, Any]], vt: FleetVehicleType) -> Optional[Dict[str, float]]:
    """Kantar moment analizi (bağımsız) — motorun _compute_weight_balance modeliyle AYNI:
    iki-uçtan mesnetli kiriş (ön=0, arka=L), ön aks payı = (1 - cog_x/L). cog_x ön duvardan."""
    tot = sum(p["weight"] for p in placed)
    if tot <= EPS:
        return None
    L = vt.length_cm
    cog_x = sum(p["weight"] * (p["xCm"] + L / 2) for p in placed) / tot   # 0 = ön duvar
    return {
        "cog_x": cog_x,
        "total_weight": tot,
        "front_pct": (1.0 - cog_x / L) * 100.0,
        "cog_dev_pct": (cog_x / L - 0.5) * 100.0,   # geometrik merkezden sapma (±)
    }


def is_axle_relevant(vehicle: Dict[str, Any], vt: FleetVehicleType, frac: float = 0.20) -> bool:
    """Aks kapısı yalnızca anlamlı-ağırlıklı araçlara uygulanır: yükü araç kapasitesinin
    %frac'ından azsa (örn. son araçtaki birkaç hafif palet) hiçbir aksı zorlamaz → muaf."""
    w = sum(c["weight"] for c in vehicle["cols"])
    return w >= frac * (vt.max_weight_kg or 1.0)


def floor_fill_pct(vehicle: Dict[str, Any], vt: FleetVehicleType, margin: float = 1.0) -> float:
    usable = max(1.0, (vt.length_cm - 2 * margin) * (vt.width_cm - 2 * margin))
    area = sum(c["wCm"] * c["lCm"] for c in vehicle["cols"])
    return area / usable * 100.0


# ── Toplu kapı: bir filonun geometri+kısıt geçerliliği (her senaryoda PASS olmalı) ──
def validate_fleet_integrity(fleet: List[Dict[str, Any]], vt: FleetVehicleType,
                             gap: float = 1.0, margin: float = 1.0) -> List[str]:
    """Çakışma + taşma (unplaced) + kısıt ihlallerinin TÜMÜNÜ topla. Boş liste = geçerli."""
    errors = []
    for vi, v in enumerate(fleet):
        placed, unplaced = vehicle_layout(v, vt, gap, margin)
        if unplaced:
            errors.append(f"araç{vi}: {len(unplaced)} sütun zemine sığmadı (taşma)")
        for a, b, ov in check_overlap(placed):
            errors.append(f"araç{vi}: çakışma {a}↔{b} ({ov}cm)")
        for pid in check_bounds(placed, vt):
            errors.append(f"araç{vi}: yerleşim {pid} araç dışına taştı")
        for msg in check_stacking(v, vt):
            errors.append(f"araç{vi}: {msg}")
    return errors


def assigned_pallet_count(fleet: List[Dict[str, Any]]) -> int:
    return sum(len(v["assignedPallets"]) for v in fleet)
