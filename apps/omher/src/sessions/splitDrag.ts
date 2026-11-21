// Drag a TERMINALS session onto the open terminal to split it there, as VS Code's editor groups and Orca do: a
// TERMINALS row from the sidebar, or a split pane by its grip (SplitView). The pane under the pointer is the target and
// the edge nearest the pointer is the side the session goes (left, right, over or under it; no middle zone, so every
// drop on a pane splits it); a translucent half of that pane shows where. A session already in the target's split moves
// there; a full split (MAX_PANES) takes no new one and shows nothing; a session never drops on its own pane. Letting go
// anywhere else, or Escape, does nothing. Pointer events only: HTML5 drag and drop fights the native file drop in
// Tauri's webview (on Windows above all).
import type { PointerEvent as ReactPointerEvent } from "react";
import { MAX_PANES, panesOf } from "../terminal/layout";
import { isTerminalRec } from "./agents";
import { getSessions } from "./sessions";
import { getSplit, groupOf, paneOf, type SplitDirName } from "./splitState";

/** How far the pointer goes before a press is a drag (a smaller wobble stays a click). */
const SLOP = 5;

export interface DropTarget {
  /** the session whose pane takes the drop */
  at: string;
  side: SplitDirName;
  box: DOMRect;
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

/** The half of the target pane the drop would fill. */
function shadeRect({ box, side }: DropTarget): { left: number; top: number; width: number; height: number } {
  const { left, top, width, height } = box;
  if (side === "left") return { left, top, width: width / 2, height };
  if (side === "right") return { left: left + width / 2, top, width: width / 2, height };
  if (side === "up") return { left, top, width, height: height / 2 };
  return { left, top: top + height / 2, width, height: height / 2 };
}

/** A press on a TERMINALS row or a pane's grip, followed: past SLOP it is a drag of session `drag`, and letting go on a
 *  pane that can take it calls `onDrop`. The click a drag ends with is swallowed (it opens or toggles nothing); a
 *  press that never moved stays an ordinary click. */
export function pressToSplit(e: ReactPointerEvent<HTMLElement>, drag: string, onDrop: (t: DropTarget) => void): void {
  if (e.button !== 0 || paneOf(drag) === null) return;
  const sx = e.clientX;
  const sy = e.clientY;
  let moving = false;
  let target: DropTarget | null = null;
  let shade: HTMLDivElement | null = null;
  const show = () => {
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
    if (!moving) {
      if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < SLOP) return;
      moving = true;
      document.body.classList.add("split-dragging");
      getSelection()?.removeAllRanges();
    }
    target = dropTargetAt(ev.clientX, ev.clientY, drag);
    show();
  };
  const end = (ev: PointerEvent | null) => {
    removeEventListener("pointermove", move);
    removeEventListener("pointerup", up);
    removeEventListener("pointercancel", cancel);
    removeEventListener("keydown", key, true);
    const drop = ev && moving ? dropTargetAt(ev.clientX, ev.clientY, drag) : null;
    target = null;
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
}
