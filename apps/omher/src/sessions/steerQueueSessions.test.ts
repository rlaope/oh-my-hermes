// steer queue sessions: a message sent while an agent chat's turn runs waits in omher with the ↵ menu. Which menu
// items an agent offers (pure), and the hold / Send now / Steer / Edit / Delete flow against a fake shell.
import { expect, test } from "vitest";
import { queueOff, STEERS, steersOf } from "./controls";
import { createSessions } from "./sessions";
import { createStore, type BridgeLike } from "../state/store";
import type { ChatEvent, ChatInput, SessionHost } from "./host";

test("Steer is offered only to the agents with their own mid-turn input; the others say why", () => {
  expect([...STEERS]).toEqual(["claude", "codex", "pi", "omp", "omo"]);
  for (const a of ["dsh", "opencode", "gemini", "omh"]) expect(steersOf(a)).toBe(false);
  expect(queueOff("codex", "Codex", true, true)).toEqual({});
  expect(queueOff("dsh", "DSH", true, true)).toEqual({ steer: "DSH has no way to take a message mid-answer" });
  // handed to the agent: nothing can change it any more, each item says so
  const off = queueOff("claude", "Claude Code", false, true)!;
  expect(Object.keys(off).sort()).toEqual(["delete", "edit", "now", "steer"]);
  expect(off.edit).toBe("Already with Claude Code · it takes it next");
  // not waiting: no menu
  expect(queueOff("claude", "Claude Code", false, false)).toBeNull();
});

const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };

async function setup(agent = "codex", failSends: string[] = [], interruptEnds = true) {
  (globalThis as { localStorage?: unknown }).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  let sink: (e: ChatEvent) => void = () => {};
  const inputs: ChatInput[] = [];
  const host = {
    kind: "mock",
    reset: async () => {},
    agents: async () => [{ id: agent, label: agent, mode: "chat", path: `/bin/${agent}` }],
    home: async () => "/w",
    pickFolder: async () => null,
    chatStart: async (_a: string, _c: string, on: (e: ChatEvent) => void) => {
      sink = on;
      return 1;
    },
    chatInput: async (_id: number, i: ChatInput) => {
      inputs.push(i);
      if (i.kind === "send" && failSends.includes(i.text)) throw new Error("agent gone");
      if (i.kind === "send") sink({ event: "turn.start" });
      if (i.kind === "interrupt" && interruptEnds) sink({ event: "turn.end", outcome: "interrupted" });
    },
    chatClose: async () => {},
  } as unknown as SessionHost;
  const store = createStore(bridge);
  const ss = createSessions(host, () => store);
  await ss.loadAgents();
  const id = ss.draft(agent as never);
  ss.setDraft(id, { cwd: "/w/proj" });
  await ss.start(id, "first");
  const key = ss.chatKey(id)!;
  const chat = () => store.getState().chats[key]!;
  const row = (text: string) => chat().items.find((i) => i.kind === "user" && i.text === text) as { id: string; held?: boolean; wait?: string } | undefined;
  const tick = () => new Promise((r) => setTimeout(r, 5));
  return { ss, id, key, chat, row, inputs, end: (outcome = "done") => sink({ event: "turn.end", outcome }), emit: (e: ChatEvent) => sink(e), tick, store };
}

const sends = (inputs: ChatInput[]) => inputs.filter((i) => i.kind === "send").map((i) => (i as { text: string }).text);

test("a message sent mid-turn is held in omher, then goes out when the turn ends, one per turn", async () => {
  const t = await setup();
  await t.ss.send(t.id, "B");
  await t.ss.send(t.id, "C");
  expect(sends(t.inputs)).toEqual(["first"]);
  expect(t.row("B")).toMatchObject({ held: true, wait: "queued" });
  t.end();
  await t.tick();
  expect(sends(t.inputs)).toEqual(["first", "B"]);
  expect(t.row("B")?.held).toBeUndefined();
  expect(t.row("B")?.wait).toBeUndefined();
  expect(t.row("C")?.held).toBe(true);
  t.end();
  await t.tick();
  expect(sends(t.inputs)).toEqual(["first", "B", "C"]);
});

test("Send now: one Stop, then this message goes first and the rest still wait", async () => {
  const t = await setup();
  await t.ss.send(t.id, "B");
  await t.ss.send(t.id, "C");
  const c = t.row("C")!.id;
  await Promise.all([t.ss.queuePick(t.id, c, "now"), t.ss.queuePick(t.id, c, "now")]);
  await t.tick();
  expect(t.inputs.filter((i) => i.kind === "interrupt")).toHaveLength(1);
  expect(sends(t.inputs)).toEqual(["first", "C"]);
  expect(t.row("B")?.held).toBe(true);
});

test("Stop throws away what waited, as the agents do", async () => {
  const t = await setup();
  await t.ss.send(t.id, "B");
  await t.ss.interrupt(t.id);
  await t.tick();
  expect(sends(t.inputs)).toEqual(["first"]);
  expect(t.row("B")).toMatchObject({ wait: "dropped" });
  expect(t.chat().queue ?? []).toEqual([]);
});

test("Steer hands it to the running turn with the agent's own steer; Edit and Delete only while omher holds it", async () => {
  const t = await setup();
  await t.ss.send(t.id, "B");
  await t.ss.send(t.id, "C");
  await t.ss.send(t.id, "D");
  await t.ss.queuePick(t.id, t.row("B")!.id, "steer");
  expect(t.inputs.filter((i) => i.kind === "steer")).toEqual([{ kind: "steer", id: t.row("B")!.id, text: "B" }]);
  // with the agent now: still Waiting, no longer held; Delete does nothing
  expect(t.row("B")).toMatchObject({ wait: "queued" });
  expect(t.row("B")?.held).toBeUndefined();
  await t.ss.queuePick(t.id, t.row("B")!.id, "delete");
  expect(t.row("B")).toBeDefined();
  // delete before taken: gone, never sent
  await t.ss.queuePick(t.id, t.row("C")!.id, "delete");
  expect(t.row("C")).toBeUndefined();
  // edit: back in the box
  await t.ss.queuePick(t.id, t.row("D")!.id, "edit");
  expect(t.row("D")).toBeUndefined();
  expect(t.store.getState().ui.draft).toMatchObject({ bot: t.key, text: "D" });
  t.end();
  await t.tick();
  expect(sends(t.inputs)).toEqual(["first"]);
});

test("an agent without steer sends nothing for Steer", async () => {
  const t = await setup("dsh");
  await t.ss.send(t.id, "B");
  await t.ss.queuePick(t.id, t.row("B")!.id, "steer");
  expect(t.inputs.filter((i) => i.kind === "steer")).toEqual([]);
  expect(t.row("B")?.held).toBe(true);
});

test("M4: a held message whose send fails is marked, and the next one still goes out", async () => {
  const t = await setup("codex", ["B"]);
  await t.ss.send(t.id, "B");
  await t.ss.send(t.id, "C");
  t.end();
  await t.tick();
  await t.tick();
  expect(sends(t.inputs)).toEqual(["first", "B", "C"]);
  expect(t.row("B")).toMatchObject({ error: "agent gone" });
  expect(t.row("C")?.held).toBeUndefined();
  expect(t.chat().queue ?? []).toEqual([]);
});

test("a Send now mark is used up by the turn's end: a later Stop still throws away what waits", async () => {
  const t = await setup("codex", [], false);
  await t.ss.send(t.id, "B");
  // Send now, then Delete before the stopped turn ends: that end finds nothing waiting
  await t.ss.queuePick(t.id, t.row("B")!.id, "now");
  await t.ss.queuePick(t.id, t.row("B")!.id, "delete");
  t.end("interrupted");
  await t.tick();
  // a new turn, a message waiting behind it, then a real Stop: it is thrown away, not sent as a Send now
  await t.ss.send(t.id, "C");
  await t.ss.send(t.id, "D");
  t.end("interrupted");
  await t.tick();
  expect(t.row("D")).toMatchObject({ wait: "dropped" });
  expect(sends(t.inputs)).toEqual(["first", "C"]);
});
