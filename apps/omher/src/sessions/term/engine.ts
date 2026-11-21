// How a SESSIONS terminal draws and takes its program's output: what is attached once it is on the page (the
// renderer, add-ons) and how bytes from the program reach it.
//
// Renderer: the GPU (WebGL) add-on, lazily loaded, by `settings.gpu`. A terminal that cannot or should not use it
// keeps xterm's standard renderer and shows nothing about it. A lost context drops back to the standard renderer at
// once and is tried again later (three losses in 60 s stop it for that terminal). A terminal that leaves the page
// gives its GPU context back (its program keeps running and its output keeps being parsed) and takes one again when
// it returns, so many open sessions never run into the browser's cap on live contexts. While it is away it draws no
// rows at all (engine-hidden.ts); shown, it draws its screen and selection once. One that stays away and quiet long
// enough is parked (park.ts): kept as a snapshot, its xterm disposed, and made again when it is shown or prints.
import type { Terminal } from "@xterm/xterm";
import type { WebglAddon } from "@xterm/addon-webgl";
import { canRetry, probeWebgl, recordLoss } from "./engine-policy";
import { hideRows, showRows } from "./engine-hidden";
import { cannotPark, carriedOf, dueToPark, extras, innerOf, limits, putCarried, type Carried } from "./park";
import { onTermSettings, type TermSettings } from "./settings";
import { attachLinks } from "./engine-links";
import { attachInput } from "./engine-input";
import { attachIme } from "./engine-ime";
import { attachMarks } from "./engine-marks";
import { attachOsc52 } from "./engine-osc52";
import { FIND_EVENT, makeFinder, type FindRequest } from "./engine-find";
import { attachImages, detachImages, loadImages } from "./engine-image";
import { GPU_OPTIONS } from "./look";

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

/** The grapheme-aware widths (Unicode 15, a ZWJ family or a flag is one wide cell, not one per code point) load with
 *  the first terminal (with xterm), not with the app. */
let unicodeLoad: Promise<typeof import("@xterm/addon-unicode-graphemes").UnicodeGraphemesAddon> | null = null;
const loadUnicode = () => (unicodeLoad ??= import("@xterm/addon-unicode-graphemes").then((m) => m.UnicodeGraphemesAddon));

/** Pause before a terminal tries the GPU renderer again after losing its context. */
const RETRY_AFTER_MS = 2000;

interface State {
  term: Terminal;
  gpu: TermSettings["gpu"];
  shown: boolean;
  addon: WebglAddon | null;
  /** it drew with the GPU the last time it was on the page and nothing has taken that away: a terminal that left
   *  the page (Settings is open) gave its context back but still counts as a GPU terminal for `rendererInUse` */
  gpuLast: boolean;
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
  /** output that came before the grapheme widths were active, in order; null once they are */
  held: (() => void)[] | null;
  /** when it left the page (ms); null while it is on it */
  hiddenAt: number | null;
  /** when its program last printed (ms) */
  lastOut: number;
  /** writes the terminal has not taken yet */
  pending: number;
  /** makes the terminal again after it was parked (null: its owner cannot, so it is never parked) */
  remake: Remake | null;
  el: HTMLElement;
  /** the undo `afterOpen` returned, run once */
  undo: () => void;
  /** Settings > Terminal > Show images, as this terminal last read it */
  images: boolean;
}

/** Makes a parked terminal again: a new `Terminal` at this size with its owner's options and handlers, opened on the
 *  same element and passed to `afterOpen`. The engine then writes the snapshot into it. */
export type Remake = (size: { cols: number; rows: number }) => Terminal;

/** A parked terminal: its snapshot and what the one made from it takes over. */
interface Parked {
  /** UTF-8: the add-on builds its string from many small pieces, which V8 keeps as a rope several times its length */
  snapshot: Uint8Array;
  /** what the snapshot leaves out (saved cursor, tab stops, scroll position), put back once it is read */
  carried: Carried;
  cols: number;
  rows: number;
  remake: Remake;
  hiddenAt: number | null;
  lastOut: number;
  gpuLast: boolean;
  gaveUp: boolean;
  losses: number[];
  /** the program had turned on bracketed paste (DECSET 2004) when it was parked; the snapshot turns it on again. Its
   *  output makes the terminal again before it is read, so the mode cannot change while parked */
  paste: boolean;
}
const parked = new Map<Terminal, Parked>();
/** a parked terminal that was made again: the one that replaced it */
const remade = new WeakMap<Terminal, Terminal>();
/** a terminal made again whose snapshot xterm has not read yet: the paste mode it had (its own reads the old one) */
const restoring = new WeakMap<Terminal, boolean>();
/** what the next `afterOpen` takes over from the parked terminal it replaces */
let carry: Parked | null = null;

const states = new Map<Terminal, State>();
let stopSettings: (() => void) | null = null;
/** the GPU setting as the engine last read it (a parked terminal has no state to keep it in) */
let gpuSetting: TermSettings["gpu"] = "auto";

const wants = (s: State) => !s.gone && s.shown && !s.gaveUp && !s.addon && s.gpu !== "off" && (s.gpu === "on" || probeWebgl().allow);

/** `release`: the terminal left the page, so its context goes but it would take one again on its return. */
function detach(s: State, release = false): void {
  if (!release) s.gpuLast = false;
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

/** Sent on a terminal's element when its cells change size while it is on the page: the GPU renderer came or went
 *  (it draws in whole device pixels, the standard one does not) or a font arrived. Its owner fits it to its box
 *  again, as it does when the box changes size; otherwise the program keeps printing at a width the box no longer
 *  has, and a screen it drew at that width moves when the next fit reflows it. */
export const CELLS_EVENT = "omher-term-cells";

/** Sent on a terminal's element just before it is parked, while its xterm can still be read: its owner takes what
 *  it was about to read from the screen now, as reading it after the park would make the terminal again. */
export const PARKING_EVENT = "omher-term-parking";

function cellsChanged(s: State): void {
  if (!s.gone && s.shown) s.el.dispatchEvent(new Event(CELLS_EVENT));
}

/** A terminal just shown is waiting for the GPU renderer, which will tell its owner when its cells are known
 *  (`CELLS_EVENT`): a fit made before that measures the standard renderer's cells, and the one after it undoes it, so
 *  the program's screen is reflowed twice for nothing. */
export function gpuComing(term: Terminal): boolean {
  const s = states.get(term);
  return !!s && s.shown && (s.loading || wants(s));
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
      if (!wants(s)) return cellsChanged(s); // hidden, switched off or closed while the chunk came
      const addon = new Ctor(GPU_OPTIONS);
      const before = new Set(s.term.element?.querySelectorAll("canvas") ?? []);
      try {
        const off = addon.onContextLoss(() => lost(s, addon));
        s.term.loadAddon(addon);
        s.addon = addon;
        s.gpuLast = true;
        // xterm waits 3 s for a lost context to come back before it says so, and draws nothing meanwhile: the
        // canvas's own event sends the terminal back to the standard renderer at once
        const onLost = () => lost(s, addon);
        const canvases = [...(s.term.element?.querySelectorAll("canvas") ?? [])].filter((c) => !before.has(c));
        for (const c of canvases) c.addEventListener("webglcontextlost", onLost);
        s.unwatch = () => {
          off.dispose();
          for (const c of canvases) c.removeEventListener("webglcontextlost", onLost);
        };
        cellsChanged(s);
      } catch {
        // no context, or the add-on would not start: keep the standard renderer, say nothing
        s.addon = null;
        try {
          addon.dispose();
        } catch {
          /* never fully started */
        }
        cellsChanged(s); // the owner held its fit for this renderer
        return;
      }
      repaint(s);
    },
    () => {
      s.loading = false; // the chunk would not load: standard renderer
      cellsChanged(s);
    },
  );
}

function lost(s: State, addon: WebglAddon): void {
  if (s.addon !== addon) return; // a loss already handled
  detach(s);
  cellsChanged(s);
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

/** Pictures on or off for one terminal: the add-on's chunk loads the first time one wants it. Off drops the pictures
 *  it kept; output that comes while the chunk loads is drawn as before (a picture in it is skipped). */
function images(s: State, on: boolean): void {
  s.images = on;
  if (!on) return detachImages(s.term);
  void loadImages().then(
    (Ctor) => {
      if (!s.gone && s.images) attachImages(s.term, Ctor);
    },
    () => undefined, // the chunk would not load: no pictures
  );
}

function reconsider(settings: TermSettings): void {
  if (settings.gpu !== gpuSetting) for (const p of parked.values()) p.gaveUp = false;
  gpuSetting = settings.gpu;
  for (const s of states.values()) {
    if (!s.gone && s.images !== settings.images) images(s, settings.images);
    if (s.gpu !== settings.gpu) s.gaveUp = false;
    s.gpu = settings.gpu;
    if (s.gpu === "off" || (s.gpu === "auto" && !probeWebgl().allow)) {
      const had = !!s.addon;
      detach(s);
      if (had) cellsChanged(s);
      repaint(s);
    } else attach(s);
  }
}

/** Called once, right after `term.open(el)`. Returns what undoes it (called before the terminal is disposed). */
export function afterOpen(term: Terminal, el: HTMLElement, settings: TermSettings, remake?: Remake): () => void {
  const now = Date.now();
  gpuSetting = settings.gpu;
  const c = carry;
  carry = null;
  // a parked terminal is made again away from the page (the bottom panel's element stays connected while the panel
  // is hidden); the show that made it again says so right after
  const shown = !c && el.isConnected;
  const s: State = {
    term,
    gpu: settings.gpu,
    shown,
    addon: null,
    gpuLast: c?.gpuLast ?? false,
    loading: false,
    losses: c?.losses ?? [],
    gaveUp: c?.gaveUp ?? false,
    retry: null,
    gone: false,
    unwatch: null,
    held: [],
    hiddenAt: shown ? null : (c?.hiddenAt ?? now),
    lastOut: c?.lastOut ?? now,
    pending: 0,
    remake: remake ?? null,
    el,
    undo: () => undefined,
    images: false,
  };
  states.set(term, s);
  // CJK, emoji (a ZWJ family, a flag, a skin tone: one wide cell) and box drawing take the widths agents' TUIs
  // expect. Output waits (in order) until they are active.
  const release = () => {
    const q = s.held;
    s.held = null;
    for (const w of q ?? []) w();
  };
  void loadUnicode().then(
    (UnicodeGraphemesAddon) => {
      if (!s.gone) {
        try {
          term.loadAddon(new UnicodeGraphemesAddon()); // makes "15-graphemes" the active version
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
  // Korean, Japanese and Chinese input methods: each committed text reaches the program once (engine-ime.ts)
  const undoIme = attachIme(term, el);
  // what the shell says of itself: prompt marks (OSC 133), its folder (OSC 7), progress (OSC 9;4) (engine-marks.ts)
  const undoMarks = attachMarks(term, el);
  // a program's copy to the clipboard (OSC 52), copy only (engine-osc52.ts)
  const undoOsc52 = attachOsc52(term, el);
  // a font that arrives after the terminal drew (the symbols font loads on its first glyph, or JetBrains Mono came
  // after the wait for it gave up): the cell is measured again in the font now drawn, and the GPU renderer's glyph
  // cache, which holds the fallback's shapes, is cleared
  const fonts = typeof document !== "undefined" ? document.fonts : undefined;
  const fontsLoaded = () => {
    if (s.gone) return;
    try {
      (term as unknown as { _core?: { _charSizeService?: { measure?(): void } } })._core?._charSizeService?.measure?.();
      term.clearTextureAtlas();
    } catch {
      /* not drawable yet */
    }
    cellsChanged(s);
    repaint(s);
  };
  fonts?.addEventListener?.("loadingdone", fontsLoaded);
  stopSettings ??= onTermSettings(reconsider);
  if (!s.shown) hideRows(term);
  attach(s);
  if (settings.images) images(s, true);
  s.undo = () => {
    if (s.gone) return;
    fonts?.removeEventListener?.("loadingdone", fontsLoaded);
    undoMarks();
    undoOsc52();
    undoIme();
    undoInput();
    undoLinks();
    finder.dispose();
    s.gone = true;
    s.held = null;
    if (s.retry) clearTimeout(s.retry);
    detach(s);
    detachImages(term);
    states.delete(term);
    settingsWhileOpen();
    sweepWhenHidden();
  };
  sweepWhenHidden();
  // a parked terminal's undo only forgets its snapshot (its add-ons went when it was parked)
  return () => {
    if (parked.delete(term)) settingsWhileOpen();
    else s.undo();
  };
}

/** The settings listener stays while any terminal is open, parked ones included (`rendererInUse` reads them). */
function settingsWhileOpen(): void {
  if (states.size || parked.size) return;
  stopSettings?.();
  stopSettings = null;
}

/** The terminal to use now: a parked one is made again first, from its snapshot, where it was (off the page unless it
 *  is being shown). Its owner reads its terminal through this, so output, a show or a close reach the new one. */
export function live(term: Terminal): Terminal {
  const moved = remade.get(term);
  if (moved) return live(moved);
  const p = parked.get(term);
  if (!p) return term;
  parked.delete(term);
  carry = p;
  let next: Terminal;
  try {
    next = p.remake({ cols: p.cols, rows: p.rows });
  } catch (e) {
    parked.set(term, p); // the snapshot is kept for the next try
    throw e;
  } finally {
    carry = null;
  }
  remade.set(term, next);
  restoring.set(next, p.paste);
  const s = states.get(next);
  // the snapshot is not the program's output: it neither counts as output nor waits for an ack. It is pending, though:
  // parked again before xterm has taken all of it, the next snapshot would miss the rest
  if (!s)
    next.write(p.snapshot, () => {
      putCarried(next, p.carried);
      restoring.delete(next);
    });
  else {
    s.pending++;
    // the write callback runs before xterm parses the next write, so the program's next bytes see it all
    const took = () => {
      putCarried(next, p.carried);
      restoring.delete(next);
      s.pending--;
    };
    if (s.held) s.held.push(() => next.write(p.snapshot, took));
    else next.write(p.snapshot, took); // xterm decodes UTF-8 bytes itself
  }
  return next;
}

/** Whether `term` is parked: it has no xterm (nothing to dispose) until `live` makes it again. */
export const isParked = (term: Terminal): boolean => parked.has(term);

/** Whether the program in `term` turned on bracketed paste, read without making a parked terminal again (a parked one
 *  says what it had when it was parked). */
export function bracketedPaste(term: Terminal): boolean {
  const moved = remade.get(term);
  if (moved) return bracketedPaste(moved);
  const p = parked.get(term);
  if (p) return p.paste;
  return restoring.get(term) ?? term.modes.bracketedPasteMode;
}

const utf8 = new TextEncoder();
let sweepTimer: ReturnType<typeof setInterval> | null = null;
let serializeLoad: Promise<typeof import("@xterm/addon-serialize").SerializeAddon> | null = null;
const loadSerialize = () =>
  (serializeLoad ??= import("@xterm/addon-serialize").then(
    (m) => m.SerializeAddon,
    (e) => {
      serializeLoad = null;
      throw e;
    },
  ));

/** One timer for every terminal, running only while some terminal is off the page. */
function sweepWhenHidden(): void {
  const need = [...states.values()].some((s) => !s.gone && !s.shown && s.remake);
  if (need && !sweepTimer) sweepTimer = setInterval(sweep, limits.sweepMs);
  else if (!need && sweepTimer) {
    clearInterval(sweepTimer);
    sweepTimer = null;
  }
}

const due = (s: State, now: number) => !s.gone && !s.shown && !!s.remake && s.pending === 0 && !s.held && dueToPark({ hiddenAt: s.hiddenAt, lastOut: s.lastOut, now });

function sweep(): void {
  const now = Date.now();
  if (![...states.values()].some((s) => due(s, now))) return;
  void loadSerialize().then(
    (Ctor) => {
      const at = Date.now();
      for (const s of [...states.values()]) if (due(s, at)) park(s, Ctor);
    },
    () => undefined, // the chunk would not load: nothing is parked
  );
}

function park(s: State, Serialize: typeof import("@xterm/addon-serialize").SerializeAddon): void {
  const term = s.term;
  const inner = innerOf(term);
  if (!inner || cannotPark(inner) !== null) return;
  const carried = carriedOf(term);
  if (!carried) return;
  s.el.dispatchEvent(new Event(PARKING_EVENT));
  let snapshot: string;
  const ser = new Serialize();
  try {
    term.loadAddon(ser);
    // The add-on parks the cursor with a move relative to the end of the last row, which is one column off when that
    // row is full width (the end is a pending wrap, not a column): a full-width status bar on a vim or htop screen.
    // An absolute move after it puts the cursor where the program had it (a pending wrap is not kept: nothing relies on one).
    const at = term.buffer.active;
    snapshot = ser.serialize() + `\x1b[${at.cursorY + 1};${Math.min(at.cursorX, term.cols - 1) + 1}H` + extras(inner);
  } catch {
    return;
  } finally {
    ser.dispose();
  }
  const title = (term as unknown as { _core?: { _inputHandler?: { _windowTitle?: unknown } } })._core?._inputHandler?._windowTitle;
  if (typeof title === "string" && title) snapshot += `\x1b]2;${title}\x07`;
  parked.set(term, { snapshot: utf8.encode(snapshot), carried, cols: term.cols, rows: term.rows, remake: s.remake!, hiddenAt: s.hiddenAt, lastOut: s.lastOut, gpuLast: s.gpuLast, gaveUp: s.gaveUp, losses: s.losses, paste: inner.modes.bracketedPasteMode });
  // a find bar left open on it (the bottom panel keeps one while hidden) closes: its terminal is going
  s.el.dispatchEvent(new CustomEvent(FIND_EVENT, { bubbles: true, detail: null }));
  s.undo();
  if (import.meta.env?.DEV && typeof window !== "undefined") (window as unknown as { __omherTerms?: Set<Terminal> }).__omherTerms?.delete(term);
  // the disposed xterm object stays referenced (by its owner until it is made again) and dispose leaves its buffers
  // in place: a reset first drops the scrollback to one empty screen
  try {
    term.reset();
  } catch {
    /* nothing to drop */
  }
  term.dispose();
}

/** Output from the program into the terminal. `done` runs once the terminal has taken these bytes. */
export function feed(term: Terminal, data: string | Uint8Array, done?: () => void): void {
  term = live(term);
  const s = states.get(term);
  if (!s) return void term.write(data, done);
  s.lastOut = Date.now();
  s.pending++;
  const cb = () => {
    s.pending--;
    done?.();
  };
  if (s.held) s.held.push(() => term.write(data, cb));
  else term.write(data, cb);
}

/** What draws the terminals now: the GPU renderer, the standard one, or null while no terminal is open.
 *  Settings shows it, so a person (and a check of the real window) can see which is in use. Settings is itself a
 *  page no terminal is on, so a terminal that left the page counts as GPU when it drew with the GPU until then. */
export function rendererInUse(): "gpu" | "standard" | null {
  if (!states.size && !parked.size) return null;
  for (const s of states.values()) if (!s.gone && (s.addon || (!s.shown && s.gpuLast && !s.gaveUp && s.gpu !== "off"))) return "gpu";
  for (const p of parked.values()) if (p.gpuLast && !p.gaveUp && gpuSetting !== "off") return "gpu";
  return "standard";
}

/** A terminal came onto the page (`shown`) or left it while its program keeps running. */
export function onVisible(term: Terminal, shown: boolean): void {
  if (!shown && parked.has(term)) return; // already away
  term = live(term);
  const s = states.get(term);
  if (!s || s.gone) return;
  s.shown = shown;
  s.hiddenAt = shown ? null : (s.hiddenAt ?? Date.now());
  sweepWhenHidden();
  if (!shown) {
    if (s.retry) {
      clearTimeout(s.retry);
      s.retry = null;
    }
    detach(s, true); // gives the GPU context back
    hideRows(term); // and draws nothing until it is back
    return;
  }
  showRows(term);
  if (s.addon) repaint(s);
  else attach(s);
}

/** e2e only (a dev build): shorter park thresholds, and how many terminals are parked. A release build has none. */
if (import.meta.env?.DEV && typeof window !== "undefined") {
  (window as unknown as { __omherPark?: unknown }).__omherPark = {
    set(l: Partial<typeof limits>) {
      Object.assign(limits, l);
      if (sweepTimer) clearInterval(sweepTimer);
      sweepTimer = null;
      sweepWhenHidden();
    },
    parked: () => parked.size,
    /** the parked (disposed) xterm objects, so a bench can count what they still hold */
    held: () => [...parked.keys()],
    /** what the snapshots take (bytes) */
    snapshotBytes: () => [...parked.values()].reduce((n, p) => n + p.snapshot.byteLength, 0),
  };
}
