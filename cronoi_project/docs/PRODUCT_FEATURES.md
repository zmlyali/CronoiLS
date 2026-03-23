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
