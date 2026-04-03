tam"""Headboard yerleştirme analiz scripti — debug modu."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.optimizer import (
    BinPackingOptimizer3D, PalletConfig, ProductItem, OptimizerSettings
)

def run_analysis():
    # Palet: P7 Özel Boy 100x200, maxH=240 (kullanıcının seçtiği)
    config = PalletConfig(
        type="P7", length_cm=200, width_cm=100,
        max_height_cm=240, max_weight_kg=1500,
    )
    settings = OptimizerSettings()
    settings.overflow_tolerance_pct = 5

    # 17 adet Headboard: 185x105x15 cm, 1kg
    products = [
        ProductItem(name="Headboard", quantity=17,
                    length_cm=185, width_cm=105, height_cm=15, weight_kg=1.0)
    ]

    print("=" * 70)
    print("HEADBOARD ANALİZ — 17× (185×105×15cm) → P7 (100×200, maxH=240)")
    print("=" * 70)

    opt = BinPackingOptimizer3D(config, settings=settings)

    # Orientasyonları göster
    item = ProductItem(name="Headboard", quantity=1,
                       length_cm=185, width_cm=105, height_cm=15, weight_kg=1.0)
    orients = opt._get_valid_orientations(item)
    print(f"\n📐 Geçerli orientasyonlar ({len(orients)} adet):")
    print(f"   Palet efektif: L={opt._overflow_length:.0f} W={opt._overflow_width:.0f} H={opt._effective_max_height:.0f}")
    for i, (l, w, h, rot) in enumerate(orients):
        floor_x = int(opt._overflow_length // l)
        floor_z = int(opt._overflow_width // w)
        cap = floor_x * floor_z
        print(f"   [{i}] {l}×{w}×{h}cm (h={h}) rotated={rot} | zemin kapasitesi: {floor_x}×{floor_z}={cap} adet")

    # Optimizasyon çalıştır
    print(f"\n🚀 Optimizasyon başlıyor...")
    result = opt.optimize(products)

    print(f"\n📊 SONUÇ: {result.total_pallets} palet, doluluk=%{result.avg_fill_rate_pct}")
    print(f"   Reddedilen: {len(result.rejected_items)}")
    if result.rejected_items:
        for r in result.rejected_items:
            print(f"   ❌ {r.name}: {r.reason}")

    for pallet in result.pallets:
        print(f"\n📦 Palet #{pallet.pallet_number} ({pallet.pallet_type})")
        print(f"   Ürün sayısı: {sum(p.quantity for p in pallet.products)}")
        print(f"   Toplam yükseklik: {pallet.total_height_cm} cm")
        print(f"   Toplam ağırlık: {pallet.total_weight_kg} kg")
        print(f"   Doluluk: %{pallet.fill_rate_pct}")

        rects = pallet.layout_data.get("placed_rects", [])
        print(f"   Yerleştirilen rect'ler ({len(rects)}):")
        for j, r in enumerate(rects):
            top = r['z'] + r['dz']
            orient_type = "FLAT" if r['dz'] < 20 else ("BOOKSHELF" if r['dz'] > 100 else "MID")
            print(f"     [{j:2d}] pos=({r['x']:6.1f}, {r['y']:6.1f}, {r['z']:6.1f}) "
                  f"size=({r['dx']:5.1f}×{r['dy']:5.1f}×{r['dz']:5.1f}) "
                  f"top_z={top:6.1f} | {orient_type}")

        # Yükseklik ihlali kontrolü
        max_z = max((r['z'] + r['dz'] for r in rects), default=0)
        if max_z > config.max_height_cm:
            print(f"   ⛔ YÜKSEKLİK İHLALİ: {max_z:.1f} > {config.max_height_cm}")
        else:
            print(f"   ✅ Yükseklik OK: {max_z:.1f} ≤ {config.max_height_cm}")

    # Validasyon sonuçları
    print(f"\n🔍 Validasyon:")
    for v in result.constraint_validations:
        status = "✅ PASS" if v.passed else "❌ FAIL"
        print(f"   Palet #{v.pallet_number}: {status}")
        for viol in v.violations:
            print(f"      ⛔ {viol}")
        for w in v.warnings:
            print(f"      ⚠️ {w}")

    print(f"\n{'=' * 70}")


if __name__ == "__main__":
    run_analysis()
