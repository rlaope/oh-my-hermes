// TERMINALS folder prefs (`omher.term.folders`): the folders the person added from the right-click menu's
// "New folder…" are parsed defensively, listed once, put at the top of the saved order, and removed without
// touching the rest.
import { describe, expect, it } from "vitest";
import { addFolder, addedFolders, orderFolders, parseFolderPrefs, removeFolder, withAdded, type FolderPrefs } from "./folders";

const NONE: FolderPrefs = { collapsed: [], order: [] };
const shown = (p: FolderPrefs, sessions: string[]) => orderFolders(withAdded(sessions.map((cwd) => ({ cwd, rows: [cwd] })), addedFolders(p)), p.order).map((g) => g.cwd);

describe("parseFolderPrefs", () => {
  it("reads a record saved before `added` existed as none added, keeping what it had and adding no field", () => {
    const old = JSON.stringify({ collapsed: ["/a"], order: ["/b", "/a"] });
    const p = parseFolderPrefs(old);
    expect(addedFolders(p)).toEqual([]);
    expect("added" in p).toBe(false);
    // saved again, it is the record it was
    expect(JSON.stringify(p)).toBe(old);
  });

  it("keeps only strings in `added`, once each, never an empty path", () => {
    expect(addedFolders(parseFolderPrefs(JSON.stringify({ added: ["/a", 3, null, "/a", "", { cwd: "/x" }, "/b"] })))).toEqual(["/a", "/b"]);
  });

  it("reads anything that is not the record as empty", () => {
    for (const raw of [null, "", "not json", "[]", "7", JSON.stringify({ added: "/a" }), JSON.stringify({ added: { 0: "/a" } }), JSON.stringify({ added: [""] })]) {
      const p = parseFolderPrefs(raw);
      expect(p).toEqual(NONE);
      expect("added" in p).toBe(false);
    }
  });

  it("caps `added` at 200 folders", () => {
    const many = Array.from({ length: 260 }, (_, i) => `/f/${i}`);
    const got = addedFolders(parseFolderPrefs(JSON.stringify({ added: many })));
    expect(got).toHaveLength(200);
    expect(got[0]).toBe("/f/0");
  });
});

describe("addFolder", () => {
  it("adds a folder and puts it at the top of the saved order, above folders that were never dragged", () => {
    const p = addFolder(NONE, "/new", ["/s1", "/s2"]);
    expect(p.added).toEqual(["/new"]);
    expect(p.order).toEqual(["/new", "/s1", "/s2"]);
    expect(shown(p, ["/s1", "/s2"])).toEqual(["/new", "/s1", "/s2"]);
  });

  it("keeps the dragged order of the others under the new folder", () => {
    const p = addFolder({ collapsed: [], order: ["/s2", "/s1"], added: [] }, "/new", ["/s1", "/s2", "/s3"]);
    expect(shown(p, ["/s1", "/s2", "/s3"])).toEqual(["/new", "/s2", "/s1", "/s3"]);
  });

  it("a second added folder goes above the first", () => {
    const one = addFolder(NONE, "/a", []);
    const two = addFolder(one, "/b", addedFolders(one));
    expect(two.added).toEqual(["/b", "/a"]);
    expect(shown(two, [])).toEqual(["/b", "/a"]);
  });

  it("an added folder picked again is not listed twice and keeps its place; a collapsed one opens", () => {
    const base: FolderPrefs = { collapsed: ["/a"], order: ["/s1", "/a"], added: ["/a"] };
    const p = addFolder(base, "/a", ["/s1", "/a"]);
    expect(p.added).toEqual(["/a"]);
    expect(p.order).toEqual(["/s1", "/a"]);
    expect(p.collapsed).toEqual([]);
    // nothing to change: the same record, so nothing is saved again
    expect(addFolder(p, "/a", ["/s1", "/a"])).toBe(p);
  });

  it("a folder a session already lists only opens: it is not added and does not move", () => {
    const base: FolderPrefs = { collapsed: ["/s2"], order: [] };
    const p = addFolder(base, "/s2", ["/s1", "/s2"]);
    expect(p).toEqual({ collapsed: [], order: [] });
    expect("added" in p).toBe(false);
    expect(shown(p, ["/s1", "/s2"])).toEqual(["/s1", "/s2"]);
  });

  it("no folder (the dialog was cancelled) changes nothing", () => {
    const base: FolderPrefs = { collapsed: ["/a"], order: ["/a"], added: ["/a"] };
    expect(addFolder(base, "", ["/a"])).toBe(base);
  });

  it("holds at most 200 added folders, dropping the oldest", () => {
    let p = NONE;
    for (let i = 0; i < 205; i++) p = addFolder(p, `/f/${i}`, addedFolders(p));
    expect(addedFolders(p)).toHaveLength(200);
    expect(addedFolders(p)[0]).toBe("/f/204");
    expect(addedFolders(p)).not.toContain("/f/0");
    expect(p.order.length).toBeLessThanOrEqual(200);
  });

  it("survives the round trip through storage", () => {
    const p = addFolder(NONE, "/new", ["/s1"]);
    expect(parseFolderPrefs(JSON.stringify(p))).toEqual(p);
  });
});

describe("removeFolder", () => {
  it("takes the folder out of `added` and leaves the rest as it was", () => {
    const base: FolderPrefs = { collapsed: ["/a"], order: ["/a", "/b"], added: ["/a", "/b"] };
    expect(removeFolder(base, "/a")).toEqual({ collapsed: ["/a"], order: ["/a", "/b"], added: ["/b"] });
  });

  it("the last one removed leaves the record without the field, as before any was added", () => {
    const p = removeFolder({ collapsed: [], order: ["/a"], added: ["/a"] }, "/a");
    expect(p).toEqual({ collapsed: [], order: ["/a"] });
    expect("added" in p).toBe(false);
  });

  it("a folder that was never added is left alone", () => {
    const base: FolderPrefs = { collapsed: [], order: ["/s1"], added: ["/a"] };
    expect(removeFolder(base, "/s1")).toBe(base);
  });

  it("removed while a session still runs there, the group stays in its saved place", () => {
    const p = removeFolder({ collapsed: [], order: ["/a", "/s1"], added: ["/a"] }, "/a");
    expect(shown(p, ["/s1", "/a"])).toEqual(["/a", "/s1"]);
    expect(shown(p, ["/s1"])).toEqual(["/s1"]);
  });
});

describe("withAdded", () => {
  it("gives an added folder with no session an empty group, and one with sessions no second group", () => {
    const groups = [{ cwd: "/s1", rows: ["a", "b"] }];
    expect(withAdded(groups, ["/s1", "/new"])).toEqual([
      { cwd: "/s1", rows: ["a", "b"] },
      { cwd: "/new", rows: [] },
    ]);
    expect(withAdded(groups, [])).toEqual(groups);
  });
});
