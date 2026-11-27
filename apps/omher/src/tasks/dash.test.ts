import { afterEach, describe, expect, it } from "vitest";
import { baseRelease, dashAccount, formatDuration, inTab, prsOf, releasesOf, runSeconds, runsOf, shownRepos, suggestions, tabCounts, type RepoState } from "./dash";
import { getTasks, pinRepo, resetTasks, setDashRepo, setDashTab, setScope, unpinRepo, MAX_PINS } from "./state";
import type { DashRelease, DashRepo, DashRun, MeItem } from "./types";

const pr = (repo: string, number: number, p: Partial<MeItem> = {}): MeItem => ({
  repo, number, title: `t${number}`, url: "", pr: true, draft: false, state: "open", author: "contributor-a", labels: [], created: 0, updated: number, asked: false, ci: "", review: "", conflict: false, requested: 0, ...p,
});
const run = (id: number, p: Partial<DashRun> = {}): DashRun => ({ id, workflow: "CI", title: "", branch: "main", event: "push", state: "passed", created: id, started: id, updated: id, url: "", ...p });
const rel = (tag: string, p: Partial<DashRelease> = {}): DashRelease => ({ tag, name: tag, latest: false, prerelease: false, published: 0, url: "", ...p });
const st = (d: Partial<DashRepo> & { repo: string }): RepoState => ({
  data: { branch: "main", ci: "", prs: [], runs: [], releases: [], ahead: null, rate: false, ...d },
  loading: false, fail: null, rate: false, at: 1,
});

describe("GitHub dashboard: the pure part", () => {
  afterEach(() => resetTasks());

  it("reads a repository as the account that owns it, else the first github.com account", () => {
    const accounts = [
      { host: "ghe.example.com", login: "example", color: "#000" },
      { host: "github.com", login: "contributor-a", color: "#111" },
      { host: "github.com", login: "example", color: "#222" },
    ];
    expect(dashAccount(accounts, "example/web-console")).toBe("example@github.com");
    expect(dashAccount(accounts, "Example/web-console")).toBe("example@github.com");
    expect(dashAccount(accounts, "acme/site")).toBe("contributor-a@github.com");
    expect(dashAccount([accounts[0]], "example/web-console")).toBeNull();
    expect(dashAccount([], "example/web-console")).toBeNull();
  });

  it("filters by the picked repository and the tab, newest update first", () => {
    const data = {
      "example/web-console": st({ repo: "example/web-console", prs: [pr("example/web-console", 212, { updated: 50 }), pr("example/web-console", 209, { updated: 90, asked: true })] }),
      "example/api": st({ repo: "example/api", prs: [pr("example/api", 7, { updated: 70, asked: true })] }),
    };
    const pins = ["example/web-console", "example/api"];
    expect(shownRepos(pins, "all")).toEqual(pins);
    expect(shownRepos(pins, "example/api")).toEqual(["example/api"]);
    expect(shownRepos(pins, "gone/repo")).toEqual(pins);
    const all = prsOf(data, shownRepos(pins, "all"));
    expect(all.map((p) => p.number)).toEqual([209, 7, 212]);
    expect(tabCounts(all)).toEqual({ all: 3, asked: 2 });
    expect(inTab(all, "asked").map((p) => p.number)).toEqual([209, 7]);
    expect(prsOf(data, ["example/api"]).map((p) => p.number)).toEqual([7]);
    // a repository not read yet adds nothing
    expect(prsOf(data, ["example/none"])).toEqual([]);
  });

  it("lists runs newest first and each repository's latest release with the commits since", () => {
    const data = {
      a: st({ repo: "a", runs: [run(10), run(30)], releases: [rel("v2-rc", { prerelease: true, published: 300 }), rel("v1", { latest: true, published: 100 })], ahead: 4 }),
      b: st({ repo: "b", runs: [run(20)], releases: [rel("v9", { published: 200 })], ahead: null, branch: "trunk" }),
      c: st({ repo: "c" }),
    };
    expect(runsOf(data, ["a", "b", "c"]).map((r) => [r.repo, r.id])).toEqual([["a", 30], ["b", 20], ["a", 10]]);
    expect(runsOf(data, ["a", "b"], 2)).toHaveLength(2);
    const rs = releasesOf(data, ["a", "b", "c"]);
    expect(rs.map((r) => [r.repo, r.release.tag, r.ahead, r.branch])).toEqual([["b", "v9", null, "trunk"], ["a", "v1", 4, "main"]]);
    expect(baseRelease([rel("x", { prerelease: true }), rel("y")])?.tag).toBe("y");
    expect(baseRelease([rel("x", { prerelease: true })])?.tag).toBe("x");
    expect(baseRelease([])).toBeNull();
  });

  it("times a run: finished from start to its last update, running until now", () => {
    expect(runSeconds(run(1, { started: 1000, updated: 1494 }))).toBe(494);
    expect(runSeconds(run(1, { state: "pending", started: 1000, updated: 1001 }), 1_060_000)).toBe(60);
    expect(runSeconds(run(1, { started: 0 }))).toBeNull();
    expect(formatDuration(45)).toBe("45s");
    expect(formatDuration(494)).toBe("8m 14s");
    expect(formatDuration(3720)).toBe("1h 2m");
  });

  it("suggests github.com repositories found in folders, not pinned, once each", () => {
    const found = [
      { source: "github" as const, repo: "example/web-console" },
      null,
      { source: "gitlab" as const, repo: "group/project" },
      { source: "github" as const, repo: "example/api" },
      { source: "github" as const, repo: "example/api" },
    ];
    expect(suggestions(["example/web-console"], found)).toEqual(["example/api"]);
    expect(suggestions([], found, 1)).toEqual(["example/web-console"]);
  });

  it("keeps pins checked, at most MAX_PINS, and the filter on a pin", () => {
    expect(pinRepo("example/web-console")).toBe(true);
    expect(pinRepo("example/web-console")).toBe(false);
    expect(pinRepo("not a repo")).toBe(false);
    expect(pinRepo("-x/y")).toBe(false);
    setDashRepo("example/web-console");
    setDashTab("asked");
    setScope("gh");
    expect(getTasks()).toMatchObject({ pins: ["example/web-console"], dashRepo: "example/web-console", dashTab: "asked", scope: "gh" });
    setDashRepo("gone/repo");
    expect(getTasks().dashRepo).toBe("example/web-console");
    unpinRepo("example/web-console");
    expect(getTasks()).toMatchObject({ pins: [], dashRepo: "all" });
    for (let i = 0; i < MAX_PINS + 2; i++) pinRepo(`example/r${i}`);
    expect(getTasks().pins).toHaveLength(MAX_PINS);
  });
});
