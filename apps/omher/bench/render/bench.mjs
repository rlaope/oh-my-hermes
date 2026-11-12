// Terminal render bench (not part of the e2e suite). Opens omher on the mock host, opens a terminal session and
// feeds the terminal through the real `feed()` of src/sessions/term/engine.ts.
//
//   node bench/render/bench.mjs --engine chromium|webkit --gpu off|on|auto --label NAME --out FILE [--runs 3]
//        [--only A,B,C,D] [--mb 20] [--chromium-channel chromium]
//
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
const gpu = arg("gpu", "off");
const label = arg("label", "run");
const out = arg("out", join(here, `${label}-${engineName}-${gpu}.json`));
const runs = Number(arg("runs", "3"));
const only = arg("only", "A,B,C,D").split(",");
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
  const tui = (frames) => {
    const out = ["\x1b[?1049h\x1b[?25l"];
    for (let f = 0; f < frames; f++) {
      let s = "\x1b[H";
      for (let r = 0; r < 40; r++) {
        const c = (f + r) % 200 + 16;
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
  if (name === "C") term.resize(120, 40);
  else term.resize(80, 36);
  await sleep(200);

  let chunks;
  if (name === "A") chunks = plain(mb * 1024 * 1024);
  else if (name === "B" || name === "D") chunks = colour(mb * 1024 * 1024);
  else chunks = tui(2000);
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

async function openTerminal(page) {
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
    { gpu },
  );
  // the bench needs the xterm instance: record it where the session store makes it (same on every commit)
  await page.route("**/src/sessions/sessions.ts*", async (route) => {
    const r = await route.fetch();
    const body = (await r.text()).replace("const fit = new FitAddon();", "const fit = new FitAddon(); (globalThis.__benchTerms ??= []).push(term);");
    await route.fulfill({ response: r, body });
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
  await page.locator(".xterm-rows").getByText("(mock)").first().waitFor();
}

async function heap(page, context) {
  if (engineName !== "chromium") return null;
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
  const channel = arg("chromium-channel", "");
  const browser = await type.launch(channel && engineName === "chromium" ? { channel } : {});
  const result = {
    label,
    engine: engineName,
    engineVersion: browser.version(),
    gpuSetting: gpu,
    machine: `${os.cpus()[0].model}, ${os.platform()} ${os.release()}`,
    measuredOn: "Playwright-driven browser against the vite dev server and the mock host (not the Tauri window)",
    mb,
    runs,
    scenarios: {},
  };
  // one throw-away page: vite transforms every module once, so the first load is not measured
  {
    const ctx = await browser.newContext({ baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1400, height: 1000 } });
    const p = await ctx.newPage();
    await openTerminal(p);
    await ctx.close();
  }
  for (const name of only) {
    const rs = [];
    for (let i = 0; i < runs; i++) {
      const ctx = await browser.newContext({ baseURL: `http://127.0.0.1:${PORT}`, viewport: { width: 1400, height: 1000 } });
      const p = await ctx.newPage();
      await openTerminal(p);
      const r = await p.evaluate(pageBench, { name, mb });
      r.heapMB = await heap(p, ctx);
      rs.push(r);
      console.log(label, engineName, gpu, name, i + 1, JSON.stringify(r));
      await ctx.close();
    }
    result.scenarios[name] = {
      runs: rs,
      wallMs: summary(rs, "wallMs"),
      longFrames: summary(rs, "longFrames"),
      maxGapMs: summary(rs, "maxGapMs"),
      heapMB: summary(rs, "heapMB"),
      echoP50: summary(rs, "echoP50"),
      echoP95: summary(rs, "echoP95"),
    };
  }
  await browser.close();
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
  console.log("wrote", out);
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
