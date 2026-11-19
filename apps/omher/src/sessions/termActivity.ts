// What a terminal's output says about it, per session: when output last flowed (`lastOut`), the last line its screen
// shows with text (`lastLine`) and the title it set (`oscTitle`). These change while a program prints, hidden or not,
// so they live here and not in the sessions list: a change notifies the one session's readers (its TERMINALS row,
// its collapsed folder's spinner) and never re-renders the list or its other rows.
import { useEffect, useState } from "react";
import { BUSY_MS } from "./agents";

export interface TermAct {
  /** ms since epoch of the terminal's last output (throttled), for the row's spinner and age. */
  lastOut?: number;
  /** The last line the terminal shows with text on it (read from its own screen, throttled): the card's second line. */
  lastLine?: string;
  /** The window title the program set (OSC 0/2), when it set one: the second line while nothing is printed yet. */
  oscTitle?: string;
  /** The folder its shell last reported (OSC 7), when it reported one: the row's folder, which the start folder was. */
  cwd?: string;
  /** Its program reports progress (OSC 9;4 working) and has not reported done: the row shows it working. */
  progress?: boolean;
}

const NONE: TermAct = Object.freeze({});

export function createTermActivity() {
  const acts = new Map<string, TermAct>();
  const subs = new Map<string, Set<() => void>>();
  return {
    get: (id: string): TermAct => acts.get(id) ?? NONE,
    /** Set fields of session `id`; its readers hear of it only when a value changed. */
    patch(id: string, p: TermAct) {
      const cur = acts.get(id) ?? NONE;
      if (!(Object.keys(p) as (keyof TermAct)[]).some((k) => cur[k] !== p[k])) return;
      acts.set(id, { ...cur, ...p });
      for (const fn of [...(subs.get(id) ?? [])]) fn();
    },
    subscribe(id: string, fn: () => void): () => void {
      let set = subs.get(id);
      if (!set) subs.set(id, (set = new Set()));
      set.add(fn);
      return () => {
        set.delete(fn);
        if (set.size === 0 && subs.get(id) === set) subs.delete(id);
      };
    },
  };
}

export type TermActivityStore = ReturnType<typeof createTermActivity>;

/** The app's one store (session ids are unique for the page's life). */
export const termActs: TermActivityStore = createTermActivity();

/** Output flowed within BUSY_MS of `now`, or its program reports progress (the row's spinner, while it runs). */
export const flowing = (a: TermAct, now: number): boolean => !!a.progress || (!!a.lastOut && now - a.lastOut < BUSY_MS);

/** Which label `ageOf(at, now)` shows ("now", "5m", "3h", "2d"), as a key: equal keys, equal labels. */
export function ageBucket(at: number, now: number): string {
  const s = Math.max(0, Math.floor((now - at) / 1000));
  if (s < 3600) return s < 60 ? "now" : `m${Math.floor(s / 60)}`;
  return s < 86_400 ? `h${Math.floor(s / 3600)}` : `d${Math.floor(s / 86_400)}`;
}

/** When the age label of `at` next reads differently, after `now`: ms since epoch. */
export function ageChangeAt(at: number, now: number): number {
  const s = Math.max(0, Math.floor((now - at) / 1000));
  const step = s < 3600 ? 60 : s < 86_400 ? 3600 : 86_400;
  return at + (Math.floor(s / step) + 1) * step * 1000;
}

/** What a TERMINALS row shows from its activity at `now` (spinner, age label, second line), as a key. */
export function faceKey(a: TermAct, startedAt: number, now: number): string {
  return `${flowing(a, now) ? 1 : 0}|${ageBucket(a.lastOut ?? startedAt, now)}|${a.lastLine ?? ""}|${a.oscTitle ?? ""}|${a.cwd ?? ""}`;
}

/** When `faceKey` next changes by the clock alone (the spinner stops, the age label steps): ms since epoch. */
export function nextFaceAt(a: TermAct, startedAt: number, now: number): number {
  const age = ageChangeAt(a.lastOut ?? startedAt, now);
  // progress holds the spinner until the program says otherwise (a store change), not until a time
  return flowing(a, now) && !a.progress ? Math.min(age, a.lastOut! + BUSY_MS) : age;
}

/** Session `id`'s activity, read at render time with the time it was read. The row re-renders only when what it shows
 *  changes: its spinner, its age label or its second line. While `ticking`, the clock moves it (the spinner stops
 *  BUSY_MS after output, the age label steps); a program that keeps printing the same line re-renders nothing. */
export function useTermFace(id: string, startedAt: number, ticking: boolean, store: TermActivityStore = termActs): { act: TermAct; now: number } {
  const [, setKey] = useState(() => faceKey(store.get(id), startedAt, Date.now()));
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const check = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      const now = Date.now();
      const a = store.get(id);
      setKey(faceKey(a, startedAt, now));
      if (ticking) timer = setTimeout(check, Math.max(0, nextFaceAt(a, startedAt, now) - now) + 5);
    };
    check();
    const off = store.subscribe(id, check);
    return () => {
      off();
      if (timer !== null) clearTimeout(timer);
    };
  }, [id, startedAt, ticking, store]);
  return { act: store.get(id), now: Date.now() };
}

/** Output flows in any of sessions `ids` (a collapsed folder's spinner). Re-renders only when that flips. */
export function useAnyFlowing(ids: readonly string[], store: TermActivityStore = termActs): boolean {
  const key = ids.join("\n");
  const [on, setOn] = useState(() => ids.some((id) => flowing(store.get(id), Date.now())));
  useEffect(() => {
    const list = key ? key.split("\n") : [];
    let timer: ReturnType<typeof setTimeout> | null = null;
    const check = () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      const now = Date.now();
      let until = 0;
      for (const id of list) {
        const a = store.get(id);
        if (flowing(a, now)) until = Math.max(until, a.progress ? Infinity : a.lastOut! + BUSY_MS);
      }
      setOn(until > 0);
      if (until && until !== Infinity) timer = setTimeout(check, until - now + 5);
    };
    check();
    const offs = list.map((id) => store.subscribe(id, check));
    return () => {
      for (const off of offs) off();
      if (timer !== null) clearTimeout(timer);
    };
  }, [key, store]);
  return on;
}

/** Dev builds only (e2e, the bench): how many times each sidebar part rendered, on `window.__omherRenders`. */
export function countRender(part: string): void {
  if (!import.meta.env?.DEV || typeof window === "undefined") return;
  const w = window as unknown as { __omherRenders?: Record<string, number> };
  const m = (w.__omherRenders ??= {});
  m[part] = (m[part] ?? 0) + 1;
}
