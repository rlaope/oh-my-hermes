// Terminal render bench (not part of the e2e suite). Opens omher on the mock host, opens a terminal session and
// feeds the terminal through the real `feed()` of src/sessions/term/engine.ts.
//
//   node bench/render/bench.mjs --engine chromium|chromium-metal|webkit --modes seam,off,on,auto --label NAME [--runs 3]
//        [--only A,B,C,C2,C3,D] [--mb 20]
//
// Modes run round-robin inside one process (run 1 of each mode, then run 2 ...), so machine load hits them equally:
//   seam  = the engine of the seam commit f9fab5d17 (no add-ons, standard renderer), served in place of engine.ts
//   off|on|auto = the current engine with that `gpu` setting
// `chromium` is Playwright's headless shell: its WebGL is SwiftShader (software). `chromium-metal` is the full
// Chromium build (channel chromium), whose WebGL is ANGLE on Metal (the GPU). `webkit` is Playwright WebKit.
// Raw numbers go to raw/<label>-<engine>-<mode>.json. C2 is C run twice in the page, the second pass measured.
//
// C3 is C with 6 foreground colours instead of 200 (a real TUI's palette; C is the worst case for a glyph atlas).
// Scenarios: A 20 MB plain 80-column lines; B 20 MB colour-heavy output (SGR on every word); C full-screen TUI redraw
// (alt screen, 120x40, 2,000 frames); D typing echo (one char every 16 ms while B streams, feed -> next frame after
// xterm took it). Per run: wall ms until the write callback of the last chunk, frames over 50 ms (rAF gaps), JS heap.
// Output is fed in 32 KB chunks with at most 1 MB in flight (the next chunk goes when `done` of an earlier one ran),
// the way delivery credit paces a real program. Numbers are from a browser driven by Playwright against the vite dev
// server, never from the Tauri window. Run it under the heavy lock, nothing else running.
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
const engineName = arg("engine", "chromium");
const modes = arg("modes", "off").split(",");
const label = arg("label", "run");
const runs = Number(arg("runs", "3"));
const only = arg("only", "A,B,C,C2,C3,D").split(",");
const mb = Number(arg("mb", "20"));
const PORT = Number(arg("port", process.env.OMHER_PORT || 5385));
const MOCK = Number(arg("mock", process.env.OMHER_MOCK_PORT || 5386));

const children = [];
const waitPort = (port) =>
  new Promise((res, rej) => {
    const t0 = Date.now();
    const tryOnce = () => {
      const s = net.connect(port, "127.0.0.1");
      s.on("connect", () => (s.destroy(), res()));
      s.on("error", () => (s.destroy(), Date.now() - t0 > 60000 ? rej(new Error(`port ${port}`)) : setTimeout(tryOnce, 250)));
    };
    tryOnce();
  });
const start = (cmd, args, env) => {
  const c = spawn(cmd, args, { cwd: app, env: { ...process.env, ...env }, stdio: "ignore" });
  children.push(c);
  return c;
};
const stopAll = () => children.forEach((c) => c.kill("SIGTERM"));
process.on("exit", stopAll);
process.on("SIGINT", () => (stopAll(), process.exit(130)));

// ---- page side ---------------------------------------------------------------------------------
const pageBench = async ({ name, mb, rows120 }) => {
  const eng = await import("/src/sessions/term/engine.ts");
  const term = globalThis.__benchTerms.at(-1);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const CH = 32 * 1024;
  const WINDOW = 32;
  const words = "agent tool result file path diff patch status build test pass fail run read write edit search plan".split(" ");
  const chunksOf = (lines) => {
    const out = [];
    let cur = "";
    for (const l of lines) {
      cur += l;
      if (cur.length >= CH) (out.push(cur), (cur = ""));
    }
    if (cur) out.push(cur);
    return out;
  };
  const plain = (bytes) => {
    const lines = [];
    let n = 0, total = 0;
    while (total < bytes) {
      const l = (`line ${n++} ` + "lorem ipsum dolor sit amet consectetur ".repeat(3)).slice(0, 79).padEnd(79, ".") + "\r\n";
      lines.push(l);
      total += l.length;
    }
    return chunksOf(lines);
  };
  const colour = (bytes) => {
    const lines = [];
    let n = 0, total = 0;
    while (total < bytes) {
      let l = "";
      for (let w = 0; w < 9; w++) {
        const c = (n * 7 + w * 31) % 216 + 16;
        l += w % 3 === 0 ? `\x1b[1;38;5;${c}m${words[(n + w) % words.length]}\x1b[0m ` : w % 3 === 1 ? `\x1b[38;2;${(c * 3) % 256};${(c * 5) % 256};${(c * 11) % 256};48;5;${(c % 8) + 232}m${words[(n * 3 + w) % words.length]}\x1b[0m ` : `\x1b[2;3;4m${words[(n + w * 5) % words.length]}\x1b[0m `;
      }
      l += "\r\n";
      n++;
      lines.push(l);
      total += l.length;
    }
    return chunksOf(lines);
  };
  const tui = (frames, colours = 200) => {
    const out = ["\x1b[?1049h\x1b[?25l"];
    for (let f = 0; f < frames; f++) {
      let s = "\x1b[H";
      for (let r = 0; r < 40; r++) {
        const c = (f + r) % colours + 16;
        s += `\x1b[${r + 1};1H\x1b[38;5;${c}m` + (`frame ${f} row ${r} ` + "█▓▒░ box ─│┌┐└┘ ".repeat(8)).slice(0, 118).padEnd(118, " ") + "\x1b[0m\x1b[K";
        if (r % 8 === 0) s += `\x1b[${r + 1};100H\x1b[7m ${f % 100} \x1b[0m`;
      }
      out.push(s);
    }
    out.push("\x1b[?1049l\x1b[?25h");
    return out;
  };

  const frames = { gaps: [], on: false, last: 0, n: 0 };
  const tick = (t) => {
    if (!frames.on) return;
    if (frames.last) frames.gaps.push(t - frames.last);
    frames.last = t;
    frames.n++;
    requestAnimationFrame(tick);
  };
  const frameStart = () => ((frames.gaps = []), (frames.last = 0), (frames.n = 0), (frames.on = true), requestAnimationFrame(tick));
  const frameStop = () => (frames.on = false);

  const feedAll = (chunks, mark) =>
    new Promise((res) => {
      let i = 0, inflight = 0, done = 0;
      const order = [];
      const pump = () => {
        while (i < chunks.length && inflight < WINDOW) {
          const k = i++;
          inflight++;
          eng.feed(term, chunks[k], () => {
            inflight--;
            done++;
            order.push(k);
            if (done === chunks.length) res(order);
            else pump();
          });
        }
      };
      pump();
    });

  term.reset();
  if (name === "C" || name === "C2" || name === "C3") term.resize(120, 40);
  else term.resize(80, 36);
  await sleep(200);

  let chunks;
  if (name === "A") chunks = plain(mb * 1024 * 1024);
  else if (name === "B" || name === "D") chunks = colour(mb * 1024 * 1024);
  else if (name === "C3") chunks = tui(2000, 6);
  else chunks = tui(2000);
  if (name === "C2") {
    // a first, unmeasured pass: glyphs and colours are cached when the measured one starts
    await feedAll(chunks);
    await sleep(300);
  }
  await sleep(100);

  const echo = [];
  let typing = null;
  const raf = () => new Promise((r) => requestAnimationFrame(() => r(performance.now())));
  frameStart();
  const t0 = performance.now();
  if (name === "D") {
    typing = setInterval(() => {
      const sent = performance.now();
      eng.feed(term, "x", async () => {
        const shown = await raf();
        echo.push(shown - sent);
      });
    }, 16);
  }
  const order = await feedAll(chunks);
  const wall = performance.now() - t0;
  if (typing) clearInterval(typing);
  await sleep(100);
  frameStop();
  const inOrder = order.every((v, i) => v === i);
  const gaps = frames.gaps;
  const sorted = [...echo].sort((a, b) => a - b);
  const pick = (p) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] : null);
  const res = {
    wallMs: Math.round(wall),
    longFrames: gaps.filter((g) => g > 50).length,
    maxGapMs: Math.round(Math.max(0, ...gaps)),
    frames: frames.n,
    doneInOrder: inOrder && order.length === chunks.length,
    renderer: eng.rendererInUse(),
    canvas: !!document.querySelector(".term-host canvas"),
    bytes: chunks.reduce((n, c) => n + c.length, 0),
    bufferLines: term.buffer.active.length,
    echoN: echo.length,
    echoP50: pick(0.5) === null ? null : Math.round(pick(0.5) * 10) / 10,
    echoP95: pick(0.95) === null ? null : Math.round(pick(0.95) * 10) / 10,
  };
  term.reset();
  return res;
};

// ---- node side ---------------------------------------------------------------------------------
const median = (a) => {
  const s = [...a].sort((x, y) => x - y);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const summary = (rs, key) => {
  const v = rs.map((r) => r[key]).filter((x) => typeof x === "number");
  return v.length ? { median: median(v), min: Math.min(...v), max: Math.max(...v) } : null;
};

async function openTerminal(page, mode) {
  await page.addInitScript(
    ({ gpu }) => {
      localStorage.setItem("omher.onboarded", "1");
      localStorage.removeItem("omher.sessions.recent");
      localStorage.removeItem("omher.sessions.open");
      localStorage.removeItem("omher.resume");
      localStorage.setItem("omher.term", JSON.stringify({ gpu }));
      window.__omherPickFolder = "/Users/you/code/web-app";
      window.__omherMockAgents = ["claude", "codex", "omh"];
    },
    { gpu: mode === "seam" ? "off" : mode },
  );
  // the bench needs the xterm instance: record it where the session store makes it (same on every commit)
  await page.route("**/src/sessions/sessions.ts*", async (route) => {
    const r = await route.fetch();
    const body = (await r.text()).replace("const fit = new FitAddon();", "const fit = new FitAddon(); (globalThis.__benchTerms ??= []).push(term);");
    await route.fulfill({ response: r, body });
  });
  // `seam`: the engine of the seam commit (seam-engine.ts, served by vite) stands in for the current one
  if (mode === "seam")
    await page.route("**/src/sessions/term/engine.ts*", async (route) => {
      const r = await route.fetch({ url: `http://127.0.0.1:${PORT}/bench/render/seam-engine.ts` });
      await route.fulfill({ response: r });
    });
  await page.goto("/");
  await page.getByTestId("bot-kami").waitFor();
  await page.getByTestId("session-new").click();
  await page.getByTestId("session-agent-claude").click();
  await page.getByTestId("session-folder").click();
  await page.getByTestId("session-choose").click();
  await page.getByTestId("session-way-terminal").click();
  await page.getByTestId("session-go").click();
  await page.getByTestId("terminal").waitFor();
  // the banner, read from xterm's buffer (a GPU-drawn terminal has no text in the page)
  await page.waitForFunction(() => {
    const t = globalThis.__benchTerms?.at(-1);
    if (!t) return false;
    for (let n = 0; n < 5; n++) if (t.buffer.active.getLine(n)?.translateToString(true).includes("(mock)")) return true;
    return false;
  });
}

async function heap(page, context) {
  if (!engineName.startsWith("chromium")) return null;
  const cdp = await context.newCDPSession(page);
  await cdp.send("HeapProfiler.collectGarbage");
  const h = await cdp.send("Runtime.getHeapUsage");
  await cdp.detach();
  return Math.round((h.usedSize / 1048576) * 10) / 10;
}

async function main() {
  start("node", ["e2e/mock-bridge.mjs", "--port", String(MOCK)], {});
  start("pnpm", ["exec", "vite", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], { VITE_OMHER_BRIDGE: `ws://127.0.0.1:${MOCK}/?token=e2e` });
  await Promise.all([waitPort(MOCK), waitPort(PORT)]);
  const type = engineName === "webkit" ? pw.webkit : pw.chromium;
  const browser = await type.launch(engineName === "chromium-metal" ? { channel: "chromium" } : {});
  const meta = {
    label,
    engine: engineName,
    engineVersion: browser.version(),
    machine: `${os.cpus()[0].model}, ${os.platform()} ${os.release()}`,
    loadAvgAtStart: os.loadavg()[0].toFixed(1),
    measuredOn: "Playwright-driven browser against the vite dev server and the mock host (not the Tauri window)",
    mb,
    runs,
  };
  const ctxOpts = { baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1400, height: 1000 } };
  // one throw-away page per mode: vite transforms every module once, so the first load is not measured
  for (const mode of modes) {
    const ctx = await browser.newContext(ctxOpts);
    await openTerminal(await ctx.newPage(), mode);
    await ctx.close();
  }
  const results = Object.fromEntries(modes.map((m) => [m, { ...meta, mode: m, scenarios: {} }]));
  for (const name of only) {
    const rs = Object.fromEntries(modes.map((m) => [m, []]));
    // round-robin: run i of every mode before run i+1, so machine load hits the modes equally
    for (let i = 0; i < runs; i++) {
      for (const mode of modes) {
        const ctx = await browser.newContext(ctxOpts);
        const p = await ctx.newPage();
        await openTerminal(p, mode);
        const r = await p.evaluate(pageBench, { name, mb });
        r.heapMB = await heap(p, ctx);
        rs[mode].push(r);
        console.log(label, engineName, mode, name, i + 1, JSON.stringify(r));
        await ctx.close();
      }
    }
    for (const mode of modes) {
      const r = rs[mode];
      results[mode].scenarios[name] = {
        runs: r,
        wallMs: summary(r, "wallMs"),
        longFrames: summary(r, "longFrames"),
        maxGapMs: summary(r, "maxGapMs"),
        heapMB: summary(r, "heapMB"),
        echoP50: summary(r, "echoP50"),
        echoP95: summary(r, "echoP95"),
      };
    }
  }
  await browser.close();
  mkdirSync(join(here, "raw"), { recursive: true });
  for (const mode of modes) writeFileSync(join(here, "raw", `${label}-${engineName}-${mode}.json`), JSON.stringify(results[mode], null, 2) + "\n");
  console.log("wrote", modes.map((m) => `${label}-${engineName}-${m}.json`).join(" "));
}

main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => {
    stopAll();
    setTimeout(() => process.exit(process.exitCode ?? 0), 300);
  });
