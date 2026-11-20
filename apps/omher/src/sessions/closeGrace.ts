// Closing a TERMINALS row can be undone for a short while (Settings › Terminal › Undo window after closing; 10 s by
// default). The row leaves the list at once and its terminal stops taking input, but its program keeps running in
// the hidden terminal (output is still read and acknowledged, as for any terminal off screen). Undo puts the same
// row and terminal back; at the deadline the old close runs, once. The deadline counts from the close, never from
// output, and is one `setTimeout` per close (plus a sweep when the window shows again, in case a hidden window's
// timers were held back). Kept apart from React and xterm so it can be tested on its own.

import { MAX_PANES, panesOf, removePane, type Layout } from "../terminal/layout";
import { groupOf, paneOf, type SplitGroup } from "./splitState";

/** One closed row waiting out its undo window. `data` is what the owner needs to put it back. */
export interface Grace<T> {
  id: string;
  /** what the toast calls it */
  name: string;
  /** when it was closed, and when the old close runs (ms, the clock given) */
  closedAt: number;
  until: number;
  data: T;
}

/** How many toasts show at once (the newest on top); older closes still keep their own deadlines. */
export const GRACE_SHOWN = 3;

export interface GraceOpts<T> {
  /** the old close: called once per close that was not undone, when its window ends */
  expire: (g: Grace<T>) => void;
  now?: () => number;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (h: unknown) => void;
}

export function createCloseGrace<T>(o: GraceOpts<T>) {
  const now = o.now ?? (() => Date.now());
  const setTimer = o.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = o.clearTimer ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  const held = new Map<string, { g: Grace<T>; timer: unknown }>();
  /** newest first */
  let list: Grace<T>[] = [];
  const listeners = new Set<() => void>();
  const changed = () => {
    list = [...held.values()].map((x) => x.g).sort((a, b) => b.closedAt - a.closedAt);
    for (const fn of [...listeners]) fn();
  };

  const take = (id: string): Grace<T> | null => {
    const x = held.get(id);
    if (!x) return null;
    clearTimer(x.timer);
    held.delete(id);
    changed();
    return x.g;
  };

  /** End `id`'s window now (its deadline came, or it cannot wait): the old close runs once. False when not held. */
  const finish = (id: string): boolean => {
    const g = take(id);
    if (!g) return false;
    o.expire(g);
    return true;
  };

  return {
    /** Hold `id` for `ms`. Null (nothing held) when `ms` is 0 or less (the setting is Off) or it is held already. */
    begin(id: string, name: string, ms: number, data: T): Grace<T> | null {
      if (!(ms > 0) || held.has(id)) return null;
      const at = now();
      const g: Grace<T> = { id, name, closedAt: at, until: at + ms, data };
      held.set(id, { g, timer: setTimer(() => finish(id), ms) });
      changed();
      return g;
    },
    /** Undo: `id`'s entry back (its timer cleared, the old close never runs), or null when it is not held. */
    undo: take,
    finish,
    /** Run every close whose deadline passed (a hidden window's timers may have been held back). */
    sweep(): void {
      const t = now();
      for (const x of [...held.values()]) if (x.g.until <= t) finish(x.g.id);
    },
    has: (id: string): boolean => held.has(id),
    /** Every held close, newest first. Stable between changes (a React snapshot). */
    list: (): Grace<T>[] => list,
    subscribe(fn: () => void): () => void {
      listeners.add(fn);
      return () => void listeners.delete(fn);
    },
  };
}

export type CloseGrace<T> = ReturnType<typeof createCloseGrace<T>>;

/** The undo window in ms for the setting's seconds; `override` (e2e, mock host only) changes a window that is on:
 *  a shorter wait, or 0 for none. */
export function graceMs(seconds: number, override?: unknown): number {
  if (!(seconds > 0)) return 0;
  return typeof override === "number" && Number.isFinite(override) && override >= 0 ? override : seconds * 1000;
}

/** The split a closed row was in, as it was when it closed. */
export type SplitWas = { layout: Layout; zoom?: true };

/** Session `id` put back into the split it was in (`was`), in the same slot: the panes of that layout that are still
 *  listed (`alive`) and in no other split keep their places and sizes. The same list back when the slot is gone (the
 *  split took other panes since, or nothing of it is left): the row then comes back on its own. */
export function restoreSplitIn(groups: SplitGroup[], id: string, was: SplitWas, alive: ReadonlySet<string>): SplitGroup[] {
  const n = paneOf(id);
  if (n === null || groupOf(groups, id) || !panesOf(was.layout).includes(n)) return groups;
  const ofPane = (p: number) => groups.find((g) => panesOf(g.layout).length > 1 && panesOf(g.layout).includes(p)) ?? null;
  const others = panesOf(was.layout).filter((p) => p !== n);
  // the split those panes are in now (one at most: a split that broke up is not put together again from parts)
  const now = [...new Set(others.map(ofPane).filter((g): g is SplitGroup => g !== null))];
  if (now.length > 1) return groups;
  const g = now[0] ?? null;
  if (g && panesOf(g.layout).some((p) => !others.includes(p))) return groups;
  let layout: Layout | null = was.layout;
  for (const p of others) {
    if (alive.has(`s${p}`) && (!ofPane(p) || ofPane(p) === g)) continue;
    layout = layout ? removePane(layout, p).layout : null;
  }
  if (!layout || panesOf(layout).length < 2 || panesOf(layout).length > MAX_PANES) return groups;
  const back: SplitGroup = { layout, ...((g ? g.zoom : was.zoom) ? { zoom: true as const } : {}) };
  return g ? groups.map((x) => (x === g ? back : x)) : [...groups, back];
}

/** The newest-first undo key: ⌘Z on macOS, Ctrl+Shift+Z elsewhere (plain Ctrl+Z stays the program's). */
export function isUndoKey(e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }, mac: boolean): boolean {
  if (e.key.toLowerCase() !== "z" || e.altKey) return false;
  return mac ? e.metaKey && !e.ctrlKey && !e.shiftKey : e.ctrlKey && e.shiftKey && !e.metaKey;
}
