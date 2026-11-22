import { describe, expect, it } from "vitest";
import { clampRatio, equalize, MAX_PANES, neighbor, paneKey, panesOf, paneRects, parseLayout, removePane, setRatioAt, splitLayout, stepPane, swapPanes, type Layout } from "./layout";

const key = (k: Partial<{ key: string; code: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }>) => ({ key: "", metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...k });

describe("a panel tab's pane layout", () => {
  it("splits a pane right or down, half each, and keeps reading order", () => {
    let l: Layout = { pane: 1 };
    l = splitLayout(l, 1, "row", 2)!;
    expect(l).toEqual({ dir: "row", ratio: 0.5, a: { pane: 1 }, b: { pane: 2 } });
    l = splitLayout(l, 2, "col", 3)!;
    expect(l).toEqual({ dir: "row", ratio: 0.5, a: { pane: 1 }, b: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } } });
    expect(panesOf(l)).toEqual([1, 2, 3]);
    expect(splitLayout(l, 9, "row", 4)).toBeNull(); // no such pane
    expect(splitLayout(l, 1, "row", 3)).toBeNull(); // id already used
    expect(splitLayout({ pane: 1 }, 1, "col", 2, true)).toEqual({ dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 1 } }); // over it
  });

  it("holds at most four panes", () => {
    let l: Layout = { pane: 1 };
    for (let id = 2; id <= MAX_PANES; id++) l = splitLayout(l, id - 1, id % 2 ? "row" : "col", id)!;
    expect(panesOf(l)).toHaveLength(4);
    expect(splitLayout(l, 1, "row", 5)).toBeNull();
  });

  it("closing a pane gives its room to the part beside it, and names who takes the keyboard", () => {
    const l: Layout = { dir: "row", ratio: 0.3, a: { pane: 1 }, b: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } } };
    expect(removePane(l, 1)).toEqual({ layout: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } }, heir: 2 });
    expect(removePane(l, 3)).toEqual({ layout: { dir: "row", ratio: 0.3, a: { pane: 1 }, b: { pane: 2 } }, heir: 2 });
    expect(removePane(l, 2).layout).toEqual({ dir: "row", ratio: 0.3, a: { pane: 1 }, b: { pane: 3 } });
    expect(removePane({ pane: 1 }, 1)).toEqual({ layout: null, heir: null });
    expect(removePane(l, 7)).toEqual({ layout: l, heir: null });
  });

  it("equalizes along each line of splits (three side by side get a third each)", () => {
    const l: Layout = { dir: "row", ratio: 0.8, a: { pane: 1 }, b: { dir: "row", ratio: 0.2, a: { pane: 2 }, b: { pane: 3 } } };
    const e = equalize(l);
    const r = paneRects(e);
    for (const id of [1, 2, 3]) expect(r.get(id)!.w).toBeCloseTo(1 / 3);
    // a split the other way stays half and half
    const m = equalize({ dir: "row", ratio: 0.9, a: { pane: 1 }, b: { dir: "col", ratio: 0.1, a: { pane: 2 }, b: { pane: 3 } } });
    expect(m).toMatchObject({ ratio: 0.5, b: { ratio: 0.5 } });
  });

  it("moves a divider by its path", () => {
    const l: Layout = { dir: "row", ratio: 0.5, a: { pane: 1 }, b: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } } };
    expect(setRatioAt(l, "", 0.7)).toMatchObject({ ratio: 0.7, b: { ratio: 0.5 } });
    expect(setRatioAt(l, "b", 0.25)).toMatchObject({ ratio: 0.5, b: { ratio: 0.25 } });
  });

  it("keeps each side of a divider at its least size", () => {
    expect(clampRatio(0.01, 1000, 120)).toBeCloseTo(0.12);
    expect(clampRatio(0.99, 1000, 120)).toBeCloseTo(0.88);
    expect(clampRatio(0.4, 1000, 120)).toBe(0.4);
    expect(clampRatio(0.1, 200, 120)).toBe(0.5); // no room for both
    expect(clampRatio(NaN, 1000, 120)).toBe(0.5);
  });

  it("finds the pane beside the focused one in each direction", () => {
    // 1 | 2
    //   | 3
    const l: Layout = { dir: "row", ratio: 0.5, a: { pane: 1 }, b: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } } };
    expect(neighbor(l, 1, "right")).toBe(2);
    expect(neighbor(l, 3, "left")).toBe(1);
    expect(neighbor(l, 2, "down")).toBe(3);
    expect(neighbor(l, 3, "up")).toBe(2);
    expect(neighbor(l, 1, "left")).toBeNull();
    expect(neighbor(l, 2, "right")).toBeNull();
  });

  it("reads the pane keys: ⌘D / ⌘⇧D / ⌘W / ⌘⌥arrows on macOS, Ctrl+Shift+D / Alt+Shift+D / Ctrl+Shift+W / Ctrl+Alt+arrows elsewhere", () => {
    expect(paneKey(key({ key: "d", code: "KeyD", metaKey: true }), true)).toEqual({ kind: "split", dir: "right" });
    expect(paneKey(key({ key: "D", code: "KeyD", metaKey: true, shiftKey: true }), true)).toEqual({ kind: "split", dir: "down" });
    expect(paneKey(key({ key: "ㅇ", code: "KeyD", metaKey: true }), true)).toEqual({ kind: "split", dir: "right" }); // Korean layout
    expect(paneKey(key({ key: "w", code: "KeyW", metaKey: true }), true)).toEqual({ kind: "close" });
    expect(paneKey(key({ key: "ArrowLeft", metaKey: true, altKey: true }), true)).toEqual({ kind: "focus", dir: "left" });
    expect(paneKey(key({ key: "d", code: "KeyD", ctrlKey: true }), true)).toBeNull(); // Ctrl+D is the shell's
    expect(paneKey(key({ key: "k", code: "KeyK", metaKey: true }), true)).toBeNull();
    expect(paneKey(key({ key: "d", code: "KeyD", ctrlKey: true }), false)).toBeNull(); // Ctrl+D off macOS: the shell's
    expect(paneKey(key({ key: "w", code: "KeyW", ctrlKey: true }), false)).toBeNull(); // Ctrl+W: the shell's
    expect(paneKey(key({ key: "D", code: "KeyD", ctrlKey: true, shiftKey: true }), false)).toEqual({ kind: "split", dir: "right" });
    expect(paneKey(key({ key: "D", code: "KeyD", altKey: true, shiftKey: true }), false)).toEqual({ kind: "split", dir: "down" });
    expect(paneKey(key({ key: "W", code: "KeyW", ctrlKey: true, shiftKey: true }), false)).toEqual({ kind: "close" });
    expect(paneKey(key({ key: "ArrowUp", ctrlKey: true, altKey: true }), false)).toEqual({ kind: "focus", dir: "up" });
  });

  it("reads the other pane keys: step, move, zoom, equalize (⌘] ⌘[ ⌘⇧⌥arrows ⌘⇧↩ ⌘⌃= / Ctrl+Tab Ctrl+Alt+Shift+arrows Ctrl+Shift+Enter Ctrl+Alt+=)", () => {
    expect(paneKey(key({ key: "]", code: "BracketRight", metaKey: true }), true)).toEqual({ kind: "step", step: 1 });
    expect(paneKey(key({ key: "[", code: "BracketLeft", metaKey: true }), true)).toEqual({ kind: "step", step: -1 });
    expect(paneKey(key({ key: "}", code: "BracketRight", metaKey: true, shiftKey: true }), true)).toBeNull(); // ⌘⇧] is the next session
    expect(paneKey(key({ key: "ArrowRight", metaKey: true, altKey: true, shiftKey: true }), true)).toEqual({ kind: "move", dir: "right" });
    expect(paneKey(key({ key: "Enter", metaKey: true, shiftKey: true }), true)).toEqual({ kind: "zoom" });
    expect(paneKey(key({ key: "Enter", metaKey: true }), true)).toBeNull();
    expect(paneKey(key({ key: "=", code: "Equal", metaKey: true, ctrlKey: true }), true)).toEqual({ kind: "equalize" });
    expect(paneKey(key({ key: "=", code: "Equal", metaKey: true }), true)).toBeNull(); // ⌘= stays the page's
    expect(paneKey(key({ key: "Tab", ctrlKey: true }), false)).toEqual({ kind: "step", step: 1 });
    expect(paneKey(key({ key: "Tab", ctrlKey: true, shiftKey: true }), false)).toEqual({ kind: "step", step: -1 });
    expect(paneKey(key({ key: "ArrowLeft", ctrlKey: true, altKey: true, shiftKey: true }), false)).toEqual({ kind: "move", dir: "left" });
    expect(paneKey(key({ key: "Enter", ctrlKey: true, shiftKey: true }), false)).toEqual({ kind: "zoom" });
    expect(paneKey(key({ key: "=", code: "Equal", ctrlKey: true, altKey: true }), false)).toEqual({ kind: "equalize" });
    expect(paneKey(key({ key: "Tab" }), false)).toBeNull();
    expect(paneKey(key({ key: "]", code: "BracketRight", ctrlKey: true }), false)).toBeNull(); // Ctrl+] is the program's
  });

  it("AltGr (read as Ctrl+Alt off macOS) types its character: } on French AZERTY, ~ Swiss, | Danish, never equalize", () => {
    const altGr = (k: string, code: string) => ({ ...key({ key: k, code, ctrlKey: true, altKey: true }), getModifierState: (m: string) => m === "AltGraph" });
    expect(paneKey(altGr("}", "Equal"), false)).toBeNull();
    expect(paneKey(altGr("~", "Equal"), false)).toBeNull();
    expect(paneKey(altGr("|", "Equal"), false)).toBeNull();
    // the layout's Ctrl+Alt on that key still types a character (no AltGraph state reported): not equalize either
    expect(paneKey(key({ key: "}", code: "Equal", ctrlKey: true, altKey: true }), false)).toBeNull();
    // AltGr itself on a key that says =: still the layout's
    expect(paneKey(altGr("=", "Equal"), false)).toBeNull();
    // a US layout's Ctrl+Alt+= (or +) evens them out as before
    expect(paneKey(key({ key: "=", code: "Equal", ctrlKey: true, altKey: true }), false)).toEqual({ kind: "equalize" });
    expect(paneKey({ ...key({ key: "+", code: "Equal", ctrlKey: true, altKey: true }), getModifierState: () => false }, false)).toEqual({ kind: "equalize" });
  });

  it("swaps two panes, steps through them in reading order, and reads a saved layout back checked", () => {
    const l: Layout = { dir: "row", ratio: 0.3, a: { pane: 1 }, b: { dir: "col", ratio: 0.5, a: { pane: 2 }, b: { pane: 3 } } };
    expect(panesOf(swapPanes(l, 1, 3))).toEqual([3, 2, 1]);
    expect(swapPanes(l, 1, 9)).toBe(l);
    expect(stepPane(l, 3, 1)).toBe(1);
    expect(stepPane(l, 1, -1)).toBe(3);
    expect(stepPane({ pane: 1 }, 1, 1)).toBeNull();
    expect(parseLayout(JSON.parse(JSON.stringify(l)))).toEqual(l);
    expect(parseLayout({ dir: "row", ratio: 0.5, a: { pane: 1 }, b: { pane: 1 } })).toBeNull();
    expect(parseLayout({ pane: 1.5 })).toBeNull();
    expect(parseLayout("x")).toBeNull();
  });
});
