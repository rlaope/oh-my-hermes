// A terminal that has been off the page for a while and has printed nothing for a while gives its memory back. xterm
// keeps about 12 bytes per cell of scrollback (5,000 lines x 120 columns is about 8.5 MB a terminal), while the same
// screen written out as text and escapes is about 1 byte per cell. So a parked terminal keeps only that text (the
// serialize add-on's snapshot), its xterm is disposed, and a new one is made from the snapshot the moment it is
// shown again or its program prints. Its session, its program, its flow-control credit and its row stay as they were.
//
// Prior art: Orca parks a hidden pane (serializes it, drops it, restores it from the snapshot when shown) 30 s after
// it is hidden; herdr compresses a pane's idle scrollback after 250 ms without output. omher waits longer than either
// (a person flipping between a few sessions never waits for a restore) and only for terminals nobody looks at.
//
// What the snapshot cannot carry, a terminal in that state is not parked and stays as it is (see `cannotPark`).
import type { IModes, Terminal } from "@xterm/xterm";

/** Off the page at least this long ... */
export const PARK_HIDDEN_MS = 2 * 60_000;
/** ... and nothing printed for at least this long. */
export const PARK_IDLE_MS = 60_000;
/** One timer for every terminal looks this often, and only while some terminal is off the page. */
export const PARK_SWEEP_MS = 15_000;

/** The thresholds in use. Only a dev build's e2e hook changes them (engine.ts); a release build never does. */
export const limits = { hiddenMs: PARK_HIDDEN_MS, idleMs: PARK_IDLE_MS, sweepMs: PARK_SWEEP_MS };

/** Whether a terminal is due to be parked, by its times (ms). `hiddenAt` is null while it is on the page. */
export function dueToPark(f: { hiddenAt: number | null; lastOut: number; now: number }): boolean {
  return f.hiddenAt !== null && f.now - f.hiddenAt >= limits.hiddenMs && f.now - f.lastOut >= limits.idleMs;
}

/** The parts of a terminal's state the snapshot has to reproduce or that rule a snapshot out. */
export interface Inner {
  modes: IModes;
  /** a selection would be lost */
  selection: boolean;
  /** the active buffer's scroll region (DECSTBM) */
  scrollTop: number;
  scrollBottom: number;
  rows: number;
  /** DECTCEM: the program hid the cursor */
  cursorHidden: boolean;
  /** DECSCUSR as the program set it (undefined: the setting's own) */
  cursorStyle: "block" | "underline" | "bar" | undefined;
  cursorBlink: boolean | undefined;
  /** G0-G3 designations and the level in use */
  glevel: number;
  charsets: number;
  /** the parser is between escape sequences and no multi-byte character is half read */
  ground: boolean;
}

/** Why a terminal in this state cannot be parked, or null when it can. */
export function cannotPark(i: Inner): string | null {
  if (i.selection) return "selection";
  if (i.modes.mouseTrackingMode !== "none") return "mouse tracking"; // the snapshot keeps the protocol, not its encoding
  if (i.modes.originMode) return "origin mode"; // restoring it moves the cursor home
  if (i.modes.synchronizedOutputMode) return "synchronized output"; // a frame is half drawn
  if (i.scrollTop !== 0 || i.scrollBottom !== i.rows - 1) return "scroll region";
  if (i.glevel !== 0 || i.charsets !== 0) return "charset";
  if (!i.ground) return "mid sequence";
  return null;
}

/** What goes after the add-on's snapshot: the cursor's visibility and shape, which the add-on leaves out. */
export function extras(i: Pick<Inner, "cursorHidden" | "cursorStyle" | "cursorBlink">): string {
  let s = "";
  if (i.cursorStyle) {
    const base = { block: 1, underline: 3, bar: 5 }[i.cursorStyle];
    s += `\x1b[${base + (i.cursorBlink ? 0 : 1)} q`;
  }
  if (i.cursorHidden) s += "\x1b[?25l";
  return s;
}

/** One buffer's state the add-on's snapshot leaves out: the saved cursor (DECSC: its place, colours and charset) and
 *  the tab stops. The saved row is kept from the top of the screen, as DECRC reads it. */
interface BufferExtra {
  savedX: number;
  savedRow: number;
  savedFg: number;
  savedBg: number;
  savedCharset: unknown;
  tabs: number[];
}

/** The Kitty keyboard protocol's state (xterm 6.1 `coreService.kittyKeyboard`): the flags in force, each screen's
 *  flags while the other is shown, and each screen's stack of pushed flags (`CSI > flags u`), so a program that
 *  pushed modes inside each other pops back to the outer one (`CSI < u`) after its terminal was parked. */
export interface KittyState {
  flags: number;
  mainFlags: number;
  altFlags: number;
  mainStack: number[];
  altStack: number[];
}

/** What the engine carries beside the snapshot and puts back once the new terminal has read it: each buffer's
 *  saved cursor and tab stops, how far the person had scrolled up from the bottom, and the Kitty keyboard state
 *  (null when this xterm has none). */
export interface Carried {
  normal: BufferExtra;
  alt: BufferExtra;
  /** rows between the viewport's top and the bottom screen's top (0: at the bottom) */
  scrolledUp: number;
  kitty: KittyState | null;
}

type RawKitty = { flags?: unknown; mainFlags?: unknown; altFlags?: unknown; mainStack?: unknown; altStack?: unknown };
const kittyOf = (term: Terminal) => (term as unknown as { _core?: { coreService?: { kittyKeyboard?: RawKitty } } })._core?.coreService?.kittyKeyboard;
const nums = (v: unknown): v is number[] => Array.isArray(v) && v.every((n) => typeof n === "number");

function readKitty(term: Terminal): KittyState | null {
  const k = kittyOf(term);
  if (!k || typeof k.flags !== "number" || typeof k.mainFlags !== "number" || typeof k.altFlags !== "number") return null;
  if (!nums(k.mainStack) || !nums(k.altStack)) return null;
  return { flags: k.flags, mainFlags: k.mainFlags, altFlags: k.altFlags, mainStack: [...k.mainStack], altStack: [...k.altStack] };
}

function writeKitty(term: Terminal, c: KittyState): void {
  const k = kittyOf(term);
  if (!k || !nums(k.mainStack) || !nums(k.altStack)) return;
  k.flags = c.flags;
  k.mainFlags = c.mainFlags;
  k.altFlags = c.altFlags;
  k.mainStack = [...c.mainStack];
  k.altStack = [...c.altStack];
}

type RawBuffer = {
  x?: unknown;
  savedX?: unknown;
  savedY?: unknown;
  ybase?: unknown;
  ydisp?: unknown;
  savedCurAttrData?: { fg?: unknown; bg?: unknown };
  savedCharset?: unknown;
  tabs?: unknown;
};
const buffersOf = (term: Terminal) =>
  (term as unknown as { _core?: { buffers?: { normal?: RawBuffer; alt?: RawBuffer; active?: RawBuffer } } })._core?.buffers;

function readBuffer(b: RawBuffer | undefined): BufferExtra | null {
  const a = b?.savedCurAttrData;
  if (!b || !a || typeof b.savedX !== "number" || typeof b.savedY !== "number" || typeof b.ybase !== "number") return null;
  if (typeof a.fg !== "number" || typeof a.bg !== "number" || !b.tabs || typeof b.tabs !== "object") return null;
  const tabs = Object.keys(b.tabs as object)
    .filter((k) => (b.tabs as Record<string, unknown>)[k])
    .map(Number);
  return { savedX: b.savedX, savedRow: b.savedY - b.ybase, savedFg: a.fg, savedBg: a.bg, savedCharset: b.savedCharset, tabs };
}

/** The state to carry, or null when xterm's shape is not the one this knows (then the terminal is not parked). */
export function carriedOf(term: Terminal): Carried | null {
  const bs = buffersOf(term);
  const normal = readBuffer(bs?.normal);
  const alt = readBuffer(bs?.alt);
  const act = bs?.active;
  if (!normal || !alt || !act || typeof act.ybase !== "number" || typeof act.ydisp !== "number") return null;
  return { normal, alt, scrolledUp: act.ybase - act.ydisp, kitty: readKitty(term) };
}

function writeBuffer(b: RawBuffer | undefined, e: BufferExtra): void {
  if (!b || typeof b.ybase !== "number" || !b.savedCurAttrData) return;
  b.savedX = e.savedX;
  b.savedY = b.ybase + e.savedRow;
  b.savedCurAttrData.fg = e.savedFg;
  b.savedCurAttrData.bg = e.savedBg;
  b.savedCharset = e.savedCharset;
  const tabs: Record<number, boolean> = {};
  for (const t of e.tabs) tabs[t] = true;
  b.tabs = tabs;
}

/** Put the carried state into the terminal made from the snapshot, after it has read the snapshot. */
export function putCarried(term: Terminal, c: Carried): void {
  const bs = buffersOf(term);
  writeBuffer(bs?.normal, c.normal);
  writeBuffer(bs?.alt, c.alt);
  // after the snapshot: its switch to the alternate screen (when one was shown) moved the flags already
  if (c.kitty) writeKitty(term, c.kitty);
  if (c.scrolledUp > 0) {
    try {
      term.scrollLines(-c.scrolledUp);
    } catch {
      /* not scrollable */
    }
  }
}

/** The internals of xterm 6 `Inner` reads, after checking they are there; null for any other shape (then nothing is
 *  parked). park.test.ts fails when an xterm bump removes one of them. */
type Core = {
  coreService?: { isCursorHidden?: unknown; decPrivateModes?: { cursorStyle?: unknown; cursorBlink?: unknown } };
  buffer?: { scrollTop?: unknown; scrollBottom?: unknown };
  _charsetService?: { glevel?: unknown; _charsets?: unknown };
  _inputHandler?: {
    _parser?: { currentState?: unknown; initialState?: unknown };
    _utf8Decoder?: { interim?: unknown };
    _stringDecoder?: { _interim?: unknown };
  };
};

export function innerOf(term: Terminal): Inner | null {
  const core = (term as unknown as { _core?: Core })._core;
  const cs = core?.coreService;
  const dec = cs?.decPrivateModes;
  const buf = core?.buffer;
  const ch = core?._charsetService;
  const ih = core?._inputHandler;
  if (!cs || !dec || !buf || !ch || !ih?._parser || !ih._utf8Decoder || !ih._stringDecoder) return null;
  if (typeof cs.isCursorHidden !== "boolean" || typeof buf.scrollTop !== "number" || typeof buf.scrollBottom !== "number") return null;
  if (typeof ch.glevel !== "number" || !Array.isArray(ch._charsets)) return null;
  const { currentState, initialState } = ih._parser;
  const interim = ih._utf8Decoder.interim;
  if (typeof currentState !== "number" || typeof initialState !== "number" || !(interim instanceof Uint8Array) || typeof ih._stringDecoder._interim !== "number") return null;
  const style = dec.cursorStyle;
  return {
    modes: term.modes,
    selection: term.hasSelection(),
    scrollTop: buf.scrollTop,
    scrollBottom: buf.scrollBottom,
    rows: term.rows,
    cursorHidden: cs.isCursorHidden,
    cursorStyle: style === "block" || style === "underline" || style === "bar" ? style : undefined,
    cursorBlink: typeof dec.cursorBlink === "boolean" ? dec.cursorBlink : undefined,
    glevel: ch.glevel,
    charsets: (ch._charsets as unknown[]).filter((c) => c !== undefined).length,
    ground: currentState === initialState && interim.every((b) => b === 0) && ih._stringDecoder._interim === 0,
  };
}
