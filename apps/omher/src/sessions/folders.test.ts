// TERMINALS folder prefs (`omher.term.folders`): the folders the person added from the right-click menu's
// "New folder…" are parsed defensively, listed once, put at the top of the saved order, and removed without
// touching the rest.
import { describe, expect, it } from "vitest";
import { addFolder, addedFolders, allCollapsed, folderSummary, goneFolders, isFolderGone, ranElsewhere, setFolderGone, collapseOthers, folderGroups, isAddedFolder, pathKey, pathSpelling, isCollapsed, moveFolder, orderFolders, parseFolderPrefs, removeFolder, setAllFolders, toggleFolder, withAdded, type FolderPrefs } from "./folders";

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
    expect(pathSpelling("C:\\")).toBe("C:\\");
    expect(pathSpelling("C:/")).toBe("C:\\");
    expect(pathSpelling("C:\\\\")).toBe("C:\\");
    expect(pathSpelling("C:\\Users\\you\\app\\")).toBe("C:\\Users\\you\\app");
    expect(pathSpelling("C:/Users//you/app/")).toBe("C:\\Users\\you\\app");
    expect(pathSpelling("\\\\server\\share\\app\\")).toBe("\\\\server\\share\\app");
    // a backslash in a Unix folder's name is part of the name
    expect(pathSpelling("/home/you/odd\\name/")).toBe("/home/you/odd\\name");
    expect(pathKey("/home/you/odd\\name/")).toBe("/home/you/odd\\name");
  });

  it("is one key for a folder composed (NFC) or decomposed (NFD), as macOS hands a shell's folder over", () => {
    const nfc = "/Users/you/문서/보고서";
    const nfd = nfc.normalize("NFD");
    expect(nfd).not.toBe(nfc);
    expect(pathKey(nfd)).toBe(pathKey(nfc));
    expect(pathKey(`${nfd}/`)).toBe(nfc);
    expect(pathKey("/Users/you/Cafe\u0301")).toBe(pathKey("/Users/you/Caf\u00e9"));
    // the spelling keeps the letters as they came: what a shell is started in is the system's own path
    expect(pathSpelling(`${nfd}/`)).toBe(nfd);
  });

  it("folds case for a drive-letter path only: never for a macOS or Linux path, nor a share", () => {
    expect(pathKey("C:\\Users\\You\\App")).toBe(pathKey("c:/users/you/app/"));
    expect(pathKey("C:\\")).toBe(pathKey("c:\\"));
    expect(pathKey("C:\\보고서")).toBe(pathKey("c:\\" + "보고서".normalize("NFD")));
    expect(pathKey("/Users/you/App")).not.toBe(pathKey("/users/you/app"));
    expect(pathKey("/home/you/Code")).toBe("/home/you/Code");
    expect(pathKey("\\\\Server\\Share")).toBe("\\\\Server\\Share");
    // and the spelling keeps the case
    expect(pathSpelling("C:/Users/You/")).toBe("C:\\Users\\You");
  });

  it("never expands `~`, and is the same again when applied twice", () => {
    expect(pathKey("~/code/")).toBe("~/code");
    expect(pathKey("~")).toBe("~");
    for (const p of ["/a/b/", "C:/x//y/", "\\\\s\\t\\", "/", "C:\\", "~/x/"]) expect(pathKey(pathKey(p))).toBe(pathKey(p));
    for (const p of ["/a/b/", "C:/X//y/", "\\\\s\\t\\", "/", "~/x/", "/한/".normalize("NFD")]) expect(pathSpelling(pathSpelling(p))).toBe(pathSpelling(p));
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

// A Korean folder from a shell (decomposed on macOS) and the same folder from the dialog (composed), and a Windows
// drive path in either case: one group, one saved state. Records saved while the key was the spelling alone read
// with their collapsed and order state found under the new key.
describe("one group per folder, however it is composed or (on Windows) cased", () => {
  const NFC = "/Users/you/문서";
  const NFD = NFC.normalize("NFD");

  it("sessions in both forms are one group, named and started in as the first session spelled it", () => {
    const g = folderGroups([{ cwd: NFD, id: 1 }, { cwd: NFC, id: 2 }, { cwd: "C:\\Users\\you", id: 3 }, { cwd: "c:/users/you/", id: 4 }]);
    expect(g.map((x) => x.cwd)).toEqual([NFD, "C:\\Users\\you"]);
    expect(g.map((x) => x.rows.map((r) => r.id))).toEqual([[1, 2], [3, 4]]);
  });

  it("a folder picked composed that a shell reported decomposed only opens that group; picked again, it adds nothing", () => {
    const base: FolderPrefs = { collapsed: [pathKey(NFD)], order: [] };
    const listed = folderGroups([{ cwd: NFD }]).map((g) => g.cwd);
    const p = addFolder(base, NFC, listed);
    expect(p).toEqual({ collapsed: [], order: [] });
    const added = addFolder(NONE, NFD, []);
    // kept as the dialog spelled it, found by either form
    expect(added.added).toEqual([NFD]);
    expect(isAddedFolder(added, NFC)).toBe(true);
    expect(addFolder(added, NFC, addedFolders(added))).toBe(added);
    // a session there in the other form makes the one group
    expect(shown(added, [NFC])).toEqual([NFC]);
    expect(removeFolder(added, NFC)).toEqual({ collapsed: [], order: [NFC] });
  });

  it("collapse and order follow the folder in either form", () => {
    const p = toggleFolder(NONE, NFD);
    expect(isCollapsed(p, NFC)).toBe(true);
    expect(orderFolders([{ cwd: "/b" }, { cwd: NFC }], moveFolder(["/b", NFD], NFD, 0)).map((g) => g.cwd)).toEqual([NFC, "/b"]);
    expect(isCollapsed(toggleFolder(NONE, "C:\\Users\\You"), "c:\\users\\you")).toBe(true);
    expect(isCollapsed(toggleFolder(NONE, "/Users/You"), "/users/you")).toBe(false);
  });

  it("a record saved under the old keys keeps its collapsed folders and its order", () => {
    // as saved before: keyed by the spelling only, so a decomposed name and a Windows path in its own case
    const old = JSON.stringify({ collapsed: [NFD, "C:\\Users\\You\\App"], order: ["/b", NFD, "C:\\Users\\You\\App", NFC], added: [NFD, NFC] });
    const p = parseFolderPrefs(old);
    expect(p.collapsed).toEqual([NFC, "c:\\users\\you\\app"]);
    // two saved names of one folder are one, at the first one's place
    expect(p.order).toEqual(["/b", NFC, "c:\\users\\you\\app"]);
    expect(p.added).toEqual([NFD]);
    for (const cwd of [NFC, NFD]) expect(isCollapsed(p, cwd)).toBe(true);
    expect(isCollapsed(p, "c:/users/you/app")).toBe(true);
    const groups = orderFolders(withAdded(folderGroups([{ cwd: "C:\\Users\\You\\App" }, { cwd: NFC }, { cwd: "/b" }]), addedFolders(p)), p.order);
    expect(groups.map((g) => g.cwd)).toEqual(["/b", NFC, "C:\\Users\\You\\App"]);
    // saved again and read back, it is the same record
    expect(parseFolderPrefs(JSON.stringify(p))).toEqual(p);
  });

  it("a folder found gone is found in either form", () => {
    setFolderGone(NFD, true);
    expect(isFolderGone(NFC)).toBe(true);
    expect(ranElsewhere(NFC, NFD)).toBeNull();
    expect(ranElsewhere("C:\\Users\\you", "c:\\users\\you")).toBeNull();
    setFolderGone(NFC, false);
    expect(goneFolders()).toEqual([]);
  });
});

// A listed folder that is no longer on disk (review round 1, BLOCKING 7): the host starts the shell in home and says
// so (`ShellStarted.cwd`); the page must notice, not list the row under the dead folder.
describe("a folder found gone", () => {
  it("ranElsewhere is the folder the shell runs in only when that is not the one asked for", () => {
    expect(ranElsewhere("/home/you/gone", "/home/you")).toBe("/home/you");
    expect(ranElsewhere("/home/you/app", "/home/you/app")).toBeNull();
    // another spelling of the folder asked for is that folder
    expect(ranElsewhere("/home/you/app/", "/home/you/app")).toBeNull();
    expect(ranElsewhere("C:/Users/you/app/", "C:\\Users\\you\\app")).toBeNull();
    // asked for no folder (home): nothing is gone
    expect(ranElsewhere("", "/home/you")).toBeNull();
    expect(ranElsewhere(null, "/home/you")).toBeNull();
    expect(ranElsewhere("/home/you/gone", "")).toBeNull();
  });

  it("is remembered by its one spelling until a shell starts there or the list forgets it, and is never saved", () => {
    expect(goneFolders()).toEqual([]);
    setFolderGone("/home/you/gone/", true);
    setFolderGone("/home/you/gone", true);
    expect(goneFolders()).toEqual(["/home/you/gone"]);
    expect(isFolderGone("/home/you/gone//")).toBe(true);
    expect(isFolderGone("/home/you")).toBe(false);
    const same = goneFolders();
    setFolderGone("/home/you/gone", true);
    // nothing changed: the same list, so nothing re-renders
    expect(goneFolders()).toBe(same);
    setFolderGone("/home/you/gone/", false);
    expect(goneFolders()).toEqual([]);
    setFolderGone("", true);
    expect(goneFolders()).toEqual([]);
  });
});

describe("folderSummary", () => {
  it("counts only a known wait (a bot's request, `bell`) as needs; an unseen ring is news", () => {
    expect(folderSummary(["news", null])).toEqual({ count: 2, busy: false, needs: false, news: true, failed: false });
    expect(folderSummary(["bell", "busy"])).toEqual({ count: 2, busy: true, needs: true, news: false, failed: false });
    expect(folderSummary(["news", "bell", "err"])).toEqual({ count: 3, busy: false, needs: true, news: true, failed: true });
    expect(folderSummary([])).toEqual({ count: 0, busy: false, needs: false, news: false, failed: false });
  });
});
