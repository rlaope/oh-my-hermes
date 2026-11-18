// A terminal that is not on the page draws nothing. xterm pauses its own row renders while its element is out of
// view (an IntersectionObserver), but not the selection's: every time output scrolls the buffer, its selection
// service asks for a redraw on the next frame, and the render service hands that straight to the renderer, which
// redraws every row (the DOM renderer's `createRow`/`_measure`) whether the terminal is paused or not. With many
// sessions printing in the background that is most of the page's xterm work for screens nobody sees.
//
// xterm has no public way to turn that off, so this touches one internal member of xterm 6's RenderService, after
// checking it is there; where it is not (another xterm), nothing is changed and xterm behaves as it always did.
// engine-hidden.test.ts fails when the members are gone, so an xterm bump is noticed.
//
// While hidden, a selection redraw only keeps the selection (as xterm does) and marks it owed. When the terminal is
// shown again it is redrawn once, selection included, by the render service's own next refresh. Parsing, the write
// callback (the flow-control credit), bells and OSC handlers never pass through here.
import type { Terminal } from "@xterm/xterm";

/** The parts of xterm 6's RenderService (`_core._renderService`) this relies on. */
interface RenderService {
  /** where the selection service's redraw lands; the renderer then redraws every row */
  handleSelectionChanged(start: unknown, end: unknown, columnSelectMode: boolean): void;
  /** what the renderer draws as the selection */
  _selectionState: { start: unknown; end: unknown; columnSelectMode: boolean };
  /** set: the next row render also gives the renderer the selection (xterm does this for a new renderer) */
  _needsSelectionRefresh: boolean;
}

/** The terminal's render service when it has the shape this needs, else null (not opened yet, or another xterm). */
export function renderServiceOf(term: Terminal): RenderService | null {
  const rs = (term as unknown as { _core?: { _renderService?: Partial<RenderService> } })._core?._renderService;
  if (!rs || typeof rs.handleSelectionChanged !== "function" || typeof rs._needsSelectionRefresh !== "boolean") return null;
  const sel = rs._selectionState;
  if (!sel || typeof sel !== "object" || !("start" in sel) || !("end" in sel) || !("columnSelectMode" in sel)) return null;
  return rs as RenderService;
}

interface Quiet {
  rs: RenderService;
  /** the member as it was on the instance (xterm keeps it on the prototype: none) */
  own: RenderService["handleSelectionChanged"] | null;
  /** a selection redraw that changes the screen was held back (one with a selection, or one clearing it) */
  owed: boolean;
}

const quiet = new WeakMap<Terminal, Quiet>();

/** The terminal left the page: selection redraws are held until it is shown. False when xterm's shape is not the
 *  one this knows (nothing was changed). */
export function hideRows(term: Terminal): boolean {
  if (quiet.has(term)) return true;
  const rs = renderServiceOf(term);
  if (!rs) return false;
  const q: Quiet = { rs, own: Object.prototype.hasOwnProperty.call(rs, "handleSelectionChanged") ? rs.handleSelectionChanged : null, owed: false };
  // with no selection on the screen and none made meanwhile, the rows' own refresh on show is all there is to draw
  const had = !!(rs._selectionState.start && rs._selectionState.end);
  rs.handleSelectionChanged = (start, end, columnSelectMode) => {
    rs._selectionState.start = start;
    rs._selectionState.end = end;
    rs._selectionState.columnSelectMode = columnSelectMode;
    if (had || (start && end)) q.owed = true;
  };
  quiet.set(term, q);
  return true;
}

/** The terminal is on the page again: selection redraws go through, and one that was held is drawn with the next
 *  refresh (when xterm's own pause lets it, which also draws what was printed meanwhile). */
export function showRows(term: Terminal): void {
  const q = quiet.get(term);
  if (!q) return;
  quiet.delete(term);
  if (q.own) q.rs.handleSelectionChanged = q.own;
  else delete (q.rs as Partial<RenderService>).handleSelectionChanged;
  if (!q.owed) return;
  q.rs._needsSelectionRefresh = true;
  try {
    term.refresh(0, term.rows - 1);
  } catch {
    /* disposed meanwhile */
  }
}
