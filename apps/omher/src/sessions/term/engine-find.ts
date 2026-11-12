// Find in one terminal: the search add-on (loaded the first time somebody searches, never with the app) behind a
// small controller the find bar drives. Matches are highlighted in the scrollback with colours from the terminal's
// theme (find-colors.ts) and the count comes from the add-on's own result event.
import type { Terminal } from "@xterm/xterm";
import type { SearchAddon } from "@xterm/addon-search";
import { findColors } from "./find-colors";

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
        a.onDidChangeResults((e) => emit({ index: e.resultIndex, count: e.resultCount, capped: e.resultCount >= FIND_LIMIT }));
        return (addon = a);
      },
      () => null,
    ));

  const run = (text: string, direction: "next" | "previous", incremental: boolean) => {
    if (!text) {
      addon?.clearDecorations();
      term.clearSelection();
      emit({ index: -1, count: 0, capped: false });
      return;
    }
    void ready().then((a) => {
      if (!a || gone) return;
      const opts = { incremental, decorations: findColors(term.options.theme ?? {}) };
      const found = direction === "next" ? a.findNext(text, opts) : a.findPrevious(text, opts);
      // nothing matched: the add-on fires no event then
      if (!found) emit({ index: -1, count: 0, capped: false });
    });
  };

  return {
    search: run,
    clear() {
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
