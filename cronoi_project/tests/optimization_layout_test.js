/**
 * Cronoi LS — Optimizasyon Yerleşim Test Harness'ı
 * ================================================
 * Amaç: Palet→araç optimizasyon motorunu (zemin paketleme + dikey istif + filo) ve
 *       3D render ile TUTARLILIĞINI (taşma yok, yan yana dizilim) doğrular.
 *
 * Motoru frontend HTML'inden (tek kaynak) çıkarır → kod ve test ASLA ayrışmaz.
 *
 * Çalıştır:  node tests/optimization_layout_test.js
 *            (cronoi_project/cronoi_project klasöründen)
 *
 * Yeni test eklemek için: CASES dizisine bir nesne ekle (aşağıdaki şema).
 */

const fs = require('fs');
const path = require('path');

// ── 1) Motoru HTML'den çıkar (brace-matched) ──────────────────────────────
const HTML = path.join(__dirname, '..', 'frontend', 'Cronoi_LS_v2.html');
const src = fs.readFileSync(HTML, 'utf8');

function extractFn(name) {
  const sig = 'function ' + name;
  const s = src.indexOf(sig);
  if (s < 0) throw new Error('Fonksiyon bulunamadı: ' + name);
  let i = src.indexOf('{', s), d = 0, e = -1;
  for (; i < src.length; i++) {
    if (src[i] === '{') d++;
    else if (src[i] === '}') { d--; if (d === 0) { e = i + 1; break; } }
  }
  return src.slice(s, e);
}

// APP/global stub'ları (motorun beklediği ortam)
global._selectedVehicleIdx = 0;
global.APP = {
  state: { vehicles: [], pallets: [] },
  config: {
    engine: { palletGapCm: 1, usableVolumeFactorPct: 90 },
    palletTypes: { p: { tareHeightCm: 15 } },
    vehicleTypes: {},
  },
};
global.VEHICLE_COST_DEFAULTS = {};

const ENGINE_FNS = [
  '_getVehDefaults', '_palletFootprint', '_floorItemsFromPallets', '_palletPhysHcm',
  '_canStackPallet', '_stackPallets', '_buildRows', '_packFloor', '_vehUsableVol',
  '_computePalletSlots', '_buildFleetOfType', '_getFleetBreakdown', '_calcFleetVolumes',
  '_repackScenarioFloorAware', '_ensureScenarioFloorFit',
];
// TEK eval (fonksiyon bildirimleri modül kapsamına sızar; destructure ETME → "already declared")
eval(ENGINE_FNS.map(extractFn).join('\n'));

// ── 2) Araç tipleri (gerçek sistem değerleri) ─────────────────────────────
const VEHICLES = {
  konteyner40hc: { name: 'Konteyner 40ft HC', icon: '🚢', type: 'container',
                   length: 1198, width: 233, height: 255, maxWeight: 26000, usableVolume: 72, is_active: true },
  tir:           { name: 'TIR (Standart)', icon: '🚛', type: 'truck',
                   length: 1360, width: 245, height: 270, maxWeight: 24000, usableVolume: 90, is_active: true },
};

// ── 3) Yardımcılar ────────────────────────────────────────────────────────
let _pid = 0;
function makePallets(n, PW, PL, PH, stackable, weight) {
  return Array.from({ length: n }, () => ({
    id: ++_pid, source: 'prepack', constraints: [], totalHeight: PH,
    totalWeight: weight || 100, totalVolume: (PW * PL * PH) / 1e6,
    layout: { width: PW, length: PL }, type: 'p', stackable: stackable !== false,
  }));
}

// Bir aracı TAM dolduracak palet adedini geometriden hesapla (yan yana × sıra × kat)
function fullLoadCount(vt, PW, PL, PH, gap = 1, margin = 1) {
  const Lu = vt.length - 2 * margin, Wu = vt.width - 2 * margin;
  const across = Math.floor((Wu + gap) / (PW + gap));
  const rows = Math.floor((Lu + gap) / (PL + gap));
  const high = Math.floor(vt.height / PH);
  return { count: across * rows * high, across, rows, high, columns: across * rows };
}

// Bir aracın paletleri zemine SIĞIYOR mu (render ile AYNI _packFloor) → taşma kontrolü
function vehicleOverflow(v, vt) {
  if (!Array.isArray(v.cols) || !v.cols.length) return true;
  const pf = _packFloor(v.cols.map((c, i) => ({ id: i, w: c.wCm, l: c.lCm, h: c.usedH })),
                        vt.length, vt.width, 1, 1);
  return pf.unplaced.length > 0;
}

// Bir araçta kaç farklı Z (en) konumu var → yan yana dizilim göstergesi
function sideBySideRows(v, vt) {
  const pf = _packFloor(v.cols.map((c, i) => ({ id: i, w: c.wCm, l: c.lCm, h: c.usedH })),
                        vt.length, vt.width, 1, 1);
  return new Set(pf.placed.map(p => Math.round(p.zCm))).size;
}

function floorPct(v, vt) {
  const used = v.cols.reduce((s, c) => s + c.wCm * c.lCm, 0);
  return used / ((vt.length - 2) * (vt.width - 2)) * 100;
}

// ── 4) TEST DURUMLARI ─────────────────────────────────────────────────────
// Her durum: { name, vtCode, pallets(), expect:{ vehicles, minFloorPct, sideBySide, minLdmPct } }
const CASES = [];

// (A) TAM 1 × 40ft konteyner — geometri ile tam dolu
(() => {
  const vt = VEHICLES.konteyner40hc;
  const f = fullLoadCount(vt, 115, 195, 125);   // 2 yan yana × 6 sıra × 2 kat = 24
  CASES.push({
    name: `Tam 1 konteyner (40ft HC) — ${f.count} palet [${f.across}×${f.rows}×${f.high}]`,
    vtCode: 'konteyner40hc', vt,
    pallets: () => makePallets(f.count, 115, 195, 125, true, 200),
    expect: { vehicles: 1, minFloorPct: 90, sideBySide: 2, minLdmPct: 90, noOverflow: true },
  });
})();

// (B) Tam 1 konteyner + 1 palet → 2 araç olmalı (eşik testi)
(() => {
  const vt = VEHICLES.konteyner40hc;
  const f = fullLoadCount(vt, 115, 195, 125);
  CASES.push({
    name: `Eşik: tam konteyner + 1 palet (${f.count + 1}) → 2 araç`,
    vtCode: 'konteyner40hc', vt,
    pallets: () => makePallets(f.count + 1, 115, 195, 125, true, 200),
    expect: { vehicles: 2, noOverflow: true },
  });
})();

// (C) Tam 1 TIR — EUR 80×120, istiflenmez, tek kat (klasik 33 EUR)
(() => {
  const vt = VEHICLES.tir;
  CASES.push({
    name: 'Tam 1 TIR — 33 EUR (80×120, tek kat)',
    vtCode: 'tir', vt,
    pallets: () => makePallets(33, 80, 120, 240, false, 300),
    expect: { vehicles: 1, minFloorPct: 70, sideBySide: 3, noOverflow: true },
  });
})();

// (D) Yan yana doğrulama — headboard 108×210 konteynerde 2 yan yana, 2 kat
(() => {
  const vt = VEHICLES.konteyner40hc;
  CASES.push({
    name: 'Yan yana: 108×210 headboard (2 across, 2 kat)',
    vtCode: 'konteyner40hc', vt,
    pallets: () => makePallets(20, 108, 210, 124, true, 100),
    expect: { vehicles: 1, sideBySide: 2, noOverflow: true },
  });
})();

// (E) Over-assignment kurtarma — backend 1 araca tıkıştırırsa ensureFloorFit dağıtır
(() => {
  const vt = VEHICLES.konteyner40hc;
  CASES.push({
    name: 'Repack güvenlik: 1 araca aşırı atama → zemin-fit dağıtım',
    vtCode: 'konteyner40hc', vt, repack: true,
    pallets: () => makePallets(60, 115, 195, 125, true, 200),   // ~24/araç → ~3 araç olmalı
    expect: { minVehicles: 2, noOverflow: true },
  });
})();

// ── 5) ÇALIŞTIR + RAPORLA ──────────────────────────────────────────────────
let pass = 0, fail = 0;
const ok = (b) => b ? '✓' : '✗';

console.log('═══════════════════════════════════════════════════════════════');
console.log(' CRONOI LS — Optimizasyon Yerleşim Testleri');
console.log('═══════════════════════════════════════════════════════════════\n');

for (const c of CASES) {
  _pid = 0;
  const pallets = c.pallets();
  APP.state.pallets = pallets;

  let fleet;
  if (c.repack) {
    // Aşırı-atanmış senaryo taklidi: tüm paletleri TEK araca koy → ensureFloorFit
    const scen = { vehicles: [{ code: c.vtCode, type: c.vt.type, name: c.vt.name,
                                length: c.vt.length, width: c.vt.width, height: c.vt.height,
                                maxWeight: c.vt.maxWeight, assignedPallets: pallets.map(p => p.id) }] };
    _ensureScenarioFloorFit(scen);
    fleet = scen.vehicles;
  } else {
    fleet = _buildFleetOfType(pallets, c.vtCode, c.vt);
  }

  const checks = [];
  const e = c.expect;
  if (e.vehicles != null)    checks.push(['araç sayısı=' + e.vehicles, fleet.length === e.vehicles, `${fleet.length}`]);
  if (e.minVehicles != null) checks.push(['araç ≥' + e.minVehicles, fleet.length >= e.minVehicles, `${fleet.length}`]);
  if (e.noOverflow)          checks.push(['taşma yok', fleet.every(v => !vehicleOverflow(v, c.vt)), fleet.some(v => vehicleOverflow(v, c.vt)) ? 'TAŞMA!' : 'temiz']);
  if (e.sideBySide != null)  checks.push(['yan yana ≥' + e.sideBySide, fleet.every(v => sideBySideRows(v, c.vt) >= e.sideBySide), `min ${Math.min(...fleet.map(v => sideBySideRows(v, c.vt)))} sıra`]);
  if (e.minFloorPct != null) checks.push(['zemin ≥%' + e.minFloorPct, fleet.every(v => floorPct(v, c.vt) >= e.minFloorPct), `%${Math.min(...fleet.map(v => floorPct(v, c.vt))).toFixed(0)}`]);
  if (e.minLdmPct != null)   checks.push(['LDM ≥%' + e.minLdmPct, fleet.every(v => (v.ldmFillPct || 0) >= e.minLdmPct), `%${Math.min(...fleet.map(v => v.ldmFillPct || 0)).toFixed(0)}`]);

  const allOk = checks.every(([, b]) => b);
  if (allOk) pass++; else fail++;

  console.log(`${allOk ? '✅' : '❌'} ${c.name}`);
  console.log(`   ${fleet.length} araç · ${pallets.length} palet`);
  for (const [label, b, detail] of checks) console.log(`      ${ok(b)} ${label}  (${detail})`);
  console.log('');
}

console.log('───────────────────────────────────────────────────────────────');
console.log(` SONUÇ: ${pass} geçti, ${fail} kaldı  ${fail === 0 ? '🎯 HEPSİ TEMİZ' : '⚠️ BAŞARISIZ VAR'}`);
console.log('───────────────────────────────────────────────────────────────');
process.exit(fail === 0 ? 0 : 1);
