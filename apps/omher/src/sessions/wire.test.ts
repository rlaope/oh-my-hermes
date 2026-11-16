import { describe, expect, it } from "vitest";
import { dispatchSessionFg, onSessionFg } from "./fg";
import { allCollapsed, collapseOthers, folderSummary, moveFolder, orderFolders, parseFolderPrefs, setAllFolders, toggleFolder } from "./folders";
import { dockCols, dockSpan } from "../sidebar/Dock";
import { topFor } from "../sidebar/revealBot";

describe("session-fg", () => {
  it("hands each event to the terminal that owns the pty id", () => {
    const a: (string | null)[] = [];
    const b: (string | null)[] = [];
    const offA = onSessionFg(101, (x) => a.push(x));
    const offB = onSessionFg(102, (x) => b.push(x));
    dispatchSessionFg({ id: 101, agent: "claude" });
    dispatchSessionFg({ id: 102, agent: "codex" });
    dispatchSessionFg({ id: 101, agent: null });
    expect(a).toEqual(["claude", null]);
    expect(b).toEqual(["codex"]);
    offA();
    offB();
    dispatchSessionFg({ id: 101, agent: "grok" });
    expect(a).toEqual(["claude", null]);
  });
  it("keeps an event that arrives before its terminal knows its id", () => {
    dispatchSessionFg({ id: 103, agent: "pi" });
    const got: (string | null)[] = [];
    const off = onSessionFg(103, (x) => got.push(x));
    expect(got).toEqual(["pi"]);
    off();
  });
  it("an empty agent is the shell", () => {
    const got: (string | null)[] = [];
    const off = onSessionFg(104, (x) => got.push(x));
    dispatchSessionFg({ id: 104, agent: "" });
    expect(got).toEqual([null]);
    off();
  });
});

describe("TERMINALS folders", () => {
  const groups = [{ cwd: "/a" }, { cwd: "/b" }, { cwd: "/c" }];
  it("orders by the saved order, unknown folders after in their own order", () => {
    expect(orderFolders(groups, ["/c", "/a"]).map((g) => g.cwd)).toEqual(["/c", "/a", "/b"]);
    expect(orderFolders(groups, []).map((g) => g.cwd)).toEqual(["/a", "/b", "/c"]);
  });
  it("moves a folder to a place", () => {
    expect(moveFolder(["/a", "/b", "/c"], "/c", 0)).toEqual(["/c", "/a", "/b"]);
    expect(moveFolder(["/a", "/b", "/c"], "/a", 2)).toEqual(["/b", "/c", "/a"]);
  });
  it("collapses one, all, and all but one", () => {
    const p = { collapsed: [], order: [] };
    expect(toggleFolder(p, "/a").collapsed).toEqual(["/a"]);
    expect(toggleFolder(toggleFolder(p, "/a"), "/a").collapsed).toEqual([]);
    const all = setAllFolders(p, ["/a", "/b"], true);
    expect(allCollapsed(all, ["/a", "/b"])).toBe(true);
    expect(setAllFolders(all, ["/a", "/b"], false).collapsed).toEqual([]);
    expect(collapseOthers(all, ["/a", "/b", "/c"], "/b").collapsed.sort()).toEqual(["/a", "/c"]);
  });
  it("reads only well-formed saved prefs", () => {
    expect(parseFolderPrefs("{bad")).toEqual({ collapsed: [], order: [] });
    expect(parseFolderPrefs(JSON.stringify({ collapsed: ["/a", 3, "/a"], order: "x" }))).toEqual({ collapsed: ["/a"], order: [] });
  });
  it("a collapsed header's summary: count, output flowing, waiting, failed", () => {
    expect(folderSummary(["busy", null, "bell"])).toEqual({ count: 3, busy: true, needs: true, failed: false });
    expect(folderSummary(["ok", "err"])).toEqual({ count: 2, busy: false, needs: false, failed: true });
  });
});

describe("dock rows", () => {
  it("never leaves a tile alone on a row: 4 = 2x2, 5 = 3 over 2 filling the width", () => {
    expect([1, 2, 3, 4, 5, 6].map(dockCols)).toEqual([1, 2, 3, 2, 3, 3]);
    expect([0, 1, 2, 3].map((i) => dockSpan(i, 4))).toEqual([3, 3, 3, 3]);
    expect([0, 1, 2, 3, 4].map((i) => dockSpan(i, 5))).toEqual([2, 2, 2, 3, 3]);
    expect([0, 1, 2, 3, 4, 5].map((i) => dockSpan(i, 6))).toEqual([2, 2, 2, 2, 2, 2]);
  });
});

describe("bot reveal", () => {
  it("puts the row at the top of its list, within what the list can scroll", () => {
    expect(topFor(100, 400, 0, 1000)).toBe(300);
    expect(topFor(100, 400, 50, 1000)).toBe(350);
    expect(topFor(100, 400, 0, 120)).toBe(120);
    expect(topFor(100, 60, 20, 1000)).toBe(0);
  });
});
