#!/usr/bin/env python3
"""Compare star forcing an item directly with starring cheap fodder and moving the stars by Equipment Transfer.

Equipment Transfer (GMS, wiki Equipment_Transfer): star force and potential move to an item of the same type
up to 10 levels higher (20 if the source is Lv. 119 or below). The target gets one star less, and potential
arrives at Epic at most. Superior (Tyrant-type) equipment can't take part.

The point of the fodder route is where the boom risk lands: a boomed fodder item costs one re-farmable copy,
while a boomed target (e.g. a Superior Gollux piece) costs a copy of the target. Star force cost also grows
with item level cubed, so stars are cheaper on lower-level fodder.

Examples:
  # Golden Clover Belt (140) to 21 stars, then transfer to a Superior Gollux Belt (150): arrives at 20
  python3 transfer_chain.py --chain 140 150 --stars 21 --sunday
  # Dominator (140) -> Superior Gollux Pendant (150) -> Source of Suffering (160), topping up at each step
  python3 transfer_chain.py --chain 140 150 160 --stars 21 --topup 21 --sunday
Mesos for the transfer itself (if any) and copies' farming time aren't priced; copies are reported instead.
"""
import argparse
import glob
import importlib.util
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_sf():
    rel = "scripts/star_force.py"
    cands = [os.environ.get("MAPLE_STAR_FORCE", ""), os.path.join(HERE, "star_force.py"),
             os.path.join(HERE, "..", "..", "maplestory-strength-map", rel),
             "~/.claude/skills/maplestory-strength-map/" + rel,
             "/root/.claude/skills/synced/*/maplestory-strength-map/" + rel,
             "/mnt/skills/*/maplestory-strength-map/" + rel]
    for c in cands:
        for p in sorted(glob.glob(os.path.expanduser(c))) if c else []:
            spec = importlib.util.spec_from_file_location("sf", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    sys.exit("star_force.py not found; set MAPLE_STAR_FORCE to its path")


sf = _load_sf()


def climb(level, start, target, sunday, trials):
    """Mean mesos, 75% mesos, mean booms and boom samples for one climb."""
    if target <= start:
        return 0.0, 0.0, 0.0, np.zeros(max(trials, 1))
    mean, booms = sf.expected(start, target, level, sunday)
    out, b = sf.simulate(start, target, level, sunday, trials=trials)
    return mean, float(np.percentile(out, 75)), booms, b


def check_gap(src, dst):
    gap = dst - src
    limit = 20 if src <= 119 else 10
    if gap < 0 or gap > limit:
        sys.exit(f"Lv. {src} -> Lv. {dst} can't transfer: the target must be 0-{limit} levels higher")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chain", type=int, nargs="+", required=True,
                    help="item levels along the transfer path, fodder first, e.g. 140 150 160")
    ap.add_argument("--stars", type=int, required=True, help="stars to reach on the fodder")
    ap.add_argument("--from", dest="start", type=int, default=0, help="fodder's current stars (default 0)")
    ap.add_argument("--topup", type=int, default=None,
                    help="after each transfer, star the new item back up to this many stars before moving on "
                         "(booms here cost copies of that item)")
    ap.add_argument("--sunday", action="store_true", help="Sunny Sunday: 30%% off, 30%% less destruction below 21★")
    ap.add_argument("--trials", type=int, default=20000)
    a = ap.parse_args()
    for s, d in zip(a.chain, a.chain[1:]):
        check_gap(s, d)

    tag = " (Sunny Sunday)" if a.sunday else ""
    print(f"Transfer chain Lv. {' -> '.join(map(str, a.chain))}{tag}\n")

    total_mean = total_p75 = 0.0
    stars = a.start
    rows = []
    for i, lvl in enumerate(a.chain):
        goal = a.stars if i == 0 else (a.topup if a.topup is not None else stars)
        mean, p75, booms, b = climb(lvl, stars, goal, a.sunday, a.trials)
        total_mean += mean
        total_p75 += p75
        rows.append((lvl, stars, max(goal, stars), mean, p75, booms, b))
        stars = max(goal, stars)
        if i + 1 < len(a.chain):
            stars -= 1  # transfer loses one star
    final = stars

    print(f"  {'step':28} {'mean':>7} {'75%':>7} {'booms (copies of that item)':>28}")
    for i, (lvl, s0, s1, mean, p75, booms, b) in enumerate(rows):
        if s1 > s0:
            label = f"Lv. {lvl}: {s0}->{s1}★" + (" (fodder)" if i == 0 else "")
            stock = int(np.ceil(np.percentile(b, 75))) if booms else 0
            risk = f", {np.mean(b > 0)*100:.0f}% chance of at least one" if booms else ""
            print(f"  {label:28} {mean/1e9:6.2f}B {p75/1e9:6.2f}B {booms:6.2f} mean, stock {stock} for 75%{risk}")
        if i + 1 < len(rows):
            print(f"  {'  transfer':28} -> Lv. {rows[i+1][0]} arrives at {s1 - 1}★ (potential capped at Epic)")
    print(f"  {'Fodder route total':28} {total_mean/1e9:6.2f}B {total_p75/1e9:6.2f}B   final: Lv. {a.chain[-1]} at {final}★")

    last = a.chain[-1]
    d_mean, d_p75, d_booms, d_b = climb(last, 0, final, a.sunday, a.trials)
    stock = int(np.ceil(np.percentile(d_b, 75))) if d_booms else 0
    print(f"\n  Direct: Lv. {last} 0->{final}★     {d_mean/1e9:6.2f}B {d_p75/1e9:6.2f}B "
          f"{d_booms:6.2f} booms, each a copy of the Lv. {last} item (stock {stock} for 75%)")
    fodder_booms = rows[0][5]
    later_booms = sum(r[5] for r in rows[1:])
    print(f"\n  Mesos: fodder route {total_mean/1e9:.2f}B vs direct {d_mean/1e9:.2f}B "
          f"({(total_mean - d_mean)/1e9:+.2f}B).")
    print(f"  Booms on the valuable item: {later_booms:.2f} on the fodder route vs {d_booms:.2f} direct; "
          f"the fodder route's other {fodder_booms:.2f} land on cheap Lv. {a.chain[0]} copies.")


if __name__ == "__main__":
    main()
