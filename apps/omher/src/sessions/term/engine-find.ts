// Find in one terminal: the search add-on (loaded the first time somebody searches, never with the app) behind a
// small controller the find bar drives. Matches are highlighted in the scrollback with colours from the terminal's
// theme (find-colors.ts) and the count comes from the add-on's own result event.
//
// The add-on marks the active match by selecting it, and xterm paints a selection over a decoration's fill: left to
// itself the active match shows the theme's selection colour (on most themes close to the background) inside an
// outline, weaker than the filled matches around it. So the active match gets one more decoration here, on the top
// layer, which xterm paints above the selection: the fill find-colors.ts picked for it, the text colour that reads
// on that fill (a decoration's fill leaves the cell's own colour, and a program's yellow can be the fill's colour),
// and a heavier outline.
//
// The colours are the theme's, so a terminal whose theme changes while find is open (the app follows the system
// from light to dark) is told to take them again: `restyle()`, which look.ts calls with the new look.
//
// The selection is find's only while it is the active match. A person can click in the terminal or select other
// text with find open; that selection (or none) is theirs, and neither a restyle nor closing find takes it.
import type { IBufferRange, IDecoration, IDisposable, IMarker, Terminal } from "@xterm/xterm";
import type { SearchAddon } from "@xterm/addon-search";
import { findColors, type FindColors } from "./find-colors";

/** The terminal's element sends this (bubbling) when the person asks for find; the find bar above it listens. */
export const FIND_EVENT = "omher-term-find";
export interface FindRequest {
  term: Terminal;
  finder: Finder;
}

/** The add-on stops counting here; the bar then says "more than". */
export const FIND_LIMIT = 2000;

export interface FindResults {
  /** 0-based position of the active match, -1 when none is active */
  index: number;
  count: number;
  /** the add-on stopped counting at its limit */
  capped: boolean;
}

export interface Finder {
  /** Look for `text`: from the current spot for typing (`incremental`), or one match on for Enter / Shift+Enter. */
  search(text: string, direction: "next" | "previous", incremental?: boolean): void;
  /** Drop the highlights and the selection that find made. */
  clear(): void;
  /** The terminal's theme may have changed: the matches and the active one take its colours, where they are. */
  restyle(): void;
  onResults(fn: (r: FindResults) => void): () => void;
  dispose(): void;
}

let searchLoad: Promise<typeof SearchAddon> | null = null;
const loadSearch = () =>
  (searchLoad ??= import("@xterm/addon-search").then(
    (m) => m.SearchAddon,
    (e) => {
      searchLoad = null;
      throw e;
    },
  ));

const finders = new WeakMap<Terminal, Finder>();
/** The finder of a terminal that has one (a session's terminal; the Settings preview has none). */
export const finderOf = (term: Terminal): Finder | undefined => finders.get(term);

const sameColors = (a: FindColors, b: FindColors) => (Object.keys(a) as (keyof FindColors)[]).every((k) => a[k] === b[k]);

export function makeFinder(term: Terminal): Finder {
  let addon: SearchAddon | null = null;
  let loading: Promise<SearchAddon | null> | null = null;
  let gone = false;
  let last: FindResults = { index: -1, count: 0, capped: false };
  const listeners = new Set<(r: FindResults) => void>();
  const emit = (r: FindResults) => {
    last = r;
    for (const fn of listeners) fn(r);
  };
  /** The top-layer fill of the active match (one decoration per row it spans). */
  let active: IDisposable[] = [];
  /** Where the active match is: its first cell (the marker follows the row as output scrolls) and its length in
   *  cells, as `term.select` takes them. */
  let match: { row: IMarker; x: number; length: number } | null = null;
  const unmark = () => {
    for (const d of active) d.dispose();
    active = [];
    match = null;
  };
  /** A selection's length in cells, rows wrapping at the terminal's width. */
  const cells = (r: IBufferRange) => (r.end.y - r.start.y) * term.cols + r.end.x - r.start.x;
  /** The active match as it stands now; null when there is none or its row has left the scrollback. */
  const matchNow = () => (match && match.row.line >= 0 ? { x: match.x, y: match.row.line, length: match.length } : null);
  /** The terminal's selection is the active match, so it is find's own and not one the person made. */
  const selectionIsFinds = () => {
    const m = matchNow();
    const sel = term.getSelectionPosition();
    return !!m && !!sel && sel.start.x === m.x && sel.start.y === m.y && cells(sel) === m.length;
  };
  /** Fill and outline the active match, which is what the add-on has just selected. */
  const mark = (c: FindColors) => {
    unmark();
    const sel = term.getSelectionPosition();
    if (!sel) return;
    const buf = term.buffer.active;
    const row = term.registerMarker(sel.start.y - buf.baseY - buf.cursorY);
    active.push(row);
    match = { row, x: sel.start.x, length: cells(sel) };
    for (let y = sel.start.y; y <= sel.end.y; y++) {
      const x = y === sel.start.y ? sel.start.x : 0;
      const width = (y === sel.end.y ? sel.end.x : term.cols) - x;
      if (width <= 0) continue;
      let d: IDecoration | undefined;
      const marker = term.registerMarker(y - buf.baseY - buf.cursorY);
      try {
        d = term.registerDecoration({ marker, x, width, backgroundColor: c.activeMatchBackground, foregroundColor: c.activeMatchForeground, layer: "top" });
      } catch {
        /* proposed API off: the add-on's own outline is all the active match gets */
      }
      active.push(marker);
      if (!d) continue;
      active.push(d);
      active.push(
        d.onRender((el) => {
          el.classList.add("tfind-active");
          el.style.outline = `2px solid ${c.activeMatchBorder}`;
          // half of it inside the cell, so it does not sit on the letters either side of the match
          el.style.outlineOffset = "-1px";
        }),
      );
    }
  };
  /** The colours in use, so a result the add-on finds again by itself (new output, a resize) is marked the same. */
  let colors: FindColors | null = null;
  /** What is being looked for ("" when nothing is). */
  let wanted = "";

  const ready = (): Promise<SearchAddon | null> =>
    (loading ??= loadSearch().then(
      (Ctor) => {
        if (gone) return null;
        const a = new Ctor({ highlightLimit: FIND_LIMIT });
        try {
          term.loadAddon(a);
        } catch {
          return null;
        }
        a.onDidChangeResults((e) => {
          if (e.resultIndex >= 0 && colors) mark(colors);
          else unmark();
          emit({ index: e.resultIndex, count: e.resultCount, capped: e.resultCount >= FIND_LIMIT });
        });
        return (addon = a);
      },
      () => null,
    ));

  const run = (text: string, direction: "next" | "previous", incremental: boolean) => {
    wanted = text;
    if (!text) {
      const own = selectionIsFinds();
      unmark();
      addon?.clearDecorations();
      if (own) term.clearSelection();
      emit({ index: -1, count: 0, capped: false });
      return;
    }
    void ready().then((a) => {
      // closed, or looking for something else by now (the add-on's chunk loads on the first search)
      if (!a || gone || wanted !== text) return;
      colors = findColors(term.options.theme ?? {});
      const opts = { incremental, decorations: colors };
      const found = direction === "next" ? a.findNext(text, opts) : a.findPrevious(text, opts);
      // nothing matched: the add-on fires no event then
      if (!found) {
        unmark();
        emit({ index: -1, count: 0, capped: false });
      }
    });
  };

  const finder: Finder = {
    search: run,
    clear() {
      wanted = "";
      // the bar can outlive its terminal by a moment (a session that ended while find was open)
      if (gone) return;
      const own = selectionIsFinds();
      unmark();
      addon?.clearDecorations();
      if (own) term.clearSelection();
      emit({ index: -1, count: 0, capped: false });
    },
    restyle() {
      const a = addon;
      if (!a || gone || !wanted || !colors) return;
      const next = findColors(term.options.theme ?? {});
      // a font size or a padding is a new look too, and no new colour
      if (sameColors(next, colors)) return;
      colors = next;
      // the add-on keeps the fills of a text it has searched: drop them, then find the same match again. It
      // searches from the selection, so the active match is selected first (a click or the person's own selection
      // may have replaced find's), and what the person had selected, or nothing, is put back afterwards. A person
      // who scrolled away from the match stays where they are.
      const at = term.buffer.active.viewportY;
      const own = selectionIsFinds();
      const theirs = own ? undefined : term.getSelectionPosition();
      const m = matchNow();
      a.clearDecorations();
      if (m) term.select(m.x, m.y, m.length);
      if (!a.findNext(wanted, { incremental: true, decorations: colors })) {
        unmark();
        emit({ index: -1, count: 0, capped: false });
      }
      if (!own) {
        if (theirs) term.select(theirs.start.x, theirs.start.y, cells(theirs));
        else term.clearSelection();
      }
      if (term.buffer.active.viewportY !== at) term.scrollToLine(at);
    },
    onResults(fn) {
      listeners.add(fn);
      fn(last);
      return () => void listeners.delete(fn);
    },
    dispose() {
      gone = true;
      finders.delete(term);
      unmark();
      listeners.clear();
      try {
        addon?.dispose();
      } catch {
        /* already gone with the terminal */
      }
      addon = null;
    },
  };
  finders.set(term, finder);
  return finder;
}
