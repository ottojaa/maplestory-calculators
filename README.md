# MapleStory calculators

Command-line calculators for GMS MapleStory upgrade decisions (Heroic worlds), used by a personal Claude skill. Every script prints `--help`.

| Script | What it does |
| --- | --- |
| `damage_model.py` | Relative bossing damage: product of stat, ATT, damage+boss, IED, crit and final damage. Rank changes by % damage (and % per 1B with `cost=`). Paste a stat window with `--stats`. |
| `upgrade_planner.py` | Ranks candidate upgrades by % damage per 1B mesos and fills a budget, pricing cubes, star force and fixed costs (example: `examples/ren_candidates_2026-10-03.json`). |
| `star_force.py` | Exact expected star force cost and booms (v.271 rates, MathBro's cost formula), percentiles, `--fodder` copies to stockpile, `--table`. |
| `transfer_chain.py` | Star cheap fodder and Equipment Transfer the stars vs starring the valuable item directly. |
| `flames.py` | Flame (bonus stat) odds and reset costs for a STR warrior. |
| `hyper_opt.py` | Best hyper stat allocation for a point budget on the damage model. |
| `symbols.py` | Arcane symbol growth, Arcane Power, mesos and % damage by week from current levels. |
| `nexon_news.py` | Lists and reads MapleStory GMS news posts (patch notes, events) from Nexon's JSON feed: `list --grep ...`, `get <id> --grep ...`. |
| `cube_calc.mjs` | Cube odds and costs, offline (Node 18+): chance per cube of a line target, cubes and mesos to tier up and hit it. Line odds are Nexon's official tables (`data/cube_lines_kms.json`); GMS tier-up rates, prices and fees are in `data/cube_gms.json` with sources. `--lines` prints what can roll on an item; `--check` compares with [MathBro's calculator](https://brendonmay.github.io/cubingCalculator/) (downloads it). |
| `cube_rates_fetch.mjs` | Re-downloads Nexon Korea's potential tables into `data/cube_lines_kms.json` (~11,000 requests, ~17 min). Run it when Nexon changes the tables, then `node cube_calc.mjs --batch examples/cube_check_scenarios.json --check`. |

Requirements: Python 3.9+ with numpy, Node 18+ for cubes. Quick start:

```bash
python3 damage_model.py --stats "STR 15493 DEX 2687 ATT 1471 damage 46 boss 191 IED 93.09 crit 74 critdmg 17" \
  --change "Pendant 21% STR:main_pct=21,cost=0.4" --change "Link 15% IED:ied=15"
python3 star_force.py --level 140 --from 12 --to 21 --sunday --fodder --copies 2
node cube_calc.mjs --item accessory --cube glowing --from legendary --to legendary --level 140 --want percStat=21
```

Odds and costs follow Nexon's published tables, MathBro's calculators, the MapleStory Wiki and Nexon patch notes (v.271, Sept 2026). GMS publishes no cube tables: cube line odds are Nexon Korea's official KMS tables, and tier-up rates are unofficial community figures.
