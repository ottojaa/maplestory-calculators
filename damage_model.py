#!/usr/bin/env python3
"""Relative bossing damage model for MapleStory upgrades.

Estimates how much a change (more boss %, more STR %, symbol STR, ATT, IED, crit) raises damage against a
boss, compared with a baseline stat sheet. Used to rank upgrades by mesos or time per % damage.

Damage is modelled as the product of independent factors:
  stat   = 4 * main_total + secondary          (main stat counts 4x, e.g. STR for warriors)
  att    = att_base * (1 + att_pct)
  dmg    = 1 + (damage% + boss%)               (damage and boss damage add together)
  ied    = 1 - boss_def * remaining_def         (each IED source multiplies the remaining defense)
  crit   = 1 + crit_rate * (0.35 + crit_dmg)    (crit hits average +35% base, plus crit damage)
  final  = 1 + final_dmg                        (only for changes: Arcane Power bands, HEXA boosts...)
The baseline's own final damage % and skill % cancel out of comparisons, so they're left out.

The baseline is profile.json next to this script if present (dated), otherwise a built-in example sheet.
A warning prints when it's over two weeks old. Override it with --stats (a pasted stat window), --profile or --set.

Examples:
  python3 damage_model.py --change "Pendant 21% STR:main_pct=21,cost=0.40" --change "Link 15% IED:ied=15"
  python3 damage_model.py --stats "STR 15493 DEX 2687 ATT 1471 damage 46 boss 191 IED 93.09 crit 74 critdmg 17" \
      --change "Arcane Power x1.3 band:final_dmg=30"
  python3 damage_model.py --profile my_stats.json --change "Weapon ATT 12%:att_pct=12" --json
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

PROFILE_PATH = os.environ.get("MAPLE_PROFILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")
STALE_DAYS = 14

# Example baseline used when there's no profile.json: a Lv. 227 STR warrior's stat window (2026-10-02).
# Pass --stats with the current stat window instead; the script warns when the baseline is over two weeks old.
_FALLBACK_PROFILE = {
    "main": 15493, "secondary": 2687, "main_pct": 200, "unaffected_main": 4150, "att": 1471, "att_pct": 25,
    "damage": 46, "boss": 191, "ied": 93.09, "crit_rate": 74, "crit_dmg": 17, "boss_def": 300,
}
_FALLBACK_AS_OF = dt.date(2026, 10, 2)
PROFILE_FIELDS = {
    "main": "total main stat shown in the stat window",
    "secondary": "total secondary stat",
    "main_pct": "total main stat %, assumed (not shown in game)",
    "unaffected_main": "main stat that % doesn't multiply: arcane/sacred symbols + hyper stat",
    "att": "total ATT shown (unbuffed)",
    "att_pct": "total ATT %, assumed",
    "damage": "damage %",
    "boss": "boss damage %",
    "ied": "ignore defense %",
    "crit_rate": "crit rate %",
    "crit_dmg": "crit damage %",
    "boss_def": "target defense %: ~200 Chaos Vellum, ~300 Lotus/Damien and later",
}


def _read_profile(path):
    """Return (numeric fields, as_of date or None) from a profile JSON."""
    with open(path) as f:
        raw = json.load(f)
    fields = {k: float(v) for k, v in raw.items() if k in PROFILE_FIELDS}
    as_of = raw.get("as_of")
    return fields, (dt.date.fromisoformat(as_of) if as_of else None)


try:
    _fields, PROFILE_AS_OF = _read_profile(PROFILE_PATH)
    DEFAULT_PROFILE = {**_FALLBACK_PROFILE, **_fields}
except FileNotFoundError:
    DEFAULT_PROFILE, PROFILE_AS_OF = dict(_FALLBACK_PROFILE), _FALLBACK_AS_OF

CHANGE_KEYS = {
    "flat_main": "main stat added before % (gear, flames, star force)",
    "unaffected_main": "main stat that % doesn't multiply (arcane/sacred symbols, hyper stat)",
    "main_pct": "main stat % (potential lines, all-stat % counts too)",
    "att": "flat ATT added before %",
    "att_pct": "ATT %",
    "damage": "damage %",
    "boss": "boss damage %",
    "ied": "a new IED source, applied multiplicatively (e.g. 15 for a 15% link)",
    "crit_rate": "crit rate % (capped at 100)",
    "crit_dmg": "crit damage %",
    "final_dmg": "final damage % as a multiplier (Arcane Power band 10/30/50, HEXA boosts); sources multiply",
    "boss_def": "change the target's defense %",
}
MULTIPLICATIVE = ("ied", "final_dmg")

# Stat-window names accepted by --stats, lower-case, mapped to profile fields.
STAT_ALIASES = {
    "str": "main", "main": "main", "mainstat": "main",
    "dex": "secondary", "secondary": "secondary",
    "att": "att", "attack": "att",
    "damage": "damage", "dmg": "damage",
    "boss": "boss", "bossdamage": "boss",
    "ied": "ied", "ignoredefense": "ied", "ignoredef": "ied",
    "crit": "crit_rate", "critrate": "crit_rate", "crit_rate": "crit_rate",
    "critdmg": "crit_dmg", "critdamage": "crit_dmg", "crit_dmg": "crit_dmg", "cd": "crit_dmg",
    "symbols": "unaffected_main", "unaffected": "unaffected_main", "unaffected_main": "unaffected_main",
    "strpct": "main_pct", "main_pct": "main_pct", "attpct": "att_pct", "att_pct": "att_pct",
    "def": "boss_def", "bossdef": "boss_def", "boss_def": "boss_def",
}


def combine(changes):
    """Merge change dicts: values add inside each stat, except IED and final damage, which multiply."""
    out = {}
    for ch in changes:
        for k, v in ch.items():
            if k in MULTIPLICATIVE:
                out[k] = 100 * (1 - (1 - out.get(k, 0) / 100) * (1 - v / 100)) if k == "ied" \
                    else 100 * ((1 + out.get(k, 0) / 100) * (1 + v / 100) - 1)
            else:
                out[k] = out.get(k, 0) + v
    return out


def parse_stats(text):
    """Parse a pasted stat window like 'STR 15,493 DEX 2687 ATT 1471 boss 191% IED 93.09 crit 74 critdmg 17'."""
    out = {}
    for name, value in re.findall(r"([A-Za-z_]+(?:\s+(?:damage|rate|def|defense))?)\s*[:=]?\s*([\d,]+(?:\.\d+)?)\s*%?", text):
        key = STAT_ALIASES.get(re.sub(r"\s+", "", name).lower())
        if key is None:
            sys.exit(f"Unknown stat '{name}' in --stats. Known: {', '.join(sorted(set(STAT_ALIASES)))}")
        out[key] = float(value.replace(",", ""))
    if not out:
        sys.exit("--stats: no 'name value' pairs found")
    return out


def damage(p, ch=None):
    ch = ch or {}
    base_flat = (p["main"] - p["unaffected_main"]) / (1 + p["main_pct"] / 100)
    main_total = ((base_flat + ch.get("flat_main", 0)) * (1 + (p["main_pct"] + ch.get("main_pct", 0)) / 100)
                  + p["unaffected_main"] + ch.get("unaffected_main", 0))
    stat = 4 * main_total + p["secondary"]

    att_base = p["att"] / (1 + p["att_pct"] / 100)
    att = (att_base + ch.get("att", 0)) * (1 + (p["att_pct"] + ch.get("att_pct", 0)) / 100)

    dmg = 1 + (p["damage"] + p["boss"] + ch.get("damage", 0) + ch.get("boss", 0)) / 100

    remaining = (1 - p["ied"] / 100) * (1 - ch.get("ied", 0) / 100)
    ied = max(0.0, 1 - (p["boss_def"] + ch.get("boss_def", 0)) / 100 * remaining)

    cr = min(100, p["crit_rate"] + ch.get("crit_rate", 0)) / 100
    crit = 1 + cr * (0.35 + (p["crit_dmg"] + ch.get("crit_dmg", 0)) / 100)

    final = 1 + ch.get("final_dmg", 0) / 100

    return stat * att * dmg * ied * crit * final


def parse_change(text):
    """'label:key=value,...' -> (label, change dict, cost in billions or None). 'cost' is a pseudo-key."""
    label, _, body = text.rpartition(":")
    if not label:
        label = body
    parts, cost = [], None
    for part in body.split(","):
        key, _, value = part.partition("=")
        key = key.strip()
        if key == "cost":
            cost = float(value)
            continue
        if key not in CHANGE_KEYS:
            sys.exit(f"Unknown change key '{key}'. Valid keys: {', '.join(CHANGE_KEYS)}, cost (billions)")
        parts.append({key: float(value)})
    return label.strip(), combine(parts), cost


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="JSON file overriding any baseline field (same fields as profile.json; extra keys ignored)")
    ap.add_argument("--stats", help='pasted stat window, e.g. "STR 15493 DEX 2687 ATT 1471 boss 191 IED 93.09"')
    ap.add_argument("--set", action="append", default=[], help="override one baseline field, e.g. --set boss_def=300")
    ap.add_argument("--change", action="append", default=[],
                    help='"label:key=value,key=value[,cost=B]" (repeatable; cost in billions adds %% per 1B)')
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    profile, as_of = dict(DEFAULT_PROFILE), PROFILE_AS_OF
    if args.profile:
        fields, as_of = _read_profile(args.profile)
        profile.update(fields)
    if args.stats:
        profile.update(parse_stats(args.stats))
        as_of = dt.date.today()
    for s in args.set:
        key, _, value = s.partition("=")
        profile[key.strip()] = float(value)
    if as_of and (dt.date.today() - as_of).days > STALE_DAYS and not args.stats:
        print(f"Warning: baseline stats are from {as_of}, over {STALE_DAYS} days old. Pass --stats with the "
              f"current stat window.", file=sys.stderr)

    base = damage(profile)
    results, changes, total_cost = [], [], 0.0
    for text in args.change:
        label, change, cost = parse_change(text)
        gain = damage(profile, change) / base - 1
        r = {"label": label, "change": change, "gain_pct": round(gain * 100, 2)}
        if cost:
            r["cost_b"] = cost
            r["pct_per_b"] = round(gain * 100 / cost, 2)
            total_cost += cost
        results.append(r)
        changes.append(change)
    if len(results) > 1:
        combined = combine(changes)
        gain = damage(profile, combined) / base - 1
        r = {"label": "All changes together", "change": combined, "gain_pct": round(gain * 100, 2)}
        if total_cost:
            r["cost_b"] = round(total_cost, 3)
            r["cost_partial"] = any("cost_b" not in x for x in results)
        results.append(r)

    if args.json:
        print(json.dumps({"profile": profile, "as_of": str(as_of) if as_of else None, "results": results}, indent=2))
        return
    print(f"Baseline ({as_of}): " + ", ".join(f"{k}={v:g}" for k, v in profile.items()))
    if not results:
        print("No --change given. Valid keys: " + ", ".join(f"{k} ({d})" for k, d in CHANGE_KEYS.items()))
    for r in results:
        extra = ""
        if "pct_per_b" in r:
            extra = f"   {r['cost_b']:g}B -> {r['pct_per_b']:.1f}% per 1B"
        elif "cost_b" in r:
            extra = f"   {r['cost_b']:g}B total" + (" (priced changes only)" if r.get("cost_partial") else "")
        print(f"{r['gain_pct']:+7.2f}%  {r['label']}{extra}")


if __name__ == "__main__":
    main()
