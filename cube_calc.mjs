#!/usr/bin/env node
// Runs MathBro's cubing calculator (https://brendonmay.github.io/cubingCalculator/) headlessly.
// The calculator's own JS files are evaluated in a sandbox, so results match the website exactly.
// Nothing from the site is re-implemented here. Files come from a download cache (~/.cache/maplestory-cubing,
// refreshed with --refresh) or, when there's no cache and no network (e.g. Claude Desktop's sandbox),
// from an optional local vendor/ folder next to this script (not committed: the calculator has no license).
//
// Usage:
//   node cube_calc.mjs --item accessory --cube bright --from epic --to legendary --level 140 --want percStat=21
//   node cube_calc.mjs --batch scenarios.json [--json]
//   node cube_calc.mjs --rates
//   node cube_calc.mjs --refresh          (re-download the calculator files)

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const BASE_URL = "https://brendonmay.github.io/cubingCalculator/";
const FILES = ["cubeRates.js", "getProbability.js", "statistics.js", "cubes.js"];
const VENDOR_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "vendor");  // optional offline copy, not in the repo
const WRITE_CACHE = process.env.CUBECALC_CACHE || path.join(os.homedir(), ".cache", "maplestory-cubing");
let CACHE_DIR = WRITE_CACHE;

// GMS 2025+ cube names -> the calculator's internal names.
const CUBE_ALIASES = {
  mystical: "occult", occult: "occult",
  hard: "master", master: "master",
  solid: "meister", meister: "meister",
  glowing: "red", red: "red",
  bright: "black", black: "black",
};
const CUBE_LABEL = { occult: "Mystical", master: "Hard", meister: "Solid", red: "Glowing", black: "Bright" };
const TIERS = { rare: 0, epic: 1, unique: 2, legendary: 3 };
const TIER_LABEL = ["Rare", "Epic", "Unique", "Legendary"];
const ITEM_TYPES = ["accessory", "badge", "belt", "bottom", "cape", "emblem", "gloves", "hat", "heart",
  "overall", "top", "secondary", "shoes", "shoulder", "weapon"];

const hasAll = (dir) => FILES.every((f) => fs.existsSync(path.join(dir, f)));

async function ensureFiles(refresh) {
  if (!refresh) {
    for (const dir of [WRITE_CACHE, VENDOR_DIR]) {
      if (hasAll(dir)) { CACHE_DIR = dir; return; }
    }
  }
  let dest = WRITE_CACHE;
  try {
    fs.mkdirSync(dest, { recursive: true });
    fs.accessSync(dest, fs.constants.W_OK);
  } catch {
    dest = path.join(os.tmpdir(), "maplestory-cubing");
    fs.mkdirSync(dest, { recursive: true });
  }
  try {
    for (const f of FILES) {
      const res = await fetch(BASE_URL + f);
      if (!res.ok) throw new Error(`Failed to download ${f}: HTTP ${res.status}`);
      fs.writeFileSync(path.join(dest, f), await res.text());
    }
    CACHE_DIR = dest;
  } catch (e) {
    if (!hasAll(VENDOR_DIR)) throw e;
    console.error(`Download failed (${e.message}); using the bundled copy in ${VENDOR_DIR}.`);
    CACHE_DIR = VENDOR_DIR;
  }
}

function loadCalculator() {
  const quiet = () => {};
  const ctx = vm.createContext({
    console: { log: quiet, table: quiet, group: quiet, groupCollapsed: quiet, groupEnd: quiet, warn: quiet },
  });
  for (const f of FILES) {
    vm.runInContext(fs.readFileSync(path.join(CACHE_DIR, f), "utf8"), ctx, { filename: f });
  }
  const api = vm.runInContext(
    "({ getProbability, getTierCosts, geoDistrQuantile, cubingCost, emptyInputObject, tier_rates, prime_line_rates, maxCubeTier })",
    ctx,
  );
  const header = fs.readFileSync(path.join(CACHE_DIR, "cubeRates.js"), "utf8").split("\n", 1)[0];
  api.lineDataDate = header.replace(/^\/\/\s*/, "");
  return api;
}

function parseWant(want) {
  // "percStat=21,lineBoss=1" or an object {percStat: 21}
  if (!want) return {};
  if (typeof want === "object") return want;
  const out = {};
  for (const part of String(want).split(/[,&]/).map((s) => s.trim()).filter(Boolean)) {
    const [k, v] = part.split(/[=+]/);
    out[k] = (out[k] || 0) + Number(v);
  }
  return out;
}

function runScenario(calc, s) {
  const cube = CUBE_ALIASES[String(s.cube).toLowerCase()];
  if (!cube) throw new Error(`Unknown cube "${s.cube}". Use one of: ${Object.keys(CUBE_ALIASES).join(", ")}`);
  const item = String(s.item).toLowerCase();
  if (!ITEM_TYPES.includes(item)) throw new Error(`Unknown item "${s.item}". Use one of: ${ITEM_TYPES.join(", ")}`);
  const from = TIERS[String(s.from).toLowerCase()];
  const to = TIERS[String(s.to ?? s.from).toLowerCase()];
  if (from === undefined || to === undefined) throw new Error("--from/--to must be rare, epic, unique or legendary");
  if (to < from) throw new Error("--to must be the same tier or higher than --from");
  if (to > calc.maxCubeTier[cube]) {
    throw new Error(`${CUBE_LABEL[cube]} cubes can't reach ${TIER_LABEL[to]} (max ${TIER_LABEL[calc.maxCubeTier[cube]]})`);
  }
  if (to > from && calc.tier_rates[cube][to - 1] === undefined) {
    throw new Error(`${CUBE_LABEL[cube]} cube has no tier-up rate for ${TIER_LABEL[to - 1]} -> ${TIER_LABEL[to]}`);
  }
  const level = Number(s.level ?? 150);
  const dmt = Boolean(s.dmt);
  const want = parseWant(s.want);
  for (const k of Object.keys(want)) {
    if (!(k in calc.emptyInputObject)) {
      throw new Error(`Unknown --want key "${k}". Valid: ${Object.keys(calc.emptyInputObject).join(", ")}`);
    }
  }
  const anyStats = Object.keys(want).length === 0;
  if (!anyStats && level < 71) throw new Error("Stat targets need item level 71+ (calculator limit)");

  const input = Object.assign({}, calc.emptyInputObject, want);
  const p = anyStats ? 1 : calc.getProbability(to, input, item, cube, level);
  const tier = calc.getTierCosts(from, to, cube, dmt);
  const stat = calc.geoDistrQuantile(p);
  const keys = ["mean", "median", "seventy_fifth", "eighty_fifth", "nintey_fifth"];
  const statCubes = {}, total = {}, mesos = {};
  for (const k of keys) {
    statCubes[k] = anyStats ? 0 : Math.round(stat[k]);
    total[k] = statCubes[k] + tier[k];
    mesos[k] = calc.cubingCost(cube, level, total[k]);
  }
  const tierRates = [];
  for (let i = from; i < to; i++) tierRates.push({ step: `${TIER_LABEL[i]}->${TIER_LABEL[i + 1]}`, rate: (dmt ? 2 : 1) * calc.tier_rates[cube][i] });

  // With one phase (a single tier-up, or a stat target at the current tier) the numbers above are exactly
  // what the website shows. With several phases the website adds up each phase's percentiles, which is not
  // the percentile of the total, so replace them with the exact distribution of the summed phases.
  const phases = tierRates.map((t) => t.rate).concat(anyStats ? [] : [p]);
  const siteMethod = phases.length > 1 ? { totalCubes: { ...total }, totalMesos: { ...mesos } } : undefined;
  if (phases.length > 1) {
    const exact = sumOfGeometrics(phases);
    for (const k of keys) {
      total[k] = exact[k];
      mesos[k] = calc.cubingCost(cube, level, total[k]);
    }
  }
  return {
    label: s.label || null,
    cube: CUBE_LABEL[cube], item, level, from: TIER_LABEL[from], to: TIER_LABEL[to], dmt, want,
    tierRates,
    perCubeTargetChance: anyStats ? null : p,
    tierUpCubes: tier, targetCubes: statCubes, totalCubes: total, totalMesos: mesos,
    ...(siteMethod ? { siteMethod } : {}),
  };
}

// Exact mean and quantiles of the number of cubes needed to clear several geometric phases in a row
// (e.g. Epic->Unique, then Unique->Legendary, then hitting the stat target).
function sumOfGeometrics(ps) {
  const quantiles = { median: 0.5, seventy_fifth: 0.75, eighty_fifth: 0.85, nintey_fifth: 0.95 };
  const maxN = 1_000_000;
  let pmf = new Float64Array([1]); // 0 cubes with certainty before any phase
  for (const p of ps) {
    const cap = Math.min(maxN, pmf.length + Math.ceil(Math.log(1e-9) / Math.log(1 - p)) + 1);
    const next = new Float64Array(cap);
    for (let n = 1; n < cap; n++) next[n] = p * (n - 1 < pmf.length ? pmf[n - 1] : 0) + (1 - p) * next[n - 1];
    pmf = next;
  }
  const out = { mean: Math.round(ps.reduce((a, p) => a + 1 / p, 0)) };
  let cdf = 0, n = 0;
  for (const [k, q] of Object.entries(quantiles)) {
    while (cdf < q && n < pmf.length) cdf += pmf[n++];
    out[k] = n - 1;
  }
  return out;
}

const fmtB = (m) => (m === 0 ? "0" : `${(m / 1e9).toFixed(2)}B`);
const pct = (x) => `${(x * 100).toFixed(x < 0.01 ? 3 : 2)}%`;

function describe(r) {
  const want = Object.keys(r.want).length ? Object.entries(r.want).map(([k, v]) => `${k}>=${v}`).join(", ") : "any lines";
  const lines = [];
  lines.push(`${r.label ? r.label + ": " : ""}${r.cube} cube, ${r.item} Lv.${r.level}, ${r.from} -> ${r.to}, want ${want}${r.dmt ? " (DMT)" : ""}`);
  if (r.tierRates.length) {
    lines.push(`  Tier-up: ${r.tierRates.map((t) => `${t.step} ${pct(t.rate)}`).join(", ")} -> mean ${r.tierUpCubes.mean} cubes`);
  }
  if (r.perCubeTargetChance !== null) {
    lines.push(`  Target at ${r.to}: ${pct(r.perCubeTargetChance)} per cube -> mean ${r.targetCubes.mean} cubes`);
  }
  const t = r.totalCubes, m = r.totalMesos;
  lines.push(`  Total cubes: mean ${t.mean}, median ${t.median}, 75% ${t.seventy_fifth}, 85% ${t.eighty_fifth}, 95% ${t.nintey_fifth}`);
  if (m.mean > 0) {
    lines.push(`  Mesos (cube price + reveal fee): mean ${fmtB(m.mean)}, median ${fmtB(m.median)}, 75% ${fmtB(m.seventy_fifth)}, 85% ${fmtB(m.eighty_fifth)}, 95% ${fmtB(m.nintey_fifth)}`);
  } else {
    lines.push("  Mesos: not priced (this cube isn't sold for mesos)");
  }
  return lines.join("\n");
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

async function main() {
  const args = parseArgs(process.argv.slice(2));
  await ensureFiles(Boolean(args.refresh));
  const calc = loadCalculator();

  if (args.rates) {
    const out = { lineDataDate: calc.lineDataDate, tierUpRates: {}, primeLineRates: {} };
    for (const [k, v] of Object.entries(calc.tier_rates)) out.tierUpRates[CUBE_LABEL[k]] = v;
    for (const [k, v] of Object.entries(calc.prime_line_rates)) out.primeLineRates[CUBE_LABEL[k]] = v;
    console.log(JSON.stringify(out, null, 2));
    return;
  }
  if (args.refresh && !args.item && !args.batch) { console.log(`Refreshed calculator files in ${CACHE_DIR}`); return; }

  const scenarios = args.batch ? JSON.parse(fs.readFileSync(args.batch, "utf8")) : [args];
  const results = scenarios.map((s) => {
    try { return runScenario(calc, s); } catch (e) { return { label: s.label || null, error: e.message }; }
  });
  if (args.json) { console.log(JSON.stringify(results, null, 2)); return; }
  for (const r of results) console.log(r.error ? `${r.label ? r.label + ": " : ""}ERROR ${r.error}` : describe(r), "\n");
}

main().catch((e) => { console.error(e.message); process.exit(1); });
