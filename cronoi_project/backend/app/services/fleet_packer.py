"""
Cronoi LS — Zemin-Duyarlı Filo Paketleyici + Solver-Sınıfı Arama (Backend)
==========================================================================
Frontend'deki kanıtlanmış palet→araç motorunun (Cronoi_LS_v2.html) Python portu:
  _packFloor (6272)  → pack_floor          : Maximal-Rectangles + Bottom-Left zemin paketleme
  _stackPallets(6400)→ stack_pallets       : dikey istif (yatakbaşı üst üste)
  _canStackPallet    → can_stack_pallet
  _buildRows  (6438) → build_rows          : width-pattern blokları (ek strateji)
  _buildFleetOfType  → build_fleet_of_type : istif→sütun, FFD/best-fit, konsolidasyon, ileri-doldurma

ÜSTÜNE eklenen "solver" katmanı:
  search_fleet_of_type : çok-başlangıçlı GRASP + alt-sınır (LB) + süre bütçesi
  optimize_fleet       : tüm araç tiplerini değerlendir, en ucuz uygun filoyu seç (FE _evalAllFleets)

DEĞİŞMEZ KURAL (memory r21c): render ve kapasite AYNI pack_floor sütunlarını kullanır;
araca yalnızca pack_floor(...).unplaced == [] olan sütun atanır → taşma yapısal imkânsız.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import math
import time
import random

from app.services.alns import run_alns

EPS = 1e-6


# ════════════════════════════════════════════════════════════════════
# Veri modelleri
# ════════════════════════════════════════════════════════════════════

@dataclass
class FleetPallet:
    """Filo paketleme için hafif palet görünümü (ayak izi + fiziksel yükseklik dahil)."""
    id: Any
    w_cm: float                       # ayak izi genişliği (z ekseni / "across")
    l_cm: float                       # ayak izi uzunluğu (x ekseni / "along")
    h_cm: float                       # FİZİKSEL yükseklik (taban/tare dahil)
    weight_kg: float = 0.0
    volume_m3: float = 0.0
    stackable: bool = True
    constraints: List[str] = field(default_factory=list)


@dataclass
class FleetVehicleType:
    """Araç tipi — zemin geometrisi + kapasite + maliyet."""
    id: str
    name: str
    type: str
    length_cm: float
    width_cm: float
    height_cm: float
    max_weight_kg: float
    pallet_capacity: int = 0
    usable_volume_m3: float = 0.0     # 0 → brüt × usable_factor
    total_cost: float = 0.0
    icon: str = "🚛"


def _norm_constraints(cons) -> List[str]:
    out = []
    for c in (cons or []):
        out.append(c.value if hasattr(c, "value") else str(c))
    return out


def veh_usable_vol(vt: FleetVehicleType, usable_factor_pct: float = 90.0) -> float:
    if not vt:
        return 0.0
    if vt.usable_volume_m3 and vt.usable_volume_m3 > 0:
        return float(vt.usable_volume_m3)
    gross = (vt.length_cm * vt.width_cm * vt.height_cm) / 1_000_000
    # Yuvarlama YOK: tailored tam-dolum (%100 faktör) knife-edge'inde hassasiyet kaybı
    # 71.179'u 71.179'a indirip 100% yükü taşırıyordu → alt-sınır/atama hatası.
    return gross * (usable_factor_pct / 100.0)


# ════════════════════════════════════════════════════════════════════
# pack_floor — Maximal Rectangles + Bottom-Left (FE _packFloor portu)
# ════════════════════════════════════════════════════════════════════

def pack_floor(items: List[Dict[str, Any]], vL: float, vW: float,
               gap: float, margin: Optional[float]) -> Dict[str, Any]:
    """items: [{'id','w','l','h'}] (w=across/z, l=along/x). Dönüş: placed/unplaced/usedLenCm.
    FE Cronoi_LS_v2.html:6272 ile birebir: serbest-dikdörtgen listesi, Bottom-Left + en-doldurma
    yönelim seçimi (BSSF DEĞİL), kalanı maksimal alt-dikdörtgenlere böl + prune."""
    m = 1.0 if margin is None else margin
    g = gap or 0
    Lmax = vL - 2 * m
    Wmax = vW - 2 * m
    placed: List[Dict[str, Any]] = []
    unplaced: List[Any] = []
    free: List[Dict[str, float]] = [{"x": 0.0, "z": 0.0, "l": Lmax, "w": Wmax}]

    def contains(a, b) -> bool:
        return (a["x"] <= b["x"] + EPS and a["z"] <= b["z"] + EPS and
                a["x"] + a["l"] >= b["x"] + b["l"] - EPS and
                a["z"] + a["w"] >= b["z"] + b["w"] - EPS)

    def prune(rects):
        out = []
        for i in range(len(rects)):
            if rects[i]["l"] <= EPS or rects[i]["w"] <= EPS:
                continue
            inside = False
            for j in range(len(rects)):
                if i == j:
                    continue
                if contains(rects[j], rects[i]) and not (i < j and contains(rects[i], rects[j])):
                    inside = True
                    break
            if not inside:
                out.append(rects[i])
        return out

    # Büyük ayak izleri önce (alan azalan) — MR için en iyi
    srt = sorted(items, key=lambda it: -(it["l"] * it["w"]))

    for it in srt:
        oris = [{"along": it["l"], "across": it["w"], "rot": 0}]
        if abs(it["l"] - it["w"]) > EPS:
            oris.append({"along": it["w"], "across": it["l"], "rot": 90})

        best = None
        for r in free:
            for o in oris:
                if o["along"] <= r["l"] + EPS and o["across"] <= r["w"] + EPS:
                    w_cnt = math.floor((r["w"] + EPS) / o["across"])
                    w_waste = r["w"] - w_cnt * o["across"]
                    better = (
                        best is None or
                        r["x"] < best["rx"] - EPS or
                        (abs(r["x"] - best["rx"]) < EPS and r["z"] < best["rz"] - EPS) or
                        (abs(r["x"] - best["rx"]) < EPS and abs(r["z"] - best["rz"]) < EPS and
                         (w_waste < best["wWaste"] - EPS or
                          (abs(w_waste - best["wWaste"]) < EPS and w_cnt > best["wCnt"]) or
                          (abs(w_waste - best["wWaste"]) < EPS and w_cnt == best["wCnt"] and
                           o["across"] < best["across"] - EPS)))
                    )
                    if better:
                        best = {"rx": r["x"], "rz": r["z"], "along": o["along"],
                                "across": o["across"], "rot": o["rot"],
                                "wWaste": w_waste, "wCnt": w_cnt}
        if best is None:
            unplaced.append(it["id"])
            continue

        px, pz = best["rx"], best["rz"]
        placed.append({
            "id": it["id"], "rotDeg": best["rot"], "wCm": best["across"], "lCm": best["along"],
            "xCm": -vL / 2 + m + px + best["along"] / 2,
            "zCm": -vW / 2 + m + pz + best["across"] / 2,
        })

        ix0, iz0 = px, pz
        ix1, iz1 = px + best["along"] + g, pz + best["across"] + g
        nxt = []
        for r in free:
            if (ix0 >= r["x"] + r["l"] - EPS or ix1 <= r["x"] + EPS or
                    iz0 >= r["z"] + r["w"] - EPS or iz1 <= r["z"] + EPS):
                nxt.append(r)
                continue
            if r["x"] < ix0 - EPS:
                nxt.append({"x": r["x"], "z": r["z"], "l": ix0 - r["x"], "w": r["w"]})
            if r["x"] + r["l"] > ix1 + EPS:
                nxt.append({"x": ix1, "z": r["z"], "l": r["x"] + r["l"] - ix1, "w": r["w"]})
            if r["z"] < iz0 - EPS:
                nxt.append({"x": r["x"], "z": r["z"], "l": r["l"], "w": iz0 - r["z"]})
            if r["z"] + r["w"] > iz1 + EPS:
                nxt.append({"x": r["x"], "z": iz1, "l": r["l"], "w": r["z"] + r["w"] - iz1})
        free = prune(nxt)

    used_len = (max(p["xCm"] + p["lCm"] / 2 for p in placed) - (-vL / 2 + m)) if placed else 0.0
    return {"placed": placed, "unplaced": unplaced, "usedLenCm": used_len}


# ════════════════════════════════════════════════════════════════════
# Dikey istif (FE _stackPallets / _canStackPallet portu)
# ════════════════════════════════════════════════════════════════════

_BLOCK_BOTTOM = {"fragile", "no_stack", "must_top", "this_side_up", "vertical"}


def can_stack_pallet(bottom: FleetPallet, top: FleetPallet, remaining_h: float) -> bool:
    if bottom.stackable is False or top.stackable is False:
        return False
    bc = _norm_constraints(bottom.constraints)
    tc = _norm_constraints(top.constraints)
    if any(c in _BLOCK_BOTTOM for c in bc):
        return False
    if "must_bottom" in tc:
        return False
    if top.w_cm > bottom.w_cm * 1.02 + 1e-6 or top.l_cm > bottom.l_cm * 1.02 + 1e-6:
        return False
    if (top.weight_kg or 0) > (bottom.weight_kg or 0) + 1e-6:   # ağır alta
        return False
    return top.h_cm <= remaining_h + 1e-6


def _col_new(p: FleetPallet) -> Dict[str, Any]:
    return {"objs": [p], "usedH": p.h_cm, "weight": p.weight_kg or 0.0,
            "volume": p.volume_m3 or 0.0, "wCm": p.w_cm, "lCm": p.l_cm}


def stack_pallets(pallets: List[FleetPallet], veh_h_cm: float) -> List[Dict[str, Any]]:
    """Paletleri araç iç yüksekliğine göre dikey SÜTUNLARA böl. Her sütun = bir zemin ayak izi.
    Sıra: footprint anahtarı → ağır önce (sütun tabanı) → yüksek önce (FE ile aynı)."""
    def fkey(p: FleetPallet) -> str:
        return f"{round(p.w_cm)}x{round(p.l_cm)}"
    srt = sorted(pallets, key=lambda p: (fkey(p), -(p.weight_kg or 0.0), -(p.h_cm or 0.0)))
    cols: List[Dict[str, Any]] = []
    for p in srt:
        placed = False
        for col in cols:
            bottom = col["objs"][-1]
            if can_stack_pallet(bottom, p, veh_h_cm - col["usedH"]):
                col["objs"].append(p)
                col["usedH"] += p.h_cm
                col["weight"] += (p.weight_kg or 0.0)
                col["volume"] += (p.volume_m3 or 0.0)
                col["wCm"] = max(col["wCm"], p.w_cm)
                col["lCm"] = max(col["lCm"], p.l_cm)
                placed = True
                break
        if not placed:
            cols.append(_col_new(p))
    return cols


# ── Width-pattern blokları (FE _buildRows portu) ──
def build_rows(columns: List[Dict[str, Any]], Wcm: float, gap: float) -> List[Dict[str, Any]]:
    rem = list(columns)
    rows: List[Dict[str, Any]] = []
    guard = 0
    while rem and guard < 20000:
        guard += 1
        rem.sort(key=lambda c: -c["wCm"])
        seed = rem.pop(0)
        row = {"objs": list(seed["objs"]), "wCm": seed["wCm"], "lCm": seed["lCm"],
               "weight": seed["weight"], "volume": seed["volume"]}
        added = True
        while added:
            added = False
            rem_w = Wcm - row["wCm"] - gap
            pick, pick_idx = None, -1
            for i, c in enumerate(rem):
                if c["wCm"] <= rem_w + 1e-6:
                    if (pick is None or
                            abs(c["lCm"] - row["lCm"]) < abs(pick["lCm"] - row["lCm"]) - 1e-6 or
                            (abs(abs(c["lCm"] - row["lCm"]) - abs(pick["lCm"] - row["lCm"])) < 1e-6 and
                             c["wCm"] > pick["wCm"])):
                        pick, pick_idx = c, i
            if pick is not None:
                rem.pop(pick_idx)
                row["objs"].extend(pick["objs"])
                row["wCm"] += gap + pick["wCm"]
                row["lCm"] = max(row["lCm"], pick["lCm"])
                row["weight"] += pick["weight"]
                row["volume"] += pick["volume"]
                added = True
        rows.append(row)
    return rows


# ════════════════════════════════════════════════════════════════════
# Filo kurucu (FE _buildFleetOfType portu) — tek araç tipi
# ════════════════════════════════════════════════════════════════════

def _col_items(cols: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # NOT: row-block'larda (build_rows) usedH yoktur; pack_floor h'yi kullanmaz → güvenli get.
    return [{"id": i, "w": c["wCm"], "l": c["lCm"], "h": c.get("usedH", 0)} for i, c in enumerate(cols)]


def _floor_fits(cols: List[Dict[str, Any]], col: Dict[str, Any],
                vt: FleetVehicleType, gap: float, margin: float = 1.0) -> bool:
    # Ucuz alan ön-elemesi (gerekli koşul): toplam ayak izi kullanılabilir zemini aşıyorsa
    # pack_floor da reddederdi → pahalı MR paketlemeyi hiç çağırma (büyük hız kazancı, sonuç aynı).
    usable = max(1.0, (vt.length_cm - 2 * margin) * (vt.width_cm - 2 * margin))
    area = col["wCm"] * col["lCm"] + sum(c["wCm"] * c["lCm"] for c in cols)
    if area > usable + EPS:
        return False
    res = pack_floor(_col_items(cols + [col]), vt.length_cm, vt.width_cm, gap, margin)
    return len(res["unplaced"]) == 0


def _mk_veh(col: Dict[str, Any], vt: FleetVehicleType) -> Dict[str, Any]:
    return {
        "code": vt.id, "type": vt.type, "name": vt.name, "icon": vt.icon,
        "length": vt.length_cm, "width": vt.width_cm, "height": vt.height_cm,
        "maxWeight": vt.max_weight_kg, "cost": vt.total_cost,
        "cols": [col],
        "assignedPallets": [p.id for p in col["objs"]],
        "palletObjs": list(col["objs"]),
        "currentWeight": col["weight"], "currentVolume": col["volume"],
    }


def _add_col(v: Dict[str, Any], col: Dict[str, Any]) -> None:
    v["cols"].append(col)
    for p in col["objs"]:
        v["assignedPallets"].append(p.id)
        v["palletObjs"].append(p)
    v["currentWeight"] += col["weight"]
    v["currentVolume"] += col["volume"]


def _run_ffd(ordered_cols: List[Dict[str, Any]], vt: FleetVehicleType,
             gap: float, usable_vol: float, margin: float = 1.0) -> List[Dict[str, Any]]:
    """Tek FFD koşusu (best-fit) + konsolidasyon pası (FE runFFD portu)."""
    fleet: List[Dict[str, Any]] = []
    for col in ordered_cols:
        best = None
        for v in fleet:
            if (v["currentWeight"] + col["weight"] <= vt.max_weight_kg + EPS and
                    v["currentVolume"] + col["volume"] <= usable_vol + EPS and
                    _floor_fits(v["cols"], col, vt, gap, margin)):
                if best is None or v["currentVolume"] > best["currentVolume"]:
                    best = v
        if best is not None:
            _add_col(best, col)
        else:
            fleet.append(_mk_veh(col, vt))

    def floor_area(v):
        return sum(c["wCm"] * c["lCm"] for c in v["cols"])

    shrunk, guard = True, 0
    while shrunk and len(fleet) > 1 and guard < 200:
        guard += 1
        shrunk = False
        vi = 0
        for i in range(1, len(fleet)):
            if floor_area(fleet[i]) < floor_area(fleet[vi]):
                vi = i
        victim = fleet[vi]
        others = [v for i, v in enumerate(fleet) if i != vi]
        work = [{"ref": v, "cols": list(v["cols"]), "added": [],
                 "w": v["currentWeight"], "vol": v["currentVolume"]} for v in others]
        all_fit = True
        for col in victim["cols"]:
            t = None
            col_area = col["wCm"] * col["lCm"]
            usable_floor_v = max(1.0, (vt.length_cm - 2 * margin) * (vt.width_cm - 2 * margin))
            for w in work:
                if (w["w"] + col["weight"] <= vt.max_weight_kg + EPS and
                        w["vol"] + col["volume"] <= usable_vol + EPS and
                        col_area + sum(c["wCm"] * c["lCm"] for c in w["cols"]) <= usable_floor_v + EPS and
                        len(pack_floor(_col_items(w["cols"] + [col]), vt.length_cm,
                                       vt.width_cm, gap, margin)["unplaced"]) == 0):
                    if t is None or w["vol"] > t["vol"]:
                        t = w
            if t is None:
                all_fit = False
                break
            t["cols"].append(col)
            t["added"].append(col)
            t["w"] += col["weight"]
            t["vol"] += col["volume"]
        if all_fit:
            for w in work:
                for col in w["added"]:
                    _add_col(w["ref"], col)
            fleet.pop(vi)
            shrunk = True
    return fleet


def _forward_fill(fleet: List[Dict[str, Any]], vt: FleetVehicleType,
                  gap: float, usable_vol: float, margin: float = 1.0) -> List[Dict[str, Any]]:
    """Boşluğu son araca yığ (FE ileri-doldurma portu). Sayıyı ARTIRMAZ; son araç boşalırsa düşer."""
    def floor_area(v):
        return sum(c["wCm"] * c["lCm"] for c in v["cols"])

    def remove_col(v, col):
        if col in v["cols"]:
            v["cols"].remove(col)
        for p in col["objs"]:
            if p.id in v["assignedPallets"]:
                v["assignedPallets"].remove(p.id)
            if p in v["palletObjs"]:
                v["palletObjs"].remove(p)
        v["currentWeight"] -= col["weight"]
        v["currentVolume"] -= col["volume"]

    fleet.sort(key=floor_area, reverse=True)
    moved, guard = True, 0
    while moved and guard < 500:
        guard += 1
        moved = False
        for i in range(len(fleet) - 1):
            target = fleet[i]
            for j in range(len(fleet) - 1, i, -1):
                donor = fleet[j]
                for k in range(len(donor["cols"]) - 1, -1, -1):
                    col = donor["cols"][k]
                    if (target["currentWeight"] + col["weight"] <= vt.max_weight_kg + EPS and
                            target["currentVolume"] + col["volume"] <= usable_vol + EPS and
                            _floor_fits(target["cols"], col, vt, gap, margin)):
                        remove_col(donor, col)
                        _add_col(target, col)
                        moved = True
    return [v for v in fleet if len(v["cols"]) > 0]


def _finalize(fleet: List[Dict[str, Any]], vt: FleetVehicleType, gap: float,
              margin: float = 1.0) -> None:
    """LDM (yükleme metresi) + id ata."""
    for idx, v in enumerate(fleet):
        pf = pack_floor(_col_items(v["cols"]), vt.length_cm, vt.width_cm, gap, margin)
        v["usedLenCm"] = pf.get("usedLenCm", 0.0)
        v["ldm"] = round(v["usedLenCm"] / 100.0, 2)
        v["ldmFillPct"] = round(v["usedLenCm"] / vt.length_cm * 100.0, 1) if vt.length_cm else 0.0
        v["id"] = idx + 1


def _gap_for(settings) -> float:
    raw = getattr(settings, "pallet_gap_cm", 1)
    if raw is None:
        raw = 1
    return max(0.0, min(raw, 1))


def _margin_for(settings) -> float:
    """Duvar payı (cm). Varsayılan 1 (forklift güvenlik clearance'ı); tailored/sıfır-fire
    yükler için 0 verilebilir (wall_margin_cm=0 → matematiksel kusursuz dolum mümkün)."""
    raw = getattr(settings, "wall_margin_cm", 1.0)
    if raw is None:
        raw = 1.0
    return max(0.0, float(raw))


# ════════════════════════════════════════════════════════════════════
# AKS / KÜTLE MERKEZİ DENGELEME — moment-duyarlı boylamasına yerleştirme
# ════════════════════════════════════════════════════════════════════
# Kantar moment kapısı (doküman Test 3): yükün boylamasına kütle merkezi (COG) hedef
# ön-aks oranına çekilir. KRİTİK GÜVENLİK: dengeleyici pack_floor'un slot GEOMETRİSİNİ
# HİÇ değiştirmez — yalnızca AYNI ayak izine sahip slotlar arasında sütun içeriğini takas
# eder. Böylece çakışma/taşma/araç-sayısı/LDM birebir korunur (render==kapasite r21c),
# yalnızca ağırlık DAĞILIMI hedefe yaklaşır. Deterministik (steepest-descent, RNG yok).

def _akey(c: Dict[str, Any]) -> Tuple[float, float]:
    return (round(c["wCm"], 1), round(c["lCm"], 1))


def balance_axle_vehicle(vehicle: Dict[str, Any], vt: FleetVehicleType,
                         gap: float, margin: float, target_front_pct: float) -> None:
    """Tek aracın COG'unu hedef ön-aks oranına çek (ayak-izi-eşli slot takasıyla)."""
    cols = vehicle["cols"]
    if len(cols) < 2:
        return
    L = vt.length_cm
    pf = pack_floor(_col_items(cols), vt.length_cm, vt.width_cm, gap, margin)
    placed = pf["placed"]
    if len(placed) < 2:
        return
    # slot = (emission sırası, ön-duvardan x, ayak izi anahtarı, mevcut sütun)
    slots = [{"x": p["xCm"] + L / 2.0, "akey": _akey(cols[p["id"]]), "col": cols[p["id"]]}
             for p in placed]
    W = sum(s["col"]["weight"] for s in slots)
    if W <= EPS:
        return
    M = sum(s["col"]["weight"] * s["x"] for s in slots)        # toplam moment (ön duvardan)
    target_M = (1.0 - target_front_pct / 100.0) * L * W         # hedef: front_pct → cog=(1-fp)·L
    n = len(slots)
    guard = 0
    improved = True
    while improved and guard < 4000:
        guard += 1
        improved = False
        cur = abs(M - target_M)
        best = None   # (yeni_fark, i, j, dM)
        for i in range(n):
            xi, wi = slots[i]["x"], slots[i]["col"]["weight"]
            ak = slots[i]["akey"]
            for j in range(i + 1, n):
                if slots[j]["akey"] != ak:
                    continue
                wj = slots[j]["col"]["weight"]
                if abs(wi - wj) < EPS:
                    continue
                dM = (wj - wi) * (xi - slots[j]["x"])           # i↔j takasının moment etkisi
                d = abs(M + dM - target_M)
                if d < cur - 1e-6 and (best is None or d < best[0]):
                    best = (d, i, j, dM)
        if best:
            _, i, j, dM = best
            slots[i]["col"], slots[j]["col"] = slots[j]["col"], slots[i]["col"]
            M += dM
            improved = True

    # Yeni sütun sırası: ayak-izi grubuna göre slot emission sırasında atanmış sütunlarla.
    # pack_floor area-desc STABLE sıralar → grup içi sıra korunur → her slot atanan sütunu alır.
    groups: Dict[Tuple[float, float], List[Dict[str, Any]]] = {}
    for s in slots:
        groups.setdefault(s["akey"], []).append(s["col"])
    new_cols = [c for ak in groups for c in groups[ak]]
    vehicle["cols"] = new_cols
    vehicle["assignedPallets"] = [p.id for c in new_cols for p in c["objs"]]
    vehicle["palletObjs"] = [p for c in new_cols for p in c["objs"]]


def balance_fleet_axle(fleet: List[Dict[str, Any]], vt: FleetVehicleType,
                       gap: float, margin: float, settings) -> None:
    """Filodaki her aracı aks-dengele (ayar `balance_axle_load=False` ile kapatılabilir)."""
    if not getattr(settings, "balance_axle_load", True):
        return
    target = float(getattr(settings, "weight_front_ratio_pct", 60.0) or 60.0)
    for v in fleet:
        balance_axle_vehicle(v, vt, gap, margin, target)


def vehicle_axle_front_pct(vehicle: Dict[str, Any], vt: FleetVehicleType,
                           gap: float = 1.0, margin: float = 1.0) -> Optional[float]:
    """Aracın GERÇEK boylamasına ön-aks yük yüzdesi (pack_floor pozisyonlarından).
    Model = optimizer._compute_weight_balance ile aynı: ön aks payı = (1 - cog_x/L)·100."""
    cols = vehicle.get("cols") or []
    if not cols or vt.length_cm <= 0:
        return None
    pf = pack_floor(_col_items(cols), vt.length_cm, vt.width_cm, gap, margin)
    placed = pf["placed"]
    W = sum(cols[p["id"]]["weight"] for p in placed)
    if W <= EPS:
        return None
    L = vt.length_cm
    cog_x = sum(cols[p["id"]]["weight"] * (p["xCm"] + L / 2.0) for p in placed) / W
    return (1.0 - cog_x / L) * 100.0


# ── Aday sıralamalar (FE 6 strateji + rows) ──
def _seed_orderings(columns: List[Dict[str, Any]], vt: FleetVehicleType,
                    gap: float, margin: float = 1.0) -> List[List[Dict[str, Any]]]:
    row_blocks = build_rows(columns, vt.width_cm - 2 * margin, gap)
    return [
        sorted(columns, key=lambda c: (-c["wCm"], -c["lCm"], -c["weight"])),
        sorted(columns, key=lambda c: (-c["lCm"], -c["wCm"])),
        sorted(columns, key=lambda c: (-(c["wCm"] * c["lCm"]),)),
        sorted(columns, key=lambda c: (-c["weight"], -(c["wCm"] * c["lCm"]))),
        sorted(row_blocks, key=lambda c: (-c["lCm"], -c["wCm"])),
        sorted(row_blocks, key=lambda c: (-c["wCm"], -c["lCm"])),
    ]


def _grasp_order(columns: List[Dict[str, Any]], rng: random.Random,
                 alpha: float = 0.35) -> List[Dict[str, Any]]:
    """GRASP: kısıtlı aday listesinden (RCL, alan-azalan üst %alpha) rastgele seç."""
    rem = list(columns)
    order: List[Dict[str, Any]] = []
    while rem:
        rem.sort(key=lambda c: -(c["wCm"] * c["lCm"]))
        k = max(1, int(len(rem) * alpha))
        order.append(rem.pop(rng.randrange(k)))
    return order


def _lower_bound(columns: List[Dict[str, Any]], vt: FleetVehicleType,
                 usable_vol: float, gap: float, margin: float = 1.0) -> int:
    """Araç sayısı için kanıtlanabilir alt sınır = max(zemin, ağırlık, hacim)."""
    usable_floor = max(1.0, (vt.length_cm - 2 * margin) * (vt.width_cm - 2 * margin))
    total_floor = sum(c["wCm"] * c["lCm"] for c in columns)
    total_weight = sum(c["weight"] for c in columns)
    total_vol = sum(c["volume"] for c in columns)
    lb_floor = math.ceil(total_floor / usable_floor - 1e-9)
    lb_weight = math.ceil(total_weight / vt.max_weight_kg - 1e-9) if vt.max_weight_kg > 0 else 1
    lb_vol = math.ceil(total_vol / usable_vol - 1e-9) if usable_vol > 0 else 1
    return max(1, lb_floor, lb_weight, lb_vol)


# ════════════════════════════════════════════════════════════════════
# FİLO KATMANI ALNS — domain çözüm + destroy/repair operatörleri (V10)
# ════════════════════════════════════════════════════════════════════
# Çözüm = sütun→araç ataması. Her araç DAİMA floor-fit geçerli (pack_floor.unplaced==[]).
# Operatörler sütunları araçlardan "havuz"a çıkarır (destroy) ve geçerli araçlara geri
# yerleştirir (repair). Araç sayısını düşürmek WorstVehicleDestroy + iyi repair ile olur.

def _usable_floor(vt: FleetVehicleType, margin: float = 1.0) -> float:
    return max(1.0, (vt.length_cm - 2 * margin) * (vt.width_cm - 2 * margin))


def _veh_area(cols: List[Dict[str, Any]]) -> float:
    return sum(c["wCm"] * c["lCm"] for c in cols)


def _veh_weight(cols: List[Dict[str, Any]]) -> float:
    return sum(c["weight"] for c in cols)


def _veh_volume(cols: List[Dict[str, Any]]) -> float:
    return sum(c["volume"] for c in cols)


def _cols_floor_ok(cols: List[Dict[str, Any]], vt: FleetVehicleType, gap: float,
                   margin: float = 1.0) -> bool:
    return len(pack_floor(_col_items(cols), vt.length_cm, vt.width_cm, gap, margin)["unplaced"]) == 0


def _can_add(cols: List[Dict[str, Any]], col: Dict[str, Any],
             vt: FleetVehicleType, gap: float, usable_vol: float, margin: float = 1.0) -> bool:
    return (_veh_weight(cols) + col["weight"] <= vt.max_weight_kg + 1e-6 and
            _veh_volume(cols) + col["volume"] <= usable_vol + 1e-6 and
            _veh_area(cols) + col["wCm"] * col["lCm"] <= _usable_floor(vt, margin) + 1e-6 and
            _cols_floor_ok(cols + [col], vt, gap, margin))


class _FleetSolution:
    """ALNS çözümü: araç başına sütun listesi + yerleştirilmemiş sütun havuzu."""
    __slots__ = ("vehicles", "pool", "vt", "gap", "usable_vol", "margin")

    def __init__(self, vehicles: List[List[Dict[str, Any]]], pool: List[Dict[str, Any]],
                 vt: FleetVehicleType, gap: float, usable_vol: float, margin: float = 1.0):
        self.vehicles = vehicles
        self.pool = pool
        self.vt = vt
        self.gap = gap
        self.usable_vol = usable_vol
        self.margin = margin

    @classmethod
    def from_fleet(cls, fleet: List[Dict[str, Any]], vt: FleetVehicleType,
                   gap: float, usable_vol: float, margin: float = 1.0) -> "_FleetSolution":
        return cls([list(v["cols"]) for v in fleet], [], vt, gap, usable_vol, margin)

    def copy(self) -> "_FleetSolution":
        # Sütunlar değişmez (içerikleri asla mutasyona uğramaz) → sığ kopya yeterli
        return _FleetSolution([list(c) for c in self.vehicles], list(self.pool),
                              self.vt, self.gap, self.usable_vol, self.margin)

    def cost(self) -> float:
        if self.pool:
            return math.inf
        nonempty = [c for c in self.vehicles if c]
        if not nonempty:
            return 0.0
        uf = _usable_floor(self.vt, self.margin)
        fills = [min(1.0, _veh_area(c) / uf) for c in nonempty]
        # Araç sayısı baskın + doluluk ince-ayar (eşit araç → daha dolu/derli toplu tercih)
        return len(nonempty) + (1.0 - sum(fills) / len(fills)) * 0.001

    def to_fleet(self) -> List[Dict[str, Any]]:
        fleet: List[Dict[str, Any]] = []
        for cols in self.vehicles:
            if not cols:
                continue
            v = _mk_veh(cols[0], self.vt)
            for c in cols[1:]:
                _add_col(v, c)
            fleet.append(v)
        return fleet


def _place_into_vehicle_or_new(sol: _FleetSolution, col: Dict[str, Any], idx: Optional[int]):
    if idx is not None:
        sol.vehicles[idx].append(col)
        return
    for i, cols in enumerate(sol.vehicles):   # boş slotu yeniden kullan
        if not cols:
            sol.vehicles[i] = [col]
            return
    sol.vehicles.append([col])


# ── Destroy operatörleri ──
def _destroy_worst_vehicle(sol: _FleetSolution, rng: random.Random, degree: float):
    nonempty = [i for i, c in enumerate(sol.vehicles) if c]
    if len(nonempty) <= 1:
        return sol
    k = min(max(1, round(degree * len(nonempty))), len(nonempty) - 1)
    ranked = sorted(nonempty, key=lambda i: _veh_area(sol.vehicles[i]))   # en boş önce
    for i in ranked[:k]:
        sol.pool.extend(sol.vehicles[i])
        sol.vehicles[i] = []
    return sol


def _destroy_random_cols(sol: _FleetSolution, rng: random.Random, degree: float):
    all_cols = [(i, j) for i, cols in enumerate(sol.vehicles) for j in range(len(cols))]
    if not all_cols:
        return sol
    q = min(max(1, round(degree * len(all_cols))), len(all_cols))
    picks = rng.sample(all_cols, q)
    byv: Dict[int, List[int]] = {}
    for i, j in picks:
        byv.setdefault(i, []).append(j)
    for i, js in byv.items():
        for j in sorted(js, reverse=True):
            sol.pool.append(sol.vehicles[i].pop(j))
    return sol


def _destroy_cluster(sol: _FleetSolution, rng: random.Random, degree: float):
    all_cols = [(i, j, sol.vehicles[i][j]) for i, cols in enumerate(sol.vehicles)
                for j in range(len(cols))]
    if not all_cols:
        return sol
    seed = rng.choice(all_cols)
    sw, sl = seed[2]["wCm"], seed[2]["lCm"]
    ranked = sorted(all_cols, key=lambda t: abs(t[2]["wCm"] - sw) + abs(t[2]["lCm"] - sl))
    q = min(max(1, round(degree * len(all_cols))), len(all_cols))
    byv: Dict[int, List[int]] = {}
    for i, j, _c in ranked[:q]:
        byv.setdefault(i, []).append(j)
    for i, js in byv.items():
        for j in sorted(js, reverse=True):
            sol.pool.append(sol.vehicles[i].pop(j))
    return sol


# ── Repair operatörleri ──
def _repair_best(sol: _FleetSolution, rng: random.Random):
    pool = sorted(sol.pool, key=lambda c: (-(c["wCm"] * c["lCm"]), rng.random()))
    sol.pool = []
    uf = _usable_floor(sol.vt, sol.margin)
    for col in pool:
        best_i, best_slack = None, None
        for i, cols in enumerate(sol.vehicles):
            if not cols:
                continue
            if _can_add(cols, col, sol.vt, sol.gap, sol.usable_vol, sol.margin):
                slack = uf - (_veh_area(cols) + col["wCm"] * col["lCm"])
                if best_i is None or slack < best_slack:
                    best_i, best_slack = i, slack
        _place_into_vehicle_or_new(sol, col, best_i)
    return sol


def _repair_regret(sol: _FleetSolution, rng: random.Random):
    pool = list(sol.pool)
    sol.pool = []
    uf = _usable_floor(sol.vt, sol.margin)
    BIG = 1e9
    while pool:
        best_choice = None   # (key, pool_idx, target_vehicle_or_None)
        for pi, col in enumerate(pool):
            costs = []
            for i, cols in enumerate(sol.vehicles):
                if not cols:
                    continue
                if _can_add(cols, col, sol.vt, sol.gap, sol.usable_vol, sol.margin):
                    costs.append((uf - (_veh_area(cols) + col["wCm"] * col["lCm"]), i))
            costs.sort()
            if costs:
                best_cost, best_v = costs[0]
                second = costs[1][0] if len(costs) > 1 else BIG + col["wCm"] * col["lCm"]
            else:
                best_cost, best_v = BIG + col["wCm"] * col["lCm"], None
                second = best_cost
            regret = second - best_cost
            key = (regret, -(col["wCm"] * col["lCm"]))
            if best_choice is None or key > best_choice[0]:
                best_choice = (key, pi, best_v)
        _, pi, target = best_choice
        col = pool.pop(pi)
        _place_into_vehicle_or_new(sol, col, target)
    return sol


_FLEET_DESTROY = [("worst_vehicle", _destroy_worst_vehicle),
                  ("random_cols", _destroy_random_cols),
                  ("cluster", _destroy_cluster)]
_FLEET_REPAIR = [("best_insert", _repair_best), ("regret", _repair_regret)]


# ════════════════════════════════════════════════════════════════════
# search_fleet_of_type — ALNS (başlangıç=seed+FFD) + alt-sınır + bütçe
# ════════════════════════════════════════════════════════════════════

def search_fleet_of_type(pallets: List[FleetPallet], vt: FleetVehicleType, settings,
                         deadline: float, rng: random.Random,
                         usable_factor_pct: float = 90.0) -> Optional[Dict[str, Any]]:
    """Bir araç tipi için EN AZ araçlı filoyu ALNS ile ara. Dönüş: {fleet, count,
    lower_bound, proven_optimal, iterations} ya da tip uygun değilse None.
    DETERMİNİZM: tohumlu rng + iterasyon-tabanlı durdurma (deadline = güvenlik tavanı)."""
    gap = _gap_for(settings)
    margin = _margin_for(settings)
    usable_vol = veh_usable_vol(vt, usable_factor_pct)

    columns = stack_pallets(pallets, vt.height_cm)
    for c in columns:   # Tip uygunluğu: her sütun boş araca sığmalı
        if len(pack_floor(_col_items([c]), vt.length_cm, vt.width_cm, gap, margin)["unplaced"]) > 0:
            return None

    lb = _lower_bound(columns, vt, usable_vol, gap, margin)

    # ── Başlangıç çözümü: en iyi seed sıralaması + ileri-doldurma (eski GRASP'ın çekirdeği) ──
    best_init: Optional[List[Dict[str, Any]]] = None
    for order in _seed_orderings(columns, vt, gap, margin):
        f = _run_ffd(order, vt, gap, usable_vol, margin)
        if best_init is None or len(f) < len(best_init):
            best_init = f
        if len(best_init) <= lb:
            break
    init = _forward_fill(best_init, vt, gap, usable_vol, margin)

    # Zaten kanıtlanmış optimum → ALNS gereksiz
    if len(init) <= lb:
        balance_fleet_axle(init, vt, gap, margin, settings)
        _finalize(init, vt, gap, margin)
        return {"fleet": init, "count": len(init), "lower_bound": lb,
                "proven_optimal": True, "iterations": 0, "usable_vol": usable_vol}

    # ── ALNS arama (tüm planı ara, geri-alınabilir, en iyiyi tut) ──
    sol0 = _FleetSolution.from_fleet(init, vt, gap, usable_vol, margin)
    n = len(columns)
    max_iter = max(200, min(3000, n * 60))
    best_sol, stats = run_alns(
        sol0, _FLEET_DESTROY, _FLEET_REPAIR, rng,
        max_iter=max_iter, no_improve_limit=max(100, n * 15),
        convergence_patience=max(50, n),   # iyileşme durduysa boşuna iterasyon harcama (deterministik)
        deadline=deadline, target_cost=lb + 0.5,
        sa_start_temp=0.05, sa_cooling=0.999)

    fleet = best_sol.to_fleet()
    fleet = _forward_fill(fleet, vt, gap, usable_vol, margin)
    balance_fleet_axle(fleet, vt, gap, margin, settings)
    _finalize(fleet, vt, gap, margin)

    return {
        "fleet": fleet,
        "count": len(fleet),
        "lower_bound": lb,
        "proven_optimal": len(fleet) <= lb or stats.reached_target,
        "iterations": stats.iterations,
        "usable_vol": usable_vol,
    }


# ════════════════════════════════════════════════════════════════════
# optimize_fleet — tüm tipleri değerlendir, en ucuz uygun filoyu seç
# ════════════════════════════════════════════════════════════════════

def evaluate_all_fleet_types(pallets: List[FleetPallet], vehicle_types: List[FleetVehicleType],
                             settings, time_budget_s: float = 3.0,
                             usable_factor_pct: float = 90.0,
                             seed: int = 12345) -> List[Dict[str, Any]]:
    """FE _evalAllFleets karşılığı: her araç tipinden tek-tip filo kur (solver aramasıyla).
    Dönüş: uygun tiplerin sonuç listesi (her birinde fleet/count/total_cost/vt/lower_bound …).
    Süre bütçesi tipler arasında paylaştırılır."""
    if not pallets or not vehicle_types:
        return []
    time_budget_s = max(0.3, min(time_budget_s, 5.0))
    per_type = max(0.25, time_budget_s / max(1, len(vehicle_types)))

    results: List[Dict[str, Any]] = []
    for i, vt in enumerate(vehicle_types):
        # Yükseklik uyumu: fiziksel yüksekliği araç içini aşan palet varsa tip elenir
        if any(p.h_cm > vt.height_cm + 1e-6 for p in pallets):
            continue
        # Tip-başına deterministik RNG: aynı girdi → birebir aynı sonuç (tip sırasından bağımsız)
        rng = random.Random((seed * 1_000_003) ^ (i + 1))
        deadline = time.time() + per_type
        res = search_fleet_of_type(pallets, vt, settings, deadline, rng, usable_factor_pct)
        if not res or not res["fleet"]:
            continue
        res["vt"] = vt
        res["total_cost"] = sum(v["cost"] for v in res["fleet"])
        res["avg_ldm_fill"] = sum(v.get("ldmFillPct", 0) for v in res["fleet"]) / max(1, len(res["fleet"]))
        results.append(res)
    return results


def optimize_fleet(pallets: List[FleetPallet], vehicle_types: List[FleetVehicleType],
                   settings, time_budget_s: float = 3.0,
                   usable_factor_pct: float = 90.0,
                   seed: int = 12345) -> Optional[Dict[str, Any]]:
    """En düşük (araç sayısı → maliyet → en yüksek doluluk) uygun filoyu döndür."""
    results = evaluate_all_fleet_types(pallets, vehicle_types, settings,
                                       time_budget_s, usable_factor_pct, seed)
    if not results:
        return None
    results.sort(key=lambda r: (r["count"], r["total_cost"], -r["avg_ldm_fill"]))
    return results[0]
