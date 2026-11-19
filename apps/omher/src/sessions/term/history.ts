// Terminal history across restarts: what each TERMINALS session and bottom-panel tab showed is kept by the desktop
// shell in omher's own folder (`~/.omher/term-history/<key>.txt`, src-tauri/src/term_history.rs) and written back,
// dimmed, into the new terminal after omher restarts, under a one-line divider, before the program's own output.
// The text is the terminal's buffer serialized with `@xterm/addon-serialize` (its last HISTORY_LINES lines, no modes
// and no full-screen program's alternate screen), saved every HISTORY_EVERY_MS while it changed and when the page
// goes away. Settings › Terminal › History "Keep history across restarts" (`keepHistory`) turns all of it off, and
// turning it off removes every kept file at once.
import type { Terminal } from "@xterm/xterm";
import { locale, t } from "../../i18n";
import { onTermSettings, readTermSettings } from "./settings";

/** Lines kept of one terminal (the shell keeps at most this many, and 1 MB). */
export const HISTORY_LINES = 2000;
/** A terminal whose buffer changed is saved this often. */
export const HISTORY_EVERY_MS = 30_000;

/** The shell's history calls (SessionHost implements them). */
export interface HistoryHost {
  /** `since`: when history was last turned on in this page (ms since the epoch); the shell drops a write from
   *  before its last clear, so a save still on its way when the person turns history off never makes a file again. */
  historySave(key: string, text: string, since: number): Promise<void>;
  historyRead(key: string): Promise<{ text: string; at: number } | null>;
  historyRemove(key: string): Promise<void>;
  historyPrune(keep: string[]): Promise<void>;
  historyClear(): Promise<void>;
}

export const historyOn = (): boolean => readTermSettings().keepHistory;

/** `text` drawn dim: faint from the start and again after every colour change (a reset would end it). */
export function dimmed(text: string): string {
  return `\x1b[0m\x1b[2m${text.replace(/\x1b\[[0-9;:]*m/g, "$&\x1b[2m")}\x1b[0m`;
}

/** The line between what was kept and the new program's output. */
export function divider(at: number): string {
  const time = new Date(at * 1000).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" });
  return `\r\n\x1b[0m\x1b[2m--- ${t("term.restored", { time })} ---\x1b[0m\r\n`;
}

type Serialize = typeof import("@xterm/addon-serialize").SerializeAddon;
let Ser: Serialize | null = null;
let serLoad: Promise<Serialize | null> | null = null;
const loadSer = () =>
  (serLoad ??= import("@xterm/addon-serialize").then(
    (m) => (Ser = m.SerializeAddon),
    () => (serLoad = null),
  ));

/** The newest HISTORY_LINES lines of `term`'s main buffer, as text that redraws them: no modes, no full-screen
 *  program's alternate screen, no final cursor move, and no blank rows after the last line with text. */
export function serializeTail(term: Terminal, S: Serialize): string {
  const ser = new S();
  term.loadAddon(ser);
  try {
    const n = term.buffer.normal.length;
    const text = ser.serialize({ range: { start: Math.max(0, n - HISTORY_LINES), end: n - 1 }, excludeModes: true, excludeAltBuffer: true });
    return text.replace(/(?:\s|\x1b\[[0-9;]*m)+$/, "");
  } finally {
    ser.dispose();
  }
}

interface Tracked {
  /** the terminal now, or null while it cannot be read (parked, gone) */
  term: () => Terminal | null;
  dirty: boolean;
}

const tracked = new Map<string, Tracked>();
let host: HistoryHost | null = null;
/** When history was last turned on in this page (its load, or the switch): every save carries it. */
let onSince = Date.now();
let timer: ReturnType<typeof setInterval> | null = null;

function save(key: string, tr: Tracked): void {
  if (!tr.dirty || !Ser || !host) return;
  const term = tr.term();
  if (!term) return;
  let text: string;
  try {
    text = serializeTail(term, Ser);
  } catch {
    return;
  }
  tr.dirty = false;
  try {
    void host.historySave(key, text, onSince).catch(() => (tr.dirty = true));
  } catch {
    tr.dirty = true;
  }
}

/** Save every terminal that changed since it was last saved (the 30-s tick, the page going away). */
export function flushHistory(): void {
  if (!historyOn()) return;
  for (const [key, tr] of tracked) save(key, tr);
}

function tick(): void {
  const need = tracked.size > 0 && historyOn();
  if (need && !timer) timer = setInterval(flushHistory, HISTORY_EVERY_MS);
  else if (!need && timer) {
    clearInterval(timer);
    timer = null;
  }
}

let wired = false;
function wire(): void {
  if (wired || typeof window === "undefined") return;
  wired = true;
  window.addEventListener("pagehide", flushHistory);
  window.addEventListener("beforeunload", flushHistory);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushHistory();
  });
}

/** Keep terminal `key`'s history from now on; `touch` marks it changed (its program printed). */
export function trackHistory(h: HistoryHost, key: string, term: () => Terminal | null): { touch: () => void; stop: () => void; flush: () => void } {
  host = h;
  const tr: Tracked = { term, dirty: false };
  tracked.set(key, tr);
  if (historyOn()) void loadSer();
  wire();
  tick();
  return {
    touch: () => {
      tr.dirty = true;
    },
    stop: () => {
      if (tracked.get(key) === tr) tracked.delete(key);
      tick();
    },
    /** save now if it changed (the terminal is about to be parked) */
    flush: () => {
      if (historyOn()) save(key, tr);
    },
  };
}

/** What terminal `key` showed before the restart, ready to write into its new terminal (dimmed, then the divider);
 *  "" when nothing was kept or history is off. */
export async function restoredText(h: HistoryHost, key: string): Promise<string> {
  if (!historyOn()) return "";
  try {
    const got = await h.historyRead(key);
    return got && got.text.trim() ? dimmed(got.text) + divider(got.at) : "";
  } catch {
    return "";
  }
}

/** Terminal `key` was closed: its history goes. */
export function forgetHistory(h: HistoryHost, key: string): void {
  tracked.delete(key);
  tick();
  if (!historyOn()) return;
  try {
    void h.historyRemove(key).catch(() => undefined);
  } catch {
    /* an older shell */
  }
}

/** omher started: the history of every terminal not in `keep` goes. */
export function pruneHistory(h: HistoryHost, keep: string[]): void {
  if (!historyOn()) return;
  try {
    void h.historyPrune(keep).catch(() => undefined);
  } catch {
    /* an older shell */
  }
}

/** Settings turned history off: every kept file goes at once; turned on, the open terminals are saved from now. */
let wasOn: boolean | null = null;
export function watchHistorySetting(h: HistoryHost): void {
  if (wasOn !== null) return;
  wasOn = historyOn();
  onTermSettings((s) => {
    if (s.keepHistory === wasOn) return;
    wasOn = s.keepHistory;
    tick();
    if (s.keepHistory) {
      onSince = Date.now();
      void loadSer();
      for (const tr of tracked.values()) tr.dirty = true;
      return;
    }
    try {
      void h.historyClear().catch(() => undefined);
    } catch {
      /* an older shell */
    }
  });
}
