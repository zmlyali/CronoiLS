-- Konsolidasyon/Tasarruf No: birlikte planlanan siparişleri gruplar
ALTER TABLE orders ADD COLUMN IF NOT EXISTS consolidation_no VARCHAR(40);
