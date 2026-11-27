// The text a terminal showed before omher restarted (history.ts) is omher's, not the program's: it stays selectable
// with a plain drag even while the new program has the mouse. A TUI that turns mouse reporting on (Antigravity CLI
// and other full-window agents do) makes xterm send every click and drag to it, and xterm then selects only with a
// modifier held (Shift; Option on macOS with `macOptionClickForcesSelection`), so the restored lines above the divider
// could not be selected or copied at all. A press on one of those lines now selects as a forced selection does; a
// press anywhere below the divider goes to the program as before.
//
// xterm has no public hook for this, so it wraps one member of xterm 6's SelectionService
// (`_core._selectionService.shouldForceSelection`), which both its mouse service (to hold the press back from the
// program) and its selection service (to start a selection) ask. When that member is not there (another xterm),
// nothing is changed. engine-restored.test.ts fails when it is gone, so an xterm bump is noticed.
import type { IMarker, Terminal } from "@xterm/xterm";

interface SelectionService {
  shouldForceSelection(event: MouseEvent): boolean;
}

/** The terminal's selection service when it has the shape this needs, else null (not opened yet, or another xterm). */
export function selectionServiceOf(term: Terminal): SelectionService | null {
  const ss = (term as unknown as { _core?: { _selectionService?: Partial<SelectionService> } })._core?._selectionService;
  return ss && typeof ss.shouldForceSelection === "function" ? (ss as SelectionService) : null;
}

/** The last restored line of each terminal (the divider's), moving with the buffer as it scrolls and trims. */
const ends = new WeakMap<Terminal, IMarker>();
const wrapped = new WeakSet<Terminal>();

/** The buffer line of the divider under the restored text, or -1 when it has none (never had, or trimmed away). */
export function restoredEnd(term: Terminal): number {
  const m = ends.get(term);
  return m && !m.isDisposed && m.line >= 0 ? m.line : -1;
}

/** The normal buffer's line under a mouse event, or null when it is not over the rows. */
function lineAt(term: Terminal, ev: MouseEvent): number | null {
  const screen = term.element?.querySelector(".xterm-screen");
  if (!screen || !term.rows) return null;
  const r = screen.getBoundingClientRect();
  if (r.height <= 0 || ev.clientY < r.top || ev.clientY >= r.bottom) return null;
  const row = Math.floor(((ev.clientY - r.top) / r.height) * term.rows);
  return term.buffer.active.viewportY + row;
}

/** Whether a press at `ev` lands on the restored text: the main screen shows and the row is at or above the divider. */
export function onRestored(term: Terminal, ev: MouseEvent): boolean {
  const end = restoredEnd(term);
  if (end < 0 || term.buffer.active.type !== "normal") return false;
  const line = lineAt(term, ev);
  return line !== null && line <= end;
}

/** The restored text and its divider were just written into `term` (history.ts `restoredText`: the divider ends with
 *  a line break, so the cursor sits on the line after it, where the new program's output starts): from here on a press
 *  on the divider's line or above selects, whatever mode the program puts the mouse in. `line`: the buffer line to mark
 *  instead (a parked terminal made again). False when xterm's shape is not the one this knows (nothing was changed). */
export function markRestored(term: Terminal, line?: number): boolean {
  const ss = selectionServiceOf(term);
  if (!ss) return false;
  const b = term.buffer.active;
  const at = line ?? b.baseY + b.cursorY - 1;
  if (at < 0) return false;
  const m = term.registerMarker(at - (b.baseY + b.cursorY));
  if (!m) return false;
  ends.get(term)?.dispose();
  ends.set(term, m);
  if (!wrapped.has(term)) {
    wrapped.add(term);
    const own = ss.shouldForceSelection.bind(ss);
    ss.shouldForceSelection = (ev: MouseEvent) => own(ev) || onRestored(term, ev);
  }
  return true;
}
