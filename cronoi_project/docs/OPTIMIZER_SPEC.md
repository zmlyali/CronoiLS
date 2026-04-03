# Cronoi LS — Palet & Araç Optimizasyonu Nihai Direktif Dosyası
> **Hedef:** GitHub Copilot / Claude Opus için yazılmıştır.
> **Versiyon:** 3.0 — Konsey + Danışman Revizyonu
> **Tarih:** 2026-03-29
> **Yöntem:** Her sprint sonunda bölüm eklenerek güncellenir.
>
> Bu dosya şu kaynaklara dayanır:
> - Konsey değerlendirmesi (Prof., Lojistik Müdürü, Sevkiyat Uzmanı, CEO)
> - Gemini araştırması: Küresel Yükleme Güvenliği Standartları
> - Kısıt Kütüphanesi (CTU Code 2014, EUMOS 40509, IMDG, ADR)

---

## KISIM A — TEMEL PRENSİPLER

### A.1 Değiştirilemez Kurallar

```
KURAL-1: Optimizer'da HİÇBİR boyut, ağırlık veya kapasite sabit kodlanmaz.
         Araç verileri  → vehicle_types tablosundan (VehicleType nesnesi)
         Palet verileri → pallet_types tablosundan (PalletType nesnesi)
         Ayarlar        → optimizer_settings tablosundan (OptimizerSettings nesnesi)

KURAL-2: Validation her optimizasyon sonrası zorunlu çalışır. Asla atlanamaz.

KURAL-3: Yerleşim önceliği: X-yönü (yan yana) → Y-yönü (yeni satır) → Z-yönü (üst üste)
         Z-yönüne score penalty uygulanır, asla ilk tercih değildir.

KURAL-4: Hard constraint ihlali → çözüm REDDEDILIR.
         Soft constraint ihlali → skor düşer, kullanıcıya uyarı.

KURAL-5: Tüm parametreler ayarlar ekranından (Optimizasyon Sekmesi) beslenebilir.
         %85 doluluk hedefi, %5 tolerans, 15 cm boşluk limiti gibi değerler
         sistem geneli default, firma bazında override edilebilir.
```

---

## KISIM B — VERİ MODELLERİ

### B.1 VehicleType — DB'den Gelen Araç Verisi

```python
@dataclass
class VehicleType:
    """
    vehicle_types tablosundan. Optimizer içinde string karşılaştırma YASAK.
    'tir', 'panelvan' gibi hardcode değer girilmez — nesne kullanılır.
    """
    id: str
    code: str                  # 'TIR_136', 'PANELVAN_3'
    name: str                  # 'TIR (13.6m Standart)'
    vehicle_type: str          # 'tir' | 'kamyon' | 'panelvan' | 'konteyner'
    cargo_length_cm: float     # İç kargo boyu
    cargo_width_cm: float      # İç kargo genişliği
    cargo_height_cm: float     # İç kargo yüksekliği
    max_payload_kg: float      # Maks. yük ağırlığı
    pallet_capacity: int       # Standart EUR palet adedi
    is_reefer: bool = False    # Frigofirik mi?
    wheelbase_cm: float = 0.0  # Aks arası mesafe (60/40 hesabı için)

    @classmethod
    def from_db_row(cls, row: dict) -> 'VehicleType':
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})
```

### B.2 PalletType — DB'den Gelen Palet Verisi

```python
@dataclass
class PalletType:
    """pallet_types tablosundan."""
    id: str
    code: str                  # 'EUR', 'STD', 'UK', 'HALF'
    name: str                  # 'EUR Palet 80×120'
    width_cm: float            # 80
    length_cm: float           # 120
    tare_height_cm: float      # 15 (palet kendi yüksekliği)
    max_height_cm: float       # 180 (max istifleme — araçtan override edilir)
    max_weight_kg: float       # 1000
    tare_weight_kg: float      # 25 (paletin kendi ağırlığı)
    is_ispm15: bool = False    # Uluslararası ısıl işlemli ahşap palet mi?
    material: str = 'wood'     # 'wood' | 'plastic' | 'paper'

    @classmethod
    def from_db_row(cls, row: dict) -> 'PalletType':
        return cls(**{k: row[k] for k in cls.__dataclass_fields__})
```

### B.3 Item — Optimize Edilecek Ürün

```python
@dataclass
class Item:
    id: str
    product_name: str
    order_id: str              # Hangi siparişe ait
    delivery_address: str      # Teslim noktası (LIFO gruplaması için)
    delivery_sequence: int     # Çok duraklı rotada kaçıncı durak

    # Fiziksel özellikler
    width_cm: float
    length_cm: float
    height_cm: float
    weight_kg: float
    density_kg_m3: float       # weight / volume (katman sınıfı için)

    # Ambalaj özellikleri (McKee hesabı için)
    packaging_ect: float = 0.0      # Edge Crush Test değeri (N/m)
    packaging_thickness_cm: float = 0.0  # Karton kalınlığı
    packaging_humidity_sensitive: bool = False

    # Kısıtlar
    constraints: list[str] = field(default_factory=list)
    # Geçerli değerler: 'fragile','heavy','no_stack','must_bottom','must_top',
    #   'horizontal','this_side_up','cold_chain','hazmat','keep_dry',
    #   'load_first','load_last','veh_front','veh_rear','ispm15_required'

    # Tercihler
    preferred_pallet_type_code: str = ''
    preferred_vehicle_type: str = ''

    @property
    def min_dim(self): return min(self.width_cm, self.length_cm, self.height_cm)
    @property
    def volume_m3(self): return (self.width_cm * self.length_cm * self.height_cm) / 1_000_000
```

### B.4 OptimizerSettings — Tüm Parametrik Değerler

```python
@dataclass
class OptimizerSettings:
    """
    Ayarlar Ekranı > Optimizasyon Sekmesi'nden gelir.
    Firma bazında override edilebilir. Hiçbir değer hardcode değildir.
    Default değerler sistem geneli önerilen değerlerdir.
    """

    # ── Boyut Toleransları ───────────────────────────────────────────────
    height_tolerance_pct: float = 5.0
    # Açıklama: Palet max yüksekliğinin yüzde kaç üzerine çıkılabilir
    # Arayüz: slider 0–15%, adım 0.5%
    # Etki: Her yerleşimde (pos_z + item_h) <= max_h * (1 + t/100) kontrolü

    width_tolerance_pct: float = 5.0
    # Açıklama: Palet genişlik/uzunluk taşma payı
    # Arayüz: slider 0–10%, adım 0.5%

    # ── Doluluk Hedefleri ────────────────────────────────────────────────
    target_fill_rate_pct: float = 85.0
    # Açıklama: Optimizasyon bu oranı yakalamaya çalışır
    # Arayüz: slider 60–100%, adım 1%
    # Etki: Bu eşiğe ulaşınca Phase-2 optimizasyon durdurulabilir

    suggestion_trigger_pct: float = 75.0
    # Açıklama: Bu oranın altındaki paletler için öneri motoru devreye girer
    # Arayüz: slider 50–90%, adım 5%

    # ── Algorıtma Davranışı ──────────────────────────────────────────────
    max_optimization_time_sec: int = 30
    # Açıklama: Phase-2 Skyline'ın max çalışma süresi
    # Arayüz: select 5 / 15 / 30 / 60 sn
    # Not: Phase-1 FFD her zaman <200ms'de biter (zaman limitsiz)

    prefer_fewer_pallets: bool = True
    # Açıklama: True=az palet hedefi, False=yüksek doluluk hedefi
    # Arayüz: toggle switch

    allow_mixed_orders_on_pallet: bool = True
    # Açıklama: Farklı sipariş ürünleri aynı palete girebilir mi?
    # Arayüz: toggle — kapalıysa her sipariş ayrı palete

    allow_mixed_pallet_types: bool = True
    # Açıklama: Farklı paletler aynı sevkiyatta karışabilir mi?
    # Arayüz: toggle

    placement_priority: list = field(default_factory=lambda: ['x_extend','y_new_row','z_stack'])
    # Not: Bu sıra değiştirilemez — kural olarak sabit

    # ── Fizik & Güvenlik Kuralları ───────────────────────────────────────
    max_void_gap_cm: float = 15.0
    # Kaynak: CTU Code 2014, Bölüm 5
    # Açıklama: Paletler/ürünler arası max izin verilen boşluk
    # Arayüz: input 5–30 cm
    # Etki: Aşılırsa uyarı + dunnage bag önerisi

    weight_front_ratio_pct: float = 60.0
    # Kaynak: EUMOS 40509 / FMCSA
    # Açıklama: TIR/treyler için ön aksın taşıması gereken yük oranı
    # Arayüz: slider 50–70%, adım 5%
    # Etki: 60/40 kural — bu değer ön oran, geri kalan arka

    weight_front_tolerance_pct: float = 5.0
    # Açıklama: 60/40 kuralında kabul edilen sapma (55–65 arası kabul)
    # Arayüz: slider 2–10%

    tongue_weight_min_pct: float = 10.0
    # Kaynak: EUMOS 40509
    # Açıklama: Römorklu yüklemelerde bağlantı noktasına min binen oran
    # Arayüz: slider 5–20%

    tongue_weight_max_pct: float = 15.0
    # Arayüz: slider 10–25%

    eumos_forward_g: float = 0.8
    # Kaynak: EUMOS 40509
    # Açıklama: İleri yönde ivme dayanım testi değeri
    # Arayüz: read-only (standart değer, değiştirilmez)

    eumos_lateral_g: float = 0.5
    # Kaynak: EUMOS 40509
    # Arayüz: read-only

    # ── McKee & Ambalaj ──────────────────────────────────────────────────
    packaging_enabled: bool = False
    # Açıklama: Karton kutu BCT hesabı aktif mi?
    # Arayüz: toggle — aktifse ambalaj kalınlığı ve ECT değeri gerekli

    packaging_thickness_cm: float = 0.4
    # Açıklama: Standart karton kalınlığı (McKee formülü girdi)
    # Kaynak: McKee: BCT = 5.87 × ECT × √(h × Z)
    # Arayüz: input 0.2–1.5 cm

    humidity_factor: float = 1.0
    # Açıklama: Karton BCT çarpanı — nem etkisi
    # Değer tablosu: %50 nem → 1.0, %65 → 0.85, %75 → 0.70, %90 → 0.50
    # Arayüz: select (kuru ortam / nemli depo / çok nemli)

    stacking_pattern: str = 'interlocked'
    # Açıklama: Palet içi istifleme paternı
    # 'column'     → max dikey mukavemet, düşük yatay stabilite
    # 'interlocked'→ yüksek yatay stabilite, %40 dikey güç kaybı
    # Arayüz: radio button — uzun yol/sarsıntı için 'interlocked' önerilen

    # ── Sürtünme & Sabitleme ─────────────────────────────────────────────
    friction_coefficient_threshold: float = 0.6
    # Kaynak: EN 12195-1
    # Açıklama: Ahşap palet–metal zemin sürtünmesi bu değerin altındaysa
    #           anti-slip mat zorunlu uyarısı çıkar
    # Arayüz: input 0.3–0.8

    # ── Soğuk Zincir & Reefer ────────────────────────────────────────────
    reefer_door_clearance_cm: float = 11.0
    # Kaynak: Reefer yükleme kılavuzu
    # Açıklama: Kapı tarafında bırakılması gereken min hava boşluğu
    # Arayüz: input 10–15 cm

    reefer_ceiling_clearance_cm: float = 22.0
    # Açıklama: Tavanda bırakılması gereken min boşluk (hava dönüş yolu)
    # Arayüz: input 20–30 cm

    # ── Uluslararası Kısıtlar ────────────────────────────────────────────
    enforce_ispm15: bool = False
    # Kaynak: ISPM 15 Fitofarmasötik Standart
    # Açıklama: Aktifse ahşap paletlerin ısıl işlemli olması zorunlu
    # Arayüz: toggle — uluslararası sevkiyatlarda aktif edilmeli
```

---

## KISIM C — ALGORİTMA

### C.1 Genel Akış (Değiştirilemez Sıra)

```
INPUT
  items[]              → sipariş ürünleri (Item listesi)
  pallet_types[]       → DB'den aktif palet tipleri
  vehicle_types[]      → DB'den firma araç filosu
  target_vehicle_ids[] → hangi araçlar değerlendirilecek
  settings             → OptimizerSettings (ayarlar ekranından)
  route_stops[]        → çok duraklı rota varsa teslim sırası

PHASE 1 — HIZLI ÖN ÇÖZÜM (FFD) ~50-200ms
  1a. Constraint extraction   → kısıtları parse et
  1b. ISPM-15 filter          → uluslararası ise ahşap palet uyarısı
  1c. Incompatibility filter  → aynı palete giremeyecek çiftleri bul
  1d. Layer classification    → katman sınıfı ata (0=alt, 1=orta, 2=üst)
  1e. Delivery grouping       → sipariş + teslim noktası bazlı grupla
  1f. FFD placement           → hızlı yerleştir
  → yield phase1_result       → Frontend'e anında gönder

PHASE 2 — İYİLEŞTİRME (3D Layer Skyline) max settings.max_optimization_time_sec
  2a. Per-pallet Skyline      → her grup için katman bazlı 3D Skyline
  2b. Rotation trials         → geçerli rotasyonları dene (kısıt filtreli)
  2c. Width-first priority    → X → Y → Z sırasıyla doldur
  2d. McKee check             → packaging_enabled=True ise BCT hesapla
  2e. Fill rate check         → target_fill_rate_pct yakalandı mı?
  → yield improved_result     → Frontend'e güncelleme gönder

PHASE 3 — ARAÇ ATAMASI
  3a. Pallet summary          → tip bazlı özet (EUR:5, STD:10)
  3b. Vehicle fit             → hangi araçlara sığıyor?
  3c. Min vehicle select      → en az araç kombinasyonu
  3d. Weight distribution     → 60/40 kuralı + dil ağırlığı
  3e. LIFO positioning        → route_stops varsa yükleme sırası

PHASE 4 — ZORUNLU VALIDATION
  4a. Hard constraint check   → tüm hard kurallar karşılandı mı?
  4b. Void gap check          → max_void_gap_cm aşıldı mı?
  4c. EUMOS check             → 0.8g/0.5g ivme dayanımı yeterli mi?
  4d. Weight balance check    → 60/40 kural sağlandı mı?
  4e. ISPM-15 check           → enforce_ispm15=True ise ahşap palet uyarısı

OUTPUT
  phase1_result    → hızlı önizleme
  final_result     → optimize edilmiş son çözüm
  validation       → errors[] + warnings[] + compliance[]
```

### C.2 3D Katman Bazlı Skyline

```python
class LayeredSkyline:
    """
    Mobilya için 3D Skyline: 3 katman, her biri ayrı 2D Skyline.

    KATMAN SINIFLANDIRMASI (density_kg_m3 + constraints bazlı):
    ┌─ Katman 2 (Üst)  ─── fragile, must_top, hafif (density < 200 kg/m³)
    ├─ Katman 1 (Orta) ─── normal ürünler
    └─ Katman 0 (Alt)  ─── heavy, must_bottom, ağır (density > 400 kg/m³)
    """
    layers: list[SkylineLayer2D]
    pallet: PalletType
    vehicle: VehicleType
    settings: OptimizerSettings

    @property
    def max_allowed_height(self) -> float:
        usable = self.vehicle.cargo_height_cm - self.pallet.tare_height_cm
        return usable * (1 + self.settings.height_tolerance_pct / 100)

    def _classify_layer(self, item: Item) -> int:
        if 'must_bottom' in item.constraints or 'heavy' in item.constraints:
            return 0
        if item.density_kg_m3 > 400:
            return 0
        if 'must_top' in item.constraints or 'fragile' in item.constraints:
            return 2
        if item.density_kg_m3 < 200:
            return 2
        return 1

    def add_item(self, item: Item) -> Placement | None:
        layer_idx = self._classify_layer(item)
        rotations = self._valid_rotations(item)

        # Önce X yönü, sonra Y, en son Z (BUG-2 düzeltmesi)
        for direction in ['x_extend', 'y_new_row', 'z_stack']:
            for rot in rotations:
                pos = self.layers[layer_idx].try_place(item, rot, direction)
                if pos and self._height_ok(pos, item, rot):
                    self.layers[layer_idx].commit(item, rot, pos)
                    return Placement(pos, rot, layer_idx, direction)

        # Bu katmanda yer yok — yeni katman ekle (aynı sınıf)
        new_layer = SkylineLayer2D(class_=layer_idx,
                                   z_start=self._next_z(layer_idx))
        self.layers.append(new_layer)
        for rot in rotations:
            pos = new_layer.try_place(item, rot, 'x_extend')
            if pos and self._height_ok(pos, item, rot):
                new_layer.commit(item, rot, pos)
                return Placement(pos, rot, layer_idx, 'x_extend')
        return None

    def _valid_rotations(self, item: Item) -> list[Rotation]:
        """Kısıt bazlı rotasyon filtresi — 6 değil kısıta göre 1-3 adet."""
        base = [
            Rotation(item.width_cm, item.length_cm, item.height_cm),
            Rotation(item.length_cm, item.width_cm, item.height_cm),
        ]
        if 'horizontal' in item.constraints:
            return [r for r in base if r.h == item.min_dim]
        if 'this_side_up' in item.constraints or 'no_rotate' in item.constraints:
            return [base[0]]
        return base

    def _height_ok(self, pos: Position, item: Item, rot: Rotation) -> bool:
        total = pos.z + rot.h
        return total <= self.max_allowed_height
```

### C.3 Yerleşim Skoru

```python
def score_placement(direction: str, pos: Position, rot: Rotation,
                    item: Item, pallet: PalletSpace,
                    settings: OptimizerSettings) -> float:
    score = 0.0

    # Yön bonusu — X tercih, Z ceza
    score += {'x_extend': 100, 'y_new_row': 50, 'z_stack': 10}[direction]

    # Yükseklik cezası (ne kadar yükseğe çıkıyorsa o kadar kötü)
    h_ratio = (pos.z + rot.h) / pallet.max_allowed_height
    score -= h_ratio * 40

    # Doluluk katkısı (bu ürün ne kadar boşluk dolduruyor)
    vol_ratio = item.volume_m3 / pallet.remaining_volume_m3
    score += vol_ratio * 30

    # Ağırlık merkezi iyileştirmesi
    if item.weight_kg > 30 and pos.z == 0:
        score += 20  # Ağır ürün tabanda — iyi

    # Boşluk cezası (CTU Code 15 cm kuralı)
    gap = calculate_x_gap(pos, pallet, settings)
    if gap > settings.max_void_gap_cm:
        score -= 20

    return score
```

---

## KISIM D — HARD CONSTRAINT MOTORU

### D.1 Yerleşim Hard Kısıtları

```python
HARD_CONSTRAINTS = {

    # ── Boyut Limitleri ──────────────────────────────────────────────────
    'height_limit': {
        'check': lambda pos, rot, max_h, tol:
            (pos.z + rot.h) <= max_h * (1 + tol/100),
        'error': 'Yükseklik limiti aşıldı: {actual:.1f}cm > {limit:.1f}cm'
    },
    'width_limit': {
        'check': lambda pos, rot, pallet, tol:
            (pos.x + rot.w) <= pallet.width_cm * (1 + tol/100),
        'error': 'Palet genişliği aşıldı'
    },
    'length_limit': {
        'check': lambda pos, rot, pallet, tol:
            (pos.y + rot.l) <= pallet.length_cm * (1 + tol/100),
        'error': 'Palet uzunluğu aşıldı'
    },
    'weight_limit': {
        'check': lambda pallet: pallet.current_weight_kg <= pallet.max_weight_kg,
        'error': 'Palet ağırlık limiti aşıldı: {actual}kg > {limit}kg'
    },

    # ── Malzeme Uyumluluğu ───────────────────────────────────────────────
    # Kaynak: CTU Code 2014, IMDG Code
    'fragile_heavy_incompatible': {
        'check': lambda items: not (
            any('fragile' in i.constraints for i in items) and
            any('heavy'   in i.constraints for i in items)
        ),
        'error': 'Kırılgan + Ağır aynı palete giremez (CTU Code)'
    },
    'cold_hazmat_incompatible': {
        'check': lambda items: not (
            any('cold_chain' in i.constraints for i in items) and
            any('hazmat'     in i.constraints for i in items)
        ),
        'error': 'Soğuk zincir + Tehlikeli madde aynı araçta yasak (IMDG)'
    },
    'hazmat_segregation_away_from': {
        'check': lambda item_a, item_b, distance_m:
            distance_m >= 3.0 if (
                'hazmat' in item_a.constraints and 'hazmat' in item_b.constraints
            ) else True,
        'error': 'Tehlikeli maddeler arası min 3 metre mesafe (IMDG Away From)'
    },
    'liquid_above_dry': {
        'check': lambda items: not any(
            'liquid' in a.constraints and a_pos.z > b_pos.z
            for a, a_pos in items
            for b, b_pos in items
            if 'liquid' not in b.constraints
        ),
        'error': 'Sıvı yük kuru yükün üzerine konamaz'
    },

    # ── Katman Kısıtları ─────────────────────────────────────────────────
    'must_bottom': {
        'check': lambda item, pos: pos.z == 0 if 'must_bottom' in item.constraints else True,
        'error': '{name} palet tabanında olmalı (must_bottom)'
    },
    'no_stack_above': {
        'check': lambda item, items_above:
            len(items_above) == 0 if 'no_stack' in item.constraints else True,
        'error': '{name} üzerine yük konulamaz (no_stack)'
    },
    'overlap_check': {
        'check': lambda pallets: not has_any_overlap(pallets),
        'error': 'Çakışan ürünler var — geometrik hata'
    },

    # ── Reefer Özel ──────────────────────────────────────────────────────
    # Kaynak: Reefer yükleme kılavuzu (T-Floor & kırmızı çizgi kuralı)
    'reefer_ceiling_clearance': {
        'check': lambda pallet, vehicle, settings:
            (vehicle.cargo_height_cm - pallet.actual_height_cm) >= settings.reefer_ceiling_clearance_cm
            if vehicle.is_reefer else True,
        'error': 'Frigofirik araçta tavan boşluğu yetersiz (min {limit}cm gerekli)'
    },

    # ── Uluslararası ─────────────────────────────────────────────────────
    # Kaynak: ISPM 15
    'ispm15_required': {
        'check': lambda item, pallet, settings:
            (not settings.enforce_ispm15) or pallet.is_ispm15 or pallet.material != 'wood',
        'error': 'Uluslararası sevkiyat: ahşap palet ısıl işlemli (ISPM-15) olmalı'
    },
}
```

### D.2 Soft Constraint Skoru

```python
SOFT_CONSTRAINTS = {
    'weight_order': {
        'penalty': lambda item, pos: -10 if (item.density_kg_m3 > 400 and pos.z > 0) else 0,
        'warning': 'Ağır ürün üst katmanda — tavsiye edilmez'
    },
    'void_gap': {
        'penalty': lambda gap_cm, limit: -(gap_cm - limit) * 2 if gap_cm > limit else 0,
        'warning': f'Boşluk {{gap}}cm > {{limit}}cm — dunnage bag önerilen (CTU Code)'
    },
    'stacking_stability': {
        'penalty': lambda pattern, item:
            -15 if pattern == 'column' and item.weight_kg < 20 else 0,
        'warning': 'Hafif ürün için kilitli istifleme daha stabil'
    },
    'friction_warning': {
        'penalty': 0,
        'warning': 'Ahşap palet–metal zemin sürtünmesi düşük — anti-slip mat önerilir'
    },
    'mckey_compression': {
        'penalty': lambda bct_ratio: -20 if bct_ratio < 1.5 else 0,
        'warning': 'BCT güvenlik faktörü 1.5 altında — istifleme yüksekliği azaltın'
    },
}
```

---

## KISIM E — FİZİK KURALLARI (Gemini Danışman Raporu Eklentisi)

### E.1 McKee Formülü — Karton BCT Analizi

```python
def calculate_bct(item: Item, settings: OptimizerSettings) -> float:
    """
    McKee Formülü: BCT = 5.87 × ECT × √(h × Z)
    Kaynak: McKee (1963), Cronoi LS Kısıt Kütüphanesi Bölüm 1

    Aktif: settings.packaging_enabled = True
    Parametreler: settings'ten gelir — hardcode yok

    Returns: Düzeltilmiş BCT (kg) — nemin etkisi dahil
    """
    if not settings.packaging_enabled or item.packaging_ect <= 0:
        return float('inf')  # Hesaplama yapılmıyor

    # Ham BCT
    perimeter = 2 * (item.width_cm + item.length_cm)
    bct_raw = 5.87 * item.packaging_ect * (
        (item.packaging_thickness_cm * perimeter) ** 0.5
    )

    # Nem düzeltmesi (settings'ten gelir)
    bct_adjusted = bct_raw * settings.humidity_factor

    return bct_adjusted

def max_stack_height_for_item(item: Item, settings: OptimizerSettings) -> float:
    """Bir ürünün üstüne kaç kg konulabileceğini hesaplar."""
    bct = calculate_bct(item, settings)
    safety_factor = 1.5  # Min güvenlik faktörü
    allowable_load = bct / safety_factor
    return allowable_load
```

### E.2 Aks Yükü Hesaplama — Kaldıraç Prensibi

```python
def calculate_axle_loads(
    pallets: list[PlacedPallet],
    vehicle: VehicleType
) -> AxleLoadResult:
    """
    Kaldıraç prensibi ile aks yük dağılımı.
    Kaynak: Cronoi LS Kısıt Kütüphanesi Bölüm 2

    W_RearAxle = (TotalLoad × FrontAxleDistance) / WheelBase
    W_FrontAxle = TotalLoad - W_RearAxle

    Araç verileri vehicle_types tablosundan (wheelbase_cm).
    """
    if vehicle.wheelbase_cm <= 0:
        return AxleLoadResult(skipped=True, reason='Dingil arası mesafe bilinmiyor')

    total_weight = sum(p.total_weight_kg for p in pallets)

    # Ağırlık merkezini hesapla (Y ekseni boyunca)
    weight_cg_y = sum(p.total_weight_kg * p.center_y for p in pallets) / total_weight

    front_dist = vehicle.cargo_length_cm - weight_cg_y
    rear_load  = (total_weight * front_dist) / vehicle.wheelbase_cm
    front_load = total_weight - rear_load

    front_ratio = front_load / total_weight
    return AxleLoadResult(
        front_load_kg=front_load,
        rear_load_kg=rear_load,
        front_ratio_pct=front_ratio * 100,
        is_balanced=abs(front_ratio - 0.60) <= (settings.weight_front_tolerance_pct / 100)
    )
```

### E.3 Dunnage & Boşluk Yönetimi

```python
def check_void_gaps(
    pallet: PalletDetail,
    settings: OptimizerSettings
) -> list[VoidGapWarning]:
    """
    CTU Code kuralı: 15 cm üzeri boşluklara dunnage bag / takoz gerekli.
    settings.max_void_gap_cm parametrik.
    """
    warnings = []
    gaps = calculate_horizontal_gaps(pallet.items)
    for gap in gaps:
        if gap.size_cm > settings.max_void_gap_cm:
            warnings.append(VoidGapWarning(
                location=gap.location,
                size_cm=gap.size_cm,
                recommendation='dunnage_bag' if gap.size_cm < 30 else 'takoz',
                message=f'Boşluk {gap.size_cm:.0f}cm > {settings.max_void_gap_cm}cm '
                        f'(CTU Code) — {gap.size_cm:.0f}cm dunnage bag önerilen'
            ))
    return warnings
```

---

## KISIM F — ARAÇ ATAMASI VE LIFO

### F.1 Çok Duraklı LIFO Pozisyonlama

```python
def assign_vehicle_positions(
    pallets: list[PalletDetail],
    vehicle: VehicleType,
    route_stops: list[DeliveryStop],
    settings: OptimizerSettings
) -> list[PalletDetail]:
    """
    LIFO: Son teslim noktası → Araç önüne (kabine yakın, Y=max)
           İlk teslim noktası → Araç arkasına (kapıya yakın, Y=0)

    Aynı anda 60/40 dengesi de sağlanmalı.
    Çatışırsa: hard kural önce (60/40), sonra LIFO soft constraint.
    """
    if not route_stops:
        return pallets  # Tek duraklı rota — LIFO gerekmez

    stop_count = len(route_stops)
    zone_len = vehicle.cargo_length_cm / stop_count

    for pallet in pallets:
        stop_idx = next(
            (i for i, s in enumerate(route_stops) if s.address == pallet.delivery_address),
            stop_count - 1
        )
        # Erken durak (0) → kapıya yakın (Y=0)
        pallet.suggested_vehicle_y = stop_idx * zone_len
        pallet.load_sequence = stop_count - stop_idx  # Kaçıncı yüklenecek

    # 60/40 dengesini kontrol et ve gerekirse pozisyonları iyileştir
    return _rebalance_weight_distribution(pallets, vehicle, settings)
```

### F.2 Araç Öneri Motoru

```python
def suggest_vehicle_combination(
    pallets: list[PalletDetail],
    available_vehicles: list[VehicleType],
    settings: OptimizerSettings
) -> VehicleAssignmentResult:
    """
    En az araç sayısı ile en yüksek doluluk oranı.
    settings.prefer_fewer_pallets değerine göre ağırlık değişir.
    """
    best = None
    best_score = -1

    # Büyük araçtan başla (Greedy)
    sorted_vehicles = sorted(available_vehicles,
                              key=lambda v: v.max_payload_kg, reverse=True)
    for vehicle in sorted_vehicles:
        max_h = (vehicle.cargo_height_cm - min(p.pallet_type.tare_height_cm for p in pallets)
                ) * (1 + settings.height_tolerance_pct / 100)
        fitting = [p for p in pallets if p.actual_height_cm <= max_h]

        if len(fitting) == len(pallets):
            fill_rate = sum(p.weight_kg for p in pallets) / vehicle.max_payload_kg
            score = fill_rate * 100
            if score > best_score:
                best_score = score
                best = VehicleAssignment(vehicle=vehicle, pallets=pallets,
                                          fill_rate_pct=fill_rate * 100)

    return best or suggest_multi_vehicle(pallets, sorted_vehicles, settings)
```

---

## KISIM G — VALIDATION (Zorunlu)

```python
def validate_optimization_result(
    result: OptimizationResult,
    settings: OptimizerSettings,
    vehicle: VehicleType
) -> ValidationReport:
    """
    Her optimizasyon sonrası ZORUNLU çalışır. Asla atlanmaz.
    Hard constraint ihlali → is_valid = False
    Soft constraint ihlali → warnings'e eklenir
    """
    errors, warnings, compliance = [], [], []

    for pallet in result.pallets:
        max_h = get_max_pallet_height(vehicle, pallet.pallet_type.tare_height_cm,
                                       settings.height_tolerance_pct)

        # HARD: Yükseklik
        if pallet.actual_height_cm > max_h:
            errors.append(ActionableError(
                code='HEIGHT_EXCEEDED',
                message=f'{pallet.pallet_id}: Yükseklik {pallet.actual_height_cm:.0f}cm > '
                        f'{max_h:.0f}cm ({vehicle.name})',
                action_label='Paleti Böl',
                affected_pallet_id=pallet.pallet_id
            ))

        # HARD: Ağırlık
        if pallet.total_weight_kg > pallet.pallet_type.max_weight_kg:
            errors.append(ActionableError(
                code='WEIGHT_EXCEEDED',
                message=f'{pallet.pallet_id}: Ağırlık {pallet.total_weight_kg:.0f}kg > '
                        f'{pallet.pallet_type.max_weight_kg:.0f}kg',
                action_label='Ürün Çıkar',
                affected_pallet_id=pallet.pallet_id
            ))

        # HARD: Kırılgan + Ağır çakışma
        if has_fragile_and_heavy(pallet.items):
            errors.append(ActionableError(
                code='CONSTRAINT_CONFLICT',
                message=f'{pallet.pallet_id}: Kırılgan ve ağır ürün birlikte (CTU Code)',
                action_label='Ayır',
                affected_pallet_id=pallet.pallet_id
            ))

        # HARD: Çakışma
        if has_overlap(pallet.items):
            errors.append(ActionableError(
                code='GEOMETRY_ERROR',
                message=f'{pallet.pallet_id}: Çakışan ürünler — optimizer hatası',
                action_label='Yeniden Optimize Et',
                affected_pallet_id=pallet.pallet_id
            ))

        # HARD: Reefer tavan boşluğu
        if vehicle.is_reefer:
            clearance = vehicle.cargo_height_cm - pallet.actual_height_cm
            if clearance < settings.reefer_ceiling_clearance_cm:
                errors.append(ActionableError(
                    code='REEFER_CLEARANCE',
                    message=f'Frigofirik tavan boşluğu yetersiz: {clearance:.0f}cm '
                            f'< {settings.reefer_ceiling_clearance_cm:.0f}cm',
                    action_label='Yükseklik Azalt'
                ))

        # HARD: ISPM-15
        if (settings.enforce_ispm15 and
            pallet.pallet_type.material == 'wood' and
            not pallet.pallet_type.is_ispm15):
            errors.append(ActionableError(
                code='ISPM15_VIOLATION',
                message='Uluslararası sevkiyat: ısıl işlemsiz ahşap palet kullanılamaz',
                action_label='Palet Tipini Değiştir'
            ))

        # SOFT: Doluluk uyarısı
        if pallet.fill_rate_pct < settings.suggestion_trigger_pct:
            warnings.append(f'{pallet.pallet_id}: Düşük doluluk %{pallet.fill_rate_pct:.0f}')

        # SOFT: Boşluk kontrolü
        void_warnings = check_void_gaps(pallet, settings)
        warnings.extend([w.message for w in void_warnings])

        # SOFT: McKee BCT
        if settings.packaging_enabled:
            for item in pallet.items:
                bct = calculate_bct(item, settings)
                load_above = sum(i.weight_kg for i in items_above(item, pallet))
                if bct > 0 and load_above > (bct / 1.5):
                    warnings.append(f'{item.product_name}: BCT güvenlik faktörü düşük')

    # HARD: 60/40 ağırlık dengesi (araç geneli)
    axle = calculate_axle_loads(result.all_pallets, vehicle)
    if not axle.skipped and not axle.is_balanced:
        errors.append(ActionableError(
            code='WEIGHT_IMBALANCE',
            message=f'60/40 dengesi sağlanamadı: ön %{axle.front_ratio_pct:.0f} '
                    f'(beklenen %{settings.weight_front_ratio_pct:.0f} ±%{settings.weight_front_tolerance_pct:.0f})',
            action_label='Yeniden Düzenle'
        ))

    # Compliance raporu
    compliance.append(f'CTU Code 2014: {"OK" if not any(e.code=="GEOMETRY_ERROR" for e in errors) else "FAIL"}')
    compliance.append(f'EUMOS 40509: {"OK" if axle.is_balanced else "FAIL"}')
    compliance.append(f'ISPM-15: {"OK" if not any(e.code=="ISPM15_VIOLATION" for e in errors) else "FAIL"}')

    return ValidationReport(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        compliance=compliance
    )
```

---

## KISIM H — OUTPUT FORMAT

```python
@dataclass
class OptimizationResult:
    # Özet
    total_pallets: int
    pallets_by_type: dict            # {'EUR': 5, 'STD': 12, 'HALF': 3}
    total_weight_kg: float
    total_volume_m3: float
    avg_fill_rate_pct: float
    estimated_vehicles: dict         # {'TIR_136': 1, 'PANELVAN_3': 0}
    optimization_time_ms: float      # Phase1 + Phase2 toplam süre

    pallets: list[PalletDetail]
    is_valid: bool
    errors: list[ActionableError]    # Hard — eyleme geçirilebilir
    warnings: list[str]              # Soft — bilgilendirme
    compliance: list[str]            # CTU/EUMOS/ISPM-15 durumu

@dataclass
class PalletDetail:
    pallet_id: str
    pallet_type_code: str
    pallet_type_name: str
    width_cm: float
    length_cm: float
    max_height_cm: float             # Araç tipine göre hesaplanmış
    actual_height_cm: float
    fill_rate_pct: float
    total_weight_kg: float
    stacking_pattern: str            # 'column' | 'interlocked'
    # Sipariş bilgisi
    order_ids: list[str]             # ['SIP-001', 'SIP-003']
    delivery_address: str            # Teslim noktası
    customer_names: list[str]
    is_mixed_orders: bool
    # Araç içi pozisyon
    load_sequence: int               # Kaçıncı yüklenecek (LIFO)
    suggested_vehicle_y: float       # Araç içi Y koordinatı
    # Ürünler
    items: list[PlacedItem]

@dataclass
class PlacedItem:
    item_id: str
    product_name: str
    order_id: str
    pos_x: float; pos_y: float; pos_z: float
    placed_width: float; placed_length: float; placed_height: float
    orig_width: float; orig_length: float; orig_height: float
    layer_class: int                 # 0=alt, 1=orta, 2=üst
    placement_direction: str         # 'x_extend'|'y_new_row'|'z_stack'
    color_hex: str                   # Three.js için
    constraints: list[str]
    bct_safety_factor: float         # McKee hesabı varsa

@dataclass
class ActionableError:
    code: str                        # 'HEIGHT_EXCEEDED', 'WEIGHT_EXCEEDED'...
    message: str                     # Kullanıcıya gösterilecek Türkçe mesaj
    action_label: str                # Buton metni: 'Paleti Böl', 'Ürün Çıkar'
    affected_pallet_id: str = ''
```

---

## KISIM I — ANA API

```python
def optimize(
    items: list[dict],
    pallet_types: list[dict],        # pallet_types tablosundan
    vehicle_types: list[dict],       # vehicle_types tablosundan
    target_vehicle_ids: list[str],
    route_stops: list[dict],         # Çok duraklı rota (opsiyonel)
    settings: dict                   # OptimizerSettings alanları
) -> dict:
    """
    İMZA SABITTIR. Değiştirilmez.

    Akış:
    1. Parse — tüm dict'leri dataclass'a çevir
    2. Phase-1 FFD → hemen yield et (frontend'e gönder)
    3. Phase-2 Skyline → zaman bütçesi içinde iyileştir, her iyileşmede yield
    4. Araç atama → LIFO + 60/40
    5. Validation → ZORUNLU, asla atlanmaz
    6. Return

    Returns: {
        'phase1': {...},        # Hızlı ön çözüm
        'final': {...},         # Optimize edilmiş son çözüm
        'validation': {...},    # errors + warnings + compliance
        'duration_ms': float
    }
    """
```

---

## KISIM J — AYARLAR EKRANı (Optimizasyon Sekmesi)

```
Ayarlar → Optimizasyon sekmesinde firmalar şu parametreleri değiştirebilir.
Tüm değerler optimizer_settings tablosuna yazılır, optimizer buradan okur.

GENEL
  [slider] Doluluk hedefi              : %85   (60–100)
  [slider] Öneri motoru eşiği          : %75   (50–90)
  [toggle] Daha az palet tercih et     : Açık
  [toggle] Farklı sipariş harmonla     : Açık
  [toggle] Karışık palet tipine izin   : Açık
  [select] Max optimizasyon süresi     : 30 sn (5/15/30/60)

BOYUT TOLERANSLARI
  [slider] Yükseklik taşma toleransı   : %5    (0–15)
  [slider] Genişlik taşma toleransı    : %5    (0–10)

FİZİK KURALLARI
  [input]  Max boşluk (CTU Code)       : 15 cm (5–30)
  [slider] TIR ön aks oranı (60/40)   : %60   (50–70)
  [slider] 60/40 toleransı             : %5    (2–10)
  [slider] Dil ağırlığı min            : %10   (5–20)
  [slider] Dil ağırlığı max            : %15   (10–25)
  [input]  Sürtünme eşiği (μ)          : 0.6   (0.3–0.8)

AMBALAJ ANALİZİ
  [toggle] McKee BCT hesabı            : Kapalı
  [input]  Karton kalınlığı            : 0.4 cm
  [select] Nem faktörü                 : Kuru (1.0) / Nemli (0.70) / Çok nemli (0.50)
  [radio]  İstifleme paterni           : Kilitli ○ Kolon

SOĞUK ZİNCİR
  [input]  Tavan boşluğu min           : 22 cm (20–30)
  [input]  Kapı boşluğu min            : 11 cm (10–15)

ULUSLARARASI
  [toggle] ISPM-15 zorunlu             : Kapalı
  [info]   EUMOS 40509 değerleri       : 0.8g ileri / 0.5g yanal (salt okunur)
```

---

## KISIM K — TEST SENARYOLARI

```python
# Tüm testlerde VehicleType ve PalletType nesneleri DB mock'tan gelir.
# String 'tir', 'panelvan' geçmez.

PANELVAN = VehicleType(code='PANELVAN_3', cargo_height_cm=180,
                        cargo_width_cm=180, cargo_length_cm=350,
                        max_payload_kg=1500, pallet_capacity=2,
                        is_reefer=False, wheelbase_cm=280)
TIR      = VehicleType(code='TIR_136', cargo_height_cm=270,
                        cargo_width_cm=245, cargo_length_cm=1360,
                        max_payload_kg=24000, pallet_capacity=33,
                        is_reefer=False, wheelbase_cm=600)
EUR      = PalletType(code='EUR', width_cm=80, length_cm=120,
                       tare_height_cm=15, max_weight_kg=1000,
                       tare_weight_kg=25, is_ispm15=False, material='wood')
DEFAULT_SETTINGS = OptimizerSettings()  # Tüm default değerler

def test_height_never_exceeded_panelvan():
    items = [create_item(h=100), create_item(h=100)]
    result = optimize(items, [EUR], [PANELVAN], [PANELVAN.id], [], DEFAULT_SETTINGS)
    max_h = (180 - 15) * 1.05  # (cargo_h - tare_h) * (1 + tolerance)
    for p in result['final']['pallets']:
        assert p['actual_height_cm'] <= max_h

def test_width_first_placement():
    items = [create_item(w=30, l=30, h=20) for _ in range(6)]
    result = optimize(items, [EUR], [TIR], [TIR.id], [], DEFAULT_SETTINGS)
    pallet = result['final']['pallets'][0]
    z_vals = [i['pos_z'] for i in pallet['items']]
    assert max(z_vals) == 0, "Yan yana yerleşim başarısız — üst üste dizilmiş"

def test_fragile_heavy_separation():
    items = [create_item(constraints=['fragile']), create_item(constraints=['heavy'])]
    result = optimize(items, [EUR], [TIR], [TIR.id], [], DEFAULT_SETTINGS)
    assert result['final']['total_pallets'] >= 2
    assert result['validation']['is_valid']

def test_multi_pallet_type_summary():
    STD = PalletType(code='STD', width_cm=100, length_cm=120,
                      tare_height_cm=15, max_weight_kg=1200,
                      tare_weight_kg=28, is_ispm15=False, material='wood')
    items = [create_item() for _ in range(100)]
    result = optimize(items, [EUR, STD], [TIR], [TIR.id], [], DEFAULT_SETTINGS)
    by_type = result['final']['pallets_by_type']
    assert isinstance(by_type, dict)
    assert 'total_pallets' in result['final']

def test_lifo_ordering():
    stops = [DeliveryStop(address='İzmir', sequence=1),
             DeliveryStop(address='Manisa', sequence=2)]
    items = [create_item(delivery_address='Manisa'), create_item(delivery_address='İzmir')]
    result = optimize(items, [EUR], [TIR], [TIR.id], stops, DEFAULT_SETTINGS)
    izmir_pal = next(p for p in result['final']['pallets'] if 'İzmir' in p['delivery_address'])
    manisa_pal = next(p for p in result['final']['pallets'] if 'Manisa' in p['delivery_address'])
    assert izmir_pal['load_sequence'] < manisa_pal['load_sequence']

def test_weight_balance_60_40():
    heavy_items = [create_item(weight_kg=500) for _ in range(10)]
    result = optimize(heavy_items, [EUR], [TIR], [TIR.id], [], DEFAULT_SETTINGS)
    assert result['validation']['is_valid']

def test_ispm15_violation_detected():
    s = OptimizerSettings(enforce_ispm15=True)
    wood_pallet = PalletType(code='WOOD', material='wood', is_ispm15=False,
                               width_cm=80, length_cm=120, tare_height_cm=15,
                               max_weight_kg=1000, tare_weight_kg=25)
    result = optimize([create_item()], [wood_pallet], [TIR], [TIR.id], [], s)
    error_codes = [e['code'] for e in result['validation']['errors']]
    assert 'ISPM15_VIOLATION' in error_codes

def test_actionable_errors_have_action():
    big_item = create_item(h=300)  # TIR'a sığmaz
    result = optimize([big_item], [EUR], [TIR], [TIR.id], [], DEFAULT_SETTINGS)
    assert not result['validation']['is_valid']
    for err in result['validation']['errors']:
        assert 'message' in err
        assert 'action_label' in err  # CEO isteği: eyleme geçirilebilir hata

def test_parametric_fill_rate():
    s_strict = OptimizerSettings(target_fill_rate_pct=95.0)
    s_loose  = OptimizerSettings(target_fill_rate_pct=60.0)
    items = [create_item() for _ in range(20)]
    r_strict = optimize(items, [EUR], [TIR], [TIR.id], [], s_strict)
    r_loose  = optimize(items, [EUR], [TIR], [TIR.id], [], s_loose)
    # Strict modda daha az palet kullanılması beklenir (daha dolu)
    assert r_strict['final']['avg_fill_rate_pct'] >= r_loose['final']['avg_fill_rate_pct']

def test_no_hardcoded_vehicle_string():
    import inspect, optimizer
    src = inspect.getsource(optimizer)
    forbidden = ["== 'tir'", "== 'panelvan'", "== 'kamyon'",
                 "'tir':270", "'panelvan':200", "VEHICLE_HEIGHT_LIMITS"]
    for pattern in forbidden:
        assert pattern not in src, f"Hardcode bulundu: {pattern}"
```

---

## KISIM L — GELİŞTİRME ÖNCELİKLERİ

```
SPRINT 1 — Kritik Bug Düzeltme:
  [ ] BUG-1 Height hard constraint — her yerleşimde kontrol
  [ ] BUG-2 Width-first placement — X→Y→Z sırası, Z'ye penalty
  [ ] BUG-3 DB-driven palet tipleri — sabit kodu kaldır
  [ ] Validation fonksiyonu zorunlu + ActionableError formatı

SPRINT 2 — Algoritma:
  [ ] 3D Layer-based Skyline (B.2 sınıflandırması)
  [ ] 2-Aşamalı heuristic (FFD → Skyline)
  [ ] Sipariş + teslim noktası gruplaması
  [ ] PalletDetail'e order_ids / delivery_address / load_sequence

SPRINT 3 — Lojistik Kurallar:
  [ ] LIFO pozisyonlama (çok duraklı rota)
  [ ] 60/40 kural + aks yükü hesabı
  [ ] Void gap kontrolü (CTU Code 15 cm)
  [ ] Kullanıcı override + yeniden validasyon

SPRINT 4 — Ayarlar Ekranı:
  [ ] OptimizerSettings tablo + API
  [ ] Ayarlar UI (Optimizasyon Sekmesi — Bölüm J)
  [ ] McKee BCT hesabı (packaging_enabled toggle)
  [ ] ISPM-15 toggle
  [ ] Reefer clearance parametreleri

SPRINT 5 — İleri:
  [ ] Öneri motoru entegrasyonu (doluluk eşiği aşılınca)
  [ ] VGM kontrolü (konteyner deniz yolu)
  [ ] Anti-slip mat uyarısı (sürtünme eşiği)
  [ ] Stacking pattern seçici (column/interlocked)
```

---

*Cronoi LS — OPTIMIZER_SPEC v3.0*
*Bir sonraki sprint başında bu dosya güncellenerek üzerine ekleme yapılır.*
*CRONOI_LS_SPEC_FOR_AI.md ve CRONOI_LS_STATUS_MODEL.md ile birlikte kullanılır.*
