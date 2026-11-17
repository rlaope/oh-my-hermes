// BOTS | TERMINALS in auto mode (no divider share saved), sized from what the two lists hold (tidy, 2026-11-16):
// - both fit the room the sidebar has for them: each is as tall as its rows, the rest goes under them (above the footer)
// - else each region ends on a whole row: its list is cut just under a row (plus the chevron's band), never on an
//   expanded folder header or a bot whose threads are open with none of them showing. The smaller region is shown
//   whole when it needs at most AUTO_WHOLE of the room; else the two heights leave as little room unused as they can,
//   near an even split. A plain flex layout split evenly and left a blank band where edgeFade hid a cut row.
import { useEffect, type RefObject } from "react";
import { CUE_PX, CUT_ROWS, isHead } from "./edgeFade";

/** A region as the planner sees it: its height with every row shown, and the heights at which its list ends on a
 *  whole row (each below `need`). */
export interface Region {
  need: number;
  stops: number[];
}

/** The smaller region is shown whole when it needs at most this share of the room. */
export const AUTO_WHOLE = 0.6;
/** Neither region is made shorter than this (or its need, when that is less). */
export const AUTO_MIN = 96;

/** BOTS' and TERMINALS' heights for `room` px. */
export function planSplit(room: number, b: Region, t: Region, min = AUTO_MIN): [number, number] {
  if (room <= 0) return [b.need, t.need];
  if (b.need + t.need <= room) return [b.need, t.need];
  const minB = Math.min(b.need, min);
  const minT = Math.min(t.need, min);
  // where an even split would put BOTS; the smaller one whole when it is small enough
  let aim = Math.min(b.need, Math.max(room / 2, room - t.need));
  if (t.need <= b.need && t.need <= room * AUTO_WHOLE) aim = room - t.need;
  else if (b.need < t.need && b.need <= room * AUTO_WHOLE) aim = b.need;
  const hs = (r: Region) => [...new Set([...r.stops.filter((s) => s < r.need), r.need])].sort((x, y) => x - y);
  // the smaller one fits in AUTO_WHOLE of the room: it is shown whole, the other ends on its last whole row above it
  const small = t.need <= b.need ? "t" : "b";
  const sr = small === "t" ? t : b;
  const big = small === "t" ? b : t;
  if (sr.need <= room * AUTO_WHOLE) {
    const fit = hs(big).filter((h) => h <= room - sr.need && h >= Math.min(big.need, min));
    if (fit.length) {
      const h = fit[fit.length - 1]!;
      return small === "t" ? [h, t.need] : [b.need, h];
    }
  }
  let best: { hb: number; ht: number; score: number } | null = null;
  for (const hb of hs(b)) {
    if (hb < minB || hb > room - minT) continue;
    // TERMINALS: the tallest of its heights that fits under what BOTS leaves
    let ht = -1;
    for (const h of hs(t)) if (h <= room - hb && h > ht) ht = h;
    if (ht < minT) continue;
    const score = room - hb - ht + 0.25 * Math.abs(hb - aim);
    if (!best || score < best.score - 0.01) best = { hb, ht, score };
  }
  if (best) return [best.hb, best.ht];
  const hb = Math.max(minB, Math.min(room - minT, aim));
  return [hb, room - hb];
}

/** The list heights at which `list` ends just under a whole row with the chevron's band free (a folder header of an
 *  open folder or a bot with its threads open never ends it). Content coordinates, from the list's top. */
export function listStops(list: HTMLElement): number[] {
  const top = list.getBoundingClientRect().top - list.scrollTop;
  const stops: number[] = [];
  for (const r of list.querySelectorAll<HTMLElement>(CUT_ROWS)) {
    const box = r.getBoundingClientRect();
    if (box.height === 0) continue;
    if (isHead(r)) continue;
    stops.push(Math.ceil(box.bottom - top) + CUE_PX);
  }
  return stops;
}

/** A section's height with all of it shown, and its list (the part that scrolls). */
function measure(sec: HTMLElement): { need: number; chrome: number; list: HTMLElement | null } {
  const cs = getComputedStyle(sec);
  let need = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
  let list: HTMLElement | null = null;
  for (const c of sec.children) {
    const el = c as HTMLElement;
    const ccs = getComputedStyle(el);
    if (ccs.position === "absolute" || ccs.position === "fixed" || ccs.display === "none") continue;
    const m = parseFloat(ccs.marginTop) + parseFloat(ccs.marginBottom);
    if (el.matches(".bot-list, .ss-list")) {
      list = el;
      need += el.scrollHeight + m;
    } else need += el.getBoundingClientRect().height + m;
  }
  return { need: Math.ceil(need), chrome: Math.ceil(need) - (list?.scrollHeight ?? 0), list };
}

// only the height is inline; `data-auto` turns the flex sizing off in CSS (sessions.css), so the divider's own inline
// flex (React's) is never touched here
function clear(sec: HTMLElement | null) {
  if (sec && sec.dataset.auto) {
    sec.style.height = "";
    delete sec.dataset.auto;
  }
}

/** While `on`, sizes the two sections from their rows (planSplit) and keeps them so as rows and the window change. */
export function useAutoSplit(bots: RefObject<HTMLElement | null>, terms: RefObject<HTMLElement | null>, on: boolean, deps: unknown[] = []) {
  useEffect(() => {
    const b = bots.current;
    const t = terms.current;
    if (!on || !b || !t) {
      clear(b);
      clear(t);
      return;
    }
    const side = b.parentElement!;
    let frame = 0;
    const apply = () => {
      frame = 0;
      // the room: the sidebar's height less everything else in it (the footer's auto margin is free room, not counted)
      const scs = getComputedStyle(side);
      let room = side.clientHeight - parseFloat(scs.paddingTop) - parseFloat(scs.paddingBottom);
      for (const c of side.children) {
        const el = c as HTMLElement;
        const ccs = getComputedStyle(el);
        if (ccs.position === "absolute" || ccs.position === "fixed" || ccs.display === "none") continue;
        const own = el === b || el === t;
        room -= (own ? 0 : el.getBoundingClientRect().height) + (el.matches(".side-foot") ? 0 : parseFloat(ccs.marginTop)) + parseFloat(ccs.marginBottom);
      }
      room = Math.floor(room);
      const mb = measure(b);
      const mt = measure(t);
      const region = (m: ReturnType<typeof measure>): Region => ({ need: m.need, stops: m.list ? listStops(m.list).map((s) => s + m.chrome) : [] });
      const [hb, ht] = planSplit(room, region(mb), region(mt));
      for (const [sec, h] of [[b, hb], [t, ht]] as const) {
        const px = `${Math.round(h)}px`;
        if (sec.style.height === px) continue;
        sec.dataset.auto = "1";
        sec.style.height = px;
      }
    };
    const soon = () => {
      if (!frame) frame = requestAnimationFrame(apply);
    };
    apply();
    const ro = new ResizeObserver(soon);
    ro.observe(side);
    for (const c of side.children) ro.observe(c);
    // rows come and go (threads load, a terminal starts, a folder folds), and the dock or the needs strip come in
    const mo = new MutationObserver((recs) => {
      for (const r of recs) if (r.target === side) for (const n of r.addedNodes) if (n instanceof Element) ro.observe(n);
      soon();
    });
    mo.observe(side, { childList: true });
    for (const sec of [b, t]) mo.observe(sec, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "data-collapsed"] });
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      mo.disconnect();
      clear(b);
      clear(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, ...deps]);
}
