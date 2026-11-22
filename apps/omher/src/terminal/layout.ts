// A bottom-panel tab's panes: a binary layout tree (a pane, or two parts side by side or one over the other), kept
// apart from React and xterm so it can be tested on its own. Each pane is one login shell. A tab holds at most
// MAX_PANES. Splitting a pane puts the new one right of it (`row`) or under it (`col`); closing a pane gives its room to
// the part beside it. Also: where a pane sits (for the focus keys) and the split keys themselves.

export type SplitDir = "row" | "col";
export type Layout = { pane: number } | { dir: SplitDir; ratio: number; a: Layout; b: Layout };
export type FocusDir = "left" | "right" | "up" | "down";

/** Most panes a tab holds (as Orca and Otty keep a split usable at panel height). */
export const MAX_PANES = 4;
/** The least a pane keeps across a divider: 120 px wide, 4 rows tall. */
export const PANE_MIN_W = 120;
export const PANE_MIN_ROWS = 4;

export const isPane = (l: Layout): l is { pane: number } => "pane" in l;

/** The panes in reading order (left to right, top to bottom within each split). */
export function panesOf(l: Layout): number[] {
  return isPane(l) ? [l.pane] : [...panesOf(l.a), ...panesOf(l.b)];
}

/** Split pane `target`, putting pane `id` right of it (`row`) or under it (`col`), half each; `before`: left of it or
 *  over it instead. Null when the tab is full or `target` is not in it. */
export function splitLayout(l: Layout, target: number, dir: SplitDir, id: number, before = false): Layout | null {
  const all = panesOf(l);
  if (all.length >= MAX_PANES || !all.includes(target) || all.includes(id)) return null;
  const go = (n: Layout): Layout => (isPane(n) ? (n.pane === target ? { dir, ratio: 0.5, a: before ? { pane: id } : n, b: before ? n : { pane: id } } : n) : { ...n, a: go(n.a), b: go(n.b) });
  return go(l);
}

/** Take pane `target` out: the part beside it takes its room. `layout` is null when it was the last pane; `heir` is
 *  the pane nearest to where it was (the one that takes the keyboard), null when nothing changed. */
export function removePane(l: Layout, target: number): { layout: Layout | null; heir: number | null } {
  if (isPane(l)) return l.pane === target ? { layout: null, heir: null } : { layout: l, heir: null };
  const ra = removePane(l.a, target);
  if (ra.layout === null) return { layout: l.b, heir: panesOf(l.b)[0] };
  if (ra.layout !== l.a) return { layout: { ...l, a: ra.layout }, heir: ra.heir };
  const rb = removePane(l.b, target);
  if (rb.layout === null) {
    const left = panesOf(l.a);
    return { layout: l.a, heir: left[left.length - 1] };
  }
  if (rb.layout !== l.b) return { layout: { ...l, b: rb.layout }, heir: rb.heir };
  return { layout: l, heir: null };
}

/** The split at `path` ("" the root, then `a`/`b` per level) takes `ratio` (the first part's share). */
export function setRatioAt(l: Layout, path: string, ratio: number): Layout {
  if (isPane(l)) return l;
  if (!path) return { ...l, ratio };
  return path[0] === "a" ? { ...l, a: setRatioAt(l.a, path.slice(1), ratio) } : { ...l, b: setRatioAt(l.b, path.slice(1), ratio) };
}

/** Every pane the same size along each line of splits (a double click on a divider). */
export function equalize(l: Layout): Layout {
  if (isPane(l)) return l;
  const count = (n: Layout): number => (isPane(n) || n.dir !== l.dir ? 1 : count(n.a) + count(n.b));
  const a = count(l.a);
  const b = count(l.b);
  return { ...l, ratio: a / (a + b), a: equalize(l.a), b: equalize(l.b) };
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where each pane sits in a unit square. */
export function paneRects(l: Layout, box: Rect = { x: 0, y: 0, w: 1, h: 1 }, out = new Map<number, Rect>()): Map<number, Rect> {
  if (isPane(l)) {
    out.set(l.pane, box);
    return out;
  }
  if (l.dir === "row") {
    const w = box.w * l.ratio;
    paneRects(l.a, { ...box, w }, out);
    paneRects(l.b, { ...box, x: box.x + w, w: box.w - w }, out);
  } else {
    const h = box.h * l.ratio;
    paneRects(l.a, { ...box, h }, out);
    paneRects(l.b, { ...box, y: box.y + h, h: box.h - h }, out);
  }
  return out;
}

/** The pane next to `from` in direction `dir` (the nearest one that lines up with it), or null at the edge. */
export function neighbor(l: Layout, from: number, dir: FocusDir): number | null {
  const all = paneRects(l);
  const r = all.get(from);
  if (!r) return null;
  const eps = 1e-6;
  const horiz = dir === "left" || dir === "right";
  let best: { id: number; gap: number; off: number } | null = null;
  for (const [id, c] of all) {
    if (id === from) continue;
    const gap = dir === "left" ? r.x - (c.x + c.w) : dir === "right" ? c.x - (r.x + r.w) : dir === "up" ? r.y - (c.y + c.h) : c.y - (r.y + r.h);
    if (gap < -eps) continue;
    // it must share some of the edge it is across
    const overlap = horiz ? Math.min(r.y + r.h, c.y + c.h) - Math.max(r.y, c.y) : Math.min(r.x + r.w, c.x + c.w) - Math.max(r.x, c.x);
    if (overlap <= eps) continue;
    // nearest first, then the one whose start lines up with this pane's
    const off = horiz ? Math.abs(c.y - r.y) : Math.abs(c.x - r.x);
    if (!best || gap < best.gap - eps || (Math.abs(gap - best.gap) <= eps && off < best.off)) best = { id, gap, off };
  }
  return best?.id ?? null;
}

/** A divider's share kept so each side has at least `min` px of `total` (half each when there is no room for both). */
export function clampRatio(ratio: number, total: number, min: number): number {
  if (!Number.isFinite(ratio)) return 0.5;
  if (total <= 2 * min) return 0.5;
  const lo = min / total;
  return Math.min(1 - lo, Math.max(lo, ratio));
}

/** Pane `a` and pane `b` trade places (a pane moved with ⌘⇧⌥arrows); the layout is unchanged when either is missing. */
export function swapPanes(l: Layout, a: number, b: number): Layout {
  const all = panesOf(l);
  if (a === b || !all.includes(a) || !all.includes(b)) return l;
  const go = (n: Layout): Layout => (isPane(n) ? (n.pane === a ? { pane: b } : n.pane === b ? { pane: a } : n) : { ...n, a: go(n.a), b: go(n.b) });
  return go(l);
}

/** The pane after (1) or before (-1) `from` in reading order, wrapping; null with one pane. */
export function stepPane(l: Layout, from: number, step: 1 | -1): number | null {
  const all = panesOf(l);
  const at = all.indexOf(from);
  if (all.length < 2 || at < 0) return null;
  return all[(at + step + all.length) % all.length];
}

/** A layout read back from storage, checked: at most MAX_PANES distinct whole-number panes, ratios kept in (0, 1).
 *  Null when it is anything else. */
export function parseLayout(v: unknown, depth = 0): Layout | null {
  if (!v || typeof v !== "object" || Array.isArray(v) || depth > MAX_PANES) return null;
  const o = v as Record<string, unknown>;
  let out: Layout | null = null;
  if ("pane" in o) out = typeof o.pane === "number" && Number.isInteger(o.pane) && o.pane >= 0 && o.pane < 1_000_000 ? { pane: o.pane } : null;
  else if ((o.dir === "row" || o.dir === "col") && typeof o.ratio === "number" && Number.isFinite(o.ratio)) {
    const a = parseLayout(o.a, depth + 1);
    const b = parseLayout(o.b, depth + 1);
    if (a && b) out = { dir: o.dir, ratio: Math.min(0.95, Math.max(0.05, o.ratio)), a, b };
  }
  if (!out || depth > 0) return out;
  const all = panesOf(out);
  return all.length <= MAX_PANES && new Set(all).size === all.length ? out : null;
}

type KeyLike = { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; getModifierState?: (k: string) => boolean };

const isKey = (e: KeyLike, letter: string) => e.code === `Key${letter.toUpperCase()}` || e.key.toLowerCase() === letter;
const ARROWS: Record<string, FocusDir> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
const isBracket = (e: KeyLike, side: "[" | "]") => e.code === (side === "]" ? "BracketRight" : "BracketLeft") || (!e.code && e.key === side);
const isEqual = (e: KeyLike) => e.code === "Equal" || (!e.code && (e.key === "=" || e.key === "+"));

export type PaneKey =
  | { kind: "split"; dir: "right" | "down" }
  | { kind: "close" }
  | { kind: "focus"; dir: FocusDir }
  | { kind: "move"; dir: FocusDir }
  | { kind: "step"; step: 1 | -1 }
  | { kind: "zoom" }
  | { kind: "equalize" };

/** A pane key, or null. macOS: ⌘D split right, ⌘⇧D split down, ⌘W close the pane, ⌘⌥arrows move between panes,
 *  ⌘⇧⌥arrows move the pane itself, ⌘] / ⌘[ the next / previous pane, ⌘⇧↩ zoom the pane (again: back), ⌘⌃= even
 *  them out. Elsewhere Ctrl+<key> in a terminal is the program's (Ctrl+D, Ctrl+W), so: Ctrl+Shift+D right,
 *  Alt+Shift+D down (Orca's), Ctrl+Shift+W close, Ctrl+Alt+arrows move between, Ctrl+Alt+Shift+arrows move the pane,
 *  Ctrl+Tab / Ctrl+Shift+Tab next / previous, Ctrl+Shift+Enter zoom, Ctrl+Alt+= even out (not AltGr, which types a character there). */
export function paneKey(e: KeyLike, mac: boolean): PaneKey | null {
  const dir = ARROWS[e.key];
  if (mac) {
    if (!e.metaKey) return null;
    if (e.ctrlKey) return !e.altKey && !e.shiftKey && isEqual(e) ? { kind: "equalize" } : null;
    if (dir && e.altKey) return { kind: e.shiftKey ? "move" : "focus", dir };
    if (e.altKey) return null;
    if (isKey(e, "d")) return { kind: "split", dir: e.shiftKey ? "down" : "right" };
    if (e.shiftKey && e.key === "Enter") return { kind: "zoom" };
    if (e.shiftKey) return null;
    if (isKey(e, "w")) return { kind: "close" };
    if (isBracket(e, "]")) return { kind: "step", step: 1 };
    if (isBracket(e, "[")) return { kind: "step", step: -1 };
    return null;
  }
  if (e.metaKey) return null;
  if (dir && e.ctrlKey && e.altKey) return { kind: e.shiftKey ? "move" : "focus", dir };
  // AltGr reads as Ctrl+Alt: AltGr+= types } on French AZERTY (~ Swiss, | Danish), so only a key that still says = or
  // + evens the panes out, and never with AltGr held
  if (e.ctrlKey && e.altKey && !e.shiftKey && isEqual(e) && (e.key === "=" || e.key === "+") && !e.getModifierState?.("AltGraph")) return { kind: "equalize" };
  if (e.key === "Tab" && e.ctrlKey && !e.altKey) return { kind: "step", step: e.shiftKey ? -1 : 1 };
  if (!e.shiftKey) return null;
  if (e.key === "Enter" && e.ctrlKey && !e.altKey) return { kind: "zoom" };
  if (isKey(e, "d") && e.ctrlKey && !e.altKey) return { kind: "split", dir: "right" };
  if (isKey(e, "d") && e.altKey && !e.ctrlKey) return { kind: "split", dir: "down" };
  if (isKey(e, "w") && e.ctrlKey && !e.altKey) return { kind: "close" };
  return null;
}
