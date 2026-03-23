"""
Cronoi LS — Constraint Knowledge Base API

GET    /api/v1/constraints                    → Firma + sistem kısıtlarını listele
POST   /api/v1/constraints                    → Yeni özel kısıt oluştur
GET    /api/v1/constraints/{id}               → Kısıt detayı
PUT    /api/v1/constraints/{id}               → Kısıt güncelle
DELETE /api/v1/constraints/{id}               → Kısıt sil (firma kısıtları)
GET    /api/v1/constraints/compatibility      → Uyumluluk matrisi
POST   /api/v1/constraints/compatibility      → Yeni uyumluluk kuralı ekle
POST   /api/v1/constraints/validate           → Kısıt setini doğrula (çelişki var mı?)
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
from enum import Enum

router = APIRouter()


# ============================================================
# Schemas
# ============================================================

class ConstraintCategoryEnum(str, Enum):
    orientation   = "orientation"
    stackability  = "stackability"
    environment   = "environment"
    loading_order = "loading_order"
    compatibility = "compatibility"
    custom        = "custom"


class ConstraintScopeEnum(str, Enum):
    pallet  = "pallet"
    vehicle = "vehicle"
    both    = "both"


class ParamSchemaInput(BaseModel):
    param_key:     str
    param_label:   str
    param_type:    str = Field(..., pattern="^(number|boolean|select|range|text)$")
    param_default: Optional[Any] = None
    param_min:     Optional[float] = None
    param_max:     Optional[float] = None
    param_options: Optional[List[Dict]] = None
    param_unit:    Optional[str] = None
    is_required:   bool = False


class ConstraintCreate(BaseModel):
    code:            str = Field(..., min_length=2, max_length=50, pattern="^[A-Z0-9_]+$")
    name:            str = Field(..., min_length=2, max_length=100)
    name_en:         Optional[str] = None
    description:     Optional[str] = None
    category:        ConstraintCategoryEnum
    scope:           ConstraintScopeEnum = ConstraintScopeEnum.pallet
    icon_key:        str = "alert"
    color_hex:       str = "#667eea"
    optimizer_rules: Dict[str, Any] = {}
    param_schemas:   List[ParamSchemaInput] = []
    sort_order:      int = 100

    class Config:
        json_schema_extra = {
            "example": {
                "code": "GLASS_PANEL",
                "name": "Cam Panel",
                "description": "Cam paneller dik tutulmalı, üzerine yük konulamaz, yatay taşıma yasak.",
                "category": "stackability",
                "scope": "pallet",
                "icon_key": "glass",
                "color_hex": "#85B7EB",
                "optimizer_rules": {
                    "orientation": "vertical",
                    "rotation_allowed": False,
                    "max_weight_above_kg": 0,
                    "layer_position": "edge"
                },
                "param_schemas": []
            }
        }


class ConstraintResponse(BaseModel):
    id:              UUID
    code:            str
    name:            str
    name_en:         Optional[str]
    description:     Optional[str]
    category:        str
    scope:           str
    icon_key:        str
    color_hex:       str
    is_system_default: bool
    is_active:       bool
    optimizer_rules: Dict[str, Any]
    param_schemas:   List[Dict] = []
    use_count:       int
    sort_order:      int

    class Config:
        from_attributes = True


class CompatibilityRuleCreate(BaseModel):
    constraint_a_code: str
    constraint_b_code: str
    rule_type:         str = Field(..., pattern="^(cannot_share_pallet|cannot_share_vehicle|must_be_below|must_be_above|must_be_separated_by_m|requires_isolation)$")
    severity:          str = Field(default="error", pattern="^(error|warning)$")
    description:       Optional[str] = None
    is_symmetric:      bool = True
    min_separation_m:  Optional[float] = None


class CompatibilityRuleResponse(BaseModel):
    id:                UUID
    constraint_a_code: str
    constraint_a_name: str
    constraint_b_code: str
    constraint_b_name: str
    rule_type:         str
    severity:          str
    description:       Optional[str]
    is_symmetric:      bool
    is_system_default: bool


class ValidateRequest(BaseModel):
    """Bir ürüne atanacak kısıt setini doğrula"""
    constraint_codes: List[str]
    param_values:     Dict[str, Dict[str, Any]] = {}
    # {"COLD_CHAIN": {"temp_min_c": 2, "temp_max_c": 8}}


class ValidateResponse(BaseModel):
    is_valid:     bool
    errors:       List[str] = []
    warnings:     List[str] = []
    suggestions:  List[str] = []


# ============================================================
# Endpoints
# ============================================================

@router.get("", response_model=List[ConstraintResponse])
async def list_constraints(
    category: Optional[ConstraintCategoryEnum] = Query(None),
    scope:    Optional[str] = Query(None),
    include_system: bool = Query(True, description="Sistem varsayılanlarını dahil et"),
    search:   Optional[str] = Query(None),
):
    """
    Firma + sistem kısıtlarını listele.

    Yanıt: [sistem_kısıtları] + [firma_kısıtları]
    Sistem kısıtları is_system_default=True, firma kısıtları False.
    Firmalar sistem kısıtlarını görebilir ama silemez/değiştiremez.
    """
    # TODO: DB sorgusu
    # query = select(ConstraintDefinition).where(
    #     or_(
    #         ConstraintDefinition.company_id == current_user.company_id,
    #         ConstraintDefinition.is_system_default == True if include_system else False
    #     ),
    #     ConstraintDefinition.is_active == True
    # )
    # if category:
    #     query = query.where(ConstraintDefinition.category == category)
    # if search:
    #     query = query.where(ConstraintDefinition.name.ilike(f"%{search}%"))
    # results = await db.execute(query.order_by(ConstraintDefinition.sort_order))

    # Test dönüşü
    return []


@router.post("", response_model=ConstraintResponse, status_code=status.HTTP_201_CREATED)
async def create_constraint(payload: ConstraintCreate):
    """
    Firmaya özel yeni kısıt tanımla.

    Örnekler:
    - "Cam Panel" → dikey zorunlu + üzerine yük yasak
    - "Mermer Levha" → yatay zorunlu + max 200kg üst yük + alt katman zorunlu
    - "Pil Paketi" → sıcaklık hassas (15-25°C) + diğer tehlikeli maddelerle aynı araçta olamaz
    """
    # Kod benzersizliği kontrol et
    # existing = await db.execute(
    #     select(ConstraintDefinition).where(
    #         ConstraintDefinition.company_id == current_user.company_id,
    #         ConstraintDefinition.code == payload.code
    #     )
    # )
    # if existing.scalar_one_or_none():
    #     raise HTTPException(400, f"'{payload.code}' kodu zaten mevcut")

    # Optimizer rule validasyonu
    validated_rules = _validate_optimizer_rules(payload.category, payload.optimizer_rules)

    # TODO: DB'ye kaydet
    raise HTTPException(status_code=501, detail="DB bağlantısı henüz hazır değil")


@router.get("/compatibility", response_model=List[CompatibilityRuleResponse])
async def list_compatibility_rules(
    constraint_code: Optional[str] = Query(None)
):
    """
    Uyumluluk matrisini getir.
    constraint_code verilirse sadece o kısıtla ilgili kuralları döner.
    """
    return []


@router.post("/compatibility", response_model=CompatibilityRuleResponse,
             status_code=status.HTTP_201_CREATED)
async def create_compatibility_rule(payload: CompatibilityRuleCreate):
    """
    İki kısıt arasına uyumluluk kuralı ekle.

    Örnek: "Cam Panel" + "Ağır Makine" → cannot_share_pallet (error)
    Örnek: "Soğutulmuş Ürün" + "Nem Hassas" → cannot_share_vehicle (warning)
    """
    if payload.constraint_a_code == payload.constraint_b_code:
        raise HTTPException(400, "Aynı kısıt kendisiyle kural oluşturamaz")

    # TODO: DB'ye kaydet
    raise HTTPException(status_code=501, detail="DB bağlantısı henüz hazır değil")


@router.post("/validate", response_model=ValidateResponse)
async def validate_constraint_set(payload: ValidateRequest):
    """
    Bir ürüne atanmak istenen kısıt setini doğrula.

    Kontrol edilenler:
    1. Çelişen yönelim kısıtları (hem yatay hem dikey)
    2. Çelişen katman kısıtları (hem alt hem üst zorunlu)
    3. Parametre gereksinimleri (MAX_WEIGHT_ABOVE için değer girilmiş mi?)
    4. Uyumluluk matrisi ihlalleri (bu kombinasyon mantıklı mı?)
    5. Optimizasyon önerileri (bu kısıtları eklerken dikkat et)
    """
    from app.services.constraint_engine import get_constraint_engine
    engine = get_constraint_engine()

    errors = []
    warnings = []
    suggestions = []

    codes = set(payload.constraint_codes)

    # 1. Yönelim çelişkisi
    if "HORIZONTAL_ONLY" in codes and "VERTICAL_ONLY" in codes:
        errors.append("Hem 'Yatay Zorunlu' hem 'Dikey Zorunlu' aynı ürüne atanamaz")

    # 2. Katman çelişkisi
    if "MUST_BE_BOTTOM" in codes and "MUST_BE_TOP" in codes:
        errors.append("Hem 'Alt Katman Zorunlu' hem 'Üst Katman Zorunlu' çelişiyor")

    # 3. NO_STACK + MUST_BE_BOTTOM mantıklı kombinasyon
    if "NO_STACK" in codes and "MUST_BE_TOP" in codes:
        suggestions.append("'Üzerine Yük Konulamaz' zaten üst katman anlamına gelir — 'Üst Katman Zorunlu' gereksiz olabilir")

    # 4. COLD_CHAIN parametresi girilmiş mi?
    if "COLD_CHAIN" in codes:
        cold_params = payload.param_values.get("COLD_CHAIN", {})
        if "temp_min_c" not in cold_params or "temp_max_c" not in cold_params:
            warnings.append("'Soğuk Zincir' için sıcaklık aralığı (min/max °C) tanımlanmamış")

    # 5. TEMP_SENSITIVE parametresi
    if "TEMP_SENSITIVE" in codes:
        temp_params = payload.param_values.get("TEMP_SENSITIVE", {})
        if not temp_params.get("temp_min_c") and not temp_params.get("temp_max_c"):
            errors.append("'Sıcaklık Hassas' kısıtı için en az bir sıcaklık sınırı (min veya max) gereklidir")

    # 6. HAZMAT uyarısı
    if "HAZMAT_CLASS_1" in codes:
        warnings.append("Tehlikeli madde kısıtlı ürünler, otomatik olarak izole araçlara yönlendirilir ve ek belge gerektirir")

    # 7. MAX_WEIGHT_ABOVE parametresi
    if "MAX_WEIGHT_ABOVE" in codes:
        mwa_params = payload.param_values.get("MAX_WEIGHT_ABOVE", {})
        if "max_weight_above_kg" not in mwa_params:
            errors.append("'Maksimum Üst Yük' kısıtı için ağırlık değeri (kg) girilmesi zorunludur")

    # 8. Öneri: Kırılgan ürün için önerilen kombinasyon
    if "THIS_SIDE_UP" in codes and "MUST_BE_TOP" not in codes:
        suggestions.append("'Bu Taraf Yukarı' kısıtlı ürünler için 'Üst Katman Zorunlu' eklemeyi düşünün")

    # 9. Yükleme sırası çelişkisi
    if "LOAD_FIRST" in codes and "LOAD_LAST" in codes:
        errors.append("'İlk Yükle' ve 'Son Yükle' aynı anda kullanılamaz")
    if "VEHICLE_FRONT" in codes and "VEHICLE_REAR" in codes:
        errors.append("'Araç Önüne' ve 'Araç Arkasına' aynı anda kullanılamaz")

    return ValidateResponse(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        suggestions=suggestions,
    )


@router.put("/{constraint_id}", response_model=ConstraintResponse)
async def update_constraint(constraint_id: UUID, payload: ConstraintCreate):
    """
    Firma kısıtını güncelle.
    Sistem kısıtları güncellenemez (403).
    """
    # if constraint.is_system_default:
    #     raise HTTPException(403, "Sistem kısıtları değiştirilemez")
    raise HTTPException(status_code=501, detail="DB bağlantısı henüz hazır değil")


@router.delete("/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_constraint(constraint_id: UUID):
    """
    Firma kısıtını sil.
    Ürünlere atanmışsa önce atamalar kaldırılmalı (veya cascade).
    Sistem kısıtları silinemez.
    """
    # if constraint.use_count > 0:
    #     raise HTTPException(409, f"Bu kısıt {constraint.use_count} ürüne atanmış. Önce atamaları kaldırın.")
    pass


# ============================================================
# Yardımcı Fonksiyonlar
# ============================================================

def _validate_optimizer_rules(
    category: ConstraintCategoryEnum,
    rules: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Optimizer kurallarının kategoriye uygun olduğunu doğrula.
    """
    category_allowed_keys = {
        "orientation":   {"orientation", "rotation_allowed", "top_face_fixed"},
        "stackability":  {"max_weight_above_kg", "max_items_above", "layer_position", "priority"},
        "environment":   {"temp_min_c", "temp_max_c", "requires_refrigeration",
                          "moisture_sensitive", "hazmat_class", "requires_isolation",
                          "requires_special_permit", "requires_dry_environment"},
        "loading_order": {"loading_priority", "position_preference", "vehicle_zone", "zone_ratio"},
        "compatibility": {},  # Uyumluluk kuralları ayrı tabloda
        "custom":        None,  # Özel kısıtlar herhangi bir key içerebilir
    }

    allowed = category_allowed_keys.get(category.value)
    if allowed is not None:  # custom kategorisi için None
        unknown_keys = set(rules.keys()) - allowed
        if unknown_keys:
            raise HTTPException(
                400,
                f"'{category.value}' kategorisi için bilinmeyen kurallar: {unknown_keys}. "
                f"İzin verilen: {allowed}"
            )

    return rules
