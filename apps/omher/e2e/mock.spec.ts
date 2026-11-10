// API-level test of the mock bridge (no page): Node's global WebSocket talks the protocol directly.
import { expect, test } from "@playwright/test";

const MOCK = Number(process.env.OMHER_MOCK_PORT || 5308);
const URL = (token: string) => `ws://127.0.0.1:${MOCK}/?token=${token}`;

type Ev = { event: string; bot: string; [k: string]: any };

class Client {
  ws!: WebSocket;
  events: Ev[] = [];
  private seq = 0;
  private waiting = new Map<string, (m: any) => void>();
  private watchers: (() => void)[] = [];

  static async open(token = "e2e"): Promise<Client> {
    const c = new Client();
    c.ws = new WebSocket(URL(token));
    c.ws.onmessage = (m) => {
      const msg = JSON.parse(String(m.data));
      if (msg.event) {
        c.events.push(msg);
        c.watchers.slice().forEach((w) => w());
      } else if (msg.id && c.waiting.has(msg.id)) {
        c.waiting.get(msg.id)!(msg);
        c.waiting.delete(msg.id);
      }
    };
    await new Promise<void>((res, rej) => {
      c.ws.onopen = () => res();
      c.ws.onerror = () => rej(new Error("websocket error"));
    });
    return c;
  }

  req(op: string, params: Record<string, unknown> = {}): Promise<any> {
    const id = `t${++this.seq}`;
    return new Promise((res) => {
      this.waiting.set(id, res);
      this.ws.send(JSON.stringify({ id, op, ...params }));
    });
  }
  async ok(op: string, params: Record<string, unknown> = {}) {
    const r = await this.req(op, params);
    expect(r.ok, JSON.stringify(r)).toBe(true);
    return r.result;
  }
  waitFor(pred: (e: Ev) => boolean, ms = 8000): Promise<Ev> {
    return new Promise((res, rej) => {
      const check = () => {
        const hit = this.events.find(pred);
        if (hit) {
          this.watchers = this.watchers.filter((w) => w !== check);
          clearTimeout(timer);
          res(hit);
        }
      };
      const timer = setTimeout(() => {
        this.watchers = this.watchers.filter((w) => w !== check);
        rej(new Error(`timed out; saw ${this.events.map((e) => e.event).join(",")}`));
      }, ms);
      this.watchers.push(check);
      check();
    });
  }
  close() {
    this.ws.close();
  }
}

test.describe.configure({ mode: "serial" });

let c: Client;
test.beforeEach(async () => {
  c = await Client.open();
  await c.ok("mock.reset");
  c.events.length = 0;
});
test.afterEach(() => c.close());

test("hello, bots and seeded data", async () => {
  const hello = await c.ok("hello");
  expect(hello).toMatchObject({ bridge: "mock", version: "0.1.0" });
  const { bots } = await c.ok("bots.list");
  expect(bots.map((b: any) => [b.name, b.display_name])).toEqual([["kami", "Kami"], ["friren", "Friren"], ["default", "Hermes"], ["omh-tui", "OMH TUI"]]);
  expect(bots[0]).toMatchObject({ model: "Opus 5.5", provider: "claude-proxy", running: true, status: "online" });

  const chat = await c.ok("chat.open", { bot: "kami" });
  expect(chat.messages.length).toBeGreaterThanOrEqual(2);
  expect(chat.messages.length).toBeLessThanOrEqual(7); // the mention answer and the three link-chip messages included
  expect(chat.messages[0]).toMatchObject({ role: "user" });
  expect(chat).toMatchObject({ model: "Opus 5.5", provider: "claude-proxy", running: false });

  const { sessions } = await c.ok("elsewhere.list", { bot: "kami" });
  expect(sessions.map((s: any) => [s.source, s.place, s.title])).toEqual([
    ["slack", "#og-dev", "gateway 502 on /v1/responses"],
    ["discord", "#cron", "OpenMausBot 조사후 브리핑"],
    ["discord", "#oh-my-hermes", "PR #2657 review"],
  ]);
  expect(sessions.every((s: any) => typeof s.url === "string" && s.url)).toBe(true);
  expect(sessions[0].running).toBe(true);
  expect(sessions.every((s: any) => s.label)).toBe(true);

  const peek = await c.ok("elsewhere.peek", { bot: "kami", session_id: sessions[0].id });
  expect(peek.messages).toHaveLength(4);
  expect(peek.total).toBeGreaterThan(4);

  // link chips: channel names by id, as the bridge reads them from the bot's own sessions
  const { places } = await c.ok("links.places", { bot: "kami" });
  expect(places.slack).toMatchObject({ C0BLC924P1P: "#docs-agent" });
  expect(places.discord).toEqual({ "1544259371528232980": "#cron" });
  expect((await c.ok("links.places", { bot: "friren" })).places).toEqual({ slack: {}, discord: {} });

  const { routines } = await c.ok("routines.list", { bot: "kami" });
  expect(routines.map((r: any) => [r.name, r.schedule])).toEqual([["Repo watch", "Daily 09:00"], ["OG digest", "Weekly (Mon 09:00)"]]);

  const opts = await c.ok("models.options", { bot: "kami" });
  expect(opts.reasoning_levels).toEqual(["none", "low", "medium", "high", "xhigh"]);
  const set = await c.ok("chat.set_model", { bot: "kami", reasoning: "low" });
  expect(set).toMatchObject({ model: "Opus 5.5", reasoning: "low" });
});

test("errors are replies, not crashes", async () => {
  expect((await c.req("nope")).error.code).toBe("unknown_op");
  expect((await c.req("chat.open", { bot: "ghost" })).error.code).toBe("unknown_bot");
  expect((await c.req("chat.send", { bot: "kami" })).error.code).toBe("bad_request");
  c.ws.send("not json");
  await c.ok("hello"); // still alive
});

test("a wrong token is refused", async () => {
  const bad = new WebSocket(URL("wrong"));
  const outcome = await new Promise<string>((res) => {
    bad.onopen = () => res("open");
    bad.onerror = () => res("refused");
    bad.onclose = () => res("refused");
  });
  expect(outcome).toBe("refused");
});

test("chat.send plays the scripted turn", async () => {
  const { input_id } = await c.ok("chat.send", { bot: "kami", text: "check the gateway logs" });
  expect(input_id).toBeTruthy();
  await c.waitFor((e) => e.event === "turn.end");
  const names = c.events.map((e) => e.event);
  expect(names[0]).toBe("bot.status");
  expect(names).toContain("turn.start");
  expect(names).toContain("status");
  expect(names.filter((n) => n === "tool.start")).toHaveLength(4);
  expect(names.filter((n) => n === "tool.end")).toHaveLength(4);
  expect(names.filter((n) => n === "skill")).toEqual(["skill"]);
  expect(c.events.find((e) => e.event === "skill")!.name).toBe("plan");
  expect(names.filter((n) => n === "delta").length).toBeGreaterThanOrEqual(2);
  const msg = c.events.find((e) => e.event === "message")!;
  const streamed = c.events.filter((e) => e.event === "delta").map((e) => e.text).join("");
  expect(msg.text).toBe(streamed);
  expect(c.events.find((e) => e.event === "turn.end")).toMatchObject({ bot: "kami", outcome: "done" });
  expect(names.indexOf("turn.start")).toBeLessThan(names.indexOf("tool.start"));
  expect(names.indexOf("message")).toBeLessThan(names.indexOf("turn.end"));
  for (const t of c.events.filter((e) => e.event === "tool.start")) {
    expect(c.events.some((e) => e.event === "tool.end" && e.tool_id === t.tool_id)).toBe(true);
  }

  const chat = await c.ok("chat.open", { bot: "kami" });
  expect(chat.messages.at(-2)).toMatchObject({ role: "user", text: "check the gateway logs" });
  expect(chat.messages.at(-1)).toMatchObject({ role: "assistant", id: msg.id });
});

test("approval: deny ends the turn interrupted, with no tool.end", async () => {
  await c.ok("chat.send", { bot: "kami", text: "/approve clean up" });
  const ask = await c.waitFor((e) => e.event === "approval.request");
  expect(ask).toMatchObject({ bot: "kami", command: "rm -rf ./build" });
  expect(ask.choices).toContain("deny");
  await c.ok("approval.respond", { bot: "kami", request_id: ask.request_id, choice: "deny" });
  const end = await c.waitFor((e) => e.event === "turn.end");
  expect(end.outcome).toBe("interrupted");
  await new Promise((r) => setTimeout(r, 800));
  expect(c.events.some((e) => e.event === "tool.end")).toBe(false);
  expect(c.events.filter((e) => e.event === "turn.end")).toHaveLength(1);
  expect((await c.req("approval.respond", { bot: "kami", request_id: ask.request_id, choice: "deny" })).error.code).toBe("not_found");
});

test("approval: allow runs the command and finishes", async () => {
  await c.ok("chat.send", { bot: "kami", text: "/approve" });
  const ask = await c.waitFor((e) => e.event === "approval.request");
  await c.ok("approval.respond", { bot: "kami", request_id: ask.request_id, choice: "once" });
  const end = await c.waitFor((e) => e.event === "turn.end");
  expect(end.outcome).toBe("done");
  expect(c.events.some((e) => e.event === "tool.end")).toBe(true);
});

test("clarify asks, then continues on the answer", async () => {
  await c.ok("chat.send", { bot: "friren", text: "/clarify" });
  const q = await c.waitFor((e) => e.event === "clarify.request");
  expect(q).toMatchObject({ bot: "friren", choices: ["staging", "production"] });
  await c.ok("clarify.respond", { bot: "friren", request_id: q.request_id, answer: "staging" });
  const msg = await c.waitFor((e) => e.event === "message");
  expect(msg.text).toContain("staging");
  await c.waitFor((e) => e.event === "turn.end");
});

test("interrupt ends a running turn", async () => {
  await c.ok("chat.send", { bot: "kami", text: "long job" });
  await c.waitFor((e) => e.event === "tool.start");
  await c.ok("chat.interrupt", { bot: "kami" });
  const end = await c.waitFor((e) => e.event === "turn.end");
  expect(end.outcome).toBe("interrupted");
  await new Promise((r) => setTimeout(r, 600));
  expect(c.events.some((e) => e.event === "message")).toBe(false);
});

test("mock.calls records chat.send without any session id; mock.emit broadcasts", async () => {
  await c.ok("chat.send", { bot: "default", text: "hello there" });
  await c.ok("elsewhere.list", { bot: "kami" });
  const { calls } = await c.ok("mock.calls");
  const sends = calls.filter((x: any) => x.op === "chat.send");
  expect(sends).toHaveLength(1);
  expect(sends[0].params).toEqual({ bot: "default", text: "hello there" });
  expect(Object.keys(sends[0].params).some((k) => /session/i.test(k))).toBe(false);
  expect(calls.map((x: any) => x.op)).toEqual(["chat.send", "elsewhere.list"]);

  await c.ok("mock.emit", { events: [{ event: "elsewhere.update", bot: "kami" }] });
  await c.waitFor((e) => e.event === "elsewhere.update");

  await c.ok("mock.reset");
  expect((await c.ok("mock.calls")).calls).toEqual([]);
});
