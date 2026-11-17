// The foreground CLI of a terminal's program, from the shell's `session-fg` event (src-tauri/src/lib.rs
// `watch_foreground`: `{ id, agent }`, sent for every pty session — TERMINALS rows and the bottom panel's shells —
// only when it changes, and once with null when a session that showed an agent ends). One listener for the page;
// each terminal registers its pty id. In a plain browser (dev, e2e against the mock bridge) there is no shell, so
// `window.__omherEmitSessionFg({ id, agent })` sends the same payload.

export interface SessionFg {
  id: number;
  agent: string | null;
}

/** The mock hosts' pty ids: one sequence for TERMINALS and the bottom panel, as the shell's own (one `Sessions`
 *  table numbers both), so a `session-fg` id names one terminal. */
let mockPty = 0;
export const nextMockPty = (): number => ++mockPty;
/** The mock hosts' running ptys: what prints into each (e2e seeds a terminal's screen through it). */
const mockOut = new Map<number, (d: string) => void>();
export function mockPtyOut(id: number, out: ((d: string) => void) | null): void {
  if (out) mockOut.set(id, out);
  else mockOut.delete(id);
}

type Handler = (agent: string | null) => void;

const handlers = new Map<number, Handler>();
/** Events for an id nobody registered yet (the start call's reply can arrive after the first event). */
const early = new Map<number, string | null>();
const EARLY_MAX = 64;
let listening = false;

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Hand one event to the terminal that owns its pty id. */
export function dispatchSessionFg(p: SessionFg): void {
  if (!p || typeof p.id !== "number") return;
  const agent = typeof p.agent === "string" && p.agent ? p.agent : null;
  const h = handlers.get(p.id);
  if (h) return h(agent);
  early.set(p.id, agent);
  if (early.size > EARLY_MAX) early.delete(early.keys().next().value as number);
}

function listen(): void {
  if (listening) return;
  listening = true;
  if (!inTauri()) return;
  void import("@tauri-apps/api/event")
    .then(({ listen: on }) => on<SessionFg>("session-fg", (e) => dispatchSessionFg(e.payload)))
    .catch(() => {
      listening = false;
    });
}

/** Follow pty session `id`'s foreground CLI; returns what stops following it. */
export function onSessionFg(id: number, fn: Handler): () => void {
  listen();
  handlers.set(id, fn);
  if (early.has(id)) {
    const agent = early.get(id) ?? null;
    early.delete(id);
    fn(agent);
  }
  return () => {
    if (handlers.get(id) === fn) handlers.delete(id);
    early.delete(id);
  };
}

// e2e / dev (mock host only): send the shell's event by hand
// and print into a mock pty (`__omherMockOut(id, text)`), as its program would
if (typeof window !== "undefined" && !inTauri()) {
  const w = window as unknown as { __omherEmitSessionFg?: (p: SessionFg) => void; __omherMockOut?: (id: number, d: string) => boolean };
  w.__omherEmitSessionFg = dispatchSessionFg;
  w.__omherMockOut = (id, d) => {
    const out = mockOut.get(id);
    out?.(d);
    return !!out;
  };
}
