#!/usr/bin/env node
// Downloads Nexon Korea's official potential (cube) probability tables into data/cube_lines_kms.json, the line
// data cube_calc.mjs runs on. GMS publishes no such tables, so KMS's are the official source: GMS's Glowing,
// Bright, Hard, Solid and Mystical cubes are taken to roll lines like KMS's Red, Black, Master Craftsman's,
// Meister's and Occult cubes (see data/cube_gms.json for the GMS-only numbers: tier-up rates, prices, fees).
//
// Source pages: https://maplestory.nexon.com/Guide/OtherProbability/cube/<red|black|strange|master|artisan>
// Each page's search form (POST .../cube/GetSearchProbList) returns the three line tables for one potential
// tier, equipment slot and level. Line 2 and 3 tables already include the prime-line chance.
//
// Tables only change at Lv. 10k or 10k+1, and Lv. 120-200 and 201-250 are one block each, so one level per
// decade interior, each decade edge, 120 and 201 cover Lv. 71-250. A level with no KMS item returns nothing;
// such ranges reuse the range below and are marked "inferred".
//
// Usage: node cube_rates_fetch.mjs [--out data/cube_lines_kms.json] [--concurrency 4]
// Takes about 17 minutes (~11,000 requests; levels with no item are retried). Run it when Nexon changes the
// tables, then: node cube_calc.mjs --batch examples/cube_check_scenarios.json --check

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { useEnvProxy } from "./cube_calc.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = "https://maplestory.nexon.com/Guide/OtherProbability/cube/";
const SEARCH = BASE + "GetSearchProbList";
const MIN_LEVEL = 71;

// KMS cube page -> item id and the tiers it can roll (1 rare .. 4 legendary).
const CUBES = {
  red: { id: 5062009, tiers: [1, 2, 3, 4] },
  black: { id: 5062010, tiers: [1, 2, 3, 4] },
  strange: { id: 2711000, tiers: [1, 2] },
  master: { id: 2711003, tiers: [1, 2, 3] },
  artisan: { id: 2711004, tiers: [1, 2, 3, 4] },
};
const TIER = { 1: "rare", 2: "epic", 3: "unique", 4: "legendary" };
// Slot numbers from the page's equipment select box.
const PARTS = {
  weapon: 1, emblem: 2, secondary: 3, forceShield: 4, shield: 5, hat: 6, top: 7, overall: 8, bottom: 9, shoes: 10,
  gloves: 11, cape: 12, belt: 13, shoulder: 14, face: 15, eye: 16, earring: 17, ring: 18, pendant: 19, heart: 20,
};

// Level ranges and the levels to try for each, in order, until one returns tables.
function levelPlan() {
  const plan = [];
  for (let d = 7; d <= 11; d++) {
    if (10 * d >= MIN_LEVEL) plan.push({ lo: 10 * d, hi: 10 * d, tries: [10 * d] });
    const inner = [5, 1, 9, 2, 8, 3, 7, 4, 6].map((k) => 10 * d + k).filter((l) => l >= MIN_LEVEL);
    plan.push({ lo: Math.max(10 * d + 1, MIN_LEVEL), hi: 10 * d + 9, tries: inner });
  }
  plan.push({ lo: 120, hi: 200, tries: [120, 140, 160, 200] });
  plan.push({ lo: 201, hi: 250, tries: [201, 210, 250] });
  return plan;
}

const ENTITIES = { "&rarr;": "->", "&nbsp;": " ", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&amp;": "&" };
const text = (s) => s.replace(/<[^>]+>/g, "").replace(/&[a-z#0-9]+;/g, (e) => ENTITIES[e] ?? e).replace(/\s+/g, " ").trim();
const pct = (s) => Number(s.replace("%", ""));

async function post(form, attempt = 0) {
  try {
    const res = await fetch(SEARCH, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Requested-With": "XMLHttpRequest" },
      body: new URLSearchParams(form),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.text();
  } catch (e) {
    if (attempt >= 4) throw new Error(`${SEARCH} ${JSON.stringify(form)}: ${e.message}`);
    await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
    return post(form, attempt + 1);
  }
}

// The three line tables of one search result, as [[optionText, percent], ...] each; null if the level has no item.
function parseLines(html) {
  const lines = [];
  for (const m of html.matchAll(/<table class="cube_data[^"]*">([\s\S]*?)<\/table>/g)) {
    const rows = [];
    for (const tr of m[1].matchAll(/<tr>([\s\S]*?)<\/tr>/g)) {
      const tds = [...tr[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((t) => text(t[1]));
      if (tds.length >= 2) rows.push([tds[0], pct(tds[tds.length - 1])]);
    }
    lines.push(rows);
  }
  if (lines.length === 0 || lines.every((l) => l.length === 0)) return null;
  if (lines.length !== 3) throw new Error(`expected 3 line tables, got ${lines.length}`);
  return lines;
}

// Tier-up rates and prime-line chances from a cube's main page (KMS figures; kept for reference and --rates).
function parsePage(html) {
  const tables = [...html.matchAll(/<table class="cube_(info|grade)">([\s\S]*?)<\/table>/g)];
  const info = tables.find((t) => t[1] === "info");
  const tierUp = {};
  for (const tr of info[2].matchAll(/<tr>([\s\S]*?)<\/tr>/g)) {
    const tds = [...tr[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((t) => text(t[1]));
    if (tds.length === 2) tierUp[tds[0]] = pct(tds[1]);
  }
  const grade = tables.find((t) => t[1] === "grade");
  const rows = [...grade[2].matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map((tr) =>
    [...tr[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((t) => text(t[1])));
  // Rows: line 1, line 2 prime, line 2 non-prime, line 3 prime, line 3 non-prime; two cells per tier column.
  const body = rows.filter((r) => r.length > 0);
  const prime = {};
  const nTiers = body[0].length / 2;
  for (let i = 0; i < nTiers; i++) {
    prime[TIER[i + 1]] = [body[0], body[1], body[3]].map((r) => Number((pct(r[2 * i + 1]) / 100).toPrecision(8)));
  }
  const limitsKo = [...html.matchAll(/<div class="gray_box">([\s\S]*?)<\/div>/g)].map((m) =>
    [...m[1].matchAll(/<li>([\s\S]*?)<\/li>/g)].map((li) => text(li[1]))).flat();
  return { tierUpKms: tierUp, primeChance: prime, limitsKo };
}

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) =>
    (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : true]] : acc), []));
  const out = path.resolve(HERE, args.out || "data/cube_lines_kms.json");
  const concurrency = Number(args.concurrency || 4);
  await useEnvProxy();

  const cubes = {};
  for (const [name, c] of Object.entries(CUBES)) {
    const res = await fetch(BASE + name);
    if (!res.ok) throw new Error(`${BASE + name}: HTTP ${res.status}`);
    cubes[name] = { itemId: c.id, page: BASE + name, tiers: c.tiers.map((t) => TIER[t]), ...parsePage(await res.text()) };
  }

  const jobs = [];
  for (const [cube, c] of Object.entries(CUBES)) {
    for (const tier of c.tiers) {
      for (const [part, partNo] of Object.entries(PARTS)) {
        for (const range of levelPlan()) jobs.push({ cube, tier, part, partNo, range });
      }
    }
  }
  let next = 0, done = 0, requests = 0;
  const started = Date.now();
  async function worker() {
    while (next < jobs.length) {
      const job = jobs[next++];
      for (const lev of job.range.tries) {
        requests++;
        const lines = parseLines(await post({ nCubeItemID: CUBES[job.cube].id, nGrade: job.tier, nPartsType: job.partNo, nReqLev: lev }));
        if (lines) { job.lines = lines; job.level = lev; break; }
      }
      if (++done % 200 === 0) {
        console.error(`${done}/${jobs.length} ranges, ${requests} requests, ${Math.round((Date.now() - started) / 1000)}s`);
      }
    }
  }
  await Promise.all(Array.from({ length: concurrency }, worker));

  // Pool option texts and identical tables; index each cube/tier/slot as merged level ranges.
  const options = [], optionId = new Map(), tables = [], tableId = new Map(), index = {}, warnings = [];
  const opt = (s) => { if (!optionId.has(s)) { optionId.set(s, options.length); options.push(s); } return optionId.get(s); };
  for (const job of jobs) {
    let id = null, inferred = false;
    if (job.lines) {
      job.lines.forEach((rows, i) => {
        const sum = rows.reduce((a, r) => a + r[1], 0);
        if (Math.abs(sum - 100) > 0.05) warnings.push(`${job.cube} ${TIER[job.tier]} ${job.part} Lv.${job.level} line ${i + 1} sums to ${sum.toFixed(4)}%`);
      });
      const t = job.lines.map((rows) => rows.map(([o, p]) => [opt(o), p]));
      const key = JSON.stringify(t);
      if (!tableId.has(key)) { tableId.set(key, tables.length); tables.push(t); }
      id = tableId.get(key);
    }
    const ranges = ((index[job.cube] ??= {})[TIER[job.tier]] ??= {})[job.part] ??= [];
    if (id === null) {
      const prev = ranges[ranges.length - 1];
      if (!prev) { warnings.push(`${job.cube} ${TIER[job.tier]} ${job.part}: no table for Lv.${job.range.lo}-${job.range.hi}`); continue; }
      id = prev[2]; inferred = true;
    }
    const prev = ranges[ranges.length - 1];
    if (prev && prev[2] === id && Boolean(prev[3]) === inferred && prev[1] + 1 === job.range.lo) prev[1] = job.range.hi;
    else ranges.push(inferred ? [job.range.lo, job.range.hi, id, "inferred"] : [job.range.lo, job.range.hi, id]);
  }

  const data = {
    about: "Nexon Korea's official KMS potential probability tables, copied verbatim (option text in Korean, percent " +
      "per line). Line 2 and 3 percents already include the prime-line chance. Index: cube -> tier -> slot -> " +
      "[[fromLevel, toLevel, tableId, 'inferred'?]]; inferred ranges had no KMS item at the tried levels and reuse the range below.",
    source: "https://maplestory.nexon.com/Guide/OtherProbability/cube/ (Nexon Korea, 확률형 아이템 > 잠재능력 재설정)",
    fetched: new Date().toLocaleDateString("en-CA"),
    levels: [MIN_LEVEL, 250],
    cubes,
    options,
    tables,
    index,
  };
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const body = JSON.stringify(data, null, 1)
    .replace(/\[\s+(-?[\d.]+),\s+(-?[\d.]+)\s+\]/g, "[$1,$2]")
    .replace(/\[\s+(\d+),\s+(\d+),\s+(\d+)(,\s+"inferred")?\s+\]/g, (m, a, b, c, d) => `[${a},${b},${c}${d ? ',"inferred"' : ""}]`);
  fs.writeFileSync(out, body + "\n");
  console.error(`Wrote ${out}: ${tables.length} distinct tables, ${options.length} option texts, ${requests} requests.`);
  for (const w of warnings) console.error(`warning: ${w}`);
}

main().catch((e) => { console.error(e.message); process.exit(1); });
