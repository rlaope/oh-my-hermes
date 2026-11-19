// engine-hidden.ts touches xterm internals: the fallback when they are missing, the hold-and-redraw-once when they
// are there, and a check of the installed xterm that fails when an xterm bump moves or renames what it relies on.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import type { Terminal } from "@xterm/xterm";
import { describe, expect, it } from "vitest";
import { hideRows, renderServiceOf, showRows } from "./engine-hidden";

type Sel = { start: unknown; end: unknown; columnSelectMode: boolean };

/** A terminal shaped like xterm 6's, whose render service records what reaches its renderer. */
function fakeTerm() {
  const drawn: Sel[] = [];
  const refreshed: [number, number][] = [];
  class RenderService {
    _selectionState: Sel = { start: undefined, end: undefined, columnSelectMode: false };
    _needsSelectionRefresh = false;
    handleSelectionChanged(start: unknown, end: unknown, columnSelectMode: boolean) {
      this._selectionState = { start, end, columnSelectMode };
      drawn.push({ start, end, columnSelectMode });
    }
  }
  const rs = new RenderService();
  const term = { rows: 24, _core: { _renderService: rs }, refresh: (a: number, b: number) => refreshed.push([a, b]) };
  return { term: term as unknown as Terminal, rs, drawn, refreshed };
}

describe("engine-hidden", () => {
  it("finds xterm 6's render service only when it has every member it needs", () => {
    expect(renderServiceOf(fakeTerm().term)).not.toBeNull();
    expect(renderServiceOf({} as Terminal)).toBeNull();
    expect(renderServiceOf({ _core: {} } as unknown as Terminal)).toBeNull();
    for (const drop of ["handleSelectionChanged", "_selectionState", "_needsSelectionRefresh"] as const) {
      const { term, rs } = fakeTerm();
      Object.defineProperty(rs, drop, { value: undefined });
      expect(renderServiceOf(term)).toBeNull();
    }
  });

  it("another xterm: nothing is changed and selection redraws go through as before", () => {
    const { term, rs, drawn } = fakeTerm();
    Object.defineProperty(rs, "_needsSelectionRefresh", { value: undefined });
    const before = rs.handleSelectionChanged;
    expect(hideRows(term)).toBe(false);
    expect(rs.handleSelectionChanged).toBe(before);
    rs.handleSelectionChanged([0, 0], [3, 0], false);
    expect(drawn).toHaveLength(1);
    showRows(term);
    expect(rs.handleSelectionChanged).toBe(before);
  });

  it("hidden: selection redraws keep the selection and draw nothing; shown: one refresh draws it", () => {
    const { term, rs, drawn, refreshed } = fakeTerm();
    const proto = Object.getPrototypeOf(rs).handleSelectionChanged;
    expect(hideRows(term)).toBe(true);
    expect(hideRows(term)).toBe(true); // a second hide changes nothing
    for (let i = 0; i < 50; i++) rs.handleSelectionChanged([0, i], [5, i], false);
    expect(drawn).toEqual([]);
    expect(rs._selectionState).toEqual({ start: [0, 49], end: [5, 49], columnSelectMode: false });
    showRows(term);
    // the prototype's member is back, and the next row render gives the renderer the selection, once
    expect(Object.prototype.hasOwnProperty.call(rs, "handleSelectionChanged")).toBe(false);
    expect(rs.handleSelectionChanged).toBe(proto);
    expect(rs._needsSelectionRefresh).toBe(true);
    expect(refreshed).toEqual([[0, 23]]);
    showRows(term); // a second show changes nothing
    expect(refreshed).toHaveLength(1);
    rs.handleSelectionChanged(undefined, undefined, false);
    expect(drawn).toHaveLength(1);
  });

  it("hidden and shown with no selection redraw meanwhile: no extra refresh", () => {
    const { term, rs, refreshed } = fakeTerm();
    hideRows(term);
    showRows(term);
    expect(refreshed).toEqual([]);
    expect(rs._needsSelectionRefresh).toBe(false);
  });

  // The installed xterm, read as shipped: these are the paths engine-hidden.ts sits on. When one is gone (an xterm
  // bump), this fails; read engine-hidden.ts again against the new xterm before changing the patterns.
  it("the installed @xterm/xterm still has the members and the paths engine-hidden.ts relies on", () => {
    const require = createRequire(import.meta.url);
    const src = readFileSync(require.resolve("@xterm/xterm/lib/xterm.mjs"), "utf8");
    const paths: [string, RegExp][] = [
      // output scrolling the buffer asks the selection service for a redraw
      ["scroll -> selection refresh", /this\._onScroll\.event,this\._inputHandler\.onScroll\)\(\(\)=>\{this\._selectionService\.refresh\(\)/],
      // which lands on the render service's handleSelectionChanged
      ["selection redraw -> RenderService.handleSelectionChanged", /this\._selectionService\.onRequestRedraw\((\w+)=>this\._renderService\.handleSelectionChanged\(\1\.start,\1\.end,\1\.columnSelectMode\)\)/],
      // which keeps the selection in _selectionState and hands it to the renderer, paused or not
      ["RenderService.handleSelectionChanged", /handleSelectionChanged\((\w+),(\w+),(\w+)\)\{this\._selectionState\.start=\1,this\._selectionState\.end=\2,this\._selectionState\.columnSelectMode=\3,this\._renderer\.value\?\.handleSelectionChanged\(\1,\2,\3\)\}/],
      // a row render with _needsSelectionRefresh set gives the renderer the kept selection
      ["_renderRows + _needsSelectionRefresh", /this\._needsSelectionRefresh&&\(this\._renderer\.value\.handleSelectionChanged\(this\._selectionState\.start,this\._selectionState\.end,this\._selectionState\.columnSelectMode\),this\._needsSelectionRefresh=!1\)/],
      // and the public refresh is held while xterm's own pause is on, then done in full when the terminal is seen
      // (xterm 6.1 added a defaulted `isRedrawOnly` after `sync`, and `refresh` passes `sync` through: same path)
      ["paused refreshRows", /refreshRows\(\w+,\w+(?:,\w+=!1)+\)\{if\(this\._isPaused\)\{this\._needsFullRefresh=!0;return\}/],
      ["Terminal.refresh -> refreshRows", /refresh\((\w+),(\w+)(?:,(\w+)=!1)?\)\{this\._renderService\?\.refreshRows\(\1,\2(?:,\3)?\)\}/],
    ];
    const missing = paths.filter(([, re]) => !re.test(src)).map(([name]) => name);
    expect(missing).toEqual([]);
  });
});
