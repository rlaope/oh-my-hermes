import { describe, expect, it } from "vitest";
import type { AgentRun, RunNode } from "../lib/runs";
import { boxText, GEOMETRY, layoutBoxes, prWidth, type Measure } from "./boxView";
import { prLabel, prLink, prState, prText, prWord, PR_URL, withPrs } from "./pr";
import { PR_PATHS } from "../ui/PrIcon";

const M: Measure = (text, font) => [...text].length * (font === "title" ? 8 : 7);
const node = (id: string, extra: Partial<RunNode> = {}): RunNode => ({ id, label: id, deps: [], layer: 0, state: "done", attempts: [], ...extra });
const URL = (n: number) => `https://github.com/rlaope/oh-my-hermes/pull/${n}`;

describe("a plan node's pull request", () => {
  it("says the number, and the state word only once GitHub has said it", () => {
    expect(prLabel({ number: 2746 })).toBe("#2746");
    expect(prState({})).toBe("unknown");
    expect(prText({ number: 2746 })).toBe("#2746");
    expect(prText({ number: 2746, state: "unknown" })).toBe("#2746");
    expect(prText({ number: 2746, state: "merged" })).toBe("#2746 · Merged");
    expect(["open", "merged", "closed", "draft"].map((s) => prWord(s as never))).toEqual(["Open", "Merged", "Closed", "Draft"]);
  });

  it("links only a GitHub pull request page whose number is the PR's", () => {
    expect(prLink({ number: 2750, url: URL(2750) })).toBe(URL(2750));
    expect(prLink({ number: 2750, url: URL(2751) })).toBeNull();
    expect(prLink({ number: 2750 })).toBeNull();
    for (const bad of [`${URL(2750)}/files`, `${URL(2750)}?x`, "https://github.com/o/r/issues/2750", "http://github.com/o/r/pull/2750", "https://github.com.evil.example/o/r/pull/2750", "javascript:alert(2750)"])
      expect(prLink({ number: 2750, url: bad }), bad).toBeNull();
    expect(PR_URL.test("https://github.com/o-1/r_e.po/pull/1")).toBe(true);
  });

  it("lays the state from runs.prs over the number runs.get gave, for the same number only", () => {
    const run = { nodes: [node("a", { pr: { number: 1, repo: "o/r" } }), node("b", { pr: { number: 2 } }), node("c")] } as Pick<AgentRun, "nodes">;
    const got = withPrs(run, { a: { number: 1, repo: "o/r", url: "https://github.com/o/r/pull/1", state: "draft" }, b: { number: 3, state: "open" }, c: { number: 4, state: "open" } });
    expect(got.nodes.map((n) => n.pr)).toEqual([{ number: 1, repo: "o/r", url: "https://github.com/o/r/pull/1", state: "draft" }, { number: 2 }, undefined]);
    expect(withPrs(run, null)).toBe(run);
    expect(withPrs(run, {})).toBe(run);
  });

  it("uses GitHub's own Octicon paths, one per state", () => {
    expect(Object.keys(PR_PATHS).sort()).toEqual(["closed", "draft", "merged", "open"]);
    expect(PR_PATHS.open.startsWith("M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256")).toBe(true); // git-pull-request-16
    expect(PR_PATHS.merged.startsWith("M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5")).toBe(true); // git-merge-16
    expect(new Set(Object.values(PR_PATHS)).size).toBe(4);
  });

  it("ends the status line with the PR where the word still fits beside it; the time gives way first", () => {
    const pr = { number: 2746, state: "merged" as const };
    const r = { kind: "dag" as const, nodes: [node("a", { started: 0, ended: 420, pr }), node("b", { started: 0, ended: 420 })] };
    const g = layoutBoxes(r, { width: 700, measure: M });
    const w = prWidth(pr, M);
    expect(w).toBe(GEOMETRY.prGap + GEOMETRY.icon + GEOMETRY.prIconGap + 5 * 7);
    const at = (inner: number) => boxText(r.nodes[0], r, g, inner, 0, M);
    const room = (chars: number) => GEOMETRY.icon + GEOMETRY.iconGap + chars * 7 + 0.5;
    expect(at(room(7) + w)).toMatchObject({ word: "Done", time: "7m", pr }); // "Done 7m" and the PR
    expect(at(room(6) + w)).toMatchObject({ word: "Done", time: "", pr }); // the time gives way to the PR
    expect(at(room(3) + w).pr).toBeNull(); // the word itself does not fit beside it: the detail names the PR
    expect(boxText(r.nodes[1], r, g, 240, 0, M).pr).toBeNull();
    // every box is wide enough for its status with the PR whole: a box with a PR asks for that much room
    const one = layoutBoxes({ kind: "dag", nodes: [node("a", { started: 0, ended: 420, pr })] }, { width: 1200, measure: M });
    const none = layoutBoxes({ kind: "dag", nodes: [node("a", { started: 0, ended: 420 })] }, { width: 1200, measure: M });
    expect(one.boxW).toBeGreaterThanOrEqual(none.boxW);
    expect(boxText(one.boxes.length ? r.nodes[0] : r.nodes[0], r, one, one.inner, 0, M)).toMatchObject({ time: "7m", pr });
  });
});
