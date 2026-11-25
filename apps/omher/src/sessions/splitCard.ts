// The sidebar's split card, kept apart from React and the DOM: how tall the card's map is, where each pane's cell sits
// in it, how a cell lays out its text for its own size, which state its edge shows and the elapsed time in its corner.
// Ideas from kasaterm's sidebar map (2rami/kasaterm, MIT); written fresh.
import { t } from "../i18n";
import { panesOf, paneRects, type Layout } from "../terminal/layout";
import type { TermStatus } from "./agents";

export const CARD_MIN_H = 46, CARD_MAX_H = 240, CARD_DEFAULT_CAP = 150, CELL_MIN_H = 42, GRIP_STEP = 16;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** The card's map height before anyone drags it: more panes, a taller map, raised so the shortest cell's share is
 *  CELL_MIN_H (a 1+3 split's third-height cells), never past CARD_MAX_H. */
export function defaultCardHeight(layout: Layout): number {
  const base = clamp(36 + 13 * panesOf(layout).length, CARD_MIN_H, CARD_DEFAULT_CAP);
  let share = 1;
  for (const r of paneRects(layout).values()) share = Math.min(share, r.h);
  // float shares (1/3 of 1) land a hair under the exact height; the epsilon keeps 126 from reading as 127
  const need = share > 0 ? Math.ceil(CELL_MIN_H / share - 1e-6) : CARD_MAX_H;
  return Math.min(CARD_MAX_H, Math.max(base, need));
}

/** A dragged map height, whole px inside [CARD_MIN_H, CARD_MAX_H]. */
export const clampCardHeight = (h: number): number => clamp(Math.round(h), CARD_MIN_H, CARD_MAX_H);

/** How a card's cells place their mark, title and last line, all left-aligned on the TERMINALS rows' icon column:
 *  `line` (mark and title on one line, no last line) when a cell is too short for two, `beside` (the title beside the
 *  mark, the last line under the title) when every cell is wide enough for a CLI's name there, else `stack` (the mark
 *  above the title, so the title has the cell's whole width). */
export type CellText = "line" | "beside" | "stack";
/** Below this a cell has no room for the mark above its title (16 + 2 + a 14 px title line, 4 px above and below; a
 *  default card's shortest cell, CELL_MIN_H less the 2 px gap, is 40): it shows one line, the title beside the mark. */
export const STACK_MIN_H = 40;
/** A stacked cell shows its last line from this height (mark 16, title 14, line 13, their gaps and 4 px above and
 *  below). */
export const STACK_LINE_H = 56;
/** From this width the title fits beside the 16 px mark: \"Claude Code\" (about 69 px at 11 px) and the cell's padding. */
export const BESIDE_MIN_W = 120;

/** One layout for a whole card, from what its smallest cell can hold, so a card never mixes layouts (a stacked tall
 *  cell beside short cells read as two designs); `lines`: whether every cell shows its last line. */
export function cardText(cells: readonly { w: number; h: number }[]): { text: CellText; lines: boolean } {
  if (!cells.length) return { text: "beside", lines: true };
  const minH = Math.min(...cells.map((c) => c.h));
  if (minH < STACK_MIN_H) return { text: "line", lines: false };
  if (cells.every((c) => c.w >= BESIDE_MIN_W)) return { text: "beside", lines: true };
  return { text: "stack", lines: minH >= STACK_LINE_H };
}

/** The layout one w×h cell would take on its own. */
export const cellText = (w: number, h: number): CellText => cardText([{ w, h }]).text;

/** The one state a cell's edge shows: a wait omher knows (a bot's request to type, `asked`) beats working, which beats
 *  background work; a ring seen by no one (`news`: a bell, an OSC 9 message, a progress done) is quiet news, not a
 *  wait, since it may as well mean the program finished. */
export type CellState = "work" | "bg" | "wait" | "news" | "err" | "ok" | "idle";
export function cellState(i: { status: TermStatus; asked: boolean; background?: number }): CellState {
  if (i.asked) return "wait";
  if (i.status === "err") return "err";
  if (i.status === "news") return "news";
  if (i.status === "busy") return "work";
  if ((i.background ?? 0) > 0) return "bg";
  return i.status === "ok" ? "ok" : "idle";
}

/** The corner time of a cell working for a minute or more of one busy streak (`14m`, `2h`); dimmer from ten minutes. */
export function elapsedLabel(busySince: number | undefined, busy: boolean, now: number): { text: string; old: boolean } | null {
  if (!busy || busySince === undefined) return null;
  const ms = now - busySince;
  if (ms < 60_000) return null;
  const text = ms < 3_600_000 ? t("unit.m", { n: Math.floor(ms / 60_000) }) : t("unit.h", { n: Math.floor(ms / 3_600_000) });
  return { text, old: ms >= 600_000 };
}

export interface CellBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Each pane's cell in px inside a w×h map, in the pane's real place and proportions, `gap` px between neighbours.
 *  Ids are session ids (`s12`), as splitState's `sessionOf` names them (not imported: splitState imports this file). */
export function cellBoxes(layout: Layout, w: number, h: number, gap = 2): CellBox[] {
  const out: CellBox[] = [];
  for (const [n, r] of paneRects(layout)) {
    out.push({ id: `s${n}`, x: r.x * w + gap / 2, y: r.y * h + gap / 2, w: Math.max(0, r.w * w - gap), h: Math.max(0, r.h * h - gap) });
  }
  return out;
}
