// park.ts: when a terminal is due, what rules it out, and (on a real, unopened xterm 6) that the snapshot plus its
// extras makes a terminal equal to the one it came from. innerOf reads xterm internals; the round trips fail when an
// xterm bump moves one of them.
import { Terminal, type IBufferCell } from "@xterm/xterm";
import { SerializeAddon } from "@xterm/addon-serialize";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { describe, expect, it } from "vitest";
import { PARK_HIDDEN_MS, PARK_IDLE_MS, PARK_SWEEP_MS, cannotPark, carriedOf, dueToPark, extras, innerOf, putCarried, type Inner } from "./park";

const MIN = 60_000;

describe("dueToPark", () => {
  const now = 10 * MIN;
  it("needs both: off the page for 2 minutes and quiet for 60 s", () => {
    expect(PARK_HIDDEN_MS).toBe(2 * MIN);
    expect(PARK_IDLE_MS).toBe(MIN);
    expect(PARK_SWEEP_MS).toBe(15_000);
    expect(dueToPark({ hiddenAt: now - 2 * MIN, lastOut: now - MIN, now })).toBe(true);
    expect(dueToPark({ hiddenAt: now - 2 * MIN + 1, lastOut: now - 5 * MIN, now })).toBe(false);
    expect(dueToPark({ hiddenAt: now - 5 * MIN, lastOut: now - MIN + 1, now })).toBe(false);
  });
  it("never while on the page", () => {
    expect(dueToPark({ hiddenAt: null, lastOut: 0, now })).toBe(false);
  });
});

const base: Inner = {
  modes: {
    applicationCursorKeysMode: false,
    applicationKeypadMode: false,
    bracketedPasteMode: false,
    insertMode: false,
    mouseTrackingMode: "none",
    originMode: false,
    reverseWraparoundMode: false,
    sendFocusMode: false,
    synchronizedOutputMode: false,
    wraparoundMode: true,
  },
  selection: false,
  scrollTop: 0,
  scrollBottom: 23,
  rows: 24,
  cursorHidden: false,
  cursorStyle: undefined,
  cursorBlink: undefined,
  glevel: 0,
  charsets: 0,
  ground: true,
};

describe("cannotPark", () => {
  it("parks a plain terminal, and one in modes the snapshot restores", () => {
    expect(cannotPark(base)).toBeNull();
    expect(cannotPark({ ...base, modes: { ...base.modes, bracketedPasteMode: true, applicationCursorKeysMode: true, wraparoundMode: false } })).toBeNull();
  });
  it("skips what the snapshot cannot restore", () => {
    expect(cannotPark({ ...base, modes: { ...base.modes, mouseTrackingMode: "vt200" } })).toBe("mouse tracking");
    expect(cannotPark({ ...base, modes: { ...base.modes, originMode: true } })).toBe("origin mode");
    expect(cannotPark({ ...base, modes: { ...base.modes, synchronizedOutputMode: true } })).toBe("synchronized output");
    expect(cannotPark({ ...base, selection: true })).toBe("selection");
    expect(cannotPark({ ...base, scrollTop: 2 })).toBe("scroll region");
    expect(cannotPark({ ...base, scrollBottom: 20 })).toBe("scroll region");
    expect(cannotPark({ ...base, glevel: 1 })).toBe("charset");
    expect(cannotPark({ ...base, charsets: 1 })).toBe("charset");
    expect(cannotPark({ ...base, ground: false })).toBe("mid sequence");
  });
});

describe("extras", () => {
  it("the cursor's shape and visibility, which the add-on leaves out", () => {
    expect(extras(base)).toBe("");
    expect(extras({ ...base, cursorStyle: "bar", cursorBlink: true })).toBe("\x1b[5 q");
    expect(extras({ ...base, cursorStyle: "underline", cursorBlink: false })).toBe("\x1b[4 q");
    expect(extras({ ...base, cursorHidden: true })).toBe("\x1b[?25l");
  });
});

const write = (t: Terminal, d: string) => new Promise<void>((r) => t.write(d, r));
const make = () => {
  const t = new Terminal({ cols: 60, rows: 12, scrollback: 200, allowProposedApi: true });
  t.loadAddon(new Unicode11Addon());
  t.unicode.activeVersion = "11";
  return t;
};
/** a colour as xterm draws it: its renderers treat the 16- and 256-colour modes as one palette (`38;5;1` draws as
 *  `31`), and the add-on writes an index under 16 in the short form */
const mode = (m: number) => (m === 0x1000000 || m === 0x2000000 ? "palette" : m);
const cell = (c: IBufferCell) => [c.getChars(), c.getWidth(), mode(c.getFgColorMode()), c.getFgColor(), mode(c.getBgColorMode()), c.getBgColor(), c.isBold(), c.isInverse()];
function state(t: Terminal) {
  const b = t.buffer.active;
  const lines: string[] = [];
  const cells: unknown[] = [];
  for (let y = 0; y < b.length; y++) {
    const l = b.getLine(y)!;
    lines.push(l.translateToString(true));
    for (let x = 0; x < t.cols; x += 7) cells.push(cell(l.getCell(x)!));
  }
  return { type: b.type, lines, cells, cursor: [b.cursorX, b.cursorY, b.baseY], viewportY: b.viewportY, modes: t.modes };
}

/** What the engine does to park and make again, minus the page: snapshot + extras + title into a fresh terminal. */
async function roundTrip(bytes: string, more = "\x1b[1;31mnext\x1b[0m line\r\n$ ", scrollTo?: number) {
  const twin = make();
  const a = make();
  let title = "";
  a.onTitleChange((x) => (title = x));
  await write(twin, bytes);
  await write(a, bytes);
  if (scrollTo !== undefined) {
    twin.scrollToLine(scrollTo);
    a.scrollToLine(scrollTo);
  }
  const carried = carriedOf(a);
  expect(carried).not.toBeNull();
  const inner = innerOf(a);
  expect(inner).not.toBeNull();
  expect(cannotPark(inner!)).toBeNull();
  const ser = new SerializeAddon();
  a.loadAddon(ser);
  let snap = ser.serialize() + extras(inner!);
  if (title) snap += `\x1b]2;${title}\x07`;
  a.dispose();
  const b = make();
  let titleB = "";
  b.onTitleChange((x) => (titleB = x));
  await write(b, snap);
  putCarried(b, carried!);
  expect(state(b)).toEqual(state(twin));
  expect(titleB).toBe(title);
  expect(innerOf(b)).toEqual(innerOf(twin));
  // and the program's next bytes land the same in both
  await write(b, more);
  await write(twin, more);
  expect(state(b)).toEqual(state(twin));
}

describe("snapshot round trip (xterm 6 + addon-serialize 0.14)", () => {
  const plain = Array.from({ length: 40 }, (_, i) => `line ${i} of plain output`).join("\r\n");
  it("plain lines past one screen", () => roundTrip(plain));
  it("SGR colours: 16, 256, true colour, bold, inverse", () =>
    roundTrip(`\x1b[32mgreen\x1b[0m \x1b[1;38;5;208mbold orange\x1b[0m \x1b[38;5;3m256 low\x1b[0m \x1b[48;2;10;20;30mrgb bg\x1b[0m \x1b[7minv\x1b[0m\r\n`.repeat(15)));
  it("wide CJK and emoji", () => roundTrip("한글 漢字 テスト 😀👍 mixed ✅ text\r\n".repeat(20)));
  it("a TUI in the alternate screen with box drawing, a title and a hidden bar cursor", () =>
    roundTrip(
      plain +
        "\x1b]2;claude — repo\x07\x1b[?1049h\x1b[H\x1b[2J\x1b[?25l\x1b[5 q\x1b[?2004h\x1b[?1h" +
        "╭──────────────────────────╮\r\n│ \x1b[1m✻ Welcome\x1b[0m                │\r\n╰──────────────────────────╯\r\n\x1b[36m> \x1b[0mtype here",
    ));
  it("a line rewritten in place", () => roundTrip("before\r\n\x1b[33m⠋\x1b[0m Working (1s)\r\x1b[2K\x1b[33m⠙\x1b[0m Working (2s)\r\x1b[2K  ⎿ done\r\n$ "));

  // found by the run's independent verify: the add-on's snapshot leaves these out
  it("a saved cursor (DECSC) the program restores after the park", () =>
    roundTrip("\x1b[2J\x1b[H\x1b[3J\x1b[4;9H\x1b[33m\x1b7\x1b[0m\x1b[10;25Hhold", "\x1b8RESTORED"));
  it("custom tab stops", () => roundTrip("\x1b[2J\x1b[H\x1b[3J\x1b[3g\x1b[1;5H\x1bH\x1b[1;14H\x1bH\x1b[H", "\tX\tY"));
  it("where the person had scrolled to", () =>
    roundTrip(Array.from({ length: 150 }, (_, i) => `numbered ${i}`).join("\r\n"), "", 12));
  it("a saved cursor in the alternate screen", () =>
    roundTrip("\x1b[?1049h\x1b[H\x1b[2J\x1b[5;7H\x1b7\x1b[1;1Htop", "\x1b8alt"));

  it("innerOf sees a half-read sequence, a selection and a mouse mode", async () => {
    const t = make();
    await write(t, "abc\x1b[3");
    expect(cannotPark(innerOf(t)!)).toBe("mid sequence");
    await write(t, "1mred\x1b[?1000h");
    expect(cannotPark(innerOf(t)!)).toBe("mouse tracking");
    await write(t, "\x1b[?1000l");
    expect(cannotPark(innerOf(t)!)).toBeNull();
    await write(t, "\x1b[2;8r");
    expect(cannotPark(innerOf(t)!)).toBe("scroll region");
    await write(t, "\x1b[r\x1b(0");
    expect(cannotPark(innerOf(t)!)).toBe("charset");
  });

  it("innerOf is null for a terminal that is not xterm 6's shape", () => {
    expect(innerOf({ modes: base.modes } as unknown as Terminal)).toBeNull();
  });
});
