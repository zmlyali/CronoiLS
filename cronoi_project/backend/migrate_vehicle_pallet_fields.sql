-- Migration: allowed_vehicle_types per order + pallet_type per order item
-- Run once against the live DB:
--   psql $DATABASE_URL -f migrate_vehicle_pallet_fields.sql

ALTER TABLE orders      ADD COLUMN IF NOT EXISTS allowed_vehicle_types JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS pallet_type TEXT;
