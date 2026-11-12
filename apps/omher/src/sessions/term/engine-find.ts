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
import type { IDecoration, IDisposable, Terminal } from "@xterm/xterm";
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
  const unmark = () => {
    for (const d of active) d.dispose();
    active = [];
  };
  /** Fill and outline the active match, which is what the add-on has just selected. */
  const mark = (c: FindColors) => {
    unmark();
    const sel = term.getSelectionPosition();
    if (!sel) return;
    const buf = term.buffer.active;
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
    if (!text) {
      unmark();
      addon?.clearDecorations();
      term.clearSelection();
      emit({ index: -1, count: 0, capped: false });
      return;
    }
    void ready().then((a) => {
      if (!a || gone) return;
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

  return {
    search: run,
    clear() {
      unmark();
      addon?.clearDecorations();
      term.clearSelection();
      emit({ index: -1, count: 0, capped: false });
    },
    onResults(fn) {
      listeners.add(fn);
      fn(last);
      return () => void listeners.delete(fn);
    },
    dispose() {
      gone = true;
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
}
