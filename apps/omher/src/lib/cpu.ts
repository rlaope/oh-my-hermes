// Another app keeping a CPU core busy (src-tauri/src/cpu.rs reads the person's own processes' CPU time every 5 s and
// runs no program). The shell sends `cpu-hog` `{name, pct, pid}` once for a hog the page has not been told about (an
// app is told about again only an hour later, or after it cooled down): that event is the one desktop notification.
// `cpu-hogs` carries the current hogs whenever that list changes: the sidebar chip shows the hottest while there is one.
// Settings › General's "Warn when another app keeps the CPU busy" (on by default, saved on this computer in
// `omher.cpuWarn`) turns the reading itself on and off.
import { useSyncExternalStore } from "react";
import { cpuHogNote, type Note } from "./notify";

export interface CpuHog {
  name: string;
  /** Usage in the last reading, % of one core. */
  pct: number;
  pid: number;
}

export interface CpuState {
  /** Hottest first. */
  hogs: CpuHog[];
  /** False where the shell does not read CPU time (Windows). */
  supported: boolean;
}

/** The host side `lib/cpu.ts` needs (`SessionHost.cpuWatch` / `onCpuHog` / `onCpuHogs`). */
export interface CpuHost {
  cpuWatch(on: boolean): Promise<CpuState>;
  onCpuHog(fn: (h: CpuHog) => void): () => void;
  onCpuHogs(fn: (s: CpuState) => void): () => void;
}

const KEY = "omher.cpuWarn";

/** Settings › General: warn when another app keeps the CPU busy. On unless turned off. */
export function cpuWarn(): boolean {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem(KEY) !== "off";
  } catch {
    return true;
  }
}

const NONE: CpuHog[] = [];
let now: CpuHog[] = NONE;
const subs = new Set<() => void>();

function set(hogs: CpuHog[] | null | undefined): void {
  const next = Array.isArray(hogs) && hogs.length && cpuWarn() ? hogs.map((h) => ({ name: String(h.name), pct: Number(h.pct) || 0, pid: Number(h.pid) || 0 })) : NONE;
  if (next.length === now.length && next.every((h, i) => h.name === now[i].name && h.pct === now[i].pct)) return;
  now = next;
  for (const f of subs) f();
}

/** The current hogs, hottest first (the chip). */
export function useCpuHogs(): CpuHog[] {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => now,
    () => now,
  );
}

let host: CpuHost | null = null;
let started = false;
let notify: ((n: Note) => void) | null = null;

async function ask(): Promise<void> {
  if (!host) return;
  try {
    const s = await host.cpuWatch(cpuWarn());
    set(s?.hogs);
  } catch {
    /* an older shell without the command: no chip */
  }
}

/** Start following hogs once per page. `note` sends the notification (the store's `showNote` path, after the Notify me
 *  setting). The shell decides when a warning is due; the page only drops one that arrives with the setting off. */
export function startCpuWatch(h: CpuHost, note: (n: Note) => void): void {
  if (started) return;
  started = true;
  host = h;
  notify = note;
  h.onCpuHog((hog) => {
    if (cpuWarn() && hog && hog.name) notify?.(cpuHogNote(hog));
  });
  h.onCpuHogs((s) => set(s?.hogs));
  void ask();
}

/** Settings › General: the warning on or off; off clears the chip and the shell stops reading. */
export function setCpuWarn(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    /* private mode: this run only */
  }
  if (!on) set(NONE);
  void ask();
}

/** Tests: forget the page's state. */
export function resetCpuForTest(): void {
  now = NONE;
  host = null;
  started = false;
  notify = null;
}
