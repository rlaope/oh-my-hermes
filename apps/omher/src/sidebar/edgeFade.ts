// A sidebar list that scrolls on its own (BOTS, TERMINALS) fades out at an edge that has more rows past it, so a row
// cut by the region's end reads as "more below" (or above), not as a broken row. `data-more` on the list: "below",
// "above", "both" or nothing; the fade itself is CSS (sessions.css). Use the returned callback as the list's `ref`
// (the list can mount after its section, as TERMINALS does with its first session).
import { useCallback, useRef } from "react";

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
