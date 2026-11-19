// engine-find.ts: the xterm 6.1 decoration-removal fix, on a real xterm. Several decorations disposed in one go, a
// middle one first (as find drops the active match's fill, then the add-on the others) must all leave xterm's line
// index; without the fix one of them stays and its fill stays drawn.
import { Terminal } from "@xterm/xterm";
import { describe, expect, it } from "vitest";
import { settleDecorationRemovals } from "./engine-find";

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
