// omher mock bridge: the same protocol as the real Python bridge (01-protocol.md), with seeded data and
// scripted turns, so every e2e test runs without Hermes. Node only, no dependencies: it carries its own
// minimal RFC 6455 WebSocket server (text frames, ping/pong, close, fragmentation).
//
//   node e2e/mock-bridge.mjs --port 5308 [--token T]
//
// Without --token it accepts `e2e` (playwright.config.ts) and `dev` (the UI's built-in default URL).
// Test-control ops (not part of the protocol): mock.calls, mock.emit {events}, mock.reset.
import http from "node:http";
import crypto from "node:crypto";

const argv = process.argv.slice(2);
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : dflt;
};
const PORT = Number(arg("port", process.env.OMHER_MOCK_PORT || 5308));
const TOKENS = new Set(arg("token", "") ? [arg("token", "")] : ["e2e", "dev"]);
const GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

const now = () => Date.now() / 1000;
const BOOT = now();
const MIN = 60;

// ---- seed data -------------------------------------------------------------------------------

const BOT_SEED = [
  { name: "kami", display_name: "Kami", is_default: false, model: "Opus 5.5", provider: "claude-proxy", description: "khope's everyday assistant", status: "online", running: true, reasoning: "high" },
  { name: "friren", display_name: "Friren", is_default: false, model: "Sonnet 5.5", provider: "claude-proxy", description: "research and reading", status: "online", running: false, reasoning: "medium" },
  { name: "default", display_name: "Hermes", is_default: true, model: "Haiku 5", provider: "claude-proxy", description: "the default profile", status: "online", running: false, reasoning: "low" },
];

const HISTORY_SEED = {
  kami: [
    ["user", "gateway 502 로그 좀 봐줄래?", 3 * 3600],
    ["assistant", "확인했어요. `/v1/responses`에서 upstream timeout이 간헐적으로 나고 있어요. 재시도 정책부터 볼게요.", 3 * 3600 - 40],
    ["user", "Thanks. Ping me when the retry fix is up.", 2 * 3600],
  ],
  friren: [
    ["user", "Summarise the Tauri 2 updater docs.", 5 * 3600],
    ["assistant", "The updater checks a signed manifest, downloads the bundle and swaps it on restart.", 5 * 3600 - 30],
  ],
  default: [["assistant", "Hi, I'm Hermes. Ask me anything.", 24 * 3600]],
};

// Away sessions are stored as offsets from "now" so the timeline always looks fresh.
const AWAY_SEED = {
  kami: [
    { id: "slack-og-dev-502", source: "slack", title: "gateway 502 on /v1/responses", place: "#og-dev", url: "slack://channel?team=T1&id=C1&thread_ts=1794186944.520669", reply: "Reading gateway logs from 14:31. Upstream resets look like keep-alive expiry.", started: 4 * MIN, last: 20, count: 14, running: true },
    { id: "discord-cron-openmaus", source: "discord", title: "OpenMausBot 조사후 브리핑", place: "#cron", url: "https://discord.com/channels/1/2", reply: "OpenMausBot은 Claude·Codex·Grok CLI를 채팅 앱으로 묶는 Electron 앱입니다. ⭐17,657, Apache-2.0입니다.", started: 3 * 3600, last: 2 * 3600, count: 6, running: false },
    { id: "discord-omh-2657", source: "discord", title: "PR #2657 review", place: "#oh-my-hermes", url: "https://discord.com/channels/1/3", started: 27 * 3600, last: 26 * 3600, count: 9, running: false },
  ],
  friren: [{ id: "telegram-reading-list", source: "telegram", title: "Reading list", started: 6 * 3600, last: 4 * 3600, count: 5, running: false }],
  default: [],
};
const PEEK_SEED = {
  "slack-og-dev-502": [
    ["user", "minji", "502s are back on /v1/responses since 14:10", 9],
    ["assistant", "", "Reading gateway logs. Upstream resets look like keep-alive expiry.", 8],
    ["user", "jun", "can we raise the pool idle timeout?", 6],
    ["assistant", "", "Trying that now, rolling to one replica first.", 4],
    ["user", "minji", "ok, watching the error rate", 2],
  ],
  "discord-cron-openmaus": [
    ["assistant", "", "Briefing: OpenMausBot ships weekly, 3 open issues, nothing blocking.", 120],
    ["user", "khope", "good, thanks", 118],
  ],
  "discord-omh-2657": [
    ["user", "rlaope", "PR #2657 is ready for review", 1600],
    ["assistant", "", "Reviewed. One blocking comment on the retry loop, otherwise fine.", 1590],
    ["user", "rlaope", "fixed, please re-check", 1570],
    ["assistant", "", "Approved.", 1560],
  ],
  "telegram-reading-list": [["user", "khope", "add the Tauri updater post", 240], ["assistant", "", "Added.", 239]],
};

const ROUTINE_SEED = {
  kami: [
    { id: "cron-repo-watch", name: "Repo watch", schedule: "Daily 09:00", next: 15 * 3600, last: -9 * 3600, status: "ok", enabled: true },
    { id: "cron-og-digest", name: "OG digest", schedule: "Weekly (Mon 09:00)", next: 6 * 24 * 3600, last: -24 * 3600, status: "ok", enabled: true },
  ],
  friren: [],
  default: [],
};

const PANEL_RUNS = {
  kami: [
    { id: "r3", command: "pytest tests/test_upstream.py -q", output: "............\n12 passed in 1.84s", exit_code: 0, cwd: "/w/gateway-keepalive", source: "tui", ago: 120 },
    { id: "r2", command: 'rg -n "keepalive|idle_timeout" gateway/', output: "gateway/upstream.py:41:    idle_timeout = 75\ngateway/upstream.py:88:    keepalive=True,", exit_code: 0, cwd: "/w/gateway-keepalive", source: "tui", ago: 300 },
    { id: "r1", command: "kubectl logs deploy/gateway --since=1h | grep -c 502", output: "37", exit_code: 0, cwd: "/w/gateway", source: "slack", ago: 900 },
    { id: "r0", command: "git push origin fix/keepalive", output: "error: failed to push some refs", exit_code: 1, cwd: "/w/gateway-keepalive", source: "tui", ago: 1800 },
  ],
  friren: [],
  default: [],
};
const PANEL_TREES = {
  kami: [
    { path: "/w/gateway-keepalive", branch: "fix/keepalive", head: "3f2c1a9e0", repo: "gateway", dirty: 2, ago: 120 },
    { path: "/w/gateway", branch: "main", head: "a91b0c2d4", repo: "gateway", dirty: 0, ago: 900 },
  ],
  friren: [],
  default: [],
};
const PANEL_DIFF = {
  "/w/gateway-keepalive": {
    scope: "uncommitted",
    files: [
      { path: "gateway/upstream.py", add: 1, del: 1 },
      { path: "tests/test_upstream.py", add: 3, del: 0 },
    ],
    patch: [
      "diff --git a/gateway/upstream.py b/gateway/upstream.py",
      "--- a/gateway/upstream.py",
      "+++ b/gateway/upstream.py",
      "@@ -38,7 +38,7 @@ class Upstream:",
      "     pool_size = 32",
      "-    idle_timeout = 75",
      "+    idle_timeout = 55  # under upstream's 60s",
      "     retries = 2",
      "diff --git a/tests/test_upstream.py b/tests/test_upstream.py",
      "--- a/tests/test_upstream.py",
      "+++ b/tests/test_upstream.py",
      "@@ -1,3 +1,6 @@",
      "+def test_idle_timeout_is_below_upstream():",
      "+    assert Upstream().idle_timeout < 60",
      "+",
    ].join("\n"),
  },
  "/w/gateway": { scope: "last commit", files: [{ path: "README.md", add: 1, del: 0 }], patch: "a91b0c2 docs: note the 60s upstream limit\n\ndiff --git a/README.md b/README.md\n@@ -1 +1,2 @@\n # gateway\n+Upstream closes idle connections after 60s." },
};

const PROVIDERS = [
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5", "Sonnet 5.5", "Haiku 5"] },
  { slug: "openai", name: "OpenAI", models: ["gpt-5.5", "gpt-5.5-mini"] },
];
const REASONING_LEVELS = ["none", "low", "medium", "high", "xhigh"];

// ---- mutable state ---------------------------------------------------------------------------

let calls = [];
let bots, history, models, turns, pending, idSeq, queues, avatars;

// What each bot has done (bots.info): sessions per place, skills, routines.
const INFO_SEED = {
  kami: { places: { slack: 78, discord: 48, cron: 15 }, first: 14 * 24 * 3600, skills: 134 },
  friren: { places: { telegram: 6 }, first: 3 * 24 * 3600, skills: 12 },
  default: { places: {}, first: null, skills: 41 },
};

function reset() {
  for (const t of Object.values(turns ?? {})) t?.timers.forEach(clearTimeout);
  bots = Object.fromEntries(BOT_SEED.map((b) => [b.name, { ...b }]));
  history = Object.fromEntries(
    Object.entries(HISTORY_SEED).map(([bot, rows]) => [
      bot,
      rows.map(([role, text, ago], i) => ({ id: `seed-${bot}-${i}`, role, text, ts: BOOT - ago })),
    ]),
  );
  models = Object.fromEntries(BOT_SEED.map((b) => [b.name, { model: b.model, provider: b.provider, reasoning: b.reasoning }]));
  turns = {};
  queues = {};
  avatars = {};
  pending = new Map();
  idSeq = 0;
  calls = [];
}
reset();

const nextId = (p) => `${p}-${++idSeq}`;
const publicBot = ({ reasoning, ...b }) => ({
  ...b,
  model: models[b.name].model,
  provider: models[b.name].provider,
  avatar_rev: avatars[b.name]?.rev ?? null,
});

// ---- WebSocket server ------------------------------------------------------------------------

const clients = new Set();

function frame(opcode, payload) {
  const len = payload.length;
  let head;
  if (len < 126) head = Buffer.from([0x80 | opcode, len]);
  else if (len < 65536) head = Buffer.from([0x80 | opcode, 126, len >> 8, len & 255]);
  else {
    head = Buffer.alloc(10);
    head[0] = 0x80 | opcode;
    head[1] = 127;
    head.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([head, payload]);
}

function sendJson(sock, obj) {
  if (!sock.destroyed && sock.writable) sock.write(frame(0x1, Buffer.from(JSON.stringify(obj))));
}
function broadcast(ev) {
  for (const c of clients) sendJson(c, ev);
}

function attach(sock, onText) {
  let buf = Buffer.alloc(0);
  let frag = null; // { opcode, parts }
  sock.on("data", (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    for (;;) {
      if (buf.length < 2) return;
      const fin = (buf[0] & 0x80) !== 0;
      const opcode = buf[0] & 0x0f;
      const masked = (buf[1] & 0x80) !== 0;
      let len = buf[1] & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) return;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) return;
        len = Number(buf.readBigUInt64BE(2));
        off = 10;
      }
      const need = off + (masked ? 4 : 0) + len;
      if (buf.length < need) return;
      let payload = buf.subarray(off + (masked ? 4 : 0), need);
      if (masked) {
        const mask = buf.subarray(off, off + 4);
        payload = Buffer.from(payload.map((b, i) => b ^ mask[i & 3]));
      }
      buf = buf.subarray(need);
      if (opcode === 0x8) {
        sock.end(frame(0x8, payload.subarray(0, 2)));
        return;
      }
      if (opcode === 0x9) {
        sock.write(frame(0xa, payload));
        continue;
      }
      if (opcode === 0xa) continue;
      if (opcode === 0x1 || opcode === 0x2) frag = { opcode, parts: [payload] };
      else if (opcode === 0x0 && frag) frag.parts.push(payload);
      else continue;
      if (fin) {
        const text = Buffer.concat(frag.parts).toString("utf8");
        frag = null;
        onText(text);
      }
    }
  });
}

const server = http.createServer((req, res) => {
  res.writeHead(426, { "content-type": "text/plain" });
  res.end("omher mock bridge: WebSocket only\n");
});

server.on("upgrade", (req, sock) => {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const key = req.headers["sec-websocket-key"];
  if (!TOKENS.has(url.searchParams.get("token") ?? "")) {
    sock.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    return;
  }
  if (!key || String(req.headers.upgrade).toLowerCase() !== "websocket") {
    sock.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    return;
  }
  const accept = crypto.createHash("sha1").update(key + GUID).digest("base64");
  sock.write(
    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  sock.setNoDelay(true);
  clients.add(sock);
  sock.on("close", () => clients.delete(sock));
  sock.on("error", () => clients.delete(sock));
  attach(sock, (text) => handleFrame(sock, text));
});

// ---- ops -------------------------------------------------------------------------------------

class OpError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function needBot(p) {
  if (typeof p.bot !== "string" || !p.bot) throw new OpError("bad_request", "missing bot");
  const b = bots[p.bot];
  if (!b) throw new OpError("unknown_bot", `no bot named ${p.bot}`);
  if (b.status === "offline") throw new OpError("bot_offline", `${p.bot} is offline`);
  return b;
}
function needStr(p, k) {
  if (typeof p[k] !== "string" || !p[k]) throw new OpError("bad_request", `missing ${k}`);
  return p[k];
}

const awayFor = (bot) =>
  (AWAY_SEED[bot] ?? [])
    .map((a) => ({
      id: a.id,
      source: a.source,
      label: a.title || `${a.source[0].toUpperCase()}${a.source.slice(1)} session`,
      title: a.title,
      started_at: now() - a.started,
      last_active: now() - a.last,
      message_count: a.count,
      running: a.running,
      url: a.url ?? null,
      place: a.place ?? null,
      last_reply: a.reply ?? null,
      last_reply_at: a.reply ? now() - a.last : null,
    }))
    .sort((x, y) => y.last_active - x.last_active)
    .slice(0, 20);

const OPS = {
  hello: () => ({ bridge: "mock", version: "0.1.0", hermes: { home: "/mock/.hermes", version: "mock" } }),
  "bots.list": () => ({ bots: Object.values(bots).map(publicBot) }),
  "chat.open": (p) => {
    const b = needBot(p);
    const m = models[b.name];
    return {
      session_id: `main-${b.name}`,
      messages: history[b.name],
      running: Boolean(turns[b.name]),
      model: m.model,
      provider: m.provider,
      reasoning: m.reasoning,
    };
  },
  "chat.send": (p) => {
    const b = needBot(p);
    const text = needStr(p, "text");
    const input_id = nextId("input");
    history[b.name].push({ id: nextId("u"), role: "user", text, ts: now() });
    if (turns[b.name]) (queues[b.name] ??= []).push(text);
    else startTurn(b.name, text);
    return { input_id };
  },
  "chat.interrupt": (p) => {
    const b = needBot(p);
    if (turns[b.name]) endTurn(b.name, "interrupted", { drop: true });
    return {};
  },
  "approval.respond": (p) => {
    const b = needBot(p);
    const id = needStr(p, "request_id");
    const choice = needStr(p, "choice");
    if (!["once", "session", "always", "deny"].includes(choice)) throw new OpError("bad_request", "bad choice");
    const wait = pending.get(id);
    if (!wait || wait.bot !== b.name || wait.kind !== "approval") throw new OpError("not_found", `no pending approval ${id}`);
    pending.delete(id);
    resumeApproval(b.name, choice);
    return {};
  },
  "clarify.respond": (p) => {
    const b = needBot(p);
    const id = needStr(p, "request_id");
    if (typeof p.answer !== "string") throw new OpError("bad_request", "missing answer");
    const wait = pending.get(id);
    if (!wait || wait.bot !== b.name || wait.kind !== "clarify") throw new OpError("not_found", `no pending clarification ${id}`);
    pending.delete(id);
    resumeClarify(b.name, p.answer);
    return {};
  },
  "elsewhere.list": (p) => ({ sessions: awayFor(needBot(p).name) }),
  "elsewhere.peek": (p) => {
    const b = needBot(p);
    const sid = needStr(p, "session_id");
    const away = awayFor(b.name).find((a) => a.id === sid);
    if (!away) throw new OpError("not_found", `no session ${sid} for ${b.name}`);
    const limit = Number.isInteger(p.limit) && p.limit > 0 ? p.limit : 4;
    const rows = (PEEK_SEED[sid] ?? []).map(([role, author, text, ago]) => ({
      role,
      ...(author ? { author } : {}),
      text: text.slice(0, 400),
      ts: now() - ago,
    }));
    return { messages: rows.slice(-limit), total: Math.max(away.message_count, rows.length) };
  },
  "bots.rename": (p) => {
    const b = needBot(p);
    if (typeof p.name !== "string") throw new OpError("bad_request", "name must be text");
    const name = p.name.split(/\s+/).filter(Boolean).join(" ");
    if (name.length > 64) throw new OpError("bad_request", `name is too long (${name.length} characters, max 64)`);
    const seed = BOT_SEED.find((x) => x.name === b.name);
    b.display_name = name || (b.name === "default" ? "Hermes" : seed?.name[0].toUpperCase() + seed?.name.slice(1));
    broadcast({ event: "bots.update", bot: b.name });
    return { display_name: b.display_name };
  },
  "bots.avatar": (p) => {
    const a = avatars[needBot(p).name];
    return { rev: a?.rev ?? null, data: a?.data ?? null };
  },
  "bots.set_avatar": (p) => {
    const b = needBot(p);
    if (p.clear === true) delete avatars[b.name];
    else {
      if (typeof p.data !== "string" || !/^data:image\/(png|jpeg|webp);base64,/.test(p.data))
        throw new OpError("bad_request", "use a PNG, JPEG or WebP picture");
      if (p.data.length > 2_700_000) throw new OpError("bad_request", "picture is larger than 2 MB");
      avatars[b.name] = { rev: ++idSeq, data: p.data };
    }
    broadcast({ event: "bots.update", bot: b.name });
    return { avatar_rev: avatars[b.name]?.rev ?? null };
  },
  "bots.info": (p) => {
    const b = needBot(p);
    const i = INFO_SEED[b.name] ?? { places: {}, first: null, skills: 0 };
    return {
      places: { ...i.places },
      first_active: i.first === null ? null : now() - i.first,
      last_active: Object.keys(i.places).length ? now() - 20 : null,
      skills: i.skills,
      routines: (ROUTINE_SEED[b.name] ?? []).length,
    };
  },
  "panel.terminal": (p) => ({
    runs: (PANEL_RUNS[needBot(p).name] ?? []).map(({ ago, ...r }) => ({ ...r, session_id: "s-" + r.id, ts: now() - ago })),
  }),
  "panel.worktrees": (p) => ({
    worktrees: (PANEL_TREES[needBot(p).name] ?? []).map(({ ago, ...w }) => ({ ...w, last: now() - ago })),
  }),
  "panel.diff": (p) => {
    const b = needBot(p);
    const w = (PANEL_TREES[b.name] ?? []).find((t) => t.path === p.path);
    if (!w) throw new OpError("not_found", "not a worktree this bot worked in");
    return { path: w.path, branch: w.branch, repo: w.repo, truncated: false, ...PANEL_DIFF[w.path] };
  },
  "routines.list": (p) => ({
    routines: (ROUTINE_SEED[needBot(p).name] ?? []).map((r) => ({
      id: r.id,
      name: r.name,
      schedule: r.schedule,
      next_run_at: now() + r.next,
      last_run_at: now() + r.last,
      last_status: r.status,
      enabled: r.enabled,
    })),
  }),
  "models.options": (p) => {
    const b = needBot(p);
    return { providers: PROVIDERS, current: { ...models[b.name] }, reasoning_levels: REASONING_LEVELS };
  },
  "chat.set_model": (p) => {
    const b = needBot(p);
    const cur = models[b.name];
    if (p.provider !== undefined && !PROVIDERS.some((x) => x.slug === p.provider)) throw new OpError("bad_request", `unknown provider ${p.provider}`);
    if (p.reasoning !== undefined && !REASONING_LEVELS.includes(p.reasoning)) throw new OpError("bad_request", `unknown reasoning level ${p.reasoning}`);
    if (p.model !== undefined && typeof p.model !== "string") throw new OpError("bad_request", "model must be a string");
    models[b.name] = {
      model: p.model ?? cur.model,
      provider: p.provider ?? cur.provider,
      reasoning: p.reasoning ?? cur.reasoning,
    };
    return { ...models[b.name] };
  },
  // ---- test control (not part of the protocol)
  "mock.calls": () => ({ calls: calls.map((c) => ({ ...c })) }),
  "mock.emit": (p) => {
    if (!Array.isArray(p.events)) throw new OpError("bad_request", "events must be an array");
    for (const ev of p.events) broadcast(ev);
    return { count: p.events.length };
  },
  "mock.reset": () => {
    reset();
    return {};
  },
};

function handleFrame(sock, text) {
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    sendJson(sock, { id: null, ok: false, error: { code: "bad_request", message: "frame is not JSON" } });
    return;
  }
  const id = msg && typeof msg === "object" && typeof msg.id === "string" ? msg.id : null;
  if (!id || typeof msg.op !== "string") {
    sendJson(sock, { id, ok: false, error: { code: "bad_request", message: "need string id and op" } });
    return;
  }
  const { id: _id, op, ...params } = msg;
  if (!op.startsWith("mock.")) calls.push({ op, params, ts: now() });
  try {
    const fn = Object.hasOwn(OPS, op) ? OPS[op] : null;
    if (!fn) throw new OpError("unknown_op", `no such op: ${op}`);
    sendJson(sock, { id, ok: true, result: fn(params) });
  } catch (e) {
    const code = e instanceof OpError ? e.code : "internal";
    sendJson(sock, { id, ok: false, error: { code, message: e?.message ?? String(e) } });
  }
}

// ---- scripted turns --------------------------------------------------------------------------

const ev = (bot, event, fields = {}) => broadcast({ event, bot, ...fields });
const hangul = /[\u3131-\u318e\uac00-\ud7a3]/;

function schedule(bot, steps) {
  const t = turns[bot];
  for (const [ms, fn] of steps) {
    const h = setTimeout(() => {
      if (turns[bot] === t) fn();
    }, ms);
    t.timers.push(h);
  }
}

function endTurn(bot, outcome, { drop = false } = {}) {
  const t = turns[bot];
  if (!t) return;
  t.timers.forEach(clearTimeout);
  for (const [id, w] of pending) if (w.bot === bot) pending.delete(id);
  delete turns[bot];
  bots[bot].running = false;
  if (drop) queues[bot] = [];
  ev(bot, "turn.end", { outcome });
  ev(bot, "bot.status", { status: bots[bot].status, running: false });
  const next = queues[bot]?.shift();
  if (next !== undefined) setTimeout(() => startTurn(bot, next), 50);
}

function say(bot, text) {
  const id = nextId("a");
  history[bot].push({ id, role: "assistant", text, ts: now() });
  ev(bot, "message", { id, text });
}

function tool(bot, tool_id, name, detail, startMs, endMs, extra = []) {
  return [
    [startMs, () => { ev(bot, "tool.start", { tool_id, name, detail }); for (const e of extra) e(); }],
    [endMs, () => ev(bot, "tool.end", { tool_id, name, ok: true, ms: endMs - startMs })],
  ];
}

function startTurn(bot, text) {
  turns[bot] = { timers: [], text };
  bots[bot].running = true;
  ev(bot, "bot.status", { status: bots[bot].status, running: true });
  ev(bot, "turn.start");
  if (text.startsWith("/approve")) return scriptApproval(bot);
  if (text.startsWith("/clarify")) return scriptClarify(bot);
  scriptNormal(bot, text);
}

function scriptNormal(bot, text) {
  const ko = hangul.test(text);
  const answer = ko
    ? `확인했어요. 로그에서 \`/v1/responses\` 502는 keep-alive 만료 때문이었고, 재시도 정책을 고쳤어요.\n\n- 원인: upstream 연결 재사용\n- 조치: idle timeout 상향`
    : `Done. The 502s on \`/v1/responses\` came from expired keep-alive connections.\n\n- Cause: upstream connection reuse\n- Fix: raised the idle timeout`;
  const parts = [answer.slice(0, 40), answer.slice(40, 90), answer.slice(90)];
  schedule(bot, [
    [80, () => ev(bot, "status", { text: "Looking into it…" })],
    [200, () => ev(bot, "thinking")],
    ...tool(bot, "tool-1", "terminal", "git log --oneline -5", 350, 700),
    ...tool(bot, "tool-2", "skill_view", "plan", 750, 950, [() => ev(bot, "skill", { name: "plan" })]),
    ...tool(bot, "tool-3", "read_file", "src/gateway/router.py", 1000, 1350),
    ...tool(bot, "tool-4", "search_files", "502 upstream", 1400, 1850),
    [1900, () => ev(bot, "thinking")],
    [2000, () => ev(bot, "delta", { text: parts[0] })],
    [2150, () => ev(bot, "delta", { text: parts[1] })],
    [2300, () => ev(bot, "delta", { text: parts[2] })],
    [2400, () => say(bot, answer)],
    [2500, () => endTurn(bot, "done")],
  ]);
}

function scriptApproval(bot) {
  const request_id = nextId("approval");
  schedule(bot, [
    [100, () => ev(bot, "status", { text: "Preparing to clean the build folder…" })],
    [300, () => {
      pending.set(request_id, { bot, kind: "approval" });
      ev(bot, "approval.request", {
        request_id,
        title: "Run shell command",
        command: "rm -rf ./build",
        choices: ["once", "session", "always", "deny"],
      });
    }],
  ]);
}

function resumeApproval(bot, choice) {
  if (choice === "deny") return endTurn(bot, "interrupted");
  schedule(bot, [
    ...tool(bot, "tool-a1", "terminal", "rm -rf ./build", 100, 500),
    [600, () => say(bot, `Cleaned the build folder (approved: ${choice}).`)],
    [700, () => endTurn(bot, "done")],
  ]);
}

function scriptClarify(bot) {
  const request_id = nextId("clarify");
  schedule(bot, [
    [100, () => ev(bot, "status", { text: "Checking what you meant…" })],
    [250, () => {
      pending.set(request_id, { bot, kind: "clarify" });
      ev(bot, "clarify.request", { request_id, question: "Which environment should I deploy to?", choices: ["staging", "production"] });
    }],
  ]);
}

function resumeClarify(bot, answer) {
  schedule(bot, [
    [100, () => say(bot, `Got it, using ${answer}.`)],
    [200, () => endTurn(bot, "done")],
  ]);
}

// ---- boot ------------------------------------------------------------------------------------

server.listen(PORT, "127.0.0.1", () => {
  console.log(`MOCK_READY ${server.address().port}`);
});
const stop = () => {
  for (const c of clients) c.destroy();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 500).unref();
};
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
