// A sidebar list that scrolls on its own (BOTS, TERMINALS) marks an edge that has more rows past it. `data-more` on the
// list: "below", "above", "both" or nothing; the cue itself is CSS (sessions.css). At the bottom edge the region never
// ends on an empty band (owner, fix5):
// - at its top ("below"): no row is shown cut. The row the region's end would cut (and any row in the cue's band) is
//   hidden whole by a clip on the list, so the chevron sits on empty sidebar; the auto split (autoSplit.ts) sizes the
//   regions so that this hides nothing but the cue's band.
// - scrolled ("both"): the cut row shows, under a soft bottom fade, as in any scrolling list. Hiding it there left its
//   whole height empty above the chevron. The chevron's own band (CUE_PX) is clipped, so it never sits on text.
// - at its top, when hiding the cut row whole would leave more than BAND_MAX empty above the chevron (the next row is
//   an open folder's first card, which the region may not end without, or the region is taller than its last whole
//   row), it takes the scrolled treatment instead (`data-fade`): rows never hide behind the chevron under an empty
//   band.
// At the top edge, a row cut there (only its subtitle under the header) gets the same fade and chevron
// (`data-cut-top`); a reveal (revealBot.ts) first tries to land the edge between two rows.
// The clip is paint only: the list keeps its size, so nothing below it moves. Use the returned callback as the list's
// `ref` (the list can mount after its section, as TERMINALS does with its first session).
import { useCallback, useRef } from "react";

/** The rows that are shown whole or not at all: a bot's own row, a thread row, a folder header, a terminal row, a
 *  TERMINALS split card (its cells and grip are one unit, never cut mid-way). */
export const CUT_ROWS = ".bot-w > .bot, .th-row, .tg-h, .ss-row, .split-card, .bot-list > :not(.bot-w):not(.tg)";
/** The band kept free at a cut bottom edge for the chevron (sessions.css draws it there). */
export const CUE_PX = 14;
/** The most empty space a region may show above its chevron while it hides rows. */
export const BAND_MAX = 12;

/** How many px to hide at the bottom of a list whose box ends at `bottom`: from the top of the first row that would
 *  reach into the cue band, at least the band itself. `rows`: the rows' tops and bottoms. With the list's `top` given,
 *  a cut that would hide every row (a first row taller than the list) hides only the band: the top of that row shows,
 *  and its controls stay reachable, rather than an empty list. */
export function cutBelow(bottom: number, rows: readonly { top: number; bottom: number; head?: boolean }[], band = CUE_PX, top?: number): number {
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
  if (top !== undefined && from <= bottom - band && !rows.some((r) => r.bottom <= from + 0.5 && r.bottom > top + 0.5) && rows.some((r) => r.top < bottom)) return band;
  return Math.max(band, Math.ceil(bottom - from));
}

/** The px a split card is drawn shorter than its own height (`data-map-h`, the saved or dragged one) because the list
 *  caps it to fit (`--sc-cap`, set below). The auto split plans with the cards at their own heights, so a cap never
 *  feeds back into the room TERMINALS is given. */
export function cardGive(card: Element): number {
  const own = Number((card as HTMLElement).dataset.mapH);
  const map = card.querySelector(".sc-map");
  return map && Number.isFinite(own) ? Math.max(0, own - map.getBoundingClientRect().height) : 0;
}

/** The tallest map the first split card in `el` may draw so its whole card, grip and the chevron's band fit the list's
 *  box, or "" (no cap) when the list's rows fit it at their own heights. The saved height is never changed. */
function cardCap(el: HTMLElement): string {
  const cards = el.querySelectorAll<HTMLElement>(".split-card");
  const first = cards[0];
  const map = first?.querySelector(".sc-map");
  if (!first || !map) return "";
  let give = 0;
  for (const c of cards) give += cardGive(c);
  if (el.scrollHeight + give <= el.clientHeight + 1) return "";
  const box = el.getBoundingClientRect();
  const m = map.getBoundingClientRect();
  // the card sits under its folder's header, which may be far down the list: it fits the box once that folder is
  // scrolled to its top (the list's own top band counted for the first folder)
  const groupTop = (first.closest(".tg") ?? first).getBoundingClientRect().top;
  const above = m.top - groupTop + Math.min(Math.max(0, groupTop - box.top + el.scrollTop), 16);
  const below = first.getBoundingClientRect().bottom - m.bottom;
  return `${Math.max(0, Math.floor(el.clientHeight - above - below - CUE_PX))}px`;
}

/** A row that heads others below it (an open folder's header, a bot row over its threads): never the last one shown. */
export const isHead = (r: Element) =>
  (r.matches(".tg-h") && !r.closest(".tg")?.matches(".shut")) || (r.matches(".bot-w > .bot") && !!r.parentElement?.querySelector(".th-tree"));

/** Whether a row stands cut at the list's top edge (`top`): its top above the edge, its bottom below it. */
export function cutAbove(top: number, rows: readonly { top: number; bottom: number }[]): boolean {
  return rows.some((r) => r.top < top - 0.5 && r.bottom > top + 0.5);
}

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
        // a split card taller than the list gives way first (CSS only, so the rows below are read at the drawn size)
        const cap = cardCap(el);
        if (el.style.getPropertyValue("--sc-cap") !== cap) {
          if (cap) el.style.setProperty("--sc-cap", cap);
          else el.style.removeProperty("--sc-cap");
        }
        const m = edgeOf(el);
        if (m) el.dataset.more = m;
        else delete el.dataset.more;
        let clip = "";
        let fade = m === "both";
        if (m === "below" || m === "both") {
          const box = el.getBoundingClientRect();
          const rows = [...el.querySelectorAll<HTMLElement>(CUT_ROWS)].map((r) => {
            const b = r.getBoundingClientRect();
            return { top: b.top, bottom: b.bottom, head: isHead(r) };
          });
          if (m === "below") {
            const cut = cutBelow(box.bottom, rows, CUE_PX, box.top);
            // hiding the cut row whole would leave an empty band over the chevron: show it under the fade instead
            if (cut - CUE_PX > BAND_MAX) fade = true;
            else clip = `inset(0 0 ${cut}px 0)`;
          }
          // under the fade only the chevron's band is clipped: the cut row shows above it, never under the chevron
          if (fade) clip = `inset(0 0 ${CUE_PX}px 0)`;
        }
        if (fade) el.dataset.fade = "true";
        else delete el.dataset.fade;
        if (el.style.clipPath !== clip) el.style.clipPath = clip;
        // scrolled, a row the top edge cuts (a list too short to show the open row and whole rows above it) gets
        // the bottom edge's cue mirrored: a fade from the sidebar's colour and a chevron (sidebar.css)
        const cutTop = (m === "above" || m === "both") && cutAbove(el.getBoundingClientRect().top, [...el.querySelectorAll(CUT_ROWS)].map((r) => r.getBoundingClientRect()));
        if (cutTop) el.dataset.cutTop = "";
        else delete el.dataset.cutTop;
      };
      read();
      el.addEventListener("scroll", read, { passive: true });
      const ro = typeof ResizeObserver === "function" ? new ResizeObserver(read) : null;
      ro?.observe(el);
      // rows come and go (threads load, a terminal starts): the list's content changes size, not the list
      const mo = typeof MutationObserver === "function" ? new MutationObserver(read) : null;
      // and a split card's own height changes (its grip) without a row coming or going
      mo?.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-map-h"] });
      stop.current = () => {
        el.removeEventListener("scroll", read);
        ro?.disconnect();
        mo?.disconnect();
      };
    },
    [own],
  );
}
