// A session chat's turn ends with its program. The Terminal toggle during a Claude Code turn stops the chat's
// process (audit O6): the shell's turn.end for that process comes from a process that is no longer current, so
// the sessions store must end the turn itself, or the chat stays Working with Stop for good.
import { expect, test } from "vitest";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import type { ChatEvent, ChatInput, SessionHost } from "./host";

const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };

test("Terminal and back during a Claude Code turn leaves the chat idle, not Working", async () => {
  (globalThis as { localStorage?: unknown }).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const sinks = new Map<number, (e: ChatEvent) => void>();
  const inputs: [number, ChatInput][] = [];
  let next = 0;
  const host = {
    kind: "mock",
    reset: async () => {},
    agents: async () => [{ id: "claude", label: "Claude Code", mode: "chat", path: "/bin/claude" }],
    home: async () => "/w",
    pickFolder: async () => null,
    start: async () => 99,
    write: async () => {},
    resize: async () => {},
    close: async () => {},
    chatStart: async (_a: string, _c: string, on: (e: ChatEvent) => void) => {
      const id = ++next;
      sinks.set(id, on);
      on({ event: "session.info", agent_session: "06646083-601c-440e-8ecb-b9cb02adf675", model: "Fable 5.2" });
      return id;
    },
    chatInput: async (id: number, i: ChatInput) => {
      inputs.push([id, i]);
      if (i.kind === "send") sinks.get(id)!({ event: "turn.start" });
    },
    chatClose: async (id: number) => {
      // the Rust watcher: the program was mid-turn, so its exit ends the turn first (agent_chat.rs exit watcher)
      sinks.get(id)!({ event: "turn.end", outcome: "ended" });
      sinks.get(id)!({ event: "exit", code: 0, error: "" });
    },
  } as unknown as SessionHost;
  const store = createStore(bridge);
  const ss = createSessions(host, () => store);
  await ss.loadAgents();
  const id = ss.draft("claude");
  ss.setDraft(id, { cwd: "/w/proj" });
  await ss.start(id, "Run a long command");
  const key = ss.chatKey(id)!;
  const chat = () => store.getState().chats[key]!;
  expect(chat().turn).not.toBeNull();
  sinks.get(1)!({ event: "tool.start", tool_id: "t1", name: "terminal", detail: "sleep 40" });
  await ss.setView(id, "terminal");
  expect(chat().turn).toBeNull();
  expect(chat().lastTurn!.outcome).toBe("interrupted");
  await ss.setView(id, "chat");
  expect(chat().turn).toBeNull();
  expect(ss.getState().list[0].status).not.toBe("exited");
  // the new process takes the next message as a turn of its own, which ends as usual
  await ss.send(id, "again");
  expect(chat().turn).not.toBeNull();
  sinks.get(2)!({ event: "turn.end", outcome: "done" });
  expect(chat().turn).toBeNull();
});
