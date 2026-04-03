"""
Cronoi LS — 3D Bin Packing Optimizer v6.0
Scored-Candidate Skyline 3D bin packing — OPTIMIZER_SPEC.md uyumlu

Yerleşim Önceliği (KURAL-3, değiştirilemez):
  X-yönü (yan yana) → Y-yönü (yeni satır) → Z-yönü (üst üste)
  Z-yönüne skor cezası uygulanır, asla ilk tercih değildir.

Parametrik (KURAL-1):
  Tüm boyut, ağırlık ve kapasite değerleri dışarıdan gelir.
  Optimizer'da HİÇBİR boyut, ağırlık veya kapasite sabit kodlanmaz.
  PalletConfig.tare_height_cm, vehicle_max_height_cm, overflow_tolerance_pct
  gibi tüm değerler çağırıcıdan (shipments.py / settings UI) beslenir.

Validation (KURAL-2):
  Her optimizasyon sonrası zorunlu çalışır. Asla atlanamaz.

Katmanlar:
  Katman 1 — HARD CONSTRAINTS (Kırılamaz)
  Katman 2 — SOFT CONSTRAINTS (Tercihler → skor cezası)
  Katman 3 — OPTIMIZATION OBJECTIVES (Doluluk, denge)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Set
from enum import Enum
import math
import uuid
import logging

logger = logging.getLogger(__name__)

# Standart EUR palet tahtası yüksekliği (cm) — geriye dönük uyumluluk için.
# Yeni kodda PalletConfig.tare_height_cm kullanılır.
PALLET_BOARD_HEIGHT_CM = 15

# Varsayılan taşma toleransı — %5
DEFAULT_OVERFLOW_TOLERANCE_PCT = 5.0

# ── Yerleşim yönü skor ağırlıkları (KURAL-3) ──
DIRECTION_SCORES = {
    "x_extend": 100,   # Yan yana — en iyi
    "y_new_row": 50,    # Yeni satır (derinlik yönü)
    "z_stack": 10,      # Üst üste — en az tercih
}


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


class ScenarioStrategy(str, Enum):
    MIN_VEHICLES = "min_vehicles"
    BALANCED = "balanced"
    MAX_EFFICIENCY = "max_efficiency"


# ── Ağırlık Hiyerarşisi (düşük = alta) ──
WEIGHT_HIERARCHY = {
    ConstraintType.MUST_BOTTOM: 0,
    ConstraintType.HEAVY: 1,
    None: 2,
    ConstraintType.TEMP: 2,
    ConstraintType.FRAGILE: 3,
    ConstraintType.NO_STACK: 3,
    ConstraintType.MUST_TOP: 4,
}


# ── Katman sınıfı yoğunluk eşikleri (kg/m³) ──
DENSITY_BOTTOM_THRESHOLD = 400   # Üzeri → katman 0 (alt)
DENSITY_TOP_THRESHOLD = 200      # Altı → katman 2 (üst)


@dataclass
class OptimizationParams:
    """Parametrik optimizasyon ayarları — Settings UI'dan gelir, hard-code yok."""
    height_safety_margin_cm: float = 0
    pallet_gap_cm: float = 3
    enforce_constraints: bool = True
    weight_balance_target: float = 0.60
    weight_balance_tolerance: float = 0.10
    max_iterations: int = 12
    optimality_target: float = 90.0
    overflow_tolerance_pct: float = 5.0
    vehicle_max_height_cm: float = 0

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
        )


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
    def layer_priority(self) -> int:
        c = self.all_constraints
        best = 2
        for ct in c:
            prio = WEIGHT_HIERARCHY.get(ct, 2)
            best = min(best, prio)
        return best

    @property
    def layer_class(self) -> int:
        """Katman sınıfı: 0=alt(ağır), 1=orta(normal), 2=üst(hafif/kırılgan)"""
        c = self.all_constraints
        if ConstraintType.MUST_BOTTOM in c or ConstraintType.HEAVY in c:
            return 0
        if self.density_kg_m3 > DENSITY_BOTTOM_THRESHOLD:
            return 0
        if ConstraintType.MUST_TOP in c or ConstraintType.FRAGILE in c:
            return 2
        if self.density_kg_m3 < DENSITY_TOP_THRESHOLD and self.density_kg_m3 > 0:
            return 2
        return 1


@dataclass
class PalletConfig:
    type: str
    width_cm: float
    length_cm: float
    max_height_cm: float
    max_weight_kg: float
    tare_height_cm: float = 15.0   # Palet kendi yüksekliği (tahta)

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
            type=d.get("code", "custom"),
            width_cm=d["width_cm"],
            length_cm=d["length_cm"],
            max_height_cm=d.get("max_height_cm", 180),
            max_weight_kg=d["max_weight_kg"],
            tare_height_cm=float(d.get("tare_height_cm", PALLET_BOARD_HEIGHT_CM)),
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
    layer_class: int = 1              # 0=alt, 1=orta, 2=üst
    placement_direction: str = ""     # x_extend | y_new_row | z_stack


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


@dataclass
class RejectedItem:
    name: str
    reason: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float


@dataclass
class ConstraintValidationResult:
    pallet_number: int
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


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
    algorithm_version: str = "scored-candidate-v6.0"
    pallet_type_breakdown: List[PalletTypeSummary] = field(default_factory=list)
    constraint_validations: List[ConstraintValidationResult] = field(default_factory=list)
    constraints_satisfied: bool = True
    quantity_audit: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 3D Bin Packing — Scored Candidate Skyline
# ============================================================

class BinPackingOptimizer3D:
    """
    Scored-Candidate 3D Bin Packing v6.0

    Algoritma:
    1. Ürünleri expand et (quantity → ayrı item)
    2. Constraint-aware + layer-class sıralama
    3. Her ürün için TÜM geçerli pozisyonları bul → skoru hesapla → en iyiyi seç
       - x_extend (yan yana) : +100 puan
       - y_new_row (yeni satır) : +50 puan
       - z_stack (üst üste) : +10 puan
    4. HARD kontroller her yerleşimde (boyut, ağırlık, yükseklik)
    5. Post-optimization validation (KURAL-2: zorunlu, atlanamaz)

    Parametrik: Tüm limit değerleri PalletConfig + OptimizationParams'tan gelir.
    """

    ALGORITHM_VERSION = "scored-candidate-v6.0"

    def __init__(self, pallet_config: PalletConfig, params: Optional[OptimizationParams] = None,
                 constraint_engine=None):
        self.config = pallet_config
        self.params = params or OptimizationParams()
        self.pallets: List[OptimizedPallet] = []
        self.rejected: List[RejectedItem] = []
        self.warnings: List[str] = []
        self._constraint_engine = constraint_engine
        self._input_summary: Dict[str, int] = {}

    # ── Efektif Limitler (parametrik — hardcode yok) ──

    @property
    def _effective_max_height(self) -> float:
        """Kargo alanı max yüksekliği.

        Hesap:
          1. Baz = palet max_height_cm (pallet_types tablosundan)
          2. Araç limiti varsa: min(baz, araç_iç_yükseklik - palet_tare_height)
          3. Güvenlik payı düş
        Tolerans yüksekliğe UYGULANMAZ — yükseklik hard constraint.
        """
        base = self.config.max_height_cm
        if self.params.vehicle_max_height_cm > 0:
            vehicle_cargo_h = self.params.vehicle_max_height_cm - self.config.tare_height_cm
            base = min(base, vehicle_cargo_h)
        return base - self.params.height_safety_margin_cm

    @property
    def _overflow_length(self) -> float:
        return self.config.length_cm * (1 + self.params.overflow_tolerance_pct / 100.0)

    @property
    def _overflow_width(self) -> float:
        return self.config.width_cm * (1 + self.params.overflow_tolerance_pct / 100.0)

    # ── Ana Akış ──

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        import time
        start = time.time()

        self._input_summary = {}
        for p in products:
            self._input_summary[p.name] = self._input_summary.get(p.name, 0) + p.quantity

        items = self._expand_items(products)
        sorted_items = self._constraint_aware_sort(items)
        self._pack(sorted_items)
        self._verify_quantities()

        duration_ms = int((time.time() - start) * 1000)
        return self._build_result(duration_ms)

    # ── Ürün Hazırlık ──

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
                ))
        return items

    def _constraint_aware_sort(self, items: List[ProductItem]) -> List[ProductItem]:
        """Sıralama: katman sınıfı → ağırlık (ağır önce) → hacim (büyük önce)"""
        def sort_key(item: ProductItem):
            return (
                item.layer_class,       # 0=alt önce, 2=üst son
                -item.weight_kg,        # Ağır önce
                -item.volume_cm3,       # Büyük hacim önce (FFD)
            )
        return sorted(items, key=sort_key)

    # ── Orientasyon ──

    def _get_valid_orientations(self, item: ProductItem) -> List[Tuple[float, float, float, bool]]:
        """Palete sığan tüm 3D orientasyonları döndür (l, w, h, rotated).

        rotation_allowed=True  → 6 permütasyon
        rotation_allowed=False → yalnızca orijinal orientasyon
        Sıralama: en düşük yükseklik önce (yan yana yerleşimi maksimize eder).
        Kenar taşma toleransı L ve W'ye uygulanır; yüksekliğe UYGULANMAZ.
        """
        from itertools import permutations as perms

        L, W, H = item.length_cm, item.width_cm, item.height_cm
        pL = self._overflow_length
        pW = self._overflow_width
        pH = self._effective_max_height

        candidates = set(perms([L, W, H])) if item.rotation_allowed else {(L, W, H)}

        valid = []
        for l, w, h in candidates:
            if l <= pL and w <= pW and h <= pH:
                rotated = not (l == L and w == W and h == H)
                valid.append((l, w, h, rotated))

        # En düşük yükseklik → daha fazla yan yana fırsat
        valid.sort(key=lambda o: (o[2], max(o[0], o[1])))
        return valid

    def _item_fits_pallet(self, item: ProductItem) -> bool:
        if item.weight_kg > self.config.max_weight_kg:
            return False
        return len(self._get_valid_orientations(item)) > 0

    # ── Yerleştirme Akışı ──

    def _pack(self, items: List[ProductItem]):
        top_items = []
        normal_items = []
        for item in items:
            if item.must_be_top:
                top_items.append(item)
            else:
                normal_items.append(item)

        for item in normal_items:
            self._place_item(item)
        for item in top_items:
            self._place_item(item)

    def _place_item(self, item: ProductItem):
        if not self._item_fits_pallet(item):
            reason = self._rejection_reason(item)
            self.rejected.append(RejectedItem(
                name=item.name, reason=reason,
                length_cm=item.length_cm, width_cm=item.width_cm,
                height_cm=item.height_cm, weight_kg=item.weight_kg,
            ))
            self.warnings.append(f"⚠️ '{item.name}' reddedildi: {reason}")
            return

        for pallet in self.pallets:
            if self._try_place_scored(pallet, item):
                return

        new_pallet = OptimizedPallet(
            pallet_number=len(self.pallets) + 1,
            pallet_type=self.config.type,
        )
        new_pallet.layout_data = {"placed_rects": []}
        if self._try_place_scored(new_pallet, item):
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
            return (f"Tek parça ağırlık ({item.weight_kg}kg) palet kapasitesini "
                    f"({self.config.max_weight_kg}kg) aşıyor")
        if not self._get_valid_orientations(item):
            return (f"Hiçbir orientasyonda ({item.length_cm}×{item.width_cm}×{item.height_cm}cm) "
                    f"palete ({self.config.length_cm}×{self.config.width_cm}×{pH}cm) sığmıyor")
        return "Palet boyut limitleri aşıldı"

    # ── SCORED CANDIDATE CORE (KURAL-3 uygulaması) ──

    def _try_place_scored(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """Ürünü palete scored-candidate yaklaşımıyla yerleştir.

        Tüm geçerli pozisyon × orientasyon kombinasyonlarını değerlendirir.
        Her aday için yön sınıflandırması + skor hesaplanır.
        En yüksek skorlu aday seçilir.

        Yön Önceliği (KURAL-3):
          x_extend (+100) > y_new_row (+50) > z_stack (+10)
        """

        # ── HARD: Ağırlık kontrolü ──
        if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
            return False
        if not self._item_fits_pallet(item):
            return False

        # ── HARD: Constraint Engine / Temel uyumluluk ──
        if self.params.enforce_constraints:
            if self._constraint_engine:
                if not self._engine_allows_placement(pallet, item):
                    return False
            elif not self._constraints_compatible(pallet, item):
                return False

        placed = pallet.layout_data.get("placed_rects", [])
        pL = self._overflow_length
        pW = self._overflow_width
        pH = self._effective_max_height

        orientations = self._get_valid_orientations(item)
        if not orientations:
            return False

        # Aday anchor noktaları: mevcut ürünlerin kenarları + orijin
        xs = sorted({0.0} | {r["x"] + r["l"] for r in placed})
        zs = sorted({0.0} | {r["z"] + r["w"] for r in placed})

        best = None   # (score, x, y, z, pl, pw, ph, rotated, direction)

        for pl, pw, ph_item, rotated in orientations:
            for x in xs:
                if x + pl > pL + 0.01:
                    continue
                for z in zs:
                    if z + pw > pW + 0.01:
                        continue

                    y = self._support_height(placed, x, z, pl, pw)

                    # ── HARD: Yükseklik limiti — kesinlikle aşılamaz ──
                    if y + ph_item > pH + 0.01:
                        continue

                    # ── Yön sınıflandırması ──
                    direction = self._classify_direction(placed, x, z, y)

                    # ── Skor hesapla ──
                    score = self._score_placement(
                        direction, x, y, z, pl, pw, ph_item, item, pH
                    )

                    if best is None or score > best[0]:
                        best = (score, x, y, z, pl, pw, ph_item, rotated, direction)

        if best is not None:
            _, x, y, z, pl, pw, ph_item, rotated, direction = best
            self._commit_place(pallet, item, x, y, z, pl, pw, ph_item, rotated, direction)
            return True

        return False

    def _classify_direction(self, placed: List[Dict], x: float, z: float, y: float) -> str:
        """Yerleşim yönünü sınıflandır.

        - z_stack  : y > 0 → mevcut ürünlerin üstüne
        - x_extend : y == 0 ve aynı z-bandında mevcut ürün var → satır genişletme
        - y_new_row: y == 0 ve yeni z pozisyonu → yeni satır (derinlik)
        """
        if y > 0.01:
            return "z_stack"

        # Zemin seviyesi — aynı z-bandında mevcut ürün var mı?
        for r in placed:
            if r["y"] < 0.01 and abs(r["z"] - z) < 0.01:
                return "x_extend"

        if placed:
            return "y_new_row"

        return "x_extend"  # İlk ürün

    def _score_placement(
        self, direction: str, x: float, y: float, z: float,
        pl: float, pw: float, ph: float,
        item: ProductItem, max_h: float,
    ) -> float:
        """Yerleşim skoru hesapla — yüksek skor = daha iyi pozisyon.

        Bileşenler:
          1. Yön bonusu (KURAL-3): x_extend=100, y_new_row=50, z_stack=10
          2. Yükseklik cezası: ne kadar yukarıda o kadar kötü
          3. Doluluk katkısı: büyük ürünü boş alana yerleştirmek iyi
          4. Ağır-tabanda bonusu: ağır ürün zemindeyse bonus
          5. Köşe/kenar bonusu: sıkı paketleme teşviki
        """
        score = 0.0

        # 1. Yön bonusu
        score += DIRECTION_SCORES.get(direction, 0)

        # 2. Yükseklik cezası (0–40 arası ceza)
        if max_h > 0:
            h_ratio = (y + ph) / max_h
            score -= h_ratio * 40

        # 3. Doluluk katkısı (0–30 arası bonus)
        item_vol = pl * pw * ph
        total_vol = self.config.length_cm * self.config.width_cm * max_h
        if total_vol > 0:
            score += (item_vol / total_vol) * 30

        # 4. Ağır ürün tabanda bonusu
        if item.weight_kg > 30 and y < 0.01:
            score += 20

        # 5. Köşe/kenar bonusu — sıkı paketleme
        if x < 0.01:
            score += 5
        if z < 0.01:
            score += 5

        return score

    # ── Destek Yüksekliği ──

    def _support_height(self, placed: List[Dict], x: float, z: float,
                        pl: float, pw: float) -> float:
        """Verilen footprint alanında en yüksek noktayı bul."""
        max_h = 0.0
        x2, z2 = x + pl, z + pw
        for r in placed:
            if (r["x"] < x2 and r["x"] + r["l"] > x and
                    r["z"] < z2 and r["z"] + r["w"] > z):
                top = r["y"] + r["h"]
                if top > max_h:
                    max_h = top
        return max_h

    # ── Yerleştirme Commit ──

    def _commit_place(
        self, pallet: OptimizedPallet, item: ProductItem,
        x: float, y: float, z: float,
        pl: float, pw: float, ph: float,
        rotated: bool, direction: str = "",
    ):
        packed = PackedItem(
            name=item.name, quantity=1,
            length_cm=pl, width_cm=pw, height_cm=ph,
            weight_kg=item.weight_kg,
            constraint=item.constraint,
            constraints=list(item.constraints),
            pos_x=round(x, 2), pos_y=round(y, 2), pos_z=round(z, 2),
            rotated=rotated,
            layer_class=item.layer_class,
            placement_direction=direction,
        )
        pallet.products.append(packed)

        rects = pallet.layout_data.setdefault("placed_rects", [])
        rects.append({"x": x, "z": z, "y": y, "l": pl, "w": pw, "h": ph})

        pallet.total_weight_kg += item.weight_kg
        pallet.total_volume_m3 += (pl * pw * ph) / 1_000_000

        pallet_max_vol = self.config.volume_cm3 / 1_000_000
        pallet.fill_rate_pct = (
            round((pallet.total_volume_m3 / pallet_max_vol) * 100, 1)
            if pallet_max_vol else 0
        )

        for ct in item.all_constraints:
            if ct not in pallet.constraints:
                pallet.constraints.append(ct)

        all_tops = [r["y"] + r["h"] for r in rects]
        pallet.total_height_cm = round(max(all_tops) if all_tops else 0, 2)

    # ── Constraint Engine Entegrasyonu ──

    def _engine_allows_placement(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        from app.services.constraint_engine import ProductConstraint

        item_pcs = self._to_product_constraints(item)
        pallet_items = []
        for p in pallet.products:
            p_pcs = self._product_constraints_from_packed(p)
            pallet_items.append((p.name, p_pcs))

        decision = self._constraint_engine.can_place_on_pallet(
            item_name=item.name,
            item_constraints=item_pcs,
            pallet_items=pallet_items,
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
            code_upper = code.upper()
            if code_upper in self._constraint_engine.constraints:
                cdef = self._constraint_engine.constraints[code_upper]
                pcs.append(ProductConstraint(definition=cdef, param_values={}))
            elif code in self._constraint_engine.constraints:
                cdef = self._constraint_engine.constraints[code]
                pcs.append(ProductConstraint(definition=cdef, param_values={}))
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
            code_upper = code.upper()
            if code_upper in self._constraint_engine.constraints:
                cdef = self._constraint_engine.constraints[code_upper]
                pcs.append(ProductConstraint(definition=cdef, param_values={}))
            elif code in self._constraint_engine.constraints:
                cdef = self._constraint_engine.constraints[code]
                pcs.append(ProductConstraint(definition=cdef, param_values={}))
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

        if ConstraintType.TEMP in item_c:
            return all(
                ConstraintType.TEMP in set(p.constraints or []) or p.constraint == ConstraintType.TEMP
                for p in pallet.products
            )
        if ConstraintType.TEMP in pallet_c:
            return ConstraintType.TEMP in item_c

        return True

    # ── Miktar Doğrulama ──

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
                    f"yerleştirilen={placed.get(name, 0)}, reddedilen={rejected_counts.get(name, 0)}, "
                    f"KAYIP={missing}"
                )
                for _ in range(missing):
                    self.rejected.append(RejectedItem(
                        name=name,
                        reason="Optimizasyon sırasında kayboldu — algoritma hatası",
                        length_cm=0, width_cm=0, height_cm=0, weight_kg=0,
                    ))
            elif actual > expected:
                self.warnings.append(
                    f"⚠️ MİKTAR FAZLASI: '{name}' → sipariş={expected}, çıktı={actual}"
                )

    # ── Sonuç Oluşturma ──

    def _build_result(self, duration_ms: int) -> OptimizationResult:
        total_weight = sum(p.total_weight_kg for p in self.pallets)
        total_volume = sum(p.total_volume_m3 for p in self.pallets)
        avg_fill = (
            round(sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets), 1)
            if self.pallets else 0
        )
        total_items = sum(
            sum(prod.quantity for prod in p.products) for p in self.pallets
        )

        type_breakdown = self._compute_pallet_type_breakdown()
        validations = self._validate_all_pallets()
        all_passed = all(v.passed for v in validations)
        if not all_passed:
            failed_count = sum(1 for v in validations if not v.passed)
            self.warnings.append(
                f"⛔ {failed_count} palette kısıt ihlali tespit edildi — detaylar constraint_validations'da"
            )

        quantity_audit = self._build_quantity_audit()

        return OptimizationResult(
            pallets=self.pallets,
            total_pallets=len(self.pallets),
            total_weight_kg=round(total_weight, 2),
            total_volume_m3=round(total_volume, 4),
            avg_fill_rate_pct=avg_fill,
            items_per_pallet=round(total_items / len(self.pallets), 1) if self.pallets else 0,
            duration_ms=duration_ms,
            rejected_items=self.rejected,
            warnings=self.warnings,
            algorithm_version=self.ALGORITHM_VERSION,
            pallet_type_breakdown=type_breakdown,
            constraint_validations=validations,
            constraints_satisfied=all_passed,
            quantity_audit=quantity_audit,
        )

    def _build_quantity_audit(self) -> Dict[str, Any]:
        placed_counts: Dict[str, int] = {}
        for pallet in self.pallets:
            for p in pallet.products:
                placed_counts[p.name] = placed_counts.get(p.name, 0) + p.quantity
        rejected_counts: Dict[str, int] = {}
        for r in self.rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1
        total_input = sum(self._input_summary.values())
        total_placed = sum(placed_counts.values())
        total_rejected = sum(rejected_counts.values())
        return {
            "input": self._input_summary,
            "placed": placed_counts,
            "rejected": rejected_counts,
            "total_input": total_input,
            "total_placed": total_placed,
            "total_rejected": total_rejected,
            "balanced": total_input == total_placed + total_rejected,
        }

    def _compute_pallet_type_breakdown(self) -> List[PalletTypeSummary]:
        from collections import defaultdict
        groups: Dict[str, List[OptimizedPallet]] = defaultdict(list)
        for p in self.pallets:
            groups[p.pallet_type].append(p)
        breakdown = []
        for ptype, pallets in sorted(groups.items()):
            total_w = sum(p.total_weight_kg for p in pallets)
            total_v = sum(p.total_volume_m3 for p in pallets)
            avg_f = sum(p.fill_rate_pct for p in pallets) / len(pallets) if pallets else 0
            breakdown.append(PalletTypeSummary(
                pallet_type=ptype,
                count=len(pallets),
                total_weight_kg=round(total_w, 2),
                total_volume_m3=round(total_v, 4),
                avg_fill_rate_pct=round(avg_f, 1),
            ))
        return breakdown

    # ── ZORUNLU POST-OPTIMIZATION VALIDATION (KURAL-2) ──

    def _validate_all_pallets(self) -> List[ConstraintValidationResult]:
        """Tüm paletlerin hard + soft kısıtlarını post-hoc doğrula."""
        results = []
        for pallet in self.pallets:
            violations = []
            warnings = []

            overflow_l = self._overflow_length
            overflow_w = self._overflow_width
            max_h = self._effective_max_height

            # 1. Boyut kontrolü — her ürün için
            for rect in pallet.layout_data.get("placed_rects", []):
                right_edge = rect["x"] + rect["l"]
                back_edge = rect["z"] + rect["w"]
                top_edge = rect["y"] + rect["h"]

                if right_edge > overflow_l + 0.01:
                    violations.append(
                        f"Ürün sağ kenarı ({right_edge:.1f}cm) > palet limiti "
                        f"({overflow_l:.1f}cm, %{self.params.overflow_tolerance_pct} tolerans dahil)"
                    )
                if back_edge > overflow_w + 0.01:
                    violations.append(
                        f"Ürün arka kenarı ({back_edge:.1f}cm) > palet limiti "
                        f"({overflow_w:.1f}cm, %{self.params.overflow_tolerance_pct} tolerans dahil)"
                    )
                if top_edge > max_h + 0.01:
                    violations.append(
                        f"Yükseklik ({top_edge:.1f}cm) > max ({max_h:.1f}cm) — "
                        f"araç iç yükseklik veya palet limiti aşıldı"
                    )

            # 2. Ağırlık kontrolü
            if pallet.total_weight_kg > self.config.max_weight_kg:
                violations.append(
                    f"Toplam ağırlık ({pallet.total_weight_kg:.1f}kg) > "
                    f"max ({self.config.max_weight_kg}kg)"
                )

            # 3. Ağırlık hiyerarşisi — ağır alta, hafif üste (soft)
            products_with_pos = [
                (p, p.pos_y) for p in pallet.products if p.pos_y is not None
            ]
            for i, (p1, y1) in enumerate(products_with_pos):
                for p2, y2 in products_with_pos[i + 1:]:
                    if y1 < y2:
                        if p2.weight_kg > p1.weight_kg * 1.5:
                            warnings.append(
                                f"Ağırlık uyarısı: '{p2.name}' ({p2.weight_kg}kg) "
                                f"'{p1.name}' ({p1.weight_kg}kg) üzerinde"
                            )

            # 4. NO_STACK kontrolü — üzerine yük konulmuş mu? (hard)
            for p in pallet.products:
                p_constraints = set(p.constraints or [])
                if p.constraint:
                    p_constraints.add(p.constraint)
                if ConstraintType.NO_STACK in p_constraints:
                    p_top = p.pos_y + p.height_cm
                    for other in pallet.products:
                        if other is p:
                            continue
                        if other.pos_y >= p_top - 0.01:
                            if (other.pos_x < p.pos_x + p.length_cm and
                                    other.pos_x + other.length_cm > p.pos_x and
                                    other.pos_z < p.pos_z + p.width_cm and
                                    other.pos_z + other.width_cm > p.pos_z):
                                violations.append(
                                    f"NO_STACK ihlali: '{p.name}' üzerine '{other.name}' konulmuş"
                                )

            # 5. Constraint Engine doğrulaması (varsa)
            if self._constraint_engine and pallet.products:
                violations += self._engine_validate_pallet(pallet)

            results.append(ConstraintValidationResult(
                pallet_number=pallet.pallet_number,
                passed=len(violations) == 0,
                violations=violations,
                warnings=warnings,
            ))
        return results

    def _engine_validate_pallet(self, pallet: OptimizedPallet) -> List[str]:
        violations = []
        placed_so_far = []
        for p in pallet.products:
            p_pcs = self._product_constraints_from_packed(p)
            decision = self._constraint_engine.can_place_on_pallet(
                item_name=p.name,
                item_constraints=p_pcs,
                pallet_items=placed_so_far,
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
    """
    Karma palet optimizasyonu — her palet için en uygun tipi seçer.
    Strateji: baseline (varsayılan tip) → her paleti tüm tiplere karşı dene.
    """

    ALGORITHM_VERSION = "mixed-scored-v3.0"

    def __init__(self, pallet_configs: List[PalletConfig], default_type: PalletConfig = None,
                 params: Optional[OptimizationParams] = None, constraint_engine=None):
        self.configs = pallet_configs
        self.default = default_type or pallet_configs[0]
        self.params = params or OptimizationParams()
        self._constraint_engine = constraint_engine

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        import time
        start = time.time()

        input_summary: Dict[str, int] = {}
        for p in products:
            input_summary[p.name] = input_summary.get(p.name, 0) + p.quantity

        base_optimizer = BinPackingOptimizer3D(
            self.default, params=self.params, constraint_engine=self._constraint_engine
        )
        base_result = base_optimizer.optimize(products)

        improved_pallets: List[OptimizedPallet] = []
        iterations_left = self.params.max_iterations

        for pallet in base_result.pallets:
            best_pallet = pallet
            best_fill = pallet.fill_rate_pct

            pallet_items = []
            for p in pallet.products:
                pallet_items.append(ProductItem(
                    name=p.name, quantity=p.quantity,
                    length_cm=p.length_cm, width_cm=p.width_cm,
                    height_cm=p.height_cm, weight_kg=p.weight_kg,
                    constraint=p.constraint,
                    constraints=list(p.constraints) if p.constraints else [],
                ))

            for cfg in self.configs:
                if cfg.type == self.default.type:
                    continue
                if iterations_left <= 0:
                    break
                iterations_left -= 1

                test_opt = BinPackingOptimizer3D(
                    cfg, params=self.params, constraint_engine=self._constraint_engine
                )
                test_result = test_opt.optimize(pallet_items)

                if (len(test_result.pallets) == 1
                        and len(test_result.rejected_items) == 0
                        and test_result.quantity_audit.get('balanced', False)
                        and test_result.avg_fill_rate_pct > best_fill
                        and test_result.constraints_satisfied):
                    best_fill = test_result.avg_fill_rate_pct
                    candidate = test_result.pallets[0]
                    candidate.pallet_number = pallet.pallet_number
                    best_pallet = candidate

            improved_pallets.append(best_pallet)

        all_rejected = list(base_result.rejected_items)
        all_warnings = list(base_result.warnings)

        duration_ms = int((time.time() - start) * 1000)
        total_weight = sum(p.total_weight_kg for p in improved_pallets)
        total_volume = sum(p.total_volume_m3 for p in improved_pallets)
        avg_fill = (
            sum(p.fill_rate_pct for p in improved_pallets) / len(improved_pallets)
            if improved_pallets else 0
        )
        total_items = sum(
            sum(prod.quantity for prod in p.products) for p in improved_pallets
        )

        # Palet tipi dağılım özeti
        from collections import defaultdict
        groups: Dict[str, List[OptimizedPallet]] = defaultdict(list)
        for p in improved_pallets:
            groups[p.pallet_type].append(p)

        type_breakdown = []
        for ptype, pallets in sorted(groups.items()):
            tw = sum(p.total_weight_kg for p in pallets)
            tv = sum(p.total_volume_m3 for p in pallets)
            af = sum(p.fill_rate_pct for p in pallets) / len(pallets) if pallets else 0
            type_breakdown.append(PalletTypeSummary(
                pallet_type=ptype,
                count=len(pallets),
                total_weight_kg=round(tw, 2),
                total_volume_m3=round(tv, 4),
                avg_fill_rate_pct=round(af, 1),
            ))

        # Post-optimization validation (KURAL-2)
        validator = BinPackingOptimizer3D(
            self.default, params=self.params, constraint_engine=self._constraint_engine
        )
        validator.pallets = improved_pallets
        validations = validator._validate_all_pallets()
        all_passed = all(v.passed for v in validations)
        if not all_passed:
            failed_count = sum(1 for v in validations if not v.passed)
            all_warnings.append(
                f"⛔ {failed_count} palette kısıt ihlali tespit edildi"
            )

        # Miktar denetim raporu
        placed_counts: Dict[str, int] = {}
        for pallet in improved_pallets:
            for p in pallet.products:
                placed_counts[p.name] = placed_counts.get(p.name, 0) + p.quantity
        rejected_counts: Dict[str, int] = {}
        for r in all_rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1
        total_input_count = sum(input_summary.values())
        total_placed_count = sum(placed_counts.values())
        total_rejected_count = sum(rejected_counts.values())
        is_balanced = total_input_count == total_placed_count + total_rejected_count

        if not is_balanced:
            all_warnings.append(
                f"⛔ MİKTAR UYUMSUZLUĞU: girdi={total_input_count}, "
                f"yerleştirilen={total_placed_count}, reddedilen={total_rejected_count}"
            )

        quantity_audit = {
            "input": input_summary,
            "placed": placed_counts,
            "rejected": rejected_counts,
            "total_input": total_input_count,
            "total_placed": total_placed_count,
            "total_rejected": total_rejected_count,
            "balanced": is_balanced,
        }

        return OptimizationResult(
            pallets=improved_pallets,
            total_pallets=len(improved_pallets),
            total_weight_kg=total_weight,
            total_volume_m3=total_volume,
            avg_fill_rate_pct=avg_fill,
            items_per_pallet=total_items / len(improved_pallets) if improved_pallets else 0,
            duration_ms=duration_ms,
            rejected_items=all_rejected,
            warnings=all_warnings,
            algorithm_version=self.ALGORITHM_VERSION,
            pallet_type_breakdown=type_breakdown,
            constraint_validations=validations,
            constraints_satisfied=all_passed,
            quantity_audit=quantity_audit,
        )


# ============================================================
# Senaryo Optimizasyonu
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

    @property
    def total_cost(self) -> float:
        return (
            self.base_cost +
            self.fuel_per_km * self.distance_km +
            self.driver_per_hour * self.duration_hours +
            self.opportunity_cost
        )

    @property
    def volume_m3(self) -> float:
        return (self.length_cm * self.width_cm * self.height_cm) / 1_000_000

    @classmethod
    def from_dict(cls, d: dict, distance_km: float = 200, duration_hours: float = 4) -> "VehicleConfig":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d["name"],
            type=d.get("type", "custom"),
            length_cm=d["length_cm"],
            width_cm=d["width_cm"],
            height_cm=d["height_cm"],
            max_weight_kg=d["max_weight_kg"],
            pallet_capacity=d.get("pallet_capacity", 0),
            base_cost=d.get("base_cost", 0),
            fuel_per_km=d.get("fuel_per_km", 0),
            driver_per_hour=d.get("driver_per_hour", 0),
            opportunity_cost=d.get("opportunity_cost", 0),
            distance_km=distance_km,
            duration_hours=duration_hours,
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
    3 farklı araç atama senaryosu üretir ve karşılaştırır.
    Karışık araç tipi desteği: 1 TIR + 1 panelvan sonucu üretilebilir.
    60/40 ağırlık dağılımı zorunlu kural olarak uygulanır.
    """

    def __init__(
        self,
        pallets: List[OptimizedPallet],
        vehicles: List[VehicleConfig],
        params: Optional[OptimizationParams] = None,
    ):
        self.pallets = pallets
        self.params = params or OptimizationParams()
        self.vehicle_templates = sorted(vehicles, key=lambda v: v.total_cost)

    def generate_all(self) -> List[ScenarioResult]:
        scenarios = [
            self._min_vehicles(),
            self._balanced(),
            self._max_efficiency(),
        ]
        best = min(scenarios, key=lambda s: s.cost_per_pallet)
        best.is_recommended = True
        return scenarios

    def _min_vehicles(self) -> ScenarioResult:
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        templates_by_capacity = sorted(
            self.vehicle_templates, key=lambda v: -v.max_weight_kg
        )
        assignments: List[VehicleAssignment] = []

        for pallet in sorted_pallets:
            placed = False
            pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
            for assignment in assignments:
                v = assignment.vehicle
                if (assignment.current_weight_kg + pallet.total_weight_kg <= v.max_weight_kg and
                        assignment.current_volume_m3 + pallet.total_volume_m3 <= v.volume_m3 and
                        pallet_physical_h <= v.height_cm):
                    assignment.pallet_ids.append(pallet.pallet_number)
                    assignment.current_weight_kg += pallet.total_weight_kg
                    assignment.current_volume_m3 += pallet.total_volume_m3
                    placed = True
                    break

            if not placed:
                best = self._pick_best_new_vehicle(pallet, templates_by_capacity)
                if best:
                    assignments.append(VehicleAssignment(
                        vehicle=best,
                        pallet_ids=[pallet.pallet_number],
                        current_weight_kg=pallet.total_weight_kg,
                        current_volume_m3=pallet.total_volume_m3,
                        cost=best.total_cost,
                    ))

        return self._build_scenario("Minimum Araç", ScenarioStrategy.MIN_VEHICLES, assignments)

    def _balanced(self) -> ScenarioResult:
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        templates_by_cost = sorted(self.vehicle_templates, key=lambda v: v.total_cost)
        assignments: List[VehicleAssignment] = []

        for pallet in sorted_pallets:
            placed = False
            pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
            for assignment in assignments:
                v = assignment.vehicle
                if (assignment.current_weight_kg + pallet.total_weight_kg <= v.max_weight_kg and
                        assignment.current_volume_m3 + pallet.total_volume_m3 <= v.volume_m3 and
                        pallet_physical_h <= v.height_cm):
                    assignment.pallet_ids.append(pallet.pallet_number)
                    assignment.current_weight_kg += pallet.total_weight_kg
                    assignment.current_volume_m3 += pallet.total_volume_m3
                    placed = True
                    break

            if not placed:
                best = self._pick_best_new_vehicle(pallet, templates_by_cost)
                if best:
                    assignments.append(VehicleAssignment(
                        vehicle=best,
                        pallet_ids=[pallet.pallet_number],
                        current_weight_kg=pallet.total_weight_kg,
                        current_volume_m3=pallet.total_volume_m3,
                        cost=best.total_cost,
                    ))

        return self._build_scenario("Dengeli", ScenarioStrategy.BALANCED, assignments)

    def _max_efficiency(self) -> ScenarioResult:
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        assignments: List[VehicleAssignment] = []

        for vt in self.vehicle_templates:
            assignments.append(VehicleAssignment(
                vehicle=vt,
                pallet_ids=[],
                current_weight_kg=0,
                current_volume_m3=0,
                cost=vt.total_cost,
            ))

        for pallet in sorted_pallets:
            pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
            best_idx = -1
            best_fill = float('inf')
            for i, a in enumerate(assignments):
                v = a.vehicle
                if (a.current_weight_kg + pallet.total_weight_kg <= v.max_weight_kg and
                        a.current_volume_m3 + pallet.total_volume_m3 <= v.volume_m3 and
                        pallet_physical_h <= v.height_cm):
                    fill_ratio = a.current_weight_kg / v.max_weight_kg
                    if fill_ratio < best_fill:
                        best_fill = fill_ratio
                        best_idx = i
            if best_idx >= 0:
                a = assignments[best_idx]
                a.pallet_ids.append(pallet.pallet_number)
                a.current_weight_kg += pallet.total_weight_kg
                a.current_volume_m3 += pallet.total_volume_m3

        assignments = [a for a in assignments if a.pallet_ids]
        return self._build_scenario("Maksimum Verim", ScenarioStrategy.MAX_EFFICIENCY, assignments)

    def _pick_best_new_vehicle(
        self,
        pallet: OptimizedPallet,
        templates: List[VehicleConfig],
    ) -> Optional[VehicleConfig]:
        pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
        for vt in templates:
            if (vt.max_weight_kg >= pallet.total_weight_kg and
                    pallet_physical_h <= vt.height_cm):
                return VehicleConfig(
                    id=str(uuid.uuid4()),
                    name=vt.name, type=vt.type,
                    length_cm=vt.length_cm, width_cm=vt.width_cm,
                    height_cm=vt.height_cm, max_weight_kg=vt.max_weight_kg,
                    pallet_capacity=vt.pallet_capacity,
                    base_cost=vt.base_cost, fuel_per_km=vt.fuel_per_km,
                    driver_per_hour=vt.driver_per_hour,
                    opportunity_cost=vt.opportunity_cost,
                    distance_km=vt.distance_km, duration_hours=vt.duration_hours,
                )
        if templates:
            biggest = max(templates, key=lambda v: v.max_weight_kg)
            return VehicleConfig(
                id=str(uuid.uuid4()),
                name=biggest.name, type=biggest.type,
                length_cm=biggest.length_cm, width_cm=biggest.width_cm,
                height_cm=biggest.height_cm, max_weight_kg=biggest.max_weight_kg,
                pallet_capacity=biggest.pallet_capacity,
                base_cost=biggest.base_cost, fuel_per_km=biggest.fuel_per_km,
                driver_per_hour=biggest.driver_per_hour,
                opportunity_cost=biggest.opportunity_cost,
                distance_km=biggest.distance_km, duration_hours=biggest.duration_hours,
            )
        return None

    def _build_scenario(
        self, name: str, strategy: ScenarioStrategy,
        assignments: List[VehicleAssignment],
    ) -> ScenarioResult:
        self._apply_weight_balance(assignments)
        total_cost = sum(a.cost for a in assignments)
        total_pallets = sum(len(a.pallet_ids) for a in assignments)

        fill_rates = []
        for a in assignments:
            vehicle_vol = a.vehicle.volume_m3
            if vehicle_vol > 0:
                fill_rates.append(min(100, a.current_volume_m3 / vehicle_vol * 100))
            elif a.vehicle.max_weight_kg > 0:
                fill_rates.append(min(100, a.current_weight_kg / a.vehicle.max_weight_kg * 100))
        avg_fill = sum(fill_rates) / len(fill_rates) if fill_rates else 0

        balance_vals = [a.front_pct for a in assignments if a.front_pct > 0]
        avg_balance = sum(balance_vals) / len(balance_vals) if balance_vals else 0

        return ScenarioResult(
            name=name,
            strategy=strategy,
            vehicles=assignments,
            total_cost=total_cost,
            cost_per_pallet=total_cost / max(1, total_pallets),
            total_vehicles=len(assignments),
            avg_fill_rate_pct=min(avg_fill, 100),
            avg_balance_pct=round(avg_balance, 1),
        )

    def _apply_weight_balance(self, assignments: List[VehicleAssignment]):
        target = self.params.weight_balance_target
        tolerance = self.params.weight_balance_tolerance
        pallet_map = {p.pallet_number: p for p in self.pallets}

        for assignment in assignments:
            if not assignment.pallet_ids:
                continue

            sorted_ids = sorted(
                assignment.pallet_ids,
                key=lambda pid: pallet_map[pid].total_weight_kg if pid in pallet_map else 0,
                reverse=True,
            )

            total_w = assignment.current_weight_kg
            if total_w <= 0:
                assignment.pallet_ids = sorted_ids
                continue

            target_front_w = total_w * target
            front_ids = []
            rear_ids = []
            running_front_w = 0.0

            for pid in sorted_ids:
                pw = pallet_map[pid].total_weight_kg if pid in pallet_map else 0
                if running_front_w < target_front_w and len(front_ids) < len(sorted_ids):
                    front_ids.append(pid)
                    running_front_w += pw
                else:
                    rear_ids.append(pid)

            assignment.pallet_ids = front_ids + rear_ids
            front_w = sum(pallet_map[pid].total_weight_kg for pid in front_ids if pid in pallet_map)
            rear_w = sum(pallet_map[pid].total_weight_kg for pid in rear_ids if pid in pallet_map)

            assignment.front_weight_kg = round(front_w, 2)
            assignment.rear_weight_kg = round(rear_w, 2)
            assignment.front_pct = round((front_w / total_w) * 100, 1) if total_w else 0
            assignment.balance_ok = abs(front_w / total_w - target) <= tolerance if total_w else True
