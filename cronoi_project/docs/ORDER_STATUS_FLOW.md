# Sipariş Statü Akışı — Cronoi LS

## Statü Tanımları

| Statü | Kod | Emoji | Açıklama |
|-------|-----|-------|----------|
| Bekliyor | `pending` | ⏳ | Sipariş sisteme girildi, henüz sevkiyata atanmadı |
| Sevkiyat Planında | `in_shipment` | 📋 | Sipariş bir sevkiyat grubuna eklendi |
| Palet Planı Hazır | `pallet_planned` | 📦 | Palet optimizasyonu tamamlandı ve onaylandı |
| Araç Planı Hazır | `vehicle_planned` | 🚛 | Araç yükleme planı onaylandı |
| Yüklendi | `loaded` | ✅ | Sevkiyat tamamlandı, araçlara yüklendi |
| Teslim Edildi | `delivered` | 🏁 | Müşteriye teslim edildi |

## Kullanıcı Akışı & Statü Geçişleri

```
pending ──→ in_shipment ──→ pallet_planned ──→ vehicle_planned ──→ loaded ──→ delivered
   │             │                │                   │               │
   └─ İptal ─────┴────────────────┴───────────────────┘               │
                                                                       └─ (Son durum)
```

### Adım 1: Sipariş Seçimi
- Kullanıcı siparişler ekranından siparişleri seçer
- "Sevkiyat Planına Ekle" butonuna tıklar
- **Statü:** `pending` → `in_shipment`

### Adım 2: Palet Optimizasyonu
- "Paletleri Hesapla" ile optimizer çalıştırılır
- Kullanıcı ister ise paletleri manuel düzenler
- **"Paleti Onayla & Devam Et"** butonuna tıklanır
- Palet verileri API'ye kaydedilir (`POST /shipments/{id}/pallets`)
- **Statü:** `in_shipment` → `pallet_planned`
- Sevkiyat durumu: `draft` → `plan_confirmed`

### Adım 3-4: Araç Optimizasyonu & Senaryo Seçimi
- Araç yükleme senaryoları oluşturulur
- En iyi senaryo seçilir
- **"Araç Planını Onayla"** butonuna tıklanır
- Seçilen senaryo API'ye kaydedilir
- **Statü:** `pallet_planned` → `vehicle_planned`
- Sevkiyat durumu: `plan_confirmed` → `loading`

### Adım 5-6: Tamamlama
- Yükleme detayları girilir (tarih, notlar)
- **"Sevkiyatı Tamamla"** butonuna tıklanır
- **Statü:** `vehicle_planned` → `loaded`
- Sevkiyat durumu: `loading` → `loaded`
- Referans numarası kesinleşir

## Backend Validasyonu

Geçerli geçişler (`ORDER_TRANSITIONS`):

| Mevcut Statü | İzin Verilen Geçişler |
|-------------|----------------------|
| `pending` | `in_shipment`, `pallet_planned`, `vehicle_planned`, `cancelled` |
| `in_shipment` | `pallet_planned`, `vehicle_planned`, `pending`, `cancelled` |
| `pallet_planned` | `vehicle_planned`, `pending`, `cancelled` |
| `vehicle_planned` | `loaded`, `pending`, `cancelled` |
| `loaded` | `delivered` |
| `delivered` | — (son durum) |

## API Endpoint'leri

- `PATCH /api/v1/orders/{order_id}/status` — `{ "status": "yeni_statü" }`
- `PATCH /api/v1/shipments/{id}/status` — sevkiyat durumu güncelleme
- `POST /api/v1/shipments/{id}/complete` — sevkiyatı tamamla + siparişleri kapat

## Rank Sistemi (Frontend)

Statü geri alınmasını önlemek için rank kontrolü yapılır:

| Rank | Statüler |
|------|----------|
| 0 | `cancelled` |
| 1 | `pending`, `in_suggestion` |
| 2 | `in_shipment`, `planned` |
| 3 | `pallet_planned`, `load_planned` |
| 4 | `vehicle_planned` |
| 5 | `loaded`, `in_transit` |
| 6 | `delivered` |

Her onay adımında `_getOrderStageRank(currentStatus) < targetRank` kontrolü yapılır,
böylece zaten ileri bir statüdeki siparişler geri alınmaz.
