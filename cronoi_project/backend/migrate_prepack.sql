-- Cronoi LS — Pre-Pack Sipariş Sistemi Migrasyonu
-- Çalıştır: psql -U <user> -d <db> -f migrate_prepack.sql
-- Geri al:  migrate_prepack_rollback.sql

-- ── 1. orders tablosuna order_type kolonu ──────────────────────────────
ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS order_type VARCHAR(20) NOT NULL DEFAULT 'standard';

COMMENT ON COLUMN orders.order_type IS
    'standard = ürün bazlı (optimizer palet oluşturur) | prepack = müşteri paletleri hazır';

-- ── 2. order_pallet_groups — palet tanım grupları ──────────────────────
-- Her satır: bir palet tipi (boyut + ağırlık) ve kaç adet olduğu
CREATE TABLE IF NOT EXISTS order_pallet_groups (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      UUID         NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    pallet_code   VARCHAR(50)  NOT NULL,       -- Excel'deki PALET_ID (P001, P002 ...)
    name          VARCHAR(200),                -- opsiyonel açıklama
    width_cm      FLOAT        NOT NULL,
    length_cm     FLOAT        NOT NULL,
    height_cm     FLOAT        NOT NULL,
    weight_kg     FLOAT        NOT NULL,       -- palet başına ağırlık (zorunlu)
    pallet_count  INTEGER      NOT NULL DEFAULT 1,
    sort_order    INTEGER      NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opg_order_id ON order_pallet_groups(order_id);

COMMENT ON TABLE order_pallet_groups IS
    'Pre-pack siparişlerinde müşteri tarafından tanımlanmış palet grupları';

-- ── 3. order_pallet_items — her palet grubundaki ürünler ───────────────
CREATE TABLE IF NOT EXISTS order_pallet_items (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    pallet_group_id       UUID         NOT NULL REFERENCES order_pallet_groups(id) ON DELETE CASCADE,
    product_code          VARCHAR(100),          -- SKU / ürün kodu (opsiyonel)
    description           VARCHAR(300) NOT NULL, -- ürün açıklaması
    quantity_per_pallet   INTEGER      NOT NULL, -- her bir paletteki adet
    total_quantity        INTEGER,               -- qty_per_pallet × pallet_count (bilgi amaçlı)
    sort_order            INTEGER      NOT NULL DEFAULT 0,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opi_group_id ON order_pallet_items(pallet_group_id);

COMMENT ON TABLE order_pallet_items IS
    'Pre-pack palet grubu içindeki ürün dökümü';

-- ── Doğrulama sorgusu ──────────────────────────────────────────────────
-- Başarılı migration sonrası şu tabloların var olduğunu kontrol et:
-- SELECT table_name FROM information_schema.tables
-- WHERE table_name IN ('order_pallet_groups','order_pallet_items');
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name='orders' AND column_name='order_type';
