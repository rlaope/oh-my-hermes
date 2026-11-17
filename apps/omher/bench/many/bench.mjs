// Many-terminals bench: what N open terminal sessions cost the page (mock host, Playwright Chromium, not the Tauri
// window). Scenarios:
//   fill  - N shell terminals, each viewed once, each fed `--mb` MiB of 120-column lines; JS heap after GC, DOM nodes
//   bg    - the same N terminals; N-1 hidden ones stream an agent-like spinner (+ a line now and then) every 100 ms
//           for `--secs`; the visible one is idle. Main-thread time (CDP Performance metrics), store updates.
// usage: node bench/many/bench.mjs --n 20 --mb 2 --secs 8 --runs 3 --label base
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";
import os from "node:os";

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, "..", "..");
const require = createRequire(join(app, "package.json"));
const pw = require("@playwright/test");
const argv = process.argv.slice(2);
const arg = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d;
};
const N = Number(arg("n", "20"));
const MB = Number(arg("mb", "2"));
const SECS = Number(arg("secs", "8"));
const RUNS = Number(arg("runs", "3"));
const LABEL = arg("label", "run");
const ENGINE = arg("engine", "chromium");
const PORT = Number(arg("port", "5391"));
const MOCK = Number(arg("mock", "5392"));

const children = [];
const waitPort = (port) =>
  new Promise((res, rej) => {
    const t0 = Date.now();
    const once = () => {
      const s = net.connect(port, "127.0.0.1");
      s.on("connect", () => (s.destroy(), res()));
      s.on("error", () => (s.destroy(), Date.now() - t0 > 90000 ? rej(new Error(`port ${port}`)) : setTimeout(once, 250)));
    };
    once();
  });
const start = (cmd, args, env) => children.push(spawn(cmd, args, { cwd: app, env: { ...process.env, ...env }, stdio: "ignore" }));
const stopAll = () => children.forEach((c) => c.kill("SIGTERM"));
process.on("exit", stopAll);
process.on("SIGINT", () => (stopAll(), process.exit(130)));

async function openN(page) {
  await page.addInitScript(() => {
    localStorage.setItem("omher.onboarded", "1");
    localStorage.setItem("omher.roster", JSON.stringify(["kami", "friren", "default", "omh-tui"]));
    for (const k of ["omher.sessions.recent", "omher.sessions.open", "omher.resume"]) localStorage.removeItem(k);
    window.__omherMockAgents = ["claude", "codex", "omh"];
  });
  await page.goto("/");
  await page.getByTestId("bot-kami").waitFor({ timeout: 90000 });
  await page.evaluate(async (n) => {
    const s = window.__omherSessions;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const ids = [];
    for (let i = 0; i < n; i++) {
      const id = s.startTerminal("shell", `/home/you/code/repo-${i % 4}`);
      ids.push(id);
      for (let k = 0; k < 200 && s.ptyOf(id) === null; k++) await sleep(10);
    }
    window.__benchIds = ids;
  }, N);
}

const pageFill = async (mb) => {
  const s = window.__omherSessions;
  const ids = window.__benchIds;
  const line = (n) => (`\x1b[32m${n}\x1b[0m ` + "agent tool result file path diff patch status build test pass ".repeat(2)).slice(0, 118) + "\r\n";
  let chunk = "";
  for (let i = 0; chunk.length < 32 * 1024; i++) chunk += line(i);
  const per = Math.ceil((mb * 1048576) / chunk.length);
  for (const id of ids) {
    const p = s.ptyOf(id);
    for (let k = 0; k < per; k++) window.__omherMockOut(p, chunk);
  }
  // wait until every terminal has parsed what it got
  await Promise.all([...(window.__omherTerms ?? [])].map((t) => new Promise((r) => t.write("", r))));
  // xterm keeps each row in a Uint32Array outside the JS heap's count: add the buffers up
  let bufBytes = 0;
  for (const t of window.__omherTerms ?? []) {
    for (const b of [t._core.buffers.normal, t._core.buffers.alt]) {
      const l = b.lines;
      for (let i = 0; i < l.length; i++) bufBytes += l.get(i)?._data?.byteLength ?? 0;
    }
  }
  return { bufMB: Math.round((bufBytes / 1048576) * 10) / 10, terms: (window.__omherTerms ?? new Set()).size, lines: [...(window.__omherTerms ?? [])].reduce((n, t) => n + t.buffer.active.length, 0) };
};

const pageBg = async (secs) => {
  const s = window.__omherSessions;
  const ids = window.__benchIds;
  const visible = ids.at(-1);
  let updates = 0;
  const off = s.subscribe(() => updates++);
  let renders = 0;
  let rendersHidden = 0;
  for (const t of window.__omherTerms ?? []) {
    const rs = t._core._renderService;
    if (rs.__wrapped) continue;
    rs.__wrapped = true;
    const orig = rs._renderRows.bind(rs);
    rs._renderRows = (a, b) => {
      if (window.__countRenders) t.element?.isConnected ? renders++ : rendersHidden++;
      return orig(a, b);
    };
  }
  window.__countRenders = true;
  let reactCommits = 0;
  const mo = new MutationObserver((l) => (reactCommits += l.filter((m) => !m.target.closest?.(".xterm")).length));
  mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
  const frames = { gaps: [], last: 0, on: true };
  const tick = (t) => {
    if (!frames.on) return;
    if (frames.last) frames.gaps.push(t - frames.last);
    frames.last = t;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  const spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";
  let n = 0;
  const t0 = performance.now();
  await new Promise((done) => {
    const iv = setInterval(() => {
      n++;
      for (const id of ids) {
        if (id === visible) continue;
        const p = s.ptyOf(id);
        let out = `\x1b[2K\r\x1b[33m${spin[n % 10]}\x1b[0m Working… (${n}s · ${n * 37} tokens · esc to interrupt)`;
        if (n % 5 === 0) out = `\x1b[2K\r  ⎿  Read src/file-${n}.ts (120 lines)\r\n` + out;
        window.__omherMockOut(p, out);
      }
      if (performance.now() - t0 >= secs * 1000) (clearInterval(iv), done());
    }, 100);
  });
  frames.on = false;
  off();
  mo.disconnect();
  window.__countRenders = false;
  const g = frames.gaps;
  return { updates, renders, rendersHidden, domMutations: reactCommits, ticks: n, longFrames: g.filter((x) => x > 50).length, maxGapMs: Math.round(Math.max(0, ...g)) };
};

const metrics = async (cdp) => Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]));

async function main() {
  start("node", ["e2e/mock-bridge.mjs", "--port", String(MOCK)], {});
  start("pnpm", ["exec", "vite", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], { VITE_OMHER_BRIDGE: `ws://127.0.0.1:${MOCK}/?token=e2e` });
  await Promise.all([waitPort(MOCK), waitPort(PORT)]);
  const browser = await (ENGINE === "webkit" ? pw.webkit : pw.chromium).launch(ENGINE === "chromium-metal" ? { channel: "chromium" } : {});
  const ctxOpts = { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1400, height: 900 } };
  { // warm vite
    const c = await browser.newContext(ctxOpts);
    await openN(await c.newPage());
    await c.close();
  }
  const out = [];
  for (let i = 0; i < RUNS; i++) {
    const ctx = await browser.newContext(ctxOpts);
    const page = await ctx.newPage();
    const cdp = ENGINE.startsWith("chromium") ? await ctx.newCDPSession(page) : null;
    if (cdp) await cdp.send("Performance.enable");
    await openN(page);
    const heap = async () => {
      if (!cdp) return null;
      await cdp.send("HeapProfiler.collectGarbage");
      return Math.round(((await cdp.send("Runtime.getHeapUsage")).usedSize / 1048576) * 10) / 10;
    };
    const heapOpen = await heap();
    const fill = await page.evaluate(pageFill, MB);
    const heapFill = await heap();
    const dom = await page.evaluate(() => ({ nodes: document.getElementsByTagName("*").length, canvases: document.querySelectorAll("canvas").length }));
    const m0 = cdp ? await metrics(cdp) : null;
    const PROF = argv.includes("--profile") && cdp;
    if (PROF) (await cdp.send("Profiler.enable"), await cdp.send("Profiler.setSamplingInterval", { interval: 200 }), await cdp.send("Profiler.start"));
    const bg = await page.evaluate(pageBg, SECS);
    if (PROF) {
      const { profile } = await cdp.send("Profiler.stop");
      const byId = new Map(profile.nodes.map((n) => [n.id, n]));
      const self = new Map();
      const dt = profile.timeDeltas;
      profile.samples.forEach((id, k) => {
        const n = byId.get(id);
        const f = n.callFrame;
        const key = `${f.functionName || "(anon)"} ${f.url.replace(/^.*\/(src|node_modules)\//, "$1/").replace(/\?.*$/, "")}:${f.lineNumber}`;
        self.set(key, (self.get(key) ?? 0) + (dt[k] ?? 0) / 1000);
      });
      const byFile = new Map();
      for (const [k, v] of self) {
        const file = k.split(" ")[1]?.split(":")[0] ?? "?";
        byFile.set(file, (byFile.get(file) ?? 0) + v);
      }
      console.log("TOPFN", JSON.stringify([...self].sort((a, b) => b[1] - a[1]).slice(0, 25).map(([k, v]) => [k, Math.round(v)])));
      console.log("TOPFILE", JSON.stringify([...byFile].sort((a, b) => b[1] - a[1]).slice(0, 20).map(([k, v]) => [k, Math.round(v)])));
      const parent = new Map();
      for (const n of profile.nodes) for (const c of n.children ?? []) parent.set(c, n.id);
      const chains = new Map();
      profile.samples.forEach((id, k) => {
        const n = byId.get(id);
        if (!/createRow|_measure|jsxDEV/.test(n.callFrame.functionName)) return;
        const names = [];
        for (let p = id; p !== undefined && names.length < 14; p = parent.get(p)) {
          const f = byId.get(p).callFrame;
          if (f.functionName) names.push(f.functionName);
        }
        const key = names.join(" < ");
        chains.set(key, (chains.get(key) ?? 0) + (dt[k] ?? 0) / 1000);
      });
      console.log("CHAINS", JSON.stringify([...chains].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => [k, Math.round(v)])));
    }
    const m1 = cdp ? await metrics(cdp) : null;
    const d = (k) => (m0 && m1 ? Math.round((m1[k] - m0[k]) * 1000) : null);
    const r = { run: i + 1, heapOpenMB: heapOpen, heapFillMB: heapFill, ...fill, ...dom, ...bg, scriptMs: d("ScriptDuration"), taskMs: d("TaskDuration"), layoutMs: d("LayoutDuration"), styleMs: d("RecalcStyleDuration"), layouts: m0 && m1 ? m1.LayoutCount - m0.LayoutCount : null };
    console.log(LABEL, JSON.stringify(r));
    out.push(r);
    await ctx.close();
  }
  await browser.close();
  const med = (k) => {
    const v = out.map((r) => r[k]).filter((x) => typeof x === "number").sort((a, b) => a - b);
    return v.length ? { median: v[Math.floor(v.length / 2)], min: v[0], max: v.at(-1) } : null;
  };
  const summary = { label: LABEL, engine: ENGINE, n: N, mb: MB, secs: SECS, runs: RUNS, load: os.loadavg()[0].toFixed(1), measuredOn: "Playwright browser + vite dev + mock host (not the Tauri window)" };
  for (const k of ["heapOpenMB", "heapFillMB", "bufMB", "terms", "lines", "renders", "rendersHidden", "domMutations", "nodes", "canvases", "updates", "scriptMs", "taskMs", "layoutMs", "styleMs", "layouts", "longFrames", "maxGapMs"]) summary[k] = med(k);
  mkdirSync(join(here, "raw"), { recursive: true });
  writeFileSync(join(here, "raw", `${LABEL}-${ENGINE}.json`), JSON.stringify({ summary, runs: out }, null, 2));
  console.log("SUMMARY", JSON.stringify(summary));
  stopAll();
  process.exit(0);
}
main().catch((e) => (console.error(e), stopAll(), process.exit(1)));
