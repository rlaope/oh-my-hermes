// engine-find.ts: the xterm 6.1 decoration-removal fix, on a real xterm. Several decorations disposed in one go, a
// middle one first (as find drops the active match's fill, then the add-on the others) must all leave xterm's line
// index; without the fix one of them stays and its fill stays drawn.
import { Terminal } from "@xterm/xterm";
import { describe, expect, it } from "vitest";
import { FIND_PLAIN, findQuery, makeFinder, settleDecorationRemovals, validPattern, type FindResults } from "./engine-find";

const write = (t: Terminal, d: string) => new Promise<void>((r) => t.write(d, r));
type DS = { getDecorationsAtCell(x: number, line: number): Iterable<unknown> };
const at = (t: Terminal, line: number) => [...((t as unknown as { _core: { _decorationService: DS } })._core._decorationService.getDecorationsAtCell(1, line))].length;

async function fills(settled: boolean): Promise<number[]> {
  const t = new Terminal({ cols: 20, rows: 8, allowProposedApi: true });
  if (settled) expect(settleDecorationRemovals(t)).toBe(true);
  await write(t, "\r\none needle\r\ntwo needle\r\nthree needle\r\n");
  const buf = t.buffer.active;
  const made: { m: { dispose(): void }; d: { dispose(): void } }[] = [];
  for (const line of [1, 2, 3]) {
    const m = t.registerMarker(line - buf.baseY - buf.cursorY);
    const d = t.registerDecoration({ marker: m, x: 0, width: 6, backgroundColor: "#ff0000" })!;
    d.onDispose(() => m.dispose()); // as the add-on ties them: the decoration goes, then its marker
    made.push({ m, d });
  }
  // xterm sorts what was registered on its next read
  expect([1, 2, 3].map((l) => at(t, l))).toEqual([1, 1, 1]);
  // the middle one first (the active match's fill, dropped before the others), then the rest: its key turns -1
  // while it still sits mid-list, so the list is no longer sorted for the next removal
  for (const i of [1, 0, 2]) made[i].d.dispose();
  const left = [1, 2, 3].map((l) => at(t, l));
  t.dispose();
  return left;
}

describe("settleDecorationRemovals", () => {
  it("a decoration whose marker went first (its line already -1) still leaves the screen", async () => {
    for (const settled of [true, false]) {
      const t = new Terminal({ cols: 20, rows: 8, allowProposedApi: true });
      if (settled) settleDecorationRemovals(t);
      await write(t, "\r\none needle\r\ntwo needle\r\n");
      const buf = t.buffer.active;
      const m = t.registerMarker(1 - buf.baseY - buf.cursorY);
      t.registerDecoration({ marker: m, x: 0, width: 6, backgroundColor: "#ff0000" });
      const other = t.registerMarker(2 - buf.baseY - buf.cursorY);
      t.registerDecoration({ marker: other, x: 0, width: 6, backgroundColor: "#ff0000" });
      expect([at(t, 1), at(t, 2)]).toEqual([1, 1]);
      m.dispose(); // its decoration goes with it
      expect(at(t, 1), settled ? "fixed" : "xterm alone").toBe(settled ? 0 : at(t, 1));
      t.dispose();
    }
  });
  it("every decoration disposed in one go leaves the screen", async () => {
    expect(await fills(true)).toEqual([0, 0, 0]);
  });
  it("without it, xterm 6.1 keeps one (the fix is still needed; drop it once this fails)", async () => {
    expect((await fills(false)).some((n) => n > 0)).toBe(true);
  });
  it("is applied once, and leaves a terminal of another shape alone", () => {
    const t = new Terminal({ cols: 10, rows: 2, allowProposedApi: true });
    expect(settleDecorationRemovals(t)).toBe(true);
    expect(settleDecorationRemovals(t)).toBe(true);
    t.dispose();
    expect(settleDecorationRemovals({} as Terminal)).toBe(false);
  });
});

// Find over text in either Unicode form: macOS hands `ls` file names decomposed (NFD), a person types them composed
// (NFC). The fixture lines are built with String.normalize so this file holds no decomposed text of its own.
const NFC = "보고서.pdf";
const NFD = NFC.normalize("NFD");
const WORD = "보고서";

describe("findQuery", () => {
  it("leaves a text with nothing to compose, and a regular expression, as typed", () => {
    expect(findQuery("needle", FIND_PLAIN)).toEqual({ text: "needle", options: FIND_PLAIN });
    const re = { caseSensitive: false, regex: true };
    expect(findQuery("보고.*", re)).toEqual({ text: "보고.*", options: re });
  });

  it("turns a text with Hangul into one pattern that takes either form of each syllable, and escapes the rest", () => {
    for (const typed of [NFC, NFD]) {
      const q = findQuery(typed, FIND_PLAIN);
      expect(q.options).toEqual({ caseSensitive: false, regex: true });
      expect(validPattern(q.text)).toBe(true);
      const re = RegExp(q.text, "g");
      expect(`${NFD} ${NFC} 보고서xpdf`.match(re)).toEqual([NFD, NFC]);
    }
    expect(findQuery("é", { caseSensitive: true, regex: false }).options.caseSensitive).toBe(true);
  });
});

/** A real xterm with the real search add-on, outside a page: xterm can only select in an open terminal, so the
 *  selection is recorded here (it is where the add-on puts each match it moves to). */
async function findIn(lines: string[]) {
  const t = new Terminal({ cols: 40, rows: 10, allowProposedApi: true });
  const picked: [number, number, number][] = [];
  let sel: { start: { x: number; y: number }; end: { x: number; y: number } } | undefined;
  Object.assign(t, {
    select: (x: number, y: number, n: number) => {
      picked.push([x, y, n]);
      sel = { start: { x, y }, end: { x: x + n, y } };
    },
    getSelectionPosition: () => sel,
    clearSelection: () => (sel = undefined),
    scrollLines: () => undefined,
    scrollToLine: () => undefined,
  });
  await write(t, lines.join("\r\n") + "\r\n");
  const finder = makeFinder(t);
  const results: FindResults[] = [];
  finder.onResults((r) => results.push(r));
  const step = async (text: string, dir: "next" | "previous", incremental = false, options = FIND_PLAIN) => {
    const before = results.length;
    finder.search(text, dir, incremental, options);
    await expect.poll(() => results.length > before).toBe(true);
    return { at: picked[picked.length - 1], result: results[results.length - 1] };
  };
  return { t, finder, step };
}

describe("find matches either Unicode form", () => {
  it("finds the composed and the decomposed spelling in one buffer, each once, in order, over its own cells", async () => {
    const { t, finder, step } = await findIn([NFD, NFC, `x ${NFD} ${NFC}`, "보고 only", "nothing"]);
    for (const typed of [WORD, WORD.normalize("NFD")]) {
      const first = await step(typed, "next", true);
      expect(first.result.count).toBe(4);
      // `보고서` is three wide cells (six columns), however it is spelled; the third line's matches start after `x ` and
      // after the first match and a space
      const order = [first.at];
      for (let i = 0; i < 4; i++) order.push((await step(typed, "next")).at);
      expect(order).toEqual([
        [0, 0, 6],
        [0, 1, 6],
        [2, 2, 6],
        [13, 2, 6],
        [0, 0, 6],
      ]);
      expect((await step(typed, "previous")).at).toEqual([13, 2, 6]);
      finder.clear();
    }
    finder.dispose();
    t.dispose();
  });

  it("an accented Latin letter in either form, case ignored unless Match case is on", async () => {
    const { t, finder, step } = await findIn([`${"Café".normalize("NFD")} au lait`, "café crème"]);
    expect((await step("CAFÉ", "next", true)).result.count).toBe(2);
    expect((await step("Café".normalize("NFD"), "next", true)).result.count).toBe(2);
    expect((await step("CAFÉ", "next", true, { caseSensitive: true, regex: false })).result.count).toBe(0);
    expect((await step("Café", "next", true, { caseSensitive: true, regex: false })).result.count).toBe(1);
    finder.dispose();
    t.dispose();
  });
});
