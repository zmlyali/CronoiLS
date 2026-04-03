# Cronoi LS v2.0 — Proje Kapsamı

## 1. Proje Özeti

**Cronoi LS**, mobilya ve beyaz eşya üreticileri için geliştirilmiş bir **B2B SaaS lojistik optimizasyon platformudur**. Manuel sevkiyat hesaplamalarını otomatikleştirerek, 3D bin packing algoritması ile palet yükleme optimizasyonu sağlar.

| Bilgi | Detay |
|---|---|
| **Hedef Pazar** | 50–500 çalışanlı mobilya/beyaz eşya üreticileri |
| **İş Modeli** | Freemium + Abonelik (299–2.499 ₺/ay) |
| **Mevcut Sürüm** | v2.0 (SaaS mimarisine geçiş) |
| **Çözdüğü Sorunlar** | Manuel sevkiyat hesabı, %20-35 boş araç kapasitesi, kırılgan ürün hasarı, maliyet belirsizliği |
| **Hedef KPI'lar** | %60 hafta-4 retention, >40 NPS, 50K MRR (6. ay), LTV:CAC >3x |

---

## 2. Mimari Yapı

```
Frontend (Tek Sayfa Uygulama — HTML/CSS/JS)
├── Cronoi_LS_v2.html (6 adımlı workflow)
├── Three.js (3D görselleştirme)
├── Chart.js (senaryo karşılaştırma)
└── SheetJS (Excel import/export)

Backend (FastAPI + PostgreSQL)
├── API Katmanı (REST endpoints — /api/v1/)
│   ├── shipments (Sevkiyat CRUD + Optimizasyon)
│   ├── orders (Sipariş yönetimi)
│   ├── scenarios (Senaryo üretimi)
│   └── constraints (Kısıt havuzu)
├── Servisler
│   ├── optimizer.py (3D Bin Packing — FFD-C algoritması)
│   └── constraint_engine.py (Kısıt değerlendirme motoru)
├── Veritabanı (SQLAlchemy ORM — async)
└── Celery Worker (Asenkron optimizasyon görevleri)

Altyapı (Docker Compose)
├── PostgreSQL 16 (veri kalıcılığı)
├── Redis 7 (cache + Celery broker)
├── FastAPI (Uvicorn — port 8000)
└── Celery Worker
```

---

## 3. Teknoloji Yığını

| Katman | Teknoloji | Sürüm | Amaç |
|--------|-----------|-------|------|
| Frontend | HTML5 + CSS3 + JavaScript | ES2020 | Monolitik SPA |
| 3D Grafik | Three.js | v150 | WebGL TIR/palet görselleştirme |
| Grafik | Chart.js | v3 | Radar chart karşılaştırma |
| Excel | SheetJS (XLSX) | v1.21 | Import/export |
| Backend | FastAPI | v0.115 | REST API + otomatik OpenAPI docs |
| Web Sunucu | Uvicorn | v0.30 | ASGI sunucu |
| Veritabanı | PostgreSQL | v16 | Kalıcı veri + JSONB |
| ORM | SQLAlchemy | v2.0 | Async ORM |
| DB Driver | asyncpg | v0.29 | Async PostgreSQL |
| Auth | python-jose + bcrypt | — | JWT + şifre hash |
| Optimizer | Google OR-Tools | v9.10 | 3D bin packing (planlanıyor) |
| Görev Kuyruğu | Celery | v5.4 | Asenkron görevler |
| Cache/Broker | Redis | v7 | Celery broker + cache |
| Konteyner | Docker Compose | v3.9 | Yerel orkestrasyon |
| Python | Python | v3.12 | Backend runtime |

---

## 4. Veritabanı Şeması

### 4.1 Ana Şema (`schema.sql` — 10 tablo)

| Tablo | Amaç | Önemli Sütunlar |
|-------|------|-----------------|
| **companies** | Multi-tenant kök tablo | name, slug, plan (free/starter/growth/enterprise), monthly_quota, settings (JSONB) |
| **users** | Kullanıcı yönetimi | email, password_hash, role (owner/admin/operator/viewer), is_active |
| **refresh_tokens** | JWT yenileme | token_hash, expires_at |
| **product_catalog** | Şirket bazlı ürün kütüphanesi | sku, name, boyutlar (L/W/H), weight_kg, constraint_type, use_count |
| **vehicle_definitions** | Şirket bazlı araç filosu | type (panelvan/kamyon/tir/konteyner), boyutlar, max_weight, maliyet parametreleri |
| **shipments** | Ana iş akışı varlığı | reference_no, status (draft→optimizing→optimized→loading→loaded→delivered), pallet_type |
| **shipment_products** | Sevkiyat ürünleri | quantity, boyutlar, weight_kg, constraint_type |
| **pallets** | Bin packing çıktısı | pallet_number, fill_rate_pct, layout_data (JSONB — 3D pozisyon) |
| **pallet_products** | Palet içi ürünler | pos_x, pos_y, pos_z (3D koordinat) |
| **scenarios** | Optimizasyon senaryoları | strategy (min_vehicles/balanced/max_efficiency), total_cost, vehicle_assignments (JSONB) |

### 4.2 Kısıt Şeması (`constraint_schema.sql` — 5 tablo + seed data)

| Tablo | Amaç |
|-------|------|
| **constraint_definitions** | Sistem + şirkete özel kısıt tanımları (15 sistem kısıtı seed) |
| **constraint_param_schemas** | Parametrelendirme (min/max, tip, varsayılan) |
| **constraint_compatibility_rules** | Çakışma matrisi (ör: COLD_CHAIN + HAZMAT → paylaşılamaz) |
| **product_constraint_assignments** | Ürüne kısıt atama |
| **constraint_violations** | Denetim izi (ihlaller) |

**15 Sistem Kısıtı:**
- **Oryantasyon:** HORIZONTAL_ONLY, VERTICAL_ONLY, THIS_SIDE_UP
- **Yığılabilirlik:** NO_STACK, MAX_WEIGHT_ABOVE, MUST_BE_BOTTOM, MUST_BE_TOP
- **Ortam:** COLD_CHAIN (2-8°C), TEMP_SENSITIVE, KEEP_DRY, HAZMAT_CLASS_1
- **Yükleme Sırası:** LOAD_FIRST, LOAD_LAST, VEHICLE_FRONT, VEHICLE_REAR

### 4.3 Sipariş Şeması (`orders_schema.sql` — 3 tablo)

| Tablo | Amaç |
|-------|------|
| **orders** | Üretim siparişleri (müşteri bilgileri, tarihler, durum) |
| **order_items** | Sipariş kalemleri (ürün bilgileri, boyutlar) |
| **order_shipments** | Sipariş ↔ Sevkiyat eşleme (N:N) |

---

## 5. API Endpointleri

### 5.1 Sevkiyat (`/api/v1/shipments`)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/shipments` | Yeni sevkiyat oluştur (ürünler dahil) |
| `GET` | `/shipments?limit=20&offset=0` | Sevkiyat listesi (pagination, soft delete filtreli) |
| `GET` | `/shipments/{id}` | Sevkiyat detayı (ürünler + paletler) |
| `DELETE` | `/shipments/{id}` | Soft delete |
| `POST` | `/shipments/{id}/optimize` | Optimizasyon başlat (Celery task) |
| `GET` | `/shipments/{id}/status` | Optimizasyon durumu polling (progress %) |
| `GET` | `/shipments/{id}/pallets` | Paletleme sonuçları |

### 5.2 Siparişler (`/api/v1/orders`)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/orders` | Yeni sipariş oluştur |
| `GET` | `/orders?status=&city=&week=` | Filtrelenmiş sipariş listesi |
| `POST` | `/orders/group-suggestions` | Şehir + hafta bazlı gruplama önerileri |
| `POST` | `/orders/bulk` | Excel'den toplu import |
| `PATCH` | `/orders/{id}/status` | Durum güncelleme |

### 5.3 Senaryolar (`/api/v1/scenarios`)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/scenarios/generate` | 3 strateji ile senaryo üret |
| `GET` | `/scenarios/{shipment_id}` | Sevkiyata ait senaryolar |

**3 Strateji:**
1. **min_vehicles** — En az araç (yoğun yükleme)
2. **balanced** — Dengeli dağılım
3. **max_efficiency** — Tüm araçlara eşit dağılım

### 5.4 Kısıtlar (`/api/v1/constraints`)

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/constraints` | Kısıt listesi (kategori, kapsam filtresi) |
| `POST` | `/constraints` | Şirkete özel kısıt oluştur |
| `GET` | `/constraints/compatibility` | Uyumluluk matrisi |
| `POST` | `/constraints/compatibility` | Çakışma kuralı oluştur |
| `POST` | `/constraints/validate` | Kısıt kombinasyonu doğrula |

### 5.5 Diğer

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/api/health` | Sağlık kontrolü (`{"status": "ok", "version": "2.0.0"}`) |

---

## 6. Frontend — 6 Adımlı İş Akışı

Cronoi_LS_v2.html dosyası (~3000+ satır) monolitik bir SPA olarak çalışır.

### Adım 1: Ürün Giriş
- Manuel ürün tablosu (ad, adet, boyutlar, ağırlık)
- Excel import/export (SheetJS)
- Kısıt seçici modal (çoklu seçim)
- Ürün kataloğundan seçim

### Adım 2: Paletleme
- Bin packing sonuçları (accordion kartlar)
- Three.js 3D palet görünümü
- Palet tipi seçimi: Euro (80×120), Standard (100×120), TIR (120×120)
- Doluluk oranı, ağırlık, hacim göstergeleri

### Adım 3: Araç Seçimi
- 5 araç tipi: Panelvan, Kamyon, TIR, 20ft Konteyner, 40ft Konteyner
- Düzenlenebilir maliyet parametreleri (baz, yakıt/km, sürücü/saat, fırsat maliyeti)
- Ağırlık/hacim doluluk göstergeleri
- Otomatik atama

### Adım 4: Senaryo Analizi
- 3 strateji karşılaştırması
- Radar chart + tablo görünümü
- Önerilen senaryo vurgulanır (yeşil)
- Maliyet/palet, toplam maliyet, doluluk oranı metrikleri

### Adım 5: TIR Planı (3D Yükleme Görünümü)
- **Three.js prosedürel 3D TIR modeli:**
  - TIR boyutları: 1360cm × 245cm × 270cm (standart Avrupa)
  - Kabin: ön cam, aynalar, kapılar, tampon, farlar
  - Tekerlekler: 3 dingil (direksiyon + çift arka)
  - Kargo alanı: ahşap zemin + ray kılavuzları
- **Etkileşim:** Sürükle-döndür, fare tekerleği zoom, palet tıkla/hover
- **Görünüm modları:** Perspektif, kuş bakışı, iç mekan, dış mekan
- **Palet renk kodlaması:** Sarı=kırılgan, Gri=ağır, Mavi=soğuk, Kırmızı=tehlikeli
- **Yükleme sırası:** Kısıt önceliği + ağırlık bazlı sıralama
- **Ağırlık dengesi analizi:** Ön/arka, sol/sağ % dağılımı

### Adım 6: Tamamlama
- Özet rapor (referans no, tarih, araç listesi)
- Fotoğraf çekimi/yükleme
- Tamamlama notları
- "Yüklendi Olarak İşaretle" butonu
- Kutlama animasyonu (konfeti)

### Ek Sayfalar
- **Dashboard:** KPI kartları, bekleyen siparişler, son sevkiyatlar
- **Siparişler:** Filtrelenebilir liste, toplu işlemler, gruplama paneli
- **Geçmiş:** Tamamlanmış sevkiyat arşivi + fotoğraf galerisi

---

## 7. Servisler (İş Mantığı)

### 7.1 Optimizer (`optimizer.py`)

**Algoritma:** First-Fit Decreasing with Constraints (FFD-C)

**İşlem Akışı:**
1. Ürünleri genişlet (10 adet → 10 ayrı item)
2. Akıllı sıralama: kısıt önceliği (ağır → normal → kırılgan), hacim, ağırlık
3. First-fit yerleştirme: mevcut paletlere sığdır
4. Yeni palet oluştur (sığmazsa)
5. Kısıt kontrolü: FRAGILE + HEAVY birlikte olamaz, COLD izole edilir
6. 3D pozisyon hesaplama (Three.js görselleştirme için)

**Kurallar:**
- Max ağırlık/palet
- Max yükseklik (genellikle 180 cm)
- Alan kontrolü (palet alanı × 1.15)
- 90° rotasyon denemesi
- Kısıt uyumluluğu kontrolü

**Senaryo Optimizer:**
- Paletleri araçlara stratejiye göre atar
- Maliyet hesabı: baz + yakıt×mesafe + sürücü×saat + fırsat maliyeti

### 7.2 Constraint Engine (`constraint_engine.py`)

**Karar Mantığı:**
1. Oryantasyon kuralları kontrolü
2. Yığılabilirlik değerlendirmesi
3. Uyumluluk matrisi kontrolü (çakışmalar)
4. Katman çakışmaları (MUST_BE_BOTTOM + MUST_BE_TOP → imkansız)
5. İhlalleri topla (error / warning)
6. `PlacementDecision(allowed, violations, warnings)` döndür

**Kabiliyetler:**
- `can_place_on_pallet(item, pallet_items)` → Palete yerleştirilebilir mi?
- `can_place_in_vehicle(pallet_constraints, vehicle_constraints)` → Araca yüklenebilir mi?
- `get_loading_priority(constraint_codes)` → Yükleme önceliği (1-100)
- `get_vehicle_zone(constraint_codes)` → Araç bölgesi (ön/arka/orta)
- `get_orientation(constraints)` → Oryantasyon kuralları

---

## 8. Kimlik Doğrulama ve Yetkilendirme

| Bileşen | Detay |
|---------|-------|
| Şifre Hash | bcrypt (CryptContext) |
| Token | JWT (python-jose) |
| Access Token | 60 dakika |
| Refresh Token | 30 gün |
| Roller | owner, admin, operator, viewer |
| Multi-tenant | company_id bazlı izolasyon |

---

## 9. Fiyatlandırma Modeli

| Plan | Fiyat (₺/ay) | Sevkiyat Limiti | Özellikler |
|------|---------------|-----------------|------------|
| **Starter** | 299 | 50 | Temel optimizasyon |
| **Growth** | 899 | 200 | Gelişmiş senaryolar |
| **Enterprise** | 2.499 | Sınırsız | Tam özellik seti |

---

## 10. Mevcut Durum ve Yol Haritası

### Tamamlanan (V1.1 + V2.0 Kısmen)

| Özellik | Durum |
|---------|-------|
| 6 adımlı workflow UI | ✅ Çalışıyor |
| Manuel ürün girişi | ✅ |
| Excel import/export | ✅ Frontend |
| JS bin packing (local fallback) | ✅ |
| 3D palet görünümü | ✅ |
| 3 senaryo üretimi | ✅ |
| Senaryo karşılaştırma | ✅ |
| 3D TIR görünümü (prosedürel) | ✅ |
| Yükleme sırası + ağırlık dengesi | ✅ |
| Veritabanı şemaları | ✅ |
| ORM modelleri | ✅ |
| Config + DB bağlantısı | ✅ |
| Auth altyapısı (JWT + bcrypt) | ✅ |
| Kısıt havuzu (DB + API) | ✅ |
| Sipariş yönetimi API | ✅ |
| Senaryo API | ✅ |
| Docker Compose | ✅ |
| Mock sunucu | ✅ |

### Devam Eden (Sprint 1)

| Özellik | Durum |
|---------|-------|
| Sevkiyat CRUD API | ⏳ ~%70 |
| Sipariş API | ⏳ ~%70 |
| Backend bin packing entegrasyonu | ⏳ Mock çalışıyor |
| Frontend ↔ API entegrasyonu | ⏳ Fetch hazır, hata yönetimi gerekli |
| Ürün kataloğu UI | ⏳ DB hazır |
| Araç filosu UI | ⏳ DB hazır |
| QR kod üretimi | ⏳ |
| PDF export | ⏳ |

### Planlanan (V3.0 — Sprint 4-6)

| Özellik | Durum |
|---------|-------|
| Analytics dashboard | 🚀 |
| Maliyet trendleri | 🚀 |
| Karbon ayak izi | 🚀 |
| ERP webhook entegrasyonu | 🚀 |
| Mobil uygulama | 🚀 |
| AI maliyet tahmini | 🚀 |
| React migrasyonu | 🚀 |

---

## 11. Dosya Yapısı ve Sorumluluklar

```
cronoi_project/
├── docker-compose.yml          # PostgreSQL + Redis + FastAPI + Celery orkestrasyon
├── mock_server.py              # Frontend test için bağımsız mock API
├── README.md                   # Proje navigasyon haritası
│
├── docs/
│   ├── PRODUCT_FEATURES.md     # Ürün vizyonu, ICP, yol haritası, fiyatlandırma
│   ├── SPRINT_1_PLAN.md        # Sprint 1 detaylı görev planı (2 hafta)
│   └── PROJECT_SCOPE.md        # Bu dosya
│
├── backend/
│   ├── Dockerfile              # Python 3.12-slim container
│   ├── requirements.txt        # Tam bağımlılıklar
│   ├── requirements-sprint1.txt# Sprint 1 minimal bağımlılıklar
│   ├── schema.sql              # Ana 10 tablo + indexler
│   ├── constraint_schema.sql   # Kısıt tabloları + 15 seed constraint
│   ├── orders_schema.sql       # Sipariş tabloları
│   │
│   └── app/
│       ├── main.py             # FastAPI uygulama + CORS + router kayıtları
│       ├── models.py           # SQLAlchemy ORM modelleri (12+ model)
│       │
│       ├── core/
│       │   ├── config.py       # Pydantic Settings (env vars)
│       │   ├── database.py     # Async engine + session factory
│       │   └── auth.py         # JWT + bcrypt yardımcıları
│       │
│       ├── api/v1/
│       │   ├── shipments.py    # Sevkiyat CRUD + optimizasyon + polling
│       │   ├── orders.py       # Sipariş CRUD + gruplama + toplu import
│       │   ├── scenarios.py    # Senaryo üretimi (3 strateji)
│       │   └── constraints.py  # Kısıt havuzu + uyumluluk + doğrulama
│       │
│       ├── services/
│       │   ├── optimizer.py    # 3D bin packing (FFD-C) + senaryo optimizer
│       │   └── constraint_engine.py  # Kısıt değerlendirme motoru
│       │
│       └── workers/            # Celery worker'lar (henüz boş)
│
└── frontend/
    ├── Cronoi_LS_v2.html       # Ana SPA (~3000+ satır)
    └── Cronoi_LS_v2 old*.html  # Önceki sürüm yedekleri (13 adet)
```

---

*Bu belge, projenin 27 Mart 2026 tarihindeki durumunu yansıtmaktadır.*
