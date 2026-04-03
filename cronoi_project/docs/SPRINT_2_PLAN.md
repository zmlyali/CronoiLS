# Sprint 2 Plan — Cronoi LS v2.0

**Başlangıç:** 28 Mart 2026  
**Durum:** 🔄 Aktif

---

## Faz 1 — Çekirdek Doğruluğu (Öncelik: KRİTİK)

> Hedef: DB kayıtları sağlıklı, statüler doğru, optimizasyon doğru çalışsın

| # | Görev | Durum | Detay |
|---|-------|-------|-------|
| 1.1 | 3D Palet Görünümü Bug Fix | 🔄 | Grid pozisyon hatası (row/col ters), stacking yükseklik hesaplama hatası |
| 1.2 | 3D TIR/Kamyon Görünümü Bug Fix | ⏳ | Yükseklik sınırı yok, quantity gösterimi 4'te duvar, taşma uyarısı eksik |
| 1.3 | Palet Taşma Görsel Uyarıları | ⏳ | Kırmızı vurgulama, yükseklik limit çizgisi, overflow göstergesi |
| 1.4 | Constraint API Tam Implementasyonu | ⏳ | Stub endpoint'ler → gerçek DB sorguları |
| 1.5 | Constraint Engine ↔ Optimizer Bağlantısı | ⏳ | Engine hazır ama optimizer çağırmıyor |
| 1.6 | Sevkiyat Statü Akışı Düzeltmesi | ⏳ | "failed" state eksik, hata durumu yönetimi |
| 1.7 | Reference No Race Condition | ⏳ | DB sequence kullanımına geçiş |

## Faz 2 — Eksik Fonksiyonlar

| # | Görev | Durum | Detay |
|---|-------|-------|-------|
| 2.1 | Shipment CRUD Tamamlama | ⏳ | Edit/Update endpoint'leri eklenmesi |
| 2.2 | Ürün Kataloğu API | ⏳ | Model var, endpoint yok |
| 2.3 | Araç Filosu API | ⏳ | Model var, endpoint yok |
| 2.4 | Sipariş → Sevkiyat Dönüşümü | ⏳ | Gruplama var ama dönüştürme yok |
| 2.5 | Senaryo Endpoint — Gerçek Optimizer | ⏳ | Basit FFD → optimizer.py 3D algoritma |

## Faz 3 — Optimizasyon Deneyimi & Görselleştirme

| # | Görev | Durum | Detay |
|---|-------|-------|-------|
| 3.1 | Canlı Optimizasyon Animasyonu | ⏳ | Ürünler palete tek tek yerleşme animasyonu |
| 3.2 | Profesyonel TIR/Kamyon Modeli | ⏳ | Daha gerçekçi kabin, kargo detayları |
| 3.3 | Senaryo Karşılaştırma Dashboard | ⏳ | Radar chart + maliyet analizi |
| 3.4 | Palet/Araç Kütüphanesi UI | ⏳ | Parametrik kütüphane yönetim ekranı |

## Faz 4 — Auth & Production

| # | Görev | Durum | Detay |
|---|-------|-------|-------|
| 4.1 | Firma Kodu + Kullanıcı Giriş Sistemi | ⏳ | Multi-tenant auth |
| 4.2 | Alembic Migration Kurulumu | ⏳ | create_all() → Alembic |
| 4.3 | Production Docker Konfigürasyonu | ⏳ | Cloud deployment (AWS/GCP) |
| 4.4 | Logging + Hata Takibi (Sentry) | ⏳ | Merkezi loglama |
| 4.5 | Rate Limiting + Güvenlik | ⏳ | CORS, HTTPS, input validation |

---

## Parametrik Palet Kütüphanesi

### Palet Tipleri

| Tip | Kod | Genişlik (cm) | Uzunluk (cm) | Max Yükseklik (cm) | Max Ağırlık (kg) | Alan (m²) | Not |
|-----|-----|:-------------:|:------------:|:-------------------:|:-----------------:|:---------:|-----|
| **EUR Palet (EPAL)** | `euro` | 80 | 120 | 180 | 1000 | 0.96 | Avrupa standardı, en yaygın |
| **Standart Palet** | `standard` | 100 | 120 | 180 | 1200 | 1.20 | Endüstriyel standart |
| **UK Palet** | `uk` | 100 | 120 | 180 | 1200 | 1.20 | İngiliz standardı |
| **Yarım Palet** | `half` | 60 | 80 | 180 | 500 | 0.48 | Küçük sevkiyatlar |
| **Çeyrek Palet** | `quarter` | 40 | 60 | 180 | 250 | 0.24 | Market/raf sevkiyatı |
| **Endüstriyel Palet** | `industrial` | 120 | 120 | 200 | 1500 | 1.44 | Ağır yükler |
| **Özel Boyut** | `custom` | (kullanıcı) | (kullanıcı) | (kullanıcı) | (kullanıcı) | — | Tam parametrik |

### Taşıma/Araç Tipleri

| Tip | Kod | İç Uzunluk (cm) | İç Genişlik (cm) | İç Yükseklik (cm) | Max Ağırlık (kg) | Palet Kapasitesi | Not |
|-----|-----|:----------------:|:-----------------:|:------------------:|:-----------------:|:----------------:|-----|
| **Panelvan** | `panelvan` | 350 | 180 | 180 | 1.500 | 2-4 | Küçük teslimatlar |
| **Kamyonet** | `kamyonet` | 430 | 205 | 200 | 3.500 | 4-6 | Şehir içi |
| **Kamyon (7.5t)** | `kamyon` | 700 | 240 | 240 | 8.000 | 12-14 | Orta mesafe |
| **Kamyon (12t)** | `kamyon12` | 850 | 245 | 250 | 12.000 | 16-18 | Orta-uzun mesafe |
| **TIR (13.6m)** | `tir` | 1360 | 245 | 270 | 24.000 | 33 | Uzun mesafe, standart |
| **Mega TIR** | `mega_tir` | 1360 | 245 | 300 | 24.000 | 33 | Yüksek kargo |
| **Konteyner 20ft** | `konteyner20` | 589 | 235 | 239 | 21.600 | 10-11 | Deniz taşımacılığı |
| **Konteyner 40ft** | `konteyner40` | 1203 | 235 | 239 | 26.500 | 21-23 | Deniz taşımacılığı |
| **Konteyner 40ft HC** | `konteyner40hc` | 1203 | 235 | 269 | 26.500 | 21-23 | Yüksek tavan |

### Maliyet Parametreleri (Araç Başına)

| Parametre | Açıklama | Örnek (TIR) |
|-----------|----------|:-----------:|
| `base_cost` | Sabit maliyet (₺) | 5.000 |
| `fuel_per_km` | Yakıt maliyeti (₺/km) | 12.5 |
| `driver_per_hour` | Sürücü ücreti (₺/saat) | 150 |
| `opportunity_cost` | Fırsat maliyeti (₺) | 1.000 |
| `toll_per_km` | Geçiş ücreti (₺/km) | 2.0 |

---

## Kısıt (Constraint) Sistemi

### Sistem Kısıtları (15 adet — seed data)

| Kod | Ad | Kategori | Optimizer Etkisi |
|-----|-----|----------|-----------------|
| `HORIZONTAL_ONLY` | Yatay Zorunlu | Oryantasyon | Ürün yatay yerleştirilmeli |
| `VERTICAL_ONLY` | Dikey Zorunlu | Oryantasyon | Ürün dikey yerleştirilmeli |
| `THIS_SIDE_UP` | Üstü Yukarı | Oryantasyon | Rotasyon yapılamaz |
| `NO_STACK` | Yığılmaz | Yığılabilirlik | Üstüne hiçbir şey konamaz |
| `MAX_WEIGHT_ABOVE` | Üst Ağırlık Limiti | Yığılabilirlik | Üstüne max X kg konabilir |
| `MUST_BE_BOTTOM` | Alt Sıra Zorunlu | Yığılabilirlik | Paletin en altına yerleşir |
| `MUST_BE_TOP` | Üst Sıra Zorunlu | Yığılabilirlik | Paletin en üstüne yerleşir |
| `COLD_CHAIN` | Soğuk Zincir | Ortam | 2-8°C, izole palet gerekir |
| `TEMP_SENSITIVE` | Sıcaklığa Hassas | Ortam | Soğuk zincir paletlerle paylaşabilir |
| `KEEP_DRY` | Kuru Tutulmalı | Ortam | Sıvı ile aynı palete konamaz |
| `HAZMAT_CLASS_1` | Tehlikeli Madde | Ortam | Tamamen izole palet + araç |
| `LOAD_FIRST` | İlk Yüklenmeli | Yükleme Sırası | Araca ilk giren |
| `LOAD_LAST` | Son Yüklenmeli | Yükleme Sırası | Araca son giren (ilk çıkar) |
| `VEHICLE_FRONT` | Araç Önü | Yükleme Sırası | Kabin tarafına yerleşir |
| `VEHICLE_REAR` | Araç Arkası | Yükleme Sırası | Kapı tarafına yerleşir |

### Uyumluluk Kuralları (Örnek)

| Kısıt A | Kısıt B | Kural | Seviye |
|---------|---------|-------|--------|
| COLD_CHAIN | HAZMAT_CLASS_1 | Aynı araca konamaz | ❌ Error |
| HORIZONTAL_ONLY | VERTICAL_ONLY | Çakışma — aynı palete konamaz | ❌ Error |
| FRAGILE | HEAVY | Aynı palete konamaz | ❌ Error |
| NO_STACK | (herhangi) | Üstüne ürün konamaz | ⚠️ Warning |
| MUST_BE_BOTTOM | MUST_BE_TOP | Aynı ürüne atanamaz | ❌ Error |

---

## Teknik Kararlar

| Karar | Seçim | Neden |
|-------|-------|-------|
| **Auth** | Faz 4'te (en son) | Önce çekirdek çalışsın, firma kodu + kullanıcı adı yapısı |
| **DB Migration** | Şimdilik create_all(), Faz 4'te Alembic | Çerçeve oturmalı önce |
| **Async İşlemler** | FastAPI BackgroundTasks | Celery'ye gerek yok şimdilik, ileride kolay geçiş |
| **Frontend** | HTML'de kal, JS modülerleştirme | Framework migrasyonu Faz 4 sonrası |
| **Deployment** | Cloud (AWS/GCP) değerlendirilecek | Henüz kesinleşmedi |

---

*Son güncelleme: 28 Mart 2026*
