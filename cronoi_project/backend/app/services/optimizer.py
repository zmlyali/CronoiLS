"""
Cronoi LS — 3D Bin Packing Optimizer v10.0
Rect-Skyline · Z-up · CoG-Balanced · Full OPTIMIZER_SPEC.md

GERÇEK TEK HEDEF:
  minimize N_vehicles
  Palet sayısını minimize et → her paleti doldur

Koordinat Sistemi (Z-up, 3D Bin Packing Standardı):
  X ekseni → palet genişliği (width_cm),  sol↔sağ
  Y ekseni → palet uzunluğu (length_cm), ön↔arka
  Z ekseni → yükseklik (max_height_cm),   zemin↑yukarı

  placed_rects format: {"x", "y", "z", "dx", "dy", "dz"}
  PackedItem: pos_x=width, pos_y=depth, pos_z=height

v10.0 (Z-up Rect-Skyline):
  - Z-up koordinat sistemi (3D paketleme standardı)
  - VERTICAL_ONLY: ince boyut X (yan yana kitaplık), düşük Z tercih
  - Palet optimizasyonu araç bağımsız (salt palet kısıtları)
  - Local optimum eşiği settings’ten (target_fill_rate_pct)
  - Scored candidate: bitişiklik + CoG + zemin stabilitesi + kenar yakınlığı
  - CoG (Ağırlık Merkezi) kontrolü: palet devrilme riski minimize

Yerleşim Önceliği (BBL — Bottom-Back-Left):
  Z-yönü (zemin → yukarı) → X-yönü (sol → sağ) → Y-yönü (ön → arka)

Parametrik (KURAL-1): Hardcode yok.
Validation (KURAL-2): Her optimizasyon sonrası zorunlu.
KURAL-4: Hard constraint ihlali → REDDEDILIR.
KURAL-5: Tüm parametreler ayarlar ekranından beslenebilir.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Set
from enum import Enum
import math
import uuid
import logging
import time

logger = logging.getLogger(__name__)

# Geriye dönük uyumluluk sabiti
PALLET_BOARD_HEIGHT_CM = 15
DEFAULT_OVERFLOW_TOLERANCE_PCT = 5.0

# ── Yerleşim yönü skor ağırlıkları (KURAL-3) ──
DIRECTION_SCORES = {
    "x_extend": 500,
    "y_new_row": 200,
    "z_stack": 10,
}


# ============================================================
# ENUMS
# ============================================================

class ConstraintType(str, Enum):
    FRAGILE = "fragile"
    HEAVY = "heavy"
    TEMP = "temp"
    NO_STACK = "no_stack"
    MUST_BOTTOM = "must_bottom"
    MUST_TOP = "must_top"
    HORIZONTAL_ONLY = "horizontal_only"
    VERTICAL_ONLY = "vertical_only"
    THIS_SIDE_UP = "this_side_up"
    COLD_CHAIN = "cold_chain"
    HAZMAT = "hazmat"
    KEEP_DRY = "keep_dry"
    LOAD_FIRST = "load_first"
    LOAD_LAST = "load_last"
    VEH_FRONT = "veh_front"
    VEH_REAR = "veh_rear"


class ScenarioStrategy(str, Enum):
    MIN_VEHICLES = "min_vehicles"
    BALANCED = "balanced"
    MAX_EFFICIENCY = "max_efficiency"


WEIGHT_HIERARCHY = {
    ConstraintType.MUST_BOTTOM: 0,
    ConstraintType.HEAVY: 1,
    None: 2,
    ConstraintType.TEMP: 2,
    ConstraintType.FRAGILE: 3,
    ConstraintType.NO_STACK: 3,
    ConstraintType.MUST_TOP: 4,
}

DENSITY_BOTTOM_THRESHOLD = 400
DENSITY_TOP_THRESHOLD = 200


# ============================================================
# OptimizerSettings — KISIM B.4
# ============================================================

@dataclass
class OptimizerSettings:
    """Ayarlar Ekranı > Optimizasyon Sekmesi. Firma bazında override."""
    # Boyut Toleransları
    height_tolerance_pct: float = 5.0
    width_tolerance_pct: float = 5.0
    # Doluluk Hedefleri
    target_fill_rate_pct: float = 85.0
    suggestion_trigger_pct: float = 75.0
    # Algoritma
    max_optimization_time_sec: int = 30
    prefer_fewer_pallets: bool = True
    allow_mixed_orders_on_pallet: bool = True
    allow_mixed_pallet_types: bool = True
    max_iterations: int = 12
    # Fizik & Güvenlik
    max_void_gap_cm: float = 15.0
    weight_front_ratio_pct: float = 60.0
    weight_front_tolerance_pct: float = 5.0
    # McKee & Ambalaj
    packaging_enabled: bool = False
    packaging_thickness_cm: float = 0.4
    humidity_factor: float = 1.0
    stacking_pattern: str = "interlocked"
    # Soğuk Zincir
    reefer_ceiling_clearance_cm: float = 22.0
    reefer_door_clearance_cm: float = 11.0
    # Uluslararası
    enforce_ispm15: bool = False
    # Yerleşim
    height_safety_margin_cm: float = 0.0
    pallet_gap_cm: float = 3.0
    enforce_constraints: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "OptimizerSettings":
        if not d:
            return cls()
        return cls(
            height_tolerance_pct=float(d.get("heightTolerancePct", d.get("height_tolerance_pct", 5.0))),
            width_tolerance_pct=float(d.get("widthTolerancePct", d.get("width_tolerance_pct",
                                      d.get("overflowTolerancePct", d.get("overflow_tolerance_pct", 5.0))))),
            target_fill_rate_pct=float(d.get("targetFillRatePct", d.get("target_fill_rate_pct",
                                       d.get("optimalityTarget", d.get("optimality_target", 85.0))))),
            suggestion_trigger_pct=float(d.get("suggestionTriggerPct", d.get("suggestion_trigger_pct", 75.0))),
            max_optimization_time_sec=int(d.get("maxOptimizationTimeSec", d.get("max_optimization_time_sec", 30))),
            prefer_fewer_pallets=bool(d.get("preferFewerPallets", d.get("prefer_fewer_pallets", True))),
            allow_mixed_orders_on_pallet=bool(d.get("allowMixedOrders", d.get("allow_mixed_orders_on_pallet", True))),
            allow_mixed_pallet_types=bool(d.get("allowMixedPalletTypes", d.get("allow_mixed_pallet_types", True))),
            max_iterations=int(d.get("maxIterations", d.get("max_iterations", 12))),
            max_void_gap_cm=float(d.get("maxVoidGapCm", d.get("max_void_gap_cm", 15.0))),
            weight_front_ratio_pct=float(d.get("weightBalanceFrontPct",
                                         d.get("weightBalanceTarget",
                                               d.get("weight_front_ratio_pct", 60.0)))),
            weight_front_tolerance_pct=float(d.get("weightBalanceTolerance",
                                              d.get("weight_front_tolerance_pct", 5.0))),
            packaging_enabled=bool(d.get("packagingEnabled", d.get("packaging_enabled", False))),
            packaging_thickness_cm=float(d.get("packagingThicknessCm", d.get("packaging_thickness_cm", 0.4))),
            humidity_factor=float(d.get("humidityFactor", d.get("humidity_factor", 1.0))),
            stacking_pattern=str(d.get("stackingPattern", d.get("stacking_pattern", "interlocked"))),
            reefer_ceiling_clearance_cm=float(d.get("reeferCeilingClearanceCm", d.get("reefer_ceiling_clearance_cm", 22.0))),
            reefer_door_clearance_cm=float(d.get("reeferDoorClearanceCm", d.get("reefer_door_clearance_cm", 11.0))),
            enforce_ispm15=bool(d.get("enforceIspm15", d.get("enforce_ispm15", False))),
            height_safety_margin_cm=float(d.get("heightSafetyMargin", d.get("height_safety_margin_cm", 0))),
            pallet_gap_cm=float(d.get("palletGapCm", d.get("pallet_gap_cm", 3))),
            enforce_constraints=bool(d.get("enforceConstraints", d.get("enforce_constraints", True))),
        )


# ── Backward compat alias ──
@dataclass
class OptimizationParams:
    """Geriye dönük uyumluluk. Yeni kod OptimizerSettings kullanır."""
    height_safety_margin_cm: float = 0
    pallet_gap_cm: float = 3
    enforce_constraints: bool = True
    weight_balance_target: float = 0.60
    weight_balance_tolerance: float = 0.10
    max_iterations: int = 12
    optimality_target: float = 90.0
    overflow_tolerance_pct: float = 5.0
    vehicle_max_height_cm: float = 0
    target_fill_rate_pct: float = 85.0
    prefer_fewer_pallets: bool = True
    max_void_gap_cm: float = 15.0
    packaging_enabled: bool = False
    packaging_thickness_cm: float = 0.4
    humidity_factor: float = 1.0
    enforce_ispm15: bool = False
    reefer_ceiling_clearance_cm: float = 22.0
    reefer_door_clearance_cm: float = 11.0

    @classmethod
    def from_dict(cls, d: dict) -> "OptimizationParams":
        if not d:
            return cls()
        wbt_raw = d.get("weightBalanceFrontPct",
                        d.get("weightBalanceTarget",
                              d.get("weight_balance_target", 0.60)))
        wbt = float(wbt_raw) / 100.0 if float(wbt_raw) > 1 else float(wbt_raw)
        wtol_raw = d.get("weightBalanceTolerance",
                         d.get("weight_balance_tolerance", 0.10))
        wtol = float(wtol_raw) / 100.0 if float(wtol_raw) > 1 else float(wtol_raw)

        return cls(
            height_safety_margin_cm=float(d.get("heightSafetyMargin", d.get("height_safety_margin_cm", 0))),
            pallet_gap_cm=float(d.get("palletGapCm", d.get("pallet_gap_cm", 3))),
            enforce_constraints=bool(d.get("enforceConstraints", d.get("enforce_constraints", True))),
            weight_balance_target=wbt,
            weight_balance_tolerance=wtol,
            max_iterations=int(d.get("maxIterations", d.get("max_iterations", 12))),
            optimality_target=float(d.get("optimalityTarget", d.get("optimality_target", 90.0))),
            overflow_tolerance_pct=float(d.get("overflowTolerancePct", d.get("overflow_tolerance_pct", DEFAULT_OVERFLOW_TOLERANCE_PCT))),
            vehicle_max_height_cm=float(d.get("vehicleMaxHeightCm", d.get("vehicle_max_height_cm", 0))),
            target_fill_rate_pct=float(d.get("targetFillRatePct", d.get("target_fill_rate_pct", 85.0))),
            prefer_fewer_pallets=bool(d.get("preferFewerPallets", d.get("prefer_fewer_pallets", True))),
            max_void_gap_cm=float(d.get("maxVoidGapCm", d.get("max_void_gap_cm", 15.0))),
            packaging_enabled=bool(d.get("packagingEnabled", d.get("packaging_enabled", False))),
            packaging_thickness_cm=float(d.get("packagingThicknessCm", d.get("packaging_thickness_cm", 0.4))),
            humidity_factor=float(d.get("humidityFactor", d.get("humidity_factor", 1.0))),
            enforce_ispm15=bool(d.get("enforceIspm15", d.get("enforce_ispm15", False))),
            reefer_ceiling_clearance_cm=float(d.get("reeferCeilingClearanceCm", d.get("reefer_ceiling_clearance_cm", 22.0))),
            reefer_door_clearance_cm=float(d.get("reeferDoorClearanceCm", d.get("reefer_door_clearance_cm", 11.0))),
        )

    def to_settings(self) -> OptimizerSettings:
        return OptimizerSettings(
            height_tolerance_pct=self.overflow_tolerance_pct,
            width_tolerance_pct=self.overflow_tolerance_pct,
            target_fill_rate_pct=self.target_fill_rate_pct,
            prefer_fewer_pallets=self.prefer_fewer_pallets,
            max_iterations=self.max_iterations,
            max_void_gap_cm=self.max_void_gap_cm,
            weight_front_ratio_pct=self.weight_balance_target * 100 if self.weight_balance_target <= 1 else self.weight_balance_target,
            weight_front_tolerance_pct=self.weight_balance_tolerance * 100 if self.weight_balance_tolerance <= 1 else self.weight_balance_tolerance,
            packaging_enabled=self.packaging_enabled,
            packaging_thickness_cm=self.packaging_thickness_cm,
            humidity_factor=self.humidity_factor,
            enforce_ispm15=self.enforce_ispm15,
            reefer_ceiling_clearance_cm=self.reefer_ceiling_clearance_cm,
            reefer_door_clearance_cm=self.reefer_door_clearance_cm,
            height_safety_margin_cm=self.height_safety_margin_cm,
            pallet_gap_cm=self.pallet_gap_cm,
            enforce_constraints=self.enforce_constraints,
        )


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class ProductItem:
    name: str
    quantity: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    constraint: Optional[ConstraintType] = None
    constraints: List[ConstraintType] = field(default_factory=list)
    catalog_id: Optional[str] = None
    order_id: Optional[str] = None
    delivery_address: Optional[str] = None
    delivery_sequence: int = 0
    packaging_ect: float = 0.0
    packaging_thickness_cm: float = 0.0

    @property
    def all_constraints(self) -> Set[ConstraintType]:
        s = set(self.constraints)
        if self.constraint:
            s.add(self.constraint)
        return s

    @property
    def volume_cm3(self) -> float:
        return self.length_cm * self.width_cm * self.height_cm

    @property
    def density_kg_m3(self) -> float:
        vol_m3 = self.volume_cm3 / 1_000_000
        return self.weight_kg / vol_m3 if vol_m3 > 0 else 0

    @property
    def is_fragile(self) -> bool:
        c = self.all_constraints
        return ConstraintType.FRAGILE in c or ConstraintType.NO_STACK in c

    @property
    def is_heavy(self) -> bool:
        c = self.all_constraints
        return ConstraintType.HEAVY in c or ConstraintType.MUST_BOTTOM in c

    @property
    def must_be_top(self) -> bool:
        c = self.all_constraints
        return ConstraintType.MUST_TOP in c or ConstraintType.NO_STACK in c

    @property
    def rotation_allowed(self) -> bool:
        c = self.all_constraints
        return not (ConstraintType.HORIZONTAL_ONLY in c or
                    ConstraintType.VERTICAL_ONLY in c or
                    ConstraintType.THIS_SIDE_UP in c)

    @property
    def layer_class(self) -> int:
        c = self.all_constraints
        if ConstraintType.MUST_BOTTOM in c or ConstraintType.HEAVY in c:
            return 0
        if self.density_kg_m3 > DENSITY_BOTTOM_THRESHOLD:
            return 0
        if ConstraintType.MUST_TOP in c or ConstraintType.FRAGILE in c:
            return 2
        if 0 < self.density_kg_m3 < DENSITY_TOP_THRESHOLD:
            return 2
        return 1


@dataclass
class PalletConfig:
    type: str
    width_cm: float
    length_cm: float
    max_height_cm: float
    max_weight_kg: float
    tare_height_cm: float = 15.0
    tare_weight_kg: float = 25.0
    material: str = "wood"
    is_ispm15: bool = False

    @classmethod
    def euro(cls) -> "PalletConfig":
        return cls("P1", 80, 120, 250, 700, tare_height_cm=15.0)

    @classmethod
    def standard(cls) -> "PalletConfig":
        return cls("P5", 100, 120, 250, 700, tare_height_cm=15.0)

    @classmethod
    def tir(cls) -> "PalletConfig":
        return cls("P10", 120, 200, 250, 700, tare_height_cm=15.0)

    @classmethod
    def from_dict(cls, d: dict) -> "PalletConfig":
        return cls(
            type=d.get("code", d.get("type", "custom")),
            width_cm=float(d["width_cm"]),
            length_cm=float(d["length_cm"]),
            max_height_cm=float(d.get("max_height_cm", 180)),
            max_weight_kg=float(d["max_weight_kg"]),
            tare_height_cm=float(d.get("tare_height_cm", PALLET_BOARD_HEIGHT_CM)),
            tare_weight_kg=float(d.get("tare_weight_kg", 25)),
            material=str(d.get("material", "wood")),
            is_ispm15=bool(d.get("is_ispm15", False)),
        )

    @property
    def area_cm2(self) -> float:
        return self.width_cm * self.length_cm

    @property
    def volume_cm3(self) -> float:
        return self.width_cm * self.length_cm * self.max_height_cm


@dataclass
class PackedItem:
    name: str
    quantity: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    constraint: Optional[ConstraintType]
    constraints: List[ConstraintType] = field(default_factory=list)
    pos_x: float = 0
    pos_y: float = 0
    pos_z: float = 0
    rotated: bool = False
    layer_class: int = 1
    placement_direction: str = ""
    order_id: Optional[str] = None
    bct_safety_factor: float = 0.0


@dataclass
class OptimizedPallet:
    pallet_number: int
    pallet_type: str
    products: List[PackedItem] = field(default_factory=list)
    total_weight_kg: float = 0
    total_height_cm: float = 0
    total_volume_m3: float = 0
    fill_rate_pct: float = 0
    constraints: List[ConstraintType] = field(default_factory=list)
    layout_data: Dict[str, Any] = field(default_factory=dict)
    order_ids: List[str] = field(default_factory=list)
    delivery_address: str = ""
    load_sequence: int = 0


@dataclass
class RejectedItem:
    name: str
    reason: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float


@dataclass
class ActionableError:
    code: str
    message: str
    action_label: str
    affected_pallet_id: str = ""
    severity: str = "error"


@dataclass
class ConstraintValidationResult:
    pallet_number: int
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[ActionableError] = field(default_factory=list)


@dataclass
class PalletTypeSummary:
    pallet_type: str
    count: int
    total_weight_kg: float
    total_volume_m3: float
    avg_fill_rate_pct: float


@dataclass
class OptimizationResult:
    pallets: List[OptimizedPallet]
    total_pallets: int
    total_weight_kg: float
    total_volume_m3: float
    avg_fill_rate_pct: float
    items_per_pallet: float
    duration_ms: int
    rejected_items: List[RejectedItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    algorithm_version: str = "rect-skyline-v9.0"
    pallet_type_breakdown: List[PalletTypeSummary] = field(default_factory=list)
    constraint_validations: List[ConstraintValidationResult] = field(default_factory=list)
    constraints_satisfied: bool = True
    quantity_audit: Dict[str, Any] = field(default_factory=dict)
    actionable_errors: List[ActionableError] = field(default_factory=list)
    compliance: List[str] = field(default_factory=list)
    binding_dimension: str = ""


# ============================================================
# PHYSICS
# ============================================================

def calculate_bct(item_width: float, item_length: float,
                  packaging_ect: float, packaging_thickness: float,
                  humidity_factor: float = 1.0) -> float:
    """McKee: BCT = 5.87 × ECT × √(h × Z). Returns kg."""
    if packaging_ect <= 0 or packaging_thickness <= 0:
        return float('inf')
    perimeter = 2 * (item_width + item_length)
    bct_raw = 5.87 * packaging_ect * ((packaging_thickness * perimeter) ** 0.5)
    return bct_raw * humidity_factor


def check_overlap(rects: List[Dict]) -> List[Tuple[int, int]]:
    """O(n²) overlap. Returns overlapping pairs."""
    overlaps = []
    for i in range(len(rects)):
        a = rects[i]
        for j in range(i + 1, len(rects)):
            b = rects[j]
            if (a["y"] < b["y"] + b["dy"] and a["y"] + a["dy"] > b["y"] and
                a["x"] < b["x"] + b["dx"] and a["x"] + a["dx"] > b["x"] and
                a["z"] < b["z"] + b["dz"] and a["z"] + a["dz"] > b["z"]):
                overlaps.append((i, j))
    return overlaps


def check_void_gaps(rects: List[Dict], pallet_length: float,
                    pallet_width: float, max_gap_cm: float) -> List[str]:
    """CTU Code 2014 void gap check."""
    warnings = []
    if not rects:
        return warnings
    # X-yönü
    x_edges = sorted({0.0} | {r["y"] for r in rects} |
                     {r["y"] + r["dy"] for r in rects} | {pallet_length})
    for i in range(len(x_edges) - 1):
        gap = x_edges[i + 1] - x_edges[i]
        has_fill = any(r["y"] < x_edges[i + 1] and r["y"] + r["dy"] > x_edges[i] for r in rects)
        if not has_fill and gap > max_gap_cm:
            warnings.append(f"X-yönü boşluk {gap:.0f}cm > {max_gap_cm:.0f}cm (CTU Code) — dunnage bag önerilir")
    # Z-yönü
    z_edges = sorted({0.0} | {r["x"] for r in rects} |
                     {r["x"] + r["dx"] for r in rects} | {pallet_width})
    for i in range(len(z_edges) - 1):
        gap = z_edges[i + 1] - z_edges[i]
        has_fill = any(r["x"] < z_edges[i + 1] and r["x"] + r["dx"] > z_edges[i] for r in rects)
        if not has_fill and gap > max_gap_cm:
            warnings.append(f"Z-yönü boşluk {gap:.0f}cm > {max_gap_cm:.0f}cm (CTU Code) — dunnage bag önerilir")
    return warnings


# ============================================================
# 3D Bin Packing — Rect-Skyline v10.0 (Z-up)
# ============================================================

class BinPackingOptimizer3D:
    """
    Rect-Skyline 3D Bin Packing v10.0 — Z-up Koordinat Sistemi

    Gerçek hedef: minimize palet sayısı → her paleti doldur

    Koordinat Sistemi (Z-up, Palet Orijin: sol-ön-alt köşe = (0,0,0)):
      X ekseni (rect["x"], rect["dx"]) → palet genişliği (width_cm),  sol↔sağ
      Y ekseni (rect["y"], rect["dy"]) → palet uzunluğu (length_cm), ön↔arka
      Z ekseni (rect["z"], rect["dz"]) → yükseklik (max_height_cm),  zemin↑yukarı

    placed_rects format: {"x":width_pos, "y":depth_pos, "z":height_pos,
                          "dx":width_size, "dy":depth_size, "dz":height_size}

    PackedItem: pos_x=width(X), pos_y=depth(Y), pos_z=height(Z)
                width_cm=dx, length_cm=dy, height_cm=dz

    VERTICAL_ONLY (Kitaplık Dizilimi):
      Ürünün en ince boyutu (kalınlık) → X ekseni (yan yana kitaplık)
      Diğer iki boyut → biri Y, biri Z (düşük Z tercih)
      Örnek: Headboard (185×105×15) → TIR'da dx=15(X), dy=185(Y), dz=105(Z)

    Palet optimizasyonu: Araç bağımsız (salt palet kısıtları)
    Local optimum: avg_fill >= settings.target_fill_rate_pct
    """

    ALGORITHM_VERSION = "rect-skyline-v10.0"

    # ── Erken durdurma sabitleri ──
    _OPTIMALITY_GAP_PCT = 90.0       # Bu doluluk üzerinde local minimum kabul

    def __init__(self, pallet_config: PalletConfig,
                 params: Optional[OptimizationParams] = None,
                 settings: Optional[OptimizerSettings] = None,
                 constraint_engine=None):
        self.config = pallet_config
        self.params = params or OptimizationParams()
        self.settings = settings or self.params.to_settings()
        self.pallets: List[OptimizedPallet] = []
        self.rejected: List[RejectedItem] = []
        self.warnings: List[str] = []
        self._constraint_engine = constraint_engine
        self._input_summary: Dict[str, int] = {}
        self._start_time: float = 0.0
        self._time_budget_sec: float = 0.0
        self._terminated_early: bool = False

    # ── Efektif Limitler ──

    @property
    def _effective_max_height(self) -> float:
        """Z ekseni limiti: palet max yükseklik (salt palet kısıtı, araç bağımsız)."""
        return self.config.max_height_cm - self.settings.height_safety_margin_cm

    @property
    def _overflow_length(self) -> float:
        return self.config.length_cm * (1 + self.settings.width_tolerance_pct / 100.0)

    @property
    def _overflow_width(self) -> float:
        return self.config.width_cm * (1 + self.settings.width_tolerance_pct / 100.0)

    # ── Ana Akış ──

    # ── Zaman ve kalite kontrolleri ──

    def _elapsed_ms(self) -> float:
        return (time.time() - self._start_time) * 1000

    def _time_exceeded(self) -> bool:
        """Zaman bütçesi aşıldı mı?"""
        if self._time_budget_sec <= 0:
            return False
        return (time.time() - self._start_time) > self._time_budget_sec

    def _avg_fill_rate(self) -> float:
        """Mevcut paletlerin ortalama doluluk oranı."""
        if not self.pallets:
            return 0.0
        return sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets)

    def _optimality_reached(self) -> bool:
        """Optimality gap: doluluk >= hedef (settings) → local minimum yeterli."""
        return self._avg_fill_rate() >= self.settings.target_fill_rate_pct

    def _should_stop(self) -> bool:
        """Durdurma koşulu: zaman VEYA optimality gap."""
        if self._time_exceeded():
            return True
        if len(self.pallets) >= 2 and self._optimality_reached():
            return True
        return False

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        self._start_time = time.time()
        self._time_budget_sec = self.settings.max_optimization_time_sec
        self._terminated_early = False
        self._input_summary = {}
        for p in products:
            self._input_summary[p.name] = self._input_summary.get(p.name, 0) + p.quantity

        items = self._expand_items(products)
        sorted_items = self._constraint_aware_sort(items)
        self._pack(sorted_items)
        self._verify_quantities()

        if self._terminated_early:
            reason = "zaman aşımı" if self._time_exceeded() else "optimality gap (%{:.0f})".format(self._avg_fill_rate())
            self.warnings.append(f"⏱️ Optimizasyon erken durduruldu: {reason} — {self._elapsed_ms():.0f}ms")
            logger.info(f"Early termination: {reason}, pallets={len(self.pallets)}, "
                        f"avg_fill={self._avg_fill_rate():.1f}%, elapsed={self._elapsed_ms():.0f}ms")

        duration_ms = int(self._elapsed_ms())
        return self._build_result(duration_ms)

    def _expand_items(self, products: List[ProductItem]) -> List[ProductItem]:
        items = []
        for p in products:
            for _ in range(p.quantity):
                items.append(ProductItem(
                    name=p.name, quantity=1,
                    length_cm=p.length_cm, width_cm=p.width_cm,
                    height_cm=p.height_cm, weight_kg=p.weight_kg,
                    constraint=p.constraint, constraints=list(p.constraints),
                    catalog_id=p.catalog_id,
                    order_id=p.order_id,
                    delivery_address=p.delivery_address,
                    delivery_sequence=p.delivery_sequence,
                    packaging_ect=p.packaging_ect,
                    packaging_thickness_cm=p.packaging_thickness_cm,
                ))
        return items

    def _constraint_aware_sort(self, items: List[ProductItem]) -> List[ProductItem]:
        """First Fit Decreasing + kısıt farkındalığı.
        Sıralama: layer_class → kısıt zorluğu → hacim (büyükten küçüğe) → ağırlık.
        VERTICAL_ONLY ürünler kendi layer'ında önce gelir (geometrik zorluk)."""
        def sort_key(item: ProductItem):
            c = item.all_constraints
            # 1. Layer: heavy/bottom (0), normal (1), top/fragile (2)
            layer = item.layer_class
            # 2. Kısıt zorluğu: VERTICAL_ONLY geometrik olarak en zor → önce yerleşir
            constraint_priority = 0 if ConstraintType.VERTICAL_ONLY in c else 1
            # 3. Hacim büyükten küçüğe (FFD — First Fit Decreasing)
            volume = item.volume_cm3
            # 4. Ağırlık büyükten küçüğe
            return (layer, constraint_priority, -volume, -item.weight_kg)
        return sorted(items, key=sort_key)

    # ── Orientasyon ──

    def _get_valid_orientations(self, item: ProductItem) -> List[Tuple[float, float, float, bool]]:
        """Ürünün geçerli orientasyonlarını döndür.
        VERTICAL_ONLY: En büyük boyut → Y (yükseklik), diğer ikisi XZ (rotatable).
        HORIZONTAL_ONLY: En küçük boyut → Y (yükseklik), diğer ikisi XZ.
        THIS_SIDE_UP: Orijinal (L,W,H) hiç döndürülmez.
        Normal: 6 permütasyonun hepsi aday."""
        L, W, H = item.length_cm, item.width_cm, item.height_cm
        pL, pW, pH = self._overflow_length, self._overflow_width, self._effective_max_height
        c = item.all_constraints

        # Boyutları küçükten büyüğe sırala
        dims = sorted([L, W, H])  # [d0=küçük, d1=orta, d2=büyük]
        d0, d1, d2 = dims[0], dims[1], dims[2]

        if ConstraintType.THIS_SIDE_UP in c:
            # Hiç döndürme yok — orijinal orientasyon
            raw_candidates = [(L, W, H)]
        elif ConstraintType.VERTICAL_ONLY in c:
            # "Dik koyulmalı": ürün dikey duruyor (ince yüzü yatay, geniş yüzü dikey).
            # d0 (en ince/kalınlık) → yatay eksenlerden biri (kitaplık dizilimi)
            # d1, d2 → biri yatay, diğeri dikey (yükseklik)
            # Düşük yükseklik tercih: daha stabil, devrilme riski az
            raw_candidates = [
                # h = d1 (orta) → daha alçak, daha stabil — TERCİH EDİLİR
                (d2, d0, d1),  # l=büyük, w=küçük(kalınlık), h=orta
                (d0, d2, d1),  # l=küçük(kalınlık), w=büyük, h=orta
                # h = d2 (büyük) → yedek (küçük paletlerde zorunlu olabilir)
                (d1, d0, d2),  # l=orta, w=küçük(kalınlık), h=büyük
                (d0, d1, d2),  # l=küçük(kalınlık), w=orta, h=büyük
            ]
        elif ConstraintType.HORIZONTAL_ONLY in c:
            # "Yatık koyulmalı": en küçük boyut → Y (yükseklik)
            # Büyük yüzeyi zemine oturtur
            raw_candidates = [
                (d1, d2, d0),  # height=küçük, XZ={orta, büyük}
                (d2, d1, d0),  # height=küçük, XZ={büyük, orta}
            ]
            # Eğer en küçük boyutu bile yüksekliğe koyamıyorsak, orta dene
            if d0 > pH:
                raw_candidates = [
                    (d0, d2, d1),  # height=orta
                    (d2, d0, d1),
                ]
        else:
            # Tüm 6 permütasyon
            from itertools import permutations as perms
            raw_candidates = list(set(perms([L, W, H])))

        # Tekrarlı orientasyonları eleme + palet sınır kontrolü
        valid = []
        seen = set()
        for l, w, h in raw_candidates:
            key = (round(l, 2), round(w, 2), round(h, 2))
            if key in seen:
                continue
            seen.add(key)
            if l <= pL and w <= pW and h <= pH:
                rotated = not (abs(l - L) < 0.01 and abs(w - W) < 0.01 and abs(h - H) < 0.01)
                valid.append((l, w, h, rotated))

        # Sıralama: düşük h tercih (stabil yerleşim, devrilme riski düşük)
        # VERTICAL_ONLY dahil tüm türler için düşük yükseklik = daha iyi
        valid.sort(key=lambda o: (o[2], max(o[0], o[1])))
        return valid

    def _item_fits_pallet(self, item: ProductItem) -> bool:
        if item.weight_kg > self.config.max_weight_kg:
            return False
        return len(self._get_valid_orientations(item)) > 0

    # ══════════════════════════════════════════════════════════
    # RECT-SKYLINE SCORED CANDIDATE — v9.0
    #
    # Mantık:
    #   1. Aday X,Z pozisyonlar placed_rects kenarlarından üretilir.
    #   2. Y-base doğrudan placed_rects üzerinden O(n) hesaplanır.
    #   3. Her aday skorlanır: yön + CoG + yüzey + bitisiklik.
    #   4. En yüksek skorlu aday seçilir.
    #   5. HARD: Palet = kapalı kutu. Hiçbir eksen dışına çıkılamaz.
    #      - X: 0 ≤ pos_x + item_l ≤ palet_length (+tolerans)
    #      - Z: 0 ≤ pos_z + item_w ≤ palet_width (+tolerans)
    #      - Y: 0 ≤ pos_y + item_h ≤ effective_max_height
    #   6. Aday limiti yok — rect-based sorgu O(n_items) → hızlı.
    # ══════════════════════════════════════════════════════════

    def _base_y_from_rects(self, pallet: OptimizedPallet,
                           x: float, z: float, pl: float, pw: float) -> float:
        """placed_rects üzerinden taban Y hesapla. O(n_items).
        Ürünün XZ footprint'i ile çakışan tüm rect'lerin max üst yüksekliği.
        Bu = ürünün oturacağı yükseklik (yerçekimi etkisi)."""
        max_top = 0.0
        x2, z2 = x + pl, z + pw
        for r in pallet.layout_data.get("placed_rects", []):
            # XZ düzleminde çakışma var mı?
            if r["y"] < x2 and r["y"] + r["dy"] > x and r["x"] < z2 and r["x"] + r["dx"] > z:
                top = r["z"] + r["dz"]
                if top > max_top:
                    max_top = top
        return max_top

    def _pack(self, items: List[ProductItem]):
        top_items = [i for i in items if i.must_be_top]
        normal_items = [i for i in items if not i.must_be_top]

        # ── Phase 1: Normal ürünler — scored placement ──
        for idx, item in enumerate(normal_items):
            # Durdurma koşulu: zaman veya optimality gap
            if self._should_stop():
                self._terminated_early = True
                # Kalan ürünleri hızlı fallback ile yerleştir
                remaining = normal_items[idx:] + top_items
                self._fast_fallback_pack(remaining)
                return
            self._place_item(item)

        # ── Phase 2: Top-constraint ürünler — her zaman yerleştirilmeli ──
        for item in top_items:
            if self._time_exceeded():
                self._terminated_early = True
            self._place_item_fast(item) if self._terminated_early else self._place_item(item)

    def _fast_fallback_pack(self, items: List[ProductItem]):
        """Zaman aşımı sonrası hızlı yerleştirme: skor hesaplamadan ilk uygun yere koy."""
        for item in items:
            if not self._item_fits_pallet(item):
                self.rejected.append(RejectedItem(
                    name=item.name, reason=self._rejection_reason(item),
                    length_cm=item.length_cm, width_cm=item.width_cm,
                    height_cm=item.height_cm, weight_kg=item.weight_kg,
                ))
                continue
            self._place_item_fast(item)

    def _place_item_fast(self, item: ProductItem):
        """Hızlı yerleştirme: ilk sığan palete koy, skor hesaplama yok."""
        for pallet in self.pallets:
            if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
                continue
            pos = self._find_first_fit(pallet, item)
            if pos is not None:
                x, z, base_y, pl, pw, ph_item, rotated = pos
                direction = "x_extend" if base_y < 0.001 and x > 0.01 else (
                    "y_new_row" if base_y < 0.001 else "z_stack")
                self._commit_place(pallet, item, x, base_y, z, pl, pw, ph_item, rotated, direction)
                self._update_layer_data(pallet, x, z, base_y, pl, pw, ph_item)
                return
        # Mevcut paletlere sığmadı → yeni palet
        new_pallet = self._create_empty_pallet()
        pos = self._find_first_fit(new_pallet, item)
        if pos is not None:
            x, z, base_y, pl, pw, ph_item, rotated = pos
            self._commit_place(new_pallet, item, x, base_y, z, pl, pw, ph_item, rotated, "y_new_row")
            self._update_layer_data(new_pallet, x, z, base_y, pl, pw, ph_item)
            self.pallets.append(new_pallet)
        else:
            self.rejected.append(RejectedItem(
                name=item.name, reason="Zaman aşımı — hızlı yerleştirmede sığmadı",
                length_cm=item.length_cm, width_cm=item.width_cm,
                height_cm=item.height_cm, weight_kg=item.weight_kg,
            ))

    def _find_first_fit(self, pallet: OptimizedPallet,
                        item: ProductItem) -> Optional[Tuple[float, float, float, float, float, float, bool]]:
        """İlk uygun pozisyonu bul — skor hesaplama yok, hızlı."""
        pH = self._effective_max_height
        orientations = self._get_valid_orientations(item)
        if not orientations:
            return None
        for pl, pw, ph_item, rotated in orientations:
            candidates = self._candidate_positions(pallet, pl, pw)
            for (x, z) in candidates:
                base_y = self._base_y_from_rects(pallet, x, z, pl, pw)
                if base_y + ph_item > pH + 0.001:
                    continue
                if self._overlaps_3d(pallet, x, z, base_y, pl, pw, ph_item):
                    continue
                return (x, z, base_y, pl, pw, ph_item, rotated)
        return None

    def _update_layer_data(self, pallet: OptimizedPallet,
                           x: float, z: float, base_y: float,
                           pl: float, pw: float, ph_item: float):
        """Layer uyumluluk verisini güncelle (mevcut API ile uyum)."""
        layers = pallet.layout_data.setdefault("layers", [])
        placed_in_layer = False
        for layer in layers:
            if abs(layer["z_base"] - base_y) < 0.5:
                layer["rects"].append({"x": z, "y": x, "dx": pw, "dy": pl})
                if ph_item > layer["height"]:
                    layer["height"] = ph_item
                placed_in_layer = True
                break
        if not placed_in_layer:
            layers.append({"z_base": base_y, "height": ph_item,
                           "rects": [{"x": z, "y": x, "dx": pw, "dy": pl}]})
            layers.sort(key=lambda l: l["z_base"])

    def _create_empty_pallet(self) -> OptimizedPallet:
        p = OptimizedPallet(
            pallet_number=len(self.pallets) + 1, pallet_type=self.config.type,
        )
        p.layout_data = {"placed_rects": [], "layers": []}
        return p

    def _can_place_in_pallet(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """Ürün bu palete yerleştirilebilir mi? (ağırlık + kısıt + geometri)"""
        if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
            return False
        if not self._item_fits_pallet(item):
            return False
        if self.settings.enforce_constraints:
            if self._constraint_engine:
                if not self._engine_allows_placement(pallet, item):
                    return False
            elif not self._constraints_compatible(pallet, item):
                return False
        return self._find_best_position(pallet, item) is not None

    def _has_space(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """Ürün için geometrik alan var mı? (placed_rects üzerinden.)"""
        return self._find_best_position(pallet, item) is not None

    # ── CoG (Ağırlık Merkezi) Hesaplama ──

    def _compute_cog(self, pallet: OptimizedPallet) -> Tuple[float, float]:
        """Palet ağırlık merkezini hesapla → (cog_x, cog_y). X=width, Y=depth."""
        total_w = 0.0
        wx_sum = 0.0
        wy_sum = 0.0
        for p in pallet.products:
            w = p.weight_kg
            total_w += w
            wx_sum += w * (p.pos_x + p.width_cm / 2.0)
            wy_sum += w * (p.pos_y + p.length_cm / 2.0)
        if total_w <= 0:
            return (self.config.width_cm / 2.0, self.config.length_cm / 2.0)
        return (wx_sum / total_w, wy_sum / total_w)

    def _cog_deviation_pct(self, pallet: OptimizedPallet) -> float:
        """CoG'un palet merkezinden sapma yüzdesi (0–100). Küçük = iyi."""
        if not pallet.products:
            return 0.0
        cog_x, cog_y = self._compute_cog(pallet)
        center_x = self.config.width_cm / 2.0
        center_y = self.config.length_cm / 2.0
        dev_x = abs(cog_x - center_x) / center_x * 100 if center_x > 0 else 0
        dev_y = abs(cog_y - center_y) / center_y * 100 if center_y > 0 else 0
        return max(dev_x, dev_y)

    # ── Aday Pozisyon Üretici (Extreme Point / Rect Edge) ──

    def _candidate_positions(self, pallet: OptimizedPallet,
                             pl: float, pw: float) -> List[Tuple[float, float]]:
        """placed_rects kenarlarından aday X,Z pozisyonlar üret.
        Yalnızca extreme point'ler (rect kenarları + orijin).
        Merkez pozisyon EKLENMEZ — sıkı paketleme önceliklidir.
        BBL sıralaması: Z artan (sol→sağ), X artan (ön→arka)."""
        pL = self._overflow_length
        pW = self._overflow_width
        rects = pallet.layout_data.get("placed_rects", [])

        # Yalnızca extreme point'ler: rect kenarları + orijin
        xs = sorted({0.0} | {r["y"] + r["dy"] for r in rects} | {r["y"] for r in rects})
        zs = sorted({0.0} | {r["x"] + r["dx"] for r in rects} | {r["x"] for r in rects})

        candidates = []
        for z in zs:
            if z + pw > pW + 0.01:
                continue
            for x in xs:
                if x + pl > pL + 0.01:
                    continue
                candidates.append((x, z))
        return candidates

    def _score_candidate(self, pallet: OptimizedPallet, item: ProductItem,
                         x: float, z: float, base_y: float,
                         pl: float, pw: float, ph: float) -> float:
        """Aday pozisyon skoru. Yüksek skor = daha iyi yerleşim.
        Prensip: KÖŞEDEN BAŞLA → SIKI PAKETLEME → AŞAĞIDAN YUKARI.
        CoG: yalnızca >%15 sapma = ceza. Pozitif bonus yok.
        Gap olmayacak — bitişiklik birincil kriter."""
        score = 0.0
        pL = self._overflow_length
        pW = self._overflow_width
        pH = self._effective_max_height
        rects = pallet.layout_data.get("placed_rects", [])

        is_ground = (base_y < 0.001)

        # 1. Düşük base_y → yüksek skor (aşağıdan doldur — en önemli kriter)
        #    base_y=0 → +200, base_y=max → +0
        score += max(0.0, (1.0 - base_y / pH)) * 200 if pH > 0 else 0

        # 2. Bitişiklik bonusu — mevcut rect'lere temas eden yüzey alanı
        #    Gap olmayacak: bitişik ürünler ödüllendirilir
        touch_area = 0.0
        for r in rects:
            # X-yönünde bitişik (sağ veya sol kenar)
            if abs(x - (r["y"] + r["dy"])) < 0.5 or abs((x + pl) - r["y"]) < 0.5:
                y_overlap = max(0, min(base_y + ph, r["z"] + r["dz"]) - max(base_y, r["z"]))
                z_overlap = max(0, min(z + pw, r["x"] + r["dx"]) - max(z, r["x"]))
                touch_area += y_overlap * z_overlap
            # Z-yönünde bitişik (ön veya arka kenar)
            if abs(z - (r["x"] + r["dx"])) < 0.5 or abs((z + pw) - r["x"]) < 0.5:
                y_overlap = max(0, min(base_y + ph, r["z"] + r["dz"]) - max(base_y, r["z"]))
                x_overlap = max(0, min(x + pl, r["y"] + r["dy"]) - max(x, r["y"]))
                touch_area += y_overlap * x_overlap
            # Y-yönünde bitişik (altında yatan ürün)
            if abs(base_y - (r["z"] + r["dz"])) < 0.5:
                x_overlap = max(0, min(x + pl, r["y"] + r["dy"]) - max(x, r["y"]))
                z_overlap = max(0, min(z + pw, r["x"] + r["dx"]) - max(z, r["x"]))
                touch_area += x_overlap * z_overlap
        # Normalize: max temas = ürün yüzey alanının toplamı
        item_surface = 2 * (pl * pw + pl * ph + pw * ph)
        if item_surface > 0:
            score += min(touch_area / item_surface, 1.0) * 150

        # 3. Zemine yerleşme bonusu (stabil taban)
        if is_ground:
            score += 50

        # 4. Köşeden başla + kenara yapış
        #    Boş palette: (0,0) köşesinden başla → sıkı paketlemenin temeli
        #    Dolu palette: kenara yakın pozisyonlar tercih
        if not rects:
            # İlk ürün: köşe başlangıcı bonusu (çok güçlü)
            if x < 1.0 and z < 1.0:
                score += 80
            elif x < 1.0 or z < 1.0:
                score += 30
        else:
            # Kenara yapışık — boşluk azaltma
            x_edge_dist = min(x, pL - (x + pl))
            z_edge_dist = min(z, pW - (z + pw))
            if x_edge_dist < 1.0:
                score += 15
            if z_edge_dist < 1.0:
                score += 15

        # 5. Hizalama bonusu: aynı X veya Z çizgisindeki ürünlerle sıra/kolon oluştur
        if rects:
            x_aligned = any(abs(r["y"] - x) < 0.5 for r in rects)
            z_aligned = any(abs(r["x"] - z) < 0.5 for r in rects)
            if x_aligned:
                score += 15
            if z_aligned:
                score += 15

        # 6. CoG sadece CEZA (%15 üzeri sapma → negatif skor)
        #    Pozitif bonus verilmez — sıkı paketleme öncelikli.
        #    CoG dengesi doğal olarak köşeden-dışa paketlemeyle sağlanır.
        if pallet.products:
            center_x = self.config.width_cm / 2.0
            center_y = self.config.length_cm / 2.0
            total_w = sum(p.weight_kg for p in pallet.products)
            cur_cog_x, cur_cog_y = self._compute_cog(pallet)
            new_tw = total_w + item.weight_kg
            if new_tw > 0:
                new_cog_x = (cur_cog_x * total_w + (z + pw / 2.0) * item.weight_kg) / new_tw
                new_cog_y = (cur_cog_y * total_w + (x + pl / 2.0) * item.weight_kg) / new_tw
                dev_x = abs(new_cog_x - center_x) / center_x * 100 if center_x > 0 else 0
                dev_y = abs(new_cog_y - center_y) / center_y * 100 if center_y > 0 else 0
                cog_dev = max(dev_x, dev_y)
                # Sadece ceza: sapma >%15 olursa puan düşür
                if cog_dev > 15:
                    score -= (cog_dev - 15) * 2

        # 7. Ağır ürün tabanda bonusu
        if item.weight_kg > 30 and is_ground:
            score += 20

        # 8. Yükseklik verimliliği: düşük h tercih (devrilme riski ↓, üst alan ↑)
        #    Aynı pozisyonda kısa orientasyon uzun orientasyona tercih edilir
        if pH > 0:
            score -= (ph / pH) * 30

        # 9. Zemin kapasite bonusu: küçük footprint → yan yana daha çok sığar
        #    Headboard gibi ince ürünlerde bookshelf dizilimini tercih ettirir
        floor_copies_x = max(1, int(pL // pl))
        floor_copies_z = max(1, int(pW // pw))
        floor_capacity = floor_copies_x * floor_copies_z
        if floor_capacity > 1:
            score += min(floor_capacity, 20) * 8

        return score

    def _find_best_position(self, pallet: OptimizedPallet,
                            item: ProductItem) -> Optional[Tuple[float, float, float, float, float, float, bool]]:
        """Rect-based en iyi pozisyonu bul. O(orientations × candidates × n_placed).
        Returns: (x, z, base_y, pl, pw, ph, rotated) veya None.
        Aday limiti yok — rect-based sorgu yeterince hızlı."""
        pH = self._effective_max_height
        pL = self._overflow_length
        pW = self._overflow_width
        orientations = self._get_valid_orientations(item)
        if not orientations:
            return None

        best = None
        best_score = -float('inf')

        for pl, pw, ph_item, rotated in orientations:
            candidates = self._candidate_positions(pallet, pl, pw)
            for (x, z) in candidates:
                # HARD: Kapalı kutu — XZ sınırları
                if x + pl > pL + 0.01 or z + pw > pW + 0.01:
                    continue
                if x < -0.01 or z < -0.01:
                    continue

                # Y-base: placed_rects üzerinden O(n)
                base_y = self._base_y_from_rects(pallet, x, z, pl, pw)

                # HARD: Kapalı kutu — Y sınırı (palet yüksekliğini geçemez)
                if base_y + ph_item > pH + 0.001:
                    continue

                # HARD: 3D çakışma kontrolü
                if self._overlaps_3d(pallet, x, z, base_y, pl, pw, ph_item):
                    continue

                score = self._score_candidate(pallet, item, x, z, base_y,
                                              pl, pw, ph_item)
                if score > best_score:
                    best_score = score
                    best = (x, z, base_y, pl, pw, ph_item, rotated)

        return best

    def _overlaps_3d(self, pallet: OptimizedPallet,
                     x: float, z: float, y: float,
                     pl: float, pw: float, ph: float) -> bool:
        """3D çakışma kontrolü — placed_rects üzerinden."""
        x2, z2, y2 = x + pl, z + pw, y + ph
        for r in pallet.layout_data.get("placed_rects", []):
            if (r["y"] < x2 and r["y"] + r["dy"] > x and
                r["x"] < z2 and r["x"] + r["dx"] > z and
                r["z"] < y2 and r["z"] + r["dz"] > y):
                return True
        return False

    def _do_place_in_pallet(self, pallet: OptimizedPallet, item: ProductItem,
                            cached_pos: Optional[Tuple] = None):
        """Ürünü palete yerleştir. cached_pos varsa tekrar aramaz."""
        pos = cached_pos or self._find_best_position(pallet, item)
        if pos is None:
            return
        x, z, base_y, pl, pw, ph_item, rotated = pos

        # Yön belirleme
        direction = "x_extend"
        if base_y < 0.001:
            direction = "x_extend" if x > 0.01 else "y_new_row"
        else:
            direction = "z_stack"

        self._commit_place(pallet, item, x, base_y, z, pl, pw, ph_item, rotated, direction)
        self._update_layer_data(pallet, x, z, base_y, pl, pw, ph_item)

    def _place_item(self, item: ProductItem):
        """Scored Best-Fit: en iyi pozisyonlu paleti tercih et.
        Pozisyon cache'lenir → _do_place_in_pallet tekrar aramaz.
        Early-exit: palet doluluk >= optimality gap → ilk uygun paleti al."""
        if not self._item_fits_pallet(item):
            self.rejected.append(RejectedItem(
                name=item.name, reason=self._rejection_reason(item),
                length_cm=item.length_cm, width_cm=item.width_cm,
                height_cm=item.height_cm, weight_kg=item.weight_kg,
            ))
            return

        # Scored best-fit: en iyi pozisyon skoruna sahip paleti bul
        best_pallet = None
        best_pos = None
        best_score = -float('inf')
        gap_threshold = self._OPTIMALITY_GAP_PCT

        for pallet in self.pallets:
            # Ağırlık ön kontrolü (ucuz)
            if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
                continue
            # Kısıt ön kontrolü
            if self.settings.enforce_constraints:
                if self._constraint_engine:
                    if not self._engine_allows_placement(pallet, item):
                        continue
                elif not self._constraints_compatible(pallet, item):
                    continue

            pos = self._find_best_position(pallet, item)
            if pos is not None:
                x, z, base_y, pl, pw, ph_item, rotated = pos
                score = self._score_candidate(pallet, item, x, z, base_y, pl, pw, ph_item)

                # Optimality gap early-exit: palet zaten iyi doluysa hemen al
                if pallet.fill_rate_pct >= gap_threshold:
                    best_pallet = pallet
                    best_pos = pos
                    break

                if score > best_score:
                    best_score = score
                    best_pallet = pallet
                    best_pos = pos

        if best_pallet is not None and best_pos is not None:
            self._do_place_in_pallet(best_pallet, item, cached_pos=best_pos)
            return

        new_pallet = self._create_empty_pallet()
        pos = self._find_best_position(new_pallet, item)
        if pos is not None:
            self._do_place_in_pallet(new_pallet, item, cached_pos=pos)
            self.pallets.append(new_pallet)
        else:
            self.rejected.append(RejectedItem(
                name=item.name, reason="Yeni palette bile yerleştirilemedi",
                length_cm=item.length_cm, width_cm=item.width_cm,
                height_cm=item.height_cm, weight_kg=item.weight_kg,
            ))

    def _rejection_reason(self, item: ProductItem) -> str:
        pH = self._effective_max_height
        if item.weight_kg > self.config.max_weight_kg:
            return f"Tek parça ağırlık ({item.weight_kg}kg) > palet max ({self.config.max_weight_kg}kg)"
        if not self._get_valid_orientations(item):
            return (f"Hiçbir orientasyonda ({item.length_cm}×{item.width_cm}×{item.height_cm}cm) "
                    f"palete ({self.config.length_cm}×{self.config.width_cm}×{pH}cm) sığmıyor")
        return "Palet boyut limitleri aşıldı"

    # ══════════════════════════════════════════════════════════
    # 2D KATMAN POZİSYON BULUCU (Geriye dönük uyumluluk)
    # ══════════════════════════════════════════════════════════

    def _find_position_in_layer(self, layer: Dict, pl: float, pw: float,
                                pL: float, pW: float) -> Optional[Tuple[float, float]]:
        """Katman içinde X→Z sırasıyla ilk boş pozisyonu bul.
        Aday pozisyonlar: mevcut dikdörtgenlerin kenarları + orijin."""
        rects = layer["rects"]

        xs = sorted({0.0} | {r["y"] + r["dy"] for r in rects} | {r["y"] for r in rects})
        zs = sorted({0.0} | {r["x"] + r["dx"] for r in rects} | {r["x"] for r in rects})

        for z in zs:
            if z + pw > pW + 0.01:
                continue
            for x in xs:
                if x + pl > pL + 0.01:
                    continue
                if not self._overlaps_2d(rects, x, z, pl, pw):
                    return (x, z)
        return None

    def _overlaps_2d(self, rects: List[Dict], x: float, z: float,
                     l: float, w: float) -> bool:
        """2D XZ düzleminde çakışma kontrol (aynı katman)."""
        x2, z2 = x + l, z + w
        for r in rects:
            if (r["y"] < x2 and r["y"] + r["dy"] > x and
                    r["x"] < z2 and r["x"] + r["dx"] > z):
                return True
        return False

    # ── Uyumluluk alias'ları ──
    def _try_place_scored(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        if self._can_place_in_pallet(pallet, item):
            self._do_place_in_pallet(pallet, item)
            return True
        return False

    def _try_place_in_pallet(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        return self._try_place_scored(pallet, item)

    def _support_height(self, placed: List[Dict], x: float, z: float,
                        pl: float, pw: float) -> float:
        """3D placed_rects üzerinden destek yüksekliği (validation için)."""
        max_h = 0.0
        x2, z2 = x + pl, z + pw
        for r in placed:
            if (r["y"] < x2 and r["y"] + r["dy"] > x and
                    r["x"] < z2 and r["x"] + r["dx"] > z):
                top = r["z"] + r["dz"]
                if top > max_h:
                    max_h = top
        return max_h

    def _commit_place(self, pallet: OptimizedPallet, item: ProductItem,
                      x: float, y: float, z: float,
                      pl: float, pw: float, ph: float,
                      rotated: bool, direction: str = ""):
        # ── HARD CONSTRAINT: yükseklik kontrolü (KURAL-4) ──
        max_h = self._effective_max_height
        if y + ph > max_h + 0.001:
            logger.error(f"YÜKSEKLİK İHLALİ: {item.name} y={y}+h={ph}={y+ph} > max={max_h}")
            return  # yerleştirme iptal

        bct_sf = 0.0
        if self.settings.packaging_enabled and item.packaging_ect > 0:
            bct = calculate_bct(item.width_cm, item.length_cm,
                                item.packaging_ect,
                                item.packaging_thickness_cm or self.settings.packaging_thickness_cm,
                                self.settings.humidity_factor)
            if bct < float('inf'):
                bct_sf = bct / max(item.weight_kg, 0.1)

        packed = PackedItem(
            name=item.name, quantity=1,
            length_cm=pl, width_cm=pw, height_cm=ph, weight_kg=item.weight_kg,
            constraint=item.constraint, constraints=list(item.constraints),
            pos_x=round(z, 2), pos_y=round(x, 2), pos_z=round(y, 2),
            rotated=rotated, layer_class=item.layer_class,
            placement_direction=direction, order_id=item.order_id,
            bct_safety_factor=round(bct_sf, 2),
        )
        pallet.products.append(packed)

        rects = pallet.layout_data.setdefault("placed_rects", [])
        rects.append({"x": z, "y": x, "z": y, "dx": pw, "dy": pl, "dz": ph})

        pallet.total_weight_kg += item.weight_kg
        pallet.total_volume_m3 += (pl * pw * ph) / 1_000_000
        # Fill rate: efektif yükseklik üzerinden (config.max_height_cm değil)
        effective_vol = (self.config.length_cm * self.config.width_cm * self._effective_max_height) / 1_000_000
        pallet.fill_rate_pct = round((pallet.total_volume_m3 / effective_vol) * 100, 1) if effective_vol else 0

        for ct in item.all_constraints:
            if ct not in pallet.constraints:
                pallet.constraints.append(ct)
        if item.order_id and item.order_id not in pallet.order_ids:
            pallet.order_ids.append(item.order_id)
        if item.delivery_address and not pallet.delivery_address:
            pallet.delivery_address = item.delivery_address

        all_tops = [r["z"] + r["dz"] for r in rects]
        pallet.total_height_cm = round(max(all_tops) if all_tops else 0, 2)

    # ── Constraint Engine ──

    def _engine_allows_placement(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        from app.services.constraint_engine import ProductConstraint
        item_pcs = self._to_product_constraints(item)
        pallet_items = [(p.name, self._product_constraints_from_packed(p)) for p in pallet.products]
        decision = self._constraint_engine.can_place_on_pallet(
            item_name=item.name, item_constraints=item_pcs, pallet_items=pallet_items,
        )
        if decision.has_errors:
            reason = decision.block_reason()
            if reason:
                self.warnings.append(f"⚙️ Kısıt engeli: '{item.name}' → {reason}")
            return False
        for w in decision.warnings:
            self.warnings.append(f"⚠️ Kısıt uyarısı: {w.message}")
        return True

    def _to_product_constraints(self, item: ProductItem) -> list:
        from app.services.constraint_engine import ProductConstraint
        if not self._constraint_engine:
            return []
        pcs = []
        for ct in item.all_constraints:
            code = ct.value if hasattr(ct, 'value') else str(ct)
            for key in [code.upper(), code]:
                if key in self._constraint_engine.constraints:
                    pcs.append(ProductConstraint(definition=self._constraint_engine.constraints[key], param_values={}))
                    break
        return pcs

    def _product_constraints_from_packed(self, packed: PackedItem) -> list:
        from app.services.constraint_engine import ProductConstraint
        if not self._constraint_engine:
            return []
        pcs = []
        all_c = set(packed.constraints or [])
        if packed.constraint:
            all_c.add(packed.constraint)
        for ct in all_c:
            code = ct.value if hasattr(ct, 'value') else str(ct)
            for key in [code.upper(), code]:
                if key in self._constraint_engine.constraints:
                    pcs.append(ProductConstraint(definition=self._constraint_engine.constraints[key], param_values={}))
                    break
        return pcs

    def _constraints_compatible(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        if not pallet.products:
            return True
        item_c = item.all_constraints
        pallet_c = set(pallet.constraints)

        if ConstraintType.FRAGILE in item_c and ConstraintType.HEAVY in pallet_c:
            return False
        if ConstraintType.HEAVY in item_c and ConstraintType.FRAGILE in pallet_c:
            return False
        if ConstraintType.FRAGILE in item_c and ConstraintType.MUST_BOTTOM in pallet_c:
            return False
        if ConstraintType.MUST_BOTTOM in item_c and ConstraintType.FRAGILE in pallet_c:
            return False
        if ConstraintType.COLD_CHAIN in item_c and ConstraintType.HAZMAT in pallet_c:
            return False
        if ConstraintType.HAZMAT in item_c and ConstraintType.COLD_CHAIN in pallet_c:
            return False
        if ConstraintType.TEMP in item_c:
            return all(ConstraintType.TEMP in set(p.constraints or []) or p.constraint == ConstraintType.TEMP
                       for p in pallet.products)
        if ConstraintType.TEMP in pallet_c:
            return ConstraintType.TEMP in item_c
        return True

    # ── Miktar ──

    def _verify_quantities(self):
        placed: Dict[str, int] = {}
        for pallet in self.pallets:
            for p in pallet.products:
                placed[p.name] = placed.get(p.name, 0) + p.quantity
        rejected_counts: Dict[str, int] = {}
        for r in self.rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1

        for name, expected in self._input_summary.items():
            actual = placed.get(name, 0) + rejected_counts.get(name, 0)
            if actual < expected:
                missing = expected - actual
                self.warnings.append(
                    f"⛔ MİKTAR HATASI: '{name}' → sipariş={expected}, "
                    f"yerleştirilen={placed.get(name, 0)}, reddedilen={rejected_counts.get(name, 0)}, KAYIP={missing}"
                )
                for _ in range(missing):
                    self.rejected.append(RejectedItem(name=name, reason="Kayıp", length_cm=0, width_cm=0, height_cm=0, weight_kg=0))

    # ── Sonuç ──

    def _build_result(self, duration_ms: int) -> OptimizationResult:
        total_weight = sum(p.total_weight_kg for p in self.pallets)
        total_volume = sum(p.total_volume_m3 for p in self.pallets)
        avg_fill = round(sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets), 1) if self.pallets else 0
        total_items = sum(sum(pr.quantity for pr in p.products) for p in self.pallets)

        type_breakdown = self._compute_pallet_type_breakdown()
        validations = self._validate_all_pallets()
        all_passed = all(v.passed for v in validations)
        if not all_passed:
            self.warnings.append(f"⛔ {sum(1 for v in validations if not v.passed)} palette kısıt ihlali")

        actionable_errors = []
        for v in validations:
            actionable_errors.extend(v.errors)
        compliance = self._build_compliance(validations)
        quantity_audit = self._build_quantity_audit()

        # ── Öneri motoru: düşük doluluk → palet tipi önerisi ──
        suggestions = self._generate_suggestions()
        if suggestions:
            self.warnings.extend(suggestions)

        return OptimizationResult(
            pallets=self.pallets, total_pallets=len(self.pallets),
            total_weight_kg=round(total_weight, 2), total_volume_m3=round(total_volume, 4),
            avg_fill_rate_pct=avg_fill,
            items_per_pallet=round(total_items / len(self.pallets), 1) if self.pallets else 0,
            duration_ms=duration_ms, rejected_items=self.rejected, warnings=self.warnings,
            algorithm_version=self.ALGORITHM_VERSION, pallet_type_breakdown=type_breakdown,
            constraint_validations=validations, constraints_satisfied=all_passed,
            quantity_audit=quantity_audit, actionable_errors=actionable_errors, compliance=compliance,
        )

    def _build_quantity_audit(self) -> Dict[str, Any]:
        placed_counts: Dict[str, int] = {}
        for pallet in self.pallets:
            for p in pallet.products:
                placed_counts[p.name] = placed_counts.get(p.name, 0) + p.quantity
        rejected_counts: Dict[str, int] = {}
        for r in self.rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1
        ti = sum(self._input_summary.values())
        tp = sum(placed_counts.values())
        tr = sum(rejected_counts.values())
        return {"input": self._input_summary, "placed": placed_counts, "rejected": rejected_counts,
                "total_input": ti, "total_placed": tp, "total_rejected": tr, "balanced": ti == tp + tr}

    def _generate_suggestions(self) -> List[str]:
        """Düşük doluluk veya yüksek palet sayısı durumunda öneriler üret."""
        suggestions = []
        if not self.pallets:
            return suggestions

        avg_fill = sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets)
        threshold = self.settings.suggestion_trigger_pct

        if avg_fill < threshold:
            # Mevcut ürünlerin max boyutlarını bul
            max_l, max_w, max_h = 0, 0, 0
            for pal in self.pallets:
                for p in pal.products:
                    max_l = max(max_l, p.length_cm)
                    max_w = max(max_w, p.width_cm)
                    max_h = max(max_h, p.height_cm)

            # Hangi standart palet tipi daha uygun olur?
            alternatives = [
                ("P1 Euro (80×120)", 80, 120),
                ("P5 Standart (100×120)", 100, 120),
                ("P10 TIR (120×200)", 120, 200),
            ]
            cur_type = self.config.type
            cur_area = self.config.width_cm * self.config.length_cm
            for name, w, l in alternatives:
                area = w * l
                if area <= cur_area:
                    continue
                # Ürün bu palete yatay yatabilir mi?
                dims = sorted([max_l, max_w, max_h])
                can_flat = (dims[0] <= (w * 1.05) and dims[1] <= (l * 1.05))
                can_stand = (dims[0] <= (l * 1.05) and dims[1] <= (w * 1.05))
                if can_flat or can_stand:
                    mode = "yatay" if can_flat else "dikey"
                    suggestions.append(
                        f"💡 Öneri: {name} paletine geçerek ürünler {mode} "
                        f"yerleştirilebilir → palet sayısı önemli ölçüde azalabilir "
                        f"(mevcut doluluk: %{avg_fill:.0f})"
                    )
                    break  # En küçük yeterli alternatifi öner

        if len(self.pallets) > 10 and avg_fill < 50:
            suggestions.append(
                f"⚠️ {len(self.pallets)} palet ancak ortalama %{avg_fill:.0f} doluluk — "
                f"daha büyük palet tipi veya karma optimizasyon önerilir"
            )

        return suggestions

    def _compute_pallet_type_breakdown(self) -> List[PalletTypeSummary]:
        from collections import defaultdict
        groups: Dict[str, List[OptimizedPallet]] = defaultdict(list)
        for p in self.pallets:
            groups[p.pallet_type].append(p)
        return [PalletTypeSummary(
            pallet_type=pt, count=len(pals),
            total_weight_kg=round(sum(p.total_weight_kg for p in pals), 2),
            total_volume_m3=round(sum(p.total_volume_m3 for p in pals), 4),
            avg_fill_rate_pct=round(sum(p.fill_rate_pct for p in pals) / len(pals), 1) if pals else 0,
        ) for pt, pals in sorted(groups.items())]

    def _build_compliance(self, validations: List[ConstraintValidationResult]) -> List[str]:
        has_geo = any(any("çakışma" in v.lower() or "overlap" in v.lower() for v in val.violations) for val in validations)
        has_ispm = any(any("ISPM" in v for v in val.violations) for val in validations)
        has_cog = any(any("ağırlık merkezi" in v.lower() for v in val.violations) for val in validations)
        return [
            f"CTU Code 2014: {'FAIL' if has_geo else 'OK'}",
            f"ISPM-15: {'FAIL' if has_ispm else 'OK'}",
            f"CoG Balance: {'FAIL' if has_cog else 'OK'}",
        ]

    # ── ZORUNLU VALIDATION (KURAL-2) ──

    def _validate_all_pallets(self) -> List[ConstraintValidationResult]:
        results = []
        for pallet in self.pallets:
            violations, warnings, errors = [], [], []
            overflow_l, overflow_w = self._overflow_length, self._overflow_width
            max_h = self._effective_max_height
            pid = f"Palet-{pallet.pallet_number}"

            rects = pallet.layout_data.get("placed_rects", [])

            # Boyut
            for rect in rects:
                if rect["y"] + rect["dy"] > overflow_l + 0.01:
                    m = f"{pid}: Sağ kenar aşıldı"
                    violations.append(m)
                    errors.append(ActionableError(code="LENGTH_EXCEEDED", message=m, action_label="Ürün Çıkar", affected_pallet_id=pid))
                if rect["x"] + rect["dx"] > overflow_w + 0.01:
                    m = f"{pid}: Arka kenar aşıldı"
                    violations.append(m)
                    errors.append(ActionableError(code="WIDTH_EXCEEDED", message=m, action_label="Ürün Çıkar", affected_pallet_id=pid))
                if rect["z"] + rect["dz"] > max_h + 0.001:
                    m = f"{pid}: Yükseklik ({rect['z']+rect['dz']:.1f}cm) > max ({max_h:.1f}cm)"
                    violations.append(m)
                    errors.append(ActionableError(code="HEIGHT_EXCEEDED", message=m, action_label="Paleti Böl", affected_pallet_id=pid))

            # Ağırlık
            if pallet.total_weight_kg > self.config.max_weight_kg:
                m = f"{pid}: Ağırlık ({pallet.total_weight_kg:.1f}kg) > max ({self.config.max_weight_kg}kg)"
                violations.append(m)
                errors.append(ActionableError(code="WEIGHT_EXCEEDED", message=m, action_label="Ürün Çıkar", affected_pallet_id=pid))

            # Overlap
            overlaps = check_overlap(rects)
            if overlaps:
                m = f"{pid}: {len(overlaps)} çakışma — geometrik hata"
                violations.append(m)
                errors.append(ActionableError(code="GEOMETRY_ERROR", message=m, action_label="Yeniden Optimize Et", affected_pallet_id=pid))

            # NO_STACK
            for p in pallet.products:
                pc = set(p.constraints or [])
                if p.constraint:
                    pc.add(p.constraint)
                if ConstraintType.NO_STACK in pc:
                    p_top = p.pos_z + p.height_cm
                    for other in pallet.products:
                        if other is p:
                            continue
                        if (other.pos_z >= p_top - 0.01 and
                            other.pos_x < p.pos_x + p.width_cm and other.pos_x + other.width_cm > p.pos_x and
                            other.pos_y < p.pos_y + p.length_cm and other.pos_y + other.length_cm > p.pos_y):
                            m = f"{pid}: NO_STACK ihlali: '{p.name}' üzerine '{other.name}'"
                            violations.append(m)
                            errors.append(ActionableError(code="NO_STACK_VIOLATION", message=m, action_label="Yeniden Düzenle", affected_pallet_id=pid))

            # ISPM-15
            if self.settings.enforce_ispm15 and self.config.material == "wood" and not self.config.is_ispm15:
                m = f"{pid}: ISPM-15 ihlali — ısıl işlemsiz ahşap palet"
                violations.append(m)
                errors.append(ActionableError(code="ISPM15_VIOLATION", message=m, action_label="Palet Tipini Değiştir", affected_pallet_id=pid))

            # Soft: ağırlık hiyerarşisi
            for i, p1 in enumerate(pallet.products):
                for p2 in pallet.products[i+1:]:
                    if p1.pos_z < p2.pos_z and p2.weight_kg > p1.weight_kg * 1.5:
                        warnings.append(f"Ağırlık uyarısı: '{p2.name}' ({p2.weight_kg}kg) '{p1.name}' ({p1.weight_kg}kg) üzerinde")

            # Soft: void gap
            warnings.extend(check_void_gaps(rects, self.config.length_cm, self.config.width_cm, self.settings.max_void_gap_cm))

            # Soft: McKee BCT
            if self.settings.packaging_enabled:
                for p in pallet.products:
                    if 0 < p.bct_safety_factor < 1.5:
                        warnings.append(f"{p.name}: BCT güvenlik faktörü {p.bct_safety_factor:.1f} < 1.5")

            # Soft: doluluk
            if pallet.fill_rate_pct < self.settings.suggestion_trigger_pct:
                warnings.append(f"{pid}: Düşük doluluk %{pallet.fill_rate_pct:.0f}")

            # Soft/Hard: CoG (ağırlık merkezi) kontrolü
            if pallet.products:
                cog_dev = self._cog_deviation_pct(pallet)
                if cog_dev > 25:
                    m = f"{pid}: Ağırlık merkezi sapması kritik: %{cog_dev:.0f} (max %25)"
                    violations.append(m)
                    errors.append(ActionableError(code="COG_CRITICAL", message=m,
                                                  action_label="Yeniden Düzenle", affected_pallet_id=pid))
                elif cog_dev > 15:
                    warnings.append(f"{pid}: Ağırlık merkezi sapması yüksek: %{cog_dev:.0f} — dengesiz palet riski")

            # Constraint Engine
            if self._constraint_engine and pallet.products:
                violations += self._engine_validate_pallet(pallet)

            results.append(ConstraintValidationResult(
                pallet_number=pallet.pallet_number, passed=len(violations) == 0,
                violations=violations, warnings=warnings, errors=errors,
            ))
        return results

    def _engine_validate_pallet(self, pallet: OptimizedPallet) -> List[str]:
        violations = []
        placed_so_far = []
        for p in pallet.products:
            p_pcs = self._product_constraints_from_packed(p)
            decision = self._constraint_engine.can_place_on_pallet(
                item_name=p.name, item_constraints=p_pcs, pallet_items=placed_so_far,
            )
            for v in decision.violations:
                if v.severity.value == "error":
                    violations.append(f"[{v.constraint_code}] {v.message}")
            placed_so_far.append((p.name, p_pcs))
        return violations


# ============================================================
# Karma Palet Optimizasyonu
# ============================================================

class MixedBinPackingOptimizer:
    ALGORITHM_VERSION = "mixed-rect-skyline-v6.0"

    def __init__(self, pallet_configs: List[PalletConfig], default_type: PalletConfig = None,
                 params: Optional[OptimizationParams] = None,
                 settings: Optional[OptimizerSettings] = None,
                 constraint_engine=None):
        self.configs = pallet_configs
        self.default = default_type or pallet_configs[0]
        self.params = params or OptimizationParams()
        self.settings = settings or self.params.to_settings()
        self._constraint_engine = constraint_engine

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        start = time.time()
        input_summary: Dict[str, int] = {}
        for p in products:
            input_summary[p.name] = input_summary.get(p.name, 0) + p.quantity

        # ── Faz 1: Global karşılaştırma — her palet tipiyle TÜM ürünleri dene ──
        # Hangisi minimum palet sayısı veriyorsa onu seç
        best_global_result = None
        best_global_pallets = float('inf')
        best_global_cfg = self.default

        for cfg in self.configs:
            trial = BinPackingOptimizer3D(cfg, params=self.params, settings=self.settings,
                                         constraint_engine=self._constraint_engine)
            trial_result = trial.optimize(products)
            if (not trial_result.rejected_items and
                    trial_result.quantity_audit.get('balanced', False) and
                    trial_result.constraints_satisfied):
                # Palet sayısı daha az veya eşitse doluluk karşılaştır
                is_better = False
                if trial_result.total_pallets < best_global_pallets:
                    is_better = True
                elif (trial_result.total_pallets == best_global_pallets and
                      best_global_result and
                      trial_result.avg_fill_rate_pct > best_global_result.avg_fill_rate_pct):
                    is_better = True
                if is_better:
                    best_global_pallets = trial_result.total_pallets
                    best_global_result = trial_result
                    best_global_cfg = cfg
            elif (best_global_result is None and
                  trial_result.quantity_audit.get('balanced', False)):
                # Henüz iyi sonuç yoksa ilkini al
                best_global_pallets = trial_result.total_pallets
                best_global_result = trial_result
                best_global_cfg = cfg

        # Default ile de dene (zaten configs içinde ama garantiye al)
        if best_global_result is None:
            base = BinPackingOptimizer3D(self.default, params=self.params, settings=self.settings,
                                         constraint_engine=self._constraint_engine)
            best_global_result = base.optimize(products)
            best_global_cfg = self.default

        logger.info(f"[Mixed] Global en iyi: {best_global_cfg.type} → {best_global_pallets} palet")

        # ── Faz 2: Palet bazlı iyileştirme — her paleti alternatif tiplerle dene ──
        improved_pallets: List[OptimizedPallet] = []
        for pallet in best_global_result.pallets:
            best_pallet, best_fill = pallet, pallet.fill_rate_pct
            pallet_items = [ProductItem(
                name=p.name, quantity=p.quantity, length_cm=p.length_cm, width_cm=p.width_cm,
                height_cm=p.height_cm, weight_kg=p.weight_kg, constraint=p.constraint,
                constraints=list(p.constraints) if p.constraints else [],
            ) for p in pallet.products]

            for cfg in self.configs:
                if cfg.type == best_global_cfg.type:
                    continue
                test = BinPackingOptimizer3D(cfg, params=self.params, settings=self.settings,
                                            constraint_engine=self._constraint_engine)
                tr = test.optimize(pallet_items)
                if (len(tr.pallets) == 1 and not tr.rejected_items and
                        tr.quantity_audit.get('balanced', False) and
                        tr.avg_fill_rate_pct > best_fill and tr.constraints_satisfied):
                    best_fill = tr.avg_fill_rate_pct
                    candidate = tr.pallets[0]
                    candidate.pallet_number = pallet.pallet_number
                    best_pallet = candidate
            improved_pallets.append(best_pallet)

        all_rejected = list(best_global_result.rejected_items)
        all_warnings = list(best_global_result.warnings)
        duration_ms = int((time.time() - start) * 1000)

        total_weight = sum(p.total_weight_kg for p in improved_pallets)
        total_volume = sum(p.total_volume_m3 for p in improved_pallets)
        avg_fill = sum(p.fill_rate_pct for p in improved_pallets) / len(improved_pallets) if improved_pallets else 0
        total_items = sum(sum(pr.quantity for pr in p.products) for p in improved_pallets)

        from collections import defaultdict
        groups: Dict[str, List[OptimizedPallet]] = defaultdict(list)
        for p in improved_pallets:
            groups[p.pallet_type].append(p)
        type_breakdown = [PalletTypeSummary(
            pallet_type=pt, count=len(pals),
            total_weight_kg=round(sum(p.total_weight_kg for p in pals), 2),
            total_volume_m3=round(sum(p.total_volume_m3 for p in pals), 4),
            avg_fill_rate_pct=round(sum(p.fill_rate_pct for p in pals) / len(pals), 1) if pals else 0,
        ) for pt, pals in sorted(groups.items())]

        # Her paleti kendi tipinin config'i ile doğrula (EUR/STD/TIR ayrımı)
        cfg_map = {c.type: c for c in self.configs}
        validations = []
        for pal in improved_pallets:
            pal_cfg = cfg_map.get(pal.pallet_type, self.default)
            v = BinPackingOptimizer3D(pal_cfg, params=self.params, settings=self.settings,
                                     constraint_engine=self._constraint_engine)
            v.pallets = [pal]
            validations.extend(v._validate_all_pallets())
        all_passed = all(v.passed for v in validations)
        if not all_passed:
            all_warnings.append(f"⛔ {sum(1 for v in validations if not v.passed)} palette kısıt ihlali")

        actionable_errors = []
        for v in validations:
            actionable_errors.extend(v.errors)
        # Compliance: herhangi bir palet tipiyle build edilebilir (yapısal veri)
        _any_validator = BinPackingOptimizer3D(self.default, params=self.params, settings=self.settings,
                                              constraint_engine=self._constraint_engine)
        compliance = _any_validator._build_compliance(validations)

        placed_counts: Dict[str, int] = {}
        for pal in improved_pallets:
            for p in pal.products:
                placed_counts[p.name] = placed_counts.get(p.name, 0) + p.quantity
        rejected_counts: Dict[str, int] = {}
        for r in all_rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1
        ti = sum(input_summary.values())
        tp = sum(placed_counts.values())
        tr_count = sum(rejected_counts.values())
        is_balanced = ti == tp + tr_count
        if not is_balanced:
            all_warnings.append(f"⛔ MİKTAR UYUMSUZLUĞU: girdi={ti}, yerleştirilen={tp}, reddedilen={tr_count}")

        return OptimizationResult(
            pallets=improved_pallets, total_pallets=len(improved_pallets),
            total_weight_kg=total_weight, total_volume_m3=total_volume, avg_fill_rate_pct=avg_fill,
            items_per_pallet=total_items / len(improved_pallets) if improved_pallets else 0,
            duration_ms=duration_ms, rejected_items=all_rejected, warnings=all_warnings,
            algorithm_version=self.ALGORITHM_VERSION, pallet_type_breakdown=type_breakdown,
            constraint_validations=validations, constraints_satisfied=all_passed,
            quantity_audit={"input": input_summary, "placed": placed_counts, "rejected": rejected_counts,
                           "total_input": ti, "total_placed": tp, "total_rejected": tr_count, "balanced": is_balanced},
            actionable_errors=actionable_errors, compliance=compliance,
        )


# ============================================================
# Senaryo Optimizasyonu — Binding Dimension
# ============================================================

@dataclass
class VehicleConfig:
    id: str
    name: str
    type: str
    length_cm: float
    width_cm: float
    height_cm: float
    max_weight_kg: float
    pallet_capacity: int
    base_cost: float
    fuel_per_km: float
    driver_per_hour: float
    opportunity_cost: float
    distance_km: float
    duration_hours: float
    is_reefer: bool = False
    wheelbase_cm: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.base_cost + self.fuel_per_km * self.distance_km + self.driver_per_hour * self.duration_hours + self.opportunity_cost

    @property
    def volume_m3(self) -> float:
        return (self.length_cm * self.width_cm * self.height_cm) / 1_000_000

    @classmethod
    def from_dict(cls, d: dict, distance_km: float = 200, duration_hours: float = 4) -> "VehicleConfig":
        return cls(
            id=d.get("id", str(uuid.uuid4())), name=d["name"], type=d.get("type", "custom"),
            length_cm=float(d["length_cm"]), width_cm=float(d["width_cm"]), height_cm=float(d["height_cm"]),
            max_weight_kg=float(d["max_weight_kg"]), pallet_capacity=int(d.get("pallet_capacity", 0)),
            base_cost=float(d.get("base_cost", 0)), fuel_per_km=float(d.get("fuel_per_km", 0)),
            driver_per_hour=float(d.get("driver_per_hour", 0)), opportunity_cost=float(d.get("opportunity_cost", 0)),
            distance_km=distance_km, duration_hours=duration_hours,
            is_reefer=bool(d.get("is_reefer", False)), wheelbase_cm=float(d.get("wheelbase_cm", 0)),
        )


@dataclass
class VehicleAssignment:
    vehicle: VehicleConfig
    pallet_ids: List[int]
    current_weight_kg: float
    current_volume_m3: float
    cost: float
    front_weight_kg: float = 0.0
    rear_weight_kg: float = 0.0
    front_pct: float = 0.0
    balance_ok: bool = True
    binding_dimension: str = ""
    vol_utilization_pct: float = 0.0
    weight_utilization_pct: float = 0.0
    pallet_utilization_pct: float = 0.0


@dataclass
class ScenarioResult:
    name: str
    strategy: ScenarioStrategy
    vehicles: List[VehicleAssignment]
    total_cost: float
    cost_per_pallet: float
    total_vehicles: int
    avg_fill_rate_pct: float
    is_recommended: bool = False
    avg_balance_pct: float = 0.0


class ScenarioOptimizer:
    """
    minimize N_vehicles → binding dimension yaklaşımı.
    binding = min(vol_ratio, weight_ratio, pallet_ratio)
    """

    def __init__(self, pallets: List[OptimizedPallet], vehicles: List[VehicleConfig],
                 params: Optional[OptimizationParams] = None,
                 settings: Optional[OptimizerSettings] = None):
        self.pallets = pallets
        self.vehicles = vehicles
        self.params = params or OptimizationParams()
        self.settings = settings or self.params.to_settings()

    def generate_all(self) -> List[ScenarioResult]:
        if not self.pallets or not self.vehicles:
            return []
        scenarios = [
            self._generate(ScenarioStrategy.MIN_VEHICLES),
            self._generate(ScenarioStrategy.BALANCED),
            self._generate(ScenarioStrategy.MAX_EFFICIENCY),
        ]
        valid = [s for s in scenarios if s.total_vehicles > 0]
        if valid:
            best = min(valid, key=lambda s: (s.total_vehicles, s.total_cost, -s.avg_fill_rate_pct))
            best.is_recommended = True
        return scenarios

    def _generate(self, strategy: ScenarioStrategy) -> ScenarioResult:
        if strategy == ScenarioStrategy.MIN_VEHICLES:
            return self._min_vehicles()
        elif strategy == ScenarioStrategy.BALANCED:
            return self._balanced()
        return self._max_efficiency()

    def _compute_binding(self, va: VehicleAssignment, assigned: List[OptimizedPallet]):
        v = va.vehicle
        vol = sum(p.total_volume_m3 for p in assigned)
        wt = sum(p.total_weight_kg for p in assigned)
        n = len(assigned)
        vr = (vol / v.volume_m3 * 100) if v.volume_m3 > 0 else 0
        wr = (wt / v.max_weight_kg * 100) if v.max_weight_kg > 0 else 0
        pr = (n / v.pallet_capacity * 100) if v.pallet_capacity > 0 else 0
        va.vol_utilization_pct = round(vr, 1)
        va.weight_utilization_pct = round(wr, 1)
        va.pallet_utilization_pct = round(pr, 1)
        ratios = {"volume": vr, "weight": wr, "pallet_count": pr}
        va.binding_dimension = max(ratios, key=ratios.get) if any(v > 0 for v in ratios.values()) else "volume"

    def _compute_weight_balance(self, va: VehicleAssignment, assigned: List[OptimizedPallet]):
        v = va.vehicle
        tw = sum(p.total_weight_kg for p in assigned)
        if tw <= 0 or v.length_cm <= 0 or not assigned:
            va.balance_ok = True
            return
        step = v.length_cm / len(assigned)
        cg = sum(p.total_weight_kg * (i * step + step / 2) for i, p in enumerate(assigned)) / tw
        front_pct = (1 - cg / v.length_cm) * 100
        va.front_pct = round(front_pct, 1)
        va.front_weight_kg = round(tw * front_pct / 100, 1)
        va.rear_weight_kg = round(tw * (100 - front_pct) / 100, 1)
        va.balance_ok = abs(front_pct - self.settings.weight_front_ratio_pct) <= self.settings.weight_front_tolerance_pct

    def _assign_greedy(self, sorted_v: List[VehicleConfig], remaining: List[OptimizedPallet]) -> List[VehicleAssignment]:
        assignments = []
        unassigned = list(remaining)
        for vehicle in sorted_v:
            if not unassigned:
                break
            batch, bw, bv = [], 0.0, 0.0
            for pallet in list(unassigned):
                if vehicle.pallet_capacity > 0 and len(batch) >= vehicle.pallet_capacity:
                    break
                if bw + pallet.total_weight_kg > vehicle.max_weight_kg:
                    continue
                if bv + pallet.total_volume_m3 > vehicle.volume_m3:
                    continue
                batch.append(pallet)
                bw += pallet.total_weight_kg
                bv += pallet.total_volume_m3
                unassigned.remove(pallet)
            if batch:
                va = VehicleAssignment(vehicle=vehicle, pallet_ids=[p.pallet_number for p in batch],
                                       current_weight_kg=round(bw, 2), current_volume_m3=round(bv, 4),
                                       cost=round(vehicle.total_cost, 2))
                self._compute_binding(va, batch)
                self._compute_weight_balance(va, batch)
                assignments.append(va)
        while unassigned:
            smallest = sorted_v[-1] if sorted_v else None
            if not smallest:
                break
            batch, bw, bv = [], 0.0, 0.0
            for pallet in list(unassigned):
                if smallest.pallet_capacity > 0 and len(batch) >= smallest.pallet_capacity:
                    break
                if bw + pallet.total_weight_kg > smallest.max_weight_kg:
                    continue
                batch.append(pallet)
                bw += pallet.total_weight_kg
                bv += pallet.total_volume_m3
                unassigned.remove(pallet)
            if batch:
                va = VehicleAssignment(vehicle=smallest, pallet_ids=[p.pallet_number for p in batch],
                                       current_weight_kg=round(bw, 2), current_volume_m3=round(bv, 4),
                                       cost=round(smallest.total_cost, 2))
                self._compute_binding(va, batch)
                self._compute_weight_balance(va, batch)
                assignments.append(va)
            else:
                break
        return assignments

    def _min_vehicles(self) -> ScenarioResult:
        sv = sorted(self.vehicles, key=lambda v: v.max_weight_kg, reverse=True)
        return self._build_scenario("En Az Araç", ScenarioStrategy.MIN_VEHICLES, self._assign_greedy(sv, list(self.pallets)))

    def _balanced(self) -> ScenarioResult:
        sv = sorted(self.vehicles, key=lambda v: v.max_weight_kg)
        mid = len(sv) // 2
        return self._build_scenario("Dengeli Dağılım", ScenarioStrategy.BALANCED, self._assign_greedy(sv[mid:] + sv[:mid], list(self.pallets)))

    def _max_efficiency(self) -> ScenarioResult:
        tw = sum(p.total_weight_kg for p in self.pallets)
        tv = sum(p.total_volume_m3 for p in self.pallets)
        np_ = len(self.pallets)
        scored = []
        for v in self.vehicles:
            vr = tv / v.volume_m3 if v.volume_m3 > 0 else 0
            wr = tw / v.max_weight_kg if v.max_weight_kg > 0 else 0
            pr = np_ / v.pallet_capacity if v.pallet_capacity > 0 else 0
            n_needed = max(1, math.ceil(max(vr, wr, pr)))
            waste = n_needed - max(vr, wr, pr)
            scored.append((waste, v.total_cost * n_needed, v))
        scored.sort(key=lambda x: (x[0], x[1]))
        return self._build_scenario("Max Verimlilik", ScenarioStrategy.MAX_EFFICIENCY, self._assign_greedy([s[2] for s in scored], list(self.pallets)))

    def _build_scenario(self, name: str, strategy: ScenarioStrategy, assignments: List[VehicleAssignment]) -> ScenarioResult:
        total_cost = sum(a.cost for a in assignments)
        avg_fill = sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets) if self.pallets else 0
        avg_bal = sum(a.front_pct for a in assignments) / len(assignments) if assignments else 0
        return ScenarioResult(
            name=name, strategy=strategy, vehicles=assignments,
            total_cost=round(total_cost, 2),
            cost_per_pallet=round(total_cost / len(self.pallets), 2) if self.pallets else 0,
            total_vehicles=len(assignments), avg_fill_rate_pct=round(avg_fill, 1),
            avg_balance_pct=round(avg_bal, 1),
        )
