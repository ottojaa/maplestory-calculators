"""Exact bonus-stat (flame) outcome distributions for a STR warrior.
Model (KMS official probability page, gameAddOption, which GMS v.271 says the meso reset matches):
 - Flame-advantaged (FA) items always get 4 distinct lines, chosen uniformly from a 19-option pool.
 - Each line's tier is independent: Black/meso reset base tiers 2-5 = 29/45/25/1 %, +2 on FA -> T4-7.
 - Non-FA: 1-4 lines with 40/40/16/4 %, tiers T2-5 with the same 29/45/25/1 %.
"""
import itertools, math, sys
from collections import defaultdict

TIERS = {
    'black':    {2: .29, 3: .45, 4: .25, 5: .01},   # = Eternal = meso reset
    'powerful': {1: .20, 2: .30, 3: .36, 4: .14},   # = Burning (keep/choose)
    'abyssal':  {3: .63, 4: .34, 5: .03},
    'drop':     {1: .25, 2: .30, 3: .30, 4: .14, 5: .01},
}
NONFA_LINES = {1: .40, 2: .40, 3: .16, 4: .04}

ARMOR_POOL = ['STR','DEX','INT','LUK','STR+DEX','STR+INT','STR+LUK','DEX+INT','DEX+LUK','INT+LUK',
              'HP','MP','REQ','DEF','ATT','MATT','SPEED','JUMP','AS']
WEAPON_POOL = ['STR','DEX','INT','LUK','STR+DEX','STR+INT','STR+LUK','DEX+INT','DEX+LUK','INT+LUK',
               'HP','MP','REQ','DEF','ATT','MATT','BOSS','DMG','AS']
assert len(ARMOR_POOL) == 19 and len(WEAPON_POOL) == 19

def single_per_tier(lvl):  # wiki Stat_Tables: STR/DEX rows
    if lvl >= 230: return 12
    if lvl >= 200: return 11
    return lvl // 20 + 1
def double_per_tier(lvl):
    if lvl >= 250: return 7
    if lvl >= 200: return 6
    return lvl // 40 + 1
def watt_pct(lvl, tier, fa=True):
    return (lvl // 40 + 1) * tier * 1.1 ** (tier - (3 if fa else 1))

def line_stats(name, tier, lvl, is_weapon=False, base_att=0, fa=True):
    """Return dict of raw stats contributed by one line."""
    s, d = single_per_tier(lvl), double_per_tier(lvl)
    if name == 'STR': return {'str': s*tier}
    if name == 'DEX': return {'dex': s*tier}
    if name == 'STR+DEX': return {'str': d*tier, 'dex': d*tier}
    if name in ('STR+INT','STR+LUK'): return {'str': d*tier}
    if name in ('DEX+INT','DEX+LUK'): return {'dex': d*tier}
    if name == 'AS': return {'as': tier}
    if name == 'ATT':
        if is_weapon: return {'att': base_att * watt_pct(lvl, tier, fa) / 100}
        return {'att': tier}
    if name == 'BOSS': return {'boss': 2*tier}
    if name == 'DMG': return {'dmg': tier}
    return {}

RELEVANT = {'STR','DEX','STR+DEX','STR+INT','STR+LUK','DEX+INT','DEX+LUK','AS','ATT','BOSS','DMG'}

def outcome_dist(lvl, flame='black', fa=True, is_weapon=False, base_att=0):
    """Yield (prob, stats_dict) over all outcomes (merging irrelevant lines)."""
    pool = WEAPON_POOL if is_weapon else ARMOR_POOL
    base = TIERS[flame]
    tiers = {t + (2 if fa else 0): p for t, p in base.items()}
    out = defaultdict(float)
    nlines_dist = {4: 1.0} if fa else NONFA_LINES
    for n, pn in nlines_dist.items():
        subsets = list(itertools.combinations(range(len(pool)), n))
        psub = pn / len(subsets)
        # group subsets by relevant-line tuple
        groups = defaultdict(int)
        for sub in subsets:
            rel = tuple(pool[i] for i in sub if pool[i] in RELEVANT)
            groups[rel] += 1
        for rel, cnt in groups.items():
            for tt in itertools.product(tiers.items(), repeat=len(rel)):
                p = psub * cnt
                stats = defaultdict(float)
                key = []
                for name, (t, pt) in zip(rel, tt):
                    p *= pt
                    for k, v in line_stats(name, t, lvl, is_weapon, base_att, fa).items():
                        stats[k] += v
                    key.append((name, t))
                out[tuple(sorted(stats.items()))] += p
    return out

def score(stats, att_w=4, as_w=10, dex_w=0.125, boss_w=0, dmg_w=0):
    s = dict(stats)
    return (s.get('str',0) + dex_w*s.get('dex',0) + att_w*s.get('att',0) + as_w*s.get('as',0)
            + boss_w*s.get('boss',0) + dmg_w*s.get('dmg',0))

def score_dist(dist, **kw):
    sd = defaultdict(float)
    for st, p in dist.items():
        sd[round(score(st, **kw), 3)] += p
    xs = sorted(sd)
    return xs, [sd[x] for x in xs]

def p_ge(xs, ps, t):
    return sum(p for x, p in zip(xs, ps) if x >= t - 1e-9)

def quantile(xs, ps, q):
    c = 0
    for x, p in zip(xs, ps):
        c += p
        if c >= q: return x
    return xs[-1]

def mean(xs, ps): return sum(x*p for x, p in zip(xs, ps))

def exp_best_after(xs, ps, n, start):
    """E[max(start, best of n rolls)] exactly via CDF."""
    cdf = []; c = 0
    for p in ps: c += p; cdf.append(c)
    e = 0; prev = 0
    for x, F in zip(xs, cdf):
        Fn = F ** n
        e += max(x, start) * (Fn - prev)
        prev = Fn
    return e


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Flame (bonus stat) odds for a STR warrior: chance per reset, expected resets and meso cost "
                    "(3M per meso reset) to reach a flame score, and the expected best score after N resets. "
                    "Score = STR + DEX/8 + 4*ATT + 10*AllStat%. On weapons use --want-att/--want-boss tiers instead.")
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--flame", default="black", choices=list(TIERS), help="black = meso reset/Eternal (default); powerful = Burning")
    ap.add_argument("--not-fa", action="store_true", help="item is NOT flame-advantaged (e.g. Chaos Horntail Necklace)")
    ap.add_argument("--target", type=float, help="target flame score (armor/accessory)")
    ap.add_argument("--start", type=float, default=0, help="current score, for --resets")
    ap.add_argument("--resets", type=int, help="expected best score after this many resets (keeping the better)")
    ap.add_argument("--weapon", action="store_true")
    ap.add_argument("--base-att", type=float, default=0, help="weapon base ATT (e.g. 171 Fafnir Soaring Sword)")
    ap.add_argument("--want-att-tier", type=int, default=0, help="weapon: minimum ATT line tier (e.g. 6)")
    ap.add_argument("--want-boss-tier", type=int, default=0, help="weapon: minimum boss line tier (e.g. 5)")
    a = ap.parse_args()
    fa = not a.not_fa
    reset_cost = 3_000_000
    if a.weapon:
        # Probability that one reset gives ATT >= tier and boss >= tier (lines independent of other lines).
        tiers = {t + (2 if fa else 0): p for t, p in TIERS[a.flame].items()}
        def p_tier_ge(t): return sum(p for tt, p in tiers.items() if tt >= t) if t else 1.0
        n = len(WEAPON_POOL)
        need = [x for x in (a.want_att_tier, a.want_boss_tier) if x]
        if len(need) == 2:
            p_lines = math.comb(n - 2, 2) / math.comb(n, 4) if fa else None
        elif len(need) == 1:
            p_lines = 4 / n if fa else None
        else:
            p_lines = 1.0
        if p_lines is None:
            raise SystemExit("weapon targets on non-flame-advantaged weapons aren't supported")
        p = p_lines * p_tier_ge(a.want_att_tier) * p_tier_ge(a.want_boss_tier)
        print(f"Weapon Lv.{a.level}, {a.flame} flame: ATT>=T{a.want_att_tier or '-'} boss>=T{a.want_boss_tier or '-'}")
        if a.want_att_tier and a.base_att:
            print(f"  ATT line at T{a.want_att_tier}: +{a.base_att * watt_pct(a.level, a.want_att_tier, fa) / 100:.0f} ATT")
        print(f"  chance per reset {p*100:.3f}% -> expected {1/p:.0f} resets, {reset_cost/p/1e9:.3f}B mesos")
        return
    dist = outcome_dist(a.level, a.flame, fa)
    xs, ps = score_dist(dist)
    print(f"Lv.{a.level} {'flame-advantaged' if fa else 'non-advantaged'} item, {a.flame} flame: mean score {mean(xs, ps):.1f}, "
          f"median {quantile(xs, ps, .5):.0f}, 90th pct {quantile(xs, ps, .9):.0f}, 99th pct {quantile(xs, ps, .99):.0f}")
    if a.target:
        p = p_ge(xs, ps, a.target)
        if p > 0:
            print(f"  score >= {a.target:g}: {p*100:.3f}% per reset -> expected {1/p:.0f} resets, {reset_cost/p/1e9:.3f}B mesos")
        else:
            print(f"  score >= {a.target:g}: impossible with this flame")
    if a.resets:
        print(f"  expected best after {a.resets} resets from {a.start:g}: {exp_best_after(xs, ps, a.resets, a.start):.1f} "
              f"({a.resets * reset_cost / 1e9:.3f}B)")


if __name__ == "__main__":
    main()
