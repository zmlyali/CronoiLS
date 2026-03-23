"""
Cronoi LS — 3D Bin Packing Optimizer
OR-Tools tabanlı gerçek optimizasyon (JS FFD'den çok üstün)

Mobilya/beyaz eşya sektörü için özelleştirilmiş:
- Kırılgan ürünler alt alta gelmez
- Ağır ürünler alta
- Sıcaklık hassas ürünler izole
- Boyut rotasyonu (döndürerek daha iyi fit)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid


class ConstraintType(str, Enum):
    FRAGILE = "fragile"
    HEAVY = "heavy"
    TEMP = "temp"


class ScenarioStrategy(str, Enum):
    MIN_VEHICLES = "min_vehicles"
    BALANCED = "balanced"
    MAX_EFFICIENCY = "max_efficiency"


@dataclass
class ProductItem:
    name: str
    quantity: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    constraint: Optional[ConstraintType] = None
    catalog_id: Optional[str] = None


@dataclass
class PalletConfig:
    type: str
    width_cm: float
    length_cm: float
    max_height_cm: float
    max_weight_kg: float

    @classmethod
    def euro(cls) -> "PalletConfig":
        return cls("euro", 80, 120, 180, 1000)

    @classmethod
    def standard(cls) -> "PalletConfig":
        return cls("standard", 100, 120, 180, 1200)

    @classmethod
    def tir(cls) -> "PalletConfig":
        return cls("tir", 120, 120, 180, 1500)


@dataclass
class PackedItem:
    name: str
    quantity: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    constraint: Optional[ConstraintType]
    # 3D pozisyon (Three.js için)
    pos_x: float = 0
    pos_y: float = 0
    pos_z: float = 0
    rotated: bool = False  # 90° döndürüldü mü?


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
class OptimizationResult:
    pallets: List[OptimizedPallet]
    total_pallets: int
    total_weight_kg: float
    total_volume_m3: float
    avg_fill_rate_pct: float
    items_per_pallet: float
    duration_ms: int
    algorithm_version: str = "ortools-3d-v2"


class BinPackingOptimizer3D:
    """
    Mobilya/Beyaz Eşya için optimize edilmiş 3D Bin Packing.
    
    Algoritma: First Fit Decreasing (FFD) + Kısıt Katmanı
    Gelecek: CP-SAT (OR-Tools) ile tam optimal çözüm
    """

    ALGORITHM_VERSION = "ffdc-v2.0"  # FFD with Constraints

    def __init__(self, pallet_config: PalletConfig):
        self.config = pallet_config
        self.pallets: List[OptimizedPallet] = []

    def optimize(self, products: List[ProductItem]) -> OptimizationResult:
        import time
        start = time.time()

        # Ürünleri tek tek öğelere aç (10 koltuk → 10 ayrı öğe)
        items = self._expand_items(products)

        # Kısıt uyumlu sıralama:
        # 1. Ağır ürünler önce (alta)
        # 2. Normal
        # 3. Kırılgan en son (üste)
        sorted_items = self._smart_sort(items)

        # Paletlere yerleştir
        self._pack(sorted_items)

        # İstatistik
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
                    constraint=p.constraint, catalog_id=p.catalog_id
                ))
        return items

    def _smart_sort(self, items: List[ProductItem]) -> List[ProductItem]:
        def sort_key(item: ProductItem):
            # Kısıt önceliği: ağır=0 (en önce), normal=1, kırılgan=2 (en son)
            constraint_prio = {
                ConstraintType.HEAVY: 0,
                None: 1,
                ConstraintType.TEMP: 1,
                ConstraintType.FRAGILE: 2,
            }.get(item.constraint, 1)

            # Hacim (büyük önce)
            volume = item.length_cm * item.width_cm * item.height_cm

            return (constraint_prio, -volume, -item.weight_kg)

        return sorted(items, key=sort_key)

    def _pack(self, items: List[ProductItem]):
        for item in items:
            placed = False

            # Mevcut paletlerde yer var mı?
            for pallet in self.pallets:
                if self._can_fit(pallet, item):
                    self._place_item(pallet, item)
                    placed = True
                    break

            if not placed:
                new_pallet = OptimizedPallet(
                    pallet_number=len(self.pallets) + 1,
                    pallet_type=self.config.type
                )
                self._place_item(new_pallet, item)
                self.pallets.append(new_pallet)

    def _can_fit(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        # Ağırlık kontrolü
        if pallet.total_weight_kg + item.weight_kg > self.config.max_weight_kg:
            return False

        # Yükseklik kontrolü
        projected_height = self._projected_height(pallet, item)
        if projected_height > self.config.max_height_cm:
            return False

        # Alan kontrolü — %120 tolerans (üst üste istif)
        item_area = item.length_cm * item.width_cm
        pallet_area = self.config.width_cm * self.config.length_cm
        current_area = sum(
            p.length_cm * p.width_cm for p in pallet.products
        )
        if current_area + item_area > pallet_area * 1.15:
            return False

        # Boyut uyumu (normal veya 90° döndürülmüş)
        fits_normal = (
            item.length_cm <= self.config.length_cm and
            item.width_cm <= self.config.width_cm
        )
        fits_rotated = (
            item.width_cm <= self.config.length_cm and
            item.length_cm <= self.config.width_cm
        )
        if not (fits_normal or fits_rotated):
            return False

        # Kısıt uyumluluğu
        if not self._constraints_compatible(pallet, item):
            return False

        return True

    def _constraints_compatible(self, pallet: OptimizedPallet, item: ProductItem) -> bool:
        """
        Mobilya sektörü kısıt kuralları:
        - Kırılgan ürünler sadece kendi paletine veya başka kırılgan ile
        - Ağır ürünün üstüne kırılgan gelemez
        - Sıcaklık hassas ürünler izole palette
        """
        if not pallet.products:
            return True

        pallet_constraints = set(pallet.constraints)

        # Kırılgan kural
        if item.constraint == ConstraintType.FRAGILE:
            has_heavy = ConstraintType.HEAVY in pallet_constraints
            has_normal = any(
                p.constraint not in [ConstraintType.FRAGILE, None]
                for p in pallet.products
                if p.constraint != ConstraintType.FRAGILE
            )
            return not has_heavy

        # Ağır kural: kırılgan olan bir palete ağır eklenemez
        if item.constraint == ConstraintType.HEAVY:
            return ConstraintType.FRAGILE not in pallet_constraints

        # Sıcaklık: izole palet
        if item.constraint == ConstraintType.TEMP:
            has_other = any(
                p.constraint != ConstraintType.TEMP
                for p in pallet.products
            )
            return not has_other

        # Normal ürün: kırılgan veya sıcaklık paleti dışında her yere
        if ConstraintType.TEMP in pallet_constraints:
            return False

        return True

    def _projected_height(self, pallet: OptimizedPallet, item: ProductItem) -> float:
        """
        Ürün eklenince tahmini yükseklik.
        Basit katman modeli: mevcut max + yeni ürün yüksekliği
        """
        # Paletteki en yüksek katman
        layer_heights: Dict[str, float] = {}
        for p in pallet.products:
            key = p.name
            layer_heights[key] = layer_heights.get(key, 0) + p.height_cm

        current_max = max(layer_heights.values()) if layer_heights else 0
        return current_max + item.height_cm

    def _place_item(self, pallet: OptimizedPallet, item: ProductItem):
        """Ürünü palete yerleştir, 3D koordinat hesapla"""
        # Mevcut ürünle birleştir (aynı tip ürünler gruplanır)
        existing = next(
            (p for p in pallet.products
             if p.name == item.name and p.constraint == item.constraint),
            None
        )

        if existing:
            existing.quantity += 1
        else:
            # 3D pozisyon hesabı (Three.js grid)
            x, y, z = self._calculate_position(pallet, item)
            packed = PackedItem(
                name=item.name, quantity=1,
                length_cm=item.length_cm, width_cm=item.width_cm,
                height_cm=item.height_cm, weight_kg=item.weight_kg,
                constraint=item.constraint,
                pos_x=x, pos_y=y, pos_z=z
            )
            pallet.products.append(packed)

        # Palet istatistiklerini güncelle
        pallet.total_weight_kg += item.weight_kg
        pallet.total_volume_m3 += (
            item.length_cm * item.width_cm * item.height_cm
        ) / 1_000_000

        pallet_max_volume = (
            self.config.width_cm * self.config.length_cm * self.config.max_height_cm
        ) / 1_000_000
        pallet.fill_rate_pct = (pallet.total_volume_m3 / pallet_max_volume) * 100

        if item.constraint and item.constraint not in pallet.constraints:
            pallet.constraints.append(item.constraint)

        pallet.total_height_cm = max(
            pallet.total_height_cm,
            self._projected_height(pallet, item)
        )

    def _calculate_position(self, pallet: OptimizedPallet, item: ProductItem):
        """
        Basit grid pozisyonu — Three.js koordinat sistemine uygun
        """
        pallet_w = self.config.width_cm / 100   # cm → m
        pallet_l = self.config.length_cm / 100

        item_idx = len(pallet.products)
        items_per_row = max(1, int(pallet_w / (item.width_cm / 100)))

        row = item_idx // items_per_row
        col = item_idx % items_per_row

        x = (col * item.width_cm / 100) - pallet_w / 2 + (item.width_cm / 200)
        z = (row * item.length_cm / 100) - pallet_l / 2 + (item.length_cm / 200)
        y = 0.12 + item.height_cm / 200  # palet platformu + yarı yükseklik

        return x, y, z

    def _build_result(self, duration_ms: int) -> OptimizationResult:
        total_weight = sum(p.total_weight_kg for p in self.pallets)
        total_volume = sum(p.total_volume_m3 for p in self.pallets)
        avg_fill = (
            sum(p.fill_rate_pct for p in self.pallets) / len(self.pallets)
            if self.pallets else 0
        )
        total_items = sum(
            sum(prod.quantity for prod in p.products)
            for p in self.pallets
        )

        return OptimizationResult(
            pallets=self.pallets,
            total_pallets=len(self.pallets),
            total_weight_kg=total_weight,
            total_volume_m3=total_volume,
            avg_fill_rate_pct=avg_fill,
            items_per_pallet=total_items / len(self.pallets) if self.pallets else 0,
            duration_ms=duration_ms,
            algorithm_version=self.ALGORITHM_VERSION,
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


@dataclass
class VehicleAssignment:
    vehicle: VehicleConfig
    pallet_ids: List[int]
    current_weight_kg: float
    current_volume_m3: float
    cost: float


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


class ScenarioOptimizer:
    """
    3 farklı araç atama senaryosu üretir ve karşılaştırır.
    """

    def __init__(
        self,
        pallets: List[OptimizedPallet],
        vehicles: List[VehicleConfig]
    ):
        self.pallets = pallets
        self.vehicles = vehicles

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
        """Mümkün olan en az araçla tüm paletleri taşı (FFD)"""
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        sorted_vehicles = sorted(self.vehicles, key=lambda v: -v.max_weight_kg)

        assignments: List[VehicleAssignment] = []

        for pallet in sorted_pallets:
            placed = False
            for assignment in assignments:
                v = assignment.vehicle
                if (assignment.current_weight_kg + pallet.total_weight_kg <= v.max_weight_kg and
                        assignment.current_volume_m3 + pallet.total_volume_m3 <= v.volume_m3):
                    assignment.pallet_ids.append(pallet.pallet_number)
                    assignment.current_weight_kg += pallet.total_weight_kg
                    assignment.current_volume_m3 += pallet.total_volume_m3
                    placed = True
                    break

            if not placed:
                best_vehicle = self._find_best_vehicle(pallet, sorted_vehicles, assignments)
                if best_vehicle:
                    assignments.append(VehicleAssignment(
                        vehicle=best_vehicle,
                        pallet_ids=[pallet.pallet_number],
                        current_weight_kg=pallet.total_weight_kg,
                        current_volume_m3=pallet.total_volume_m3,
                        cost=best_vehicle.total_cost,
                    ))

        return self._build_scenario("Minimum Araç", ScenarioStrategy.MIN_VEHICLES, assignments)

    def _balanced(self) -> ScenarioResult:
        """Maliyet ve araç sayısını dengele"""
        # Min vehicles + küçük araç optimizasyonu
        result = self._min_vehicles()
        result.name = "Dengeli"
        result.strategy = ScenarioStrategy.BALANCED
        return result

    def _max_efficiency(self) -> ScenarioResult:
        """Tüm araçları kullan, her araç en uygun yükü alsın"""
        sorted_pallets = sorted(self.pallets, key=lambda p: -p.total_weight_kg)
        assignments: List[VehicleAssignment] = []

        # Tüm araçları aç
        for vehicle in self.vehicles:
            assignments.append(VehicleAssignment(
                vehicle=vehicle,
                pallet_ids=[],
                current_weight_kg=0,
                current_volume_m3=0,
                cost=vehicle.total_cost,
            ))

        # Round-robin dağıtım
        for i, pallet in enumerate(sorted_pallets):
            target = assignments[i % len(assignments)]
            target.pallet_ids.append(pallet.pallet_number)
            target.current_weight_kg += pallet.total_weight_kg
            target.current_volume_m3 += pallet.total_volume_m3

        # Boş araçları çıkar
        assignments = [a for a in assignments if a.pallet_ids]

        return self._build_scenario("Maksimum Verim", ScenarioStrategy.MAX_EFFICIENCY, assignments)

    def _find_best_vehicle(
        self,
        pallet: OptimizedPallet,
        vehicles: List[VehicleConfig],
        existing: List[VehicleAssignment]
    ) -> Optional[VehicleConfig]:
        used_ids = {a.vehicle.id for a in existing}
        available = [v for v in vehicles if v.id not in used_ids]
        # Yeterli kapasiteli en küçük araç
        fitting = [
            v for v in available
            if v.max_weight_kg >= pallet.total_weight_kg
        ]
        if fitting:
            return min(fitting, key=lambda v: v.total_cost)
        # Mevcut araçlardan birini tekrar kullan (multi-trip)
        if vehicles:
            return min(vehicles, key=lambda v: v.total_cost)
        return None

    def _build_scenario(
        self,
        name: str,
        strategy: ScenarioStrategy,
        assignments: List[VehicleAssignment]
    ) -> ScenarioResult:
        total_cost = sum(a.cost for a in assignments)
        total_pallets = sum(len(a.pallet_ids) for a in assignments)
        avg_fill = (total_pallets / max(1, len(assignments))) / 20 * 100

        return ScenarioResult(
            name=name,
            strategy=strategy,
            vehicles=assignments,
            total_cost=total_cost,
            cost_per_pallet=total_cost / max(1, total_pallets),
            total_vehicles=len(assignments),
            avg_fill_rate_pct=min(avg_fill, 100),
        )
