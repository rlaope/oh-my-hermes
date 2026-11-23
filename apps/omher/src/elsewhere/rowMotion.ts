// Whether the side panel's tab row was still moving for a press during the maximise / restore slide
// (PanelTabs.tsx onSweptPress): a press on a tab still moving belongs to the row's double-click, one on a tab that
// stopped is the tab's. Kept free of the DOM so the rule is tested on recorded frames.

/** One drawn frame of the slide: when it was drawn (performance.now()) and the left edge of the row's free space. */
export type RowFrame = { at: number; x0: number };

/** How recent the row's last step before the press must be for the press to count as aimed before it. */
export const MOVE_MS = 60;

/**
 * - `frames`: the slide's frames, oldest first.
 * - `press`: the press's own time (`e.timeStamp`), not when its handler runs.
 * - `live`: the row's edge now, when the handler runs; the browser hit-tested the press against this layout.
 * - `sliding`: the slide's CSS transition still runs.
 *
 * The row was moving for this press when the slide still runs, when it moved between the last frame drawn at or
 * before the press (what the person saw) and the live layout (a late handler: the slide went on after the press and
 * the hit test found what slid in), or when that last frame itself had just moved it (less than MOVE_MS before the
 * press: the person aimed at what was there a frame earlier). A row that held still from the frame before the press
 * to the hit test has stopped, however much an earlier frame moved it.
 */
export function rowMoving(frames: readonly RowFrame[], press: number, live: number, sliding: boolean): boolean {
  if (sliding) return true;
  const seen = frames.filter((f) => f.at <= press);
  const last = seen[seen.length - 1];
  // no frame of this slide before the press: the person saw the row where it was before the slide
  if (!last) return true;
  if (Math.abs(live - last.x0) > 1) return true;
  const prev = seen[seen.length - 2];
  return !!prev && press - last.at <= MOVE_MS && Math.abs(last.x0 - prev.x0) > 1;
}
