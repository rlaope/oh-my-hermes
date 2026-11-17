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
