-- ============================================================
-- Cronoi LS — PostgreSQL Schema v2.0
-- Target: Mobilya / Beyaz Eşya SaaS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- fuzzy search for product catalog

-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE subscription_plan AS ENUM ('free', 'starter', 'growth', 'enterprise');
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'operator', 'viewer');
CREATE TYPE pallet_type AS ENUM ('P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9', 'P10');
CREATE TYPE vehicle_type AS ENUM ('panelvan', 'kamyon', 'tir', 'konteyner20', 'konteyner40');
CREATE TYPE constraint_type AS ENUM ('fragile', 'heavy', 'temp');
CREATE TYPE shipment_status AS ENUM ('draft', 'optimizing', 'optimized', 'loading', 'loaded', 'delivered', 'cancelled');
CREATE TYPE scenario_strategy AS ENUM ('min_vehicles', 'balanced', 'max_efficiency');

-- ============================================================
-- COMPANIES (Tenant root — her şey buraya bağlı)
-- ============================================================

CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,           -- URL'de kullanılır: cronoi.app/acme
    plan            subscription_plan NOT NULL DEFAULT 'free',
    plan_expires_at TIMESTAMPTZ,
    monthly_quota   INT NOT NULL DEFAULT 5,         -- aylık max sevkiyat
    used_quota      INT NOT NULL DEFAULT 0,
    settings        JSONB NOT NULL DEFAULT '{}',    -- UI tercihleri, varsayılan palet tipi
    logo_url        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_slug ON companies(slug);

-- ============================================================
-- USERS
-- ============================================================

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    role            user_role NOT NULL DEFAULT 'operator',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_company ON users(company_id);
CREATE INDEX idx_users_email ON users(email);

-- Refresh token store
CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- PRODUCT CATALOG (şirkete özel ürün kütüphanesi)
-- Aynı koltuk takımını 100. kez girmek zorunda kalma
-- ============================================================

CREATE TABLE product_catalog (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    sku             TEXT,                           -- Müşterinin kendi ürün kodu
    name            TEXT NOT NULL,
    length_cm       NUMERIC(8,2) NOT NULL,
    width_cm        NUMERIC(8,2) NOT NULL,
    height_cm       NUMERIC(8,2) NOT NULL,
    weight_kg       NUMERIC(8,3) NOT NULL,
    constraint_type constraint_type,
    category        TEXT,                           -- "Oturma Grubu", "Yatak Odası" vb.
    image_url       TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    use_count       INT NOT NULL DEFAULT 0,         -- "En çok kullanılan" için
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_catalog_company ON product_catalog(company_id);
CREATE INDEX idx_catalog_name_trgm ON product_catalog USING gin(name gin_trgm_ops);
CREATE INDEX idx_catalog_sku ON product_catalog(company_id, sku) WHERE sku IS NOT NULL;

-- ============================================================
-- VEHICLE DEFINITIONS (şirkete özel araç filosu)
-- ============================================================

CREATE TABLE vehicle_definitions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,                  -- "Kendi TIR-1", "Anlaşmalı Nakliye Firma A"
    type            vehicle_type NOT NULL,
    length_cm       NUMERIC(8,2) NOT NULL,
    width_cm        NUMERIC(8,2) NOT NULL,
    height_cm       NUMERIC(8,2) NOT NULL,
    max_weight_kg   NUMERIC(10,2) NOT NULL,
    base_cost       NUMERIC(12,2) NOT NULL DEFAULT 0,   -- Araç başı sabit maliyet
    fuel_per_km     NUMERIC(8,2) NOT NULL DEFAULT 0,
    driver_per_hour NUMERIC(8,2) NOT NULL DEFAULT 0,
    opportunity_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vehicles_company ON vehicle_definitions(company_id);

-- ============================================================
-- SHIPMENTS (Ana iş birimi)
-- ============================================================

CREATE TABLE shipments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    created_by      UUID NOT NULL REFERENCES users(id),
    reference_no    TEXT NOT NULL,                  -- "SEV-2026-001"
    status          shipment_status NOT NULL DEFAULT 'draft',
    pallet_type     pallet_type NOT NULL DEFAULT 'P1',
    destination     TEXT,
    notes           TEXT,
    -- Optimizer sonuçları
    optimizer_version TEXT,                         -- hangi algoritma versiyonu
    optimization_duration_ms INT,                  -- ne kadar sürdü?
    -- Zaman damgaları
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    optimized_at    TIMESTAMPTZ,
    loaded_at       TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ                     -- soft delete
);

-- Auto-increment reference_no için sequence
CREATE SEQUENCE shipment_seq START 1;

CREATE INDEX idx_shipments_company ON shipments(company_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_shipments_status ON shipments(company_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_shipments_created ON shipments(company_id, created_at DESC);

-- ============================================================
-- SHIPMENT PRODUCTS (sevkiyattaki ürün listesi)
-- ============================================================

CREATE TABLE shipment_products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id     UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    catalog_id      UUID REFERENCES product_catalog(id) ON DELETE SET NULL,  -- katalogdan seçilmişse
    name            TEXT NOT NULL,
    quantity        INT NOT NULL CHECK (quantity > 0),
    length_cm       NUMERIC(8,2) NOT NULL,
    width_cm        NUMERIC(8,2) NOT NULL,
    height_cm       NUMERIC(8,2) NOT NULL,
    weight_kg       NUMERIC(8,3) NOT NULL,
    constraint_type constraint_type,
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_shipment_products_shipment ON shipment_products(shipment_id);

-- ============================================================
-- PALLETS (bin packing sonucu)
-- ============================================================

CREATE TABLE pallets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id     UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    pallet_number   INT NOT NULL,                   -- 1, 2, 3...
    pallet_type     pallet_type NOT NULL,
    total_weight_kg NUMERIC(10,3) NOT NULL,
    total_height_cm NUMERIC(8,2) NOT NULL,
    total_volume_m3 NUMERIC(10,4) NOT NULL,
    fill_rate_pct   NUMERIC(5,2) NOT NULL,          -- % doluluk
    constraints     constraint_type[] DEFAULT '{}', -- bu paletteki kısıtlar
    layout_data     JSONB,                          -- 3D pozisyon bilgileri (Three.js için)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(shipment_id, pallet_number)
);

CREATE INDEX idx_pallets_shipment ON pallets(shipment_id);

-- ============================================================
-- PALLET PRODUCTS (hangi ürün hangi palette)
-- ============================================================

CREATE TABLE pallet_products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pallet_id       UUID NOT NULL REFERENCES pallets(id) ON DELETE CASCADE,
    shipment_product_id UUID REFERENCES shipment_products(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    quantity        INT NOT NULL CHECK (quantity > 0),
    length_cm       NUMERIC(8,2) NOT NULL,
    width_cm        NUMERIC(8,2) NOT NULL,
    height_cm       NUMERIC(8,2) NOT NULL,
    weight_kg       NUMERIC(8,3) NOT NULL,
    constraint_type constraint_type,
    -- 3D yerleşim bilgisi (her ürün parçası için)
    position_x      NUMERIC(8,3),
    position_y      NUMERIC(8,3),
    position_z      NUMERIC(8,3),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pallet_products_pallet ON pallet_products(pallet_id);

-- ============================================================
-- SCENARIOS (senaryo karşılaştırma sonuçları)
-- ============================================================

CREATE TABLE scenarios (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id         UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,              -- "Minimum Araç", "Dengeli", "Max Verim"
    strategy            scenario_strategy NOT NULL,
    total_cost          NUMERIC(14,2) NOT NULL,
    cost_per_pallet     NUMERIC(12,2) NOT NULL,
    total_vehicles      INT NOT NULL,
    avg_fill_rate_pct   NUMERIC(5,2) NOT NULL,
    vehicle_assignments JSONB NOT NULL,             -- [{vehicle_id, pallet_ids, cost}]
    is_selected         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scenarios_shipment ON scenarios(shipment_id);
CREATE INDEX idx_scenarios_selected ON scenarios(shipment_id) WHERE is_selected = TRUE;

-- ============================================================
-- LOADING PLANS (yükleme sırası ve ağırlık dengesi)
-- ============================================================

CREATE TABLE loading_plans (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    shipment_id         UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    scenario_id         UUID REFERENCES scenarios(id) ON DELETE SET NULL,
    is_balanced         BOOLEAN NOT NULL DEFAULT FALSE,
    front_rear_diff_pct NUMERIC(5,2),
    left_right_diff_pct NUMERIC(5,2),
    total_pallets       INT NOT NULL,
    total_weight_kg     NUMERIC(12,3) NOT NULL,
    estimated_time_min  INT,
    qr_token            TEXT UNIQUE,                -- depo ekibi için güvenli URL
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE loading_plan_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id         UUID NOT NULL REFERENCES loading_plans(id) ON DELETE CASCADE,
    pallet_id       UUID NOT NULL REFERENCES pallets(id) ON DELETE CASCADE,
    load_order      INT NOT NULL,                   -- 1, 2, 3 (önce yükle)
    position_label  TEXT NOT NULL,                  -- "Ön Sol", "Arka Sağ"
    position_x      NUMERIC(8,3),
    position_y      NUMERIC(8,3),
    position_z      NUMERIC(8,3),
    is_loaded       BOOLEAN NOT NULL DEFAULT FALSE, -- depo işaretledi mi?
    loaded_at       TIMESTAMPTZ,
    loaded_by       UUID REFERENCES users(id),
    notes           TEXT
);

CREATE INDEX idx_plan_items_plan ON loading_plan_items(plan_id);
CREATE INDEX idx_plan_items_order ON loading_plan_items(plan_id, load_order);

-- ============================================================
-- AUDIT LOGS (kim ne zaman ne yaptı)
-- ============================================================

CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,                      -- "shipment.created", "pallet.optimized"
    entity_type TEXT NOT NULL,                      -- "shipment", "pallet", "scenario"
    entity_id   UUID,
    meta        JSONB DEFAULT '{}',                 -- ek bilgiler
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_company ON audit_logs(company_id, created_at DESC);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);

-- ============================================================
-- ANALYTICS SNAPSHOTS (aylık maliyet dashboard için)
-- Her gün gece Celery job tarafından doldurulur
-- ============================================================

CREATE TABLE monthly_stats (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id          UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    period_year         INT NOT NULL,
    period_month        INT NOT NULL,
    total_shipments     INT NOT NULL DEFAULT 0,
    total_pallets       INT NOT NULL DEFAULT 0,
    total_cost          NUMERIC(16,2) NOT NULL DEFAULT 0,
    avg_fill_rate_pct   NUMERIC(5,2),
    avg_cost_per_pallet NUMERIC(12,2),
    total_weight_kg     NUMERIC(16,3),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(company_id, period_year, period_month)
);

-- ============================================================
-- HELPER FUNCTIONS
-- ============================================================

-- updated_at otomatik güncelleme trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger'ları ekle
CREATE TRIGGER trg_companies_updated BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_shipments_updated BEFORE UPDATE ON shipments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_loading_plans_updated BEFORE UPDATE ON loading_plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_catalog_updated BEFORE UPDATE ON product_catalog
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_vehicles_updated BEFORE UPDATE ON vehicle_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Shipment reference_no otomatik üret
CREATE OR REPLACE FUNCTION generate_reference_no()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.reference_no IS NULL OR NEW.reference_no = '' THEN
        NEW.reference_no = 'SEV-' || TO_CHAR(NOW(), 'YYYY') || '-' ||
                          LPAD(nextval('shipment_seq')::TEXT, 4, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_shipment_ref BEFORE INSERT ON shipments
    FOR EACH ROW EXECUTE FUNCTION generate_reference_no();

-- Katalog kullanım sayacı
CREATE OR REPLACE FUNCTION increment_catalog_use()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.catalog_id IS NOT NULL THEN
        UPDATE product_catalog
        SET use_count = use_count + NEW.quantity
        WHERE id = NEW.catalog_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_catalog_use AFTER INSERT ON shipment_products
    FOR EACH ROW EXECUTE FUNCTION increment_catalog_use();
