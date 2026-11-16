// A sidebar list that scrolls on its own (BOTS, TERMINALS) marks an edge that has more rows past it. `data-more` on the
// list: "below", "above", "both" or nothing; the cue itself is CSS (sessions.css). At the bottom edge no row is ever
// shown cut: the row the region's end would cut (and any row in the cue's band) is hidden whole by a clip on the list,
// so the "more below" chevron sits on empty sidebar, never on half a face or a preview line. The clip is paint only:
// the list keeps its size, so nothing below it moves. Use the returned callback as the list's `ref` (the list can
// mount after its section, as TERMINALS does with its first session).
import { useCallback, useRef } from "react";

/** The rows that are shown whole or not at all: a bot's own row, a thread row, a folder header, a terminal row. */
export const CUT_ROWS = ".bot-w > .bot, .th-row, .tg-h, .ss-row, .bot-list > :not(.bot-w):not(.tg)";
/** The band kept free at a cut bottom edge for the chevron (sessions.css draws it there). */
export const CUE_PX = 14;

/** How many px to hide at the bottom of a list whose box ends at `bottom`: from the top of the first row that would
 *  reach into the cue band, at least the band itself. `rows`: the rows' tops and bottoms. */
export function cutBelow(bottom: number, rows: readonly { top: number; bottom: number; head?: boolean }[], band = CUE_PX): number {
  // hiding a row from its top can reach into the row above it (a bot row over its first thread): repeat until no
  // shown row reaches past the hidden part's top, and the last row shown is not a `head` (an open folder's header,
  // a bot over its threads) whose rows are all hidden
  let from = bottom - band;
  for (let moved = true; moved; ) {
    moved = false;
    for (const r of rows)
      if (r.bottom > from + 0.5 && r.top < from - 0.5 && r.top < bottom) {
        from = r.top;
        moved = true;
      }
    if (moved) continue;
    let last: (typeof rows)[number] | null = null;
    for (const r of rows) if (r.bottom <= from + 0.5 && r.bottom > (last?.bottom ?? -Infinity)) last = r;
    if (last?.head && rows.some((r) => r.top >= last!.bottom - 0.5 && r.top < bottom)) {
      from = last.top;
      moved = true;
    }
  }
  return Math.max(band, Math.ceil(bottom - from));
}

/** A row that heads others below it (an open folder's header, a bot row over its threads): never the last one shown. */
export const isHead = (r: Element) =>
  (r.matches(".tg-h") && !r.closest(".tg")?.matches(".shut")) || (r.matches(".bot-w > .bot") && !!r.parentElement?.querySelector(".th-tree"));

export function edgeOf(el: { scrollTop: number; clientHeight: number; scrollHeight: number }): "above" | "below" | "both" | null {
  const above = el.scrollTop > 1;
  const below = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
  return above && below ? "both" : above ? "above" : below ? "below" : null;
}

export function useEdgeFade<T extends HTMLElement>(own?: { current: T | null }): (el: T | null) => void {
  const stop = useRef<(() => void) | null>(null);
  return useCallback(
    (el: T | null) => {
      if (own) own.current = el;
      stop.current?.();
      stop.current = null;
      if (!el) return;
      const read = () => {
        const m = edgeOf(el);
        if (m) el.dataset.more = m;
        else delete el.dataset.more;
        let clip = "";
        if (m === "below" || m === "both") {
          const box = el.getBoundingClientRect();
          const rows = [...el.querySelectorAll<HTMLElement>(CUT_ROWS)].map((r) => {
            const b = r.getBoundingClientRect();
            return { top: b.top, bottom: b.bottom, head: isHead(r) };
          });
          clip = `inset(0 0 ${cutBelow(box.bottom, rows)}px 0)`;
        }
        if (el.style.clipPath !== clip) el.style.clipPath = clip;
      };
      read();
      el.addEventListener("scroll", read, { passive: true });
      const ro = typeof ResizeObserver === "function" ? new ResizeObserver(read) : null;
      ro?.observe(el);
      // rows come and go (threads load, a terminal starts): the list's content changes size, not the list
      const mo = typeof MutationObserver === "function" ? new MutationObserver(read) : null;
      mo?.observe(el, { childList: true, subtree: true });
      stop.current = () => {
        el.removeEventListener("scroll", read);
        ro?.disconnect();
        mo?.disconnect();
      };
    },
    [own],
  );
}
