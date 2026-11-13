// Builds baseline.json (the seam engine) and after.json (this branch's engine, gpu off / on / auto) from the paired
// run in raw/final-<engine>-<mode>.json, and prints the README tables.
//   node bench/render/report.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ENGINES = ["webkit", "chromium-metal", "chromium"];
const SCEN = ["A", "B", "C", "C2", "C3", "D"];
const raw = (e, m) => JSON.parse(readFileSync(join(here, "raw", `final-${e}-${m}.json`), "utf8"));

const note = "median [min..max] of 3 runs, 20 MB for A, B and D; modes run round-robin in one process; Playwright-driven browsers on the vite dev server and the mock host, not the Tauri window";
const base = { label: "baseline", note, engineOf: "seam commit f9fab5d17 (no add-ons, standard renderer)", engines: {} };
const after = { label: "after", note, engineOf: "this branch's engine", engines: {} };
for (const e of ENGINES) {
  base.engines[e] = raw(e, "seam");
  after.engines[e] = Object.fromEntries(["off", "on", "auto"].map((m) => [m, raw(e, m)]));
}
writeFileSync(join(here, "baseline.json"), JSON.stringify(base, null, 2) + "\n");
writeFileSync(join(here, "after.json"), JSON.stringify(after, null, 2) + "\n");

const med = (s) => (s ? s.median : null);
const f0 = (x) => (x === null || x === undefined ? "n/a" : String(Math.round(x)));
const f1 = (x) => (x === null || x === undefined ? "n/a" : String(Math.round(x * 10) / 10));
const pct = (a, b) => (a && b ? `${b >= a ? "+" : ""}${Math.round(((b - a) / a) * 100)}%` : "");
const cell = (r, sc) => {
  const s = r.scenarios[sc];
  return `${f0(med(s.wallMs))} ms, ${f0(med(s.longFrames))} slow, worst ${f0(med(s.maxGapMs))}`;
};
let out = "";
for (const e of ENGINES) {
  const b = base.engines[e];
  const { off, on, auto } = after.engines[e];
  out += `\n**${e}** ${b.engineVersion}, ${b.machine}, load average ${b.loadAvgAtStart} at start; \`gpu: auto\` drew with: ${auto.scenarios.A.runs[0].renderer}\n\n`;
  out += "| scenario | before (seam) | after, gpu off | change | after, gpu auto (default) | change | after, gpu on | change |\n|---|---|---|---|---|---|---|---|\n";
  for (const sc of SCEN) {
    out += `| ${sc} | ${cell(b, sc)} | ${cell(off, sc)} | ${pct(med(b.scenarios[sc].wallMs), med(off.scenarios[sc].wallMs))} | ${cell(auto, sc)} | ${pct(med(b.scenarios[sc].wallMs), med(auto.scenarios[sc].wallMs))} | ${cell(on, sc)} | ${pct(med(b.scenarios[sc].wallMs), med(on.scenarios[sc].wallMs))} |\n`;
  }
  out += `\nTyping echo (D), median feed-to-frame ms / p95, and JS heap after the run:\n\n| | before (seam) | gpu off | gpu auto | gpu on |\n|---|---|---|---|---|\n`;
  const echo = (r) => `${f1(med(r.scenarios.D.echoP50))} / ${f1(med(r.scenarios.D.echoP95))}`;
  out += `| echo p50 / p95 | ${echo(b)} | ${echo(off)} | ${echo(auto)} | ${echo(on)} |\n`;
  const heap = (r) => (med(r.scenarios.B.heapMB) === null ? "n/a" : `${f1(med(r.scenarios.B.heapMB))} MB`);
  out += `| heap after B | ${heap(b)} | ${heap(off)} | ${heap(auto)} | ${heap(on)} |\n`;
}
console.log(out);
