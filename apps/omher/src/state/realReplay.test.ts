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
    expect(new Set(all.map((r) => r.agent))).toEqual(new Set(["claude", "codex", "codex-resume", "codex-helpers", "codex-helper-stop", "omo", "omp", "pi", "pi-noauth"]));
    expect(all.length).toBeGreaterThanOrEqual(38);
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
