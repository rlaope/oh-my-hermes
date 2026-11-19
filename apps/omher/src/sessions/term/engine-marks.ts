// What a shell or CLI tells its terminal about itself by its own escapes. omher puts no hook into the shell; these
// come only from programs that already send them (fish, zsh prompt themes, Codex, Claude Code). Three are read, and
// nothing in them is kept beyond what is said here or sent anywhere:
//
// - OSC 133 (FinalTerm marks `A` prompt, `B` command, `C` output, `D[;exit]` finished): the buffer line each prompt
//   starts on (an xterm marker, gone when that line leaves the scrollback) and whether its command ended non-zero. A
//   thin mark is drawn beside each prompt (red after a failed command), and Cmd+Up / Cmd+Down (Cmd+PageUp /
//   Cmd+PageDown) move the view to the previous / next prompt. A terminal that sent no marks keeps those keys as they
//   were.
// - OSC 7 (`file://host/path`): the folder the shell is in now, only from a `file://` address on this computer (an
//   empty host, `localhost` or this computer's name) with an absolute path. Only the path is read.
// - OSC 9;4 (ConEmu progress `4;state;percent`): working (states 1, 2, 3) or done (0). No text is read.
import type { IDecoration, IMarker, Terminal } from "@xterm/xterm";
import "./marks.css";

/** One OSC 133 mark: its letter, and for `D` the exit code when it carries one. */
export interface Mark133 {
  kind: "A" | "B" | "C" | "D";
  exit: number | null;
}

/** The OSC 133 payload (`A`, `B`, `C`, `D`, `D;1`, `A;k=i`...), or null for one this does not read. */
export function parse133(data: string): Mark133 | null {
  const [kind, second] = data.split(";");
  if (kind !== "A" && kind !== "B" && kind !== "C" && kind !== "D") return null;
  const exit = kind === "D" && second !== undefined && /^-?\d{1,10}$/.test(second) ? Number(second) : null;
  return { kind, exit };
}

/** Longest OSC 7 payload read (a path is far shorter). */
const OSC7_MAX = 4096;

/** The folder an OSC 7 payload names, or null: a `file://` address whose host is empty, `localhost` or one of
 *  `thisHost` (any case, a trailing dot ignored), percent-decoded, absolute, with no control characters. A Windows
 *  path (`file:///C:/x`) comes back as `C:/x`. */
export function parseOsc7(data: string, thisHost: readonly string[] = []): string | null {
  if (data.length > OSC7_MAX || data.slice(0, 7).toLowerCase() !== "file://") return null;
  const rest = data.slice(7);
  const slash = rest.indexOf("/");
  if (slash < 0) return null;
  const host = norm(rest.slice(0, slash));
  if (host && host !== "localhost" && !thisHost.some((h) => norm(h) === host)) return null;
  let path: string;
  try {
    path = decodeURIComponent(rest.slice(slash));
  } catch {
    return null; // a broken %-escape
  }
  if (/[\x00-\x1f\x7f]/.test(path)) return null;
  if (/^\/[A-Za-z]:[\\/]/.test(path)) path = path.slice(1);
  return path.startsWith("/") || /^[A-Za-z]:[\\/]/.test(path) ? path : null;
}

const norm = (h: string) => h.toLowerCase().replace(/\.$/, "");

/** An OSC 9 payload as progress (`4;st[;pr]`): `busy` for states 1 (normal), 2 (error), 3 (indeterminate), `done`
 *  for 0, null for anything else (a notification message, a state this does not read). */
export function parseProgress(data: string): "busy" | "done" | null {
  const m = /^4;(\d)(?:;\d{0,3})?$/.exec(data);
  if (!m) return null;
  return m[1] === "0" ? "done" : m[1] === "1" || m[1] === "2" || m[1] === "3" ? "busy" : null;
}

/** The prompt to move to from line `from`: the nearest one above (`dir` -1) or below (+1), or null. */
export function nextPrompt(lines: readonly number[], from: number, dir: -1 | 1): number | null {
  let best: number | null = null;
  for (const l of lines) {
    if (dir < 0 ? l < from && (best === null || l > best) : l > from && (best === null || l < best)) best = l;
  }
  return best;
}

interface Mark {
  marker: IMarker;
  deco: IDecoration | undefined;
  /** the exit code its command's `D` carried, null until then (or when it carried none) */
  exit: number | null;
}

interface State {
  marks: Mark[];
  /** a `C` came since the last prompt: the next `D` is that command's end */
  ran: boolean;
  /** where the last jump went and the view top it left, so a jump the scroll could not fully make goes on from it */
  last: { line: number; top: number } | null;
}

const states = new Map<Terminal, State>();

/** This computer's own names: OSC 7 from these counts as local. Set by whoever learns them (none yet: until then
 *  only an empty host and `localhost` count). */
let thisHost: string[] = [];
export function setThisHost(names: readonly string[]): void {
  thisHost = names.filter((n) => typeof n === "string" && !!n.trim()).map((n) => n.trim());
}

const paint = (el: HTMLElement, m: Mark) => {
  el.classList.add("term-mark");
  el.classList.toggle("err", m.exit !== null && m.exit !== 0);
};

function onMark(term: Terminal, s: State, data: string): void {
  const m = parse133(data);
  const b = term.buffer.active;
  if (!m || b.type !== "normal") return; // a full-screen program's screen keeps no prompts
  if (m.kind === "C") s.ran = true;
  else if (m.kind === "D") {
    const last = s.marks.at(-1);
    if (last && s.ran && m.exit !== null) {
      last.exit = m.exit;
      if (last.deco?.element) paint(last.deco.element, last);
    }
    s.ran = false;
  } else if (m.kind === "A") {
    s.ran = false;
    const line = b.baseY + b.cursorY;
    if (s.marks.at(-1)?.marker.line === line) return;
    const marker = term.registerMarker(0);
    if (!marker) return;
    const deco = term.registerDecoration({ marker, anchor: "left", x: 0, width: 1 });
    const mark: Mark = { marker, deco, exit: null };
    deco?.onRender((el) => paint(el, mark));
    // its line left the scrollback: the mark goes with it
    marker.onDispose(() => {
      const i = s.marks.indexOf(mark);
      if (i >= 0) s.marks.splice(i, 1);
      deco?.dispose();
    });
    s.marks.push(mark);
  }
}

/** The prompts terminal `term` was told of, oldest first: the buffer line each starts on and its command's exit
 *  code (null: not finished, or it said none). */
export function promptMarks(term: Terminal): { line: number; exit: number | null }[] {
  return (states.get(term)?.marks ?? []).filter((m) => !m.marker.isDisposed && m.marker.line >= 0).map((m) => ({ line: m.marker.line, exit: m.exit }));
}

/** Move `term`'s view to the previous (-1) or next (+1) prompt. False when it has no prompt marks (the key is then
 *  left to the terminal). */
export function jumpToPrompt(term: Terminal, dir: -1 | 1): boolean {
  const s = states.get(term);
  const b = term.buffer.active;
  const lines = promptMarks(term).map((m) => m.line);
  if (!s || !lines.length || b.type !== "normal") return false;
  const top = b.viewportY;
  // from the last jump while the view is still where it left it; at the bottom, upwards, from the cursor's line (the
  // prompt being typed at is not a place to go back to); else from the top of the view
  const from = s.last && s.last.top === top ? s.last.line : dir < 0 && top === b.baseY ? b.baseY + b.cursorY : top;
  const to = nextPrompt(lines, from, dir);
  if (to === null) {
    if (dir > 0) {
      term.scrollToBottom();
      s.last = null;
    }
    return true;
  }
  term.scrollToLine(to);
  s.last = { line: to, top: term.buffer.active.viewportY };
  return true;
}

const PREV = new Set(["ArrowUp", "PageUp"]);
const NEXT = new Set(["ArrowDown", "PageDown"]);

/** Sent (bubbling) on a terminal's element when its shell reports a folder that counts (OSC 7): `detail` is the path. */
export const CWD_EVENT = "omher-term-cwd";
/** Sent (bubbling) on a terminal's element when its program reports progress (OSC 9;4): `detail` is busy or done. */
export const PROGRESS_EVENT = "omher-term-progress";

/** The three escapes for one terminal (called once it is open, again for one made again after parking; `el` holds
 *  it and outlives a remake, so its owner listens there). Returns what undoes it. */
export function attachMarks(term: Terminal, el: HTMLElement): () => void {
  const s: State = { marks: [], ran: false, last: null };
  states.set(term, s);
  const tell = (type: string, detail: string) => el.dispatchEvent(new CustomEvent<string>(type, { bubbles: true, detail }));
  const handlers = [
    term.parser.registerOscHandler(133, (d) => {
      onMark(term, s, d);
      return true;
    }),
    term.parser.registerOscHandler(7, (d) => {
      const p = parseOsc7(d, thisHost);
      if (p) tell(CWD_EVENT, p);
      return true;
    }),
    // not consumed: an OSC 9 message is the owner's ring (sessions.ts), and a 9;4 report is never one
    term.parser.registerOscHandler(9, (d) => {
      const p = parseProgress(d);
      if (p) tell(PROGRESS_EVENT, p);
      return false;
    }),
  ];
  // ahead of xterm (capture on its parent): Cmd with an arrow or page key, and nothing else held
  const key = (e: KeyboardEvent) => {
    if (!e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.isComposing) return;
    const dir = PREV.has(e.key) ? -1 : NEXT.has(e.key) ? 1 : 0;
    if (!dir || !jumpToPrompt(term, dir)) return;
    e.preventDefault();
    e.stopPropagation();
  };
  el.addEventListener("keydown", key, true);
  return () => {
    for (const h of handlers) h.dispose();
    el.removeEventListener("keydown", key, true);
    for (const m of [...s.marks]) m.marker.dispose();
    states.delete(term);
  };
}

/** `fn` hears each folder the shell of the terminal in `el` reports (OSC 7) that counts. Returns what stops it. */
export function onCwd(el: HTMLElement, fn: (path: string) => void): () => void {
  const on = (e: Event) => fn((e as CustomEvent<string>).detail);
  el.addEventListener(CWD_EVENT, on);
  return () => el.removeEventListener(CWD_EVENT, on);
}

/** `fn` hears the program in the terminal in `el` report progress (OSC 9;4) as working or done. */
export function onProgress(el: HTMLElement, fn: (state: "busy" | "done") => void): () => void {
  const on = (e: Event) => fn((e as CustomEvent<"busy" | "done">).detail);
  el.addEventListener(PROGRESS_EVENT, on);
  return () => el.removeEventListener(PROGRESS_EVENT, on);
}
