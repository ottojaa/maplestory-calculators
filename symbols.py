#!/usr/bin/env python3
"""Arcane symbol growth: levels, symbol STR, Arcane Power, mesos and % damage by week, from today's levels.

Reference tool, not a leveling plan: it shows what the dailies (40 a day) and weekly clears (240 a week)
give per region, and when unlock levels add a region. Damage gains are measured against the damage model's
baseline (the damage model's baseline (profile.json or --stats)), which should already include the starting symbols.

Per symbol: STR = 200 + 100*level, Arcane Power = 20 + 10*level, next level costs level^2 + 11 symbols.

Examples:
  python3 symbols.py --levels "VJ=11,CC=10,Lach=7,Arcana=4"
  python3 symbols.py --levels "VJ=11,CC=10,Lach=7,Arcana=4" --unlock "Morass=2026-10-15,Esfera=2026-10-29" --end 2026-11-12
  python3 symbols.py --levels "VJ=11,CC=10,Lach=7,Arcana=4" --selectors "Arcana=200" --bonus-daily 5
  python3 symbols.py --costs        # symbols and mesos per level, per region
"""
import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_damage_model import load_damage_model

dm = load_damage_model()

# Meso cost factor per region (wiki): cost(level) = 10,000 * int((level^2 + 11) * (K + 0.1 * level))
K = {"VJ": 8, "CC": 10, "Lach": 12, "Arcana": 14, "Morass": 16, "Esfera": 18}
DAILY, WEEKLY = 40, 240


def sym_cost(n): return n * n + 11
def meso_cost(region, n): return 10000 * int((n * n + 11) * (K[region] + 0.1 * n))
def sym_str(levels): return sum(200 + 100 * l for l in levels.values())
def sym_arc(levels): return sum(20 + 10 * l for l in levels.values())


def parse_pairs(text, conv):
    out = {}
    for part in filter(None, (p.strip() for p in (text or "").split(","))):
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in K:
            sys.exit(f"Unknown region '{k}'. Use: {', '.join(K)}")
        out[k] = conv(v.strip())
    return out


def costs_table():
    print("Lv -> Lv+1: symbols needed (cumulative) | mesos for that level-up per region")
    cum = 0
    for n in range(1, 20):
        cum += sym_cost(n)
        print(f"  {n:2d}->{n+1:2d}: {sym_cost(n):3d} ({cum:4d}) | " +
              " ".join(f"{r} {meso_cost(r, n)/1e6:5.1f}M" for r in K))
    tot = {r: sum(meso_cost(r, n) for n in range(1, 20)) for r in K}
    print("  1->20 total: " + ", ".join(f"{r} {v/1e6:.0f}M" for r, v in tot.items()) +
          f"; all six {sum(tot.values())/1e9:.2f}B")


def simulate(levels, unlock, start, end, selectors, bonus_daily, weekly_done_now=False):
    lv, have, spent = dict(levels), {r: 0 for r in K}, 0
    start_str = sym_str(levels)
    base = dm.damage(dm.DEFAULT_PROFILE)
    weekly_done, rows, week_meso = set(), [], 0
    if weekly_done_now:
        wk0 = start - dt.timedelta(days=start.weekday())
        weekly_done = {(r, wk0) for r in levels}
    d = start
    while d <= end:
        wk = d - dt.timedelta(days=d.weekday())  # weekly reset counted Monday to Sunday
        active = set(lv) | {r for r, ud in unlock.items() if d >= ud}
        for r in active:
            if r not in lv:
                lv[r] = 1
            have[r] += DAILY + bonus_daily
            if (r, wk) not in weekly_done:
                have[r] += WEEKLY
                weekly_done.add((r, wk))
            if d == start and r in selectors:
                have[r] += selectors[r]
            while lv[r] < 20 and have[r] >= sym_cost(lv[r]):
                have[r] -= sym_cost(lv[r])
                spent += meso_cost(r, lv[r])
                week_meso += meso_cost(r, lv[r])
                lv[r] += 1
        if d.weekday() == 3 or d == end:  # Thursday checkpoints (weekly boss reset)
            g = dm.damage(dm.DEFAULT_PROFILE, {"unaffected_main": sym_str(lv) - start_str}) / base - 1
            rows.append((d, dict(lv), sym_str(lv), sym_arc(lv), g * 100, week_meso / 1e6, spent / 1e6))
            week_meso = 0
        d += dt.timedelta(days=1)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", help='current symbol levels, e.g. "VJ=11,CC=10,Lach=7,Arcana=4"')
    ap.add_argument("--unlock", default="", help='regions not yet unlocked and their unlock dates, "Morass=2026-10-15"')
    ap.add_argument("--start", default=str(dt.date.today()), help="first day counted (default today)")
    ap.add_argument("--end", default=None, help="last day (default start + 6 weeks)")
    ap.add_argument("--selectors", default="", help='one-time symbol selectors added on the start day, "Arcana=200"')
    ap.add_argument("--bonus-daily", type=int, default=0, help="extra symbols per daily (e.g. 5 from a Mesotron decoration)")
    ap.add_argument("--weekly-done", action="store_true", help="this week's weekly symbol clears are already claimed")
    ap.add_argument("--costs", action="store_true", help="print the per-level symbol and meso cost table and exit")
    a = ap.parse_args()
    if a.costs:
        costs_table()
        return
    if not a.levels:
        sys.exit("--levels is required (or use --costs)")
    levels = parse_pairs(a.levels, int)
    unlock = parse_pairs(a.unlock, dt.date.fromisoformat)
    selectors = parse_pairs(a.selectors, int)
    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end) if a.end else start + dt.timedelta(weeks=6)

    print(f"Start {start}: " + " ".join(f"{k}{v}" for k, v in levels.items()) +
          f" | symbol STR {sym_str(levels)} | Arcane Power from symbols {sym_arc(levels)}")
    print(f"Damage vs the model baseline (as of {dm.PROFILE_AS_OF if hasattr(dm, 'PROFILE_AS_OF') else '?'}), "
          "which should already include these starting symbols.\n")
    for d, l, s, arc, g, wm, sp in simulate(levels, unlock, start, end, selectors, a.bonus_daily, a.weekly_done):
        print(f"{d} | " + " ".join(f"{k}{v}" for k, v in l.items()) +
              f" | STR {s} | ARC {arc} | {g:+.1f}% | {wm:.0f}M this week, {sp:.0f}M total")


if __name__ == "__main__":
    main()
