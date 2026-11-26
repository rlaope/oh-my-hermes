// Slash commands typed while a bot chat's turn runs, as Claude Code does them mid-turn (measured on 2.1.332): /usage
// and /status run at once beside the turn (chat.command) and their answer shows above the running answer; /model
// opens the header's model picker; every other command (and /model with Hermes' own flags) waits in the steer queue
// for the turn's end, where its ↵ sends it now (one interrupt), as Claude Code's ctrl+x ctrl+s does.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createStore, type BridgeLike } from "./store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";
import { OPEN_MODEL_PICKER } from "../lib/modelPickerEvent";

const T0 = 1_800_000_000_000;
const tick = () => new Promise((r) => setTimeout(r, 0));

function fake() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, unknown> }[] = [];
  const bridge: BridgeLike = {
    connect: async () => statusH?.("open"),
    onAny: (h) => ((anyH = h), () => {}),
    onStatus: (h) => ((statusH = h), () => {}),
    request: (async (op: string, params: Record<string, unknown>) => {
      calls.push({ op, params });
      switch (op) {
        case "hello":
          return { bridge: "mock", version: "0", hermes: { home: "/h" } };
        case "bots.list":
          return { bots: [{ name: "kami", display_name: "kami", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false }] };
        case "chat.open":
          return { session_id: "s-kami", messages: [], running: false, model: "m", provider: "p", reasoning: "high" };
        case "elsewhere.list":
          return { sessions: [] };
        case "routines.list":
          return { routines: [] };
        case "chat.send":
          return { input_id: "i" };
        case "chat.steer":
          return { status: "rejected" };
        default:
          return {};
      }
    }) as BridgeLike["request"],
  };
  return { bridge, calls, emit: (ev: BridgeEvent) => anyH!(ev), ops: (op: string) => calls.filter((c) => c.op === op).map((c) => c.params) };
}

async function busy() {
  const f = fake();
  let clock = T0;
  const store = createStore(f.bridge, { now: () => (clock += 10) });
  await store.actions.init();
  f.emit({ event: "turn.start", bot: "kami" });
  return { f, store, a: store.actions, chat: () => store.getState().chats.kami! };
}

describe("a slash command typed during a turn", () => {
  // node has EventTarget and CustomEvent but no window: the picker's event goes to a stand-in for it
  let opened: string[];
  const onOpen = (e: Event) => opened.push((e as CustomEvent<string>).detail);
  beforeEach(() => {
    opened = [];
    vi.stubGlobal("window", new EventTarget());
    window.addEventListener(OPEN_MODEL_PICKER, onOpen);
  });
  afterEach(() => {
    window.removeEventListener(OPEN_MODEL_PICKER, onOpen);
    vi.unstubAllGlobals();
  });

  it("runs /usage and /status at once beside the turn: nothing is queued, sent or interrupted", async () => {
    for (const typed of ["/usage", "/status", "/USAGE", "/usage reset"]) {
      const { f, a, chat } = await busy();
      await a.send(typed);
      await tick();
      expect(f.ops("chat.command")).toEqual([{ bot: "kami", text: typed }]);
      expect(f.ops("chat.send")).toEqual([]);
      expect(f.ops("chat.interrupt")).toEqual([]);
      expect(chat().queue ?? []).toEqual([]);
      expect(chat().turn).toBeTruthy();
    }
  });

  it("shows the command's answer above the running answer and leaves what streams alone", async () => {
    const { f, a, chat } = await busy();
    f.emit({ event: "delta", bot: "kami", text: "half an answer" });
    await a.send("/usage");
    f.emit({ event: "command.output", bot: "kami", id: "u1", text: "Session tokens: 1,234 in" });
    f.emit({ event: "command.output", bot: "kami", id: "u1", text: "Session tokens: 1,234 in" }); // a replay adds nothing
    const answers = () => chat().items.flatMap((i) => (i.kind === "assistant" ? [i.text] : []));
    expect(answers()).toEqual(["Session tokens: 1,234 in"]);
    expect(chat().turn?.streaming).toBe("half an answer");
    f.emit({ event: "message", bot: "kami", id: "m1", text: "the whole answer" });
    expect(answers()).toEqual(["Session tokens: 1,234 in", "the whole answer"]);
  });

  it("opens the model picker for a bare /model and sends nothing", async () => {
    const { f, a, chat } = await busy();
    await a.send("/model");
    expect(opened).toEqual(["kami"]);
    expect(f.calls.filter((c) => c.op.startsWith("chat.") && c.op !== "chat.open")).toEqual([]);
    expect(chat().queue ?? []).toEqual([]);
  });

  it("queues every other command, /model with an argument too, as before", async () => {
    for (const typed of ["/context", "/help", "/compress", "/export", "/model gpt-5.4 --global", "/myskill go"]) {
      const { f, a, chat } = await busy();
      await a.send(typed);
      await tick();
      expect(f.ops("chat.command")).toEqual([]);
      expect(f.ops("chat.send")).toEqual([]);
      expect(chat().queue?.length).toBe(1);
      expect(opened).toEqual([]);
    }
  });

  it("sends /usage as a message when no turn runs, as before", async () => {
    const { f, a } = await busy();
    f.emit({ event: "turn.end", bot: "kami", outcome: "done" });
    await tick();
    await a.send("/usage");
    await tick();
    expect(f.ops("chat.command")).toEqual([]);
    expect(f.ops("chat.send").map((p) => p.text)).toEqual(["/usage"]);
  });

  it("the queued command's ↵ stops the turn once and sends it first when the turn ends", async () => {
    const { f, a, chat } = await busy();
    await a.send("/context");
    await a.send("after it");
    const [first] = chat().queue ?? [];
    await a.queueSendNow(first);
    expect(f.ops("chat.interrupt")).toEqual([{ bot: "kami" }]);
    f.emit({ event: "turn.end", bot: "kami", outcome: "interrupted" });
    await tick();
    await tick();
    expect(f.ops("chat.send").map((p) => p.text)[0]).toBe("/context");
  });

  it("runs /usage at once in a thread's turn too, with the thread named", async () => {
    const { f, a } = await busy();
    f.emit({ event: "turn.start", bot: "kami", session: "t1" } as BridgeEvent);
    await a.threadSend("kami", "t1", "/status");
    await tick();
    expect(f.ops("chat.command")).toEqual([{ bot: "kami", session: "t1", text: "/status" }]);
  });

  it("an older bridge without chat.command says so as an error and queues nothing", async () => {
    const f = fake();
    const request = f.bridge.request;
    f.bridge.request = (async (op: string, params: Record<string, unknown>) => {
      if (op === "chat.command") throw { code: "unsupported", message: "this Hermes cannot run a command during a turn" };
      return (request as (o: string, p: Record<string, unknown>) => Promise<unknown>)(op, params);
    }) as BridgeLike["request"];
    let clock = T0;
    const store = createStore(f.bridge, { now: () => (clock += 10) });
    await store.actions.init();
    f.emit({ event: "turn.start", bot: "kami" });
    await store.actions.send("/usage");
    await tick();
    expect(store.getState().lastError).toMatch(/cannot run a command during a turn/);
    expect(store.getState().chats.kami?.queue ?? []).toEqual([]);
  });
});

describe("the ↵ of a queued command", () => {
  it("never steers it into the answer: it stops the turn once and the command goes first", async () => {
    const { f, a, chat } = await busy();
    await a.send("/context");
    const [id] = chat().queue ?? [];
    await a.queueSteer(id);
    expect(f.ops("chat.steer")).toEqual([]);
    expect(f.ops("chat.interrupt")).toEqual([{ bot: "kami" }]);
    f.emit({ event: "turn.end", bot: "kami", outcome: "interrupted" });
    await tick();
    await tick();
    expect(f.ops("chat.send").map((p) => p.text)).toEqual(["/context"]);
  });
});

describe("a mid-turn command's answer in the timeline", () => {
  it("is no answer of the turn: the typing bubble stays and no reply quote takes it", async () => {
    const { awaitingFirstToken } = await import("../chat/parts/Typing");
    const { quoteFor } = await import("../chat/parts/answers");
    const { f, a, chat } = await busy();
    await a.send("one more thing"); // a second message: the running answer will quote both
    f.emit({ event: "command.output", bot: "kami", id: "u1", text: "Session tokens", command: "/usage" } as BridgeEvent);
    const items = chat().items;
    const cmd = items.findIndex((i) => i.kind === "assistant" && i.command === "/usage");
    expect(cmd).toBeGreaterThan(-1);
    expect(awaitingFirstToken(chat())).toBe(true);
    expect(quoteFor(items, cmd)).toBeNull();
  });
});
