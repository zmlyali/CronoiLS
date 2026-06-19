# Cronoi LS — Kod Tabanı Referans Kılavuzu

> Bu dosya, `Cronoi_LS_v2.html` (~18 000 satır) ve FastAPI backend kodlarını
> kapsayan hızlı başvuru kaynağıdır. Değişiklik yapmadan önce buradan ilgili
> fonksiyon grubunu bul, ardından doğrudan satır numarasına git.

---

## 1. Proje Genel Yapısı

```
cronoi_project/
├── backend/
│   ├── app/
│   │   ├── main.py              — FastAPI app, CORS, router mount
│   │   ├── models.py            — SQLAlchemy ORM modelleri
│   │   ├── core/
│   │   │   ├── config.py        — Settings (env vars, DB URL)
│   │   │   ├── auth.py          — JWT yardımcıları, get_current_active_user
│   │   │   └── database.py      — AsyncSession factory, init_db()
│   │   ├── api/v1/
│   │   │   ├── auth.py          — /auth/login, /auth/refresh
│   │   │   ├── users.py         — /users (CRUD)
│   │   │   ├── orders.py        — /orders (CRUD + bulk import)
│   │   │   ├── shipments.py     — /shipments + optimize endpoint
│   │   │   ├── scenarios.py     — /scenarios
│   │   │   ├── transport_units.py — /transport-units (palet/araç tanımları)
│   │   │   └── vehicle_plans.py — /vehicle-plans (manuel araç planı)
│   │   └── services/
│   │       ├── optimizer.py     — 3D Bin Packing v9 (Rect-Skyline)
│   │       └── constraint_engine.py — Kısıt uyumluluk motoru
└── frontend/
    └── Cronoi_LS_v2.html        — Tek sayfa uygulama (~18 000 satır)
```

---

## 2. Frontend Genel Mimarisi

### 2.1 Global Nesneler

| Nesne | Satır | Açıklama |
|-------|-------|----------|
| `APP.state` | ~2963 | Tüm uygulama durumu (products, pallets, scenarios, orders …) |
| `APP.config` | ~2998 | palletTypes, vehicleTypes, constraints, engine parametreleri |
| `CPOOL` | ~3053 | Constraint pool — tüm kısıt tanımları (sistem + firma özel) |
| `API` | ~9610 | Backend iletişim katmanı (get/post/patch/delete/put/pollStatus) |
| `UI` | ayrı | Toast, badge, modal yardımcıları |

### 2.2 APP.state Kritik Alanlar

```javascript
APP.state.products        // Step 1'de girilen ürünler [{name, qty, length, width, height, weight, constraints, pallet_type}]
APP.state.pallets         // Oluşturulan paletler [{id, type, products, placedItems, totalWeight, layout, ...}]
APP.state.scenarios       // Araç optimizasyon sonuçları [{vehicles, totalCost, costPerPallet, engineUsed, ...}]
APP.state.selectedScenario // Aktif seçili senaryo
APP.state.selectedPalletType // Fallback palet tipi kodu (varsayılan: 'euro', ama _syncConfigFromDefs() sonrası P1-P10)
APP.state.orders          // Siparişler listesi
APP.state.shipmentId      // Aktif sevkiyat UUID (API mode)
APP.state.apiMode         // true = backend bağlı, false = local mod
APP.state.chosenFleetCode // Seçilen araç tipi kodu
```

### 2.3 APP.config.palletTypes — KRİTİK UYARI

`_syncConfigFromDefs()` (satır 13264) çağrıldıktan sonra `APP.config.palletTypes`
**tamamen silinip yeniden oluşturulur**. Başlangıçtaki `'euro'`, `'standard'`
anahtarları kalkar; artık yalnızca API'den gelen kodlar (P1, P2 … P10) bulunur.

**Her `palletTypes[key]` erişiminde fallback kullan:**
```javascript
const cfg = APP.config.palletTypes[pallet.type]
         || pallet.layout
         || Object.values(APP.config.palletTypes)[0]
         || { width:120, length:80, maxHeight:200 };
```

---

## 3. Sayfa / Ekran Sistemi

### 3.1 Sayfalar

| Sayfa id | Açıklama | Yükleyici |
|----------|----------|-----------|
| `dashboard` | Ana panel, KPI kartları, lens görünümleri | `loadDashboard()` |
| `orders` | Sipariş listesi, gruplamalar, Intel Bar | `renderOrdersList()` |
| `wizard` | Yükleme planı sihirbazı (6 adım) | `switchStep(n)` |
| `vehiclePlans` | Manuel araç planları listesi | `renderVehiclePlans()` |
| `history` | Tamamlanan sevkiyatlar | `renderCompletedShipments()` |
| `settings` | Palet/araç tanımları, tema, motor ayarları | çeşitli render fn |

Sayfa geçişi: `showPage(pageId)` (satır 11322)

### 3.2 Wizard — 6 Adım

| Adım | Ne Yapılır | Tetikleyici |
|------|-----------|-------------|
| 1 | Ürün girişi | `switchStep(1)` |
| 2 | Palet oluşturma & 3D görünüm | `_afterPalletGeneration()` → `switchStep(2)` |
| 3 | Palet tipi onay + özet | `approvePalletsAndContinue()` → `switchStep(3)` |
| 4 | Araç optimizasyonu | `switchStep(4)` + `autoOptimize()` (otomatik) |
| 5 | TIR 3D + yükleme planı + rapor | `switchStep(5)` |
| 6 | Tamamlama fotoğraf + özet | `switchStep(6)` |

`switchStep()` (satır 8818) — Adım geçişini, CSS active/completed state'ini ve
3D init/render tetiklemelerini yönetir. **Her step geçişinde burada yan etki var.**

---

## 4. Palet Sistemi

### 4.1 Palet Oluşturma

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `generatePallets()` | 4259 | Ana giriş: API mode → `/shipments/{id}/optimize`, local → `BinPackingOptimizer` |
| `generateMixedPallets()` | 4164 | Birden fazla palet tipi karıştırma |
| `_selectBestPalletType()` | 4054 | Otomatik palet tipi seçimi (doluluk skoru) |
| `_afterPalletGeneration()` | 10292 | `generatePallets()` sonrası: renderList + stats + step 2'ye geç |
| `_mapApiPallets()` | 10300 | API cevabını `APP.state.pallets` formatına dönüştür |

**`generatePallets()` içinde palet tipi belirleme mantığı:**
```javascript
const hasPerType = APP.state.products.some(p => p.pallet_type && p.pallet_type.trim() !== '');
// hasPerType=true → her ürün kendi pallet_type'ını kullanır
// hasPerType=false → hepsi APP.state.selectedPalletType kullanır
const key = (p.pallet_type && p.pallet_type.trim()) ? p.pallet_type : fallbackKey;
const cfg = APP.config.palletTypes[typeKey] || APP.config.palletTypes[fallbackKey];
```

### 4.2 Palet Görüntüleme

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `renderPalletList()` | 4443 | Sol panel palet listesi (her paleti kart olarak göster) |
| `togglePallet(id)` | 4509 | Palet detayını aç/kapat |
| `_renderPalletProductsDetail()` | 4521 | Palet içeriği (ürün listesi) |
| `_renderPalletSummaryPanel()` | 4625 | Sağ panel özet (boyutlar, ağırlık, fill rate) |
| `_renderStep3PalletSummary()` | 4210 | Step 3'teki palet özeti |
| `updatePalletStats()` | 4611 | İstatistik güncelleme |
| `calculatePalletFillRate()` | 4603 | Doluluk hesaplama |

### 4.3 Palet 3D (Step 2)

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `init3D()` | 3107 | Three.js sahnesini başlat |
| `update3DScene(pallet)` | 3164 | Seçili paleti 3D render et |
| `animate3D()` | 3427 | requestAnimationFrame döngüsü |
| `resetCamera()` | 3434 | Kamerayı sıfırla |
| `toggleWireframe()` | 3439 | Wireframe modu |

**Kritik satır 3168 — palet tipi null crash fix:**
```javascript
const palletType = APP.config.palletTypes[pallet.type || APP.state.selectedPalletType]
                || pallet.layout
                || Object.values(APP.config.palletTypes)[0]
                || {width:120, length:80, maxHeight:200};
```

### 4.4 Palet Tanım Yönetimi (Settings)

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `_syncConfigFromDefs()` | 13264 | **API'den gelen tanımları `APP.config` 'e yaz** (palletTypes + vehicleTypes tamamen sıfırlanır) |
| `_rebuildPalletTypeSelect()` | 13292 | Select elementlerini güncelle |
| `renderPalletDefGrid()` | 13308 | Settings ekranı palet tipi grid |
| `openPalletDefModal()` | 13452 | Palet tanımı ekle/düzenle modal |

---

## 5. OPTİMİZASYON (Palet + Araç) — Çekirdek Mühendislik ⭐

> Bu bölüm projenin en kritik kısmıdır. Aşağıdaki **çalışma sırası** ve **birleşik zemin
> paketleyici** mantığı korunmalıdır. Gerçek hayata aykırı sonuç (araç dışına taşma,
> arka arkaya dizip yan yana koymama, önden doldurmama) üretilmemelidir.
> Son büyük revizyon: **2026-06-15 (r14)** — birleşik `_packFloor` motoru.

### 5.0 Optimizasyon Çalışma Sırası (pipeline)

İki bağımsız katman vardır: **(A) ürün → palet** ve **(B) palet → araç**.

```
ADIM 2  ÜRÜN → PALET  (3D bin packing)
  generatePallets() [4349]
    ├─ API modu  → POST /shipments/{id}/optimize  (BACKEND optimizer.py BinPackingOptimizer3D)
    │              ⚠️ "API Bağlı" iken paketleme BACKEND'DE yapılır — frontend BinPackingOptimizer
    │                 ÇALIŞMAZ. Palet mantığı değişikliği HEM frontend HEM backend'e yapılmalı,
    │                 ve backend sunucusu YENİDEN BAŞLATILMALI. (placed_items GET /pallets'tan gelir.)
    └─ Lokal      → class BinPackingOptimizer [3602]
         _packItems(items)  — her ürün için:
            _getOrientations()  → kısıtlı/6 permütasyon, düşük-Z sıralı
            _findBestPosition() → aday pozisyonlar × yönelim, en iyi skor
               ├─ _baseZ()        → footprint altındaki kutuların tepe kotu (oturma yüksekliği)
               ├─ _supportRatio() → STABİLİTE KAPISI: istif tabanının ≥ minSupportRatioPct'i
               │                    desteklenmeli (yoksa pozisyon GEÇERSİZ → havada/devrik olmaz)
               └─ _settleXY()     → SIKIŞTIRMA: kutuyu -X/-Y'ye çekip boşlukları kapat
            _score()  → en düşük Z + zemin + bitişiklik + hizalama + zemin-kapasite + destek
            _commitPlace()  → placed_rects + placedItems + totalVolume/Height
         Kısıtlar: yükseklik (HARD), ağırlık, fragile/this_side_up/vertical uyumu (CPOOL)
         Taşma toleransı: pallet.layout.{width,length} × (1 + overflowTolerancePct/100)
  → APP.state.pallets[] (her biri: footprint layout.{width,length}, totalHeight, totalVolume,
    totalWeight, placedItems[], constraints[])
  STABİLİTE (2026-06-15 r15, FE+BE): Eskiden _baseZ/_base_y_from_rects %1 çakışmayı "destek"
    sayıyordu → kutular havada/dengesiz duruyordu (tır hareketinde kayar). Artık support oranı
    ≥ minSupportRatioPct (%70) ZORUNLU + sıkıştırma ile boşluklar kapatılır. İKİ YERDE de var:
      • Frontend: BinPackingOptimizer._supportRatio + _settleXY (lokal mod)
      • Backend:  BinPackingOptimizer3D._support_ratio + _settle_xz [optimizer.py] (API modu) ← asıl çalışan
    Ayar: engine_params.minSupportRatioPct → OptimizerSettings/Params (default 70).
    Test: FE /tmp/palpack.js (69/69), BE C:/tmp/test_support.py (73/73) — istifte her kutu ≥%70 destekli.
  BİRİM YÜK (2026-06-16 r16, FE+BE — group_same_products): "Aynı ürünleri grupla" ayarı AÇIKken
    her ürün KENDİ paletlerine yerleşir (karışmaz) ve özdeş ürünler TAM KATMANLI grid ile dizilir →
    tek-ürün, DÜZ TEPE, %100 destekli, tıra istiflenebilir "unit load" paletler. Yönelim seçimi:
    stabil 2D taban (duvar değil) > düz tepe (tam katman) > yoğunluk > ince katman. Bedeli: palet
    sayısı biraz artabilir (son palet kısmi). Tam bölünen adetlerde tepe-farkı=0; bölünmeyende sadece
    en üst katman kısmi (yine stabil). FE: _packGrouped/_packUniformGroup/_placeItemGrouped;
    BE: _pack_grouped/_pack_uniform_group/_place_item_grouped. Ayar engine_params.groupSameProducts.
    Eskiden bu ayar UI'da vardı ama HİÇBİR optimizer kullanmıyordu (ölü ayar). Test: BE/FE grup
    harness — 16 sandalye/8 kÜp/30 pano → düz tepe (0cm), 11 sandalye → 8'li blok + üstte 3 (stabil).

ADIM 4  PALET → ARAÇ  (fleet optimizasyonu)
  autoOptimize() [12195] → _autoOptimizeLocal() [12284]
    optimizeForMinVehicles() [8620]  ┐  her biri:
    optimizeBalanced()       [8648]  ├─ _evalAllFleets(pallets) [8457]
    optimizeForEfficiency()  [8710]  ┘     ├─ _computeEffectiveAllowedVehicleTypes() [8428] (HARD filtre)
                                           ├─ _checkHeightFitability() [8406] (palet boyu > araç içi → tip elenir)
                                           └─ _buildFleetOfType() [8521] (FFD + GERÇEK zemin sığması)
                                                  └─ _packFloor() [6090]  ← BİRLEŞİK MOTOR
  → APP.state.scenarios[]  (her senaryo: vehicles[], totalCost, avgFillRate, ...)

ADIM 5  3D YERLEŞİM  (görsel — optimizer ile AYNI motor)
  renderSelectedTruck() → _buildTruck3D() → _placePallets3D() [6198]
     └─ _packFloor() [6090]  ← AYNI MOTOR → görsel optimizasyonla ASLA çelişmez
        sığmayan → _placeLeftoverPallets() [6288] (üst kata istif / belirgin taşma)
```

**Kritik ilke:** `_buildFleetOfType` (kapasite/atama) ve `_placePallets3D` (3D konum)
**aynı** `_packFloor` fonksiyonunu çağırır. Eskiden iki ayrı mantık vardı → optimizer
"sığar" derken görsel araç dışına taşıyordu (r14 öncesi bug).

### 5.1 Birleşik Zemin Paketleyici — `_packFloor()` [6090] ⭐

2B **Raf/Şerit paketleme + FFDH + yönelim seçimi**. Saf fonksiyon (THREE/DOM yok → test edilebilir).

| Özellik | Davranış |
|---------|----------|
| **Önden doldurma** | Raflar araç UZUNLUĞU (X) boyunca ön (`-vL/2`) → arka ilerler; ön aks önce |
| **Yan yana (döndürme)** | Her palet 0°/90° denenir; yeni rafta **en çok sütun veren** yönelim seçilir |
| **Bitişik genişlik** | Raf içinde paletler yan yana **boşluksuz** (gerçekte duvara/birbirine değer) |
| **Raf arası boşluk** | `engine.palletGapCm` (Ayarlar; forklift/bağlama payı) |
| **Duvar payı** | `marginCm` (varsayılan 1 cm/kenar) |
| **Uzunluk sınırı** | Araç içini aşan palet **yerleştirilmez** (`unplaced`) → istif veya sonraki araç |
| **Raf-içi yerleşim** | En küçük `across` → kalan genişliğe en çok palet (uniform'da tam grid) |

**Dönüş:** `{ placed:[{id,xCm,zCm,rotDeg,wCm,lCm}], unplaced:[id], usedLenCm, shelfCount }`
(xCm/zCm = palet merkezi, araç merkez-orijinli cm).

**Doğrulanmış sonuçlar** (node harness, `/tmp/packfloor.js`):
- EUR 80×120 → TIR 1360×245: **33 palet** (gerçek dünya standardı), 3-across, 11 raf, taşma yok
- EUR×34 → 33 yerleşir + 1 sonraki araca
- Büyük 200×120 ×22 → 12 yerleşir + 10 sonraki araca (görseldeki taşma bug'ı çözüldü)
- Dar araç → palet otomatik döner; karışık boyut + konteyner → çakışma/taşma yok

**Literatür:** Coffman–Garey–Johnson–Tarjan (1980) Shelf/FFDH; Dowsland (1992) Pallet
Loading Problem; George & Robinson (1980) konteyner duvar-duvar yükleme.

**Bilinen sınır (güvenli taraf):** Saf raf-packer uniform paletlerde optimaldir (EUR→33);
konteynerde "pinwheel" karışık-yönelim desenini kullanmaz → kapasiteyi **düşük** tahmin
edebilir (asla taşmaz). PLP-optimal (maximal-rectangles) gelecekteki geliştirme.

### 5.2 `_buildFleetOfType()` [8521] — FFD + gerçek zemin sığması

```javascript
// Ağır paletler önce (ön aks + paketleme). Bir palet bir araca eklenebilir mi?
//   1. ağırlık ≤ maxWeight   2. hacim ≤ usable   3. floorFits() = _packFloor(unplaced==0)
// Yeni araç açarken palet boş araca bile sığmıyorsa → tip infeasible → return []
const floorFits = (objs, p) => _packFloor(_floorItemsFromPallets([...objs, p]),
                                          vtConfig.length, vtConfig.width, gapCm, 1).unplaced.length === 0;
```
Eski `assignedPallets.length < maxSlots` slot-sayısı tahmini **kaldırıldı**; kapasite artık
gerçek yerleşimle (floor-fit) belirlenir. `_computePalletSlots` yalnızca `palletCapacity`
gösterimi için kalır (en-iyi-yönelimli grid).

### 5.3 Sipariş araç-tipi kısıtı (HARD) — `_computeEffectiveAllowedVehicleTypes()` [8428]

Aktif siparişlerin `allowed_vehicle_types` **kesişimi**; herhangi biri kısıtlıysa yalnızca
ortak tipler kullanılır. 3 noktada uygulanır: `_evalAllFleets` (oto, satır ~8470), karşılaştırma
tablosu ("🚫 Sipariş kısıtı"), `_applyFleetOption` (manuel, toast ile reddet). Kaynak:
`APP.state.activeOrderIds` + `pallet.orderId` (pre-pack). Boş kesişim = hiç araç (uyumsuz kısıt).

### 5.4 Doluluk/Hacim — KULLANILABİLİR hacme göre — `_vehUsableVol()` [8447]

Tüm doluluk göstergeleri **brüt değil usable** hacmi denominator alır: araç tipinde
`usable_volume_m3` tanımlıysa o, değilse brüt iç hacmin `engine.usableVolumeFactorPct`
(%90) kadarı. Kullanan yerler: `_buildFleetOfType` vVol, `_calcFleetFillRate/Volumes`,
3D HUD overlay, MVP kapasite barları.

### 5.5 Strateji Fonksiyonları & Maliyet

| Fonksiyon | Satır | Strateji |
|-----------|-------|----------|
| `optimizeForMinVehicles()` | 8620 | En ucuz TEK TİP filo (3 panelvan vs 1 TIR) |
| `optimizeBalanced()` | 8648 | Büyük tip ana + küçük tip artık paletler |
| `optimizeForEfficiency()` | 8710 | En yüksek doluluk |
| `_applyFleetOption(vtCode)` | 8971 | Manuel tip seç → `engineUsed:'manual'` |

Maliyet: `baseCost + fuelPerKm·distance + driverPerHour·duration + opportunityCost`
(araç tipinde tanımlı; yoksa `_getVehDefaults` / `VEHICLE_COST_DEFAULTS`).

**Manuel senaryo koruması** — `renderComparison()` sadece `engineUsed !== 'manual'`
senaryoları gösterir (max 3); manuel 4. eleman olunca null crash'ini önler.

### 5.6 Ayarlardan gelen optimizasyon parametreleri (`APP.config.engine`)

| Parametre | Varsayılan | Etki |
|-----------|-----------|------|
| `palletGapCm` | 3 | Raflar arası boşluk (zemin) + palet-içi kutu boşluğu |
| `overflowTolerancePct` | 5 | Palet kenarı taşma toleransı (item packing) |
| `minSupportRatioPct` | 70 | İstiflenen kutu tabanının min destek oranı (stabilite; altı boşsa devrilir) |
| `groupSameProducts` | false | Birim yük: aynı ürünü aynı palete grupla → tek-ürün, düz tepe, tıra istiflenebilir (palet sayısı artabilir) |
| `usableVolumeFactorPct` | 90 | usable_volume_m3 yoksa brüt × bu oran |
| `heightSafetyMargin` | 0 | Palet max yükseklikten düş (cm) |
| `enforceConstraints` | true | fragile/this_side_up/vertical ayrımı |
| `maxIterations` | 12 | Değerlendirilen araç/palet tipi limiti |

**Araç kodları:** `panelvan · kamyonet · kamyon_mid · kamyon_buyuk · tir_standart · tir_mega · konteyner20 · konteyner40 · konteyner40hc`

---

## 6. TIR 3D Görselleştirme (Step 5)

> **Araç-tipine duyarlı mimari (2026-06 revizyonu):** `_buildTruck3D` artık
> `_getVehicleKind(vehicle)` ile aracı sınıflandırır ve tipe göre dış gövde çizer.
> Paletler tek global ölçü yerine **her paletin gerçek `layout.width/length` ölçüsüyle**
> birebir ölçekli çizilir (`_palletFootprint`). Satır numaraları yaklaşıktır (THREE r128).

| Fonksiyon | Açıklama |
|-----------|----------|
| `initTruck3D()` | Three.js sahnesi; depo zemini artık `warehouse-env` adlı grupta (konteynerde gizlenir) |
| `renderSelectedTruck()` | Seçili aracı render; `kind==='container'` → gemi/deniz arka planı + `warehouse-env` gizle |
| `_getVehicleKind(vehicle)` | `vehicle.code`/`type` → `'container'` \| `'van'` \| `'truck'` |
| `_buildTruck3D(vehicle)` | Materyaller + paylaşılan iç hacim (taban/raylar/tavan lambası) + tip-bazlı gövde dallanması |
| `_buildTrailerExterior(group,v,L,H,W,EL,M)` | TIR/kamyon: kabin + dorse + tekerlekler (eski gövde buraya taşındı) |
| `_buildContainerExterior(group,v,L,H,W,EL)` | ISO konteyner: oluklu çelik, 8 köşe kilidi, twist-lock, kilit çubukları, **gemi güvertesi + deniz** |
| `_buildVanExterior(group,v,L,H,W,EL,M)` | Panelvan: tek parça kasa + entegre kabin burnu + 4 tekerlek |
| `_makeCorrugatedTexture(hex)` | Konteyner duvarı için oluklu çelik CanvasTexture |
| `_palletFootprint(pallet)` | Paletin gerçek taban ölçüsü (m) — `pallet.layout` öncelikli, fallback `selectedPalletType` |
| `_placePallets3D()` | **Birleşik `_packFloor` [6090] motorunu çağırır** (optimizer ile aynı) → döndürme + önden doldurma + uzunluk sınırı; sığmayan → `_placeLeftoverPallets()` (istif/taşma). Kayıtlı manuel yerleşim (`vehicle.placements`) varsa onu uygular. Bkz. §5.1 |
| `_packFloor(items,vLcm,vWcm,gapCm,marginCm)` | **Birleşik 2B zemin paketleyici** (FFDH raf + yönelim). Saf fonksiyon; optimizer + 3D aynı kaynak. Bkz. §5.1 |
| `_placeLeftoverPallets()` | Zemine sığmayan paletleri uygun zemin paletinin üstüne istifler (yükseklik/kısıt uygunsa); olmazsa arka taşma bölgesi |
| `_buildPallet3D(p,px,py,pz,PW,PL,drawEdges)` | EUR-stili taban (güverte+3 ayak) + ürün kutuları; `palletMaxH` artık `pallet.layout.maxHeight`'tan |
| `_drawExteriorView()` | 2D yan görünüm (hâlâ TIR silüeti — konteyner/van için güncellenmedi) |
| `_enterInteriorMode()` | Kabine giriş (FPS benzeri) |
| `toggleTruckWireframe()` | Wireframe |
| `buildTruckSelector()` / `selectTruck(idx)` | Araç seçim tabı |

**Araç kitleri (`_getVehicleKit`):** kod → `{body, env, reefer}`. `body`: container / van /
rigid (kamyon·kamyonet: `_buildRigidExterior`) / trailer (tır). `reefer` ise ön duvara
`_addReeferUnit` ile soğutma ünitesi eklenir.

### 6.1 Manuel Yükleme Editörü (`TruckEditor`)

Step 5'te **Düzenle** butonu (`toggleTruckEditMode`) ile açılır. Origin-local palet grupları
(`_buildPallet3D` artık `(pallet, PW, PL, drawEdges)` — çocuklar lokal, grup `.position/.rotation.y`
ile taşınır) ve `truckPalletNodes[palletId] = {group, px, pz, baseY, PW, PL, rot, stackUnder, stackLevel, pallet}`
kayıt defteri üzerine kurulu. Tüm paletler `_addPalletToTruck` (tek kaynak) ile eklenir.

| Fonksiyon | Açıklama |
|-----------|----------|
| `toggleTruckEditMode()` | Görüntüle↔Düzenle; tepe kamera + ızgara + HUD + klavye |
| `_editorPointerDown/Move/Up` | Seç + zemine sürükle (ray→`dragPlane`), ızgara yapışma, çarpışma, bırak |
| `_editorRotate(dir)` | Seçili paleti 90° döndür (R tuşu); footprint takas |
| `_findStackTarget`/`_canStack` | Üst üste bırakınca istif (kısıt kontrolü: no_stack/fragile/must_top/heavy/yükseklik) |
| `_editorUnstackSelected()` | İstiften zemine indir |
| `_editorState/_editorApply/_editorUndo/_editorRedo` | Komut yığını (Ctrl+Z/Y) |
| `_editorViolations()` | Sert ihlaller: taşma, çakışma, yükseklik, kaçak istif (kayıt engeli) |
| `_updateEditorHUD()` | Canlı telemetri: ağırlık/aks dengesi/CoG/doluluk/uyarılar |
| `saveTruckLayout()` | İhlal yoksa `placements[]` serialize → `vehicle.placements` + plan PATCH |
| `_editorResetToOptimized()` | `vehicle.placements=null` → oto-paketleme |

**Kalıcılık (Faz 3):** `placements = [{pallet_id, vehicle_index, pos_x_cm, pos_z_cm, rot_deg, stack_level, stack_under_pallet_id}]`.
Kaydetme `approveVehiclePlan` payload'ına ve `VehicleItemSchema` (backend, JSONB — migration yok) `placements/manual_edited/layout_locked`
alanlarına yazılır. `_placePallets3D` `vehicle.placements` varsa oto-paketlemeyi atlayıp kayıtlı düzeni uygular
(`_addPalletToTruck` ile). `jumpToShipmentStep` tekrar açılışta plana ait placements'ı senaryoya bağlar → **"böyle kalmalı."**

### 6.2 Editör — Gelişmiş Etkileşim (2026-06-14 r2)

| Özellik | Fonksiyon | Not |
|---------|-----------|-----|
| 360° serbest bakış | `toggleTruckEditMode` artık `truckViewMode='perspective'` | Boş alanı sürükle=yörünge, paleti sürükle=taşı; "Tepe" butonu `toggleTruckView` |
| Oyunlaştırma | `_editorBurst`/`_editorBounce`/`_editorTickFX` | Geçerli bırakışta yeşil snap halkası + ✓ sprite + palet zıplama; istifte altın ⬆. `animateTruck3D` içinde tick |
| Çok katlı istif | `_findStackTarget` (üst yüzey hedefleme) + `_isInStackChain` (döngü koruması) | `stackLevel = (taban.stackLevel)+1`; yükseklik `_canStack` ile sınırlı |
| Kasalı paket | `_editorToggleCrate` + `_buildPallet3D` `pallet.isCrate` dalı | Crate kapalı ahşap kasa render; `_canStack` crate tabanda fragile/no_stack baypası (no_stack hariç) |
| Araçlar arası çekme | `toggleEditorPull`/`_renderEditorPullPanel`/`_editorPullPallet` | Diğer araçların paletini bu araca taşı; `_editorFindFreeSpot` boş yer bulur; `_pruneVehicleRefs`/`_recalcVehicleAgg` |
| Boş aracı eleme | `_editorRemoveEmptyVehicle` | Boşalan aracı filodan çıkar → maliyet düşer |
| Çoklu araç kalıcılık | `saveTruckLayout` tüm `sc.vehicles` PATCH | `_currentPlacements`; çekme/eleme dahil tüm araçlar yazılır, notlar korunur |

### 6.3 Akıllı Yapışma (snap-to-fit, 2026-06-14 r3)

Paleti seçince (drag başı) sığabileceği **aday yuvalar** hesaplanıp zeminde gösterilir; sürüklerken
en yakına **mıknatıs** gibi oturur, **gerekirse otomatik 90° döner**, küçük toleransları (≤3cm) yutar.
Tam sıkı oturunca (snug≥3) **sinematik ışıltı**.

| Fonksiyon | Açıklama |
|-----------|----------|
| `_editorComputeSlots(node)` | Duvar/komşu kenarlarına hizalı aday merkezler (2 yön), tolerans ile fit testi → `TruckEditor.slots` (en snug 40) |
| `_editorSnugness(cx,cz,fx,fz,exclId)` | Kaç kenar duvara/komşuya temas ediyor (≥3 = mükemmel) |
| `_editorBuildSlotMeshes`/`_editorClearSlots` | Yuva footprint hatları + dolgu; snug≥3 yeşil, diğer mavi |
| `_editorNearestSlot`/`_editorHighlightSlot` | İmlece en yakın yuva; aktif yuvayı parlat |
| `_editorSnapRadius(node)` | Mıknatıs yarıçapı |
| `_editorSparkle(x,z,baseY)` | Çoklu halka + 9 yıldız parçacığı (FX 'spark' + gecikmeli 'ring') |

`_editorPointerMove`: istif hedefi > mıknatıs yuva > serbest. `_editorPointerUp`: yuvaya tam yapış +
snug≥3 ise `_editorSparkle` ("🌟 Tam oturdu"), değilse normal `_editorBurst`. `_editorTickFX` 'spark'
ve negatif-t (gecikmeli) destekler.

**Belirgin yerleşim pad'i (r5):** `_buildPadGroup(ewM,edM,color)` → çerçeve + 4 köşe L-braketi +
parıltı dolgusu, **`depthTest:false` + yüksek renderOrder** → araç gövdesinin/zeminin **üstünde her
zaman görünür** (kapalı treyler/konteyner dahil tüm tiplerde). `_editorSelRect`/`_pSelRect` bunu kullanır;
sürüklerken renk gerçek-zamanlı: yeşil=sığar, kırmızı=sığmaz, altın=istif, mint=mükemmel. Yuvalar da
`depthTest:false`. **Not:** editör hiçbir zaman araç tipine bağlı değildi; "konteyner-only" algısı
göstergelerin gövde arkasında kalmasındandı — pad/yuva artık üstte çiziliyor.

**Sıradaki:** öneri motoru / AI ile konuşarak otomatik optimize (slot skorları zaten hazır altyapı).

### 6.4 Palet-İçi Ürün Editörü (Faz 4, 2026-06-14 r4)

Step 2 palet 3D'sine (`scene`/`camera`/`renderer`) **aynı snap-to-fit motoru** taşındı. `update3DScene`
`placedItems` dalı artık her ürünü **origin-local grup** olarak çizer ve `palletItemNodes[idx] =
{group, item, cx, cz, bz, odx, ody, odz, rot}` (merkez-tabanlı, cm) kayıt defterine yazar.
`_current3DPallet` aktif paleti tutar.

| Fonksiyon | Açıklama |
|-----------|----------|
| `togglePalletEdit` | Düzenle modu (Step 2 "Düzenle" butonu); ızgara + HUD + klavye |
| `_pPointerDown/Move/Up` | Ürünü seç + deck düzleminde sürükle; parlak yeşil aday yuvalar; mıknatıs snap |
| `_pComputeSlots`/`_pSnugness`/`_pBuildSlotMeshes` | Taban-katman aday yuvaları (duvar/komşu kenarına flush), neon additive parlama |
| `_pRestHeight` | **Yerçekimi**: üstüne bırakınca alttaki kutunun üstüne oturur (otomatik istif) |
| `_pRotate` | 90° döndür (R); kayıtta boyut takas edilir (bake) |
| `_pValidAt`/`_pViolations` | Palet sınırı + maxHeight; ihlalde kayıt engeli |
| `_pSparkle`/`_pBurst`/`_pBounce`/`_pTickFX` | snug≥3 sinematik ışıltı; `animate3D` içinde tick |
| `_pState/_pApplyState/_pUndo/_pRedo` | Komut yığını (Ctrl+Z/Y) |
| `savePalletLayout` | `_current3DPallet.placedItems`'a geri yaz (rot bake) + `totalHeight` + re-render |

Pointer routing `setupControls` içinde (PalletEditor.on iken).

**Backend kalıcılık (r5):** `savePalletLayout` → `PATCH /shipments/{id}/pallets/{pallet_number}`
(`pallet.id` = pallet_number) → `Pallet.layout_data.placed_items` + `total_height_cm`.
`get_pallets` çıktısına `placed_items`/`manual_edited` eklendi; `_mapApiPallets` `ap.placed_items`
varsa doğrudan kullanır → manuel palet düzeni DB'de kalıcı, tekrar açılışta yüklenir.
Tır düzeni zaten `VehiclePlan.vehicles[].placements` JSONB'de kalıcı (`saveTruckLayout` PATCH).

### 6.6 Birleşik OO Editör — `class LoadEditor` (r6) ⭐

İki paralel editör (`TruckEditor`/`PalletEditor` fonksiyon yığınları → **artık ölü kod**) tek bir
**nesne-yönelimli `LoadEditor` sınıfında** birleşti. Domain farkları **adaptör** ile soyutlanır;
hem araç/konteyner hem palet **aynı koddan** beslenir → tüm araç tiplerinde garantili parite.

- **Birimler metre**, konteyner orijinde merkezli. **Yerçekimiyle istif** (üst üste bırak → alttakinin üstüne oturur) tek model.
- `truckEditorAdapter` (truckPalletNodes) · `palletEditorAdapter` (palletItemNodes, cm↔m). Örnekler: `truckLoadEditor`, `palletLoadEditor`.
- Eski global adlar (`toggleTruckEditMode`, `_editorRotate`, `savePalletLayout`, `_pRotate`…) **ince delegatörlere** dönüştü → HTML/pointer aynen çalışır.
- Adaptör arabirimi: `scene/camera/raycaster/mouse/floorY/bounds/nodeList/idOf/idFromHit/pickMeshes/foot/baseFoot/pos/setPos/rotOf/setRot/heightOf/weightOf/labelOf/els/onEnable/onDisable/renderHUD/persist/reset`.
- Pointer: `setupTruckControls`/`setupControls` → `*LoadEditor.pointerDown/Move/Up`; FX: `animate*` → `*LoadEditor.tickFX()`.

**Hazırlık (staging) alanı:** taşıma biriminin yanında sarı "HAZIRLIK ALANI" zonu. Öğeyi oraya
sürükle / **Kenara Al** → `staged`; geri sürükle / **İndir** → yeniden diz. Hazırlıkta öğe varken
**kayıt engellenir**. `stageSelected`/`dropToFloor`/`_stageBounds`/`inStaging`. Görünürlük pad/yuva `depthTest:false`.

**Asist + yönelim + geniş staging (r7):**
- **Asist:** geçersiz bırakışta geri almak yerine **en yakın uygun boşluğa otomatik oturur** (`pointerUp` `near.slot`); sürüklerken en yakın yuva ipucu parlar; snap yarıçapı footprint×1.1.
- **Yönelim (tipping):** `rotate` → adaptör `cycleOri` ile **4 alternatif** dolaşır. Palet kutuları: 0/1 dik (yaw) + 2/3 **yan yatış** (`_descAll` euler + fw/fd/h, X/Z ekseni). Kısıt `this_side_up`/`vertical` → yalnız dik. Tır paletleri yaw-only. `isTipped` → slot-snap atlanır (yatık yön korunur). Kayıt yönelimli boyutları **bake** eder.
- **Staging genişliği:** `_stageBounds` adaptör `stageW`/`stageD` çarpanları — palet `2.6×4.5`, tır `1.1×1.6`.

**Ölü kod TEMİZLENDİ (r8):** eski `const TruckEditor`/`PalletEditor` + tüm `_editor*`/`_p*` legacy
fonksiyonları (~780 satır) silindi. Korunan paylaşılan yardımcılar (`_overlapXZ`, `_buildPadGroup`,
`_disposePadGroup`, `_recalcVehicleAgg`, `_P_DECK_Y`, `_pPalletDims`) sınıftan önce tek blokta yeniden
tanımlı. Legacy crate & cross-vehicle-pull UI/HTML kaldırıldı. Aktif yol tamamen OO: `LoadEditor` + adaptörler.

**Kaynak paneli (SourceTray, r9):** Düzenleme modunda **"Kaynak"** butonu → diğer birimlerden öğe çek
veya yeni oluştur; gelen öğe **staging alanına** düşer, yerleştirip kaydedersin. Tek soyutlama, her ikisinde:
- Sınıf: `toggleSourcePanel`/`_renderSourcePanel`/`importSource(key)`/`newUnit`/`_stageImported(id)`.
- Adaptör arabirimi: `gname`, `newLabel`, `sources()` → `[{title, items:[{key,label,sub}]}]`, `spawn(key,ed)` → yeni node id, `createNew(ed)` → yeni node id, `els().source`.
- **Tır:** `sources` = diğer araçların paletleri; `spawn` paleti araçlar arası taşır (assignedPallets+placements güncellenir, `_spawnNode`→`_addPalletToTruck`); `createNew` boş palet ekler. Kayıt zaten çoklu-araç PATCH.
- **Palet:** `sources` = diğer paletlerin kutuları (kararlı **`uid`**); `spawn` kutuyu paletler arası taşır (`_markDirty`); `createNew` 40³ kutu. Kayıt: mevcut + `_dirtySet` kaynak paletleri `PATCH /pallets/{n}`.
- Altyapı: `update3DScene` ürün çizimi `_buildPalletItemNode` (global, kararlı uid) ile paylaşıldı; palet adaptörü `idOf=uid` (rebuild'e dayanıklı).

---

## 6.8 Sipariş Haritası (Leaflet, r10)

Yeni sayfa **`map`** (`PAGES`'e eklendi, `nav-map` "Harita", `page-map` div, `showPage`→`initOrderMap`).
Leaflet 1.9.4 (CDN, anahtarsız) + CartoDB **dark** tiles. Siparişler **adrese (şehir+ülke) göre**
geocode edilir — **offline gazetteer**: `GEO_TR` (81 il) + `GEO_WORLD` (uluslararası) + `GEO_ALIAS` +
`GEO_COUNTRY` (ülke merkezi fallback). `_geocodeOrderCity(city,country)` ayraç bölme + `_normGeo`
(TR diakritik normalize). Şehir bazında gruplanır (performans), tek marker + popup.

| Fonksiyon | Açıklama |
|-----------|----------|
| `initOrderMap` | Leaflet'i lazy kur, siparişleri yükle, `renderOrderMap` |
| `renderOrderMap` | Filtre uygula → şehir grupla → marker'lar + `fitBounds` + sayaçlar |
| `_omBucket(status)` | delivered→`done`, in_transit/loaded→`transit`, diğer→`open` |
| `_orderMarkerIcon` | DivIcon: yolda=turuncu **nabız**, açık=mavi, teslim=yeşil **✓**; çoklu=sayı |
| `_orderCityPopup` | Şehirdeki siparişler + durum + "Listede gör" |
| `setOrderMapFilter`/`_renderOrderMapFilters` | Chip: Tümü/Açık/Yolda/Teslim (sayılı) |

Markerlar/nabız/chip CSS'i head'de ayrı `<style>` (`.omk`, `.omk-pulse`, `.omf-chip`). Bilinmeyen
şehirler "haritalanamadı" notuyla sayılır.

**Tam adres + araç tercihi (r11):**
- **Hassas geocode:** `_orderCoord(o)` → tam `address` varsa **Nominatim cache**'ten hassas konum, yoksa şehir gazetteer, sonra ülke. `_refineAddresses()` arka planda throttled (≤1 istek/sn) Nominatim geocode yapar, `localStorage('cronoi_geocache')`'e yazar, marker'ı hassas konuma taşır (`_addrKey`, `_geoCacheLoad/Save`). Gruplama artık **koordinat bazında** (0.001° yuvarlama).
- **Araç tercihi:** popup'ta her sipariş satırında `o.allowed_vehicle_types` ikonları (`_vehMeta`/`_vehChips`) + marker başında `_vehSummary` ("Tercih: 🚛×2 🚐×1"). Kullanıcı hangi siparişin hangi aracı istediğini görüp konsolide karar verebilir. Esnek (kısıtsız) = "esnek".

## 7. Yükleme Planı

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `generateLoadingSequence()` | 6486 | Yükleme sırası oluştur |
| `sortPalletsForLoading()` | 6507 | Paletleri yükleme sırasına göre sırala |
| `calculateLoadingPosition()` | 6524 | Her palet için araç koordinatı |
| `calculatePalletPositions()` | 6533 | Tüm paletler için pozisyon hesabı |
| `calculateAndDisplayWeightBalance()` | 6553 | Ağırlık dengesi (ön/arka aks) |
| `displayLoadingStats()` | 6647 | İstatistik göster |
| `renderLoadingSequence()` | 9578 | Yükleme sırası listesi |
| `renderVehiclePlanReport()` | 6805 | Araç plan raporu |
| `printLoadingPlan()` | 6674 | Yazdır |
| `exportLoadingPlan()` | 6678 | Dışa aktar |

---

## 8. Sipariş Sistemi

### 8.1 Sipariş Listesi & Görüntüleme

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `renderOrdersList()` | 13864 | Ana liste render (filtreli, sıralı) |
| `_renderOrdersIntelBar()` | 13760 | Üst durum çubuğu (5 aşamalı pipeline) |
| `_oibFilter(status)` | 13856 | Intel bar tıklaması → filtre uygula |
| `toggleOrderDetail(orderId)` | 14012 | Sipariş satırını genişlet/daralt |
| `sortOrders(key)` | 14023 | Sıralama |
| `_updateOrdersBadge()` | 13741 | Sidebar sipariş sayısı badge |
| `_updateOrdersSummaryLine()` | 13747 | Özet satırı güncelle |

**Sipariş durum akışı:**
```
pending → in_planning → pallet_planned → vehicle_planned → loaded → in_transit → delivered
cancelled (herhangi adımdan)
```

Sıra fonksiyonu: `_getOrderStageRank(status)` (satır 11484)

### 8.2 Sipariş Gruplama

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `_groupOrders(orders, by)` | 14117 | Gruplama mantığı |
| `_renderOrdersGrouped()` | 14153 | Gruplandırılmış liste render |
| `_toggleGroupCheckboxes()` | 14259 | Grup içi checkbox toggle |
| `_selectGroupOrders(tableDiv)` | 14266 | Tümünü seç — `tableDiv` doğrudan tablo div olmalı |
| `_addGroupToShipment(orderIds)` | 14275 | Grubu sevkiyata ekle |
| `toggleGroupingPanel()` | 14295 | Gruplama paneli aç/kapat |
| `renderGroupingPanel()` | 14570 | Panel içeriğini render et |

**Gruplama seçenekleri (`by` parametresi):**
```
'customer'     → Müşteriye göre
'week'         → Haftaya göre
'month'        → Aya göre
'city'         → Hedef şehre göre (o.city)
'city_customer'→ Şehir + müşteri bileşik
```

**"Tümünü Seç" butonu DOM navigasyonu — kritik:**
```javascript
// YANLIŞ (eski hata): closest('div') → inner flex div → nextSibling = <i chevron>
// DOĞRU:
_selectGroupOrders(this.closest('div[onclick]').nextElementSibling)
// closest('div[onclick]') → header div → nextElementSibling = tablo container
```

### 8.3 Sipariş CRUD

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `openNewOrderModal()` | 14896 | Yeni sipariş formu |
| `_addOrderItemRow()` | 14996 | Ürün satırı ekle (palet tipi select dahil) |
| `openEditOrderModal(orderId)` | 15069 | Düzenle |
| `_oamAction(event, action, orderId)` | 16247 | Sipariş aksiyon menüsü (sil, kopyala, vb.) |
| `_toggleOrderMenu(btn, orderId)` | 16168 | Dropdown menü |

**`_addOrderItemRow()` palet tipi seçeneği:** İlk option her zaman boş olmalı
(varsayılan = sipariş seviyesi palet tipi):
```javascript
const ptOptions = `<option value="">— Varsayılan —</option>` + Object.entries(APP.config.palletTypes)…
```

### 8.4 Sipariş → Wizard Akışı

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `_loadOrdersIntoWizard(orders)` | 14741 | Siparişleri wizard'a yükle (products dizisini doldur) |
| `addOrderToShipment(orderId)` | 14831 | Tek sipariş ekle |
| `_detectSmartStep(orderStatus)` | 14848 | Sipariş durumuna göre wizard adımını belirle |
| `createShipmentFromSelected()` | 14055 | Seçili siparişlerden sevkiyat oluştur |
| `newShipment()` | 17079 | Yeni boş sevkiyat |

### 8.5 Excel Import

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `downloadTemplate()` | 9534 | Excel şablon indir |
| `handleFileUpload(event)` | 9548 | Excel dosyası yükle |
| `_showImportPreview(orders)` | 16551 | Import önizleme |
| `_saveImportedOrders()` | ~16371 | Toplu kaydet → `POST /orders/bulk` |
| `_excelDateToISO(val)` | 16663 | Excel serial tarih → ISO |

---

## 9. Dashboard

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `loadDashboard()` | 11356 | Ana yükleyici (API'den veri çek) |
| `_computeDashboardMetrics()` | 11748 | KPI hesaplama |
| `_renderOpsLens()` | 11784 | Ops lens render |
| `_renderPlanLens()` | 11846 | Planlama lens render |
| `_renderExecLens()` | 11900 | Yürütme lens render |
| `setDashboardLens(lens)` | 11943 | Lens geçişi (ops/plan/exec) |
| `_renderDashboardOrders()` | 11972 | Dashboard sipariş özeti |
| `_renderDashboardRecentShipments()` | 12008 | Son sevkiyatlar |
| `_buildLoadGroups()` | 11646 | Yükleme grubu oluştur |
| `_deriveWeeklyPlan()` | 11687 | Haftalık plan çıkar |
| `focusOrdersFor(dateIso, city)` | 11956 | Belirli gün/şehir siparişlerine geç |

---

## 10. Geçmiş (History) Ekranı

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `_buildHistoryDetailHTML()` | 13017 | Sevkiyat detay HTML |
| `closeHistoryDetail()` | 13000 | Detay kapat |
| `_renderHistoryPallet3DAll()` | 12334 | Geçmiş palet 3D mini canvas'lar |
| `_renderShipmentTruck3DAll()` | 12547 | Geçmiş araç 3D mini canvas'lar |
| `openHistoryPhotoLightbox()` | 12923 | Fotoğraf lightbox |
| `switchTransportTab(tab)` | 13212 | History tab geçişi |

---

## 11. Fotoğraf & Tamamlama

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `capturePhoto()` | 16736 | Kamera ile çek |
| `addPhotosFromFile()` | 16759 | Dosyadan ekle |
| `_addPhotoToState()` | 16770 | State'e ekle |
| `_renderPhotoThumbnails()` | 16775 | Thumbnail grid |
| `openPhotoLightbox()` | 16793 | Büyük görünüm |
| `_fillCompletionSummary()` | 16865 | Step 6 özet |
| `_lockCompletionStep()` | 17015 | Tamamlama kilitle (API'ye kaydet) |
| `_celebrateCompletion()` | 17054 | Konfeti animasyonu |

---

## 12. API Katmanı (Frontend)

`API` nesnesi (satır 9610):

```javascript
API.get(path)              → GET isteği
API.post(path, body)       → POST isteği
API.patch(path, body)      → PATCH isteği
API.put(path, body)        → PUT isteği
API.delete(path)           → DELETE isteği
API.ping()                 → /api/health — online/offline testi
API.pollStatus(shipmentId, onProgress)  → Optimizasyon progress polling
```

**API endpoint haritası:**
```
GET  /health                          → ping
POST /auth/login                      → giriş
POST /auth/refresh                    → token yenile
GET  /orders                          → sipariş listesi
POST /orders                          → yeni sipariş
PUT  /orders/{id}                     → güncelle
PATCH /orders/{id}/status             → durum güncelle
DELETE /orders/{id}                   → soft delete
POST /orders/bulk                     → toplu import
GET  /shipments                       → sevkiyat listesi
POST /shipments                       → yeni sevkiyat
POST /shipments/{id}/optimize         → optimizasyon başlat
GET  /shipments/{id}/status           → optimizasyon durumu
GET  /scenarios                       → senaryo listesi
POST /scenarios/{id}/select           → senaryo seç
GET  /transport-units/pallets         → palet tanımları
GET  /transport-units/vehicles        → araç tanımları
POST /vehicle-plans                   → manuel araç planı
GET  /vehicle-plans                   → araç planları listesi
```

---

## 13. Backend API Yapısı

### 13.1 Veritabanı Modelleri (models.py)

| Model | Tablo | İlişki |
|-------|-------|--------|
| `Company` | companies | → users, shipments, catalog_products, vehicle_defs, pallet_defs |
| `User` | users | → company |
| `Shipment` | shipments | → products, pallets, scenarios, loading_plans, order_links, photos |
| `ShipmentProduct` | shipment_products | → shipment |
| `Pallet` | pallets | → shipment, products |
| `PalletProduct` | pallet_products | → pallet |
| `Scenario` | scenarios | → shipment |
| `Order` | orders | → items, pallet_groups; `order_type`: standard/prepack |
| `OrderItem` | order_items | → order |
| `OrderPalletGroup` | order_pallet_groups | → order, items (pre-pack palet tanımı) |
| `OrderPalletItem` | order_pallet_items | → pallet_group (pre-pack ürün satırı) |
| `VehicleDefinition` | vehicle_definitions | → company |
| `PalletDefinition` | pallet_definitions | → company |
| `ConstraintDefinition` | constraint_definitions | → company |

**Order önemli alanlar:**
```python
status           # pending, in_planning, pallet_planned, vehicle_planned, loaded, in_transit, delivered, cancelled
priority         # 1=acil … 5=düşük
deadline_date    # termin
allowed_vehicle_types  # JSONB [str] — izin verilen araç kodları
items            # → OrderItem[]
```

**OrderItem önemli alanlar:**
```python
pallet_type     # String(30) — P1..P10, None=sipariş varsayılanı
constraints     # JSONB [{code, param_values}]
```

### 13.2 Optimizer (services/optimizer.py)

Algoritma: **3D Rect-Skyline Bin Packing v9.0**

```
Yerleşim önceliği: X (yan yana) → Y (yeni satır) → Z (üst üste)
Skor: X_extend=100 · Y_new_row=50 · Z_stack=10
CoG kontrolü: ağırlık merkezi sapması minimize
Kısıt: KURAL-4 → hard constraint ihlali = REDDET
```

Giriş: `products[]` (boyut + ağırlık + constraints) + `pallet_config` (width/length/maxHeight/maxWeight)
Çıkış: `pallets[]` → `[{pallet_number, pallet_type, total_weight_kg, products:[{pos_x, pos_y, pos_z}]}]`

**`_mapApiPallets()` (satır 10300) — Koordinat dönüşümü:**
```
Backend: pos_x=length yönü, pos_y=dikey, pos_z=width yönü
Frontend: x=width, y=length, z=dikey
→ placedItems: x=p.pos_z, y=p.pos_x, z=p.pos_y
```

---

## 14. Kısıt Sistemi

### 14.1 Kısıt Havuzu (CPOOL)

`CPOOL.system` — sistem tanımlı kısıtlar (satır 3053)
`CPOOL.company` — firma özel kısıtlar
`CPOOL.compat` — çakışma kuralları (horizontal+vertical = hata)

**Kısıt kategorileri:**
```
orientation   → horizontal, vertical, this_side_up
stackability  → no_stack, fragile, heavy, must_bottom, must_top, max_weight_above
environment   → temp, cold_chain, keep_dry, hazmat
loading_order → load_first, load_last, veh_front, veh_rear
```

### 14.2 Constraint Pool UI

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `openConstraintPool()` | 17920 | Kısıt havuzu modal aç |
| `cpInit()` | 17720 | Başlat |
| `cpRenderList()` | 17758 | Liste render |
| `cpSelectCard(code)` | 17781 | Kısıt seç |
| `cpSaveNew()` | 17873 | Yeni kısıt kaydet |
| `_openConstraintPicker(btn)` | 15207 | Sipariş formunda kısıt seçici |
| `_applyConstraintPicker()` | 15268 | Seçimleri uygula |

---

## 15. Tema & Ayarlar

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `applyTheme(themeId)` | 10658 | Temayı CSS değişkenlerine uygula |
| `initTheme()` | 10826 | Başlangıç teması |
| `_renderThemePicker()` | 10937 | Tema seçici render |
| `_initEngineSettings()` | 10853 | Motor ayarlarını yükle |
| `_saveEngineSettings()` | 10892 | Motor ayarlarını kaydet (APP.config.engine) |
| `renderVehicleDefGrid()` | 13348 | Araç tanımları grid |
| `openVehicleDefModal()` | 13490 | Araç tanımı ekle/düzenle |

**APP.config.engine ayarları:**
```javascript
maxIterations        // araç/palet tipi değerlendirme limiti
optimalityTarget     // % — erken dur eşiği
heightSafetyMargin   // cm — palet max yüksekliğinden düş
enforceConstraints   // kısıtları uygula
palletGapCm          // paletler arası boşluk
weightBalanceFrontPct// % ön aks hedef
targetFillRatePct    // % doluluk hedefi
preferFewerPallets   // daha az palet tercih et
```

---

## 16. Utility & Yardımcı Fonksiyonlar

| Fonksiyon | Satır | Açıklama |
|-----------|-------|----------|
| `_formatDate(dateStr)` | 8545 | Tarih formatla |
| `_daysBetween(d1, d2)` | 8551 | Gün farkı |
| `_toISODate(date)` | 11365 | ISO format |
| `_safeDate(dateStr)` | 11372 | Güvenli tarih parse |
| `_todayISO(offsetDays)` | 11378 | Bugün + offset |
| `_formatShortDate(dateStr)` | 11385 | Kısa tarih |
| `_getStartOfWeek(date)` | 11395 | Haftanın başlangıcı |
| `_estimateOrderPallets(order)` | 11403 | Siparişten tahmini palet sayısı |
| `_getStatusMeta(status, ctx)` | 11436 | Durum metadata (renk, ikon, etiket) |
| `_statusBadge(status, ctx)` | 11479 | Durum badge HTML |
| `_getOrderStageRank(status)` | 11484 | Durum sırası sayısı |
| `_themeClr()` | 11297 | Aktif tema ana rengi |
| `calculateVolume(product)` | 4400 | Ürün hacmi (m³) |
| `_constraintBadgesHTML(codes)` | 4404 | Kısıt badge HTML |
| `_woodenPalletMiniSVG()` | 4415 | Mini palet SVG ikonu |
| `_darken(hex, amt)` | 5937 | Renk koyulaştır |
| `_quickFleetEstimate(pallets)` | 4377 | Hızlı araç tahmin |
| `exportAllData()` | 17133 | Tüm veriyi dışa aktar |
| `exportSummaryExcel()` | 17480 | Özet rapor Excel |

---

## 17. Başlatma Akışı

```
_startApp()                    ← DOMContentLoaded
  ├─ checkAndShowApiStatus()   ← API.ping()
  ├─ loadTransportUnits()      ← GET /transport-units/pallets + /vehicles
  │    └─ _syncConfigFromDefs() ← APP.config.palletTypes/vehicleTypes SIFIRLANIR
  ├─ updatePalletInfo()
  ├─ loadDashboard()           ← GET /orders + /shipments
  ├─ loadVehiclePlans()        ← GET /vehicle-plans
  └─ showPage('dashboard')
```

**`loadTransportUnits()` → `_syncConfigFromDefs()` çağrısından sonra**
`APP.config.palletTypes` değiştiği için, bu fonksiyon çağrılmadan önce
`palletTypes`'a bağımlı olan tüm UI render'ları **boş sonuç verir**.

---

## 18. Sık Karşılaşılan Hatalar & Çözümleri

| Hata | Kök Neden | Çözüm |
|------|-----------|-------|
| `palletType.width is undefined` | `APP.config.palletTypes[pallet.type]` → undefined (sync sonrası key değişti) | `\|\| pallet.layout \|\| Object.values(...)[0] \|\| {}` fallback zinciri ekle |
| `null.textContent` in renderComparison | 4. manuel senaryo → `scenario-4-header` DOM'da yok | `filter(s => s.engineUsed !== 'manual').slice(0,3)` |
| Manuel araç seçimi sıfırlanıyor | `renderComparison()` her seferinde `bestScenario` atıyor | `if (!selectedScenario \|\| selectedScenario.engineUsed !== 'manual')` koruması |
| hasPerType false (palet tipi atanmıyor) | `APP.config.palletTypes[p.pallet_type]` lookup sync öncesi başarısız | `p.pallet_type.trim() !== ''` ile kontrol et, config lookup yapma |
| "Tümünü Seç" çalışmıyor | `closest('div')` inner flex div'e gidiyor, chevron alınıyor | `closest('div[onclick]')` kullan |
| Step 4'e geçince boş ekran | `autoOptimize()` çağrılmıyor | `approvePalletsAndContinue()` içinde `switchStep(4)` sonrası `autoOptimize()` çağır |

---

## 19. Pre-Pack Sipariş Sistemi

Müşteri paletlerini önceden tasarlayıp içe aktarır; optimizer palet oluşturmak yerine doğrudan araç optimizasyonu yapar.

### 19.1 Veri Modeli

```
Order (order_type='prepack')
  └── OrderPalletGroup  (pallet_code, dimensions, weight_kg, pallet_count)
        └── OrderPalletItem (product_code, description, quantity_per_pallet, total_quantity)
```

**Migration:** `cronoi_project/backend/migrate_prepack.sql` (geri al: `migrate_prepack_rollback.sql`)

### 19.2 Backend

| Dosya | Değişiklik |
|-------|-----------|
| `models.py` | `Order.order_type`, `Order.pallet_groups` ilişkisi; `OrderPalletGroup`, `OrderPalletItem` modelleri |
| `orders.py` | `OrderPalletGroupInput`, `OrderPalletItemInput` şemaları; `create_order`, `update_order`, `_order_to_dict` güncellendi |

`_order_to_dict()` → `pallet_groups: [{id, pallet_code, name, width_cm, length_cm, height_cm, weight_kg, pallet_count, items:[{product_code, description, quantity_per_pallet, total_quantity}]}]`

### 19.3 Frontend — Import Akışı

| Fonksiyon | Açıklama |
|-----------|----------|
| `importPrePackFromExcel(event)` | Excel parse: PALET_ID, URUN_KODU, ACIKLAMA, ADET_TOPLAM, PALET_SAYISI, GENISLIK/UZUNLUK/YUKSEKLIK_CM, AGIRLIK_KG. 'OF PACKS'/'WIDTH' gibi İngilizce alias desteği var |
| `downloadPrePackTemplate()` | ExcelJS şablon indir |
| `_showPrePackImportModal(palletGroups)` | Özet + sipariş bilgisi formu + önizleme tablosu |
| `_savePrePackOrder()` | Validasyon → `POST /orders` (`order_type:'prepack'`) |
| `_prepackRemoveGroup(idx)` | Modal'dan grup kaldır |

**PALET_ID gruplandırma kuralı:** Aynı PALET_ID'ye sahip satırlar tek palet grubu. Master satır = PALET_SAYISI veya boyut bilgisi olan. `qty_per_pallet = total_qty / pallet_count` (yuvarlanır).

**Sipariş meta alanları (r12):** Her iki pre-pack giriş yolu (Excel import `_showPrePackImportModal`
+ manuel `openNewPrePackModal`) artık standart siparişlerle hizalı: **`address`** (harita için) ve
**`deadline_date`** (termin) alanları eklendi; `_savePrePackOrder` ve `saveNewPrePack` payload'larına
yazılıyor. Excel = palet/ürün listesi; sipariş meta (adres/termin/müşteri/şehir) formdan girilir.
Backend `OrderCreate` zaten bu alanları kabul ediyor — değişiklik gerekmedi. Pre-pack şablonu artık
sipariş üst barında **"Pre-Pack Şablon"** butonuyla (standart "Şablon İndir" gibi) indirilebilir.

### 19.4 Frontend — Sipariş Listesi

`renderOrdersList()` içinde:
- `isPrepack = o.order_type === 'prepack'` → içerik sütununda "N palet · X kg" + "📦 PRE-PACK" mor badge
- `_prepackDetailHTML(o)` — mor temalı palet grupları tablosu (pallet_code, ürünler, boyut, ağırlık)
- `_standardDetailHTML(o)` — mevcut ürün tablosu (ayrı fonksiyon)

**Düzenleme:** `openEditOrderModal()` → `order_type === 'prepack'` ise `_openEditPrePackModal(order)` çağırır. `'draft'` durumu düzenlenebilir olarak eklendi.

| Fonksiyon | Açıklama |
|-----------|----------|
| `_openEditPrePackModal(order)` | Tam inline düzenleme modalı (meta alanlar + palet grupları tablosu) |
| `eppm_update(gi, field, val)` | Grup alanı güncelle |
| `eppm_updateItem(gi, ii, field, val)` | Ürün satırı güncelle |
| `eppm_addItem(gi)` / `eppm_removeItem(gi, ii)` | Ürün satırı ekle/sil |
| `eppm_addGroup()` / `eppm_removeGroup(gi)` | Grup ekle/sil |
| `_eppm_rerender(modal)` | Tbody yeniden render |
| `_eppm_refreshSummary(modal)` | Toplam palet/ağırlık güncelle |
| `saveEditPrePack(orderId)` | Validasyon → `PUT /orders/{id}` |

### 19.5 Frontend — Wizard Entegrasyonu

`_loadOrdersIntoWizard(orders)` akışı:
```
Tüm prepack → _buildPalletsFromPalletGroups() → switchStep(3) (1+2 atlanır)
Karışık      → hata toast, dur
Tüm standard → mevcut akış
```

| Fonksiyon | Açıklama |
|-----------|----------|
| `_buildPalletsFromPalletGroups(orders)` | `pallet_groups` → `APP.state.pallets` formatı. `source:'prepack'`, `layout:{width,length}`, `totalHeight`, `totalWeight` |
| `_estimatePrePackPlacements(pallet)` | Ürünleri orantısal yatay katmanlar olarak `placedItems` oluştur (3D görsel için) |

**Pre-pack palet nesnesi yapısı:**
```javascript
{
  id, type:'prepack', source:'prepack',
  orderId, orderNo, palletCode,          // pallet_group_id
  products: [{name, description, product_code, quantity, weight}],
  placedItems: [{...estimated:true}],
  totalWeight: grp.weight_kg,
  totalHeight: grp.height_cm,
  totalVolume,
  layout: {width:grp.width_cm, length:grp.length_cm, maxHeight:grp.height_cm, maxWeight:grp.weight_kg},
  assignedVehicle: null
}
```

### 19.6 Frontend — Araç Plan Raporu

`renderVehiclePlanReport()` (satır 6805) değişiklikleri:
- Pre-pack paletlerde fill% yerine `W×L×H cm` boyutu gösterilir
- `hasPrepack` ise rapor sonuna **"Ürün — Araç Dağılımı"** tablosu eklenir:
  - Satırlar: her benzersiz ürün (product_code + description)
  - Sütunlar: her araç (Araç 1, Araç 2 …) + Toplam Palet
  - Hücre değeri: o araçtaki palet sayısı

---

## 20. Planlanan / Devam Eden Özellikler

Detaylar için: `C:\Users\zmlya\.claude\plans\swirling-dazzling-dewdrop.md`

**Sipariş bazında araç tipi kısıtı + ürün bazında palet tipi (Plan var, uygulanmadı):**
- `Order.allowed_vehicle_types` JSONB kolonu (migrate_vehicle_pallet_fields.sql)
- `OrderItem.pallet_type` kolonu
- Frontend: sipariş formunda araç tipi toggle butonları
- Frontend: fleet tablosunda kısıtlı araçlara 🚫 badge + disable
- Migration SQL: `cronoi_project/backend/migrate_vehicle_pallet_fields.sql`
