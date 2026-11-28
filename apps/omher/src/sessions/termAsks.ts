// Terminal agents' asks: a Claude Code or Codex in a TERMINALS row that stopped on its permission dialog or a choice
// menu (term/screenAsk.ts reads it off the screen, sessions.ts reads on output). They join the bot asks wherever those
// show: the Needs-you strip and list, ⌘J, the Dock count and the row's mark. One per row at most; it leaves on the
// first read without it, when the row's program ends or the row closes, and all of them when the setting goes off.
import { useSyncExternalStore } from "react";
import { getStore, notifyEnabled, TERM_ASK } from "../state/store";
import { showNote, windowWatched } from "../lib/notify";
import { t } from "../i18n";
import { onTermSettings, readTermSettings } from "./term/settings";
import type { ScreenAskKind } from "./term/screenAsk";

export interface TermAsk {
  /** the TERMINALS row's session id */
  session: string;
  kind: ScreenAskKind;
  /** the program asking ("claude", "codex"): the list shows its mark */
  agent: string;
  /** one line, as the agent wrote it ("Bash command: touch probe.txt") */
  title: string;
  options: string[];
  /** who asks, as the list names it: "web-app · Claude Code" */
  name: string;
  /** seconds since epoch: when the dialog came up */
  ts: number;
  /** this dialog's own id (a new dialog in the same row gets a new one) */
  id: string;
}

const asks = new Map<string, TermAsk>();
const listeners = new Set<() => void>();
let list: TermAsk[] = [];
let seq = 0;

function changed() {
  list = [...asks.values()].sort((a, b) => a.ts - b.ts);
  for (const fn of listeners) fn();
}

/** Whether the setting lets terminal agents' dialogs show (Settings › Terminal). */
export const termAsksOn = () => readTermSettings().agentAsks;

/** Row `session` shows this dialog now (a new one, or the same one read again). Returns true when it is new. */
export function setTermAsk(session: string, a: Omit<TermAsk, "session" | "ts" | "id">): boolean {
  if (!termAsksOn()) return false;
  const was = asks.get(session);
  if (was && was.title === a.title && was.kind === a.kind && was.options.join("\n") === a.options.join("\n")) return false;
  asks.set(session, { ...a, session, ts: Date.now() / 1000, id: `term-ask-${++seq}` });
  changed();
  return true;
}

/** Row `session` no longer shows a dialog (answered, cancelled, its program ended, the row closed). */
export function clearTermAsk(session: string): void {
  if (asks.delete(session)) changed();
}

export const hasTermAsk = (session: string) => asks.has(session);

/** Every terminal ask, oldest first. */
export const termAsks = (): TermAsk[] => list;

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useTermAsks(): TermAsk[] {
  return useSyncExternalStore(subscribe, termAsks, termAsks);
}

/** Whether row `session` waits on the person: its own re-render only when that changes. */
export function useTermAsked(session: string): boolean {
  const get = () => asks.has(session);
  return useSyncExternalStore(subscribe, get, get);
}

/** The key an ask goes by in ⌘J's order and `jumpToAsk`: `term:<session>`. */
export const termAskKey = (session: string) => `${TERM_ASK}${session}`;

/** One notification for a new dialog, when omher's window is not in front. A click opens the row with the keyboard in
 *  its terminal. */
export function notifyTermAsk(a: TermAsk): void {
  if (!notifyEnabled() || windowWatched()) return;
  const note = { title: t("note.term.ask", { name: a.name }), body: a.title, bot: termAskKey(a.session), tag: `${a.session}:ask` };
  void showNote(note, () => void getStore().actions.jumpToAsk(termAskKey(a.session), a.id));
}

// the setting turned off: every ask leaves at once
onTermSettings((s) => {
  if (s.agentAsks || !asks.size) return;
  asks.clear();
  changed();
});
