// Every real CLI stream (src-tauri/tests/fixtures/real/), replayed through its Rust adapter by
// `real_streams_end_their_turns_and_say_nothing_outside_one`, then through this reducer under a session chat key:
// after the last event no turn runs, nothing shows a status, and no ask is left open. The JSON is that test's
// output, so an adapter change that moves it fails there until it is rewritten.
import { describe, expect, it } from "vitest";
import replays from "./__fixtures__/real-agent-replay.json";
import { initialState, reduce, selectAsks, type Action, type AppState } from "./store";
import type { BridgeEvent } from "../lib/protocol";

type Replay = { name: string; agent: string; events: Record<string, unknown>[] };

const T0 = 1_800_000_000_000;

function replay(r: Replay): AppState {
  const key = "agent:s1";
  let s = reduce(initialState(), {
    type: "chat.opened",
    bot: key,
    res: { session_id: key, messages: [], running: false, model: "", provider: "", reasoning: "" },
    now: T0,
  });
  r.events.forEach((ev, i) => {
    s = reduce(s, { type: "event", ev: { ...ev, bot: key } as unknown as BridgeEvent, now: T0 + (i + 1) * 100 } as Action);
  });
  return s;
}

describe("real agent streams through the reducer", () => {
  const all = replays as Replay[];

  it("covers every agent", () => {
    expect(new Set(all.map((r) => r.agent))).toEqual(new Set(["claude", "codex", "codex-resume", "codex-resume-gone", "codex-helpers", "codex-helper-stop", "omo", "omp", "pi", "pi-noauth"]));
    expect(all.length).toBeGreaterThanOrEqual(41);
  });

  for (const r of all) {
    it(`${r.name}: no turn left running`, () => {
      const s = replay(r);
      const c = s.chats["agent:s1"];
      expect(c.turn, r.name).toBeNull();
      expect(c.early ?? null, r.name).toBeNull();
      expect(selectAsks(s).filter((a) => a.bot === "agent:s1"), r.name).toEqual([]);
      // every turn the chat drew has ended
      for (const it of c.items) if (it.kind === "activity") expect(it.turn.endedAt, `${r.name} ${it.id}`).toBeDefined();
    });
  }

  it("Claude Code's real two-file edit: one todo list all done, each edit with its change, thinking kept", () => {
    const s = replay(all.find((r) => r.name === "claude-12-work.jsonl")!);
    const acts = s.chats["agent:s1"].items.filter((i) => i.kind === "activity");
    expect(acts).toHaveLength(1);
    const t = acts[0].kind === "activity" ? acts[0].turn : null;
    expect(t!.plan?.map((p) => p.status)).toEqual(["completed", "completed", "completed"]);
    const edits = t!.steps.filter((x) => x.name === "patch");
    expect(edits.map((x) => x.diff?.[0].path)).toEqual(["calc.py", "calc.py", "README.md"]);
    expect(edits[1].diff?.[0].lines).toContain("+def mul(a, b):");
    expect(t!.steps.some((x) => /^Task|^Todo/.test(x.name))).toBe(false);
    const th = replay(all.find((r) => r.name === "claude-12-thinking.jsonl")!);
    const tt = th.chats["agent:s1"].items.find((i) => i.kind === "activity");
    expect(tt?.kind === "activity" && tt.turn.thinking).toMatch(/^No todo tool is available/);
  });

  it("Claude Code's real rewind takes the first message and its answer out of the chat", () => {
    const r = all.find((x) => x.name === "claude-12-rewind.jsonl")!;
    expect(r.events.some((e) => e.event === "rewound")).toBe(true);
  });

  const fans = (s: AppState) => s.chats["agent:s1"].items.flatMap((i) => (i.kind === "activity" ? (i.turn.fanouts ?? []) : []));

  it("Claude Code's two subagents in parallel: one card, two rows with name, task, steps and their own answer", () => {
    const s = replay(all.find((r) => r.name === "claude-9-subagents.jsonl")!);
    const f = fans(s);
    expect(f.map((x) => x.subs.length)).toEqual([2, 1]);
    const [a, b] = f[0].subs;
    expect([a.agent, a.name, a.goal, a.state, a.summary]).toEqual(["claude", "general-purpose", "Read a.txt first line", "done", "alpha line"]);
    expect([b.goal, b.state]).toEqual(["Count lines of b.txt", "done"]);
    expect(a.steps?.map((x) => x.text)).toEqual(["/w/proj/a.txt"]);
    expect(a.seconds).toBeGreaterThan(0);
    // the second turn's subagent asked for approval: the card named it, and the answer closed it
    const r = all.find((x) => x.name === "claude-9-subagents.jsonl")!;
    const ask = r.events.find((e) => e.event === "approval.request") as { subagent?: { name: string } };
    expect(ask.subagent?.name).toBe("Write c.txt via echo");
  });

  it("an approval inside a subagent is an ask that names the subagent", () => {
    const r = all.find((x) => x.name === "claude-9-subagents.jsonl")!;
    const upto = r.events.findIndex((e) => e.event === "approval.request");
    const s = replay({ ...r, events: r.events.slice(0, upto + 1) });
    const asks = selectAsks(s).filter((a) => a.bot === "agent:s1");
    expect(asks).toHaveLength(1);
    expect((asks[0].item as { subagent?: { name: string } }).subagent?.name).toBe("Write c.txt via echo");
  });

  it("OmO's two background subagents: one card, each with its own answer", () => {
    const s = replay(all.find((r) => r.name === "omo-9-subagents.jsonl")!);
    const subs = fans(s).flatMap((x) => x.subs);
    expect(subs.length).toBe(2);
    expect(subs.every((x) => x.agent === "omo" && x.state === "done" && !!x.summary)).toBe(true);
  });

  it("OmO's statuses after its answer start nothing (the owner's 안녕 turn)", () => {
    const omo = all.find((r) => r.name === "omo-1-plain.jsonl")!;
    // what the adapter used to forward after agent_end
    const late = [{ event: "status", text: "(😺 OmO Native)" }, { event: "status", text: "mem:khope-sionic-ai-d09472c9 9d ago (+1)" }, { event: "thinking" }];
    const s = replay({ ...omo, events: [...omo.events, ...late] });
    const c = s.chats["agent:s1"];
    expect(c.turn).toBeNull();
    expect(c.items.filter((i) => i.kind === "activity")).toHaveLength(1);
  });
});
