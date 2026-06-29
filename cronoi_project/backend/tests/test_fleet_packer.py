"""
Backend filo paketleyici testleri — fleet_packer (zemin + istif + GRASP).
FE harness (tests/optimization_layout_test.js) vakalarının portu + prepack ekran vakası.

Çalıştır:  backend/ klasöründen
    venv\\Scripts\\python.exe -m pytest tests/test_fleet_packer.py -v
veya doğrudan:
    venv\\Scripts\\python.exe tests/test_fleet_packer.py
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.fleet_packer import (   # noqa: E402
    FleetPallet, FleetVehicleType, pack_floor, stack_pallets,
    search_fleet_of_type, optimize_fleet, _col_items, veh_usable_vol,
)
import time  # noqa: E402


class _Settings:
    pallet_gap_cm = 1
    min_support_ratio_pct = 70.0


SETTINGS = _Settings()

TIR = FleetVehicleType(id="tir", name="TIR", type="truck",
                       length_cm=1360, width_cm=245, height_cm=270,
                       max_weight_kg=24000, usable_volume_m3=90, total_cost=10000)
KONT40 = FleetVehicleType(id="konteyner40hc", name="Konteyner 40HC", type="container",
                          length_cm=1198, width_cm=233, height_cm=255,
                          max_weight_kg=26000, usable_volume_m3=72, total_cost=9000)

_pid = 0


def mk(n, pw, pl, ph, stackable=True, weight=100.0, cons=None):
    global _pid
    out = []
    for _ in range(n):
        _pid += 1
        out.append(FleetPallet(id=_pid, w_cm=pw, l_cm=pl, h_cm=ph,
                               weight_kg=weight, volume_m3=(pw * pl * ph) / 1e6,
                               stackable=stackable, constraints=list(cons or [])))
    return out


def _no_overflow(fleet, vt, gap=1):
    for v in fleet:
        res = pack_floor(_col_items(v["cols"]), vt.length_cm, vt.width_cm, gap, 1)
        if res["unplaced"]:
            return False
    return True


# ── pack_floor: EUR 80×120 → TIR zemininde 33 palet ──
def test_packfloor_eur_33_per_tir():
    items = [{"id": i, "w": 80, "l": 120, "h": 100} for i in range(33)]
    res = pack_floor(items, TIR.length_cm, TIR.width_cm, 1, 1)
    assert res["unplaced"] == [], "33 EUR TIR zeminine sığmalı"
    # 34. taşmalı
    items34 = items + [{"id": 99, "w": 80, "l": 120, "h": 100}]
    res34 = pack_floor(items34, TIR.length_cm, TIR.width_cm, 1, 1)
    assert len(res34["unplaced"]) == 1, "34. EUR zemine sığmamalı (33 sınırı)"


# ── search: 33 uzun, istiflenemez EUR → 1 TIR; 34 → 2 TIR ──
def test_search_eur_floor_bound():
    pallets = mk(33, 80, 120, 230, stackable=False)
    res = search_fleet_of_type(pallets, TIR, SETTINGS, time.time() + 2.0,
                               __import__("random").Random(1))
    assert res is not None
    assert res["count"] == 1, f"33 uzun EUR tek TIR olmalı, oldu {res['count']}"
    assert _no_overflow(res["fleet"], TIR)

    pallets2 = mk(34, 80, 120, 230, stackable=False)
    res2 = search_fleet_of_type(pallets2, TIR, SETTINGS, time.time() + 2.0,
                                __import__("random").Random(1))
    assert res2["count"] == 2, f"34 uzun EUR iki TIR olmalı, oldu {res2['count']}"
    assert _no_overflow(res2["fleet"], TIR)


# ── istif: düşük + istiflenebilir paletler dikey sütuna iner ──
def test_stacking_reduces_columns():
    pallets = mk(8, 100, 120, 100, stackable=True, weight=100)
    cols = stack_pallets(pallets, TIR.height_cm)   # 270/100 → 2'li istif
    assert len(cols) < 8, "istiflenebilir düşük paletler sütun sayısını düşürmeli"
    assert all(c["usedH"] <= TIR.height_cm + 1e-6 for c in cols)


# ── prepack ekran vakası: 31 karışık palet, taşma yok, LB tutarlı ──
def test_prepack_screenshot_case():
    pallets = (
        mk(5, 123, 123, 183, stackable=False, weight=25) +
        mk(8, 123, 123, 183, stackable=False, weight=25) +
        mk(3, 105, 105, 175, stackable=False, weight=25) +
        mk(1, 80, 120, 175, stackable=False, weight=25) +
        mk(14, 120, 200, 164, stackable=False, weight=25)
    )
    assert len(pallets) == 31
    res = search_fleet_of_type(pallets, TIR, SETTINGS, time.time() + 3.0,
                               __import__("random").Random(7))
    assert res is not None
    assert _no_overflow(res["fleet"], TIR), "hiçbir araç zemini taşmamalı"
    assert res["count"] >= res["lower_bound"], "araç sayısı alt sınırdan küçük olamaz"
    # tüm paletler atanmış olmalı
    assigned = sum(len(v["assignedPallets"]) for v in res["fleet"])
    assert assigned == 31, f"31 palet atanmalı, atandı {assigned}"
    print(f"[prepack] count={res['count']} lb={res['lower_bound']} "
          f"proven={res['proven_optimal']} iters={res['iterations']}")


# ── optimize_fleet: çoklu tip → en ucuz uygun filo ──
def test_optimize_fleet_picks_cheapest():
    pallets = mk(20, 100, 120, 220, stackable=False, weight=300)
    best = optimize_fleet(pallets, [TIR, KONT40], SETTINGS, time_budget_s=2.0)
    assert best is not None
    assert best["count"] >= 1
    assert _no_overflow(best["fleet"], best["vt"])
    print(f"[optimize] type={best['vt'].name} count={best['count']} "
          f"cost={best['total_cost']:.0f} lb={best['lower_bound']}")


# ── ScenarioOptimizer entegrasyonu: footprint'li paletler → zemin-duyarlı motor ──
def test_scenario_optimizer_uses_floor_engine():
    from app.services.optimizer import (
        ScenarioOptimizer, OptimizedPallet, VehicleConfig, OptimizerSettings,
    )
    pallets = []
    pn = 0
    spec = [(5, 123, 123, 183), (8, 123, 123, 183), (3, 105, 105, 175),
            (1, 80, 120, 175), (14, 120, 200, 164)]
    for cnt, w, l, h in spec:
        for _ in range(cnt):
            pn += 1
            pallets.append(OptimizedPallet(
                pallet_number=pn, pallet_type="PP",
                total_weight_kg=25, total_height_cm=h,
                total_volume_m3=(w * l * h) / 1e6, fill_rate_pct=100,
                footprint_w_cm=w, footprint_l_cm=l, phys_height_cm=h,
                stackable=False, source="prepack",
            ))
    vehicles = [VehicleConfig(
        id="tir", name="TIR", type="truck", length_cm=1360, width_cm=245, height_cm=270,
        max_weight_kg=24000, pallet_capacity=33, base_cost=10000, fuel_per_km=0,
        driver_per_hour=0, opportunity_cost=0, distance_km=500, duration_hours=8)]
    settings = OptimizerSettings.from_dict({"optimizerTimeBudgetMs": 2000, "palletGapCm": 3})
    opt = ScenarioOptimizer(pallets, vehicles, settings=settings)
    scenarios = opt.generate_all()
    assert len(scenarios) == 3
    rec = next((s for s in scenarios if s.is_recommended), scenarios[0])
    assert rec.engine == "floor-aware-alns", f"zemin-duyarlı ALNS motoru kullanılmalı, oldu {rec.engine}"
    assert rec.total_vehicles >= 1
    # tüm paletler atanmış olmalı
    assigned = sum(len(va.pallet_ids) for va in rec.vehicles)
    assert assigned == 31, f"31 palet atanmalı, atandı {assigned}"
    print(f"[scenario] engine={rec.engine} vehicles={rec.total_vehicles} "
          f"lb={rec.lower_bound} proven={rec.proven_optimal} cost={rec.total_cost:.0f}")


def test_scenario_optimizer_legacy_fallback():
    """Footprint yoksa eski hacim-tabanlı greedy'e güvenli düşüş."""
    from app.services.optimizer import ScenarioOptimizer, OptimizedPallet, VehicleConfig
    pallets = [OptimizedPallet(pallet_number=i, pallet_type="P1", total_weight_kg=200,
                               total_height_cm=120, total_volume_m3=1.0, fill_rate_pct=80)
               for i in range(1, 11)]
    vehicles = [VehicleConfig(id="tir", name="TIR", type="truck", length_cm=1360, width_cm=245,
                              height_cm=270, max_weight_kg=24000, pallet_capacity=33,
                              base_cost=10000, fuel_per_km=0, driver_per_hour=0,
                              opportunity_cost=0, distance_km=500, duration_hours=8)]
    scenarios = ScenarioOptimizer(pallets, vehicles).generate_all()
    assert len(scenarios) == 3
    assert all(getattr(s, "engine", "binding-greedy") == "binding-greedy" for s in scenarios)
    print("[legacy] footprint yok → binding-greedy fallback OK")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            t0 = time.time()
            fn()
            print(f"✓ {name}  ({(time.time()-t0)*1000:.0f}ms)")
    print("TÜM TESTLER GEÇTİ")
