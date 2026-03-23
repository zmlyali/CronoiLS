# Cronoi LS — Sprint 1 Plan
**Hedef:** Backend API + DB kurulumu, veri kaybı sorunu çözülüyor  
**Süre:** 2 hafta  
**Öncelik:** P0 — Temel altyapı

---

## Sprint 1 Görevleri

### Hafta 1: Foundation

#### Gün 1-2: Proje kurulumu
- [ ] FastAPI proje skeleton (`app/main.py`, config, router yapısı)
- [ ] Docker Compose: PostgreSQL 16 + Redis + API + Worker
- [ ] `.env.example` dosyası (tüm environment variables)
- [ ] `schema.sql` çalıştır, tabloları doğrula
- [ ] Alembic migrations kurulumu (ilk migration: initial schema)
- [ ] `GET /api/health` → `{"status": "ok"}` çalışsın

#### Gün 3-4: Auth API
- [ ] `POST /api/v1/auth/register` — şirket + kullanıcı oluştur
- [ ] `POST /api/v1/auth/login` — JWT access + refresh token
- [ ] `POST /api/v1/auth/refresh` — token yenile
- [ ] `POST /api/v1/auth/logout` — refresh token iptal
- [ ] `GET /api/v1/auth/me` — mevcut kullanıcı bilgisi
- [ ] JWT middleware — her endpoint'e company_id inject

#### Gün 5: Shipment CRUD
- [ ] `POST /api/v1/shipments` — sevkiyat + ürün listesi kaydet
- [ ] `GET /api/v1/shipments` — şirketin sevkiyat listesi (sayfalı)
- [ ] `GET /api/v1/shipments/{id}` — detay (ürünler dahil)
- [ ] `DELETE /api/v1/shipments/{id}` — soft delete

### Hafta 2: Optimizer + Integration

#### Gün 6-7: Bin Packing API
- [ ] `POST /api/v1/shipments/{id}/optimize` — Celery task başlat
- [ ] `GET /api/v1/shipments/{id}/status` — polling endpoint
- [ ] Celery worker: `BinPackingOptimizer3D` çalıştır
- [ ] Palet sonuçlarını `pallets` + `pallet_products` tablosuna kaydet
- [ ] `GET /api/v1/shipments/{id}/pallets` — palet listesi

#### Gün 8-9: Scenario + Loading Plan API
- [ ] `POST /api/v1/scenarios/generate` — 3 senaryo oluştur
- [ ] `GET /api/v1/scenarios?shipment_id=X` — senaryoları listele
- [ ] `POST /api/v1/scenarios/{id}/select` — senaryo seç
- [ ] `POST /api/v1/loading-plans` — yükleme planı oluştur
- [ ] `GET /api/v1/loading-plans/{id}` — detay
- [ ] `GET /api/v1/loading-plans/{id}/qr` — QR kod URL

#### Gün 10: Test + Bağlantı
- [ ] Postman collection hazırla (tüm endpointler)
- [ ] Mevcut HTML'i API'ye bağla (fetch çağrıları ekle)
- [ ] `processProducts()` → `POST /api/v1/shipments` çağrısına dönüştür
- [ ] `autoOptimize()` → `POST /api/v1/shipments/{id}/optimize`
- [ ] Palet listesi → API'den çek
- [ ] Integration testler (pytest)

---

## API Endpoint Özeti (Sprint 1 sonu)

```
AUTH
  POST   /api/v1/auth/register
  POST   /api/v1/auth/login
  POST   /api/v1/auth/refresh
  GET    /api/v1/auth/me

SHIPMENTS
  POST   /api/v1/shipments
  GET    /api/v1/shipments
  GET    /api/v1/shipments/{id}
  DELETE /api/v1/shipments/{id}
  POST   /api/v1/shipments/{id}/optimize
  GET    /api/v1/shipments/{id}/status
  GET    /api/v1/shipments/{id}/pallets

SCENARIOS
  POST   /api/v1/scenarios/generate
  GET    /api/v1/scenarios?shipment_id=X
  POST   /api/v1/scenarios/{id}/select

LOADING PLANS
  POST   /api/v1/loading-plans
  GET    /api/v1/loading-plans/{id}
  GET    /api/v1/loading-plans/{id}/qr

HEALTH
  GET    /api/health
```

---

## Definition of Done (Sprint 1)

- [ ] Docker Compose ile `docker-compose up` tek komutla çalışıyor
- [ ] Tüm P0 endpointler Postman'da test edildi
- [ ] Şu anki HTML'deki "Paletleri Hesapla" butonu API'yi çağırıyor
- [ ] Optimizasyon sonucu DB'de kalıcı
- [ ] Sayfa yenilendiğinde son sevkiyat geri geliyor
- [ ] README.md ile kurulum talimatı hazır

---

## Sprint 2 Preview (Auth + Frontend)

- React + Vite kurulumu
- Login/Register ekranları
- Şirket dashboard (sevkiyat listesi)
- Ürün kataloğu CRUD UI
- Araç filosu yönetimi UI
- Rol bazlı yetkilendirme
