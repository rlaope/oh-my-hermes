// The dock at the bottom of the sidebar holds BOTS ONLY, and only while BOTS is scrolled (owner, 2026-11-16: "스크롤을
// 하면 저 하단에 있는 게 상단에 보이게" / "클로드랑 덱스는 빼고"): its tiles are exactly the bots whose rows scrolled out
// of view at the top of BOTS, in list order, at most six. With every bot row in view (scrollTop 0) there is no dock.
// Nothing is pinned or stored: the tiles follow the scroll.
import { useEffect, useState } from "react";

export const DOCK_MAX = 6;

/** The bots whose own row (face and name, not its threads) is wholly above the list's top edge, in list order. */
export function botsAbove(listTop: number, rows: readonly { name: string; bottom: number }[]): string[] {
  return rows.filter((r) => r.bottom <= listTop + 1).map((r) => r.name);
}

const PREFIX = "bot-row-";

function read(list: HTMLElement): string[] {
  if (list.scrollTop <= 0) return [];
  const top = list.getBoundingClientRect().top;
  const rows = [...list.querySelectorAll<HTMLElement>(`:scope > [data-testid^="${PREFIX}"]`)].map((w) => ({
    name: w.dataset.testid!.slice(PREFIX.length),
    bottom: (w.querySelector<HTMLElement>(":scope > .bot") ?? w).getBoundingClientRect().bottom,
  }));
  return botsAbove(top, rows);
}

/** The bots scrolled out of view above the BOTS list; follows its scroll, its size and its rows. */
export function useBotsAbove(list: { current: HTMLElement | null }): string[] {
  const [above, setAbove] = useState<string[]>([]);
  useEffect(() => {
    const el = list.current;
    if (!el) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const next = read(el);
        setAbove((cur) => (cur.join("\n") === next.join("\n") ? cur : next));
      });
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(update) : null;
    ro?.observe(el);
    const mo = typeof MutationObserver === "function" ? new MutationObserver(update) : null;
    mo?.observe(el, { childList: true, subtree: true });
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener("scroll", update);
      ro?.disconnect();
      mo?.disconnect();
    };
  }, [list]);
  return above;
}
