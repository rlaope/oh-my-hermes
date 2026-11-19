// The xterm side of the bottom terminal panel: one terminal per tab, kept for the page's life so a hidden panel (or
// a tab in the back) keeps its scrollback while its shell runs on. Built from the SESSIONS terminal engine
// (src/sessions/term: look, Orca themes, renderer, find, links, clipboard settings), imported, not copied.
import type { ITerminalInitOnlyOptions, ITerminalOptions, Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { afterOpen, CELLS_EVENT, feed, isParked, live, onVisible, type Remake } from "../sessions/term/engine";
import { onCwd } from "../sessions/term/engine-marks";
import { applyLook, termOptions } from "../sessions/term/look";
import { termFontsReady } from "../sessions/term/fonts";
import { onTermSettings, readTermSettings } from "../sessions/term/settings";
import { termTheme } from "../sessions/term/themes";
import { t } from "../i18n";
import { getShellHost } from "./host";
import { setTabCwd, setTabFg } from "./state";
import { onSessionFg } from "../sessions/fg";

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
  settle: ReturnType<typeof setTimeout> | null;
  undo: () => void;
  /** stops following the shell's foreground CLI */
  fgOff?: () => void;
  /** stops following the folder its shell reports */
  cwdOff?: () => void;
  /** its shell reported a folder (OSC 7), which the folder it started in no longer overrides */
  cwdSaid?: boolean;
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
      if (p.id !== null && !p.ended) void host.write(p.id, d).catch(() => undefined);
    });
    term.onResize(({ cols, rows }) => {
      if (p.settle !== null) clearTimeout(p.settle);
      p.settle = setTimeout(() => {
        p.settle = null;
        if (p.id !== null && !p.ended) void host.resize(p.id, cols, rows).catch(() => undefined);
      }, RESIZE_SETTLE_MS);
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
    settle: null,
    undo: () => undefined,
  };
  terms.set(key, p);
  wire(first.term);
  // the folder its shell reports (OSC 7) names the tab; the element outlives a parked terminal made again
  p.cwdOff = onCwd(el, (path) => {
    p.cwdSaid = true;
    setTabCwd(key, path);
  });
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
        setTabFg(key, null);
        feed(p.term, `\r\n\x1b[2m[${code ? t("termpanel.endedCode", { code }) : t("termpanel.ended")}]\x1b[0m\r\n`);
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
        p.fgOff = onSessionFg(started.id, (agent) => setTabFg(key, agent));
        if (p.owed) host.ack(p.id, p.owed);
        p.owed = 0;
        if (!p.cwdSaid) setTabCwd(key, started.cwd);
      },
      (e) => {
        p.ended = true;
        feed(p.term, `\x1b[31m${t("termpanel.couldNotStart", { error: e instanceof Error ? e.message : String(e) })}\x1b[0m\r\n`);
      },
    );
}

/** Put tab `key`'s terminal into `box` (made and its shell started the first time). Returns what takes it out. */
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
    // a tab is made when it comes to the front: once xterm has loaded, it takes the keyboard
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

/** Give tab `key`'s terminal the keyboard (after the panel opens or a tab is picked). */
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

/** Close tab `key`: its shell is stopped and its terminal thrown away. */
export function disposeTerm(key: number): void {
  const p = terms.get(key);
  if (!p) return;
  terms.delete(key);
  if (p.id !== null && !p.ended) void getShellHost().close(p.id).catch(() => undefined);
  p.ended = true;
  if (p.settle !== null) clearTimeout(p.settle);
  const wasParked = isParked(p.raw);
  p.undo();
  p.fgOff?.();
  p.cwdOff?.();
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
