#!/usr/bin/env node
// The PTY flow bench: builds the shell's tests in release, then runs each scenario of src-tauri/src/pty_bench.rs
// three times, every run in its own process, and writes median / min / max of each number.
//   node bench/pty/run.mjs bench/pty/after.json
//   node bench/pty/run.mjs bench/pty/sweep.json --sweep     the high and low marks tried against each other
// Real programs (/bin/cat, /usr/bin/yes); macOS or Linux. Nothing else heavy should run beside it.
import { spawnSync } from "node:child_process";
import { closeSync, mkdtempSync, openSync, rmSync, writeFileSync, writeSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RUNS = 3;
// sink_*: the sink stands in for the page (it takes the time itself). page_*: the sink returns at once, as the
// app's does, and a page thread draws behind it.
const SCENARIOS = ["sink_cat", "sink_yes", "sink_slow_2ms", "sink_interrupt_2ms", "echo", "page_cat", "page_yes", "page_slow_20ms", "page_interrupt_2ms", "page_interrupt_20ms"];
// (high, low) in bytes, for --sweep
const KB = 1024;
const SWEEP = [
  [128 * KB, 32 * KB],
  [256 * KB, 64 * KB],
  [512 * KB, 128 * KB],
  [1024 * KB, 64 * KB],
  [1024 * KB, 256 * KB],
  [1024 * KB, 512 * KB],
  [2048 * KB, 512 * KB],
  [4096 * KB, 1024 * KB],
];
const SWEEP_SCENARIOS = ["page_yes", "page_cat", "page_slow_20ms", "page_interrupt_2ms", "page_interrupt_20ms"];

const args = process.argv.slice(2);
const out = args.find((a) => !a.startsWith("--"));
if (!out) {
  console.error("usage: node bench/pty/run.mjs <out.json> [--sweep]");
  process.exit(2);
}
const here = path.dirname(fileURLToPath(import.meta.url));
const tauri = path.resolve(here, "../../src-tauri");

const sh = (cmd, argv) => {
  const r = spawnSync(cmd, argv, { cwd: tauri, encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : "";
};
// a copy of the sources outside git names its commit itself
const commit = process.env.OMHER_PTY_BENCH_COMMIT || `${sh("git", ["rev-parse", "--short=9", "HEAD"])}${sh("git", ["status", "--porcelain", "--", "."]) ? " +changes" : ""}`;

// build once and take the test program's path from cargo
const build = spawnSync("cargo", ["test", "--release", "--lib", "--no-run", "--message-format=json"], { cwd: tauri, encoding: "utf8", maxBuffer: 1 << 29, stdio: ["ignore", "pipe", "inherit"] });
if (build.status !== 0) process.exit(build.status ?? 1);
let exe = "";
for (const line of build.stdout.split("\n")) {
  if (!line.startsWith("{")) continue;
  const m = JSON.parse(line);
  if (m.reason === "compiler-artifact" && m.profile?.test && m.executable) exe = m.executable;
}
if (!exe) throw new Error("cargo named no test program");

// 200 MB without a newline or a tab, so the terminal passes every byte as it is
const dir = mkdtempSync(path.join(os.tmpdir(), "omher-pty-bench-"));
const file = path.join(dir, "200mb.txt");
{
  const block = Buffer.alloc(1024 * 1024);
  for (let i = 0; i < block.length; i++) block[i] = 97 + (i % 26);
  const fd = openSync(file, "w");
  for (let i = 0; i < 200; i++) writeSync(fd, block);
  closeSync(fd);
}

function one(scenario, marks) {
  const env = { ...process.env, OMHER_PTY_BENCH_ONE: scenario, OMHER_PTY_BENCH_FILE: file };
  if (marks) env.OMHER_PTY_BENCH_MARKS = marks.join(",");
  const r = spawnSync(exe, ["pty_bench::pty_bench_one", "--exact", "--ignored", "--nocapture", "--test-threads=1"], { env, encoding: "utf8", maxBuffer: 1 << 26, timeout: 40 * 60_000 });
  const line = (r.stdout ?? "").split("\n").map((l) => l.split("PTY_BENCH ")[1]).find(Boolean);
  if (!line) {
    console.error(r.stdout, r.stderr);
    throw new Error(`${scenario} gave no numbers`);
  }
  return JSON.parse(line);
}

const round = (x) => Math.round(x * 1000) / 1000;
function measure(scenario, marks) {
  const all = {};
  for (let i = 0; i < RUNS; i++) for (const [k, v] of Object.entries(one(scenario, marks))) (all[k] ??= []).push(v);
  const res = {};
  for (const [k, runs] of Object.entries(all)) {
    const s = [...runs].sort((a, b) => a - b);
    res[k] = { median: round(s[Math.floor(s.length / 2)]), min: round(s[0]), max: round(s[s.length - 1]), runs: runs.map(round) };
    console.log(`${marks ? `${marks.join("/")} ` : ""}${k}: median ${res[k].median} (min ${res[k].min}, max ${res[k].max})`);
  }
  return res;
}

const doc = {
  commit,
  machine: `${os.type()} ${os.release()} ${os.arch()}; ${os.cpus()[0]?.model ?? "?"}; ${os.cpus().length} cores; ${Math.round(os.totalmem() / 2 ** 30)} GB`,
  profile: "release",
  runs_each: RUNS,
  load_average_at_start: os.loadavg().map(round),
};
try {
  if (args.includes("--sweep")) {
    doc.sweep = SWEEP.map(([high, low]) => ({ high, low, results: Object.assign({}, ...SWEEP_SCENARIOS.map((sc) => measure(sc, [high, low]))) }));
  } else {
    doc.results = Object.assign({}, ...SCENARIOS.map((sc) => measure(sc)));
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}
doc.load_average_at_end = os.loadavg().map(round);
writeFileSync(out, `${JSON.stringify(doc, null, 2)}\n`);
console.log(`wrote ${out}`);
