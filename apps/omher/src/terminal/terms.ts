// The xterm side of the bottom terminal panel: one terminal per pane (a tab holds up to four), kept for the page's life
// so a hidden panel (or a tab in the back) keeps its scrollback while its shell runs on. Built from the SESSIONS
// terminal engine (src/sessions/term: look, Orca themes, renderer, find, links, clipboard settings), imported, not
// copied. As a TERMINALS terminal does, a pane rings (bell, OSC 9 message, OSC 777 notify: the tab's dot, no text
// kept), takes a dropped file (saved, its path typed), and closes when its shell ends.
import type { ITerminalInitOnlyOptions, ITerminalOptions, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { afterOpen, CELLS_EVENT, feed, isParked, live, onVisible, type Remake } from "../sessions/term/engine";
import { applyLook, termOptions } from "../sessions/term/look";
import { termFontsReady } from "../sessions/term/fonts";
import { onTermSettings, readTermSettings } from "../sessions/term/settings";
import { termTheme } from "../sessions/term/themes";
import { t } from "../i18n";
import { getShellHost } from "./host";
import { closePane, ringPane, setPaneCwd, setPaneFg } from "./state";
import { onSessionFg } from "../sessions/fg";
import { getHost } from "../sessions/host";
import { shellQuote } from "../sessions/attach";
import { termEnd } from "../sessions/agents";

/** A size goes to the shell once it has held this long (a drag gives one per frame). */
const RESIZE_SETTLE_MS = 32;
const utf8 = new TextEncoder();

type Xterm = [typeof import("@xterm/xterm"), typeof import("@xterm/addon-fit")];
let load: Promise<Xterm> | null = null;
const loadXterm = () =>
  (load ??= Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/xterm/css/xterm.css"), termFontsReady()]).then(([x, f]) => [x, f] as Xterm));

interface PanelTerm {
  /** the terminal now: reading it makes a parked one again (sessions/term/park.ts) */
  readonly term: Terminal;
  /** the xterm it has, parked or not */
  raw: Terminal;
  fit: FitAddon;
  /** makes it again after it was parked */
  remake: Remake;
  el: HTMLDivElement;
  /** the shell's session id, once started */
  id: number | null;
  /** output drawn before the id came back, acknowledged once it does */
  owed: number;
  ended: boolean;
  /** the person typed into it (a shell that ends after that closes its pane) */
  typed: boolean;
  /** files dropped on it were saved (removed with the pane) */
  saved: boolean;
  settle: ReturnType<typeof setTimeout> | null;
  undo: () => void;
  /** stops following the shell's foreground CLI */
  fgOff?: () => void;
}

const terms = new Map<number, PanelTerm>();
let look: "dark" | "light" = "dark";

function refit(p: PanelTerm): void {
  if (!p.el.isConnected || p.el.clientWidth === 0 || p.el.clientHeight === 0) return;
  try {
    p.fit.fit();
  } catch {
    /* not measurable yet */
  }
}

function create([{ Terminal }, { FitAddon }]: Xterm, key: number, want: string | null): PanelTerm {
  const settings = readTermSettings();
  const theme = termTheme(look, settings);
  const el = document.createElement("div");
  el.className = "term-host";
  const make = (opts: ITerminalOptions & ITerminalInitOnlyOptions) => {
    const term = new Terminal(opts);
    const fit = new FitAddon();
    term.loadAddon(fit);
    return { term, fit };
  };
  const first = make(termOptions(theme, settings));
  const host = getShellHost();
  const wire = (term: Terminal) => {
    term.onData((d) => {
      if (p.id === null || p.ended) return;
      p.typed = true;
      void host.write(p.id, d).catch(() => undefined);
    });
    term.onResize(({ cols, rows }) => {
      if (p.settle !== null) clearTimeout(p.settle);
      p.settle = setTimeout(() => {
        p.settle = null;
        if (p.id !== null && !p.ended) void host.resize(p.id, cols, rows).catch(() => undefined);
      }, RESIZE_SETTLE_MS);
    });
    // The bell, and the notification escapes agents send instead (OSC 9 with a message, not a `9;<n>` report such as
    // the 9;4 progress bar; OSC 777 `notify`), ring as a TERMINALS terminal's do (sessions.ts): the tab's dot. Their
    // text is never shown or kept.
    const ring = () => {
      if (!p.ended) ringPane(key);
    };
    term.onBell(ring);
    term.parser.registerOscHandler(9, (d) => {
      if (!/^\d+(;|$)/.test(d)) ring();
      return false; // not consumed: another handler may want the escape
    });
    term.parser.registerOscHandler(777, (d) => {
      if (d.startsWith("notify;")) ring();
      return false;
    });
  };
  const p: PanelTerm = {
    get term() {
      return live(this.raw);
    },
    raw: first.term,
    fit: first.fit,
    // a parked terminal made again: the same options and handlers, at the size it had, where it was
    remake: ({ cols, rows }) => {
      const s = readTermSettings();
      const th = termTheme(look, s);
      const next = make({ ...termOptions(th, s), cols, rows });
      p.raw = next.term;
      p.fit = next.fit;
      wire(next.term);
      next.term.open(p.el);
      p.undo = afterOpen(next.term, p.el, s, p.remake);
      applyLook(next.term, th, s);
      return next.term;
    },
    el,
    id: null,
    owed: 0,
    ended: false,
    typed: false,
    saved: false,
    settle: null,
    undo: () => undefined,
  };
  terms.set(key, p);
  wire(first.term);
  return p;
}

function start(key: number, p: PanelTerm, want: string | null): void {
  const host = getShellHost();
  void host
    .start(
      want,
      p.term.cols,
      p.term.rows,
      (d) => {
        // acknowledged once drawn, in order: the shell reads no further ahead of the page than its credit
        const bytes = typeof d === "string" ? utf8.encode(d).length : d.byteLength;
        feed(p.term, d, () => {
          if (p.id === null) p.owed += bytes;
          else host.ack(p.id, bytes);
        });
      },
      (code) => {
        p.ended = true;
        setPaneFg(key, null);
        // as a TERMINALS shell: one that ends (exit, Ctrl+D, any code once the person typed) closes its pane and the
        // pane beside it takes the room; one that ended with an error before any typing stays, saying so
        if (termEnd({ ofChat: false, shell: true, typed: p.typed, code }) === "close") closePane(key);
        else feed(p.term, `\r\n\x1b[2m[${code ? t("termpanel.endedCode", { code }) : t("termpanel.ended")}]\x1b[0m\r\n`);
      },
    )
    .then(
      (started) => {
        if (!terms.has(key)) {
          // the tab closed while the shell started
          void host.close(started.id).catch(() => undefined);
          return;
        }
        p.id = started.id;
        // the tab's mark follows the CLI in the shell's foreground
        p.fgOff = onSessionFg(started.id, (agent) => setPaneFg(key, agent));
        if (p.owed) host.ack(p.id, p.owed);
        p.owed = 0;
        setPaneCwd(key, started.cwd);
      },
      (e) => {
        p.ended = true;
        feed(p.term, `\x1b[31m${t("termpanel.couldNotStart", { error: e instanceof Error ? e.message : String(e) })}\x1b[0m\r\n`);
      },
    );
}

/** Put pane `key`'s terminal into `box` (made and its shell started the first time). Returns what takes it out. */
export function attachTerm(key: number, want: string | null, box: HTMLElement, mode: "dark" | "light"): () => void {
  look = mode;
  let gone = false;
  let detach: (() => void) | null = null;
  const mount = (m: Xterm) => {
    let p = terms.get(key);
    const fresh = !p;
    if (!p) p = create(m, key, want);
    const pt = p;
    box.appendChild(pt.el);
    if (fresh) {
      pt.raw.open(pt.el);
      pt.undo = afterOpen(pt.raw, pt.el, readTermSettings(), pt.remake);
    }
    applyLook(pt.term, termTheme(look, readTermSettings()), readTermSettings());
    refit(pt);
    if (fresh) start(key, pt, want);
    const ro = new ResizeObserver(() => refit(pt));
    ro.observe(box);
    // and when its cells change size (the GPU renderer arrived after this fit, or went)
    const cells = () => refit(pt);
    pt.el.addEventListener(CELLS_EVENT, cells);
    onVisible(pt.term, true);
    // a pane is made when it comes to the front (a new tab, a split): once xterm has loaded, it takes the keyboard
    if (fresh) pt.term.focus();
    detach = () => {
      ro.disconnect();
      pt.el.removeEventListener(CELLS_EVENT, cells);
      onVisible(pt.raw, false);
      if (pt.el.parentElement === box) box.removeChild(pt.el);
    };
  };
  void loadXterm().then((m) => {
    if (!gone) mount(m);
  });
  return () => {
    gone = true;
    detach?.();
  };
}

/** Give pane `key`'s terminal the keyboard (after the panel opens, or a tab or pane is picked). */
export function focusTerm(key: number): void {
  const p = terms.get(key);
  if (!p) return;
  refit(p);
  p.term.focus();
}

/** The panel shows or hides: a hidden terminal gives its GPU context back; a shown one is measured again. */
export function showTerm(key: number, shown: boolean): void {
  const p = terms.get(key);
  if (!p) return;
  onVisible(shown ? p.term : p.raw, shown);
  if (shown) refit(p);
}

/** Close pane `key`: its shell is stopped, its terminal thrown away and the files dropped on it removed. */
export function disposeTerm(key: number): void {
  const p = terms.get(key);
  if (!p) return;
  terms.delete(key);
  if (p.id !== null && !p.ended) void getShellHost().close(p.id).catch(() => undefined);
  if (p.saved && p.id !== null) void getHost().removeFiles(filesId(p.id)).catch(() => undefined);
  p.ended = true;
  if (p.settle !== null) clearTimeout(p.settle);
  const wasParked = isParked(p.raw);
  p.undo();
  p.fgOff?.();
  if (!wasParked) p.raw.dispose(); // a parked one was disposed when it was parked
  p.el.remove();
}

/** Every panel terminal takes the look again (the app theme or a terminal setting changed). */
export function relookTerms(mode: "dark" | "light" = look): void {
  look = mode;
  const settings = readTermSettings();
  const theme = termTheme(look, settings);
  for (const p of terms.values()) {
    if (isParked(p.raw)) continue; // takes the look when it is made again
    applyLook(p.term, theme, settings);
    refit(p);
  }
}
onTermSettings(() => relookTerms());

/** The folder name a panel shell's saved files go under (`~/.omher/session-files/<this>/`): `s0` and the shell's
 *  session id. A TERMINALS session's ids are `s1`, `s2`... (never a leading zero), so the two never share a folder. */
export const filesId = (shellId: number): string => `s0${shellId}`;

/** A file as a terminal's drop and paste hand it on. */
export interface DroppedFile {
  name: string;
  read: () => Promise<Uint8Array>;
}
export const fileIn = (f: File): DroppedFile => ({ name: f.name || "pasted.png", read: async () => new Uint8Array(await f.arrayBuffer()) });
export const isWindows = (): boolean => typeof navigator !== "undefined" && /^Win/.test(navigator.platform);

/** A file dropped on `el`, or a picture pasted there, goes to `onFiles` (as a system terminal types a dropped file's
 *  path). Plain text pastes stay xterm's own. Shared by TERMINALS (SessionView) and the bottom panel's panes. */
export function wireFileDrop(el: HTMLElement, onFiles: (files: DroppedFile[]) => void): () => void {
  const hasFiles = (e: DragEvent) => !!e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  const over = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  };
  const drop = (e: DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    const files = [...(e.dataTransfer?.files ?? [])];
    if (files.length) onFiles(files.map(fileIn));
  };
  const paste = (e: ClipboardEvent) => {
    const files = [...(e.clipboardData?.files ?? [])];
    if (!files.length) return;
    e.preventDefault();
    e.stopPropagation();
    onFiles(files.map(fileIn));
  };
  el.addEventListener("dragenter", over);
  el.addEventListener("dragover", over);
  el.addEventListener("drop", drop);
  el.addEventListener("paste", paste, true);
  return () => {
    el.removeEventListener("dragenter", over);
    el.removeEventListener("dragover", over);
    el.removeEventListener("drop", drop);
    el.removeEventListener("paste", paste, true);
  };
}

/** Files dropped or pasted on pane `key`: each saved under its shell's own folder (the page never sees a dropped file's
 *  own path), then the saved paths typed at its prompt, shell-quoted, as TERMINALS does (sessions.ts dropOnTerminal). */
export async function dropOnPane(key: number, files: DroppedFile[], windows = isWindows()): Promise<void> {
  const p = terms.get(key);
  if (!p || p.id === null || p.ended) return;
  const id = p.id;
  const paths: string[] = [];
  for (const f of files) {
    try {
      paths.push(shellQuote(await getHost().saveFile(filesId(id), f.name, await f.read()), windows));
      p.saved = true;
    } catch (e) {
      feed(p.term, `\r\n\x1b[31m${t("att.failed", { name: f.name, error: e instanceof Error ? e.message : String(e) })}\x1b[0m\r\n`);
      return;
    }
  }
  if (!paths.length || p.ended) return;
  p.typed = true;
  await getShellHost().write(id, `${paths.join(" ")} `);
  p.term.focus();
}
