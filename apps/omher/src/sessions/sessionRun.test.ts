// A focused pane's run is read by its conversation id first (`runs.get`), so a resumed conversation older than the
// folder list's window keeps its subagents; the list is only the fallback.
import { describe, expect, it, vi } from "vitest";
import type { AgentRun, AgentRunSummary, RunDetail } from "../lib/runs";
import { readSessionRun } from "./SessionPlans";

const SID = "11111111-2222-4333-8444-555555555555";
const ID = `claude:${SID}`;
const run: AgentRun = {
  id: ID,
  kind: "claude-task",
  agent: "claude",
  owner: { type: "session", id: SID },
  title: "Claude Code session",
  cwd: "/w/app",
  state: "done",
  started: 1,
  updated: 2,
  nodes: [
    { id: "a", label: "one", state: "done", deps: [] },
    { id: "b", label: "two", state: "running", deps: [] },
    { id: "c", label: "three", state: "done", deps: [] },
  ] as unknown as AgentRun["nodes"],
};
const detail: RunDetail = { run, handoffs: {} };

describe("readSessionRun", () => {
  it("a resumed conversation the folder list leaves out is read by its own id, its subagents counted", async () => {
    const a = { runsGet: vi.fn(async () => detail), runsCli: vi.fn(async () => ({ runs: [] as AgentRunSummary[] })) };
    const got = await readSessionRun(a, ID, "claude", "/w/app", undefined);
    expect(a.runsGet).toHaveBeenCalledWith("", ID);
    expect(a.runsCli).not.toHaveBeenCalled();
    expect(got?.detail.run.nodes).toHaveLength(3);
    expect(got?.summary).toMatchObject({ id: ID, counts: { nodes: 3, done: 2, running: 1 } });
    expect(got?.summary).not.toHaveProperty("nodes");
  });

  it("when the read by id fails, the folder list is the fallback; neither: nothing", async () => {
    let calls = 0;
    const a = {
      runsGet: vi.fn(async () => {
        if (calls++ === 0) throw new Error("not_found");
        return detail;
      }),
      runsCli: vi.fn(async () => ({ runs: [{ ...run, nodes: undefined, counts: { nodes: 3, done: 2, running: 1, failed: 0 } }] as unknown as AgentRunSummary[] })),
    };
    expect((await readSessionRun(a, ID, "claude", "/w/app", 100))?.summary.counts.nodes).toBe(3);
    expect(a.runsCli).toHaveBeenCalledWith({ agent: "claude", cwd: "/w/app", since: 100 });
    const none = { runsGet: vi.fn(async () => Promise.reject(new Error("not_found"))), runsCli: vi.fn(async () => ({ runs: [] })) };
    expect(await readSessionRun(none, ID, "claude", "/w/app")).toBeNull();
  });
});
