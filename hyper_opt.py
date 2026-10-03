"""Exact hyper-stat optimizer (knapsack over independent damage factors) on top of the skill's damage model.
Read-only use of the maplestory-gms skill's scripts/damage_model.py (found by find_damage_model.py)."""
import importlib.util, math, os, sys, itertools
import sys as _sys; _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_damage_model import load_damage_model
dm = load_damage_model()

COST = [0, 1, 3, 7, 15, 25, 40, 60, 85, 115, 150, 200, 265, 345, 440, 550]
def boss(L): return 3*L + (L-5 if L >= 5 else 0)
def crit(L): return L + (L-5 if L >= 5 else 0)
VAL = {
 "STR": lambda L: 30*L, "DEX": lambda L: 30*L, "ATT": lambda L: 3*L, "DMG": lambda L: 3*L,
 "BOSS": boss, "IED": lambda L: 3*L, "CR": crit, "CD": lambda L: L,
}

# The preset already inside the damage model's baseline (profile doc, 2026-10-02: preset 3, 600 of 608 points).
# stripped_profile() removes it so presets can be compared from zero. Override with --current.
CUR = {"STR":5,"ATT":6,"DMG":7,"BOSS":10,"IED":9,"CR":10,"CD":7}

def stripped_profile(boss_def=300, extra_crit=0, extra_cd=0):
    p = dict(dm.DEFAULT_PROFILE)
    p["boss_def"] = boss_def
    p["main"] -= 30*CUR["STR"]; p["unaffected_main"] -= 30*CUR["STR"]
    p["crit_rate"] -= crit(CUR["CR"]); p["crit_rate"] += extra_crit
    p["crit_dmg"] -= CUR["CD"]; p["crit_dmg"] += extra_cd
    rem = (1-p["ied"]/100)/(1-3*CUR["IED"]/100); p["ied"] = 100*(1-rem)
    p["damage"] -= 3*CUR["DMG"]; p["boss"] -= boss(CUR["BOSS"])
    p["att"] -= 3*CUR["ATT"]*(1+p["att_pct"]/100)
    return p

def change(levels):
    c = {}
    if levels.get("STR"): c["unaffected_main"] = VAL["STR"](levels["STR"])
    if levels.get("ATT"): c["att"] = VAL["ATT"](levels["ATT"])
    d = VAL["DMG"](levels.get("DMG",0)) + VAL["BOSS"](levels.get("BOSS",0))
    if d: c["damage"] = d
    if levels.get("IED"): c["ied"] = VAL["IED"](levels["IED"])
    if levels.get("CR"): c["crit_rate"] = VAL["CR"](levels["CR"])
    if levels.get("CD"): c["crit_dmg"] = VAL["CD"](levels["CD"])
    return c

def dmg(p, levels):
    return dm.damage(p, change(levels))

GROUPS = [["STR"], ["ATT"], ["DMG","BOSS"], ["IED"], ["CR","CD"]]

def optimize(p, budget):
    base = dm.damage(p)
    # per group: list of (cost, logfactor, levels)
    group_opts = []
    for g in GROUPS:
        opts = []
        for lv in itertools.product(range(16), repeat=len(g)):
            levels = dict(zip(g, lv)); cost = sum(COST[x] for x in lv)
            if cost > budget: continue
            opts.append((cost, math.log(dmg(p, levels)/base), levels))
        group_opts.append(opts)
    NEG = -1e9
    best = [0.0]*(budget+1); choice = [dict() for _ in range(budget+1)]
    for opts in group_opts:
        nb = [NEG]*(budget+1); nc = [None]*(budget+1)
        for b in range(budget+1):
            for cost, lf, lv in opts:
                if cost <= b and best[b-cost] + lf > nb[b]:
                    nb[b] = best[b-cost] + lf; nc[b] = {**choice[b-cost], **lv}
        best, choice = nb, nc
    lv = choice[budget]
    return lv, math.exp(best[budget]) - 1, sum(COST[x] for x in lv.values())

def marginal(p, lv):
    out = {}
    d0 = dmg(p, lv)
    for s in ["STR","ATT","DMG","BOSS","IED","CR","CD"]:
        L = lv.get(s, 0)
        if L >= 15: continue
        nl = dict(lv); nl[s] = L+1
        gain = dmg(p, nl)/d0 - 1
        out[s] = (gain*100, COST[L+1]-COST[L], gain*100/(COST[L+1]-COST[L]))
    return out

def fmt(lv): return " ".join(f"{k}{lv.get(k,0)}" for k in ["STR","ATT","DMG","BOSS","IED","CR","CD"])

def parse_levels(text):
    out = {}
    for part in filter(None, (p.strip() for p in text.replace(" ", ",").split(","))):
        k = part.rstrip("0123456789"); out[k.upper()] = int(part[len(k):])
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Best hyper stat allocation for a point budget, on the damage model's "
                                 "baseline (the damage model's baseline (profile.json or --stats)). Points by level: 586 at 225, "
                                 "+11 per level to 229 (608 at 227), 642 at 230, 702 at 235, 894 at 250, 1035 at 260.")
    ap.add_argument("--points", type=int, nargs="+", default=[608, 642, 702, 894, 1035])
    ap.add_argument("--boss-def", type=int, nargs="+", default=[300, 380], help="target defense %% (300 Lotus/Damien)")
    ap.add_argument("--current", help='preset already in the baseline stats, e.g. "STR5 ATT6 DMG7 BOSS10 IED9 CR10 CD7"')
    ap.add_argument("--extra-crit", type=int, default=0, help="crit rate the baseline will gain elsewhere (e.g. 10 DSE + 15 Phantom)")
    ap.add_argument("--extra-cd", type=int, default=0, help="crit damage the baseline will gain elsewhere (e.g. 8 DSE)")
    a = ap.parse_args()
    if a.current:
        CUR = parse_levels(a.current)
    cur_cost = sum(COST[v] for v in CUR.values())
    for bd in a.boss_def:
        p = stripped_profile(boss_def=bd, extra_crit=a.extra_crit, extra_cd=a.extra_cd)
        print(f"\n== boss def {bd}%  (without hypers: crit {p['crit_rate']:g}, crit dmg {p['crit_dmg']:g}, "
              f"IED {p['ied']:.2f}, damage {p['damage']:g}, boss {p['boss']:g})")
        cur_gain = dmg(p, CUR)/dm.damage(p)-1
        print(f"  current preset ({cur_cost} pts) {fmt(CUR)}: +{cur_gain*100:.1f}% over no hypers")
        for B in a.points:
            lv, g, used = optimize(p, B)
            m = marginal(p, lv)
            best_next = max(m.items(), key=lambda kv: kv[1][2])
            print(f"  {B:5d} pts (used {used}): {fmt(lv)}  => +{g*100:.1f}% "
                  f"({((1+g)/(1+cur_gain)-1)*100:+.1f}% vs current); next best {best_next[0]} {best_next[1][2]:.3f}%/pt")
