import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { moveRange } from "../state/order";

/** Hold this long without moving to pick a row up; moving first leaves it a plain press (or a scroll). */
export const HOLD_MS = 300;
const SLOP = 5;

interface Lift {
  bot: string;
  from: number;
  to: number;
  /** Pointer y at pick-up; the lifted row follows the pointer from there. */
  y0: number;
  dy: number;
  /** The lifted row's height plus the list gap: how far the rows it passes slide. */
  step: number;
  range: [number, number];
  /** Each row's vertical middle at pick-up, before anything slid (the list does not scroll mid-drag). */
  mids: number[];
}

/** What one sidebar row needs from the drag: its handlers and how it is drawn right now. */
export interface RowDrag {
  onPointerDown: (e: PointerEvent<HTMLDivElement>) => void;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
  lifted: boolean;
  /** px: the lifted row follows the pointer; a row it passes slides one step out of the way. */
  dy: number;
  /** A drag is on: the other rows animate their slide. */
  active: boolean;
}

/** The index a row picked up at `from` lands on with the pointer at `y`: past a neighbour's middle it takes that
 *  neighbour's place. Kept inside `range`. */
export function dropIndex(mids: readonly number[], from: number, range: readonly [number, number], y: number): number {
  let to = from;
  for (let i = range[0]; i <= range[1]; i += 1) {
    if (i < from && y < mids[i]) to = Math.min(to, i);
    if (i > from && y > mids[i]) to = Math.max(to, i);
  }
  return to;
}

/** Hold a bot row to pick it up, drag it up or down, let go to drop it (`onMove(bot, index)`); Escape puts it back.
 *  ⌥↑ / ⌥↓ on a focused row moves it one place. Off while the list is filtered by search, where a row's index is
 *  not its sidebar index. */
export function useRowDrag(order: readonly string[], pinned: readonly string[], on: boolean, onMove: (bot: string, to: number) => void) {
  const [lift, setLift] = useState<Lift | null>(null);
  const liftRef = useRef<Lift | null>(null);
  liftRef.current = lift;
  const hold = useRef<(() => void) | null>(null);
  const moveRef = useRef(onMove);
  moveRef.current = onMove;

  const lifted = lift !== null;
  useEffect(() => {
    if (!lifted) return;
    const finish = (drop: boolean) => {
      const l = liftRef.current;
      liftRef.current = null;
      setLift(null);
      if (!l) return;
      // the release that ends a drag must not also open the bot under it
      const swallow = (e: Event) => {
        e.stopPropagation();
        e.preventDefault();
      };
      window.addEventListener("click", swallow, { capture: true, once: true });
      window.setTimeout(() => window.removeEventListener("click", swallow, { capture: true }), 0);
      if (drop && l.to !== l.from) moveRef.current(l.bot, l.to);
    };
    const onPointer = (e: globalThis.PointerEvent) => {
      const l = liftRef.current;
      if (!l) return;
      const next = { ...l, dy: e.clientY - l.y0, to: dropIndex(l.mids, l.from, l.range, e.clientY) };
      liftRef.current = next;
      setLift(next);
    };
    const onUp = () => finish(true);
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      finish(false);
    };
    document.body.classList.add("row-dragging");
    window.addEventListener("pointermove", onPointer);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    window.addEventListener("keydown", onKey, true);
    return () => {
      document.body.classList.remove("row-dragging");
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [lifted]);

  useEffect(() => () => hold.current?.(), []);

  const row = (bot: string): RowDrag | null => {
    if (!on) return null;
    const index = order.indexOf(bot);
    const l = lift;
    let dy = 0;
    if (l) {
      if (l.bot === bot) dy = l.dy;
      else if (l.from < index && index <= l.to) dy = -l.step;
      else if (l.to <= index && index < l.from) dy = l.step;
    }
    return {
      lifted: l?.bot === bot,
      dy,
      active: !!l,
      onPointerDown(e) {
        // the primary button only, and not on the ⋯ button or an open menu
        if (e.button !== 0 || liftRef.current || (e.target as Element).closest(".bot-more, .bot-new, [role=menu]")) return;
        const range = moveRange(order, pinned, bot);
        if (!range || range[0] === range[1]) return;
        const el = e.currentTarget;
        const x = e.clientX;
        const y = e.clientY;
        hold.current?.();
        const early = (ev: globalThis.PointerEvent) => {
          if (Math.abs(ev.clientX - x) > SLOP || Math.abs(ev.clientY - y) > SLOP) cancel();
        };
        const cancel = () => {
          window.clearTimeout(timer);
          window.removeEventListener("pointermove", early);
          window.removeEventListener("pointerup", cancel);
          window.removeEventListener("pointercancel", cancel);
          if (hold.current === cancel) hold.current = null;
        };
        const timer = window.setTimeout(() => {
          cancel();
          const list = el.parentElement;
          const rows = [...(list?.querySelectorAll<HTMLElement>(":scope > .bot-w") ?? [])];
          const mids = rows.map((r) => {
            const b = r.getBoundingClientRect();
            return b.top + b.height / 2;
          });
          const gap = list ? parseFloat(getComputedStyle(list).rowGap) || 0 : 0;
          setLift({ bot, from: index, to: index, y0: y, dy: 0, step: el.getBoundingClientRect().height + gap, range, mids });
        }, HOLD_MS);
        window.addEventListener("pointermove", early);
        window.addEventListener("pointerup", cancel);
        window.addEventListener("pointercancel", cancel);
        hold.current = cancel;
      },
      onKeyDown(e) {
        if (!e.altKey || e.metaKey || e.ctrlKey || e.shiftKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
        e.preventDefault();
        moveRef.current(bot, index + (e.key === "ArrowUp" ? -1 : 1));
      },
    };
  };

  return { row };
}
