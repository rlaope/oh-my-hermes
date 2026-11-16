// Clicking a bot (its sidebar row or its dock tile) opens its chat and slides the BOTS region up so that bot's row
// sits at the region's top with its threads under it (owner, 2026-11-16: "사이드바 위로 스르르륵 올라가서 딱 봇 쪽
// 스레드 보이게"). Only the BOTS list scrolls; TERMINALS and the dock stay put. ~250 ms ease-out; with reduced
// motion it jumps. A region whose end is reached stops there (the last bots cannot rise past the bottom).

export const REVEAL_MS = 250;

let pending: string | null = null;

/** The scrollTop that puts `row` at the top of `list` (within what the list can scroll). */
export function topFor(listTop: number, rowTop: number, scrollTop: number, maxScroll: number, pad = 0): number {
  return Math.max(0, Math.min(maxScroll, Math.round(scrollTop + rowTop - listTop - pad)));
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
      const to = topFor(list.getBoundingClientRect().top, row.getBoundingClientRect().top, from, list.scrollHeight - list.clientHeight);
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
