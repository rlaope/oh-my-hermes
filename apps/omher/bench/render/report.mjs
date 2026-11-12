// Builds baseline.json / after.json from raw/<label>-<engine>.json files and, with --table, prints the README table.
//   node bench/render/report.mjs merge baseline   -> bench/render/baseline.json
//   node bench/render/report.mjs table baseline after
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const [cmd, ...rest] = process.argv.slice(2);
const ENGINES = ["chromium", "webkit"];
const read = (label) => {
  const out = {};
  for (const e of ENGINES) {
    // raw files are <label>-<engine>.json (one gpu setting) or <label>-<engine>-<gpu>.json
    for (const gpu of ["off", "on", "auto"]) {
      for (const f of [`${label}-${e}-${gpu}.json`, gpu === "off" ? `${label}-${e}.json` : null]) {
        if (f && existsSync(join(here, "raw", f))) (out[e] ??= {})[gpu] = JSON.parse(readFileSync(join(here, "raw", f), "utf8"));
      }
    }
  }
  return out;
};

if (cmd === "merge") {
  const label = rest[0];
  const data = read(label);
  writeFileSync(join(here, `${label}.json`), JSON.stringify({ label, note: "median [min..max] of 3 runs; Playwright-driven browsers on the vite dev server and the mock host, not the Tauri window", engines: data }, null, 2) + "\n");
  console.log("wrote", `${label}.json`, Object.keys(data));
}

if (cmd === "table") {
  const [a, b] = rest;
  const A = JSON.parse(readFileSync(join(here, `${a}.json`), "utf8")).engines;
  const B = JSON.parse(readFileSync(join(here, `${b}.json`), "utf8")).engines;
  const fmt = (s) => (s ? `${s.median} [${s.min}..${s.max}]` : "n/a");
  const pct = (x, y) => (x && y ? `${(((y.median - x.median) / x.median) * 100).toFixed(0)}%` : "");
  const rows = [];
  for (const e of ENGINES) {
    for (const gpu of Object.keys(B[e] ?? {})) {
      const base = A[e]?.off;
      const aft = B[e][gpu];
      if (!base || !aft) continue;
      for (const sc of Object.keys(aft.scenarios)) {
        const x = base.scenarios[sc], y = aft.scenarios[sc];
        if (!x) continue;
        rows.push(`| ${e} | ${sc} | ${gpu} | ${fmt(x.wallMs)} | ${fmt(y.wallMs)} | ${pct(x.wallMs, y.wallMs)} | ${fmt(x.longFrames)} | ${fmt(y.longFrames)} | ${fmt(x.maxGapMs)} | ${fmt(y.maxGapMs)} | ${sc === "D" ? `${fmt(x.echoP50)} / ${fmt(y.echoP50)}` : ""} | ${fmt(x.heapMB)} | ${fmt(y.heapMB)} |`);
      }
    }
  }
  console.log("| engine | scenario | gpu (after) | wall ms before | wall ms after | change | frames >50 ms before | after | worst frame gap ms before | after | echo p50 ms before / after (D) | heap MB before | after |");
  console.log("|---|---|---|---|---|---|---|---|---|---|---|---|---|");
  console.log(rows.join("\n"));
}
