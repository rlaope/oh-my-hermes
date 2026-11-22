// TERMINALS folder prefs (`omher.term.folders`): the folders the person added from the right-click menu's
// "New folder…" are parsed defensively, listed once, put at the top of the saved order, and removed without
// touching the rest.
import { describe, expect, it } from "vitest";
import { addFolder, addedFolders, allCollapsed, collapseOthers, folderGroups, pathKey, isCollapsed, moveFolder, orderFolders, parseFolderPrefs, removeFolder, setAllFolders, toggleFolder, withAdded, type FolderPrefs } from "./folders";

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

// One identity per folder (review round 1, BLOCKING 6): `/a/b` and `/a/b/` are one group, in what is picked, in a
// session's folder and in a record saved before the paths were normalised.
describe("pathKey", () => {
  it("drops a trailing separator and repeated ones, and keeps a root", () => {
    expect(pathKey("/home/you/code/web-app/")).toBe("/home/you/code/web-app");
    expect(pathKey("/home/you//code///web-app//")).toBe("/home/you/code/web-app");
    expect(pathKey("/home/you/code/web-app")).toBe("/home/you/code/web-app");
    expect(pathKey("/")).toBe("/");
    expect(pathKey("//")).toBe("/");
    expect(pathKey("")).toBe("");
  });

  it("spells a Windows path with backslashes, keeping the drive root and a share's two leading ones", () => {
    expect(pathKey("C:\\")).toBe("C:\\");
    expect(pathKey("C:/")).toBe("C:\\");
    expect(pathKey("C:\\\\")).toBe("C:\\");
    expect(pathKey("C:\\Users\\you\\app\\")).toBe("C:\\Users\\you\\app");
    expect(pathKey("C:/Users//you/app/")).toBe("C:\\Users\\you\\app");
    expect(pathKey("\\\\server\\share\\app\\")).toBe("\\\\server\\share\\app");
    // a backslash in a Unix folder's name is part of the name
    expect(pathKey("/home/you/odd\\name/")).toBe("/home/you/odd\\name");
  });

  it("never expands `~`, and is the same again when applied twice", () => {
    expect(pathKey("~/code/")).toBe("~/code");
    expect(pathKey("~")).toBe("~");
    for (const p of ["/a/b/", "C:/x//y/", "\\\\s\\t\\", "/", "C:\\", "~/x/"]) expect(pathKey(pathKey(p))).toBe(pathKey(p));
  });
});

describe("one group per folder, however its path is spelled", () => {
  const WEB = "/home/you/code/web-app";

  it("a record saved with the other spelling reads as that folder, once (collapsed, order and added)", () => {
    const p = parseFolderPrefs(JSON.stringify({ collapsed: [`${WEB}/`, WEB], order: [`${WEB}/`, "/b//", WEB, "/b"], added: [`${WEB}/`, WEB, "/c/"] }));
    expect(p).toEqual({ collapsed: [WEB], order: [WEB, "/b"], added: [WEB, "/c"] });
  });

  it("a saved `~` folder is not kept as an added folder, and picking one adds nothing", () => {
    expect(parseFolderPrefs(JSON.stringify({ collapsed: [], order: [], added: ["~/code", "~", "/ok"] })).added).toEqual(["/ok"]);
    expect(addFolder(NONE, "~/code", [])).toBe(NONE);
    expect(addFolder(NONE, "~", [])).toBe(NONE);
  });

  it("sessions whose folder is spelled both ways are one group, named without the trailing separator", () => {
    const g = folderGroups([{ cwd: `${WEB}/`, id: 1 }, { cwd: "/b", id: 2 }, { cwd: WEB, id: 3 }]);
    expect(g.map((x) => x.cwd)).toEqual([WEB, "/b"]);
    expect(g[0].rows.map((r) => r.id)).toEqual([1, 3]);
    // the rows are the same objects, their own `cwd` as it was
    expect(g[0].rows[0].cwd).toBe(`${WEB}/`);
  });

  it("picking an alias of an added folder adds no second one, keeps its place and opens it", () => {
    for (const [have, picked] of [[WEB, `${WEB}/`], [`${WEB}/`, WEB]] as const) {
      const base = parseFolderPrefs(JSON.stringify({ collapsed: [have], order: ["/s1", have], added: [have] }));
      const p = addFolder(base, picked, ["/s1", ...addedFolders(base)]);
      expect(p.added).toEqual([WEB]);
      expect(p.order).toEqual(["/s1", WEB]);
      expect(p.collapsed).toEqual([]);
      expect(shown(p, ["/s1"])).toEqual(["/s1", WEB]);
    }
  });

  it("picking an alias of a folder a session lists only opens that group", () => {
    const base: FolderPrefs = { collapsed: [WEB], order: [] };
    const listed = folderGroups([{ cwd: `${WEB}/` }]).map((g) => g.cwd);
    const p = addFolder(base, `${WEB}//`, listed);
    expect(p).toEqual({ collapsed: [], order: [] });
    expect(shown(p, listed)).toEqual([WEB]);
  });

  it("an added folder and a session in its alias make one group; the saved order and collapse find it", () => {
    const p = parseFolderPrefs(JSON.stringify({ collapsed: [`${WEB}/`], order: ["/b", `${WEB}/`], added: [`${WEB}/`] }));
    const groups = orderFolders(withAdded(folderGroups([{ cwd: WEB }, { cwd: "/b" }]), addedFolders(p)), p.order);
    expect(groups.map((g) => g.cwd)).toEqual(["/b", WEB]);
    expect(isCollapsed(p, WEB)).toBe(true);
    expect(isCollapsed(p, `${WEB}/`)).toBe(true);
    expect(allCollapsed(p, [`${WEB}/`])).toBe(true);
    // an order named in the other spelling by a caller still places the group
    expect(orderFolders([{ cwd: "/b" }, { cwd: WEB }], [`${WEB}/`, "/b"]).map((g) => g.cwd)).toEqual([WEB, "/b"]);
  });

  it("collapse, collapse all, collapse others, move and remove act on the one folder whichever spelling names it", () => {
    const p: FolderPrefs = { collapsed: [], order: [], added: [WEB] };
    expect(toggleFolder(p, `${WEB}/`).collapsed).toEqual([WEB]);
    expect(toggleFolder(toggleFolder(p, `${WEB}/`), WEB).collapsed).toEqual([]);
    expect(setAllFolders(p, [`${WEB}/`, "/b"], true).collapsed).toEqual([WEB, "/b"]);
    expect(collapseOthers(p, [WEB, "/b"], `${WEB}/`).collapsed).toEqual(["/b"]);
    expect(moveFolder([WEB, "/b", "/c"], `${WEB}/`, 2)).toEqual(["/b", "/c", WEB]);
    expect(removeFolder(p, `${WEB}/`)).toEqual({ collapsed: [], order: [] });
  });
});
