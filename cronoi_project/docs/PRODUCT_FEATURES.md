# Cronoi LS — Product Features & Roadmap

> **Versiyon:** v2.0-SaaS-Architecture  
> **Güncelleme:** 2026-03-23  
> **Durum:** Active Development

---

## 🎯 Ürün Vizyonu

Cronoi LS, **mobilya ve beyaz eşya sektöründeki üreticilerin** sevkiyat süreçlerini;
palet optimizasyonu, araç seçimi ve yükleme planlaması alanlarında **%30–50 maliyet
azaltımı** sağlayarak dijitalleştiren B2B Cloud SaaS çözümüdür.

---

## 👤 Hedef Müşteri Profili (ICP)

| Özellik | Detay |
|---|---|
| Sektör | Mobilya üretimi, beyaz eşya, ev tekstili |
| Şirket büyüklüğü | 50–500 çalışan |
| Sevkiyat sıklığı | Haftada 5+ TIR / konteyner |
| Mevcut araç | Excel, kâğıt, ERP modülü yok |
| Karar verici | Lojistik müdürü / Tedarik zinciri direktörü |
| Bütçe | 500–3.000 USD/ay |

### Müşteri Acı Noktaları (Validated)

**#1 — Tekrar eden manuel giriş**  
Lojistik şefi aynı koltuk takımı ölçülerini her sevkiyatta sıfırdan giriyor.
Neden: Ürün kataloğu yok, veri kalıcı saklanmıyor.  
Çözüm: `product_catalog` + şirkete özel ürün kütüphanesi.

**#2 — Boş hacim = boşa para**  
Mobilya gibi hacimli ürünlerde TIR'ın %20–35'i boş gidiyor.
Neden: Göz kararı istif, deneyime dayalı karar.  
Çözüm: OR-Tools 3D bin packing, doluluk garantisi.

**#3 — Yükleme hatası = hasar tazminatı**  
Kırılgan ürünler yanlış yükleniyor, ağırlık dengesi kontrolsüz.
Neden: Yükleme talimatı kâğıda, depo ekibi bilmiyor.  
Çözüm: QR kodlu dijital yükleme talimatı, adım adım sıra.

**#4 — Maliyet kör nokta**  
"Bu sevkiyat bize ne kadar maldı?" sorusuna cevap yok.  
Neden: Fatura var, palet başı maliyet, araç verimliliği hesaplanmıyor.  
Çözüm: Senaryo karşılaştırma + aylık maliyet dashboard.

**#5 — ERP entegrasyonu yok**  
SAP/Canias'tan ürün listesi manuel kopyalanıyor.  
Neden: Hazır lojistik modülleri ya çok pahalı ya çok genel.  
Çözüm: REST API + webhook, ERP push entegrasyonu.

---

## 🏗️ Teknik Mimari

### Stack Kararları

| Katman | Teknoloji | Neden |
|---|---|---|
| **Frontend** | React 18 + TypeScript + Vite | Component mimarisi, type safety |
| **3D Görünüm** | Three.js (mevcut kod korunuyor) | Çalışıyor, migration gerekmez |
| **State** | Zustand | Redux'tan hafif, yeterli |
| **Backend** | FastAPI (Python 3.12) | Async, otomatik OpenAPI, tip güvenli |
| **Optimizer** | Google OR-Tools + scipy | Gerçek 3D bin packing |
| **Veritabanı** | PostgreSQL 16 | Multi-tenant, JSONB, extensions |
| **Cache/Queue** | Redis + Celery | Ağır optimizasyon async çalışsın |
| **Auth** | JWT + refresh tokens | Stateless, ölçeklenebilir |
| **Storage** | AWS S3 / Cloudflare R2 | Excel/PDF export dosyaları |
| **Deployment** | Docker + Railway/Render | Hızlı deploy, autoscale |

---

## 📦 Feature Inventory

### ✅ V1.1 (Mevcut — HTML Prototip)

| Feature | Durum | Notlar |
|---|---|---|
| 6 adımlı workflow | ✅ Çalışıyor | switchStep() |
| Ürün tablosu (manuel giriş) | ✅ Çalışıyor | |
| Excel import | ✅ Çalışıyor | SheetJS |
| Excel template indirme | ✅ Çalışıyor | |
| EUR/Standart/UK/Özel palet tipleri | ✅ Çalışıyor | |
| Bin packing algoritması (JS-FFD) | ✅ Çalışıyor | Server'a taşınacak |
| Accordion palet listesi | ✅ Çalışıyor | |
| 3D palet görünümü (Three.js) | ✅ Çalışıyor | |
| Palet istatistikleri | ✅ Çalışıyor | |
| 5 araç tipi (otomatik yüklü) | ✅ Çalışıyor | |
| Araç maliyet düzenleme (modal) | ✅ Çalışıyor | |
| 3 senaryo otomatik optimizasyon | ✅ Çalışıyor | |
| Senaryo karşılaştırma (tablo+radar) | ✅ Çalışıyor | Chart.js |
| 3D TIR görünümü (Step 5) | ✅ Çalışıyor | |
| Yükleme sırası listesi | ✅ Çalışıyor | |
| Ağırlık dengesi hesabı | ✅ Çalışıyor | |
| Yükleme planı Excel export | ✅ Çalışıyor | |
| JSON dışa aktarma | ✅ Çalışıyor | |
| Kısıt yönetimi (kırılgan/ağır/sıcaklık) | ✅ Çalışıyor | |

### 🔄 V2.0 — SaaS Foundation (Sprint 1-3)

| Feature | Sprint | Öncelik |
|---|---|---|
| FastAPI backend kurulumu | 1 | P0 |
| PostgreSQL şema + migration | 1 | P0 |
| Shipment CRUD API | 1 | P0 |
| Palet & ürün kayıt API | 1 | P0 |
| OR-Tools 3D bin packing (server-side) | 1 | P0 |
| Senaryo kayıt & sorgulama | 1 | P0 |
| Loading plan kayıt | 1 | P0 |
| JWT auth (register/login/refresh) | 2 | P0 |
| Multi-tenant company izolasyonu | 2 | P0 |
| React frontend (HTML → component) | 2 | P1 |
| Ürün kataloğu (şirkete özel) | 2 | P1 |
| Araç filosu yönetimi (şirkete özel) | 2 | P1 |
| Shipment geçmişi listesi | 2 | P1 |
| Rol yönetimi (admin/operator/viewer) | 3 | P1 |
| QR kodlu yükleme talimatı sayfası | 3 | P1 |
| Email bildirim (yükleme planı hazır) | 3 | P2 |

### 🚀 V3.0 — Growth Features (Sprint 4-6)

| Feature | Öncelik | Müşteri Değeri |
|---|---|---|
| Aylık maliyet dashboard | P1 | "Bu ay ne kadar tasarruf ettim?" |
| Palet başı maliyet trend grafiği | P1 | ROI kanıtı |
| Karbon ayak izi hesabı | P2 | ESG raporlama |
| ERP webhook entegrasyonu | P1 | Manuel giriş sıfırlanır |
| SAP connector | P2 | Enterprise satış kapısı |
| Canias connector | P2 | TR market özelinde |
| Multi-destination routing | P2 | Tek TIR, çok teslimat |
| Sürücü mobil uygulaması | P2 | Teslimat takibi |
| AI maliyet tahmini (ML) | P3 | Prediktif bütçe |
| Otomatik PDF sevk irsaliyesi | P1 | Operasyonel süreç |
| API anahtarı yönetimi | P2 | Müşteri entegrasyonu |
| White-label seçeneği | P3 | Bayi kanalı |

---

## 💰 Fiyatlandırma Modeli

### Planlar

| Plan | Fiyat | Limit | Hedef |
|---|---|---|---|
| **Starter** | 299 TL/ay | 50 sevkiyat/ay, 2 kullanıcı | Küçük üretici |
| **Growth** | 899 TL/ay | 200 sevkiyat/ay, 10 kullanıcı | Orta boy fabrika |
| **Enterprise** | 2.499 TL/ay | Limitsiz, SSO, API, öncelikli destek | Büyük üretici |
| **On-premise** | Teklif al | Self-hosted | Kurumsal |

### Freemium Hook
- İlk 30 gün ücretsiz, kredi kartı gerekmez
- 5 sevkiyata kadar ücretsiz (forever free tier)
- Optimize edilmiş PDF'de "Powered by Cronoi" watermark

---

## 📊 Başarı Metrikleri (KPIs)

### Ürün Metrikleri
- **Activation rate:** İlk 7 günde ilk optimizasyon yapılması
- **Week 4 retention:** %60 hedef
- **NPS:** >40
- **Doluluk oranı iyileştirmesi:** Müşteri başına ortalama +%18

### İş Metrikleri
- **MRR hedef (Ay 6):** 50.000 TL
- **CAC:** <5.000 TL (inbound odaklı)
- **LTV:CAC:** >3x
- **Churn:** <%5/ay

---

## 🔒 Güvenlik & Compliance

- KVKK uyumlu veri işleme
- Veri Türkiye'de barındırılıyor (AWS eu-central-1 Frankfurt veya TR datacenter)
- Şifreler bcrypt hash
- API rate limiting (Redis)
- Audit log (kim ne zaman ne yaptı)
- Soft delete (veri silinmez, arşivlenir)
- TLS 1.3 zorunlu

---

## 🗂️ Bilinen Sınırlamalar (v1.1)

1. Veri kalıcı değil — sayfa kapanırsa kayboluyor (**Sprint 1'de çözülüyor**)
2. Tek kullanıcı — ekip çalışması yok (**Sprint 2**)
3. Çoklu araç 3D gösterimi yok — ilk araç gösteriliyor (**Sprint 4**)
4. Drag & drop palet yerleştirme yok (**Sprint 4**)
5. Multi-destination routing yok (**V3.0**)
6. Mobil uygulama yok — responsive web (**V3.0**)

---

## 📝 Değişiklik Geçmişi

| Versiyon | Tarih | Değişiklik |
|---|---|---|
| v1.0 | 2025 | İlk HTML prototip |
| v1.1 | 2025 | Otomatik araç yükleme, 3D TIR, Yükleme planı, Bin packing optimizer |
| v2.0 | 2026-03-23 | SaaS mimarisi kararı, FastAPI + PostgreSQL, multi-tenant |
| v2.1 | 2026-04-07 | Stabilite sistemi, hacim bazlı TIR doluluk, siparişten sevkiyat akışı |

---
---

# BÖLÜM 2 — Teknik Durum Belgesi (AI Agent Reference)

> **Son güncelleme:** 2026-04-07  
> **Amaç:** Bu bölüm, AI agent'ların (Claude Opus vb.) projenin güncel durumunu, optimizasyon mantığını ve tüm fonksiyon envanterini hızlıca kavraması için yazılmıştır. Yeni özellik eklendikçe burası güncellenir.

---

## 1. Güncel Mimari Özeti

```
Frontend (Tek Sayfa — HTML + JS + Three.js)
└── frontend/Cronoi_LS_v2.html (~14.000+ satır)
    ├── 6 adımlı sevkiyat wizard'ı
    ├── Local JS optimizer (palet + araç)
    ├── Three.js 3D palet & TIR renderlama
    └── API entegrasyonu (backend varsa API, yoksa local mod)

Backend (FastAPI + PostgreSQL)
├── backend/app/main.py              — ASGI uygulaması
├── backend/app/models.py            — SQLAlchemy ORM modelleri
├── backend/app/core/
│   ├── config.py                    — Ortam değişkenleri
│   ├── database.py                  — AsyncSession factory
│   └── auth.py                      — JWT token
├── backend/app/api/v1/
│   ├── shipments.py                 — Sevkiyat CRUD + detay
│   ├── orders.py                    — Sipariş CRUD + grup önerileri
│   ├── scenarios.py                 — Senaryo üretimi + kayıt
│   ├── constraints.py               — Kısıt havuzu + validasyon
│   └── transport_units.py           — Palet/araç tanım kütüphanesi
├── backend/app/services/
│   ├── optimizer.py                 — 3D Bin Packing + Senaryo (~2300 satır)
│   └── constraint_engine.py         — Kısıt değerlendirme motoru
└── backend/tests/
    ├── test_sprint3.py              — E2E API test script
    └── test_optimizer_v7.py         — 16 optimizer unit test
```

### Bağlantı Bilgileri

| Bilgi | Değer |
|---|---|
| DB | `postgresql+asyncpg://cronoi_user:cronoi_pass@localhost:5432/cronoi_ls` |
| API | `http://localhost:8000/api/v1/` |
| psql | `"C:\Program Files\PostgreSQL\17\bin\psql.exe"` |
| Python | `backend/venv/Scripts/python.exe` (3.12.9) |
| Test | `python -m pytest tests/ --ignore=tests/test_headboard_analysis.py` |

### Koordinat Sistemi (Kritik)

```
Z-up koordinat sistemi:
  pos_x = genişlik (width)    → paletın kısa kenarı (80cm EUR)
  pos_y = derinlik (depth)    → paletın uzun kenarı (120cm EUR)
  pos_z = yükseklik (height)  → yerden yukarı

placed_rects formatı:
  {"x": z, "y": x, "z": y, "dx": pw, "dy": pl, "dz": ph}
  → x=yükseklik, y=genişlik, z=derinlik (skyline uyumlu)
```

---

## 2. Ana Akış (End-to-End)

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. SİPARİŞ GİRİŞİ                                                │
│     → Manuel tablo / Excel import / API orders endpoint            │
│     → Ürün boyutları + ağırlık + kısıtlar                         │
├─────────────────────────────────────────────────────────────────────┤
│  2. PALET TİPİ SEÇİMİ                                             │
│     → EUR (80×120), Standart (100×120), TIR (120×200), Özel      │
│     → Otomatik öneri: _selectBestPalletType()                     │
├─────────────────────────────────────────────────────────────────────┤
│  3. 3D BİN PACKING OPTİMİZASYONU                                  │
│     → BinPackingOptimizer3D (backend) veya JS-FFD (frontend)      │
│     → Kısıt-bilinçli sıralama → skyline yerleştirme → validasyon  │
│     → Çıktı: OptimizedPallet listesi + fill_rate + stability      │
├─────────────────────────────────────────────────────────────────────┤
│  4. ARAÇ PLANLAMA (ScenarioOptimizer)                              │
│     → 3 senaryo: Min Maliyet / Karma Filo / Max Verimlilik       │
│     → Binding dimension: max(vol%, weight%, pallet_count%)        │
│     → Palet istifleme (stacking) desteği                          │
│     → Hacim bazlı doluluk oranı (vol_utilization_pct)             │
├─────────────────────────────────────────────────────────────────────┤
│  5. SENARYO KARŞILAŞTIRMA + ONAY                                  │
│     → Maliyet / araç sayısı / hacim doluluk tablo + donut chart   │
│     → Seçilen senaryo DB'ye kaydedilir                            │
├─────────────────────────────────────────────────────────────────────┤
│  6. YÜKLEME PLANI + 3D TIR                                        │
│     → Palet sıralaması, ağırlık dengesi, Three.js 3D görünüm     │
│     → Excel/PDF export, yazdırma                                   │
├─────────────────────────────────────────────────────────────────────┤
│  7. SEVKİYAT GEÇMİŞİ                                             │
│     → Tamamlanan sevkiyatlar, 3D palet detay, fotoğraf galerisi   │
│     → Dashboard KPI: TIR doluluk ortalaması, maliyet trendi       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Optimizasyon Mantığı (Detaylı)

### 3.1 Palet Yerleştirme — BinPackingOptimizer3D

**Algoritma:** Rect-Skyline FFD-C (First Fit Decreasing with Constraints), v10.0

**Aşamalar:**

1. **Ürün hazırlama** (`_expand_items` → `_constraint_aware_sort`)
   - Quantity açılır (5×Box → 5 ayrı Box)
   - Sıralama: layer_class (MUST_BOTTOM=0, normal=1, MUST_TOP=2) → kısıt zorluğu → hacim büyükten küçüğe (FFD) → ağırlık

2. **Pack döngüsü** (`_pack`)
   - Her ürün için: `_place_item()` → `_find_best_position()`
   - Bulamazsa yeni palet aç → `_create_empty_pallet()`
   - Zaman aşımı: `_fast_fallback_pack()` (skor hesaplamadan hızlı yerleştirme)
   - İki faz: önce normal ürünler, sonra MUST_TOP ürünleri

3. **Pozisyon bulma** (`_find_best_position`)
   - `_candidate_positions()`: Mevcut rect kenarlarından aday (x,z) üretir (extreme point method)
   - Her oryantasyon × her aday pozisyonu → `_score_candidate()` ile puanla
   - En yüksek skoru alan pozisyon seçilir

4. **Skor hesaplama** (`_score_candidate`) — 10 faktör:

| # | Faktör | Ağırlık | Açıklama |
|---|---|---|---|
| 1 | Düşük base_y | +100 | Mümkün olduğunca zemine yakın |
| 2 | Bitişiklik (adjacency) | +60 | Komşu ürünlere temas bonus |
| 3 | Zemin tercihi | +40 | z=0'da yerleştirme bonus |
| 4 | Köşe başlangıcı | +35 | (0,0) veya kenar pozisyonları |
| 5 | Hizalama | +30 | Palet kenarıyla hizalı yerleştirme |
| 6 | CoG + Devrilme | -30~-80 | 2D CoG sapma cezası + 3D tip stability ratio |
| 7 | Ağır alt/üst | +20~-30 | Ağır ürünler zeminse bonus, üstteyse ceza |
| 8 | Taban desteği | +40~-100 | Altındaki destek oranı (0.0-1.0) |
| 9 | Yükseklik verimliliği | +15~-20 | Max yüksekliğe kalan boşluk |
| 10 | Zemin kapasitesi | -10 | Zemin %80+ doluysa ceza |
| 11 | Ürün gruplama | +120~-80 | Aynı ürün → bonus; saf paleti koruma → ceza; karışık → hafif ceza |

5. **Stabilite sistemi** (Fizik tabanlı)
   - `_compute_cog_3d()` → 3B ağırlık merkezi (X, Y, Z)
   - `_compute_tip_stability()` → ISO 10531 devrilme moment analizi, 0.5g yanal ivme. Her kenar (±X, ±Y) için stabilite oranı. ratio < 1.0 = devrilir
   - `_compute_support_ratio()` → İstiflenmiş ürünün altında %kaç destek var (0.0=havada, 1.0=tam destekli)

6. **Validasyon** (`_validate_all_pallets`)
   - Boyut taşması (overflow toleransı dahil)
   - Ağırlık limiti
   - NO_STACK kuralı
   - ISPM-15 malzeme kontrolü
   - Ağırlık hiyerarşisi (ağır üstte = ihlal)
   - CTU Code 2014 boşluk kontrolü (>15cm = dunnage bag önerisi)
   - McKee BCT kutu dayanımı
   - CoG sapması (%25 üzeri = uyarı, %40 üzeri = ihlal)
   - Devrilme riski (ratio < 0.7 = HARD ihlal, 0.7-1.0 = uyarı)
   - Taban desteği (havada kalan ürün = ihlal)

7. **Uyumluluk raporu** (`_build_compliance`)
   - `CTU Code 2014: OK/FAIL`
   - `ISPM-15: OK/FAIL`
   - `CoG Balance: OK/FAIL`
   - `Tip Stability: OK/FAIL`
   - `Base Support: OK/FAIL`

### 3.2 Araç Planlama — ScenarioOptimizer

**Girdi:** OptimizedPallet listesi + VehicleConfig listesi  
**Çıktı:** 3 × ScenarioResult (en iyisi is_recommended=True)

**Stratejiler:**

| Strateji | Mantık |
|---|---|
| `MIN_VEHICLES` | En büyük araçtan başla, greedy dolduruluyor |
| `BALANCED` | Büyük + küçük araç karışımı, alternatif sıralama |
| `MAX_EFFICIENCY` | Waste oranı en düşük araç tipi (binding dimension'a göre) |

**Doluluk hesaplama (Hacim bazlı):**
```
vol_utilization_pct = (yüklenen_hacim_m3 / araç_hacim_m3) × 100
avg_fill_rate_pct   = ortalama(tüm araçların vol_utilization_pct)
```

**İstifleme** (`_can_stack`):
- Alt palet ağırlığı ≥ üst palet ağırlığı
- Alt palet footprint ≥ üst palet footprint
- Toplam yükseklik ≤ araç yüksekliği
- Kırılgan (FRAGILE) palet üstüne istiflenmez
- MUST_BOTTOM palet üste konmaz

---

## 4. Backend API Endpoint Envanteri

### Shipments (`/api/v1/shipments`)

| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/` | Yeni sevkiyat oluştur (ürünler + palet optimizasyonu dahil) |
| GET | `/` | Sevkiyat listesi (palet doluluk + araç doluluk ile) |
| GET | `/{shipment_id}` | Detay: ürünler, paletler, siparişler, fotoğraflar, senaryo |

### Orders (`/api/v1/orders`)

| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/` | Sipariş oluştur (satır kalemleri ile) |
| GET | `/` | Sipariş listesi (status, şehir, hafta filtresi) |
| POST | `/group-suggestions` | Bekleyen siparişlerden grup önerisi (şehir+hafta) |
| POST | `/bulk` | Toplu Excel import (order_no'ya göre grupla) |
| GET | `/{order_id}` | Sipariş detayı + kalemleri + sevkiyat referansı |
| PUT | `/{order_id}` | Sipariş güncelle |
| PATCH | `/{order_id}/status` | Durum geçişi (validasyonlu) |
| DELETE | `/{order_id}` | Soft delete |

### Scenarios (`/api/v1/scenarios`)

| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/generate` | 3 senaryo üret (ScenarioOptimizer) |
| POST | `/{shipment_id}/save` | Frontend'den gelen senaryoyu kaydet |
| PATCH | `/{scenario_id}/select` | Senaryoyu seç (diğerlerini kaldır) |
| GET | `/{shipment_id}` | Sevkiyatın tüm senaryoları |

### Constraints (`/api/v1/constraints`)

| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/` | Kısıt listesi (şirket + sistem) |
| POST | `/` | Yeni kısıt oluştur |
| GET | `/compatibility` | Uyumluluk matrisi |
| POST | `/compatibility` | Uyumluluk kuralı ekle |
| POST | `/validate` | Kısıt seti validasyonu |
| PUT | `/{constraint_id}` | Kısıt güncelle |
| DELETE | `/{constraint_id}` | Kısıt sil |

### Transport Units (`/api/v1/transport-units`)

| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/seed` | Varsayılan palet + araç tanımlarını oluştur |
| GET/POST/PATCH/DELETE | `/pallets/...` | Palet tipi CRUD + toggle |
| GET/POST/PATCH/DELETE | `/vehicles/...` | Araç tipi CRUD + toggle |

---

## 5. Backend Fonksiyon Envanteri (optimizer.py)

### 5.1 Enum & Sabitler

| İsim | Tip | Açıklama |
|------|-----|----------|
| `ConstraintType` | Enum | FRAGILE, HEAVY, NO_STACK, MUST_BOTTOM, MUST_TOP, HORIZONTAL_ONLY, VERTICAL_ONLY, THIS_SIDE_UP, COLD_CHAIN, HAZMAT, KEEP_DRY, LOAD_FIRST/LAST, VEH_FRONT/REAR |
| `ScenarioStrategy` | Enum | MIN_VEHICLES, BALANCED, MAX_EFFICIENCY |
| `PALLET_BOARD_HEIGHT_CM` | Sabit | 15 |
| `DEFAULT_OVERFLOW_TOLERANCE_PCT` | Sabit | 5.0 |
| `DENSITY_BOTTOM_THRESHOLD` | Sabit | 400 kg/m³ |
| `DENSITY_TOP_THRESHOLD` | Sabit | 200 kg/m³ |
| `PALLET_FOOTPRINT` | Dict | {"P1": (80,120), "P5": (100,120), "P10": (120,200)} |

### 5.2 Veri Yapıları (Dataclass)

| Sınıf | Amaç | Önemli Alanlar |
|-------|------|----------------|
| `OptimizerSettings` | Optimizasyon parametreleri | target_fill_rate_pct, max_void_gap_cm, weight_front_ratio_pct, stacking_pattern, group_same_products |
| `OptimizationParams` | Legacy parametre (→ to_settings()) | Geriye dönük uyumluluk |
| `ProductItem` | Girdi ürün | name, boyutlar, weight, constraints[], all_constraints, layer_class, density |
| `PalletConfig` | Palet tipi | type, boyutlar, max_weight, euro()/standard()/tir() factory'ler |
| `PackedItem` | Yerleştirilmiş ürün | pos_x/y/z, rotated, placement_direction, bct_safety_factor |
| `OptimizedPallet` | Paketlenmiş palet | products, fill_rate_pct, layout_data (placed_rects + stability) |
| `RejectedItem` | Reddedilen ürün | name, reason |
| `ConstraintValidationResult` | Palet validasyonu | violations[], warnings[], errors[] |
| `OptimizationResult` | Nihai çıktı | pallets, rejected, compliance, quantity_audit, binding_dimension |
| `VehicleConfig` | Araç tanımı | boyutlar, max_weight, maliyet alanları, volume_m3 property |
| `VehicleAssignment` | Araç ataması | pallet_ids, vol_utilization_pct, weight_utilization_pct, balance_ok |
| `ScenarioResult` | Senaryo çıktısı | vehicles[], total_cost, avg_fill_rate_pct (hacim bazlı) |

### 5.3 BinPackingOptimizer3D — Metot Grupları

**Giriş:**
| Metot | Açıklama |
|-------|----------|
| `optimize(products)` | Ana giriş noktası → OptimizationResult döner |

**Ürün Hazırlama:**
| Metot | Açıklama |
|-------|----------|
| `_expand_items(products)` | Quantity'i tekil ürünlere aç |
| `_constraint_aware_sort(items)` | Layer → kısıt zorluğu → hacim (FFD) sırala |

**Oryantasyon:**
| Metot | Açıklama |
|-------|----------|
| `_get_valid_orientations(item)` | Kısıtlara göre geçerli (L,W,H,rotated) döndür |
| `_item_fits_pallet(item)` | Hızlı sığma kontrolü |

**Pozisyon Bulma:**
| Metot | Açıklama |
|-------|----------|
| `_candidate_positions(pallet, pl, pw)` | Extreme-point aday (x,z) üret |
| `_score_candidate(pallet, item, x, z, base_y, pl, pw, ph)` | 10 faktörlü skor hesapla |
| `_find_best_position(pallet, item)` | En iyi pozisyon + oryantasyonu seç |
| `_base_y_from_rects(pallet, x, z, pl, pw)` | Verilen pozisyonda taban yüksekliği hesapla |

**Fizik & Stabilite:**
| Metot | Açıklama |
|-------|----------|
| `_compute_cog(pallet)` | 2D ağırlık merkezi (X, Y) |
| `_compute_cog_3d(pallet)` | 3D ağırlık merkezi (X, Y, Z) |
| `_cog_deviation_pct(pallet)` | CoG sapma yüzdesi |
| `_compute_tip_stability(pallet)` | ISO 10531 devrilme analizi (0.5g yanal) |
| `_compute_support_ratio(pallet, x, z, base_y, pl, pw)` | Taban destek oranı (0.0–1.0) |

**Yerleştirme:**
| Metot | Açıklama |
|-------|----------|
| `_pack(items)` | Ana pack döngüsü (2 faz: normal + MUST_TOP) |
| `_place_item(item)` | Skorlu yerleştirme |
| `_place_item_fast(item)` | Hızlı fallback yerleştirme |
| `_do_place_in_pallet(pallet, item, cached_pos)` | Fiili yerleştirme işlemi |
| `_commit_place(pallet, item, x, y, z, pl, pw, ph, rotated, direction)` | Paleti güncelle |
| `_create_empty_pallet()` | Boş palet oluştur |

**Uyumluluk & Kısıt:**
| Metot | Açıklama |
|-------|----------|
| `_can_place_in_pallet(pallet, item)` | Tam uygunluk kontrolü |
| `_has_space(pallet, item)` | Geometrik alan kontrolü |
| `_constraints_compatible(pallet, item)` | Kısıt uyumluluk kontrolü |
| `_engine_allows_placement(pallet, item)` | Harici kısıt motoru kontrolü |
| `_overlaps_3d(pallet, x, z, y, pl, pw, ph)` | 3D çakışma kontrolü |

**Validasyon:**
| Metot | Açıklama |
|-------|----------|
| `_validate_all_pallets()` | Tam uyumluluk kontrolü (boyut, ağırlık, CoG, devrilme, destek) |
| `_verify_quantities()` | Girdi vs çıktı miktar denetimi |
| `_build_compliance(validations)` | 5 maddelik uyumluluk raporu |

**Sonuç Üretme:**
| Metot | Açıklama |
|-------|----------|
| `_build_result(duration_ms)` | OptimizationResult derleme |
| `_build_quantity_audit()` | Miktar denetim raporu |
| `_generate_suggestions()` | İyileştirme önerileri |
| `_compute_pallet_type_breakdown()` | Palet tipi bazlı özet |

### 5.4 MixedBinPackingOptimizer

| Metot | Açıklama |
|-------|----------|
| `optimize(products)` | Çoklu palet tipi optimizasyonu: tüm tipleri dene → en az paleti seçen tipi kullan → palet bazlı refinement |

### 5.5 ScenarioOptimizer

| Metot | Açıklama |
|-------|----------|
| `generate_all()` | 3 strateji üret, en iyisini is_recommended yap |
| `_min_vehicles()` | Büyük araçtan küçüğe greedy |
| `_balanced()` | Orta araç öncelikli dağılım |
| `_max_efficiency()` | Waste oranı minimum araç tipi |
| `_assign_greedy(sorted_v, remaining)` | Greedy atama: zemin → istifleme → kalan |
| `_compute_binding(va, assigned)` | vol/weight/pallet utilization hesapla |
| `_compute_weight_balance(va, assigned)` | Ön/arka ağırlık dağılımı |
| `_can_stack(bottom, top, vehicle)` | İstifleme uygunluk kontrolü |
| `_build_scenario(name, strategy, assignments)` | ScenarioResult derleme (hacim bazlı doluluk) |

---

## 6. Frontend Fonksiyon Envanteri (Cronoi_LS_v2.html)

### 6.1 Workflow & Navigasyon

| Fonksiyon | Açıklama |
|-----------|----------|
| `switchStep(step)` | 6 adımlı wizard navigasyonu |
| `markStepCompleted(step)` | Adımı tamamlandı işaretle |
| `showPage(page)` | Sayfa görünümü değiştir (plan, orders, history, dashboard) |

### 6.2 Ürün Yönetimi

| Fonksiyon | Açıklama |
|-----------|----------|
| `addProductRow()` | Ürün satırı ekle |
| `deleteRow(btn)` | Satır sil |
| `handleFileUpload(event)` | Excel/CSV dosya yükle (SheetJS) |
| `processProducts()` | Ürünleri işle ve optimize et |
| `_processProductsAPI()` | API üzerinden optimize et |
| `_processProductsLocal()` | Yerel optimizer ile optimize et |
| `_verifyQuantityIntegrity()` | Miktar tutarlılık kontrolü |

### 6.3 Palet Optimizasyonu (Yerel)

| Fonksiyon | Açıklama |
|-----------|----------|
| `generatePallets()` | Optimal palet konfigürasyonu oluştur |
| `generateMixedPallets()` | Karma palet tipleri |
| `getOptimizationReport()` | Palet doluluk / ağırlık / hacim raporu |
| `_validateAll()` | Miktar + kısıt + doluluk validasyonu |
| `_selectBestPalletType(products)` | Palet tipi öneri |
| `renderPalletList()` | Palet listesi render |
| `updatePalletStats()` | İstatistik güncelle |

### 6.4 Araç & Filo

| Fonksiyon | Açıklama |
|-----------|----------|
| `loadDefaultVehicles()` | Varsayılan araç tipleri yükle |
| `renderVehicleGrid()` | Araç grid görünümü |
| `openVehicleCostModal(id)` | Maliyet düzenleme modalı |
| `saveVehicleCost()` | Maliyet kaydet |
| `_evalAllFleets(pallets)` | Tüm filo opsiyonlarını değerlendir |
| `_buildFleetOfType(pallets, code, config)` | Belirli araç tipinden filo oluştur (FFD) |
| `_calcFleetFillRate(fleet)` | **Filo hacim doluluk oranı (loadedVol/vehicleVol ×100)** |
| `_calcFleetVolumes(fleet)` | Filo toplam yüklenen/araç hacmi (m³) |

### 6.5 Senaryo Karşılaştırma

| Fonksiyon | Açıklama |
|-----------|----------|
| `optimizeForMinVehicles()` | Senaryo 1: Minimum maliyet |
| `optimizeBalanced()` | Senaryo 2: Karma filo |
| `optimizeForEfficiency()` | Senaryo 3: Hız/çeviklik |
| `renderComparison()` | Karşılaştırma tablosu (maliyet + hacim doluluk + donut chart) |
| `approveVehiclePlanAndContinue()` | Araç planını onayla ve DB'ye kaydet |
| `_applyFleetOption(vtCode)` | Manuel araç tipi seçimi |

### 6.6 API Entegrasyonu

| Fonksiyon | Açıklama |
|-----------|----------|
| `checkAndShowApiStatus()` | Backend erişilebilirlik kontrolü |
| `autoOptimize()` | Otomatik optimizasyon tetikle (API/local) |
| `_autoOptimizeAPI()` | Backend'den senaryo al |
| `_autoOptimizeLocal()` | Yerel senaryo hesapla |
| `_mapApiPallets(apiPallets)` | API palet verisini frontend formatına dönüştür |
| `_mapApiVehicleAssignments(assignments)` | API araç atamasını frontend formatına dönüştür (volume, fillRate dahil) |
| `approvePalletsAndContinue()` | Paletleri kaydet ve ilerle |

### 6.7 3D Görünüm (Three.js)

| Fonksiyon | Açıklama |
|-----------|----------|
| `init3D()` | Palet 3D sahnesini başlat |
| `update3DScene(pallet)` | Palet değiştiğinde sahneyi güncelle |
| `initTruck3D()` | TIR 3D sahnesini başlat |
| `_buildTruck3D(vehicle)` | Tam TIR geometrisi oluştur |
| `_placePallets3D()` | Paletleri TIR içine yerleştir |
| `_renderHistoryPallet3D()` | Geçmiş sevkiyat 3D palet |
| `_renderShipmentTruck3D()` | Geçmiş sevkiyat 3D TIR |

### 6.8 Sipariş & Sevkiyat

| Fonksiyon | Açıklama |
|-----------|----------|
| `renderOrdersList()` | Sipariş tablosu |
| `_loadOrdersFromAPI()` | API'den sipariş listesi |
| `createShipmentFromSelected()` | Seçili siparişlerden sevkiyat oluştur |
| `loadHistory()` | Sevkiyat geçmişi yükle |
| `openHistoryDetail(id)` | Sevkiyat detay modalı |
| `StatusManager.bulkUpdateOrderStatus()` | Toplu durum güncelleme |
| `StatusManager.updateShipmentStatus()` | Sevkiyat durumu güncelle |

### 6.9 Dashboard & Raporlama

| Fonksiyon | Açıklama |
|-----------|----------|
| `loadDashboard()` | Dashboard başlat |
| `_loadRecentShipments()` | Son sevkiyatları yükle + KPI hesapla |
| `_printVehicleReport(data)` | Araç planı yazdırma raporu (hacim bazlı) |
| `exportLoadingPlan()` | Yükleme planı Excel export |
| `_computeDashboardMetrics()` | KPI hesaplama |

### 6.10 Taşıma Birimi Yönetimi (Admin)

| Fonksiyon | Açıklama |
|-----------|----------|
| `loadTransportUnits()` | Palet & araç tanımları yükle |
| `savePalletDef() / saveVehicleDef()` | Tanım kaydet |
| `togglePalletDef() / toggleVehicleDef()` | Aktif/pasif |
| `deletePalletDef() / deleteVehicleDef()` | Tanım sil |

---

## 7. Veritabanı Tabloları (PostgreSQL)

| Tablo | Amaç | Önemli Sütunlar |
|-------|------|-----------------|
| `shipments` | Ana sevkiyat | reference_no, status, pallet_type, destination |
| `shipment_products` | Sevkiyat ürünleri | name, boyutlar, weight_kg, constraints (JSONB) |
| `pallets` | Optimize edilmiş paletler | pallet_number, fill_rate_pct, layout_data (JSONB) |
| `scenarios` | Araç senaryoları | strategy, avg_fill_rate_pct, vehicle_assignments (JSONB) |
| `orders` | Siparişler | order_no, status, city, delivery_week |
| `order_items` | Sipariş kalemleri | product_name, boyutlar, weight_kg |
| `loading_plans` | Yükleme planı | is_balanced, front_rear_diff_pct |
| `constraint_definitions` | Kısıt tanımları | code, category, scope, optimizer_rules (JSONB) |
| `pallet_definitions` | Palet tipi tanım | code, width/length/height, max_weight |
| `vehicle_definitions` | Araç tipi tanım | code, boyutlar, max_weight, maliyet alanları |

---

## 8. Aktif Özellik Durumu

### ✅ Tamamlanan Özellikler

| Özellik | Tarih | Detay |
|---------|-------|-------|
| Z-up koordinat dönüşümü | 2026-03 | Y-up → Z-up tam refactor |
| VERTICAL_ONLY oryantasyon düzeltmesi | 2026-03 | Bookshelf yerleştirme |
| 3D palet & TIR renderlama | 2026-03 | Three.js, hem palet hem araç 3D |
| Palet istifleme (stacking) | 2026-03 | _can_stack, 2-pass _assign_greedy |
| Sipariş akışı (order → shipment) | 2026-04 | Status flow, bulk import, grup önerisi |
| ⋮ Menü sevkiyat erişimi düzeltmesi | 2026-04 | shipment_id propagasyonu |
| Miktar uyumsuzluğu toast iyileştirme | 2026-04 | error → warning, detaylı bilgi |
| 3D stabilite sistemi | 2026-04 | CoG 3D, ISO 10531 devrilme, taban desteği |
| Stabilite-bilinçli optimizasyon | 2026-04 | _score_candidate'e stabilite cezaları eklendi |
| Hacim bazlı TIR doluluk | 2026-04 | Ağırlık yerine hacim: vol_utilization_pct |
| Doldurulan hacim gösterimi | 2026-04 | X.X / Y.Y m³ tüm ekranlarda |
| 16/16 backend test geçiyor | 2026-04 | test_headboard_analysis.py hariç (bozuk dosya) |
| Aynı ürün gruplama (group_same_products) | 2026-04 | Aynı ürünler aynı palete: _score_candidate #11 + palet sıralama |

### 🔮 Planlanan Özellikler (Henüz Yapılmadı)

| Özellik | Öncelik | Açıklama |
|---------|---------|----------|
| Ürün kataloğu | P1 | Şirkete özel ürün kütüphanesi |
| JWT auth sistemi | P0 | register/login/refresh |
| Multi-tenant izolasyonu | P0 | company_id bazlı veri ayrımı |
| QR kodlu yükleme talimatı | P1 | Depo ekibine dijital talimat |
| Aylık maliyet dashboard | P1 | Tasarruf analizi |
| ERP webhook | P1 | SAP/Canias entegrasyonu |
| Multi-destination routing | P2 | Tek TIR, çok teslimat noktası |
| Drag & drop palet yerleştirme | P2 | Manuel düzeltme imkanı |

---

## 9. Bilinen Sorunlar & Teknik Borç

| Sorun | Önem | Açıklama |
|-------|------|----------|
| `test_headboard_analysis.py` bozuk | Düşük | Encoding hatası, silinebilir |
| `test_sprint3.py` fixture uyumsuzluğu | Düşük | pytest'le çalışmaz, script olarak çalışır |
| Frontend tek HTML dosyası | Orta | ~14K satır, React componentlere taşınmalı |
| Koltuk takımı yükseklik ihlali | Düşük | 240cm > 180cm palet limiti, beklenen davranış |
| PRODUCT_FEATURES.md eski stack tablosu | Düşük | React + Zustand yazıyor, gerçekte HTML + vanilla JS |
