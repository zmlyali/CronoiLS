"""JS optimizer davranış simülasyonu — headboard analiz."""
# JS optimizer'ın Python eşdeğeri ile adım adım izleme

def simulate_js_optimizer():
    """JS BinPackingOptimizer'ın headboard için ne yapacağını simüle et."""
    # Palet: width=100, length=200, maxH=240 (P7 Özel Boy)
    # Overflow: 5% → maxW=105, maxL=210
    palW, palL, maxH = 100, 200, 240
    overflow = 0.05
    maxW = palW * (1 + overflow)  # 105
    maxL = palL * (1 + overflow)  # 210

    # Headboard: 185×105×15
    L, W, H = 185, 105, 15

    # JS _getOrientations(item, maxH, maxL, maxW)
    # Filtre: dx <= maxW && dy <= maxL && dz <= maxH
    print(f"Palet: {palW}×{palL}, maxH={maxH}")
    print(f"Overflow: maxW={maxW}, maxL={maxL}")
    print(f"Headboard: L={L} W={W} H={H}")
    print()

    # 6 permütasyon
    perms = [
        (L, W, H), (L, H, W), (W, L, H), (W, H, L), (H, L, W), (H, W, L)
    ]
    print("6 permütasyon ve filtre (dx<=maxW, dy<=maxL, dz<=maxH):")
    valid = []
    seen = set()
    for dx, dy, dz in perms:
        key = f"{dx},{dy},{dz}"
        if key in seen:
            continue
        seen.add(key)
        fits_w = dx <= maxW
        fits_l = dy <= maxL
        fits_h = dz <= maxH
        ok = fits_w and fits_l and fits_h
        status = "✅ VALID" if ok else "❌ REJECT"
        reason = []
        if not fits_w: reason.append(f"dx={dx}>{maxW}")
        if not fits_l: reason.append(f"dy={dy}>{maxL}")
        if not fits_h: reason.append(f"dz={dz}>{maxH}")
        print(f"  ({dx:3d}×{dy:3d}×{dz:3d}) → {status} {'  '.join(reason)}")
        if ok:
            valid.append((dx, dy, dz))

    # dz ascending sort
    valid.sort(key=lambda o: (o[2], -max(o[0], o[1])))
    print(f"\nValid orientasyonlar (dz artan):")
    for i, (dx, dy, dz) in enumerate(valid):
        cap_x = int(maxW // dx)
        cap_y = int(maxL // dy)
        cap = cap_x * cap_y
        print(f"  [{i}] dx={dx} dy={dy} dz={dz} | zeminKapasite={cap_x}×{cap_y}={cap}")

    # Yerleştirme simülasyonu
    print(f"\n{'='*60}")
    print("YERLEŞTİRME SİMÜLASYONU (17 headboard)")
    print(f"{'='*60}")

    placed_rects = []

    def baseZ(x, y, dx, dy):
        maxTop = 0
        x2, y2 = x + dx, y + dy
        for r in placed_rects:
            if r['x'] < x2 and r['x']+r['dx'] > x and r['y'] < y2 and r['y']+r['dy'] > y:
                top = r['z'] + r['dz']
                if top > maxTop:
                    maxTop = top
        return maxTop

    def overlaps3D(x, y, z, dx, dy, dz):
        x2, y2, z2 = x+dx, y+dy, z+dz
        for r in placed_rects:
            if (r['x'] < x2 and r['x']+r['dx'] > x and
                r['y'] < y2 and r['y']+r['dy'] > y and
                r['z'] < z2 and r['z']+r['dz'] > z):
                return True
        return False

    def candidates(dx, dy):
        xs = sorted({0} | {r['x']+r['dx'] for r in placed_rects} | {r['x'] for r in placed_rects})
        ys = sorted({0} | {r['y']+r['dy'] for r in placed_rects} | {r['y'] for r in placed_rects})
        cands = []
        for y in ys:
            if y + dy > maxL + 0.01: continue
            for x in xs:
                if x + dx > maxW + 0.01: continue
                cands.append((x, y))
        return cands

    def score(x, y, z, dx, dy, dz):
        s = 0
        s += max(0, (1 - z/maxH)) * 300  # low-z
        isGround = z < 0.5
        if isGround: s += 80  # ground
        # corner
        if not placed_rects:
            if x < 1 and y < 1: s += 80
            elif x < 1 or y < 1: s += 30
        else:
            if x < 1 or abs(x+dx-maxW) < 1: s += 15
            if y < 1 or abs(y+dy-maxL) < 1: s += 15
        # adjacency (simplified)
        touchArea = 0
        for r in placed_rects:
            if abs(x-(r['x']+r['dx'])) < 0.5 or abs((x+dx)-r['x']) < 0.5:
                zo = max(0, min(z+dz, r['z']+r['dz']) - max(z, r['z']))
                yo = max(0, min(y+dy, r['y']+r['dy']) - max(y, r['y']))
                touchArea += zo * yo
            if abs(y-(r['y']+r['dy'])) < 0.5 or abs((y+dy)-r['y']) < 0.5:
                zo = max(0, min(z+dz, r['z']+r['dz']) - max(z, r['z']))
                xo = max(0, min(x+dx, r['x']+r['dx']) - max(x, r['x']))
                touchArea += zo * xo
            if abs(z-(r['z']+r['dz'])) < 0.5:
                xo = max(0, min(x+dx, r['x']+r['dx']) - max(x, r['x']))
                yo = max(0, min(y+dy, r['y']+r['dy']) - max(y, r['y']))
                touchArea += xo * yo
        surf = 2*(dx*dy + dx*dz + dy*dz)
        if surf > 0: s += min(touchArea/surf, 1) * 150
        # align
        if placed_rects:
            if any(abs(r['x']-x) < 0.5 for r in placed_rects): s += 15
            if any(abs(r['y']-y) < 0.5 for r in placed_rects): s += 15
        # h-eff
        if maxH > 0: s -= (dz/maxH) * 30
        # floor capacity
        capX = max(1, int(maxW // dx))
        capY = max(1, int(maxL // dy))
        cap = capX * capY
        if cap > 1: s += min(cap, 20) * 8
        return s

    for item_idx in range(17):
        best = None
        bestScore = float('-inf')

        for dx, dy, dz in valid:
            cands = candidates(dx, dy)
            for (cx, cy) in cands:
                if cx + dx > maxW + 0.01 or cy + dy > maxL + 0.01:
                    continue
                bz = baseZ(cx, cy, dx, dy)
                if bz + dz > maxH + 0.001:
                    continue
                if overlaps3D(cx, cy, bz, dx, dy, dz):
                    continue
                sc = score(cx, cy, bz, dx, dy, dz)
                if sc > bestScore:
                    bestScore = sc
                    best = {'x': cx, 'y': cy, 'z': bz, 'dx': dx, 'dy': dy, 'dz': dz}

        if best:
            placed_rects.append(best)
            top = best['z'] + best['dz']
            orient = "FLAT" if best['dz'] < 20 else ("BOOKSHELF" if best['dz'] > 100 else "MID")
            print(f"  [{item_idx:2d}] pos=({best['x']:5.1f},{best['y']:5.1f},{best['z']:5.1f}) "
                  f"size=({best['dx']:3d}×{best['dy']:3d}×{best['dz']:3d}) top={top:5.1f} "
                  f"score={bestScore:.1f} | {orient}")
        else:
            print(f"  [{item_idx:2d}] ❌ SIĞMADI!")

    max_z = max(r['z']+r['dz'] for r in placed_rects)
    print(f"\n📊 Toplam {len(placed_rects)} rect yerleşti, max yükseklik: {max_z}")
    if max_z > maxH:
        print(f"⛔ YÜKSEKLİK İHLALİ: {max_z} > {maxH}")
    else:
        print(f"✅ Yükseklik OK: {max_z} ≤ {maxH}")


if __name__ == "__main__":
    simulate_js_optimizer()
