import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { attachDelegations, attachOwners, attachPlanned, countsOf, fromDag, fromDelegation, layerOf, nodeModel, routeTable, sortRuns, span, summary, type AgentRun, type DagRecord, type Delegation, type RouteRecord } from "./runs";

const fx = (name: string) => readFileSync(fileURLToPath(new URL(`./__fixtures__/${name}`, import.meta.url)), "utf-8");
const rec = (name: string) => JSON.parse(fx(name)) as DagRecord;
const bridge = JSON.parse(fx("runs-bridge.json")) as { runs: AgentRun[]; handoffs: Record<string, Record<string, string>> };

describe("layerOf", () => {
  it("is the longest dependency path", () => {
    const l = layerOf([
      { id: "a", deps: [] },
      { id: "b", deps: ["a"] },
      { id: "c", deps: ["a", "b"] },
      { id: "d", deps: [] },
      { id: "e", deps: ["d", "c"] },
    ]);
    expect(l).toEqual({ a: 0, b: 1, c: 2, d: 0, e: 3 });
  });
  it("ignores deps on nodes it does not have", () => {
    expect(layerOf([{ id: "a", deps: ["gone"] }])).toEqual({ a: 0 });
  });
  it("throws on a cycle", () => {
    expect(() => layerOf([{ id: "a", deps: ["b"] }, { id: "b", deps: ["a"] }])).toThrow(/cycle/);
    expect(() => layerOf([{ id: "a", deps: ["a"] }])).toThrow(/cycle/);
  });
});

describe("summary", () => {
  it("counts done, running and failed, leaving zeros out", () => {
    const n = (state: string) => ({ state }) as AgentRun["nodes"][number];
    const run = { nodes: [n("done"), n("done"), n("done"), n("running"), n("failed"), n("waiting"), n("parked")] };
    expect(summary(run)).toBe("7 nodes · 3 done · 1 running · 1 failed");
    expect(summary({ nodes: [n("waiting")] })).toBe("1 node");
    expect(summary({ counts: { nodes: 2, done: 2, running: 0, failed: 0 } })).toBe("2 nodes · 2 done");
  });
});

describe("fromDag on real (redacted) runs", () => {
  it("fan-out with a failed attempt and a repair: failed node stays failed, the run is done", () => {
    const run = fromDag(rec("codex-coexist.json"), "kami");
    expect(run.id).toBe("dag:20261102_235818_fcfb1bdd/codex-coexist");
    expect(run.kind).toBe("dag");
    expect(run.owner).toEqual({ type: "bot", id: "kami" });
    expect(run.state).toBe("done");
    const by = Object.fromEntries(run.nodes.map((n) => [n.id, n]));
    expect(by["t1-discovery"].state).toBe("failed");
    expect(by["t1-discovery"].attempts[0].reason).toMatch(/fence denied/);
    expect(by["t1-discovery"].lane).toBe("fanout");
    expect(by["t5-verify"].attempts.map((a) => a.outcome)).toEqual(["retry", "accepted"]);
    expect(by["t5-verify"].state).toBe("done");
    expect(by["t5-verify"].layer).toBe(2);
    expect(by["t3-doctor"].layer).toBe(1);
    expect(run.nodes.filter((n) => n.layer === 0).map((n) => n.id).sort()).toEqual(["t1-discovery", "t2-status-update"]);
    // the two repairs point at the failed node they repair and sit one column after it
    expect([by["t1-hermes"].repairOf, by["t4-fence"].repairOf]).toEqual(["t1-discovery", "t1-discovery"]);
    expect([by["t1-hermes"].layer, by["t4-fence"].layer]).toEqual([1, 1]);
    expect(by["t1-discovery"].repairOf).toBeUndefined();
    expect(summary(run)).toBe("6 nodes · 5 done · 1 repaired");
  });
  it("cancelled run: settled nodes keep their state, the rest are cancelled", () => {
    const run = fromDag(rec("omh-dap.json"), "kami");
    expect(run.state).toBe("cancelled");
    expect(run.ended).toBe(rec("omh-dap.json").cancelled_at);
    expect(run.nodes.map((n) => n.state)).toEqual(["done", "done", "done", "cancelled", "cancelled"]);
  });
  it("small run: two nodes in two layers, done", () => {
    const run = fromDag(rec("route-hint-dedup.json"), "kami", ["implement"]);
    expect(run.state).toBe("done");
    expect(run.nodes.map((n) => [n.id, n.layer, n.state])).toEqual([
      ["implement", 0, "done"],
      ["verify", 1, "done"],
    ]);
    expect(run.nodes[0].handoff).toBe("implement.md");
    expect(run.nodes[1].handoff).toBeUndefined();
  });
  it("a node handed out and not settled is running; one never handed out is waiting", () => {
    const run = fromDag(rec("codex-coexist-live.json"), "kami");
    expect(run.state).toBe("running");
    const by = Object.fromEntries(run.nodes.map((n) => [n.id, n]));
    expect(by["t3-doctor"].state).toBe("running");
    expect(by["t3-doctor"].ended).toBeUndefined();
    expect(by["t5-verify"].state).toBe("waiting");
    expect(run.ended).toBeUndefined();
    // the failed discovery node's two repairs are done: repaired, not an open failure
    expect(countsOf(run)).toEqual({ nodes: 6, done: 3, running: 1, failed: 0, repaired: 1 });
  });
  it("matches the bridge's dag_to_run field for field", () => {
    const names: Record<string, string> = {
      "omh-dap": "omh-dap.json",
      "route-hint-dedup": "route-hint-dedup.json",
      "codex-coexist": "codex-coexist.json",
      "codex-coexist-live": "codex-coexist-live.json",
    };
    expect(bridge.runs).toHaveLength(4);
    for (const b of bridge.runs) {
      const file = names[b.id.split("/")[1]];
      const ts = fromDag(rec(file), "kami", Object.keys(bridge.handoffs[b.id]));
      expect(JSON.parse(JSON.stringify(ts))).toEqual(b);
    }
  });
  it("a record cut mid-write does not parse (the bridge keeps the last good one)", () => {
    expect(() => JSON.parse(fx("dag-truncated.json"))).toThrow();
  });
});

describe("ordering and time", () => {
  it("running first, then most recently updated", () => {
    const r = (id: string, state: AgentRun["state"], updated: number) => ({ id, state, updated });
    expect(sortRuns([r("a", "done", 5), r("b", "running", 1), r("c", "failed", 9)]).map((x) => x.id)).toEqual(["b", "c", "a"]);
  });
  it("span is coarse", () => {
    expect([span(40), span(14 * 60 + 30), span(2 * 3600 + 5 * 60), span(3 * 3600), span(5 * 86400)]).toEqual(["40s", "14m", "2h 5m", "3h", "5d"]);
  });
});

// T5: helpers' models and routes, from real (redacted) delegation folders read by the bridge
const routed = JSON.parse(fx("runs-routed.json")) as {
  kami: AgentRun[];
  default: AgentRun[];
  delegations: Delegation[];
  owners: Record<string, Record<string, string>>;
  records: RouteRecord[];
  sessions: string[];
  table: Record<string, NonNullable<AgentRun["nodes"][number]["planned"]>>;
};
const table = routeTable(routed.records, new Set(routed.sessions));
const joined = (r: AgentRun) => attachPlanned(attachDelegations(attachOwners(r, routed.owners[r.id.split("/")[1]] ?? {}), routed.delegations), table);

describe("delegations", () => {
  it("joins each dag node to its helper: model, provider, effort and the route record", () => {
    const run = attachDelegations(fromDag(rec("omher-v02.json"), "default"), routed.delegations);
    const by = Object.fromEntries(run.nodes.map((n) => [n.id, n]));
    expect(by["t0-t3-runs"]).toMatchObject({ model: "claude-opus-5-5", provider: "claude-proxy", effort: "high", route: "unspecified-high" });
    expect(by["t7-t10-usage"]).toMatchObject({ model: "claude-opus-5-5", route: "visual-engineering" });
    expect(by["t0-t3-runs"].summary).toMatch(/^T0 and T3 are both done/);
    expect(by["t0-t3-runs"].summary!.length).toBeLessThanOrEqual(600);
    // a node no helper has started yet keeps only the dag's category
    expect(by["t9-verify"].model).toBeUndefined();
    expect(by["t9-verify"].route).toBe("review");
  });
  it("pairs attempt k with the k-th helper: a retried node shows both models", () => {
    const run = attachDelegations(fromDag(rec("codex-coexist.json"), "kami"), routed.delegations);
    const verify = run.nodes.find((n) => n.id === "t5-verify")!;
    expect(verify.attempts.map((a) => a.model)).toEqual(["gpt-6.1-sol", "claude-opus-5-5"]);
    expect(verify.model).toBe("claude-opus-5-5");
    // the dag's own route (category) wins over the record
    expect(verify.route).toBe(fromDag(rec("codex-coexist.json"), "kami").nodes.find((n) => n.id === "t5-verify")!.route);
  });
  it("every node of the live fan-out has a model to show: the agent CLI it went to, else its route's model", () => {
    expect(table).toEqual(routed.table);
    const live = joined(fromDag(rec("codex-coexist-live.json"), "kami"));
    const by = Object.fromEntries(live.nodes.map((n) => [n.id, nodeModel(n)]));
    expect(by["t3-doctor"]).toEqual({ model: "codex", source: "executor" });
    expect(by["t1-discovery"]).toEqual({ model: "codex", source: "executor" });
    expect(by["t5-verify"]).toMatchObject({ model: "claude-opus-5-5", provider: "claude-proxy", source: "route" });
    expect(live.nodes.find((n) => n.id === "t5-verify")!.role).toBe("verify");
    // nothing known at all: the bot's own model
    expect(nodeModel({ ...live.nodes[0], executor: undefined, model: undefined, planned: undefined }, { model: "Opus 5.5", provider: "claude-proxy" })).toMatchObject({ source: "bot" });
  });
  it("a fan-out with no dag marker becomes a one-layer delegate run", () => {
    const d = routed.delegations.find((x) => x.id === "deleg_e8b94630")!;
    const run = fromDelegation(d, "default");
    expect(run.kind).toBe("delegate");
    expect(run.nodes.map((n) => [n.layer, n.deps.length, n.state])).toEqual([
      [0, 0, "done"],
      [0, 0, "done"],
    ]);
    expect(run.nodes[0].model).toBe("claude-opus-5-5");
    expect(run.title).toMatch(/ \+1$/);
  });
  it("matches the bridge's attach_delegations / delegation_to_run field for field", () => {
    const names: Record<string, string> = {
      "omh-dap": "omh-dap.json",
      "route-hint-dedup": "route-hint-dedup.json",
      "codex-coexist": "codex-coexist.json",
      "codex-coexist-live": "codex-coexist-live.json",
      "omher-v02": "omher-v02.json",
    };
    for (const b of [...routed.kami, ...routed.default.filter((r) => r.kind === "dag")]) {
      const handoffs = b.nodes.filter((n) => n.handoff).map((n) => n.id);
      const ts = joined(fromDag(rec(names[b.id.split("/")[1]]), b.owner.id, handoffs));
      expect(JSON.parse(JSON.stringify(ts))).toEqual(b);
    }
    for (const b of routed.default.filter((r) => r.kind === "delegate")) {
      const d = routed.delegations.find((x) => `delegate:${x.id}` === b.id)!;
      expect(JSON.parse(JSON.stringify(fromDelegation(d, "default")))).toEqual(b);
    }
  });
});
