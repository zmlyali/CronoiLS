-- ============================================================
-- Cronoi LS — Kısıt Bilgi Havuzu (Constraint Knowledge Base)
-- Schema ek dosyası — schema.sql'e eklenir
-- ============================================================

-- ============================================================
-- ENUMS — Kısıt tipleri
-- ============================================================

CREATE TYPE constraint_category AS ENUM (
    'orientation',      -- Yönelim (yatay/dikey/bu taraf yukarı)
    'stackability',     -- İstif ve üst yük limitleri
    'environment',      -- Sıcaklık, nem, tehlikeli madde
    'loading_order',    -- Yükleme sırası direktifleri
    'compatibility',    -- Diğer kısıtlarla ilişki kuralları
    'custom'            -- Firma tanımlı özel kısıt
);

CREATE TYPE constraint_scope AS ENUM (
    'pallet',           -- Palet içi kural
    'vehicle',          -- Araç içi kural
    'both'              -- Her ikisi
);

CREATE TYPE compatibility_rule_type AS ENUM (
    'cannot_share_pallet',      -- Aynı palete giremez
    'cannot_share_vehicle',     -- Aynı araca giremez
    'must_be_below',            -- A daima B'nin altında
    'must_be_above',            -- A daima B'nin üstünde
    'must_be_separated_by_m',   -- Aralarında min mesafe
    'requires_isolation'        -- İzole palet/alan şart
);

-- ============================================================
-- CONSTRAINT DEFINITIONS — Kısıt Tanım Havuzu
-- Her firma kendi kısıtlarını burada tanımlar
-- Sistem kısıtları is_system_default=TRUE (tüm firmalara görünür)
-- ============================================================

CREATE TABLE constraint_definitions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id          UUID REFERENCES companies(id) ON DELETE CASCADE,
    -- NULL ise sistem varsayılanı (tüm firmalara görünür)

    -- Kimlik
    code                TEXT NOT NULL,          -- 'NO_STACK', 'COLD_CHAIN', 'HORIZONTAL_ONLY'
    name                TEXT NOT NULL,          -- 'Üzerine Yük Konulamaz'
    name_en             TEXT,                   -- 'No Stack' (export/API için)
    description         TEXT,                   -- Detaylı açıklama
    category            constraint_category NOT NULL,
    scope               constraint_scope NOT NULL DEFAULT 'pallet',

    -- Görsel
    icon_key            TEXT NOT NULL DEFAULT 'alert',   -- UI ikon kodu
    color_hex           TEXT NOT NULL DEFAULT '#667eea', -- Badge rengi

    -- Sistem mi yoksa firma mı?
    is_system_default   BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- Optimizer direktifleri (JSON — engine tarafından okunur)
    -- Örnek: {"orientation": "horizontal", "rotation_allowed": false}
    -- Örnek: {"max_weight_above_kg": 0, "max_items_above": 0}
    -- Örnek: {"temp_min_c": 2, "temp_max_c": 8, "isolate": true}
    optimizer_rules     JSONB NOT NULL DEFAULT '{}',

    -- Metadata
    sort_order          INT NOT NULL DEFAULT 100,
    use_count           INT NOT NULL DEFAULT 0,     -- kaç üründe kullanılıyor
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(company_id, code),
    -- Sistem kısıtları için company_id NULL olacak, kod benzersiz olmalı
    EXCLUDE (code WITH =) WHERE (company_id IS NULL)
);

CREATE INDEX idx_constraints_company ON constraint_definitions(company_id)
    WHERE company_id IS NOT NULL;
CREATE INDEX idx_constraints_system ON constraint_definitions(is_system_default)
    WHERE is_system_default = TRUE;
CREATE INDEX idx_constraints_category ON constraint_definitions(category);

-- ============================================================
-- CONSTRAINT PARAMETER SCHEMAS — Kısıt parametre şablonları
-- Bir kısıt tipi hangi parametreleri alır?
-- Kullanıcı "Max üst yük" kısıtı seçince ne soralım?
-- ============================================================

CREATE TABLE constraint_param_schemas (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    constraint_id   UUID NOT NULL REFERENCES constraint_definitions(id) ON DELETE CASCADE,
    param_key       TEXT NOT NULL,              -- 'max_weight_above_kg'
    param_label     TEXT NOT NULL,              -- 'Maksimum üst yük (kg)'
    param_type      TEXT NOT NULL,              -- 'number', 'boolean', 'select', 'range'
    param_default   JSONB,                      -- Varsayılan değer
    param_min       NUMERIC,                    -- Min değer (number için)
    param_max       NUMERIC,                    -- Max değer (number için)
    param_options   JSONB,                      -- Select seçenekleri
    param_unit      TEXT,                       -- 'kg', '°C', 'cm', 'adet'
    is_required     BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order      INT NOT NULL DEFAULT 0,
    UNIQUE(constraint_id, param_key)
);

-- ============================================================
-- COMPATIBILITY MATRIX — Kısıtlar arası ilişki kuralları
-- "Soğuk zincir" + "Tehlikeli madde" → aynı araca giremez
-- ============================================================

CREATE TABLE constraint_compatibility_rules (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id          UUID REFERENCES companies(id) ON DELETE CASCADE,
    -- NULL = sistem geneli kural

    constraint_a_id     UUID NOT NULL REFERENCES constraint_definitions(id),
    constraint_b_id     UUID NOT NULL REFERENCES constraint_definitions(id),
    rule_type           compatibility_rule_type NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'error',  -- 'error' | 'warning'
    -- error = kesinlikle ihlal etme
    -- warning = mümkünse kaçın ama zorunda kalırsan uygula

    description         TEXT,                   -- "Neden bu kural var?" açıklaması
    min_separation_m    NUMERIC,                -- rule_type=must_be_separated_by_m için
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_system_default   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A→B aynı zamanda B→A demek için her iki yönü de kaydet (veya simetri flag)
    is_symmetric        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_compat_a ON constraint_compatibility_rules(constraint_a_id);
CREATE INDEX idx_compat_b ON constraint_compatibility_rules(constraint_b_id);
CREATE INDEX idx_compat_company ON constraint_compatibility_rules(company_id);

-- ============================================================
-- PRODUCT CONSTRAINT ASSIGNMENTS — Ürüne kısıt atama
-- Bir ürün birden fazla kısıta sahip olabilir
-- Her kısıt parametreli olabilir (max_weight_above=50kg gibi)
-- ============================================================

CREATE TABLE product_constraint_assignments (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Katalog ürünü veya sevkiyat ürünü
    catalog_product_id  UUID REFERENCES product_catalog(id) ON DELETE CASCADE,
    shipment_product_id UUID REFERENCES shipment_products(id) ON DELETE CASCADE,
    -- İkisinden biri NULL olacak

    constraint_id       UUID NOT NULL REFERENCES constraint_definitions(id),

    -- Bu atamaya özel parametre değerleri (şablon değerini override eder)
    -- Örnek: aynı "max_weight_above" kısıtı farklı ürünlerde farklı kg olabilir
    param_values        JSONB NOT NULL DEFAULT '{}',
    -- {"max_weight_above_kg": 50, "temp_min_c": 4}

    notes               TEXT,                   -- Ek not
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        (catalog_product_id IS NOT NULL AND shipment_product_id IS NULL) OR
        (catalog_product_id IS NULL AND shipment_product_id IS NOT NULL)
    )
);

CREATE INDEX idx_pca_catalog ON product_constraint_assignments(catalog_product_id);
CREATE INDEX idx_pca_shipment ON product_constraint_assignments(shipment_product_id);
CREATE INDEX idx_pca_constraint ON product_constraint_assignments(constraint_id);

-- ============================================================
-- OPTIMIZER VIOLATION LOG — İhlal kayıtları
-- Optimizer hangi kısıtı neden ihlal etti? (uyarı veya hata)
-- ============================================================

CREATE TABLE constraint_violations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id     UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    pallet_id       UUID REFERENCES pallets(id) ON DELETE SET NULL,
    scenario_id     UUID REFERENCES scenarios(id) ON DELETE SET NULL,
    constraint_id   UUID NOT NULL REFERENCES constraint_definitions(id),
    rule_type       TEXT NOT NULL,              -- hangi kural ihlal edildi
    severity        TEXT NOT NULL,              -- 'error' | 'warning'
    product_a_name  TEXT,
    product_b_name  TEXT,
    details         JSONB NOT NULL DEFAULT '{}',
    resolved        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_violations_shipment ON constraint_violations(shipment_id);

-- ============================================================
-- SEED DATA — Sistem varsayılan kısıtları
-- ============================================================

INSERT INTO constraint_definitions (
    code, name, name_en, description, category, scope,
    icon_key, color_hex, is_system_default, optimizer_rules, sort_order
) VALUES

-- YÖNELIM KATEGORİSİ
('HORIZONTAL_ONLY', 'Yatay Zorunlu', 'Horizontal Only',
 'Ürün yalnızca yatay konumda taşınabilir. Dikey konuma geçilemez.',
 'orientation', 'pallet', 'rotate_h', '#3B8BD4', TRUE,
 '{"orientation": "horizontal", "rotation_allowed": false}', 10),

('VERTICAL_ONLY', 'Dikey Zorunlu', 'Vertical Only',
 'Ürün yalnızca dikey konumda taşınabilir. Örn: buzdolabı, çamaşır makinesi.',
 'orientation', 'pallet', 'rotate_v', '#3B8BD4', TRUE,
 '{"orientation": "vertical", "rotation_allowed": false}', 20),

('THIS_SIDE_UP', 'Bu Taraf Yukarı', 'This Side Up',
 'Belirtilen yüz mutlaka yukarıya bakmalı. 90° bile döndürülemez.',
 'orientation', 'pallet', 'arrow_up', '#854F0B', TRUE,
 '{"orientation": "fixed", "rotation_allowed": false, "top_face_fixed": true}', 30),

-- İSTİF KATEGORİSİ
('NO_STACK', 'Üzerine Yük Konulamaz', 'No Stack',
 'Bu ürünün üzerine başka hiçbir ürün veya palet konulamaz.',
 'stackability', 'pallet', 'block', '#A32D2D', TRUE,
 '{"max_weight_above_kg": 0, "max_items_above": 0}', 40),

('MAX_WEIGHT_ABOVE', 'Maksimum Üst Yük', 'Max Weight Above',
 'Ürünün üzerine konabilecek maksimum yük ağırlığı sınırlıdır. Parametre ile belirlenir.',
 'stackability', 'pallet', 'weight_limit', '#BA7517', TRUE,
 '{"max_weight_above_kg": null}', 50),  -- null = parametreden gelecek

('MUST_BE_BOTTOM', 'Alt Katman Zorunlu', 'Must Be Bottom Layer',
 'Bu ürün palet veya araçta her zaman en altta yer almalıdır.',
 'stackability', 'pallet', 'arrow_down', '#0F6E56', TRUE,
 '{"layer_position": "bottom", "priority": 1}', 60),

('MUST_BE_TOP', 'Üst Katman Zorunlu', 'Must Be Top Layer',
 'Bu ürün palet veya araçta her zaman en üstte yer almalıdır.',
 'stackability', 'pallet', 'arrow_up_stop', '#993C1D', TRUE,
 '{"layer_position": "top", "priority": -1}', 70),

-- ORTAM KATEGORİSİ
('COLD_CHAIN', 'Soğuk Zincir', 'Cold Chain',
 'Ürün belirli sıcaklık aralığında tutulmalıdır. Isıtıcı veya soğutucu gerektirmeden taşınamaz.',
 'environment', 'vehicle', 'thermometer', '#185FA5', TRUE,
 '{"temp_min_c": 2, "temp_max_c": 8, "requires_refrigeration": true}', 80),

('TEMP_SENSITIVE', 'Sıcaklık Hassas', 'Temperature Sensitive',
 'Aşırı ısı veya soğuğa maruz bırakılamaz. Minimum/maksimum sıcaklık sınırı parametreden alınır.',
 'environment', 'vehicle', 'thermometer_alert', '#D85A30', TRUE,
 '{"temp_min_c": null, "temp_max_c": null}', 90),

('KEEP_DRY', 'Nemden Koru', 'Keep Dry',
 'Su veya yoğun neme maruz bırakılamaz. Islak yük veya açık alan taşımacılığında uyarı verir.',
 'environment', 'vehicle', 'water_slash', '#0C447C', TRUE,
 '{"moisture_sensitive": true, "requires_dry_environment": true}', 100),

('HAZMAT_CLASS_1', 'Tehlikeli Madde (Sınıf 1)', 'Hazmat Class 1',
 'Patlayıcı veya yangın riski olan madde. Özel taşıma belgesi ve izole araç gerekir.',
 'environment', 'vehicle', 'hazmat', '#A32D2D', TRUE,
 '{"hazmat_class": 1, "requires_isolation": true, "requires_special_permit": true}', 110),

-- YÜKLEME SIRASI KATEGORİSİ
('LOAD_FIRST', 'İlk Yükle (FIFO)', 'Load First',
 'Bu ürünün bulunduğu palet en önce yüklenir. Uzak teslimat noktaları için.',
 'loading_order', 'vehicle', 'sort_first', '#534AB7', TRUE,
 '{"loading_priority": 1, "position_preference": "rear"}', 120),

('LOAD_LAST', 'Son Yükle (LIFO)', 'Load Last',
 'Bu ürünün bulunduğu palet en son yüklenir. İlk teslim edilecek ürünler için.',
 'loading_order', 'vehicle', 'sort_last', '#534AB7', TRUE,
 '{"loading_priority": 100, "position_preference": "front"}', 130),

('VEHICLE_FRONT', 'Araç Önüne Yerleştir', 'Place at Vehicle Front',
 'Bu palet araçta sürücü kabinine yakın bölgeye yerleştirilmeli.',
 'loading_order', 'vehicle', 'truck_front', '#3C3489', TRUE,
 '{"vehicle_zone": "front", "zone_ratio": 0.33}', 140),

('VEHICLE_REAR', 'Araç Arkasına Yerleştir', 'Place at Vehicle Rear',
 'Bu palet araçta kapıya yakın bölgeye yerleştirilmeli.',
 'loading_order', 'vehicle', 'truck_rear', '#3C3489', TRUE,
 '{"vehicle_zone": "rear", "zone_ratio": 0.33}', 150);

-- ============================================================
-- SEED — Sistem varsayılan uyumluluk kuralları
-- ============================================================

-- Soğuk zincir başka ürünlerle aynı araca giremez (hata seviyesi)
INSERT INTO constraint_compatibility_rules (
    constraint_a_id, constraint_b_id, rule_type, severity,
    description, is_active, is_system_default, is_symmetric
)
SELECT a.id, b.id,
    'cannot_share_vehicle',
    'error',
    'Soğuk zincir ürünler standart sıcaklıktaki ürünlerle aynı araçta taşınamaz.',
    TRUE, TRUE, TRUE
FROM constraint_definitions a
CROSS JOIN constraint_definitions b
WHERE a.code = 'COLD_CHAIN' AND b.code NOT IN ('COLD_CHAIN', 'TEMP_SENSITIVE')
  AND a.is_system_default = TRUE AND b.is_system_default = TRUE;

-- Tehlikeli madde hiçbir şeyle aynı araçta gidemez
INSERT INTO constraint_compatibility_rules (
    constraint_a_id, constraint_b_id, rule_type, severity,
    description, is_active, is_system_default, is_symmetric
)
SELECT a.id, b.id,
    'requires_isolation',
    'error',
    'Tehlikeli madde (Sınıf 1) diğer ürünlerden tamamen izole edilmelidir.',
    TRUE, TRUE, TRUE
FROM constraint_definitions a
CROSS JOIN constraint_definitions b
WHERE a.code = 'HAZMAT_CLASS_1' AND b.code != 'HAZMAT_CLASS_1'
  AND a.is_system_default = TRUE AND b.is_system_default = TRUE;

-- Üzerine yük konulamaz → ilk yükle çelişir (uyarı)
INSERT INTO constraint_compatibility_rules (
    constraint_a_id, constraint_b_id, rule_type, severity,
    description, is_active, is_system_default, is_symmetric
)
SELECT a.id, b.id,
    'must_be_above',
    'warning',
    'NO_STACK ürün, LOAD_FIRST ile birlikte kullanılırsa araç arkasında alt katmanda sorun çıkabilir.',
    TRUE, TRUE, FALSE
FROM constraint_definitions a
CROSS JOIN constraint_definitions b
WHERE a.code = 'NO_STACK' AND b.code = 'LOAD_FIRST'
  AND a.is_system_default = TRUE AND b.is_system_default = TRUE;

-- ============================================================
-- SEED — Parametre şemaları
-- ============================================================

INSERT INTO constraint_param_schemas (constraint_id, param_key, param_label, param_type, param_default, param_min, param_max, param_unit, is_required, sort_order)
SELECT id, 'max_weight_above_kg', 'Maksimum üst yük', 'number', '50', 0, 5000, 'kg', TRUE, 1
FROM constraint_definitions WHERE code = 'MAX_WEIGHT_ABOVE';

INSERT INTO constraint_param_schemas (constraint_id, param_key, param_label, param_type, param_default, param_min, param_max, param_unit, is_required, sort_order)
SELECT id, 'temp_min_c', 'Minimum sıcaklık', 'number', '0', -40, 60, '°C', TRUE, 1
FROM constraint_definitions WHERE code IN ('COLD_CHAIN', 'TEMP_SENSITIVE');

INSERT INTO constraint_param_schemas (constraint_id, param_key, param_label, param_type, param_default, param_min, param_max, param_unit, is_required, sort_order)
SELECT id, 'temp_max_c', 'Maksimum sıcaklık', 'number', '25', -40, 80, '°C', TRUE, 2
FROM constraint_definitions WHERE code IN ('COLD_CHAIN', 'TEMP_SENSITIVE');

-- Trigger
CREATE TRIGGER trg_constraint_definitions_updated
BEFORE UPDATE ON constraint_definitions
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
