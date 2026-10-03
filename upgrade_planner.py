#!/usr/bin/env python3
"""Rank MapleStory upgrades by % damage per billion mesos, and fill a meso budget.

Ties together the three calculators the skills already have:
  - damage gain:   maplestory-gms/scripts/damage_model.py   (product of damage buckets)
  - cube cost:     maplestory-cubing/scripts/cube_calc.mjs  (Nexon's line tables, offline, needs Node)
  - star force:    maplestory-strength-map/scripts/star_force.py

Candidates come from a JSON file (a list). Each candidate:
  {"label": "Dominator Pendant 21% STR",
   "change": "main_pct=21",                       # damage_model change keys, comma-separated
   "cost": {"type": "cube", "item": "accessory", "cube": "glowing",
            "from": "legendary", "to": "legendary", "level": 140, "want": "percStat=21"},
   "group": "pendant",                             # optional: at most one candidate per group is picked
   "note": "keeps the drop line",                  # optional
   "pin": true}                                    # optional: fund it first whatever its %/1B (e.g. drop/meso gear)
Cost types:
  {"type": "fixed", "mesos": 55e6}                                  # known price (flame resets, coupons...)
  {"type": "fixed", "mesos": 55e6, "p75": 80e6}                     # optional 75% budget
  {"type": "cube", ...cube_calc flags...}                           # mean and 75% from the cube calculator
  {"type": "starforce", "level": 140, "from": 12, "to": 17, "sunday": true}
Value that isn't damage (drop/meso lines, a boss unlock) can't be priced here: give "gain_pct" by hand
or leave the candidate out and say so in the answer.

Usage:
  python3 upgrade_planner.py candidates.json --budget 2.5      # baseline = the damage model's baseline (profile.json or --stats)
  python3 upgrade_planner.py candidates.json --stats "STR 15493 DEX 2687 ATT 1471 boss 191 IED 93.09" --budget 2.5
  python3 upgrade_planner.py candidates.json --budget 2.5 --basis p75   # plan on 75% budgets instead of means
"""
import argparse
import glob
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(rel_candidates, env, what):
    for c in [os.environ.get(env, "")] + rel_candidates:
        for path in sorted(glob.glob(os.path.expanduser(c))) if c else []:
            if os.path.exists(path):
                return os.path.abspath(path)
    sys.exit(f"{what} not found; set {env} to its path")


def _skill_paths(skill, rel):
    return [os.path.join(HERE, os.path.basename(rel)),
            os.path.join(HERE, "..", "..", skill, rel),
            f"~/.claude/skills/{skill}/{rel}",
            f"~/.claude/skills/*/{skill}/{rel}",
            f"/root/.claude/skills/synced/*/{skill}/{rel}",
            f"/mnt/skills/*/{skill}/{rel}"]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dm = _load(_find(_skill_paths("maplestory-gms", "scripts/damage_model.py"), "MAPLE_DAMAGE_MODEL",
                 "damage_model.py"), "dm")


def combine(changes):
    """Add changes inside each bucket; IED (and final damage) sources multiply. Uses damage_model's own rule."""
    if hasattr(dm, "combine"):
        return dm.combine(changes)
    out = {}
    for ch in changes:
        for k, v in ch.items():
            if k == "ied":
                prev = out.get("ied", 0)
                out["ied"] = 100 * (1 - (1 - prev / 100) * (1 - v / 100))
            else:
                out[k] = out.get(k, 0) + v
    return out


def parse_change(text):
    ch = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in dm.CHANGE_KEYS:
            sys.exit(f"Unknown change key '{k}'. Valid: {', '.join(dm.CHANGE_KEYS)}")
        ch = combine([ch, {k: float(v)}])
    return ch


def cube_cost(spec):
    calc = _find(_skill_paths("maplestory-cubing", "scripts/cube_calc.mjs"), "MAPLE_CUBE_CALC", "cube_calc.mjs")
    args = ["node", calc, "--json"]
    for k in ("item", "cube", "from", "to", "level", "want"):
        if k in spec:
            args += [f"--{k}", str(spec[k])]
    if spec.get("dmt"):
        args.append("--dmt")
    res = json.loads(subprocess.run(args, capture_output=True, text=True, check=True,
                                    cwd=os.path.dirname(os.path.dirname(calc))).stdout)[0]
    m = res["totalMesos"]
    return m["mean"], m["seventy_fifth"]


def sf_cost(spec):
    sf = _load(_find(_skill_paths("maplestory-strength-map", "scripts/star_force.py"), "MAPLE_STAR_FORCE",
                     "star_force.py"), "sf")
    sunday, safe = spec.get("sunday", False), spec.get("safeguard", False)
    mean, booms = sf.expected(spec["from"], spec["to"], spec["level"], sunday, safe)
    out, _ = sf.simulate(spec["from"], spec["to"], spec["level"], sunday, safe, trials=8000)
    import numpy as np
    return mean, float(np.percentile(out, 75)), booms


def price(c):
    cost = c["cost"]
    t = cost.get("type")
    if t == "fixed":
        return cost["mesos"], cost.get("p75", cost["mesos"]), None
    if t == "cube":
        mean, p75 = cube_cost(cost)
        return mean, p75, None
    if t == "starforce":
        return sf_cost(cost)
    sys.exit(f"{c['label']}: unknown cost type {t!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("candidates", help="JSON file with a list of candidates")
    ap.add_argument("--profile", help="JSON file overriding damage_model's baseline fields")
    ap.add_argument("--stats", help='pasted stat window, e.g. "STR 15493 DEX 2687 ATT 1471 boss 191 IED 93.09"')
    ap.add_argument("--set", action="append", default=[], help="override one baseline field, e.g. boss=191")
    ap.add_argument("--budget", type=float, help="meso budget in billions; fills it greedily by %% per 1B")
    ap.add_argument("--basis", choices=["mean", "p75"], default="mean",
                    help="cost used for ranking and budgeting (default: mean)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    profile = dict(dm.DEFAULT_PROFILE)
    if a.profile:
        profile.update({k: v for k, v in json.load(open(a.profile)).items() if k in profile})
    if a.stats:
        profile.update(dm.parse_stats(a.stats))
    for s in a.set:
        k, _, v = s.partition("=")
        profile[k.strip()] = float(v)
    base = dm.damage(profile)

    rows = []
    for c in json.load(open(a.candidates)):
        ch = parse_change(c.get("change", ""))
        gain = c.get("gain_pct")
        manual = gain is not None
        if gain is None:
            gain = (dm.damage(profile, ch) / base - 1) * 100
        mean, p75, booms = price(c)
        basis = mean if a.basis == "mean" else p75
        per_b = gain / (basis / 1e9) if basis > 0 else float("inf")
        rows.append({**c, "parsed": ch, "gain_pct": gain, "mean": mean, "p75": p75, "booms": booms,
                     "per_b": per_b, "manual": manual})
    rows.sort(key=lambda r: -r["per_b"])

    plan = []
    if a.budget is not None:
        left, used_groups = a.budget * 1e9, set()
        for r in sorted(rows, key=lambda r: not r.get("pin")):
            cost = r["mean"] if a.basis == "mean" else r["p75"]
            if r.get("group") in used_groups or cost > left:
                continue
            plan.append(r)
            left -= cost
            if r.get("group"):
                used_groups.add(r["group"])
        together = (dm.damage(profile, combine([r["parsed"] for r in plan])) / base - 1) * 100
        # Hand-entered gains are combined multiplicatively with the modelled ones.
        together = ((1 + together / 100) * __import__("math").prod(1 + r["gain_pct"] / 100 for r in plan if r["manual"]) - 1) * 100

    if a.json:
        print(json.dumps({"profile": profile, "ranked": rows,
                          "plan": [r["label"] for r in plan]}, indent=2, default=str))
        return

    print("Baseline: " + ", ".join(f"{k}={v:g}" for k, v in profile.items()))
    print(f"\nRanked by % damage per 1B ({a.basis} cost); * = pinned, funded first:")
    print(f"  {'upgrade':44} {'gain':>7} {'mean':>7} {'75%':>7} {'%/1B':>7}")
    for r in rows:
        extra = f"  booms {r['booms']:.2f}" if r.get("booms") else ""
        print(f"  {('* ' if r.get('pin') else '') + r['label'][:42]:44} {r['gain_pct']:+6.2f}% {r['mean']/1e9:6.2f}B {r['p75']/1e9:6.2f}B "
              f"{r['per_b']:6.1f}{extra}")
        if r.get("note"):
            print(f"  {'':44} note: {r['note']}")
    if a.budget is not None:
        spent = sum(r["mean"] if a.basis == "mean" else r["p75"] for r in plan)
        print(f"\nBudget {a.budget:.2f}B ({a.basis}): pick {len(plan)}, spend {spent/1e9:.2f}B")
        for r in plan:
            print(f"  - {r['label']}")
        print(f"  Together: {together:+.2f}% damage (buckets combined, IED multiplied)")
        print("  One session can land far above or below the average; re-plan after each result.")


if __name__ == "__main__":
    main()
