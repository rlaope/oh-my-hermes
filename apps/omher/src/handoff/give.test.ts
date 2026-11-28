// Give to <bot> on a handoff card (rule 56) through the store: the answer goes as plain text on both paths, a main
// chat's and a thread's, so a skill token in the other bot's answer never becomes a command, and a Reply chip the
// person left set stays theirs.
import { describe, expect, it } from "vitest";
import { createStore, type BridgeLike, type HandoffItem } from "../state/store";
import type { BridgeEvent } from "../lib/protocol";
import type { BridgeStatus } from "../lib/bridge";
import { en } from "../i18n/en";
import { ja } from "../i18n/ja";
import { ko } from "../i18n/ko";
import { zh } from "../i18n/zh";

const T0 = 1_800_000_000_000;
const tick = () => new Promise((r) => setTimeout(r, 0));

function fake() {
  let anyH: ((ev: BridgeEvent) => void) | null = null;
  let statusH: ((s: BridgeStatus) => void) | null = null;
  const calls: { op: string; params: Record<string, any> }[] = [];
  let refuse = false;
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
          return { bots: ["kami", "friren"].map((name) => ({ name, display_name: name === "kami" ? "Kami" : "Friren", is_default: false, model: "m", provider: "p", description: "", status: "online", running: false })) };
        case "chat.open":
          return { session_id: `s-${params.bot}`, messages: [{ id: "a1", role: "assistant", text: "Retry three times.", ts: T0 / 1000 - 60 }], running: false, model: "m", provider: "p", reasoning: "high" };
        case "thread.create":
          return { thread: "th1", title: params.title ?? "", cwd: "", started_at: 1, running: false, needs: false, message_count: 0 };
        case "skills.list":
          return { skills: [{ name: "deploy", description: "ship it", category: "" }] };
        case "chat.steer":
          return { status: "rejected" };
        case "chat.send":
          if (refuse) throw { code: "bot_offline", message: "bot is offline" };
          return { input_id: "i" };
        case "elsewhere.list":
          return { sessions: [] };
        case "routines.list":
          return { routines: [] };
        case "models.options":
          return { providers: [], current: { model: "m", provider: "p", reasoning: "high" }, reasoning_levels: [] };
        default:
          return {};
      }
    }) as BridgeLike["request"],
  };
  return { bridge, calls, emit: (ev: BridgeEvent) => anyH!(ev), refuse: (v: boolean) => (refuse = v) };
}

/** Kami's answer `a1` in chat `chat` handed to Friren's thread th1, whose turn answered `answer`: the card is done. */
async function doneCard(answer: string, chat = "kami") {
  const f = fake();
  let clock = T0;
  const store = createStore(f.bridge, { now: () => (clock += 10) });
  await store.actions.init();
  await store.actions.skills("kami");
  if (chat !== "kami") store.dispatch({ type: "chat.opened", bot: chat, res: { session_id: "k1", messages: [{ id: "a1", role: "assistant", text: "Retry three times.", ts: T0 / 1000 - 60 }], running: false, model: "m", provider: "p", reasoning: "" }, now: T0 });
  await store.actions.startTaskThread("friren", "From Kami: x", "Handoff from omher: …", { chat, message: "a1" });
  f.emit({ event: "turn.start", bot: "friren", session: "th1" });
  f.emit({ event: "message", bot: "friren", session: "th1", id: "f1", text: answer });
  f.emit({ event: "turn.end", bot: "friren", session: "th1", outcome: "done" });
  const card = () => store.getState().chats[chat].items.find((i): i is HandoffItem => i.kind === "handoff")!;
  expect(card().phase).toBe("done");
  const sends = () => f.calls.filter((c) => c.op === "chat.send" && c.params.bot === "kami").map((c) => c.params);
  return { f, store, card, sends };
}

describe("the handoff strings", () => {
  it("Give reads as giving back, never as the chip's hand to, and a thread is the app's own word for one", () => {
    for (const [lang, d] of Object.entries({ en, ko, ja, zh })) {
      expect(d["handoff.give"], lang).not.toBe(d["handoff.chip"]);
      expect(d["handoff.give"], lang).not.toBe(d["handoff.action"]);
    }
    expect(ja["handoff.give"]).toBe("{bot} に返す");
    expect(zh["handoff.give"]).toBe("交回 {bot}");
    const zhHandoff = Object.entries(zh).filter(([k]) => k.startsWith("handoff."));
    expect(zhHandoff.filter(([, v]) => v.includes("话题"))).toEqual([]);
    expect(zh["thread.untitled"]).toContain("线程");
    expect(zh["handoff.open"]).toContain("线程");
  });
});

describe("Give to <bot>", () => {
  it("a main chat: the wire is the plain text, a $skill in the answer is not hoisted, and the Reply chip stays set", async () => {
    const { store, card, sends } = await doneCard("$deploy now, then check the logs.");
    const chip = { session_id: "slack-1", source: "slack", place: "#og-dev", kind: "thread" as const };
    store.actions.setReplyTo(chip, "kami");
    await store.actions.handoffGive("kami", card().id);
    expect(sends()).toEqual([{ bot: "kami", text: "Answer from Friren:\n\n$deploy now, then check the logs." }]);
    expect(store.getState().replyTo.kami).toEqual(chip);
    const row = store.getState().chats.kami.items.find((i) => i.kind === "user" && i.text.startsWith("Answer from Friren:"));
    expect(row).toMatchObject({ kind: "user" });
    expect(row && "sent" in row ? row.sent : undefined).toBeUndefined();
    expect(card().given).toBe(row?.id);
  });

  it("a thread: the same plain text, with the thread as session", async () => {
    const { store, card, sends } = await doneCard("$deploy it.", "fold:kami:k1");
    await store.actions.handoffGive("fold:kami:k1", card().id);
    expect(sends()).toEqual([{ bot: "kami", session: "k1", text: "Answer from Friren:\n\n$deploy it." }]);
    expect(card().given).toBeTruthy();
  });

  it("a busy chat: steered in as a typed message, held when Hermes refuses the steer; deleting that row offers Give again", async () => {
    const { f, store, card, sends } = await doneCard("$deploy now.");
    f.emit({ event: "turn.start", bot: "kami" });
    await store.actions.handoffGive("kami", card().id);
    await tick();
    expect(f.calls.filter((c) => c.op === "chat.steer").map((c) => c.params.text)).toEqual(["Answer from Friren:\n\n$deploy now."]);
    expect(sends()).toEqual([]);
    const row = card().given!;
    expect(store.getState().chats.kami.queue).toEqual([row]);
    store.actions.queueDelete(row, "kami");
    expect(card().given).toBeUndefined();
    expect(sends()).toEqual([]);
  });

  it("a refused send offers Give again", async () => {
    const { f, store, card } = await doneCard("Five seconds.");
    f.refuse(true);
    await store.actions.handoffGive("kami", card().id);
    await tick();
    expect(card().given).toBeUndefined();
    f.refuse(false);
    await store.actions.handoffGive("kami", card().id);
    expect(card().given).toBeTruthy();
  });
});
