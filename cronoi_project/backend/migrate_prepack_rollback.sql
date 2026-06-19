-- Cronoi LS — Pre-Pack Migrasyonu GERİ ALMA
-- DİKKAT: Veri kaybına neden olur. Sadece geliştirme ortamında kullan.

DROP TABLE IF EXISTS order_pallet_items   CASCADE;
DROP TABLE IF EXISTS order_pallet_groups  CASCADE;
ALTER TABLE orders DROP COLUMN IF EXISTS order_type;
