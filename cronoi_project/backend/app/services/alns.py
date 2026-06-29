"""
Cronoi LS — Genel ALNS (Adaptive Large Neighborhood Search) Çatısı
==================================================================
Optimizer V10 (newoptimizersuggestion.md §4.3) — alan-bağımsız meta-sezgisel arama motoru.
"Tek yerleşimi değil TÜM planı optimize et; kararlar yakınsamaya kadar geri-alınabilir."

Kullanım: alana özel Solution + destroy/repair operatörlerini ver, run_alns çalıştır.
Bu çatı şunları sağlar: roulette ile ADAPTİF operatör seçimi, kabul kriteri (geliştirme +
iterasyon-tabanlı Simulated Annealing), en iyi takibi, graceful fallback, ve DETERMİNİZM
(tek tohumlu RNG + iterasyon-tabanlı durdurma → aynı girdi birebir aynı çıktı).

Yeniden kullanım: filo katmanı (palet→araç, fleet_packer) ve ileride 3D paketleme (ürün→palet)
ve Mod C (dökme→araç) aynı çatıyı kullanır.

Tasarım notu — DETERMİNİZM: birincil durdurma İTERASYON tabanlıdır (max_iter / no_improve_limit);
süre bütçesi (deadline) yalnızca GÜVENLİK tavanıdır. Wall-clock'a bağlı dallanma yoktur → iki koşu
aynı seed + aynı girdi ile birebir aynı sonucu verir.
"""

from dataclasses import dataclass, field
from typing import Protocol, Callable, List, Tuple, Optional, Any
import math
import time
import random


class Solution(Protocol):
    """Alana özel çözümün uyması gereken arayüz."""
    def copy(self) -> "Solution": ...
    def cost(self) -> float: ...          # düşük = iyi (araç sayısı baskın + doluluk ince-ayar)


# Operatör imzaları: yerinde (in-place) çalışır, çözümü döndürür.
DestroyOp = Callable[[Any, random.Random, float], Any]   # (solution, rng, degree) -> solution
RepairOp = Callable[[Any, random.Random], Any]            # (solution, rng) -> solution


@dataclass
class _Op:
    name: str
    fn: Callable
    weight: float = 1.0
    score: float = 0.0
    uses: int = 0


@dataclass
class ALNSStats:
    iterations: int = 0
    accepted: int = 0
    improvements: int = 0
    best_cost: float = math.inf
    elapsed_ms: float = 0.0
    op_usage: dict = field(default_factory=dict)
    op_success: dict = field(default_factory=dict)
    reached_target: bool = False


# ── Adaptif ağırlık ödülleri (Ropke & Pisinger 2006) ──
_SIGMA_BEST = 3.0      # yeni global en iyi
_SIGMA_BETTER = 2.0    # mevcuttan iyi
_SIGMA_ACCEPT = 1.0    # kötü ama kabul edildi (çeşitlilik)
_DECAY = 0.8           # segment sonu ağırlık karışım faktörü
_SEGMENT = 50          # kaç iterasyonda bir ağırlık güncelle


def _roulette(ops: List[_Op], rng: random.Random) -> _Op:
    total = sum(o.weight for o in ops)
    if total <= 0:
        return ops[rng.randrange(len(ops))]
    r = rng.random() * total
    acc = 0.0
    for o in ops:
        acc += o.weight
        if r <= acc:
            return o
    return ops[-1]


def run_alns(
    initial: Any,
    destroy_ops: List[Tuple[str, DestroyOp]],
    repair_ops: List[Tuple[str, RepairOp]],
    rng: random.Random,
    *,
    max_iter: int = 2000,
    no_improve_limit: int = 400,
    convergence_patience: Optional[int] = None,
    deadline: Optional[float] = None,
    target_cost: Optional[float] = None,
    degree_min: float = 0.10,
    degree_max: float = 0.35,
    sa_start_temp: float = 0.0,
    sa_cooling: float = 0.997,
) -> Tuple[Any, ALNSStats]:
    """ALNS ana döngüsü. initial = geçerli başlangıç çözümü (cost()/copy() destekler).
    Dönüş: (best_solution, stats). En kötü ihtimalde initial'i döndürür (graceful)."""
    dops = [_Op(n, f) for n, f in destroy_ops]
    rops = [_Op(n, f) for n, f in repair_ops]

    current = initial
    cur_cost = current.cost()
    best = current.copy()
    best_cost = cur_cost

    stats = ALNSStats(best_cost=best_cost)
    temp = sa_start_temp if sa_start_temp > 0 else 0.0
    no_improve = 0
    global_no_improve = 0   # restart'tan ETKİLENMEZ → gerçek yakınsama ölçer

    for it in range(max_iter):
        if deadline is not None and time.time() > deadline:
            break
        if target_cost is not None and best_cost <= target_cost + 1e-9:
            stats.reached_target = True
            break
        # Yakınsama-durması: global en iyi uzun süredir iyileşmiyorsa boşuna iterasyon harcama.
        # (Determinizm korunur — iterasyon-tabanlı, wall-clock'tan bağımsız.)
        if convergence_patience is not None and global_no_improve >= convergence_patience:
            break

        d = _roulette(dops, rng)
        r = _roulette(rops, rng)
        degree = degree_min + (degree_max - degree_min) * rng.random()

        candidate = current.copy()
        candidate = d.fn(candidate, rng, degree)
        candidate = r.fn(candidate, rng)
        cand_cost = candidate.cost()

        d.uses += 1
        r.uses += 1
        reward = 0.0

        if cand_cost < best_cost - 1e-12:           # yeni global en iyi
            best = candidate.copy()
            best_cost = cand_cost
            reward = _SIGMA_BEST
            stats.improvements += 1
            no_improve = 0
            global_no_improve = 0
        else:
            no_improve += 1
            global_no_improve += 1

        accept = False
        if cand_cost < cur_cost - 1e-12:
            accept = True
            reward = max(reward, _SIGMA_BETTER)
        elif temp > 1e-9:
            # Simulated Annealing (iterasyon-tabanlı sıcaklık → deterministik)
            prob = math.exp(-(cand_cost - cur_cost) / temp)
            if rng.random() < prob:
                accept = True
                reward = max(reward, _SIGMA_ACCEPT)

        if accept:
            current = candidate
            cur_cost = cand_cost
            stats.accepted += 1

        d.score += reward
        r.score += reward

        # Segment sonunda adaptif ağırlık güncelle
        if (it + 1) % _SEGMENT == 0:
            for o in dops + rops:
                if o.uses > 0:
                    o.weight = _DECAY * o.weight + (1 - _DECAY) * (o.score / o.uses)
                o.score = 0.0
                o.uses = 0

        if temp > 1e-9:
            temp *= sa_cooling

        # Stagnasyon: en iyiden yeniden başla (yoğunlaştırma)
        if no_improve >= no_improve_limit:
            current = best.copy()
            cur_cost = best_cost
            no_improve = 0

        stats.iterations = it + 1

    stats.best_cost = best_cost
    stats.op_usage = {o.name: o.uses for o in dops + rops}
    return best, stats
