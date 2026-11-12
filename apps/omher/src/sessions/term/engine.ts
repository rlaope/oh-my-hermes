// How a SESSIONS terminal draws and takes its program's output: what is attached once it is on the page (the
// renderer, add-ons) and how bytes from the program reach it.
//
// Renderer: the GPU (WebGL) add-on, lazily loaded, by `settings.gpu`. A terminal that cannot or should not use it
// keeps xterm's standard renderer and shows nothing about it. A lost context drops back to the standard renderer at
// once and is tried again later (three losses in 60 s stop it for that terminal). A terminal that leaves the page
// gives its GPU context back (its program keeps running and its output keeps being parsed) and takes one again when
// it returns, so many open sessions never run into the browser's cap on live contexts.
import type { Terminal } from "@xterm/xterm";
import type { WebglAddon } from "@xterm/addon-webgl";
import { canRetry, probeWebgl, recordLoss } from "./engine-policy";
import { onTermSettings, type TermSettings } from "./settings";
import { attachLinks } from "./engine-links";
import { attachInput } from "./engine-input";
import { FIND_EVENT, makeFinder, type FindRequest } from "./engine-find";

/** The add-on's chunk loads the first time a terminal wants it, never with the app and never while `gpu` is off. */
let webglLoad: Promise<typeof WebglAddon> | null = null;
const loadWebgl = () =>
  (webglLoad ??= import("@xterm/addon-webgl").then(
    (m) => m.WebglAddon,
    (e) => {
      webglLoad = null;
      throw e;
    },
  ));

/** The Unicode 11 add-on loads with the first terminal (with xterm), not with the app. */
let unicodeLoad: Promise<typeof import("@xterm/addon-unicode11").Unicode11Addon> | null = null;
const loadUnicode = () => (unicodeLoad ??= import("@xterm/addon-unicode11").then((m) => m.Unicode11Addon));

/** Pause before a terminal tries the GPU renderer again after losing its context. */
const RETRY_AFTER_MS = 2000;

interface State {
  term: Terminal;
  gpu: TermSettings["gpu"];
  shown: boolean;
  addon: WebglAddon | null;
  /** an attach is waiting for the add-on's chunk */
  loading: boolean;
  /** times (ms) this terminal lost its context */
  losses: number[];
  /** three losses in a window: no more tries until the setting changes */
  gaveUp: boolean;
  retry: ReturnType<typeof setTimeout> | null;
  gone: boolean;
  /** drops the listeners of the attached add-on */
  unwatch: (() => void) | null;
  /** output that came before the Unicode 11 widths were active, in order; null once they are */
  held: (() => void)[] | null;
}

const states = new Map<Terminal, State>();
let stopSettings: (() => void) | null = null;

const wants = (s: State) => !s.gone && s.shown && !s.gaveUp && !s.addon && s.gpu !== "off" && (s.gpu === "on" || probeWebgl().allow);

function detach(s: State): void {
  s.unwatch?.();
  s.unwatch = null;
  const a = s.addon;
  s.addon = null;
  if (!a) return;
  try {
    a.dispose(); // xterm puts its standard renderer back
  } catch {
    /* already gone with its context */
  }
}

function repaint(s: State): void {
  if (s.gone) return;
  try {
    s.term.refresh(0, s.term.rows - 1);
  } catch {
    /* not drawable yet */
  }
}

function attach(s: State): void {
  if (!wants(s) || s.loading) return;
  s.loading = true;
  void loadWebgl().then(
    (Ctor) => {
      s.loading = false;
      if (!wants(s)) return; // hidden, switched off or closed while the chunk came
      const addon = new Ctor();
      const before = new Set(s.term.element?.querySelectorAll("canvas") ?? []);
      try {
        const off = addon.onContextLoss(() => lost(s, addon));
        s.term.loadAddon(addon);
        s.addon = addon;
        // xterm waits 3 s for a lost context to come back before it says so, and draws nothing meanwhile: the
        // canvas's own event sends the terminal back to the standard renderer at once
        const onLost = () => lost(s, addon);
        const canvases = [...(s.term.element?.querySelectorAll("canvas") ?? [])].filter((c) => !before.has(c));
        for (const c of canvases) c.addEventListener("webglcontextlost", onLost);
        s.unwatch = () => {
          off.dispose();
          for (const c of canvases) c.removeEventListener("webglcontextlost", onLost);
        };
      } catch {
        // no context, or the add-on would not start: keep the standard renderer, say nothing
        s.addon = null;
        try {
          addon.dispose();
        } catch {
          /* never fully started */
        }
        return;
      }
      repaint(s);
    },
    () => {
      s.loading = false; // the chunk would not load: standard renderer
    },
  );
}

function lost(s: State, addon: WebglAddon): void {
  if (s.addon !== addon) return; // a loss already handled
  detach(s);
  repaint(s);
  const now = Date.now();
  s.losses = recordLoss(s.losses, now);
  if (!canRetry(s.losses, now)) {
    s.gaveUp = true;
    return;
  }
  if (s.retry) clearTimeout(s.retry);
  s.retry = setTimeout(() => {
    s.retry = null;
    attach(s);
  }, RETRY_AFTER_MS);
}

function reconsider(settings: TermSettings): void {
  for (const s of states.values()) {
    if (s.gpu !== settings.gpu) s.gaveUp = false;
    s.gpu = settings.gpu;
    if (s.gpu === "off" || (s.gpu === "auto" && !probeWebgl().allow)) {
      detach(s);
      repaint(s);
    } else attach(s);
  }
}

/** Called once, right after `term.open(el)`. Returns what undoes it (called before the terminal is disposed). */
export function afterOpen(term: Terminal, el: HTMLElement, settings: TermSettings): () => void {
  const s: State = { term, gpu: settings.gpu, shown: el.isConnected, addon: null, loading: false, losses: [], gaveUp: false, retry: null, gone: false, unwatch: null, held: [] };
  states.set(term, s);
  // CJK, emoji and box drawing take the widths agents' TUIs expect. Output waits (in order) until they are active.
  const release = () => {
    const q = s.held;
    s.held = null;
    for (const w of q ?? []) w();
  };
  void loadUnicode().then(
    (Unicode11Addon) => {
      if (!s.gone) {
        try {
          term.loadAddon(new Unicode11Addon());
          term.unicode.activeVersion = "11";
        } catch {
          /* proposed API off: keep xterm's own widths */
        }
      }
      release();
    },
    release, // the chunk would not load: xterm's own widths
  );
  // links (Cmd/Ctrl+click), find (Cmd/Ctrl+F, the bar listens for the event) and the two clipboard settings
  const finder = makeFinder(term);
  const undoLinks = attachLinks(term);
  const undoInput = attachInput(term, el, () => {
    const detail: FindRequest = { term, finder };
    el.dispatchEvent(new CustomEvent<FindRequest>(FIND_EVENT, { bubbles: true, detail }));
  });
  stopSettings ??= onTermSettings(reconsider);
  attach(s);
  return () => {
    undoInput();
    undoLinks();
    finder.dispose();
    s.gone = true;
    s.held = null;
    if (s.retry) clearTimeout(s.retry);
    detach(s);
    states.delete(term);
    if (!states.size) {
      stopSettings?.();
      stopSettings = null;
    }
  };
}

/** Output from the program into the terminal. `done` runs once the terminal has taken these bytes. */
export function feed(term: Terminal, data: string | Uint8Array, done?: () => void): void {
  const s = states.get(term);
  if (s?.held) s.held.push(() => term.write(data, done));
  else term.write(data, done);
}

/** What draws the terminals now: the GPU renderer, the standard one, or null while no terminal is open.
 *  Settings shows it, so a person (and a check of the real window) can see which is in use. */
export function rendererInUse(): "gpu" | "standard" | null {
  if (!states.size) return null;
  for (const s of states.values()) if (s.shown && s.addon) return "gpu";
  return "standard";
}

/** A terminal came onto the page (`shown`) or left it while its program keeps running. */
export function onVisible(term: Terminal, shown: boolean): void {
  const s = states.get(term);
  if (!s || s.gone) return;
  s.shown = shown;
  if (!shown) {
    if (s.retry) {
      clearTimeout(s.retry);
      s.retry = null;
    }
    detach(s); // gives the GPU context back
    return;
  }
  if (s.addon) repaint(s);
  else attach(s);
}
