// The SESSIONS store's side of the harness fixes (QA H4, H5, H7): what the shell says about a program that never
// answers in chat mode, a Codex thread that is gone, and a model picked mid-turn reaches the chat and the header as
// the person should see it.
import { expect, test } from "vitest";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import type { ChatEvent, ChatInput, SessionHost } from "./host";

const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };

function setup(agent: "claude" | "codex" | "omo") {
  (globalThis as { localStorage?: unknown }).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const sinks = new Map<number, (e: ChatEvent) => void>();
  const inputs: ChatInput[] = [];
  let next = 0;
  const host = {
    kind: "mock",
    reset: async () => {},
    agents: async () => [{ id: agent, label: agent, mode: "chat", path: `/bin/${agent}` }],
    home: async () => "/w",
    pickFolder: async () => null,
    start: async () => 99,
    write: async () => {},
    resize: async () => {},
    close: async () => {},
    chatStart: async (_a: string, _c: string, on: (e: ChatEvent) => void) => {
      const id = ++next;
      sinks.set(id, on);
      return id;
    },
    chatInput: async (_id: number, i: ChatInput) => {
      inputs.push(i);
      if (i.kind === "send") sinks.get(1)!({ event: "turn.start" });
    },
    chatClose: async () => {},
  } as unknown as SessionHost;
  const store = createStore(bridge);
  const ss = createSessions(host, () => store);
  return { ss, store, emit: (e: ChatEvent) => sinks.get(1)!(e), inputs };
}

async function started(agent: "claude" | "codex" | "omo") {
  const t = setup(agent);
  await t.ss.loadAgents();
  const id = t.ss.draft(agent);
  t.ss.setDraft(id, { cwd: "/w/proj" });
  await t.ss.start(id, "hi");
  const key = t.ss.chatKey(id)!;
  return { ...t, id, chat: () => t.store.getState().chats[key]!, rec: () => t.ss.getState().list.find((r) => r.id === id)! };
}

test("H4: an agent that never answers in chat mode ends the message and the session with a plain reason", async () => {
  const t = await started("omo");
  expect(t.chat().turn).not.toBeNull();
  const raw = "OmO did not answer in chat mode; it may be an old version: update it, then Restart.";
  // what the shell sends when the start deadline passes (agent_chat.rs)
  t.emit({ event: "session.error", kind: "no_chat_mode", message: raw });
  t.emit({ event: "turn.end", outcome: "error", error: raw });
  t.emit({ event: "exit", code: null, error: raw });
  expect(t.chat().turn).toBeNull();
  const why = "OmO did not answer in chat mode; it may be an old version: npm i -g omo-ai";
  expect(t.chat().lastTurn!.outcome).toBe("error");
  // the reason is said once, by the Ended line beside Restart: the failed turn does not repeat it
  expect(t.chat().lastTurn!.error).toBeUndefined();
  expect(t.rec().status).toBe("exited");
  expect(t.rec().error).toBe(why);
  // the reason is not a model-popover note
  expect(t.ss.getState().notes[t.id]).toBeUndefined();
});

test("H5: a Codex thread that is gone says a new conversation started, in the chat, not the model popover", async () => {
  const t = await started("codex");
  t.emit({ event: "session.note", kind: "new_conversation", text: "The earlier Codex conversation was not found; a new one started." });
  t.emit({ event: "session.info", agent_session: "01a1cb4b-0d4e-7751-aae4-9d65216fa4e6", model: "GPT-6.1-Sol" });
  const lines = t.chat().items.filter((i) => i.kind === "system");
  expect(lines.map((i) => (i as { text: string }).text)).toEqual(["The earlier conversation was not found, so a new one started here."]);
  expect(t.ss.getState().notes[t.id]).toBeUndefined();
  expect(t.rec().agentSession).toBe("01a1cb4b-0d4e-7751-aae4-9d65216fa4e6");
  // the message is still on its way: its answer ends the turn as usual
  t.emit({ event: "turn.end", outcome: "done" });
  expect(t.chat().turn).toBeNull();
});

test("H7: a Claude Code model picked mid-turn shows as next turn's and never flips the header", async () => {
  const t = await started("claude");
  t.emit({ event: "session.info", agent_session: "8807e0e5-dd2a-4324-98d1-1949e74bd4b2", model: "Haiku 5.5" });
  const seen: string[] = [];
  const unsub = t.ss.subscribe(() => seen.push(t.rec().model ?? ""));
  // the adapter's events for the recorded stream (claude-11-model-mid-turn.jsonl)
  t.emit({ event: "session.info", model_next: "Sonnet 5.5" });
  t.emit({ event: "session.info", agent_session: "8807e0e5-dd2a-4324-98d1-1949e74bd4b2", model: "Haiku 5.5" });
  expect(t.rec().model).toBe("Haiku 5.5");
  expect(t.rec().modelNext).toBe("Sonnet 5.5");
  t.emit({ event: "turn.end", outcome: "done" });
  t.emit({ event: "turn.start" });
  t.emit({ event: "session.info", agent_session: "8807e0e5-dd2a-4324-98d1-1949e74bd4b2", model: "Sonnet 5.5", model_next: "" });
  unsub();
  expect(t.rec().model).toBe("Sonnet 5.5");
  expect(t.rec().modelNext).toBeUndefined();
  // Haiku until the next turn's init, then Sonnet: no Sonnet, Haiku, Sonnet
  const shown = seen.filter((m, i) => m && m !== seen[i - 1]);
  expect(shown).toEqual(["Haiku 5.5", "Sonnet 5.5"]);
});
