"""
Cronoi LS — Constraint Engine v2.0

Kısıt Bilgi Havuzu'ndan okunan dinamik kural setini
bin packing ve araç atama optimizasyonuna entegre eder.

Mimari:
  ConstraintEngine
    ├── load_constraints(company_id)   → DB'den firma kısıtlarını yükle
    ├── evaluate_pallet_placement()    → Ürün palete gidebilir mi?
    ├── evaluate_vehicle_placement()   → Palet araca gidebilir mi?
    ├── get_loading_directives()       → Yükleme sırası kuralları
    └── collect_violations()           → İhlal raporu üret
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ============================================================
# Veri Modelleri
# ============================================================

class ConstraintCategory(str, Enum):
    ORIENTATION  = "orientation"
    STACKABILITY = "stackability"
    ENVIRONMENT  = "environment"
    LOADING_ORDER = "loading_order"
    COMPATIBILITY = "compatibility"
    CUSTOM       = "custom"


class ViolationSeverity(str, Enum):
    ERROR   = "error"    # Kesin ihlal — bu yerleştirme yapılamaz
    WARNING = "warning"  # Uyarı — mümkünse kaçın


@dataclass
class ConstraintDef:
    """DB'den yüklenen kısıt tanımı"""
    id: str
    code: str
    name: str
    category: ConstraintCategory
    scope: str                      # 'pallet' | 'vehicle' | 'both'
    optimizer_rules: Dict[str, Any] # DB'deki JSONB kolonu
    severity: str = "error"


@dataclass
class ProductConstraint:
    """Ürüne atanmış kısıt (parametre değerleriyle birlikte)"""
    definition: ConstraintDef
    param_values: Dict[str, Any]    # Ürüne özel parametre override'ları

    def get_param(self, key: str, fallback: Any = None) -> Any:
        """Parametre değerini al: önce ürün override, sonra tanım varsayılanı"""
        if key in self.param_values:
            return self.param_values[key]
        return self.definition.optimizer_rules.get(key, fallback)


@dataclass
class CompatibilityRule:
    """İki kısıt arasındaki ilişki kuralı"""
    constraint_a_id: str
    constraint_b_id: str
    rule_type: str
    severity: ViolationSeverity
    description: str
    is_symmetric: bool
    min_separation_m: Optional[float] = None


@dataclass
class ConstraintViolation:
    """Optimizer tarafından tespit edilen ihlal"""
    constraint_code: str
    rule_type: str
    severity: ViolationSeverity
    product_a_name: str
    product_b_name: Optional[str]
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlacementDecision:
    """Yerleştirme kararı sonucu"""
    allowed: bool
    violations: List[ConstraintViolation] = field(default_factory=list)
    warnings: List[ConstraintViolation] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == ViolationSeverity.ERROR for v in self.violations)

    def block_reason(self) -> Optional[str]:
        errors = [v for v in self.violations if v.severity == ViolationSeverity.ERROR]
        if errors:
            return errors[0].message
        return None


# ============================================================
# Ana Engine
# ============================================================

class ConstraintEngine:
    """
    Optimizer ile DB arasındaki köprü.
    Tüm kısıt değerlendirmesi burada yapılır.
    """

    def __init__(self):
        self.constraints: Dict[str, ConstraintDef] = {}
        self.compat_rules: List[CompatibilityRule] = []
        self._loaded = False

    def load_from_dicts(
        self,
        constraint_defs: List[Dict],
        compat_rules: List[Dict]
    ) -> None:
        """
        DB sonuçlarını (dict listesi) engine'e yükle.
        FastAPI endpoint'inden çağrılır.
        """
        self.constraints = {}
        for row in constraint_defs:
            cd = ConstraintDef(
                id=str(row["id"]),
                code=row["code"],
                name=row["name"],
                category=ConstraintCategory(row["category"]),
                scope=row["scope"],
                optimizer_rules=row.get("optimizer_rules", {}),
            )
            self.constraints[cd.code] = cd

        self.compat_rules = []
        for row in compat_rules:
            self.compat_rules.append(CompatibilityRule(
                constraint_a_id=str(row["constraint_a_id"]),
                constraint_b_id=str(row["constraint_b_id"]),
                rule_type=row["rule_type"],
                severity=ViolationSeverity(row["severity"]),
                description=row.get("description", ""),
                is_symmetric=row.get("is_symmetric", True),
                min_separation_m=row.get("min_separation_m"),
            ))

        self._loaded = True
        logger.info(f"ConstraintEngine: {len(self.constraints)} kısıt, {len(self.compat_rules)} uyumluluk kuralı yüklendi")

    def load_defaults(self) -> None:
        """
        DB bağlantısı olmadan test/geliştirme için
        varsayılan kısıtları koddan yükle.
        """
        defaults = [
            # Yönelim
            {"id": "c1", "code": "HORIZONTAL_ONLY", "name": "Yatay Zorunlu",
             "category": "orientation", "scope": "pallet",
             "optimizer_rules": {"orientation": "horizontal", "rotation_allowed": False}},
            {"id": "c2", "code": "VERTICAL_ONLY", "name": "Dikey Zorunlu",
             "category": "orientation", "scope": "pallet",
             "optimizer_rules": {"orientation": "vertical", "rotation_allowed": False}},
            {"id": "c3", "code": "THIS_SIDE_UP", "name": "Bu Taraf Yukarı",
             "category": "orientation", "scope": "pallet",
             "optimizer_rules": {"orientation": "fixed", "rotation_allowed": False, "top_face_fixed": True}},

            # İstif
            {"id": "c4", "code": "NO_STACK", "name": "Üzerine Yük Konulamaz",
             "category": "stackability", "scope": "pallet",
             "optimizer_rules": {"max_weight_above_kg": 0, "max_items_above": 0}},
            {"id": "c5", "code": "MAX_WEIGHT_ABOVE", "name": "Maksimum Üst Yük",
             "category": "stackability", "scope": "pallet",
             "optimizer_rules": {"max_weight_above_kg": None}},  # parametreden gelir
            {"id": "c6", "code": "MUST_BE_BOTTOM", "name": "Alt Katman Zorunlu",
             "category": "stackability", "scope": "pallet",
             "optimizer_rules": {"layer_position": "bottom", "priority": 1}},
            {"id": "c7", "code": "MUST_BE_TOP", "name": "Üst Katman Zorunlu",
             "category": "stackability", "scope": "pallet",
             "optimizer_rules": {"layer_position": "top", "priority": -1}},

            # Ortam
            {"id": "c8", "code": "COLD_CHAIN", "name": "Soğuk Zincir",
             "category": "environment", "scope": "vehicle",
             "optimizer_rules": {"temp_min_c": 2, "temp_max_c": 8, "requires_refrigeration": True}},
            {"id": "c9", "code": "TEMP_SENSITIVE", "name": "Sıcaklık Hassas",
             "category": "environment", "scope": "vehicle",
             "optimizer_rules": {"temp_min_c": None, "temp_max_c": None}},
            {"id": "c10", "code": "KEEP_DRY", "name": "Nemden Koru",
             "category": "environment", "scope": "vehicle",
             "optimizer_rules": {"moisture_sensitive": True}},
            {"id": "c11", "code": "HAZMAT_CLASS_1", "name": "Tehlikeli Madde",
             "category": "environment", "scope": "vehicle",
             "optimizer_rules": {"hazmat_class": 1, "requires_isolation": True}},

            # Yükleme sırası
            {"id": "c12", "code": "LOAD_FIRST", "name": "İlk Yükle",
             "category": "loading_order", "scope": "vehicle",
             "optimizer_rules": {"loading_priority": 1, "position_preference": "rear"}},
            {"id": "c13", "code": "LOAD_LAST", "name": "Son Yükle",
             "category": "loading_order", "scope": "vehicle",
             "optimizer_rules": {"loading_priority": 100, "position_preference": "front"}},
            {"id": "c14", "code": "VEHICLE_FRONT", "name": "Araç Önüne",
             "category": "loading_order", "scope": "vehicle",
             "optimizer_rules": {"vehicle_zone": "front"}},
            {"id": "c15", "code": "VEHICLE_REAR", "name": "Araç Arkasına",
             "category": "loading_order", "scope": "vehicle",
             "optimizer_rules": {"vehicle_zone": "rear"}},
        ]

        compat = [
            {"constraint_a_id": "c8", "constraint_b_id": "c10",
             "rule_type": "cannot_share_vehicle", "severity": "error",
             "description": "Soğuk zincir + nemden koru farklı koşul gerektirir",
             "is_symmetric": True},
            {"constraint_a_id": "c11", "constraint_b_id": "c1",
             "rule_type": "requires_isolation", "severity": "error",
             "description": "Tehlikeli madde izole taşınmalı",
             "is_symmetric": True},
        ]

        self.load_from_dicts(defaults, compat)

    # ============================================================
    # PALET YERLEŞTİRME DEĞERLENDİRMESİ
    # ============================================================

    def can_place_on_pallet(
        self,
        item_name: str,
        item_constraints: List[ProductConstraint],
        pallet_items: List[Tuple[str, List[ProductConstraint]]]
        # [(ürün_adı, [kısıtları])]
    ) -> PlacementDecision:
        """
        Verilen ürünü mevcut palete koyabilir miyiz?
        Tüm palet kısıt kurallarını değerlendirir.
        """
        violations = []

        item_codes = {pc.definition.code for pc in item_constraints}
        pallet_all_codes = {
            pc.definition.code
            for _, pcs in pallet_items
            for pc in pcs
        }

        # 1. YÖNELİM KURALLARI
        violations += self._check_orientation_rules(item_name, item_constraints)

        # 2. İSTİF KURALLARI
        violations += self._check_stackability(
            item_name, item_constraints, pallet_items
        )

        # 3. UYUMLULUK MATRİSİ (palet kapsamlı)
        violations += self._check_compatibility(
            item_name, item_codes, pallet_all_codes, scope="pallet"
        )

        # 4. KATMAN ÇAKIŞMASI
        violations += self._check_layer_conflicts(
            item_name, item_constraints, pallet_items
        )

        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        warnings = [v for v in violations if v.severity == ViolationSeverity.WARNING]

        return PlacementDecision(
            allowed=len(errors) == 0,
            violations=violations,
            warnings=warnings,
        )

    def can_place_in_vehicle(
        self,
        pallet_constraints: List[str],  # Bu paletteki tüm kısıt kodları
        vehicle_existing_constraint_codes: List[str],  # Araçtaki diğer paletlerin kısıtları
    ) -> PlacementDecision:
        """
        Bu paleti mevcut araca koyabilir miyiz?
        Araç kapsamlı kısıtları değerlendirir.
        """
        violations = []

        pallet_codes = set(pallet_constraints)
        vehicle_codes = set(vehicle_existing_constraint_codes)

        # Uyumluluk matrisi — araç kapsamlı
        violations += self._check_compatibility(
            "palet", pallet_codes, vehicle_codes, scope="vehicle"
        )

        # Soğuk zincir izolasyonu
        if "COLD_CHAIN" in pallet_codes and vehicle_codes - {"COLD_CHAIN", "TEMP_SENSITIVE"}:
            violations.append(ConstraintViolation(
                constraint_code="COLD_CHAIN",
                rule_type="cannot_share_vehicle",
                severity=ViolationSeverity.ERROR,
                product_a_name="Soğuk zincir palet",
                product_b_name="Standart ürün",
                message="Soğuk zincir ürünler diğer ürünlerle aynı araçta taşınamaz"
            ))

        # Tehlikeli madde izolasyonu
        if "HAZMAT_CLASS_1" in pallet_codes and vehicle_codes:
            violations.append(ConstraintViolation(
                constraint_code="HAZMAT_CLASS_1",
                rule_type="requires_isolation",
                severity=ViolationSeverity.ERROR,
                product_a_name="Tehlikeli madde palet",
                product_b_name="Diğer ürünler",
                message="Tehlikeli madde (Sınıf 1) tamamen izole araçta taşınmalıdır"
            ))

        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        return PlacementDecision(
            allowed=len(errors) == 0,
            violations=violations,
            warnings=[v for v in violations if v.severity == ViolationSeverity.WARNING],
        )

    # ============================================================
    # YÜKLEME SIRASI DİREKTİFLERİ
    # ============================================================

    def get_loading_priority(
        self, pallet_constraint_codes: List[str]
    ) -> int:
        """
        Paletin yükleme önceliğini döndür.
        Düşük sayı = önce yükle.
        MUST_BE_BOTTOM < LOAD_FIRST < normal < LOAD_LAST < MUST_BE_TOP
        """
        priority = 50  # varsayılan orta

        for code in pallet_constraint_codes:
            if code == "MUST_BE_BOTTOM":
                priority = min(priority, 5)
            elif code == "LOAD_FIRST":
                priority = min(priority, 10)
            elif code == "LOAD_LAST":
                priority = max(priority, 90)
            elif code == "MUST_BE_TOP":
                priority = max(priority, 95)

        return priority

    def get_vehicle_zone(
        self, pallet_constraint_codes: List[str]
    ) -> Optional[str]:
        """
        Paletin araçta nereye yerleştirileceğini döndür.
        Returns: 'front' | 'rear' | 'center' | None
        """
        for code in pallet_constraint_codes:
            if code == "VEHICLE_FRONT":
                return "front"
            elif code == "VEHICLE_REAR":
                return "rear"
        return None

    def get_orientation(
        self, item_constraints: List[ProductConstraint]
    ) -> Dict[str, Any]:
        """
        Ürünün yönelim kısıtlarını özetle.
        Returns: {rotation_allowed, orientation, top_face_fixed}
        """
        result = {"rotation_allowed": True, "orientation": "any", "top_face_fixed": False}
        for pc in item_constraints:
            rules = pc.definition.optimizer_rules
            if "orientation" in rules:
                result["orientation"] = rules["orientation"]
            if "rotation_allowed" in rules:
                result["rotation_allowed"] &= rules["rotation_allowed"]
            if rules.get("top_face_fixed"):
                result["top_face_fixed"] = True
        return result

    # ============================================================
    # YARDIMCI METOTLAR
    # ============================================================

    def _check_orientation_rules(
        self,
        item_name: str,
        constraints: List[ProductConstraint]
    ) -> List[ConstraintViolation]:
        violations = []
        orientations = [
            pc.definition.code for pc in constraints
            if pc.definition.category == ConstraintCategory.ORIENTATION
        ]
        # Hem HORIZONTAL hem VERTICAL aynı üründe çelişir
        if "HORIZONTAL_ONLY" in orientations and "VERTICAL_ONLY" in orientations:
            violations.append(ConstraintViolation(
                constraint_code="ORIENTATION_CONFLICT",
                rule_type="conflicting_orientations",
                severity=ViolationSeverity.ERROR,
                product_a_name=item_name,
                product_b_name=None,
                message=f"'{item_name}' aynı anda hem yatay hem dikey kısıtına sahip — çelişki!"
            ))
        return violations

    def _check_stackability(
        self,
        item_name: str,
        item_constraints: List[ProductConstraint],
        pallet_items: List[Tuple[str, List[ProductConstraint]]]
    ) -> List[ConstraintViolation]:
        violations = []

        # Eklenen ürün üzerine yük konulamaz mı? → Alt katman gerektirir
        item_codes = {pc.definition.code for pc in item_constraints}

        # Mevcut palette NO_STACK olan var ve yeni ürün onun üstüne gidiyor?
        for existing_name, existing_pcs in pallet_items:
            existing_codes = {pc.definition.code for pc in existing_pcs}

            if "NO_STACK" in existing_codes:
                # Yeni ürün eklenmek istiyor ama üste gidemez
                violations.append(ConstraintViolation(
                    constraint_code="NO_STACK",
                    rule_type="stack_violation",
                    severity=ViolationSeverity.ERROR,
                    product_a_name=item_name,
                    product_b_name=existing_name,
                    message=f"'{existing_name}' üzerine yük konulamaz (NO_STACK kısıtı)"
                ))

            # MAX_WEIGHT_ABOVE kontrolü
            for pc in existing_pcs:
                if pc.definition.code == "MAX_WEIGHT_ABOVE":
                    max_kg = pc.get_param("max_weight_above_kg")
                    if max_kg is not None:
                        # Bu örnekte yeni ürün ağırlığını bilmemiz lazım
                        # Gerçek implementasyonda item_weight parametre olarak gelir
                        pass  # bkz. can_place_on_pallet_with_weight

        # Katman çakışması: MUST_BE_BOTTOM + MUST_BE_TOP aynı palette?
        pallet_codes = {pc.definition.code for _, pcs in pallet_items for pc in pcs}
        if "MUST_BE_TOP" in pallet_codes and "MUST_BE_BOTTOM" in item_codes:
            violations.append(ConstraintViolation(
                constraint_code="LAYER_CONFLICT",
                rule_type="layer_conflict",
                severity=ViolationSeverity.WARNING,
                product_a_name=item_name,
                product_b_name=None,
                message=f"'{item_name}' alt katman kısıtlı, ama palette üst katman zorunlu ürün var"
            ))

        return violations

    def _check_layer_conflicts(
        self,
        item_name: str,
        item_constraints: List[ProductConstraint],
        pallet_items: List[Tuple[str, List[ProductConstraint]]]
    ) -> List[ConstraintViolation]:
        violations = []
        item_codes = {pc.definition.code for pc in item_constraints}
        pallet_codes = {pc.definition.code for _, pcs in pallet_items for pc in pcs}

        # MUST_BE_BOTTOM + palete yeni MUST_BE_BOTTOM eklenemez (zaten var)
        if "MUST_BE_BOTTOM" in item_codes and "MUST_BE_BOTTOM" in pallet_codes:
            violations.append(ConstraintViolation(
                constraint_code="MUST_BE_BOTTOM",
                rule_type="duplicate_bottom_constraint",
                severity=ViolationSeverity.WARNING,
                product_a_name=item_name,
                product_b_name=None,
                message="Birden fazla 'Alt Katman Zorunlu' ürün — ağırlığa göre sıralama yapılacak"
            ))
        return violations

    def _check_compatibility(
        self,
        item_name: str,
        item_codes: set,
        existing_codes: set,
        scope: str
    ) -> List[ConstraintViolation]:
        """Uyumluluk matrisini kontrol et"""
        violations = []

        for rule in self.compat_rules:
            cd_a = next((c for c in self.constraints.values() if c.id == rule.constraint_a_id), None)
            cd_b = next((c for c in self.constraints.values() if c.id == rule.constraint_b_id), None)

            if not cd_a or not cd_b:
                continue

            # Kural kapsamı uyuyor mu?
            if cd_a.scope not in (scope, "both") and cd_b.scope not in (scope, "both"):
                continue

            # İhlal var mı?
            a_in_item = cd_a.code in item_codes
            b_in_existing = cd_b.code in existing_codes
            b_in_item = cd_b.code in item_codes
            a_in_existing = cd_a.code in existing_codes

            triggered = (a_in_item and b_in_existing) or (
                rule.is_symmetric and b_in_item and a_in_existing
            )

            if triggered:
                violations.append(ConstraintViolation(
                    constraint_code=f"{cd_a.code}+{cd_b.code}",
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    product_a_name=item_name,
                    product_b_name="mevcut ürün",
                    message=rule.description or
                        f"'{cd_a.name}' ve '{cd_b.name}' kısıtları uyumsuz ({rule.rule_type})"
                ))

        return violations

    def build_sort_key(
        self,
        item_constraints: List[ProductConstraint]
    ) -> Tuple[int, int, int]:
        """
        Bin packing sıralama anahtarı.
        Returns: (katman_önceliği, yükleme_önceliği, hacim_puanı)
        Küçük = önce işle
        """
        codes = {pc.definition.code for pc in item_constraints}

        # Katman: ağır + alt zorunlu = 0 (en önce), kırılgan = 2 (en son)
        if "MUST_BE_BOTTOM" in codes:
            layer_prio = 0
        elif "HAZMAT_CLASS_1" in codes:
            layer_prio = 0
        elif "MUST_BE_TOP" in codes or "NO_STACK" in codes:
            layer_prio = 2
        else:
            layer_prio = 1

        # Yükleme sırası
        load_prio = self.get_loading_priority(list(codes))

        return (layer_prio, load_prio, 0)


# ============================================================
# Singleton — Optimizer tarafından import edilir
# ============================================================
_engine_instance: Optional[ConstraintEngine] = None


def get_constraint_engine() -> ConstraintEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ConstraintEngine()
        _engine_instance.load_defaults()
    return _engine_instance


def reset_engine():
    """Test için engine'i sıfırla"""
    global _engine_instance
    _engine_instance = None
