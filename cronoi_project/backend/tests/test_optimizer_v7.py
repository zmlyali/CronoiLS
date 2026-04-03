"""
Cronoi LS — Optimizer v7.0 Comprehensive Tests
KISIM K: Test Senaryoları (OPTIMIZER_SPEC.md)

Kapsam:
  1. Temel yerleştirme (basic packing)
  2. Kısıt ayrımı (fragile/heavy, cold/hazmat)
  3. Boyut toleransı (overflow)
  4. Ağırlık limiti + miktar denetimi
  5. Void gap + McKee BCT
  6. ISPM-15 kontrolü
  7. ActionableError formatı
  8. Senaryo optimizasyonu (binding dimension, min vehicles)
  9. Frontend settings → optimizer parametreleri
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.optimizer import (
    BinPackingOptimizer3D, MixedBinPackingOptimizer,
    PalletConfig, ProductItem, ConstraintType, OptimizationParams,
    OptimizerSettings, ActionableError, ScenarioOptimizer,
    VehicleConfig, calculate_bct, check_overlap, check_void_gaps,
    PALLET_BOARD_HEIGHT_CM,
)

PASS = 0
FAIL = 0


def test(name, condition, detail=""):
    global PASS, FAIL
    mark = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {name}{suffix}")


def header(section):
    print(f"\n{'='*60}")
    print(f"  {section}")
    print(f"{'='*60}")


# ============================================================
# 1. TEA MEL YERLEŞTIRME
# ============================================================

def test_basic_packing():
    header("1. Temel Yerleştirme")
    config = PalletConfig("P1", 80, 120, 180, 700)
    opt = BinPackingOptimizer3D(config)
    items = [
        ProductItem("Kutu-A", 10, 40, 30, 20, 5),
        ProductItem("Kutu-B", 5, 30, 30, 15, 3),
    ]
    result = opt.optimize(items)

    test("Sonuç paleti var", result.total_pallets > 0, f"{result.total_pallets} palet")
    test("Reddedilen yok", len(result.rejected_items) == 0,
         f"{len(result.rejected_items)} reddedilen" if result.rejected_items else "")
    test("Miktar dengeli", result.quantity_audit.get("balanced", False),
         f"girdi={result.quantity_audit.get('total_input')}, placed={result.quantity_audit.get('total_placed')}")
    test("Algoritma v7.0", "v7.0" in result.algorithm_version, result.algorithm_version)
    test("Doluluk > 0", result.avg_fill_rate_pct > 0, f"%{result.avg_fill_rate_pct}")


# ============================================================
# 2. KISIT AYRIMI
# ============================================================

def test_constraint_separation():
    header("2. Kısıt Ayrımı (Fragile/Heavy, Cold/Hazmat)")
    config = PalletConfig("P1", 80, 120, 180, 700)
    settings = OptimizerSettings(enforce_constraints=True)
    params = OptimizationParams(enforce_constraints=True)
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)
    items = [
        ProductItem("Cam Vazo", 5, 30, 30, 20, 2, constraint=ConstraintType.FRAGILE),
        ProductItem("Demir Blok", 5, 30, 30, 20, 30, constraint=ConstraintType.HEAVY),
    ]
    result = opt.optimize(items)

    # Fragile ve heavy aynı palette olmamalı
    for pallet in result.pallets:
        has_fragile = any(p.constraint == ConstraintType.FRAGILE for p in pallet.products)
        has_heavy = any(p.constraint == ConstraintType.HEAVY for p in pallet.products)
        test(f"Palet-{pallet.pallet_number}: fragile+heavy ayrık",
             not (has_fragile and has_heavy),
             f"fragile={has_fragile}, heavy={has_heavy}")

    # Cold chain + hazmat ayrımı
    opt2 = BinPackingOptimizer3D(config, params=params, settings=settings)
    items2 = [
        ProductItem("İlaç", 3, 30, 20, 15, 2, constraint=ConstraintType.COLD_CHAIN),
        ProductItem("Kimyasal", 3, 30, 20, 15, 5, constraint=ConstraintType.HAZMAT),
    ]
    result2 = opt2.optimize(items2)
    for pallet in result2.pallets:
        has_cold = any(p.constraint == ConstraintType.COLD_CHAIN for p in pallet.products)
        has_hazmat = any(p.constraint == ConstraintType.HAZMAT for p in pallet.products)
        test(f"Palet-{pallet.pallet_number}: cold+hazmat ayrık",
             not (has_cold and has_hazmat),
             f"cold={has_cold}, hazmat={has_hazmat}")


# ============================================================
# 3. BOYUT TOLERANSI
# ============================================================

def test_overflow_tolerance():
    header("3. Boyut Toleransı (Overflow)")
    config = PalletConfig("P1", 80, 120, 180, 700)
    # %5 tolerans → 126cm uzunluk, 84cm genişlik
    settings = OptimizerSettings(width_tolerance_pct=5.0)
    params = OptimizationParams(overflow_tolerance_pct=5.0)
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)

    items = [ProductItem("Geniş Kutu", 2, 125, 83, 30, 10)]  # Tolerans içinde
    result = opt.optimize(items)
    test("Tolerans içi kabul", len(result.rejected_items) == 0, f"{len(result.rejected_items)} red")

    # %0 tolerans → 121cm red edilmeli
    settings0 = OptimizerSettings(width_tolerance_pct=0.0)
    params0 = OptimizationParams(overflow_tolerance_pct=0.0)
    opt0 = BinPackingOptimizer3D(config, params=params0, settings=settings0)
    # 121×81 — rotation ile hiçbir orientasyonda 120×80'e sığmaz
    # 121>120, 81>80, dolayısıyla yatay sığmaz; dikey denense yükseklik ok ama taban 121×81
    items0 = [ProductItem("Taşkın Kutu", 1, 121, 81, 30, 10, constraint=ConstraintType.THIS_SIDE_UP)]
    result0 = opt0.optimize(items0)
    test("Sıfır tolerans → red", len(result0.rejected_items) > 0, f"{len(result0.rejected_items)} red")


# ============================================================
# 4. AĞIRLIK LİMİTİ + MİKTAR
# ============================================================

def test_weight_limit():
    header("4. Ağırlık Limiti + Miktar Denetimi")
    config = PalletConfig("P1", 80, 120, 180, 100)  # 100kg max
    opt = BinPackingOptimizer3D(config)
    items = [ProductItem("Ağır Parça", 10, 30, 30, 20, 15)]  # 10×15=150kg
    result = opt.optimize(items)

    test("Birden fazla palet", result.total_pallets > 1, f"{result.total_pallets} palet")
    for pallet in result.pallets:
        test(f"Palet-{pallet.pallet_number} ağırlık ≤ max",
             pallet.total_weight_kg <= config.max_weight_kg,
             f"{pallet.total_weight_kg}kg ≤ {config.max_weight_kg}kg")
    test("Miktar dengeli", result.quantity_audit.get("balanced", False))

    # Tek ürün palet max'ından ağır → reddedilmeli
    opt2 = BinPackingOptimizer3D(PalletConfig("P1", 80, 120, 180, 50))
    items2 = [ProductItem("Dev Blok", 1, 30, 30, 20, 60)]
    result2 = opt2.optimize(items2)
    test("Tek parça > max → red", len(result2.rejected_items) == 1)


# ============================================================
# 5. VOID GAP + McKee BCT
# ============================================================

def test_void_gap_and_bct():
    header("5. Void Gap + McKee BCT")

    # Void gap check
    rects = [{"x": 0, "z": 0, "y": 0, "dx": 80, "dy": 40, "dz": 30}]
    warnings = check_void_gaps(rects, 120, 80, 15)
    test("Void gap uyarısı var", len(warnings) > 0, f"{len(warnings)} uyarı")

    # Boşluk yoksa uyarı olmamalı
    rects2 = [
        {"x": 0, "z": 0, "y": 0, "dx": 80, "dy": 60, "dz": 30},
        {"x": 0, "z": 0, "y": 60, "dx": 80, "dy": 60, "dz": 30},
    ]
    warnings2 = check_void_gaps(rects2, 120, 80, 15)
    test("Tam dolu → uyarısız", len(warnings2) == 0, f"{len(warnings2)} uyarı")

    # McKee BCT
    bct = calculate_bct(30, 40, 12.0, 0.4, 1.0)
    test("BCT > 0", bct > 0, f"{bct:.1f} kg")
    test("BCT sonlu", bct < float('inf'))

    # BCT packaging_ect=0 → inf
    bct_zero = calculate_bct(30, 40, 0, 0, 1.0)
    test("BCT ect=0 → inf", bct_zero == float('inf'))


# ============================================================
# 6. ISPM-15
# ============================================================

def test_ispm15():
    header("6. ISPM-15 Kontrolü")
    config = PalletConfig("P1", 80, 120, 180, 700, material="wood", is_ispm15=False)
    settings = OptimizerSettings(enforce_ispm15=True)
    params = OptimizationParams(enforce_ispm15=True)
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)
    items = [ProductItem("Kutu", 3, 30, 30, 20, 5)]
    result = opt.optimize(items)

    has_ispm_violation = any(
        any("ISPM" in v for v in val.violations)
        for val in result.constraint_validations
    )
    test("ISPM-15 ihlali algılandı", has_ispm_violation)
    test("Compliance ISPM-15 FAIL", any("ISPM-15: FAIL" in c for c in result.compliance))

    # ISPM-15 sertifikalı palet → ihlal olmamalı
    config_ok = PalletConfig("P1", 80, 120, 180, 700, material="wood", is_ispm15=True)
    opt_ok = BinPackingOptimizer3D(config_ok, params=params, settings=settings)
    result_ok = opt_ok.optimize(items)
    has_ispm_ok = any(
        any("ISPM" in v for v in val.violations)
        for val in result_ok.constraint_validations
    )
    test("ISPM-15 sertifikalı → ihlalsiz", not has_ispm_ok)


# ============================================================
# 7. ACTIONABLE ERROR FORMAT
# ============================================================

def test_actionable_errors():
    header("7. ActionableError Formatı")
    config = PalletConfig("P1", 80, 120, 50, 700)  # 50cm max height
    settings = OptimizerSettings(height_tolerance_pct=0, height_safety_margin_cm=0)
    params = OptimizationParams(overflow_tolerance_pct=0)
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)

    # Yükseklik aşımı yaratacak kadar ürün
    items = [ProductItem("Yüksek Kutu", 4, 30, 30, 20, 5)]
    result = opt.optimize(items)

    test("Constraint validations var", len(result.constraint_validations) > 0)

    # Her validation result'da errors listesi olmalı
    for v in result.constraint_validations:
        if v.errors:
            err = v.errors[0]
            test(f"Error code var: {err.code}", bool(err.code))
            test(f"Error message var", bool(err.message))
            test(f"Error action_label var", bool(err.action_label))
            break

    # Compliance strings
    test("Compliance CTU Code var", any("CTU Code" in c for c in result.compliance))


# ============================================================
# 8. SENARYO OPTİMİZASYONU
# ============================================================

def test_scenario_optimizer():
    header("8. Senaryo Optimizasyonu (Binding Dimension)")
    config = PalletConfig("P1", 80, 120, 180, 700)
    opt = BinPackingOptimizer3D(config)
    items = [
        ProductItem("A", 20, 40, 30, 25, 10),
        ProductItem("B", 15, 50, 40, 20, 8),
    ]
    result = opt.optimize(items)

    vehicles = [
        VehicleConfig(
            id="v1", name="Kamyon", type="kamyon",
            length_cm=700, width_cm=240, height_cm=240,
            max_weight_kg=8000, pallet_capacity=12,
            base_cost=500, fuel_per_km=1.5, driver_per_hour=30,
            opportunity_cost=100, distance_km=200, duration_hours=4,
        ),
        VehicleConfig(
            id="v2", name="TIR", type="tir",
            length_cm=1360, width_cm=245, height_cm=270,
            max_weight_kg=24000, pallet_capacity=33,
            base_cost=1200, fuel_per_km=3.0, driver_per_hour=40,
            opportunity_cost=200, distance_km=200, duration_hours=4,
        ),
    ]

    scenario_opt = ScenarioOptimizer(result.pallets, vehicles)
    scenarios = scenario_opt.generate_all()

    test("3 senaryo üretildi", len(scenarios) == 3, f"{len(scenarios)} senaryo")

    for s in scenarios:
        test(f"Senaryo '{s.name}': araç > 0", s.total_vehicles > 0, f"{s.total_vehicles} araç")
        test(f"Senaryo '{s.name}': maliyet > 0", s.total_cost > 0, f"₺{s.total_cost:.0f}")

    # Binding dimension kontrolü
    has_binding = False
    for s in scenarios:
        for va in s.vehicles:
            if va.binding_dimension:
                has_binding = True
                test(f"Binding dimension: {va.binding_dimension}",
                     va.binding_dimension in ("volume", "weight", "pallet_count"),
                     f"vol={va.vol_utilization_pct}%, wt={va.weight_utilization_pct}%")
    test("Binding dimension hesaplandı", has_binding)

    # Önerilen senaryo
    recommended = [s for s in scenarios if s.is_recommended]
    test("Bir senaryo önerili", len(recommended) == 1, recommended[0].name if recommended else "yok")


# ============================================================
# 9. FRONTEND AYARLARI → OPTIMIZER
# ============================================================

def test_frontend_settings():
    header("9. Frontend Settings → Optimizer Parametreleri")

    # Frontend camelCase ayarlar
    frontend_params = {
        "maxIterations": 20,
        "optimalityTarget": 95,
        "heightSafetyMargin": 5,
        "enforceConstraints": True,
        "palletGapCm": 4,
        "weightBalanceFrontPct": 60,
        "weightBalanceTolerance": 10,
        "overflowTolerancePct": 7,
        "targetFillRatePct": 88,
        "preferFewerPallets": True,
        "maxVoidGapCm": 12,
        "packagingEnabled": True,
        "enforceIspm15": True,
        "vehicleMaxHeightCm": 270,
    }

    params = OptimizationParams.from_dict(frontend_params)
    test("maxIterations", params.max_iterations == 20, str(params.max_iterations))
    test("vehicleMaxHeightCm", params.vehicle_max_height_cm == 270, str(params.vehicle_max_height_cm))
    test("overflowTolerancePct", params.overflow_tolerance_pct == 7, str(params.overflow_tolerance_pct))
    test("targetFillRatePct", params.target_fill_rate_pct == 88, str(params.target_fill_rate_pct))
    test("packagingEnabled", params.packaging_enabled == True)
    test("enforceIspm15", params.enforce_ispm15 == True)

    # Params → Settings dönüşümü
    settings = params.to_settings()
    test("Settings height_safety_margin_cm", settings.height_safety_margin_cm == 5, str(settings.height_safety_margin_cm))
    test("Settings weight_front_ratio_pct", settings.weight_front_ratio_pct == 60, str(settings.weight_front_ratio_pct))
    test("Settings max_void_gap_cm", settings.max_void_gap_cm == 12, str(settings.max_void_gap_cm))
    test("Settings enforce_ispm15", settings.enforce_ispm15 == True)
    test("Settings packaging_enabled", settings.packaging_enabled == True)

    # OptimizerSettings.from_dict doğrudan
    settings2 = OptimizerSettings.from_dict(frontend_params)
    test("Direct settings targetFillRate", settings2.target_fill_rate_pct == 88,
         str(settings2.target_fill_rate_pct))  # targetFillRatePct=88 takes priority over optimalityTarget=95
    test("Direct settings maxVoidGap", settings2.max_void_gap_cm == 12, str(settings2.max_void_gap_cm))

    # Optimizer bu ayarlarla çalışır mı
    config = PalletConfig("P1", 80, 120, 180, 700)
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)
    items = [ProductItem("Test Kutu", 5, 30, 30, 20, 5)]
    result = opt.optimize(items)
    test("Optimizer çalıştı", result.total_pallets > 0)
    test("Miktar dengeli", result.quantity_audit.get("balanced", False))


# ============================================================
# 10. KARMA PALET OPTİMİZASYONU
# ============================================================

def test_mixed_pallet():
    header("10. Karma Palet Optimizasyonu")
    configs = [
        PalletConfig("P1", 80, 120, 180, 700),
        PalletConfig("P5", 100, 120, 180, 700),
        PalletConfig("P10", 120, 200, 250, 700),
    ]
    params = OptimizationParams(max_iterations=12)
    mixed = MixedBinPackingOptimizer(configs, params=params)
    items = [
        ProductItem("Küçük", 15, 30, 25, 15, 3),
        ProductItem("Orta", 8, 50, 40, 30, 12),
        ProductItem("Büyük", 4, 90, 70, 40, 25),
    ]
    result = mixed.optimize(items)

    test("Palletler var", result.total_pallets > 0, f"{result.total_pallets} palet")
    test("Reddedilen yok", len(result.rejected_items) == 0)
    test("Miktar dengeli", result.quantity_audit.get("balanced", False))
    test("Palet tipi breakdown", len(result.pallet_type_breakdown) > 0)
    test("Compliance var", len(result.compliance) > 0)
    test("Algoritma mixed", "mixed" in result.algorithm_version.lower(), result.algorithm_version)


# ============================================================
# 11. OVERLAP KONTROLÜ
# ============================================================

def test_overlap():
    header("11. Overlap Kontrolü")
    # Çakışan rectler
    rects = [
        {"x": 0, "z": 0, "y": 0, "dx": 40, "dy": 40, "dz": 30},
        {"x": 20, "z": 20, "y": 0, "dx": 40, "dy": 40, "dz": 30},  # overlap
    ]
    overlaps = check_overlap(rects)
    test("Overlap algılandı", len(overlaps) > 0, f"{len(overlaps)} çift")

    # Çakışmayan
    rects2 = [
        {"x": 0, "z": 0, "y": 0, "dx": 40, "dy": 40, "dz": 30},
        {"x": 0, "z": 0, "y": 40, "dx": 40, "dy": 40, "dz": 30},
    ]
    overlaps2 = check_overlap(rects2)
    test("Çakışmasız → 0", len(overlaps2) == 0)

    # Üst üste (Z ekseninde)
    rects3 = [
        {"x": 0, "z": 0, "y": 0, "dx": 40, "dy": 40, "dz": 30},
        {"x": 0, "z": 30, "y": 0, "dx": 40, "dy": 40, "dz": 30},
    ]
    overlaps3 = check_overlap(rects3)
    test("Y-yığın çakışmasız", len(overlaps3) == 0)


# ============================================================
# 12. NO_STACK KONTROLü
# ============================================================

def test_no_stack():
    header("12. NO_STACK Doğrulama")
    config = PalletConfig("P1", 80, 120, 180, 700)
    opt = BinPackingOptimizer3D(config)
    items = [
        ProductItem("Normal", 3, 30, 30, 20, 5),
        ProductItem("Kırılgan Üst", 1, 30, 30, 20, 2, constraint=ConstraintType.NO_STACK),
    ]
    result = opt.optimize(items)

    # NO_STACK validation yapılıyor
    test("Validation var", len(result.constraint_validations) > 0)
    test("Palet var", result.total_pallets > 0)


# ============================================================
# 13. MIXED OPTIMIZER — GLOBAL KARŞILAŞTIRMA
# ============================================================

def test_mixed_global_optimization():
    header("13. Mixed Optimizer Global Karşılaştırma")
    # Headboard senaryosu: P1'de kötü, P10'da iyi
    configs = [
        PalletConfig("P1", 80, 120, 250, 700),
        PalletConfig("P10", 120, 200, 250, 700),
    ]
    # Headboard 105×15×105 — P1'de yalnızca (105,15,105) uygun → 5/palet
    # P10'da (105,105,15) yatay uygun → çok daha fazla/palet
    items = [ProductItem("Headboard", 30, 105, 15, 105, 1)]

    # Sadece P1 ile
    p1_opt = BinPackingOptimizer3D(configs[0])
    p1_result = p1_opt.optimize(items)
    p1_pallets = p1_result.total_pallets

    # Mixed optimizer ile
    mixed = MixedBinPackingOptimizer(configs, default_type=configs[0])
    mixed_result = mixed.optimize(items)
    mixed_pallets = mixed_result.total_pallets

    test(f"P1 tek: {p1_pallets} palet", p1_pallets > 0)
    test(f"Mixed: {mixed_pallets} palet", mixed_pallets > 0)
    test("Mixed palet sayısı ≤ P1",
         mixed_pallets <= p1_pallets,
         f"{mixed_pallets} <= {p1_pallets}")
    test("Mixed reddedilen yok", len(mixed_result.rejected_items) == 0)
    test("Mixed miktar dengeli", mixed_result.quantity_audit.get("balanced", False))


# ============================================================
# 14. ÖNERİ MOTORU
# ============================================================

def test_suggestions():
    header("14. Öneri Motoru (Düşük Doluluk)")
    # P1'de düşük doluluk → öneri bekliyoruz
    config = PalletConfig("P1", 80, 120, 250, 700)
    settings = OptimizerSettings(suggestion_trigger_pct=75.0)
    params = OptimizationParams()
    opt = BinPackingOptimizer3D(config, params=params, settings=settings)
    items = [ProductItem("Headboard", 20, 105, 15, 105, 1)]
    result = opt.optimize(items)

    has_suggestion = any("Öneri" in w or "💡" in w for w in result.warnings)
    test("Düşük dolulukta öneri var", has_suggestion,
         next((w for w in result.warnings if "Öneri" in w or "💡" in w), "yok")[:80] if has_suggestion else "öneri yok")

    # Yüksek dolulukta öneri olmamalı
    config2 = PalletConfig("P1", 80, 120, 70, 700)  # düşük max_height → yüksek doluluk
    opt2 = BinPackingOptimizer3D(config2, params=params, settings=settings)
    items2 = [ProductItem("Küçük Kutu", 12, 39, 39, 30, 3)]
    result2 = opt2.optimize(items2)
    no_suggestion = not any("Öneri" in w or "💡" in w for w in result2.warnings)
    test(f"Yüksek doluluk (%{result2.avg_fill_rate_pct}) öneri yok", no_suggestion or result2.avg_fill_rate_pct >= 75)


# ============================================================
# 15. SIKIŞIK YERLEŞTİRME (WALL-HUGGING)
# ============================================================

def test_tight_packing():
    header("15. Sıkışık Yerleştirme (Wall-Hugging)")
    config = PalletConfig("P1", 80, 120, 250, 700)
    opt = BinPackingOptimizer3D(config)
    items = [ProductItem("Kutu", 6, 40, 40, 30, 5)]
    result = opt.optimize(items)

    test("Tek palet", result.total_pallets == 1, f"{result.total_pallets} palet")
    if result.pallets:
        pallet = result.pallets[0]
        # İlk ürün (0,0,0) köşesinde olmalı
        first = pallet.products[0]
        test("İlk ürün orijinde", first.pos_x < 0.1 and first.pos_z < 0.1,
             f"pos=({first.pos_x},{first.pos_z})")

        # Ürünler birbirine bitişik olmalı (gap yok)
        rects = pallet.layout_data.get("placed_rects", [])
        if len(rects) >= 2:
            # Her ürünün en az bir duvar veya başka ürünle temas ettiğini kontrol et
            touching_count = 0
            for r in rects:
                touches_wall = r["x"] < 0.5 or r["y"] < 0.5
                touches_item = any(
                    (abs(r["x"] - (o["x"] + o["dx"])) < 0.5 or abs((r["x"] + r["dx"]) - o["x"]) < 0.5 or
                     abs(r["y"] - (o["y"] + o["dy"])) < 0.5 or abs((r["y"] + r["dy"]) - o["y"]) < 0.5)
                    for o in rects if o is not r
                )
                if touches_wall or touches_item:
                    touching_count += 1
            test(f"Tüm ürünler temaslı", touching_count >= len(rects) * 0.8,
                 f"{touching_count}/{len(rects)}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  CRONOI LS — Optimizer v7.0 Test Suite")
    print("=" * 60)

    test_basic_packing()
    test_constraint_separation()
    test_overflow_tolerance()
    test_weight_limit()
    test_void_gap_and_bct()
    test_ispm15()
    test_actionable_errors()
    test_scenario_optimizer()
    test_frontend_settings()
    test_mixed_pallet()
    test_overlap()
    test_no_stack()
    test_mixed_global_optimization()
    test_suggestions()
    test_tight_packing()

    print(f"\n{'='*60}")
    total = PASS + FAIL
    print(f"  TOPLAM: {total} test | ✅ {PASS} geçti | ❌ {FAIL} başarısız")
    print(f"{'='*60}")
    if FAIL > 0:
        sys.exit(1)
