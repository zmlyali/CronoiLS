"""
Filo katmanı ALNS — benchmark + regresyon + determinizm kapısı (Optimizer V10).

Kapı kuralları:
  • ALNS araç sayısı ≤ greedy-başlangıç (seed+FFD)  → asla kötüleşmez
  • ALNS araç sayısı ≥ alt-sınır (LB)                → geçerli
  • Hiçbir araç zemini taşmaz                          → pack_floor.unplaced == []
  • Aynı girdi + aynı seed iki koşu → BİREBİR aynı atama (determinizm)

Çalıştır (backend/ klasöründen):
    venv\\Scripts\\python.exe tests/bench_fleet.py
veya pytest:
    venv\\Scripts\\python.exe -m pytest tests/bench_fleet.py -q
"""

import os
import sys
import time
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.services.fleet_packer as fp   # noqa: E402
from app.services.fleet_packer import (  # noqa: E402
    FleetPallet, FleetVehicleType, pack_floor, _col_items, search_fleet_of_type,
)


class _Settings:
    pallet_gap_cm = 1


SETTINGS = _Settings()

TIR = FleetVehicleType(id="tir", name="TIR", type="truck",
                       length_cm=1360, width_cm=245, height_cm=270,
                       max_weight_kg=24000, usable_volume_m3=90, total_cost=10000)
KONT = FleetVehicleType(id="kont40", name="Konteyner40HC", type="container",
                        length_cm=1198, width_cm=233, height_cm=255,
                        max_weight_kg=26000, usable_volume_m3=72, total_cost=9000)

_pid = 0


def mk(n, w, l, h, stackable=False, weight=100.0):
    global _pid
    out = []
    for _ in range(n):
        _pid += 1
        out.append(FleetPallet(id=_pid, w_cm=w, l_cm=l, h_cm=h, weight_kg=weight,
                               volume_m3=(w * l * h) / 1e6, stackable=stackable))
    return out


def greedy_initial(pallets, vt, usable_factor=90.0):
    """search_fleet_of_type'ın ALNS ÖNCESİ başlangıç çözümü (seed+FFD+forward-fill)."""
    gap = fp._gap_for(SETTINGS)
    uv = fp.veh_usable_vol(vt, usable_factor)
    cols = fp.stack_pallets(pallets, vt.height_cm)
    lb = fp._lower_bound(cols, vt, uv, gap)
    best = None
    for order in fp._seed_orderings(cols, vt, gap):
        f = fp._run_ffd(order, vt, gap, uv)
        if best is None or len(f) < len(best):
            best = f
        if len(best) <= lb:
            break
    init = fp._forward_fill(best, vt, gap, uv)
    return len(init), lb


def no_overflow(fleet, vt):
    for v in fleet:
        if pack_floor(_col_items(v["cols"]), vt.length_cm, vt.width_cm, 1, 1)["unplaced"]:
            return False
    return True


def assignment_signature(fleet):
    """Atamanın deterministik imzası: her araçtaki palet id kümeleri (sıralı)."""
    sig = []
    for v in fleet:
        ids = sorted(p.id for c in v["cols"] for p in c["objs"])
        sig.append(tuple(ids))
    return tuple(sorted(sig))


CASES = [
    ("EUR 50×(80×120×220)", lambda: mk(50, 80, 120, 220), TIR),
    ("Karışık prepack (31)", lambda: (
        mk(5, 123, 123, 183) + mk(8, 123, 123, 183) + mk(3, 105, 105, 175) +
        mk(1, 80, 120, 175) + mk(14, 120, 200, 164)), TIR),
    ("Konteyner 40×(95×230)", lambda: mk(40, 95, 230, 200), KONT),
    ("Ağırlık-bağlı 18×(100×120, 1500kg)", lambda: mk(18, 100, 120, 150, weight=1500), TIR),
    ("İstiflenebilir 60×(100×120×90)", lambda: mk(60, 100, 120, 90, stackable=True), TIR),
]


def _run_case(name, make, vt, budget_s=3.0):
    pallets = make()
    init_count, lb = greedy_initial(pallets, vt)
    t0 = time.time()
    res = search_fleet_of_type(pallets, vt, SETTINGS, time.time() + budget_s,
                               random.Random(42))
    dt = (time.time() - t0) * 1000
    assert res is not None, f"{name}: tip uygun olmalı"
    fleet = res["fleet"]
    assert no_overflow(fleet, vt), f"{name}: TAŞMA var"
    assert res["count"] >= lb, f"{name}: araç({res['count']}) < alt-sınır({lb})"
    assert res["count"] <= init_count, (
        f"{name}: ALNS({res['count']}) greedy-başlangıçtan({init_count}) KÖTÜ")
    # tüm paletler atanmış
    assigned = sum(len(v["assignedPallets"]) for v in fleet)
    assert assigned == len(pallets), f"{name}: {assigned}/{len(pallets)} palet atandı"
    gain = init_count - res["count"]
    print(f"  {name:42s} greedy={init_count} → ALNS={res['count']} "
          f"(LB={lb}{' ✓optimum' if res['proven_optimal'] else ''}"
          f"{f', −{gain} araç KAZANÇ' if gain else ''}) "
          f"{res['iterations']} iter · {dt:.0f}ms")
    return gain


def test_alns_never_worse_than_greedy_and_valid():
    total_gain = 0
    for name, make, vt in CASES:
        total_gain += _run_case(name, make, vt)
    print(f"  → toplam araç kazancı: {total_gain}")


def test_determinism_identical_runs():
    """Aynı girdi + aynı seed → BİREBİR aynı atama (iterasyon-tabanlı durdurma).
    ALNS döngüsünün GERÇEKTEN çalıştığı bir set seçilir (başlangıç > alt-sınır)."""
    # 31 paletlik karışık set → greedy=3 > LB=2 → ALNS yüzlerce iterasyon yapar.
    pallets = (mk(5, 123, 123, 183) + mk(8, 123, 123, 183) + mk(3, 105, 105, 175) +
               mk(1, 80, 120, 175) + mk(14, 120, 200, 164))
    # Bol bütçe → iterasyon limiti bağlasın (wall-clock değil) → tekrarlanabilir
    r1 = search_fleet_of_type(pallets, TIR, SETTINGS, time.time() + 30, random.Random(7))
    r2 = search_fleet_of_type(pallets, TIR, SETTINGS, time.time() + 30, random.Random(7))
    assert r1["count"] == r2["count"], "araç sayısı iki koşuda farklı"
    assert assignment_signature(r1["fleet"]) == assignment_signature(r2["fleet"]), (
        "DETERMİNİZM İHLALİ: aynı seed iki koşuda farklı atama üretti")
    print(f"  determinizm OK: iki koşu da {r1['count']} araç, birebir aynı atama "
          f"({r1['iterations']} iter)")


if __name__ == "__main__":
    print("── ALNS benchmark + regresyon ──")
    test_alns_never_worse_than_greedy_and_valid()
    print("── determinizm ──")
    test_determinism_identical_runs()
    print("TÜM KAPILAR GEÇTİ")
