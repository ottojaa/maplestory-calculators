#!/usr/bin/env node
// Cube odds and costs for GMS (Heroic), computed offline from data in this repo.
//
// Line odds: data/cube_lines_kms.json, a copy of Nexon Korea's official per-line potential tables (GMS publishes
// none); the file says where and how it was copied. GMS numbers Nexon doesn't publish (tier-up rates, cube prices,
// the per-cube meso fee, the Lv. 151+ stat step) are in data/cube_gms.json, each with its source.
// Scenarios with an "expect" field are checked against it: examples/cube_check_scenarios.json holds MathBro's
// results (https://brendonmay.github.io/cubingCalculator/, 2026-10-04) for 124 scenarios; all should say "match".
//
// Usage:
//   node cube_calc.mjs --item ring --cube glowing --from epic --to legendary --level 140 --want percStat=21
//   node cube_calc.mjs --batch scenarios.json [--json]
//   node cube_calc.mjs --lines --item weapon --cube glowing --to legendary --level 150
//   node cube_calc.mjs --rates

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TIERS = ["rare", "epic", "unique", "legendary"];
const TIER_LABEL = ["Rare", "Epic", "Unique", "Legendary"];
const ITEM_ALIASES = { accessory: "ring", badge: "heart", forceshield: "forceShield", soulring: "forceShield" };

// --- Data ---------------------------------------------------------------------------------------------------

export function loadData() {
  const read = (f) => JSON.parse(fs.readFileSync(path.join(HERE, "data", f), "utf8"));
  const kms = read("cube_lines_kms.json");
  const gms = read("cube_gms.json");
  const cubeByName = {};
  for (const [key, c] of Object.entries(gms.cubes)) for (const n of [key, ...c.aliases]) cubeByName[n] = key;
  return { kms, gms, cubeByName, options: kms.options.map(classify) };
}

// Option text (Korean, as Nexon prints it) -> what it is. Unrecognised text counts as a junk line.
const OPTION_PATTERNS = [
  [/^(STR|DEX|INT|LUK) \+(\d+)%$/, (m) => [`${m[1]} %`, +m[2]]],
  [/^올스탯 \+(\d+)%$/, (m) => ["All Stats %", +m[1]]],
  [/^최대 HP \+(\d+)%$/, (m) => ["Max HP %", +m[1]]],
  [/^최대 MP \+(\d+)%$/, (m) => ["Max MP %", +m[1]]],
  [/^공격력 \+(\d+)%$/, (m) => ["ATT %", +m[1]]],
  [/^마력 \+(\d+)%$/, (m) => ["MATT %", +m[1]]],
  [/^데미지 \+(\d+)%$/, (m) => ["Damage %", +m[1]]],
  [/^보스 몬스터 (?:공격 시 )?데미지 \+(\d+)%$/, (m) => ["Boss Damage %", +m[1]]],
  [/^몬스터 방어율 무시 \+(\d+)%$/, (m) => ["IED %", +m[1]]],
  [/^크리티컬 확률 \+(\d+)%$/, (m) => ["Crit Rate %", +m[1]]],
  [/^크리티컬 데미지 \+(\d+)%$/, (m) => ["Crit Damage %", +m[1]]],
  [/^(?:모든 )?스킬(?:의)? 재사용 대기시간 -(\d+)초/, (m) => ["Cooldown s", +m[1]]],
  [/^메소 획득량 \+(\d+)%$/, (m) => ["Meso %", +m[1]]],
  [/^아이템 드롭률 \+(\d+)%$/, (m) => ["Item Drop %", +m[1]]],
  [/확률로 오토스틸$/, () => ["Auto Steal", null]],
];

// Repeat limits Nexon lists on every cube page (대상 장비에 따른 옵션): at most one decent skill and one
// "invincibility time after being hit" line, at most two of each "when hit" chance line. When a line hits its
// family's limit, later lines draw from the remaining options: probability / (100% - excluded probabilities).
const LIMITS = [
  { family: "decent skill", max: 1, test: /^<쓸만한 .*> 스킬 사용 가능$/, ko: "쓸만한 스킬 계열" },
  { family: "invincibility time after hit", max: 1, test: /^피격 후 무적시간 \+\d+초$/, ko: "피격 후 무적시간 증가" },
  { family: "chance to ignore % damage when hit", max: 2, test: /^피격 시 \d+% 확률로 데미지의 \d+% 무시$/, ko: "피격 시 일정 확률로 데미지 % 무시" },
  { family: "chance of invincibility when hit", max: 2, test: /^피격 시 \d+% 확률로 \d+초간 무적$/, ko: "피격 시 일정 확률로 일정 시간 무적" },
];

function classify(text) {
  const limit = LIMITS.findIndex((l) => l.test.test(text));
  for (const [re, f] of OPTION_PATTERNS) {
    const m = text.match(re);
    if (m) { const [stat, value] = f(m); return { text, stat, value, limit }; }
  }
  return { text, stat: null, value: null, limit };
}

function resolveCube(d, name) {
  const key = d.cubeByName[String(name).toLowerCase()];
  if (!key) throw new Error(`Unknown cube "${name}". Use one of: ${Object.keys(d.cubeByName).join(", ")}`);
  return { key, ...d.gms.cubes[key] };
}

function resolveItem(d, name) {
  const lower = String(name).toLowerCase();
  const item = ITEM_ALIASES[lower] || Object.keys(d.kms.index.red.legendary).find((k) => k.toLowerCase() === lower);
  if (!item) {
    throw new Error(`Unknown item "${name}". Use one of: ${Object.keys(d.kms.index.red.legendary).join(", ")}, ` +
      `or ${Object.keys(ITEM_ALIASES).join(", ")}`);
  }
  return item;
}

// The three line distributions for one cube, tier, slot and level: [{...option, p}] per line, each summing to 1.
export function lineTables(d, cube, tier, item, level) {
  const ranges = d.kms.index[cube.kmsLines]?.[TIERS[tier]]?.[item];
  if (!ranges) throw new Error(`${cube.label} cubes have no ${TIER_LABEL[tier]} lines`);
  const range = ranges.find(([a, b]) => level >= a && level <= b);
  if (!range) {
    throw new Error(`Nexon's tables have no ${item} at Lv. ${level} (they cover Lv. ${ranges[0][0]}-${ranges[ranges.length - 1][1]})`);
  }
  const bump = d.gms.statBump;
  const bumped = level >= bump.fromLevel && level <= bump.toLevel;
  return d.kms.tables[range[2]].map((rows) => {
    const sum = rows.reduce((a, [, p]) => a + p, 0);
    return rows.map(([o, p]) => {
      const opt = d.options[o];
      const value = bumped && bump.options.includes(opt.stat) ? opt.value + bump.plus : opt.value;
      return { ...opt, value, p: p / sum };
    });
  });
}

// --- Targets ------------------------------------------------------------------------------------------------

// What each --want key counts, per line: a stat's value, or 1 for a matching line. "STR" stands for any one
// main stat and "ATT" for MATT; they roll at the same odds.
const is = (...stats) => (o) => (stats.includes(o.stat) ? 1 : 0);
const val = (...stats) => (o) => (stats.includes(o.stat) ? o.value : 0);
const WANTS = {
  percStat: { desc: "at least this much STR % (all-stat lines count)", per: val("STR %", "All Stats %") },
  lineStat: { desc: "lines of STR % or all-stat %", per: is("STR %", "All Stats %") },
  percAllStat: { desc: "all-stat %, with STR/DEX/LUK % counting a third (Xenon)",
    per: (o) => (o.stat === "All Stats %" ? o.value : ["STR %", "DEX %", "LUK %"].includes(o.stat) ? o.value / 3 : 0) },
  lineAllStat: { desc: "lines of all-stat %", per: is("All Stats %") },
  percHp: { desc: "max HP %", per: val("Max HP %") },
  lineHp: { desc: "lines of max HP %", per: is("Max HP %") },
  percAtt: { desc: "ATT %", per: val("ATT %") },
  lineAtt: { desc: "lines of ATT %", per: is("ATT %") },
  percBoss: { desc: "boss damage %", per: val("Boss Damage %") },
  lineBoss: { desc: "lines of boss damage", per: is("Boss Damage %") },
  lineIed: { desc: "lines of IED", per: is("IED %") },
  lineCritDamage: { desc: "lines of crit damage", per: is("Crit Damage %") },
  lineMeso: { desc: "lines of meso obtained", per: is("Meso %") },
  lineDrop: { desc: "lines of item drop rate", per: is("Item Drop %") },
  lineMesoOrDrop: { desc: "lines of meso or drop", per: is("Meso %", "Item Drop %") },
  secCooldown: { desc: "seconds of skill cooldown reduction", per: val("Cooldown s") },
  lineAutoSteal: { desc: "lines of auto steal", per: is("Auto Steal") },
  lineAttOrBoss: { desc: "lines of ATT % or boss", per: is("ATT %", "Boss Damage %") },
  lineAttOrBossOrIed: { desc: "lines of ATT %, boss or IED", per: is("ATT %", "Boss Damage %", "IED %") },
  lineBossOrIed: { desc: "lines of boss or IED", per: is("Boss Damage %", "IED %") },
};

function parseWant(want) {
  // "percStat=21,lineBoss=1" or an object {percStat: 21}
  if (!want) return {};
  const out = {};
  const parts = typeof want === "object" ? Object.entries(want)
    : String(want).split(/[,&]/).map((s) => s.trim()).filter(Boolean).map((s) => s.split(/[=+]/));
  for (const [k, v] of parts) {
    if (!WANTS[k]) throw new Error(`Unknown --want key "${k}". Valid: ${Object.keys(WANTS).join(", ")}`);
    out[k] = (out[k] || 0) + Number(v);
  }
  return out;
}

// Chance that one cube rolls lines meeting every target in `want`. Lines are enumerated in order; when an earlier
// line uses up a family's repeat limit, that family is dropped from later lines and the rest rescaled.
export function targetChance(lines, want) {
  const keys = Object.keys(want);
  const need = keys.map((k) => want[k] - 1e-9);
  // Merge options that count the same toward the targets and share a limit family.
  const merged = lines.map((line) => {
    const groups = new Map();
    for (const o of line) {
      const v = keys.map((k) => WANTS[k].per(o));
      const key = `${o.limit}|${v.join(",")}`;
      if (groups.has(key)) groups.get(key).p += o.p;
      else groups.set(key, { p: o.p, v, limit: o.limit });
    }
    return [...groups.values()];
  });
  const familyMass = merged.map((line) => {
    const m = LIMITS.map(() => 0);
    for (const g of line) if (g.limit >= 0) m[g.limit] += g.p;
    return m;
  });
  const used = LIMITS.map(() => 0);
  const sum = keys.map(() => 0);
  let total = 0;
  function walk(i, prob) {
    if (i === 3) {
      if (need.every((n, k) => sum[k] >= n)) total += prob;
      return;
    }
    let excluded = 0;
    LIMITS.forEach((l, f) => { if (used[f] >= l.max) excluded += familyMass[i][f]; });
    for (const g of merged[i]) {
      if (g.limit >= 0 && used[g.limit] >= LIMITS[g.limit].max) continue;
      if (g.limit >= 0) used[g.limit]++;
      g.v.forEach((x, k) => { sum[k] += x; });
      walk(i + 1, (prob * g.p) / (1 - excluded));
      g.v.forEach((x, k) => { sum[k] -= x; });
      if (g.limit >= 0) used[g.limit]--;
    }
  }
  walk(0, 1);
  return total;
}

// --- Costs --------------------------------------------------------------------------------------------------

const QUANTILES = { median: 0.5, seventy_fifth: 0.75, eighty_fifth: 0.85, nintey_fifth: 0.95 };

// Exact mean and quantiles of the number of cubes needed to clear several geometric phases in a row
// (e.g. Epic->Unique, then Unique->Legendary, then hitting the stat target).
export function cubesNeeded(ps) {
  const out = { mean: ps.reduce((a, p) => a + 1 / p, 0) };
  if (ps.length === 0) return { mean: 0, median: 0, seventy_fifth: 0, eighty_fifth: 0, nintey_fifth: 0 };
  let pmf = new Float64Array([1]); // 0 cubes with certainty before any phase
  for (const p of ps) {
    const cap = Math.min(5_000_000, pmf.length + Math.ceil(Math.log(1e-9) / Math.log(1 - p)) + 1);
    const next = new Float64Array(cap);
    for (let n = 1; n < cap; n++) next[n] = p * (n - 1 < pmf.length ? pmf[n - 1] : 0) + (1 - p) * next[n - 1];
    pmf = next;
  }
  let cdf = 0, n = 0;
  for (const [k, q] of Object.entries(QUANTILES)) {
    while (cdf < q && n < pmf.length) cdf += pmf[n++];
    out[k] = n - 1;
  }
  return out;
}

export function feePerCube(d, level) {
  const b = d.gms.fee.brackets.find(([lo, hi]) => level >= lo && level <= hi);
  return b ? b[2] * level ** 2 : 0;
}

export function runScenario(d, s) {
  const cube = resolveCube(d, s.cube);
  const item = resolveItem(d, s.item);
  const from = TIERS.indexOf(String(s.from).toLowerCase());
  const to = TIERS.indexOf(String(s.to ?? s.from).toLowerCase());
  if (from < 0 || to < 0) throw new Error("--from/--to must be rare, epic, unique or legendary");
  if (to < from) throw new Error("--to must be the same tier or higher than --from");
  const maxTier = TIERS.indexOf(cube.maxTier);
  if (to > maxTier) throw new Error(`${cube.label} cubes can't reach ${TIER_LABEL[to]} (max ${TIER_LABEL[maxTier]})`);
  const level = Number(s.level ?? 150);
  const dmt = Boolean(s.dmt);
  const want = parseWant(s.want);
  const anyLines = Object.keys(want).length === 0;

  const tierRates = [];
  for (let i = from; i < to; i++) {
    const rate = cube.tierUp[TIERS[i]] * (dmt && cube.miracleTime ? 2 : 1);
    tierRates.push({ step: `${TIER_LABEL[i]}->${TIER_LABEL[i + 1]}`, rate });
  }
  const p = anyLines ? null : targetChance(lineTables(d, cube, to, item, level), want);
  if (p === 0) throw new Error(`That target can't roll on a ${TIER_LABEL[to]} Lv. ${level} ${item} with ${cube.label} cubes`);

  const rnd = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, Math.round(v)]));
  const tierUpCubes = rnd(cubesNeeded(tierRates.map((t) => t.rate)));
  const targetCubes = rnd(cubesNeeded(anyLines ? [] : [p]));
  const exact = cubesNeeded(tierRates.map((t) => t.rate).concat(anyLines ? [] : [p]));
  const perCube = cube.price + feePerCube(d, level);
  const totalMesos = Object.fromEntries(Object.entries(exact).map(([k, v]) => [k, Math.round(v * perCube)]));
  return {
    label: s.label || null,
    cube: cube.label, item, level, from: TIER_LABEL[from], to: TIER_LABEL[to], dmt, want,
    tierRates,
    perCubeTargetChance: p,
    tierUpCubes, targetCubes, totalCubes: rnd(exact), totalMesos,
  };
}

// --- Expected results ---------------------------------------------------------------------------------------

// Compare a result with a scenario's "expect" ({p, meanCubes}): per-cube chance within 1%, mean cubes within 1
// (1% for long runs).
function checkExpected(r, e) {
  const pOk = e.p === undefined || Math.abs((r.perCubeTargetChance ?? 0) - e.p) <= 0.01 * e.p;
  const cubesOk = Math.abs(r.totalCubes.mean - e.meanCubes) <= Math.max(1, 0.01 * e.meanCubes);
  if (pOk && cubesOk) return "match";
  const p = e.p === undefined ? "" : `chance ${pct(r.perCubeTargetChance ?? 0)} vs ${pct(e.p)}, `;
  return `DIFF (${p}mean cubes ${r.totalCubes.mean} vs ${e.meanCubes})`;
}

// --- Output -------------------------------------------------------------------------------------------------

const fmtB = (m) => (m === 0 ? "0" : `${(m / 1e9).toFixed(2)}B`);
const pct = (x) => `${(x * 100).toFixed(x < 0.01 ? 3 : 2)}%`;

function describe(r) {
  const want = Object.keys(r.want).length ? Object.entries(r.want).map(([k, v]) => `${k}>=${v}`).join(", ") : "any lines";
  const lines = [];
  lines.push(`${r.label ? r.label + ": " : ""}${r.cube} cube, ${r.item} Lv.${r.level}, ${r.from} -> ${r.to}, want ${want}${r.dmt ? " (Miracle Time)" : ""}`);
  if (r.tierRates.length) {
    lines.push(`  Tier-up: ${r.tierRates.map((t) => `${t.step} ${pct(t.rate)}`).join(", ")} -> mean ${r.tierUpCubes.mean} cubes`);
  }
  if (r.perCubeTargetChance !== null) {
    lines.push(`  Target at ${r.to}: ${pct(r.perCubeTargetChance)} per cube -> mean ${r.targetCubes.mean} cubes`);
  }
  const t = r.totalCubes, m = r.totalMesos;
  lines.push(`  Total cubes: mean ${t.mean}, median ${t.median}, 75% ${t.seventy_fifth}, 85% ${t.eighty_fifth}, 95% ${t.nintey_fifth}`);
  if (m.mean > 0) {
    lines.push(`  Mesos (cube price + fee): mean ${fmtB(m.mean)}, median ${fmtB(m.median)}, 75% ${fmtB(m.seventy_fifth)}, 85% ${fmtB(m.eighty_fifth)}, 95% ${fmtB(m.nintey_fifth)}`);
  } else {
    lines.push("  Mesos: none (free cube, no fee at this level)");
  }
  if (r.expected) lines.push(`  Expected: ${r.expected}`);
  return lines.join("\n");
}

function printLines(d, s) {
  const cube = resolveCube(d, s.cube);
  const item = resolveItem(d, s.item);
  const tier = TIERS.indexOf(String(s.tier ?? s.to ?? "legendary").toLowerCase());
  const level = Number(s.level ?? 150);
  const lines = lineTables(d, cube, tier, item, level);
  console.log(`${cube.label} cube, ${TIER_LABEL[tier]} ${item} Lv.${level} (Nexon KMS table${level >= d.gms.statBump.fromLevel && level <= d.gms.statBump.toLevel ? ", +1 GMS Lv. 151+ step" : ""})`);
  lines.forEach((line, i) => {
    console.log(`  Line ${i + 1}:`);
    for (const o of [...line].sort((a, b) => b.p - a.p)) {
      const name = o.stat ? `${o.stat} ${o.value ?? ""}`.trim() : `(junk) ${o.text}`;
      const lim = o.limit >= 0 ? `  [max ${LIMITS[o.limit].max}: ${LIMITS[o.limit].family}]` : "";
      console.log(`    ${pct(o.p).padStart(8)}  ${name}${lim}`);
    }
  });
}

function printRates(d) {
  const out = {
    lineData: { source: d.kms.source, fetched: d.kms.fetched, levels: d.kms.levels },
    limits: LIMITS.map((l) => `max ${l.max}: ${l.family}`),
    cubes: {},
    fee: d.gms.fee,
    statBump: d.gms.statBump,
  };
  for (const [key, c] of Object.entries(d.gms.cubes)) {
    out.cubes[c.label] = {
      tierUp: c.tierUp, tierUpCounts: c.tierUpCounts, tierUpSource: c.tierUpSource, miracleTime: c.miracleTime,
      price: c.price, maxTier: c.maxTier, linesFrom: `KMS ${c.kmsLines}`,
      primeChancePerLine: d.kms.cubes[c.kmsLines].primeChance,
    };
  }
  console.log(JSON.stringify(out, null, 2));
}

// Warn if Nexon's page lists repeat limits other than the ones this engine applies.
function checkLimits(d) {
  for (const [name, c] of Object.entries(d.kms.cubes)) {
    const listed = c.limitsKo.filter((t) => !t.startsWith("*"));
    const known = LIMITS.map((l) => l.ko);
    const extra = listed.filter((t) => !known.includes(t));
    if (extra.length) console.error(`warning: Nexon's ${name} page lists repeat limits this engine doesn't apply: ${extra.join(", ")}`);
  }
}

function parseArgs(argv) {
  const a = {};
  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i];
    if (!tok.startsWith("--")) continue;
    const key = tok.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) a[key] = true;
    else { a[key] = a[key] && key === "want" ? `${a[key]},${next}` : next; i++; }
  }
  return a;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || process.argv.length <= 2) {
    console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n").slice(1, 15).map((l) => l.replace(/^\/\/ ?/, "")).join("\n"));
    console.log(`Items: ${["weapon", "emblem", "secondary", "forceShield", "shield", "hat", "top", "overall", "bottom", "shoes", "gloves", "cape", "belt", "shoulder", "face", "eye", "earring", "ring", "pendant", "heart"].join(", ")}; accessory = ring, badge = heart.`);
    console.log(`Cubes: glowing, bright, hard, solid, mystical (old names red, black, master, meister, occult).`);
    console.log(`--want keys: ${Object.entries(WANTS).map(([k, w]) => `\n  ${k}: ${w.desc}`).join("")}`);
    return;
  }
  const known = ["item", "cube", "from", "to", "tier", "level", "want", "dmt", "label", "batch", "json", "lines", "rates"];
  const unknown = Object.keys(args).filter((k) => !known.includes(k));
  if (unknown.length) throw new Error(`Unknown flag ${unknown.map((k) => `--${k}`).join(", ")}. See --help.`);
  const d = loadData();
  checkLimits(d);
  if (args.rates) { printRates(d); return; }
  if (args.lines) { printLines(d, args); return; }

  const scenarios = args.batch ? JSON.parse(fs.readFileSync(args.batch, "utf8")) : [args];
  const results = scenarios.map((s) => {
    try {
      const r = runScenario(d, s);
      if (s.expect) r.expected = checkExpected(r, s.expect);
      return r;
    } catch (e) {
      return { label: s.label || null, error: e.message };
    }
  });
  if (args.json) { console.log(JSON.stringify(results, null, 2)); return; }
  for (const r of results) console.log(`${r.error ? `${r.label ? r.label + ": " : ""}ERROR ${r.error}` : describe(r)}\n`);
  const checked = scenarios.filter((s) => s.expect).length;
  if (checked) {
    const matched = results.filter((r) => r.expected === "match").length;
    console.log(`${matched} of ${checked} scenarios match their expected results.`);
    if (matched < checked) process.exitCode = 1;
  }
}

const isMain = process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url));
if (isMain) {
  try { main(); } catch (e) { console.error(e.message); process.exit(1); }
}
