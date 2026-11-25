// Clicking a bot (its sidebar row or its dock tile) opens its chat and slides the BOTS region up so that bot's row
// sits at the region's top with its threads under it (owner, 2026-11-16: "사이드바 위로 스르르륵 올라가서 딱 봇 쪽
// 스레드 보이게"). Only the BOTS list scrolls; TERMINALS and the dock stay put. ~250 ms ease-out; with reduced
// motion it jumps. A region whose end is reached stops there (the last bots cannot rise past the bottom).

import { CUT_ROWS } from "./edgeFade";

export const REVEAL_MS = 250;

let pending: string | null = null;

/** The scrollTop that puts `row` at the top of `list` (within what the list can scroll). */
export function topFor(listTop: number, rowTop: number, scrollTop: number, maxScroll: number, pad = 0): number {
  return Math.max(0, Math.min(maxScroll, Math.round(scrollTop + rowTop - listTop - pad)));
}

type Box = { top: number; bottom: number };

/** The scrollTop that leaves no row cut at the list's top edge (a row showing only its lower half under the BOTS
 *  header reads as a stray subtitle): from `scrollTop`, scroll on past the cut row, or, where the list cannot go
 *  further, back to that row's top; either only while `keep` (the row being revealed) stays whole in the box.
 *  `rows` and `keep` are where they stand at `scrollTop`. A cut at the bottom edge has its own cue (edgeFade). */
export function wholeTop(scrollTop: number, maxScroll: number, box: Box, rows: readonly Box[], keep?: Box): number {
  let cut: Box | null = null;
  for (const r of rows) if (r.top < box.top - 0.5 && r.bottom > box.top + 0.5 && (!cut || r.top > cut.top)) cut = r;
  if (!cut) return scrollTop;
  const down = Math.ceil(cut.bottom - box.top);
  if (scrollTop + down <= maxScroll && (!keep || keep.top - down >= box.top - 0.5)) return scrollTop + down;
  const up = Math.ceil(box.top - cut.top);
  if (scrollTop - up >= 0 && (!keep || keep.bottom + up <= box.bottom + 0.5)) return scrollTop - up;
  return scrollTop;
}

/** `wholeTop` for `list` as it would stand at scrollTop `to`, keeping `row` whole. */
export function wholeTopOf(list: HTMLElement, row: HTMLElement | null, to: number): number {
  const shift = list.scrollTop - to;
  const at = (el: Element) => {
    const b = el.getBoundingClientRect();
    return { top: b.top + shift, bottom: b.bottom + shift };
  };
  const b = list.getBoundingClientRect();
  return wholeTop(to, list.scrollHeight - list.clientHeight, { top: b.top, bottom: b.bottom }, [...list.querySelectorAll(CUT_ROWS)].map(at), row ? at(row) : undefined);
}

const easeOut = (x: number) => 1 - (1 - x) ** 3;

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Whether a top reveal of `bot` was asked for and has not run yet (the sidebar's own nearest-scroll then waits). */
export const revealPending = (bot: string): boolean => pending === bot;

/** Slide BOTS so bot `bot`'s row is at the top (after the chat opens and the row has its threads). */
export function revealBotTop(bot: string): void {
  pending = bot;
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      if (pending !== bot) return;
      pending = null;
      const row = document.querySelector<HTMLElement>(`[data-testid="bot-row-${CSS.escape(bot)}"]`);
      const list = row?.closest<HTMLElement>(".bot-list");
      if (!row || !list) return;
      const from = list.scrollTop;
      // at the list's end the row cannot rise to the top: the top edge then still lands between two rows
      const top = topFor(list.getBoundingClientRect().top, row.getBoundingClientRect().top, from, list.scrollHeight - list.clientHeight);
      const to = wholeTopOf(list, row, top);
      list.dataset.reveal = bot;
      if (to === from || reduced()) {
        list.scrollTop = to;
        list.dataset.revealed = bot;
        return;
      }
      const start = performance.now();
      const step = (now: number) => {
        const k = Math.min(1, (now - start) / REVEAL_MS);
        list.scrollTop = from + (to - from) * easeOut(k);
        if (k < 1 && list.dataset.reveal === bot) requestAnimationFrame(step);
        else if (k >= 1) list.dataset.revealed = bot;
      };
      requestAnimationFrame(step);
    }),
  );
}
