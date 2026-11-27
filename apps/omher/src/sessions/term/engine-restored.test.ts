// engine-restored.ts wraps one xterm internal: the fallback when it is missing, which presses it turns into a
// selection (only on the restored lines of the main screen), and a check of the installed xterm that fails when an
// xterm bump moves or renames what it relies on (e2e/term-restore-select.spec.ts drives the real thing).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import type { Terminal } from "@xterm/xterm";
import { describe, expect, it } from "vitest";
import { markRestored, onRestored, restoredEnd, selectionServiceOf } from "./engine-restored";

/** A terminal shaped like xterm 6's: 10 rows of 20 px on a screen at top 100, scrolled to `viewportY`. */
function fakeTerm(o: { viewportY?: number; type?: "normal" | "alternate"; cursor?: number; modifier?: boolean } = {}) {
  const buffer = { viewportY: o.viewportY ?? 0, baseY: 0, cursorY: o.cursor ?? 4, type: o.type ?? "normal" };
  const ss = { shouldForceSelection: (e: MouseEvent) => !!o.modifier && e.shiftKey };
  const made = () => ({
    line: -1,
    isDisposed: false,
    dispose() {
      this.isDisposed = true;
    },
  });
  let marker = made();
  const screen = { getBoundingClientRect: () => ({ top: 100, bottom: 300, height: 200 }) };
  const term = {
    rows: 10,
    buffer: { active: buffer },
    element: { querySelector: (s: string) => (s === ".xterm-screen" ? screen : null) },
    _core: { _selectionService: ss },
    registerMarker(offset: number) {
      marker = made();
      marker.line = buffer.baseY + buffer.cursorY + offset;
      return marker;
    },
  };
  return { term: term as unknown as Terminal, ss, buffer, marker: () => marker };
}
const at = (row: number, shift = false) => ({ clientY: 100 + row * 20 + 10, shiftKey: shift }) as MouseEvent;

describe("engine-restored", () => {
  it("another xterm: nothing is marked and nothing is wrapped", () => {
    expect(selectionServiceOf({} as Terminal)).toBeNull();
    expect(selectionServiceOf({ _core: { _selectionService: {} } } as unknown as Terminal)).toBeNull();
    expect(markRestored({ _core: {} } as unknown as Terminal)).toBe(false);
  });

  it("a press on the restored lines (the divider's and above) forces a selection; one below it is the program's", () => {
    const { term, ss } = fakeTerm({ cursor: 4 });
    expect(ss.shouldForceSelection(at(2))).toBe(false);
    expect(markRestored(term)).toBe(true);
    expect(restoredEnd(term)).toBe(4);
    for (const row of [0, 2, 4]) expect(ss.shouldForceSelection(at(row)), `row ${row}`).toBe(true);
    for (const row of [5, 9]) expect(ss.shouldForceSelection(at(row)), `row ${row}`).toBe(false);
    // outside the rows
    expect(ss.shouldForceSelection({ clientY: 50, shiftKey: false } as MouseEvent)).toBe(false);
  });

  it("the line follows the scroll position, and xterm's own modifier still forces a selection anywhere", () => {
    const { term, ss, buffer } = fakeTerm({ cursor: 4, modifier: true });
    markRestored(term);
    buffer.viewportY = 3; // scrolled down three lines: row 1 is buffer line 4
    expect(ss.shouldForceSelection(at(1))).toBe(true);
    expect(ss.shouldForceSelection(at(2))).toBe(false);
    expect(ss.shouldForceSelection(at(2, true))).toBe(true);
  });

  it("the alternate screen, a trimmed divider or a parked terminal's line", () => {
    const alt = fakeTerm({ type: "alternate" });
    markRestored(alt.term);
    expect(onRestored(alt.term, at(0))).toBe(false);
    const trimmed = fakeTerm();
    markRestored(trimmed.term);
    trimmed.marker().line = -1;
    expect(restoredEnd(trimmed.term)).toBe(-1);
    expect(trimmed.ss.shouldForceSelection(at(0))).toBe(false);
    // made again from a snapshot: the line it had is marked, not the cursor's
    const remade = fakeTerm({ cursor: 8 });
    markRestored(remade.term, 2);
    expect(restoredEnd(remade.term)).toBe(2);
    expect(remade.ss.shouldForceSelection(at(3))).toBe(false);
  });

  it("marking again wraps once and moves the line", () => {
    const { term, ss, buffer } = fakeTerm({ cursor: 2 });
    markRestored(term);
    const wrapped = ss.shouldForceSelection;
    buffer.cursorY = 6;
    markRestored(term);
    expect(ss.shouldForceSelection).toBe(wrapped);
    expect(restoredEnd(term)).toBe(6);
  });

  // The installed xterm, read as shipped: both the mouse service (which holds a press back from the program) and the
  // selection service (which starts a selection while mouse reporting is on) ask shouldForceSelection.
  it("the installed @xterm/xterm still asks shouldForceSelection where engine-restored.ts relies on it", () => {
    const require = createRequire(import.meta.url);
    const src = readFileSync(require.resolve("@xterm/xterm/lib/xterm.mjs"), "utf8");
    expect(src).toMatch(/!this\._mouseStateService\.areMouseEventsActive\|\|this\._selectionService\.shouldForceSelection\(\w+\)\)return;this\._sendEvent\(/);
    expect(src).toMatch(/if\(!this\._enabled\)\{if\(!this\.shouldForceSelection\(\w+\)\)return;\w+\.stopPropagation\(\)\}/);
    expect(src).toMatch(/shouldForceSelection\(\w+\)\{return /);
  });
});
