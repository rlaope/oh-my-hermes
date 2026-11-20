// TERMINALS splits, kept apart from React and xterm: each split is a layout tree (terminal/layout.ts) of up to four
// TERMINALS sessions, right of or under each other in any nesting. A pane's number is its session's (`s12` -> 12), so
// a layout names its sessions and comes back after a restart as it was. A session is in one split at most. The pane
// with the keyboard is the session open in the main column (`ui.session`): focusing a pane opens its session, so the
// header, the row and the Plans panel follow it. Taking a pane out of a split stops nothing: its session stays listed.
// Bot chats and threads are never in a split: only TERMINALS sessions are offered.
//
// Saved on this computer (`omher.splits`) on every change; read once at load. Panes whose session is gone are dropped
// when the session list says so (SplitView prunes), and a split left with one pane ends.
import { useSyncExternalStore } from "react";
import { equalize, MAX_PANES, neighbor, panesOf, parseLayout, removePane, setRatioAt, splitLayout, stepPane, swapPanes, type FocusDir, type Layout, type PaneKey } from "../terminal/layout";

export interface SplitGroup {
  layout: Layout;
  /** the focused pane fills the split; the others keep running behind it */
  zoom?: boolean;
}

export type SplitDirName = "right" | "down";

export interface SplitState {
  groups: SplitGroup[];
  /** the picker is open: which session splits, and which way */
  picking: { at: string; dir: SplitDirName } | null;
}

/** The split pane that holds `active` (the element with the keyboard): that pane's session. Focus in the split's own
 *  chrome (between panes, the zoomed note) falls back to `selected`, the pane last picked; focus outside a split is
 *  null. The ⌘W key in a pane and the menu's Close Window both close the pane this names (one decision for both). */
export function splitPaneOf(active: Element | null, selected: string | null): string | null {
  if (!active?.closest?.('[data-testid="session-split"]')) return null;
  return active.closest('[data-testid="split-pane"]')?.getAttribute("data-session") || selected;
}

export const SPLITS_KEY = "omher.splits";
const MAX_GROUPS = 20;
const ID = /^s(\d{1,9})$/;

/** A session id's pane number (`s12` -> 12), or null for anything else. */
export const paneOf = (id: string): number | null => {
  const m = ID.exec(id);
  return m ? Number(m[1]) : null;
};
export const sessionOf = (n: number): string => `s${n}`;

/** The sessions of a split, in reading order. */
export const groupSessions = (g: SplitGroup): string[] => panesOf(g.layout).map(sessionOf);

/** The split session `id` is in (two panes or more), or null. */
export function groupOf(groups: SplitGroup[], id: string): SplitGroup | null {
  const n = paneOf(id);
  if (n === null) return null;
  return groups.find((g) => panesOf(g.layout).length > 1 && panesOf(g.layout).includes(n)) ?? null;
}

/** Splits with one pane or none end. */
const tidy = (groups: SplitGroup[]) => groups.filter((g) => panesOf(g.layout).length > 1);

/** `id` taken out of whichever split holds it; `heir` is the pane nearest to where it was (null when none). */
export function leaveIn(groups: SplitGroup[], id: string): { groups: SplitGroup[]; heir: string | null } {
  const n = paneOf(id);
  const g = groupOf(groups, id);
  if (n === null || !g) return { groups, heir: null };
  const { layout, heir } = removePane(g.layout, n);
  const next = groups.map((x) => (x === g ? { ...x, layout: layout ?? x.layout } : x));
  return { groups: tidy(layout ? next : groups.filter((x) => x !== g)), heir: heir === null ? null : sessionOf(heir) };
}

/** Split `at`'s pane, putting `add` right of it or under it (half each). `add` leaves any split it was in first. The
 *  same list back when `at` and `add` are one, either is not a session id, or `at`'s split already has MAX_PANES. */
export function splitIn(groups: SplitGroup[], at: string, dir: SplitDirName, add: string): SplitGroup[] {
  const a = paneOf(at);
  const b = paneOf(add);
  if (a === null || b === null || a === b) return groups;
  const current = groupOf(groups, at);
  if (current && panesOf(current.layout).length >= MAX_PANES) return groups;
  // already beside it in this split: nothing to do
  if (current && panesOf(current.layout).includes(b)) return groups;
  const rest = leaveIn(groups, add).groups;
  const g = groupOf(rest, at);
  const layout = splitLayout(g?.layout ?? { pane: a }, a, dir === "right" ? "row" : "col", b);
  if (!layout) return groups;
  return g ? rest.map((x) => (x === g ? { layout } : x)) : [...rest, { layout }].slice(-MAX_GROUPS);
}

/** The split holding `id`, changed by `fn` (the same list when there is none). */
function inGroup(groups: SplitGroup[], id: string, fn: (g: SplitGroup) => SplitGroup): SplitGroup[] {
  const g = groupOf(groups, id);
  return g ? groups.map((x) => (x === g ? fn(x) : x)) : groups;
}

/** `id`'s pane trades places with the pane beside it in direction `dir`. */
export const moveIn = (groups: SplitGroup[], id: string, dir: FocusDir): SplitGroup[] =>
  inGroup(groups, id, (g) => {
    const to = neighbor(g.layout, paneOf(id)!, dir);
    return to === null ? g : { ...g, layout: swapPanes(g.layout, paneOf(id)!, to) };
  });

export const ratioIn = (groups: SplitGroup[], id: string, path: string, ratio: number): SplitGroup[] => inGroup(groups, id, (g) => ({ ...g, layout: setRatioAt(g.layout, path, ratio) }));
export const equalizeIn = (groups: SplitGroup[], id: string): SplitGroup[] => inGroup(groups, id, (g) => ({ ...g, layout: equalize(g.layout) }));
export const zoomIn = (groups: SplitGroup[], id: string, on?: boolean): SplitGroup[] => inGroup(groups, id, (g) => ({ ...g, zoom: on ?? !g.zoom }));

/** Panes whose session is not in `alive` dropped (splits left with one pane end). */
export function pruneIn(groups: SplitGroup[], alive: Set<string>): SplitGroup[] {
  let out = groups;
  for (const g of groups) for (const id of groupSessions(g)) if (!alive.has(id)) out = leaveIn(out, id).groups;
  return out;
}

/** The saved splits, checked; none when missing or malformed. A session in two saved splits keeps the first. */
export function parseSplits(raw: string | null): SplitGroup[] {
  let v: unknown;
  try {
    v = raw ? JSON.parse(raw) : null;
  } catch {
    return [];
  }
  const list = v && typeof v === "object" && Array.isArray((v as { groups?: unknown }).groups) ? (v as { groups: unknown[] }).groups : [];
  const out: SplitGroup[] = [];
  const seen = new Set<number>();
  for (const g of list.slice(0, MAX_GROUPS)) {
    const layout = parseLayout((g as { layout?: unknown } | null)?.layout);
    if (!layout) continue;
    const panes = panesOf(layout);
    if (panes.length < 2 || panes.some((p) => p < 1 || seen.has(p))) continue;
    for (const p of panes) seen.add(p);
    out.push({ layout, ...((g as { zoom?: unknown }).zoom === true ? { zoom: true } : {}) });
  }
  return out;
}

export const serializeSplits = (groups: SplitGroup[]): string => JSON.stringify({ v: 1, groups });

function read(): SplitGroup[] {
  try {
    return parseSplits(typeof localStorage !== "undefined" ? localStorage.getItem(SPLITS_KEY) : null);
  } catch {
    return [];
  }
}

let state: SplitState = { groups: read(), picking: null };
const listeners = new Set<() => void>();

export function setSplit(patch: Partial<SplitState>): void {
  const before = state.groups;
  state = { ...state, ...patch };
  if (state.groups !== before) {
    try {
      if (typeof localStorage !== "undefined") {
        if (state.groups.length) localStorage.setItem(SPLITS_KEY, serializeSplits(state.groups));
        else localStorage.removeItem(SPLITS_KEY);
      }
    } catch {
      /* no storage */
    }
  }
  for (const fn of listeners) fn();
}

const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => void listeners.delete(fn);
};
export const getSplit = (): SplitState => state;
export const useSplit = (): SplitState => useSyncExternalStore(subscribe, getSplit, getSplit);

/** Tests: start from nothing. */
export function resetSplit(): void {
  setSplit({ groups: [], picking: null });
}

/** What a pane key does to the split holding `id` (the focused pane). `focus` is where the keyboard goes next, null
 *  when it stays; `took` is false when the key means nothing here (no split, or the edge) and should go on. */
export function paneKeyIn(groups: SplitGroup[], id: string, k: PaneKey): { groups: SplitGroup[]; focus: string | null; took: boolean } {
  const g = groupOf(groups, id);
  const n = paneOf(id);
  const none = { groups, focus: null, took: false };
  if (!g || n === null) return none;
  switch (k.kind) {
    case "close": {
      const r = leaveIn(groups, id);
      return { groups: r.groups, focus: r.heir, took: true };
    }
    case "focus": {
      const to = neighbor(g.layout, n, k.dir);
      return to === null ? { ...none, took: true } : { groups: zoomIn(groups, id, false), focus: sessionOf(to), took: true };
    }
    case "step": {
      const to = stepPane(g.layout, n, k.step);
      return to === null ? { ...none, took: true } : { groups: zoomIn(groups, id, false), focus: sessionOf(to), took: true };
    }
    case "move":
      return { groups: moveIn(groups, id, k.dir), focus: null, took: true };
    case "zoom":
      return { groups: zoomIn(groups, id), focus: null, took: true };
    case "equalize":
      return { groups: equalizeIn(groups, id), focus: null, took: true };
    default:
      return none;
  }
}
