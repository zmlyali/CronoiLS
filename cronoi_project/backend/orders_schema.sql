-- ============================================================
-- ORDERS (Üretimden gelen siparişler)
-- ============================================================

CREATE TABLE IF NOT EXISTS orders (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    created_by      UUID NOT NULL REFERENCES users(id),

    -- Sipariş kimliği
    order_no        VARCHAR(50) NOT NULL,          -- Üretim sipariş no
    project_code    VARCHAR(50),                   -- Proje kodu
    
    -- Alıcı bilgileri
    customer_name   VARCHAR(200) NOT NULL,
    address         TEXT,
    city            VARCHAR(100),
    postal_code     VARCHAR(20),
    country         VARCHAR(100) DEFAULT 'TR',
    contact_name    VARCHAR(200),
    contact_phone   VARCHAR(50),
    contact_email   VARCHAR(200),

    -- Tarihler
    order_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    requested_ship_date DATE,                      -- İstenen yükleme tarihi
    deadline_date   DATE,                          -- Teslim son tarihi

    -- Durum
    status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    -- pending: bekliyor
    -- planned: sevkiyata eklendi
    -- shipped: yüklendi
    -- delivered: teslim edildi
    -- cancelled: iptal

    notes           TEXT,
    priority        INT NOT NULL DEFAULT 3,        -- 1=acil, 5=normal

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_orders_company ON orders(company_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(company_id, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_orders_ship_date ON orders(company_id, requested_ship_date) WHERE deleted_at IS NULL;

-- ============================================================
-- ORDER ITEMS (Siparişin ürün kalemleri)
-- ============================================================

CREATE TABLE IF NOT EXISTS order_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    catalog_id      UUID REFERENCES product_catalog(id) ON DELETE SET NULL,

    name            VARCHAR(200) NOT NULL,
    sku             VARCHAR(100),
    quantity        INT NOT NULL CHECK (quantity > 0),
    length_cm       NUMERIC(8,2) NOT NULL,
    width_cm        NUMERIC(8,2) NOT NULL,
    height_cm       NUMERIC(8,2) NOT NULL,
    weight_kg       NUMERIC(8,3) NOT NULL,
    constraints     JSONB NOT NULL DEFAULT '[]',
    sort_order      INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

-- ============================================================
-- ORDER <-> SHIPMENT bağlantısı
-- ============================================================

CREATE TABLE IF NOT EXISTS order_shipments (
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    shipment_id     UUID NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (order_id, shipment_id)
);

-- ============================================================
-- shipments tablosuna order referansı ekle
-- ============================================================
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS order_id UUID REFERENCES orders(id) ON DELETE SET NULL;

-- ============================================================
-- Yetkiler
-- ============================================================
GRANT ALL PRIVILEGES ON TABLE orders TO cronoi_user;
GRANT ALL PRIVILEGES ON TABLE order_items TO cronoi_user;
GRANT ALL PRIVILEGES ON TABLE order_shipments TO cronoi_user;
