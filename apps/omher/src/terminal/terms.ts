// The xterm side of the bottom terminal panel: one terminal per tab, kept for the page's life so a hidden panel (or
// a tab in the back) keeps its scrollback while its shell runs on. Built from the SESSIONS terminal engine
// (src/sessions/term: look, Orca themes, renderer, find, links, clipboard settings), imported, not copied.
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { afterOpen, feed, onVisible } from "../sessions/term/engine";
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
  term: Terminal;
  fit: FitAddon;
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
  const term = new Terminal(termOptions(theme, settings));
  const fit = new FitAddon();
  term.loadAddon(fit);
  const p: PanelTerm = { term, fit, el, id: null, owed: 0, ended: false, settle: null, undo: () => undefined };
  terms.set(key, p);
  const host = getShellHost();
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
        p.term.write(`\r\n\x1b[2m[${code ? t("termpanel.endedCode", { code }) : t("termpanel.ended")}]\x1b[0m\r\n`);
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
        setTabCwd(key, started.cwd);
      },
      (e) => {
        p.ended = true;
        p.term.write(`\x1b[31m${t("termpanel.couldNotStart", { error: e instanceof Error ? e.message : String(e) })}\x1b[0m\r\n`);
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
      pt.term.open(pt.el);
      pt.undo = afterOpen(pt.term, pt.el, readTermSettings());
    }
    applyLook(pt.term, termTheme(look, readTermSettings()), readTermSettings());
    refit(pt);
    if (fresh) start(key, pt, want);
    const ro = new ResizeObserver(() => refit(pt));
    ro.observe(box);
    onVisible(pt.term, true);
    // a tab is made when it comes to the front: once xterm has loaded, it takes the keyboard
    if (fresh) pt.term.focus();
    detach = () => {
      ro.disconnect();
      onVisible(pt.term, false);
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
  onVisible(p.term, shown);
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
  p.undo();
  p.fgOff?.();
  p.term.dispose();
  p.el.remove();
}

/** Every panel terminal takes the look again (the app theme or a terminal setting changed). */
export function relookTerms(mode: "dark" | "light" = look): void {
  look = mode;
  const settings = readTermSettings();
  const theme = termTheme(look, settings);
  for (const p of terms.values()) {
    applyLook(p.term, theme, settings);
    refit(p);
  }
}
onTermSettings(() => relookTerms());
