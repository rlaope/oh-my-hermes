// Free space on the volume that holds the home folder (src-tauri/src/disk.rs reads one filesystem statistic a
// minute). The shell sends `disk-level` `{level, free_bytes, volume}` only when the level gets worse (and once at
// startup when it already is low): that event is the one desktop notification. The sidebar chip shows while the level
// is low or critical, from the event and from `diskWatch`'s answer, asked again every minute (no system call: the
// shell answers its last reading). Settings › General picks the warn value, saved on this computer in
// `omher.diskWarn`. Nothing is ever deleted.
import { useSyncExternalStore } from "react";
import { t } from "../i18n";
import type { Note } from "./notify";

export type DiskLevel = "ok" | "low" | "critical";

export interface DiskState {
  level: DiskLevel;
  free_bytes: number;
  /** Where the home folder's volume is mounted (`/`, `C:\`). */
  volume: string;
  /** How many times the level has got worse since the shell started (src-tauri/src/disk.rs `Watch::alerts`). Each new
   *  count is noted once, whether the event or a reading brings it. Absent from an older shell. */
  alerts?: number;
}

/** Settings › General's choices in GB; 0 = off. */
export const DISK_WARN_CHOICES = [5, 10, 20, 50, 0] as const;
export const DISK_WARN_DEFAULT = 20;
const KEY = "omher.diskWarn";

export function diskWarn(): number {
  try {
    const v = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    const n = v === "off" ? 0 : Number(v);
    return v !== null && (DISK_WARN_CHOICES as readonly number[]).includes(n) ? n : DISK_WARN_DEFAULT;
  } catch {
    return DISK_WARN_DEFAULT;
  }
}

/** `4.5 GB`: decimal gigabytes as Finder and Explorer count them, one decimal under 10. */
export function gb(bytes: number): string {
  const n = Math.max(0, bytes) / 1e9;
  return t("disk.gb", { n: n < 10 ? n.toFixed(1) : String(Math.round(n)) });
}

/** The one notification for a worse level. Pure: no globals. */
export function diskNote(s: DiskState): Note {
  return {
    title: t(s.level === "critical" ? "disk.noteCritical" : "disk.noteLow", { free: gb(s.free_bytes) }),
    body: t("disk.noteBody", { volume: s.volume || "/" }),
    bot: "",
    tag: `disk:${s.level}`,
  };
}

/** The host side `lib/disk.ts` needs (`SessionHost.diskWatch` / `onDiskLevel`). */
export interface DiskHost {
  diskWatch(warnGb: number): Promise<DiskState>;
  onDiskLevel(fn: (s: DiskState) => void): () => void;
}

const OK: DiskState = { level: "ok", free_bytes: 0, volume: "" };
let now: DiskState = OK;
const subs = new Set<() => void>();

function set(s: DiskState | null | undefined): void {
  if (!s || (s.level !== "ok" && s.level !== "low" && s.level !== "critical")) return;
  if (s.level === now.level && s.free_bytes === now.free_bytes && s.volume === now.volume) return;
  now = { level: s.level, free_bytes: Number(s.free_bytes) || 0, volume: String(s.volume ?? "") };
  for (const f of subs) f();
}

/** The current reading (the chip). */
export function useDisk(): DiskState {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => now,
    () => now,
  );
}

let host: DiskHost | null = null;
let started = false;
let notify: ((n: Note) => void) | null = null;
const RANK: Record<DiskLevel, number> = { ok: 0, low: 1, critical: 2 };
/** The shell's worse-step count already noted (or passed over: a step that arrives as ok, after the warning was
 *  turned off, is never noted later). */
let seenAlerts = 0;
/** An older shell without `alerts`: the level last heard. */
let noted: DiskLevel = "ok";
/** Replies come back in any order: one asked before the newest applied reply is stale. */
let asked = 0;
let applied = 0;

/** One note per time the level got worse, from whichever comes first: the shell's event, or a reading that already
 *  shows it. The startup event can fire before the page's listener is registered, a recovery and a new drop can both
 *  happen between two polls, and a slow reply can arrive after a newer one; the shell's count settles all three. */
function heard(s: DiskState | null | undefined, seq?: number): void {
  if (!s || !(s.level in RANK)) return;
  if (seq !== undefined) {
    if (seq < applied) return;
    applied = seq;
  }
  // a reading taken before a worse step the page already heard about is older than what the chip shows
  if (typeof s.alerts === "number" && s.alerts < seenAlerts) return;
  set(s);
  let worse: boolean;
  if (typeof s.alerts === "number") {
    worse = s.alerts > seenAlerts && s.level !== "ok";
    seenAlerts = Math.max(seenAlerts, s.alerts);
  } else {
    worse = RANK[s.level] > RANK[noted];
    noted = s.level;
  }
  if (worse) notify?.(diskNote(s));
}

async function ask(): Promise<void> {
  if (!host) return;
  const seq = ++asked;
  try {
    heard(await host.diskWatch(diskWarn()), seq);
  } catch {
    /* an older shell without the command: no chip */
  }
}

/** Start following the disk once per page: the event (with its note) first, then the first reading.
 *  `note` sends the notification (the store's `showNote` path, after the Notify me setting). */
export function startDiskWatch(h: DiskHost, note: (n: Note) => void, every = 60_000): void {
  if (started) return;
  started = true;
  host = h;
  notify = note;
  h.onDiskLevel((s) => heard(s));
  void ask();
  if (typeof setInterval !== "undefined") setInterval(() => void ask(), every);
}

/** Settings › General: a new warn value (0 = off), measured again at once. */
export function setDiskWarn(gbValue: number): void {
  try {
    localStorage.setItem(KEY, gbValue === 0 ? "off" : String(gbValue));
  } catch {
    /* private mode: this run only */
  }
  void ask();
}
