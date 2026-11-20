import { describe, expect, it, vi } from "vitest";
import { createCloseGrace, graceMs, GRACE_SHOWN, isUndoKey } from "./closeGrace";
import { parseTermSettings, TERM_DEFAULTS, TERM_UNDO_CLOSE } from "./term/settings";

function rig() {
  let t = 1_000;
  const timers: { at: number; fn: () => void; id: number; gone?: boolean }[] = [];
  let seq = 0;
  const expire = vi.fn();
  const g = createCloseGrace<{ term: object }>({
    expire,
    now: () => t,
    setTimer: (fn, ms) => {
      const x = { at: t + ms, fn, id: ++seq };
      timers.push(x);
      return x.id;
    },
    clearTimer: (h) => {
      const x = timers.find((y) => y.id === h);
      if (x) x.gone = true;
    },
  });
  const advance = (ms: number) => {
    t += ms;
    for (const x of timers) if (!x.gone && x.at <= t) {
      x.gone = true;
      x.fn();
    }
  };
  return { g, expire, advance, setNow: (v: number) => (t = v), timers };
}

describe("close grace", () => {
  it("counts the deadline from the close and runs the old close once at it", () => {
    const { g, expire, advance } = rig();
    const term = {};
    const e = g.begin("s1", "web · Shell", 10_000, { term })!;
    expect(e.closedAt).toBe(1_000);
    expect(e.until).toBe(11_000);
    advance(9_999);
    expect(expire).not.toHaveBeenCalled();
    expect(g.has("s1")).toBe(true);
    advance(1);
    expect(expire).toHaveBeenCalledTimes(1);
    expect(expire.mock.calls[0][0].data.term).toBe(term);
    expect(g.has("s1")).toBe(false);
    advance(20_000);
    g.sweep();
    expect(expire).toHaveBeenCalledTimes(1);
  });

  it("undo gives the same object back and the old close never runs", () => {
    const { g, expire, advance } = rig();
    const term = {};
    g.begin("s1", "a", 10_000, { term });
    const back = g.undo("s1");
    expect(back?.data.term).toBe(term);
    advance(60_000);
    expect(expire).not.toHaveBeenCalled();
    expect(g.undo("s1")).toBeNull();
    expect(g.list()).toEqual([]);
  });

  it("Off (0 s) holds nothing: the caller closes as before", () => {
    const { g, expire } = rig();
    expect(g.begin("s1", "a", 0, { term: {} })).toBeNull();
    expect(g.has("s1")).toBe(false);
    expect(expire).not.toHaveBeenCalled();
    expect(graceMs(0)).toBe(0);
    expect(graceMs(0, 300)).toBe(0);
    expect(graceMs(5)).toBe(5_000);
    expect(graceMs(10, 300)).toBe(300);
    expect(graceMs(10, "x")).toBe(10_000);
    expect(graceMs(10, 0)).toBe(0);
  });

  it("keeps each close's own deadline, newest first; the sweep runs the ones that passed", () => {
    const { g, expire, advance, setNow } = rig();
    g.begin("s1", "a", 10_000, { term: {} });
    advance(2_000);
    g.begin("s2", "b", 10_000, { term: {} });
    advance(2_000);
    g.begin("s3", "c", 10_000, { term: {} });
    advance(1_000);
    g.begin("s4", "d", 10_000, { term: {} });
    expect(g.list().map((x) => x.id)).toEqual(["s4", "s3", "s2", "s1"]);
    expect(GRACE_SHOWN).toBe(3);
    advance(5_000); // 10 s after s1
    expect(expire.mock.calls.map((c) => c[0].id)).toEqual(["s1"]);
    // a hidden window held the timers back: the sweep catches up by the clock
    setNow(1_000 + 14_500);
    g.sweep();
    expect(expire.mock.calls.map((c) => c[0].id)).toEqual(["s1", "s2", "s3"]);
    expect(g.list().map((x) => x.id)).toEqual(["s4"]);
  });

  it("finish runs the old close now; holding the same id twice does nothing", () => {
    const { g, expire } = rig();
    g.begin("s1", "a", 10_000, { term: {} });
    expect(g.begin("s1", "a", 10_000, { term: {} })).toBeNull();
    expect(g.finish("s1")).toBe(true);
    expect(g.finish("s1")).toBe(false);
    expect(expire).toHaveBeenCalledTimes(1);
  });

  it("tells listeners on every change and keeps a stable snapshot between them", () => {
    const { g } = rig();
    const fn = vi.fn();
    const off = g.subscribe(fn);
    const a = g.list();
    expect(g.list()).toBe(a);
    g.begin("s1", "a", 10_000, { term: {} });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(g.list()).not.toBe(a);
    g.undo("s1");
    expect(fn).toHaveBeenCalledTimes(2);
    off();
    g.begin("s2", "a", 10_000, { term: {} });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("the undo key: ⌘Z on macOS, Ctrl+Shift+Z elsewhere; plain Ctrl+Z stays the program's", () => {
    const k = (key: string, m: Partial<{ metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => ({ key, metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...m });
    expect(isUndoKey(k("z", { metaKey: true }), true)).toBe(true);
    expect(isUndoKey(k("z", { ctrlKey: true }), true)).toBe(false);
    expect(isUndoKey(k("z", { metaKey: true, shiftKey: true }), true)).toBe(false);
    expect(isUndoKey(k("Z", { ctrlKey: true, shiftKey: true }), false)).toBe(true);
    expect(isUndoKey(k("z", { ctrlKey: true }), false)).toBe(false);
    expect(isUndoKey(k("z", { ctrlKey: true, shiftKey: true, altKey: true }), false)).toBe(false);
  });
});

describe("undo window setting", () => {
  it("defaults to 10 s and takes only Off / 5 / 10", () => {
    expect(TERM_DEFAULTS.undoClose).toBe(10);
    expect(TERM_UNDO_CLOSE).toEqual([0, 5, 10]);
    expect(parseTermSettings({}).undoClose).toBe(10);
    expect(parseTermSettings({ undoClose: 0 }).undoClose).toBe(0);
    expect(parseTermSettings({ undoClose: 5 }).undoClose).toBe(5);
    expect(parseTermSettings({ undoClose: 7 }).undoClose).toBe(10);
    expect(parseTermSettings({ undoClose: "5" }).undoClose).toBe(10);
  });
});
