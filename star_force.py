#!/usr/bin/env python3
"""Exact expected star force cost (GMS, post-v.264 30-star system, v.271 star-catch bonus baked in).

Replicates MathBro's starforceCalculator (serverDiffs.js kmsCost/kmsRates + main.js determineOutcome)
but solves the Markov chain exactly instead of simulating. Also Monte Carlo for percentiles.
"""
import numpy as np
import sys

# [success, maintain, decrease, boom] from MathBro kmsRates == wiki == v.264 patch notes
RATES = {
    0: (0.95, 0.05, 0), 1: (0.9, 0.1, 0), 2: (0.85, 0.15, 0), 3: (0.85, 0.15, 0), 4: (0.80, 0.2, 0),
    5: (0.75, 0.25, 0), 6: (0.7, 0.3, 0), 7: (0.65, 0.35, 0), 8: (0.6, 0.4, 0), 9: (0.55, 0.45, 0),
    10: (0.5, 0.5, 0), 11: (0.45, 0.55, 0), 12: (0.4, 0.6, 0), 13: (0.35, 0.65, 0), 14: (0.3, 0.7, 0),
    15: (0.3, 0.679, 0.021), 16: (0.3, 0.679, 0.021), 17: (0.15, 0.782, 0.068), 18: (0.15, 0.782, 0.068),
    19: (0.15, 0.765, 0.085), 20: (0.3, 0.595, 0.105), 21: (0.15, 0.7225, 0.1275), 22: (0.15, 0.68, 0.17),
    23: (0.10, 0.72, 0.18), 24: (0.10, 0.72, 0.18), 25: (0.10, 0.72, 0.18), 26: (0.07, 0.744, 0.186),
    27: (0.05, 0.76, 0.19), 28: (0.03, 0.776, 0.194), 29: (0.01, 0.792, 0.198),
}
# wiki GMS divisors (cost = 1000 + L^3 * (S+1)^2.7 / div), 0-9 linear /25
DIV = {10: 400, 11: 220, 12: 150, 13: 110, 14: 75, 15: 200, 16: 200, 17: 150, 18: 70, 19: 45,
       20: 200, 21: 125}


def base_cost(s, level):
    L = (level // 10) * 10  # MathBro floors level to the decade
    if s < 10:
        raw = L ** 3 * (s + 1) / 25
    else:
        raw = L ** 3 * (s + 1) ** 2.7 / DIV.get(s, 200)
    return 100 * round(raw / 100 + 10)  # == MathBro makeMesoFn rounding


def boom_star(s):
    if s < 20:
        return 12
    if s == 20:
        return 15
    if s < 23:
        return 17
    if s < 26:
        return 19
    return 20


def probs(s, sunday, catch=True, boom_cutoff=20, safeguard=False):
    p, m, b = RATES[s]
    if sunday and s <= boom_cutoff:   # Nexon: "below 21 Stars" -> attempts from 15..20
        m, b = m + 0.3 * b, 0.7 * b
    if safeguard and 15 <= s <= 17:
        m, b = m + b, 0.0
    if catch:  # v.271: star-catch x1.05 success, rest scaled proportionally (MathBro logic)
        p2 = p * 1.05
        left = 1 - p2
        if m + b > 0:
            m, b = m * left / (m + b), left - m * left / (m + b)
        p = p2
    return p, m, b


def cost(s, level, sunday, safeguard=False):
    c = base_cost(s, level)
    mult = 1.0 - (0.3 if sunday else 0.0)
    if safeguard and 15 <= s <= 17:
        mult += 2.0  # safeguard fee = 200% of base, not discounted
    return c * mult


def expected(start, target, level, sunday=False, safeguard=False, boom_cutoff=20):
    """Solve E[s] = c + p E[s+1] + m E[s] + b E[boom(s)], E[target]=0. Returns (mesos, booms)."""
    n = target
    A = np.zeros((n, n)); rc = np.zeros(n); rb = np.zeros(n)
    for s in range(n):
        p, m, b = probs(s, sunday, boom_cutoff=boom_cutoff, safeguard=safeguard)
        A[s, s] += 1 - m
        if s + 1 < n:
            A[s, s + 1] -= p
        if b > 0:
            A[s, boom_star(s)] -= b
        rc[s] = cost(s, level, sunday, safeguard)
        rb[s] = b
    E = np.linalg.solve(A, rc)
    B = np.linalg.solve(A, rb)
    return E[start], B[start]


def simulate(start, target, level, sunday=False, safeguard=False, trials=40000, seed=1):
    rng = np.random.default_rng(seed)
    tab = {s: probs(s, sunday, safeguard=safeguard) for s in range(30)}
    out = np.empty(trials); booms = np.empty(trials)
    for t in range(trials):
        s, tot, bo = start, 0.0, 0
        while s < target:
            tot += cost(s, level, sunday, safeguard)
            p, m, b = tab[s]
            r = rng.random()
            if r < p:
                s += 1
            elif r < p + m:
                pass
            else:
                s = boom_star(s); bo += 1
        out[t] = tot; booms[t] = bo
    return out, booms


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Expected star force cost (GMS v.271 rates, MathBro cost formula), exact mean + simulated percentiles.")
    ap.add_argument("--level", type=int, required=True, help="item level, e.g. 140, 150, 160, 200")
    ap.add_argument("--from", dest="start", type=int, required=True, help="current stars")
    ap.add_argument("--to", dest="target", type=int, required=True, help="target stars")
    ap.add_argument("--sunday", action="store_true", help="Sunny Sunday: 30%% off, 30%% less destruction below 21 stars")
    ap.add_argument("--safeguard", action="store_true", help="safeguard 15-17 stars (triples those attempts' cost)")
    ap.add_argument("--trials", type=int, default=20000, help="Monte Carlo trials for percentiles (0 = skip)")
    ap.add_argument("--fodder", action="store_true",
                    help="fodder view: each boom uses up one spare copy (or a Star Core); prints how many copies "
                         "to stockpile and what an Equipment Transfer of the finished item gives (one star less)")
    ap.add_argument("--copies", type=int, default=None,
                    help="with --fodder: chance to finish with this many spare copies, and the mesos in those runs")
    ap.add_argument("--table", action="store_true",
                    help="compare targets from --from+1 up to --to (mean, 75%% budget, booms)")
    a = ap.parse_args()
    tag = f"{' (Sunny Sunday)' if a.sunday else ''}{' (safeguard)' if a.safeguard else ''}"

    if a.table:
        print(f"Lv.{a.level} from {a.start} stars{tag}")
        print(f"  {'target':>6} {'mean':>8} {'75%':>8} {'booms':>6}")
        for t in range(a.start + 1, a.target + 1):
            m, bo = expected(a.start, t, a.level, a.sunday, a.safeguard)
            q75 = ""
            if a.trials:
                out, _ = simulate(a.start, t, a.level, a.sunday, a.safeguard, trials=max(2000, a.trials // 5))
                q75 = f"{np.percentile(out, 75)/1e9:7.2f}B"
            print(f"  {t:>5}★ {m/1e9:7.2f}B {q75:>8} {bo:6.2f}")
        return

    mean, booms = expected(a.start, a.target, a.level, a.sunday, a.safeguard)
    print(f"Lv.{a.level} {a.start}->{a.target} stars{tag}")
    print(f"  mean cost {mean/1e9:.3f}B, expected destructions {booms:.2f} (each needs an identical item or Star Core to restore)")
    if a.trials:
        out, b = simulate(a.start, a.target, a.level, a.sunday, a.safeguard, trials=a.trials)
        q = np.percentile(out, [50, 75, 95]) / 1e9
        print(f"  median {q[0]:.3f}B, 75% within {q[1]:.3f}B, 95% within {q[2]:.3f}B")
        if a.fodder:
            print("  Copies used up by booms (identical items or Star Cores):")
            cum = 0.0
            for k in range(0, 8):
                share = float(np.mean(b == k)); cum += share
                print(f"    {k} booms: {share*100:5.1f}%   done with {k} spare copies or fewer: {cum*100:5.1f}%")
            for p in (50, 75, 90):
                print(f"  Stockpile for {p}% odds: {int(np.ceil(np.percentile(b, p)))} spare copies")
            if a.copies is not None:
                ok = b <= a.copies
                if ok.any():
                    print(f"  With {a.copies} spare copies: {ok.mean()*100:.1f}% chance to finish; "
                          f"mean mesos in those runs {out[ok].mean()/1e9:.2f}B")
                else:
                    print(f"  With {a.copies} spare copies: ~0% chance to finish")
            print(f"  Equipment Transfer of the finished item: the target arrives at {a.target - 1}★ "
                  f"(potential capped at Epic). Same type, up to 10 levels higher (20 if the source is Lv. 119 or below).")


if __name__ == "__main__":
    main()
