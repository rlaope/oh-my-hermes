// Closing a TERMINALS row can be undone for a short while (Settings › Terminal › Undo window after closing; 10 s by
// default). The row leaves the list at once and its terminal stops taking input, but its program keeps running in
// the hidden terminal (output is still read and acknowledged, as for any terminal off screen). Undo puts the same
// row and terminal back; at the deadline the old close runs, once. The deadline counts from the close, never from
// output, and is one `setTimeout` per close (plus a sweep when the window shows again, in case a hidden window's
// timers were held back). Kept apart from React and xterm so it can be tested on its own.

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

/** The undo window in ms for the setting's seconds; `override` (e2e, mock host only) shortens a window that is on. */
export function graceMs(seconds: number, override?: unknown): number {
  if (!(seconds > 0)) return 0;
  return typeof override === "number" && Number.isFinite(override) && override > 0 ? override : seconds * 1000;
}

/** The newest-first undo key: ⌘Z on macOS, Ctrl+Shift+Z elsewhere (plain Ctrl+Z stays the program's). */
export function isUndoKey(e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }, mac: boolean): boolean {
  if (e.key.toLowerCase() !== "z" || e.altKey) return false;
  return mac ? e.metaKey && !e.ctrlKey && !e.shiftKey : e.ctrlKey && e.shiftKey && !e.metaKey;
}
