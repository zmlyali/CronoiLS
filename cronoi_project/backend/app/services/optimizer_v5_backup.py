"""
Cronoi LS — 3D Bin Packing Optimizer v5.0
Skyline (Bottom-Left-Back) tabanlı gerçek 3D bin packing — 3 katmanlı kural motoru

Katman 1 — HARD CONSTRAINTS (Kırılamaz)
  - Palet max boyut (L×W×H) kesinlikle aşılamaz
  - Palet max ağırlık aşılamaz
  - Ürün palete sığmıyorsa reddedilir (force_place yok)
  - Ağırlık hiyerarşisi: ağır alta, hafif üste
  - NO_STACK ürünler üste yük alamaz

Katman 2 — SOFT CONSTRAINTS (Tercihler)
  - Kırılgan/ağır ürünler aynı palette olmamalı
  - Sıcaklık hassas ürünler izole
  - Yönelim kısıtları (HORIZONTAL_ONLY, VERTICAL_ONLY)

Katman 3 — OPTIMIZATION OBJECTIVES
  - Minimum palet sayısı
  - Maksimum doluluk
  - Denge (ağırlık dağılımı)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Set
from enum import Enum
import math
import uuid
import logging

logger = logging.getLogger(__name__)

# Standart EUR palet tahtası yüksekliği (cm)
PALLET_BOARD_HEIGHT_CM = 15

# Kenarladan taşma toleransı — %5 kabul edilebilir
DEFAULT_OVERFLOW_TOLERANCE_PCT = 5.0


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


@dataclass
class OptimizationParams:
    """Parametrik optimizasyon ayarları — Settings UI'dan gelir, hard-code yok."""
    height_safety_margin_cm: float = 0     # Palet max yüksekliğinden bu kadar cm düşür
    pallet_gap_cm: float = 3               # Araçta paletler arası boşluk
    enforce_constraints: bool = True        # Kısıt kurallarını uygula
    weight_balance_target: float = 0.60    # Ön aks yük hedefi (0.55–0.65 arası ideal)
    weight_balance_tolerance: float = 0.10 # Sapma toleransı (%10)
    max_iterations: int = 12               # Araç/palet tipi değerlendirme limiti
    optimality_target: float = 90.0        # Doluluk hedefi (%)
    overflow_tolerance_pct: float = 5.0    # Kenardan taşma toleransı (%)
    vehicle_max_height_cm: float = 0       # Araç iç yüksekliği limiti (0=sınırsız, palet kendi limiti geçerli)

    @classmethod
    def from_dict(cls, d: dict) -> "OptimizationParams":
        if not d:
            return cls()
        # Frontend gönderir: weightBalanceFrontPct=60 (%), backend fraction kullanır 0.60
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
        """Tüm kısıtları birleştirilmiş set olarak döndür"""
        s = set(self.constraints)
        if self.constraint:
            s.add(self.constraint)
        return s

    @property
    def volume_cm3(self) -> float:
        return self.length_cm * self.width_cm * self.height_cm

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
        """Katman önceliği: düşük = alta. Ağırlık hiyerarşisi kullanır."""
        c = self.all_constraints
        best = 2  # neutral default
        for ct in c:
            prio = WEIGHT_HIERARCHY.get(ct, 2)
            best = min(best, prio)
        return best


@dataclass
class PalletConfig:
    type: str
    width_cm: float
    length_cm: float
    max_height_cm: float
    max_weight_kg: float

    @classmethod
    def euro(cls) -> "PalletConfig":
        return cls("P1", 80, 120, 250, 700)

    @classmethod
    def standard(cls) -> "PalletConfig":
        return cls("P5", 100, 120, 250, 700)

    @classmethod
    def tir(cls) -> "PalletConfig":
        return cls("P10", 120, 200, 250, 700)

    @classmethod
    def from_dict(cls, d: dict) -> "PalletConfig":
        return cls(
            type=d.get("code", "custom"),
            width_cm=d["width_cm"],
            length_cm=d["length_cm"],
            max_height_cm=d.get("max_height_cm", 180),
            max_weight_kg=d["max_weight_kg"],
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
    """Palete sığmayan ürün — kullanıcıya bildirilir"""
    name: str
    reason: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float


@dataclass
class ConstraintValidationResult:
    """Optimizasyon sonrası kısıt doğrulama sonucu"""
    pallet_number: int
    passed: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PalletTypeSummary:
    """Palet tipi dağılım özeti — '5 euro palet, 10 standart palet' gibi"""
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
    algorithm_version: str = "skyline-blb-v5.0"
    pallet_type_breakdown: List[PalletTypeSummary] = field(default_factory=list)
    constraint_validations: List[ConstraintValidationResult] = field(default_factory=list)
    constraints_satisfied: bool = True
    quantity_audit: Dict[str, Any] = field(default_factory=dict)  # Miktar denetim raporu


class BinPackingOptimizer3D:
    """
    Skyline (Bottom-Left-Back) 3D Bin Packing — 3 katmanlı kural motoru ile.

    Algoritma:
    1. Ürünleri expand et (quantity → ayrı item)
    2. Constraint-aware sıralama:
       - MUST_BOTTOM/HEAVY → ilk (alta yerleşir)
       - Neutral → orta
       - FRAGILE/NO_STACK/MUST_TOP → son (üste yerleşir)
       - Aynı grup içinde: büyük hacim → küçük hacim (FFD)
    3. Skyline yerleştirme (shelf-layer yerine):
       - 2D heightmap — yerleştirilmiş ürünlerin üst yüzey haritası
       - Her ürün için tüm geçerli pozisyonlardan en düşük Y noktasını bul
       - Bottom-Left-Back: minimum Y → minimum X → minimum Z
       - Boşluklar doldurulur (shelf-layer'ın israf ettiği alanlar kullanılır)
    4. Kesin kontroller:
       - Ürün > palet boyutu → REDDEDILIR (force_place yok)
       - Ağırlık > max → yeni palet
       - Yükseklik > max → yeni palet
       - Kısıt uyumsuzluğu → yeni palet
    """

    ALGORITHM_VERSION = "skyline-blb-v5.0"

    def __init__(self, pallet_config: PalletConfig, params: Optional[OptimizationParams] = None,
                 constraint_engine=None):
        self.config = pallet_config
        self.params = params or OptimizationParams()
        self.pallets: List[OptimizedPallet] = []
        self.rejected: List[RejectedItem] = []
        self.warnings: List[str] = []
        self._constraint_engine = constraint_engine  # ConstraintEngine entegrasyonu
        self._input_summary: Dict[str, int] = {}  # {ürün_adı: toplam_miktar} — audit

    @property
    def _effective_max_height(self) -> float:
        """Efektif palet yüksekliği:
        min(palet_max_h, araç_iç_yükseklik - tahta) - güvenlik_payı

        Araç limiti gönderilmişse palet kendi limitinden düşükse onu kullan.
        Böylece panelvan (180cm iç) için palet yüksekliği 165cm'e düşer.
        """
        base = self.config.max_height_cm
        if self.params.vehicle_max_height_cm > 0:
            # Araç iç yüksekliği - palet tahtası yüksekliği = kargo için kullanılabilir
            vehicle_cargo_h = self.params.vehicle_max_height_cm - PALLET_BOARD_HEIGHT_CM
            base = min(base, vehicle_cargo_h)
        return base - self.params.height_safety_margin_cm

    @property
    def _overflow_length(self) -> float:
        """Palet uzunluğu + %overflow tolerans"""
        return self.config.length_cm * (1 + self.params.overflow_tolerance_pct / 100.0)

    @property
    def _overflow_width(self) -> float:
        """Palet genişliği + %overflow tolerans"""
        return self.config.width_cm * (1 + self.params.overflow_tolerance_pct / 100.0)

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        import time
        start = time.time()

        # ── Girdi miktarlarını kaydet (audit) ──
        self._input_summary = {}
        for p in products:
            self._input_summary[p.name] = self._input_summary.get(p.name, 0) + p.quantity

        items = self._expand_items(products)
        sorted_items = self._constraint_aware_sort(items)
        self._pack(sorted_items)

        # ── Miktar doğrulaması — girdi == çıktı kontrolü ──
        self._verify_quantities()

        duration_ms = int((time.time() - start) * 1000)
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
                ))
        return items

    def _constraint_aware_sort(self, items: List[ProductItem]) -> List[ProductItem]:
        def sort_key(item: ProductItem):
            return (
                item.layer_priority,
                -item.weight_kg,
                -item.volume_cm3,
            )
        return sorted(items, key=sort_key)

    def _get_valid_orientations(self, item: ProductItem) -> List[Tuple[float, float, float, bool]]:
        """Palete sığan tüm 3D orientasyonları döndür (l, w, h, rotated).

        rotation_allowed=True  → 6 permütasyon (tam 3D)
        rotation_allowed=False → yalnızca orijinal oryantasyon
        Sıralama: en düşük yükseklik önce (istiflemeyi maksimize eder).
        Kenar taşma toleransı (%overflow_tolerance_pct) uygulanır — yüksekliğe değil.
        """
        from itertools import permutations as perms

        L, W, H = item.length_cm, item.width_cm, item.height_cm
        pL, pW = self._overflow_length, self._overflow_width  # toleranslı sınırlar
        pH = self._effective_max_height  # yükseklik toleranssız

        candidates = set(perms([L, W, H])) if item.rotation_allowed else {(L, W, H)}

        valid = []
        for l, w, h in candidates:
            if l <= pL and w <= pW and h <= pH:
                rotated = not (l == L and w == W and h == H)
                valid.append((l, w, h, rotated))

        # En düşük yükseklik → daha iyi istifleme
        # Eşit yükseklikte: daha kısa max(l,w) → yan yana sığma şansı daha yüksek
        valid.sort(key=lambda o: (o[2], max(o[0], o[1]), o[0] * o[1]))
        return valid

    def _item_fits_pallet(self, item: ProductItem) -> bool:
        if item.weight_kg > self.config.max_weight_kg:
            return False
        return len(self._get_valid_orientations(item)) > 0

    def _orient_item(self, item: ProductItem) -> Tuple[float, float, float, bool]:
        orientations = self._get_valid_orientations(item)
        if orientations:
            return orientations[0]
        return item.length_cm, item.width_cm, item.height_cm, False

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
            if self._try_place_skyline(pallet, item):
                return

        new_pallet = OptimizedPallet(
            pallet_number=len(self.pallets) + 1,
            pallet_type=self.config.type,
        )
        new_pallet.layout_data = {"placed_rects": []}
        if self._try_place_skyline(new_pallet, item):
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
            return f"Tek parça ağırlık ({item.weight_kg}kg) palet kapasitesini ({self.config.max_weight_kg}kg) aşıyor"
        if not self._get_valid_orientations(item):
            pL, pW = self.config.length_cm, self.config.width_cm
            return (
                f"Hiçbir 3D orientasyonda ({item.length_cm}×{item.width_cm}×{item.height_cm}cm) "
                f"palet alanına ({pL}×{pW}×{pH}cm) sığmıyor"
            )
        return "Palet boyut limitleri aşıldı"

    # ── SKYLINE CORE ──

    def _try_place_skyline(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """Ürünü palete skyline BLB ile yerleştirmeyi dene.

        Tüm geçerli 3D orientasyonları dener ve en düşük y pozisyonunu
        tercih eder — böylece yan yana yerleştirme (floor-level) üst üste
        yığmadan önce denenir.  Aynı y'de ise BLB sıralaması (x, z) kullanılır.
        """

        # ── HARD CONSTRAINTS — Boyut & Ağırlık ──
        if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
            return False
        if not self._item_fits_pallet(item):
            return False

        # ── HARD CONSTRAINTS — Constraint Engine ──
        if self.params.enforce_constraints:
            if self._constraint_engine:
                if not self._engine_allows_placement(pallet, item):
                    return False
            elif not self._constraints_compatible(pallet, item):
                return False

        placed = pallet.layout_data.get("placed_rects", [])
        pL = self.config.length_cm
        pW = self.config.width_cm
        pH = self._effective_max_height

        # Tüm geçerli 3D orientasyonları dene — en düşük y pozisyonunu bul
        # Bu sayede yan yana (floor-level) yerleştirme üst üste yığmadan önce tercih edilir
        best = None  # (y, x, z, pl, pw, ph, rotated)
        for pl, pw, ph, rotated in self._get_valid_orientations(item):
            pos = self._skyline_find_position(placed, pl, pw, ph, pL, pW, pH)
            if pos is not None:
                x, z, y = pos
                candidate = (y, x, z, pl, pw, ph, rotated)
                if best is None or (y, x, z) < (best[0], best[1], best[2]):
                    best = candidate
                    if y < 0.01:
                        break  # Zemin seviyesi — daha iyisi yok

        if best is not None:
            y, x, z, pl, pw, ph, rotated = best
            self._commit_place(pallet, item, x, y, z, pl, pw, ph, rotated)
            return True

        return False

    def _engine_allows_placement(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """ConstraintEngine üzerinden tam kısıt değerlendirmesi yap."""
        from app.services.constraint_engine import ProductConstraint

        # Ürünün kısıtlarını ProductConstraint formatına çevir
        item_pcs = self._to_product_constraints(item)

        # Paletteki mevcut ürünlerin kısıtlarını topla
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

        # Uyarıları kaydet ama yerleştirmeye izin ver
        for w in decision.warnings:
            self.warnings.append(f"⚠️ Kısıt uyarısı: {w.message}")

        return True

    def _to_product_constraints(self, item: ProductItem) -> list:
        """ProductItem → List[ProductConstraint] dönüşümü (engine entegrasyonu)"""
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
        """PackedItem → List[ProductConstraint] dönüşümü"""
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

    def _skyline_find_position(
        self, placed: List[Dict], pl: float, pw: float, ph: float,
        pL: float, pW: float, pH: float
    ) -> Optional[Tuple[float, float, float]]:
        """
        Skyline Bottom-Left-Back: en düşük Y noktasını bul.
        Aday pozisyonlar: yerleştirilmiş ürün kenarları + (0,0).
        Kenar taşma toleransı uygulanır (pL/pW overflow dahil gelir).
        Returns: (x, z, y) veya None.
        """
        # Toleranslı sınırlar
        effL = self._overflow_length
        effW = self._overflow_width

        # Aday x ve z pozisyonları oluştur (sağ kenar + alt kenar)
        xs = sorted({0.0} | {r["x"] + r["l"] for r in placed})
        zs = sorted({0.0} | {r["z"] + r["w"] for r in placed})

        best: Optional[Tuple[float, float, float]] = None  # (y, x, z)

        for x in xs:
            if x + pl > effL + 0.01:
                continue
            for z in zs:
                if z + pw > effW + 0.01:
                    continue
                y = self._support_height(placed, x, z, pl, pw)
                if y + ph > pH + 0.01:
                    continue
                candidate = (y, x, z)
                if best is None or candidate < best:
                    best = candidate
                    if y < 0.01:
                        # Zemin seviyesi — daha iyi olamaz, erken çık
                        return (x, z, 0.0)

        if best is not None:
            return (best[1], best[2], best[0])
        return None

    def _support_height(self, placed: List[Dict], x: float, z: float, pl: float, pw: float) -> float:
        """Verilen footprint alanında en yüksek noktayı bul."""
        max_h = 0.0
        x2, z2 = x + pl, z + pw
        for r in placed:
            # XZ düzleminde çakışma kontrolü
            if r["x"] < x2 and r["x"] + r["l"] > x and r["z"] < z2 and r["z"] + r["w"] > z:
                top = r["y"] + r["h"]
                if top > max_h:
                    max_h = top
        return max_h

    def _commit_place(
        self, pallet: OptimizedPallet, item: ProductItem,
        x: float, y: float, z: float,
        pl: float, pw: float, ph: float,
        rotated: bool,
    ):
        packed = PackedItem(
            name=item.name, quantity=1,
            length_cm=pl, width_cm=pw, height_cm=ph,
            weight_kg=item.weight_kg,
            constraint=item.constraint,
            constraints=list(item.constraints),
            pos_x=round(x, 2), pos_y=round(y, 2), pos_z=round(z, 2),
            rotated=rotated,
        )
        pallet.products.append(packed)

        # Skyline rect (hızlı lookup için)
        rects = pallet.layout_data.setdefault("placed_rects", [])
        rects.append({"x": x, "z": z, "y": y, "l": pl, "w": pw, "h": ph})

        # Palet istatistiklerini güncelle
        pallet.total_weight_kg += item.weight_kg
        pallet.total_volume_m3 += (pl * pw * ph) / 1_000_000

        pallet_max_vol = self.config.volume_cm3 / 1_000_000
        pallet.fill_rate_pct = round((pallet.total_volume_m3 / pallet_max_vol) * 100, 1) if pallet_max_vol else 0

        for ct in item.all_constraints:
            if ct not in pallet.constraints:
                pallet.constraints.append(ct)

        # Toplam yükseklik = en yüksek ürünün tepesi
        all_tops = [r["y"] + r["h"] for r in rects]
        pallet.total_height_cm = round(max(all_tops) if all_tops else 0, 2)

    def _constraints_compatible(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        if not pallet.products:
            return True

        item_c = item.all_constraints
        pallet_c = set(pallet.constraints)

        # FRAGILE + HEAVY ayrılmalı
        if ConstraintType.FRAGILE in item_c and ConstraintType.HEAVY in pallet_c:
            return False
        if ConstraintType.HEAVY in item_c and ConstraintType.FRAGILE in pallet_c:
            return False
        if ConstraintType.FRAGILE in item_c and ConstraintType.MUST_BOTTOM in pallet_c:
            return False
        if ConstraintType.MUST_BOTTOM in item_c and ConstraintType.FRAGILE in pallet_c:
            return False

        # TEMP izolasyonu
        if ConstraintType.TEMP in item_c:
            return all(
                ConstraintType.TEMP in set(p.constraints or []) or p.constraint == ConstraintType.TEMP
                for p in pallet.products
            )
        if ConstraintType.TEMP in pallet_c:
            return ConstraintType.TEMP in item_c

        return True

    def _verify_quantities(self):
        """Girdi miktarlarının çıktıyla eşleştiğini doğrula.

        Her ürün adı için: paletlerdeki_miktar + reddedilen_miktar == girdi_miktarı
        Uyumsuzluk varsa warning ekler ve eksik ürünleri rejected'a ekler.
        """
        # Paletlerdeki miktarlar
        placed: Dict[str, int] = {}
        for pallet in self.pallets:
            for p in pallet.products:
                placed[p.name] = placed.get(p.name, 0) + p.quantity

        # Reddedilen miktarlar
        rejected_counts: Dict[str, int] = {}
        for r in self.rejected:
            rejected_counts[r.name] = rejected_counts.get(r.name, 0) + 1

        # Denetim
        for name, expected in self._input_summary.items():
            actual = placed.get(name, 0) + rejected_counts.get(name, 0)
            if actual < expected:
                missing = expected - actual
                self.warnings.append(
                    f"⛔ MİKTAR HATASI: '{name}' → sipariş={expected}, "
                    f"yerleştirilen={placed.get(name, 0)}, reddedilen={rejected_counts.get(name, 0)}, "
                    f"KAYIP={missing}"
                )
                # Kayıp ürünleri rejected'a ekle
                for _ in range(missing):
                    self.rejected.append(RejectedItem(
                        name=name,
                        reason=f"Optimizasyon sırasında kayboldu — algoritma hatası",
                        length_cm=0, width_cm=0, height_cm=0, weight_kg=0,
                    ))
            elif actual > expected:
                self.warnings.append(
                    f"⚠️ MİKTAR FAZLASI: '{name}' → sipariş={expected}, çıktı={actual}"
                )

    def _build_result(self, duration_ms: int) -> OptimizationResult:
        total_weight = sum(p.total_weight_kg for p in self.pallets)
        total_volume = sum(p.total_volume_m3 for p in self.pallets)
        avg_fill = (
            round(sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets), 1)
            if self.pallets else 0
        )
        total_items = sum(
            sum(prod.quantity for prod in p.products)
            for p in self.pallets
        )

        # ── Palet tipi dağılım özeti ──
        type_breakdown = self._compute_pallet_type_breakdown()

        # ── Kısıt doğrulaması (post-optimization validation) ──
        validations = self._validate_all_pallets()
        all_passed = all(v.passed for v in validations)
        if not all_passed:
            failed_count = sum(1 for v in validations if not v.passed)
            self.warnings.append(
                f"⛔ {failed_count} palette kısıt ihlali tespit edildi — detaylar constraint_validations'da"
            )

        # ── Miktar denetim raporu ──
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

        quantity_audit = {
            "input": self._input_summary,
            "placed": placed_counts,
            "rejected": rejected_counts,
            "total_input": total_input,
            "total_placed": total_placed,
            "total_rejected": total_rejected,
            "balanced": total_input == total_placed + total_rejected,
        }

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

    def _compute_pallet_type_breakdown(self) -> List[PalletTypeSummary]:
        """Palet tipi bazında dağılım özeti"""
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

    def _validate_all_pallets(self) -> List[ConstraintValidationResult]:
        """Tüm paletlerin kısıtlarını post-hoc doğrula."""
        results = []
        for pallet in self.pallets:
            violations = []
            warnings = []

            # 1. Boyut kontrolü — overflow toleransıyla
            overflow_l = self._overflow_length
            overflow_w = self._overflow_width
            max_h = self._effective_max_height

            for rect in pallet.layout_data.get("placed_rects", []):
                right_edge = rect["x"] + rect["l"]
                back_edge = rect["z"] + rect["w"]
                top_edge = rect["y"] + rect["h"]

                if right_edge > overflow_l + 0.01:
                    violations.append(
                        f"Ürün sağ kenarı ({right_edge:.1f}cm) palet limitini aşıyor "
                        f"(max {overflow_l:.1f}cm, %{self.params.overflow_tolerance_pct} tolerans dahil)"
                    )
                if back_edge > overflow_w + 0.01:
                    violations.append(
                        f"Ürün arka kenarı ({back_edge:.1f}cm) palet limitini aşıyor "
                        f"(max {overflow_w:.1f}cm, %{self.params.overflow_tolerance_pct} tolerans dahil)"
                    )
                if top_edge > max_h + 0.01:
                    violations.append(
                        f"Yükseklik ({top_edge:.1f}cm) palet max yüksekliği aşıyor (max {max_h:.1f}cm)"
                    )

            # 2. Ağırlık kontrolü
            if pallet.total_weight_kg > self.config.max_weight_kg:
                violations.append(
                    f"Toplam ağırlık ({pallet.total_weight_kg:.1f}kg) > "
                    f"max ({self.config.max_weight_kg}kg)"
                )

            # 3. Ağırlık hiyerarşisi kontrolü — ağır alta, hafif üste
            products_with_pos = [
                (p, p.pos_y) for p in pallet.products if p.pos_y is not None
            ]
            for i, (p1, y1) in enumerate(products_with_pos):
                for p2, y2 in products_with_pos[i+1:]:
                    if y1 < y2:  # p1 altta, p2 üstte
                        if p2.weight_kg > p1.weight_kg * 1.5:  # Üstteki çok daha ağır
                            warnings.append(
                                f"Ağırlık uyarısı: '{p2.name}' ({p2.weight_kg}kg) "
                                f"'{p1.name}' ({p1.weight_kg}kg) üzerinde yerleştirilmiş"
                            )

            # 4. NO_STACK kontrolü — üzerine bir şey konulmuş mu?
            for p in pallet.products:
                p_constraints = set(p.constraints or [])
                if p.constraint:
                    p_constraints.add(p.constraint)
                if ConstraintType.NO_STACK in p_constraints:
                    # Bu ürünün üstünde başka ürün var mı?
                    p_top = p.pos_y + p.height_cm
                    for other in pallet.products:
                        if other is p:
                            continue
                        if other.pos_y >= p_top - 0.01:
                            # XZ çakışma kontrolü
                            if (other.pos_x < p.pos_x + p.length_cm and
                                    other.pos_x + other.length_cm > p.pos_x and
                                    other.pos_z < p.pos_z + p.width_cm and
                                    other.pos_z + other.width_cm > p.pos_z):
                                violations.append(
                                    f"NO_STACK ihlali: '{p.name}' üzerine '{other.name}' konulmuş"
                                )

            # 5. Constraint Engine üzerinden doğrulama (varsa)
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
        """ConstraintEngine ile paletin tamamını doğrula"""
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


class MixedBinPackingOptimizer:
    """
    Karma palet optimizasyonu — her palet için en uygun tipi seçer.

    Strateji:
    1. Ürünleri varsayılan palet tipine yerleştir (FFD baseline).
    2. Her oluşan paleti tüm aktif palet tiplerine karşı dene.
    3. Tek palete sığıyorsa ve doluluk daha iyiyse o tipe geç.

    Sonuç: 10 paletin 5'i EUR, 3'ü endüstriyel, 2'si yarım EUR gibi karma dağılım.
    """

    ALGORITHM_VERSION = "mixed-skyline-v2.0"

    def __init__(self, pallet_configs: List[PalletConfig], default_type: PalletConfig = None,
                 params: Optional[OptimizationParams] = None, constraint_engine=None):
        self.configs = pallet_configs
        self.default = default_type or pallet_configs[0]
        self.params = params or OptimizationParams()
        self._constraint_engine = constraint_engine

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        import time
        start = time.time()

        # Girdi miktar kaydı (audit için)
        input_summary: Dict[str, int] = {}
        for p in products:
            input_summary[p.name] = input_summary.get(p.name, 0) + p.quantity

        # Baseline: tüm ürünleri varsayılan tipe yerleştir
        base_optimizer = BinPackingOptimizer3D(
            self.default, params=self.params, constraint_engine=self._constraint_engine
        )
        base_result = base_optimizer.optimize(products)

        # Her paleti en uygun tipe yeniden atamayı dene
        improved_pallets: List[OptimizedPallet] = []
        iterations_left = self.params.max_iterations

        for pallet in base_result.pallets:
            best_pallet = pallet
            best_fill = pallet.fill_rate_pct

            # Paletteki ürünleri tekrar ProductItem'a çevir
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
                # Aynı ürünler tek palete sığıyorsa, HİÇBİR ÜRÜN KAYBOLMAMIŞSA ve doluluk daha iyiyse
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

        # Reddedilen ürünleri ve uyarıları base_result'tan al
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

        # ── Palet tipi dağılım özeti ──
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

        # ── Post-optimization constraint validation ──
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

        # ── Miktar denetim raporu ──
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
        """DB'den gelen VehicleDefinition dict'inden oluştur"""
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
    # 60/40 ağırlık dengesi bilgisi
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
    avg_balance_pct: float = 0.0   # Ortalama ön aks yük oranı


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

        # En iyi senaryo (palet başı en ucuz)
        best = min(scenarios, key=lambda s: s.cost_per_pallet)
        best.is_recommended = True

        return scenarios

    def _min_vehicles(self) -> ScenarioResult:
        """
        Mümkün olan en az araçla tüm paletleri taşı.
        Her araçta en büyük (en çok palet sığan) araçtan başla,
        kalan küçük yükü daha küçük araçlarla tamamla.
        """
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        # Büyükten küçüğe araçlar (max kapasite önce)
        templates_by_capacity = sorted(
            self.vehicle_templates, key=lambda v: -v.max_weight_kg
        )

        assignments: List[VehicleAssignment] = []

        for pallet in sorted_pallets:
            placed = False
            pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
            # Mevcut araca sığıyor mu? (ağırlık + hacim + yükseklik)
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
                # Yeni araç aç — yeterli kapasiteli en ucuz araç
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
        """
        Maliyet ve araç sayısını dengele — küçük araçlarla daha dengeli dağıtım.
        Büyük araçları sadece gerekliyse kullan.
        """
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        # Küçükten büyüğe araçlar
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
                # En ucuz yeterli araç
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
        """
        Tüm araç tiplerinden birer tane açıp round-robin dağıt.
        Kullanılmayan araçları sonra çıkar.
        """
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

        # Round-robin: en az doluluk oranına sahip araca ekle
        for pallet in sorted_pallets:
            pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
            # Sığan araçlardan en boş olana ekle (ağırlık + hacim + yükseklik)
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

        # Boş araçları çıkar
        assignments = [a for a in assignments if a.pallet_ids]

        return self._build_scenario("Maksimum Verim", ScenarioStrategy.MAX_EFFICIENCY, assignments)

    def _pick_best_new_vehicle(
        self,
        pallet: OptimizedPallet,
        templates: List[VehicleConfig],
    ) -> Optional[VehicleConfig]:
        """
        Paleti alabilecek en uygun (en ucuz) araç şablonundan yeni kopya oluştur.
        Kontrol kriterleri (hepsi sağlanmalı):
          1. Ağırlık : vt.max_weight_kg >= pallet.total_weight_kg
          2. Yükseklik: pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM <= vt.height_cm
        """
        pallet_physical_h = pallet.total_height_cm + PALLET_BOARD_HEIGHT_CM
        for vt in templates:
            if (vt.max_weight_kg >= pallet.total_weight_kg and
                    pallet_physical_h <= vt.height_cm):
                # Yeni kopya (aynı araç tipi birden fazla kullanılabilir)
                return VehicleConfig(
                    id=str(uuid.uuid4()),
                    name=vt.name,
                    type=vt.type,
                    length_cm=vt.length_cm,
                    width_cm=vt.width_cm,
                    height_cm=vt.height_cm,
                    max_weight_kg=vt.max_weight_kg,
                    pallet_capacity=vt.pallet_capacity,
                    base_cost=vt.base_cost,
                    fuel_per_km=vt.fuel_per_km,
                    driver_per_hour=vt.driver_per_hour,
                    opportunity_cost=vt.opportunity_cost,
                    distance_km=vt.distance_km,
                    duration_hours=vt.duration_hours,
                )
        # Hiçbiri yetmediyse en büyüğünden bi tane aç
        if templates:
            biggest = max(templates, key=lambda v: v.max_weight_kg)
            return VehicleConfig(
                id=str(uuid.uuid4()),
                name=biggest.name,
                type=biggest.type,
                length_cm=biggest.length_cm,
                width_cm=biggest.width_cm,
                height_cm=biggest.height_cm,
                max_weight_kg=biggest.max_weight_kg,
                pallet_capacity=biggest.pallet_capacity,
                base_cost=biggest.base_cost,
                fuel_per_km=biggest.fuel_per_km,
                driver_per_hour=biggest.driver_per_hour,
                opportunity_cost=biggest.opportunity_cost,
                distance_km=biggest.distance_km,
                duration_hours=biggest.duration_hours,
            )
        return None

    def _build_scenario(
        self,
        name: str,
        strategy: ScenarioStrategy,
        assignments: List[VehicleAssignment]
    ) -> ScenarioResult:
        # 60/40 ağırlık dengesi hesapla ve paletleri sırala
        self._apply_weight_balance(assignments)

        total_cost = sum(a.cost for a in assignments)
        total_pallets = sum(len(a.pallet_ids) for a in assignments)

        # Gerçek doluluk hesabı (hacim bazlı — LxWxH)
        fill_rates = []
        for a in assignments:
            vehicle_vol = a.vehicle.volume_m3
            if vehicle_vol > 0:
                fill_rates.append(min(100, a.current_volume_m3 / vehicle_vol * 100))
            elif a.vehicle.max_weight_kg > 0:
                # Fallback: ağırlık bazlı
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
        """
        60/40 ağırlık dağılımı: paletleri ön→arka sırasına göre düzenle.
        TIR ön aksı toplam ağırlığın %55–65'ini taşımalıdır.
        Paletler ağırlığa göre sıralanır ve ön aksa weight target'a ulaşana kadar eklenir.
        """
        target = self.params.weight_balance_target
        tolerance = self.params.weight_balance_tolerance
        pallet_map = {p.pallet_number: p for p in self.pallets}

        for assignment in assignments:
            if not assignment.pallet_ids:
                continue

            # Paletleri ağırlıklarına göre sırala: ağır → öne
            sorted_ids = sorted(
                assignment.pallet_ids,
                key=lambda pid: pallet_map[pid].total_weight_kg if pid in pallet_map else 0,
                reverse=True,
            )

            total_w = assignment.current_weight_kg
            if total_w <= 0:
                assignment.pallet_ids = sorted_ids
                continue

            # Ağırlık bazlı bölme: ağır paletleri öne ekle, target'a ulaşınca dur
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

            # Sıralama: önce front (ağır→hafif), sonra rear (ağır→hafif)
            assignment.pallet_ids = front_ids + rear_ids

            front_w = sum(pallet_map[pid].total_weight_kg for pid in front_ids if pid in pallet_map)
            rear_w = sum(pallet_map[pid].total_weight_kg for pid in rear_ids if pid in pallet_map)

            assignment.front_weight_kg = round(front_w, 2)
            assignment.rear_weight_kg = round(rear_w, 2)
            assignment.front_pct = round((front_w / total_w) * 100, 1) if total_w else 0
            assignment.balance_ok = abs(front_w / total_w - target) <= tolerance if total_w else True
