// The dock at the bottom of the sidebar (Arc favourites): up to six tiles, bots and terminals, that stay on screen
// while BOTS and TERMINALS scroll above it. What is pinned, and in which order, is kept in this computer's storage for
// the app (`omher.dock`), never in Hermes. A pin is `bot:<profile>` or `term:<session id>`.
import { useSyncExternalStore } from "react";

export const DOCK_KEY = "omher.dock";
export const DOCK_MAX = 6;

export interface DockState {
  pins: string[];
}

const PIN = /^(bot|term):.{1,200}$/;

export function parseDock(raw: string | null): DockState {
  try {
    const v = raw ? JSON.parse(raw) : null;
    const pins = Array.isArray(v?.pins) ? (v.pins as unknown[]).filter((p): p is string => typeof p === "string" && PIN.test(p)) : [];
    return { pins: [...new Set(pins)].slice(0, 24) };
  } catch {
    return { pins: [] };
  }
}

const read = (): DockState => parseDock(typeof localStorage === "undefined" ? null : localStorage.getItem(DOCK_KEY));
let state: DockState = read();
const listeners = new Set<() => void>();

function save(next: DockState) {
  state = next;
  try {
    localStorage.setItem(DOCK_KEY, JSON.stringify(next));
  } catch {
    /* no storage */
  }
  for (const l of [...listeners]) l();
}

export const getDock = (): DockState => state;
export function subscribeDock(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
export function useDock(): DockState {
  return useSyncExternalStore(subscribeDock, getDock, getDock);
}

/** Pin `key` to the dock (at its end) or unpin it. */
export function pinToDock(key: string, on: boolean): void {
  const has = state.pins.includes(key);
  if (on === has || !PIN.test(key)) return;
  save({ pins: on ? [...state.pins, key] : state.pins.filter((p) => p !== key) });
}

/** Move pin `key` to place `to` of `order` (the tiles as shown). Moving an unpinned tile pins the whole shown order,
 *  so what the person arranged is what stays. */
export function moveInDock(order: string[], key: string, to: number): void {
  const list = order.filter((k) => k !== key);
  list.splice(Math.max(0, Math.min(to, list.length)), 0, key);
  const rest = state.pins.filter((p) => !list.includes(p));
  save({ pins: [...list, ...rest] });
}

/** The tiles, in order: the pins that still exist; with nothing pinned, the bots with the most recent activity. */
export function dockTiles(pins: string[], exists: (key: string) => boolean, recentBots: string[]): { keys: string[]; auto: boolean } {
  const pinned = pins.filter(exists);
  if (pinned.length) return { keys: pinned.slice(0, DOCK_MAX), auto: false };
  return { keys: recentBots.slice(0, DOCK_MAX).map((b) => `bot:${b}`), auto: true };
}

/** e2e / tests: forget what was read at load. */
export function resetDock(): void {
  state = read();
  for (const l of [...listeners]) l();
}
