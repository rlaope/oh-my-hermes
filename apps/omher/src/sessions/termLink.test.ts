import { describe, expect, it } from "vitest";
import { findTermLinks, isCopyLinkKey, isLinkId, LINK_ID_LEN, newLinkId, parseTermLink, termLinkUrl } from "./termLink";
import { parseResume, RESUME_VERSION } from "../app/resume";
import { createSessions } from "./sessions";
import { MockHost } from "./host";
import { createStore, type BridgeLike } from "../state/store";
import { termMenuItems } from "./SessionsSection";

const key = (over: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => ({ key: "C", code: "KeyC", metaKey: false, ctrlKey: false, altKey: false, shiftKey: true, ...over });

describe("terminal link ids", () => {
  it("are 10 characters of lowercase base32, a different one each time", () => {
    const ids = new Set(Array.from({ length: 500 }, () => newLinkId()));
    expect(ids.size).toBe(500);
    for (const id of ids) {
      expect(id).toHaveLength(LINK_ID_LEN);
      expect(id).toMatch(/^[a-z2-7]{10}$/);
      expect(isLinkId(id)).toBe(true);
    }
  });

  it("use each byte's low five bits (every letter of the alphabet reachable)", () => {
    expect(newLinkId((b) => b.map((_, i) => i))).toBe("abcdefghij");
    expect(newLinkId((b) => b.fill(31))).toBe("7777777777");
    expect(newLinkId((b) => b.fill(32 + 25))).toBe("zzzzzzzzzz");
  });

  it("parse back from the link, and nothing that only looks like one", () => {
    expect(termLinkUrl("abcdefgh23")).toBe("omher://terminal/abcdefgh23");
    expect(parseTermLink("omher://terminal/abcdefgh23")).toBe("abcdefgh23");
    expect(parseTermLink(" omher://terminal/abcdefgh23/ ")).toBe("abcdefgh23");
    for (const bad of [
      "omher://terminal/abcdefgh2",
      "omher://terminal/abcdefgh234",
      "omher://terminal/ABCDEFGH23",
      "omher://terminal/abcdefgh01",
      "omher://terminal/abcdefgh23?x=1",
      "omher://terminal/abcdefgh23/x",
      "omher://bot/abcdefgh23",
      "https://terminal/abcdefgh23",
      "omher:terminal/abcdefgh23",
      null,
      undefined,
    ]) expect(parseTermLink(bad as string)).toBeNull();
    expect(isLinkId("abcdefgh2")).toBe(false);
    expect(isLinkId(12)).toBe(false);
  });

  it("are found in text with where each sits, not when glued to a word", () => {
    const text = "see omher://terminal/abcdefgh23, and (omher://terminal/zzzzzzzzzz) not xomher://terminal/aaaaaaaaaa nor omher://terminal/bbbbbbbbbbc";
    expect(findTermLinks(text)).toEqual([
      { url: "omher://terminal/abcdefgh23", id: "abcdefgh23", start: 4, end: 31 },
      { url: "omher://terminal/zzzzzzzzzz", id: "zzzzzzzzzz", start: 38, end: 65 },
    ]);
    expect(findTermLinks("no links here")).toEqual([]);
  });

  it("Copy link key: ⌘⇧C on macOS, Alt+Shift+C elsewhere (Ctrl+Shift+C stays the terminal's copy)", () => {
    expect(isCopyLinkKey(key({ metaKey: true }), true)).toBe(true);
    expect(isCopyLinkKey(key({ metaKey: true, key: "ㅊ" }), true)).toBe(true); // Korean layout: the key where C is
    expect(isCopyLinkKey(key({ metaKey: true, shiftKey: false, key: "c" }), true)).toBe(false); // ⌘C is copy
    expect(isCopyLinkKey(key({ metaKey: true, altKey: true }), true)).toBe(false);
    expect(isCopyLinkKey(key({ ctrlKey: true }), true)).toBe(false);
    expect(isCopyLinkKey(key({ altKey: true }), false)).toBe(true);
    expect(isCopyLinkKey(key({ ctrlKey: true }), false)).toBe(false);
    expect(isCopyLinkKey(key({ metaKey: true }), false)).toBe(false);
    expect(isCopyLinkKey(key({ altKey: true, key: "D", code: "KeyD" }), false)).toBe(false);
  });
});

function setup() {
  const g = globalThis as Record<string, unknown>;
  delete g.__omherSessionCalls;
  const host = new MockHost();
  const bridge: BridgeLike = { connect: async () => undefined, onAny: () => () => {}, onStatus: () => () => {}, request: (async () => ({})) as BridgeLike["request"] };
  const store = createStore(bridge);
  return { ss: createSessions(host, () => store), store };
}

describe("a TERMINALS session's link id", () => {
  it("is given when the session starts, one per session, and its row menu offers Copy link", () => {
    const { ss } = setup();
    const a = ss.startTerminal("shell", "/w/web-app")!;
    const b = ss.startTerminal("claude", "/w/web-app")!;
    const ra = ss.getState().list.find((r) => r.id === a)!;
    const rb = ss.getState().list.find((r) => r.id === b)!;
    expect(isLinkId(ra.linkId)).toBe(true);
    expect(isLinkId(rb.linkId)).toBe(true);
    expect(ra.linkId).not.toBe(rb.linkId);
    expect(ss.linkOf(a)).toBe(`omher://terminal/${ra.linkId}`);
    expect(ss.byLink(rb.linkId!)?.id).toBe(b);
    expect(ss.byLink("aaaaaaaaaa")).toBeNull();
    expect(termMenuItems(ra)).toEqual(["rename", "reveal", "terminal", "link", "here", "close"]);
    expect(termMenuItems({ cwd: "/w" })).toEqual(["rename", "reveal", "terminal", "here", "close"]);
  });

  it("is kept through the saved list; one saved before links existed (or a bad or clashing one) gets a fresh one", () => {
    const raw = JSON.stringify({
      v: RESUME_VERSION,
      at: 1,
      bot: null,
      view: "chat",
      session: null,
      panelOpen: false,
      panelTab: "details",
      runsFull: false,
      runId: null,
      drafts: {},
      sessions: [
        { id: "s1", linkId: "keepme2345", agent: "shell", cwd: "/w/a", startedAt: 1, view: "terminal", running: false, exitCode: 0 },
        { id: "s2", agent: "shell", cwd: "/w/b", startedAt: 1, view: "terminal", running: false, exitCode: 0 },
        { id: "s3", linkId: "NOT-AN-ID!", agent: "shell", cwd: "/w/c", startedAt: 1, view: "terminal", running: false, exitCode: 0 },
        { id: "s4", linkId: "keepme2345", agent: "shell", cwd: "/w/d", startedAt: 1, view: "terminal", running: false, exitCode: 0 },
      ],
    });
    const snap = parseResume(raw)!;
    expect(snap.sessions.map((s) => s.linkId)).toEqual(["keepme2345", undefined, undefined, "keepme2345"]);
    const { ss } = setup();
    ss.restore(snap.sessions);
    const ids = Object.fromEntries(ss.getState().list.map((r) => [r.id, r.linkId]));
    expect(ids.s1).toBe("keepme2345");
    for (const k of ["s2", "s3", "s4"]) expect(isLinkId(ids[k])).toBe(true);
    expect(new Set(Object.values(ids)).size).toBe(4);
  });
});
