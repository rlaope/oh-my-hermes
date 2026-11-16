// BOTS | TERMINALS: the line between the two regions is a handle (spacing, 2026-11-16). Auto (nothing saved) is the
// sidebar's own layout: each region takes what its rows need and they share the rest. Dragging sets BOTS' share of
// the two regions' height, kept on this computer (`omher.side.split`); each region keeps at least SPLIT_MIN px.
// Double-click goes back to auto. Arrow keys move it by SPLIT_STEP px.
import { useCallback, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import { t } from "../i18n";

export const SPLIT_KEY = "omher.side.split";
export const SPLIT_MIN = 120;
export const SPLIT_STEP = 16;

/** BOTS' share of `total` px when it is to be `bots` px tall, each region at least `min` px (a total too small for
 *  both halves splits it evenly). */
export function clampSplit(total: number, bots: number, min = SPLIT_MIN): number {
  if (total <= 0) return 0.5;
  if (total < 2 * min) return 0.5;
  return Math.min(total - min, Math.max(min, bots)) / total;
}

/** The saved share, or null (auto) when none or not a number between 0 and 1. */
export function readSplit(raw: string | null): number | null {
  const n = raw === null ? NaN : Number(raw);
  return Number.isFinite(n) && n > 0 && n < 1 ? n : null;
}

function load(): number | null {
  try {
    return readSplit(localStorage.getItem(SPLIT_KEY));
  } catch {
    return null;
  }
}
function save(share: number | null) {
  try {
    if (share === null) localStorage.removeItem(SPLIT_KEY);
    else localStorage.setItem(SPLIT_KEY, String(Math.round(share * 1000) / 1000));
  } catch {
    /* no storage */
  }
}

type Sec = RefObject<HTMLElement | null>;

/** The two regions' styles for the saved share (none in auto) and the handle's actions. */
export function useSideSplit(bots: Sec, terms: Sec) {
  const [share, setShare] = useState<number | null>(load);
  const heights = () => [bots.current?.getBoundingClientRect().height ?? 0, terms.current?.getBoundingClientRect().height ?? 0] as const;
  const onDrag = useCallback(
    (e: PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const [hb, ht] = heights();
      const y0 = e.clientY;
      const total = hb + ht;
      let last: number | null = null;
      const move = (ev: globalThis.PointerEvent) => {
        last = clampSplit(total, hb + ev.clientY - y0);
        setShare(last);
      };
      const up = () => {
        removeEventListener("pointermove", move);
        removeEventListener("pointerup", up);
        document.body.classList.remove("side-resizing");
        if (last !== null) save(last);
      };
      document.body.classList.add("side-resizing");
      addEventListener("pointermove", move);
      addEventListener("pointerup", up);
    },
    [],
  );
  const reset = useCallback(() => {
    save(null);
    setShare(null);
  }, []);
  const onKey = useCallback((e: KeyboardEvent<HTMLElement>) => {
    const d = e.key === "ArrowUp" ? -SPLIT_STEP : e.key === "ArrowDown" ? SPLIT_STEP : 0;
    if (!d) return;
    e.preventDefault();
    const [hb, ht] = heights();
    const next = clampSplit(hb + ht, hb + d);
    save(next);
    setShare(next);
  }, []);
  const style = (grow: number): CSSProperties => ({ flex: `${grow} 1 0px`, minHeight: SPLIT_MIN, maxHeight: "none" });
  return {
    share,
    bots: share === null ? undefined : style(share),
    terms: share === null ? undefined : style(1 - share),
    onDrag,
    reset,
    onKey,
  };
}

/** The handle: a thin line with a taller grab band, between BOTS and TERMINALS. */
export function SplitDivider({ share, onDrag, onReset, onKey }: { share: number | null; onDrag: (e: PointerEvent<HTMLElement>) => void; onReset: () => void; onKey: (e: KeyboardEvent<HTMLElement>) => void }) {
  return (
    <div
      className="side-split"
      role="separator"
      aria-orientation="horizontal"
      aria-label={t("side.split")}
      aria-valuenow={share === null ? undefined : Math.round(share * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      title={t("side.splitTip")}
      tabIndex={0}
      data-testid="side-split"
      data-mode={share === null ? "auto" : "set"}
      onPointerDown={onDrag}
      onDoubleClick={onReset}
      onKeyDown={onKey}
    />
  );
}
