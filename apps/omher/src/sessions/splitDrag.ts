// Drag a TERMINALS session onto the open terminal to split it there, as VS Code's editor groups and Orca do: a
// TERMINALS row from the sidebar, or a split pane by its grip (SplitView). The pane under the pointer is the target and
// the edge nearest the pointer is the side the session goes (left, right, over or under it; no middle zone, so every
// drop on a pane splits it); a translucent half of that pane shows where. A session already in the target's split moves
// there; a full split (MAX_PANES) takes no new one and shows nothing; a session never drops on its own pane. Letting go
// anywhere else, or Escape, does nothing. Pointer events only: HTML5 drag and drop fights the native file drop in
// Tauri's webview (on Windows above all).
//
// A TERMINALS row dragged over another row of its own folder in the sidebar moves there instead: a line shows where it
// goes (above the row under the pointer, or below it past its middle), and letting go puts it there (moveRow).
//
// The main column's header of a TERMINALS session drags too (Otty's): in a split it is the focused pane's grip; a
// session on its own drags onto its own terminal to merge with its folder's next session (`mergePartner`), the preview
// naming that session in the half it will fill. Taken back onto the header, or Escape, nothing changes. Any drag ends
// with nothing done when the window loses focus or a move comes with the button up (let go outside the window).
import type { PointerEvent as ReactPointerEvent } from "react";
import { MAX_PANES, panesOf } from "../terminal/layout";
import { isTerminalRec, type AgentInfo, type SessionRec } from "./agents";
import { pathKey } from "./folders";
import { getSessions } from "./sessions";
import { getSplit, groupOf, paneOf, type SplitDirName, type SplitGroup } from "./splitState";

/** How far the pointer goes before a press is a drag (a smaller wobble stays a click). */
const SLOP = 5;

export interface DropTarget {
  /** the session whose pane takes the drop */
  at: string;
  side: SplitDirName;
  box: DOMRect;
  /** the name of the session that fills the other half (a header merge: `at`, which is not under the pointer) */
  fill?: string;
}

/** The side of `box` nearest to the point. */
export function sideAt(box: { left: number; top: number; width: number; height: number }, x: number, y: number): SplitDirName {
  const fx = (x - box.left) / (box.width || 1);
  const fy = (y - box.top) / (box.height || 1);
  const near: [SplitDirName, number][] = [
    ["left", fx],
    ["right", 1 - fx],
    ["up", fy],
    ["down", 1 - fy],
  ];
  return near.reduce((m, c) => (c[1] < m[1] ? c : m))[0];
}

/** Where session `drag` would go with the pointer at (x, y): a TERMINALS pane in the main column that can take it. */
export function dropTargetAt(x: number, y: number, drag: string): DropTarget | null {
  const el = document.elementFromPoint(x, y);
  const host = el?.closest<HTMLElement>('[data-testid="split-pane"]') ?? el?.closest<HTMLElement>('[data-testid="terminal"]');
  const at = host?.getAttribute("data-session");
  const n = paneOf(drag);
  if (!host || !at || at === drag || n === null || paneOf(at) === null) return null;
  const ss = getSessions().getState();
  const rec = ss.list.find((r) => r.id === at);
  if (!rec || !isTerminalRec(ss.agents, rec)) return null;
  const g = groupOf(getSplit().groups, at);
  if (g && panesOf(g.layout).length >= MAX_PANES && !panesOf(g.layout).includes(n)) return null;
  const box = host.getBoundingClientRect();
  return { at, side: sideAt(box, x, y), box };
}

/** The session a TERMINALS session `id` on its own merges with when its header is dragged onto its terminal: the next
 *  TERMINALS session of its folder in the session list's order (the order the sidebar lists a folder's rows in, a row
 *  a sidebar search or a collapsed folder hides included), or the one before it when it is the last. A session in a
 *  split already is passed over (merging never takes a pane from another split), and so is anything that is not a
 *  TERMINALS session (a bot chat has no row there). Null when `id` is in a split, is not a TERMINALS session, or its
 *  folder has no other session that can go: a partner is never taken from another folder. The preview names it. */
export function mergePartner(list: readonly SessionRec[], agents: AgentInfo[] | null | undefined, groups: SplitGroup[], id: string): string | null {
  const me = list.find((r) => r.id === id);
  if (!me || paneOf(id) === null || !isTerminalRec(agents, me) || groupOf(groups, id)) return null;
  const rows = list.filter((r) => isTerminalRec(agents, r) && pathKey(r.cwd) === pathKey(me.cwd));
  const i = rows.findIndex((r) => r.id === id);
  const free = (r: SessionRec) => paneOf(r.id) !== null && !groupOf(groups, r.id);
  return rows.slice(i + 1).find(free)?.id ?? rows.slice(0, i).reverse().find(free)?.id ?? null;
}

/** Where the header of session `drag` (on its own) would merge it with `partner` (named `name`), the pointer at
 *  (x, y): over `drag`'s own terminal (or its paused or ended view) in the main column, on the side nearest the
 *  pointer. Anywhere else, the header band and a view the main column switched to during the drag included, is no
 *  target. */
export function mergeTargetAt(x: number, y: number, drag: string, partner: string, name: string): DropTarget | null {
  const host = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-testid="terminal"], [data-testid="session-idle"]');
  if (!host || host.closest('[data-testid="session-split"], [data-testid="termpanel"]')) return null;
  if (host.getAttribute("data-session") !== drag) return null;
  const box = host.getBoundingClientRect();
  return { at: partner, side: sideAt(box, x, y), box, fill: name };
}

export interface RowTarget {
  /** the row the dragged one goes next to */
  at: string;
  /** below it (past its middle), else above */
  after: boolean;
  box: DOMRect;
}

/** Where row `drag` would move with the pointer at (x, y): next to another TERMINALS row of the same folder. */
export function rowTargetAt(x: number, y: number, drag: string): RowTarget | null {
  const el = document.elementFromPoint(x, y)?.closest<HTMLElement>('.ss-row.tr[data-testid^="session-"]');
  const at = el?.getAttribute("data-testid")?.slice("session-".length);
  if (!el || !at || at === drag) return null;
  const list = getSessions().getState().list;
  const from = list.find((r) => r.id === drag);
  const to = list.find((r) => r.id === at);
  // one folder however its path is spelled, as the sidebar groups it (and as moveRow checks)
  if (!from || !to || pathKey(from.cwd) !== pathKey(to.cwd)) return null;
  const box = el.getBoundingClientRect();
  return { at, after: y > box.top + box.height / 2, box };
}

/** The half of the target pane the drop would fill. */
function shadeRect({ box, side }: DropTarget): { left: number; top: number; width: number; height: number } {
  const { left, top, width, height } = box;
  if (side === "left") return { left, top, width: width / 2, height };
  if (side === "right") return { left: left + width / 2, top, width: width / 2, height };
  if (side === "up") return { left, top, width, height: height / 2 };
  return { left, top: top + height / 2, width, height: height / 2 };
}

const OTHER: Record<SplitDirName, SplitDirName> = { left: "right", right: "left", up: "down", down: "up" };

export interface PressOptions {
  /** where the drag would drop instead of a pane under the pointer (a header merge: `mergeTargetAt`) */
  aim?: (x: number, y: number) => DropTarget | null;
  /** the element that had the keyboard keeps it once the press is a drag (a press on the header, which takes no
   *  focus, would leave the terminal without it); a plain click is left as it is */
  keepFocus?: boolean;
}

/** A press on a TERMINALS row or a pane's grip, followed: past SLOP it is a drag of session `drag`, and letting go on a
 *  pane that can take it calls `onDrop`. The click a drag ends with is swallowed (it opens or toggles nothing); a
 *  press that never moved stays an ordinary click. */
export function pressToSplit(e: ReactPointerEvent<HTMLElement>, drag: string, onDrop: (t: DropTarget) => void, onRow?: (t: RowTarget) => void, o: PressOptions = {}): void {
  const canSplit = paneOf(drag) !== null;
  if (e.button !== 0 || (!canSplit && !onRow)) return;
  const sx = e.clientX;
  const sy = e.clientY;
  const had = o.keepFocus ? (document.activeElement as HTMLElement | null) : null;
  let moving = false;
  let target: DropTarget | null = null;
  let row: RowTarget | null = null;
  let shade: HTMLDivElement | null = null;
  let fill: HTMLDivElement | null = null;
  let line: HTMLDivElement | null = null;
  const aim = (x: number, y: number) => {
    target = canSplit ? (o.aim ?? ((px, py) => dropTargetAt(px, py, drag)))(x, y) : null;
    row = !target && onRow ? rowTargetAt(x, y, drag) : null;
  };
  const showLine = () => {
    if (!row) {
      line?.remove();
      line = null;
      return;
    }
    if (!line) {
      line = document.createElement("div");
      line.className = "row-drop";
      line.setAttribute("data-testid", "row-drop");
      line.setAttribute("aria-hidden", "true");
      document.body.appendChild(line);
    }
    const b = row.box;
    Object.assign(line.style, { left: `${b.left}px`, top: `${(row.after ? b.bottom : b.top) - 1}px`, width: `${b.width}px` });
    line.setAttribute("data-session", row.at);
    line.setAttribute("data-after", String(row.after));
  };
  // a header merge: the other half, named for the session that fills it
  const showFill = () => {
    if (!target?.fill) {
      fill?.remove();
      fill = null;
      return;
    }
    if (!fill) {
      fill = document.createElement("div");
      fill.className = "split-drop-fill";
      fill.setAttribute("data-testid", "split-drop-fill");
      fill.setAttribute("aria-hidden", "true");
      fill.appendChild(document.createElement("span"));
      document.body.appendChild(fill);
    }
    const r = shadeRect({ ...target, side: OTHER[target.side] });
    Object.assign(fill.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    fill.setAttribute("data-session", target.at);
    fill.setAttribute("data-side", OTHER[target.side]);
    fill.firstElementChild!.textContent = target.fill;
  };
  const show = () => {
    showLine();
    showFill();
    if (!target) {
      shade?.remove();
      shade = null;
      return;
    }
    if (!shade) {
      shade = document.createElement("div");
      shade.className = "split-drop";
      shade.setAttribute("data-testid", "split-drop");
      shade.setAttribute("aria-hidden", "true");
      document.body.appendChild(shade);
    }
    const r = shadeRect(target);
    Object.assign(shade.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    shade.setAttribute("data-side", target.side);
    shade.setAttribute("data-session", target.at);
  };
  const move = (ev: PointerEvent) => {
    // the button was let go where this page did not hear it (another app, outside the window): the drag is over
    if ((ev.buttons & 1) === 0) return end(null);
    if (!moving) {
      if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < SLOP) return;
      moving = true;
      document.body.classList.add("split-dragging");
      getSelection()?.removeAllRanges();
      if (had && had !== document.activeElement && had.isConnected) had.focus({ preventScroll: true });
    }
    aim(ev.clientX, ev.clientY);
    show();
  };
  const end = (ev: PointerEvent | null) => {
    removeEventListener("pointermove", move);
    removeEventListener("pointerup", up);
    removeEventListener("pointercancel", cancel);
    removeEventListener("keydown", key, true);
    removeEventListener("blur", cancel);
    if (ev && moving) aim(ev.clientX, ev.clientY);
    else {
      target = null;
      row = null;
    }
    const drop = target;
    const moveTo = row;
    target = null;
    row = null;
    show();
    document.body.classList.remove("split-dragging");
    if (!moving) return;
    // the click that follows a drag opens nothing
    const stop = (c: MouseEvent) => {
      c.stopPropagation();
      c.preventDefault();
    };
    addEventListener("click", stop, { capture: true, once: true });
    setTimeout(() => removeEventListener("click", stop, { capture: true }), 0);
    if (drop) onDrop(drop);
    else if (moveTo) onRow?.(moveTo);
  };
  const up = (ev: PointerEvent) => end(ev);
  const cancel = () => end(null);
  const key = (ev: KeyboardEvent) => {
    if (ev.key !== "Escape") return;
    if (moving) {
      ev.preventDefault();
      ev.stopPropagation();
    }
    end(null);
  };
  addEventListener("pointermove", move);
  addEventListener("pointerup", up);
  addEventListener("pointercancel", cancel);
  addEventListener("keydown", key, true);
  // the window losing focus (another app came forward) ends the drag with nothing done
  addEventListener("blur", cancel);
}
