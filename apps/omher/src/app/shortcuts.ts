// App-wide keyboard shortcuts. ⌘ on macOS, Ctrl elsewhere:
//   ⌘1…⌘9  open bot 1 to 9 (sidebar order)      ⌘K  focus the bot search
//   ⌘.     show or hide Details                    ⌘,  Settings
//   ⌘J     jump to the next approval or question waiting on you (any bot or SESSIONS chat)
//   ⌘⇧G   maximise the side panel in place, or restore it (Esc restores; a closed panel opens on Plans)
//   ⌘N ⌘T  the TERMINALS + menu (Shell or a CLI, in a terminal)
//   ⌘⇧]    the next terminal session (sidebar order, wrapping)  ⌘⇧[  the previous one
//   Esc    stop the running answer (only when no popover, field or dialog wants Esc first)
//   Ctrl+` the bottom terminal panel, show or hide, on every OS (Ctrl on macOS too, as in VS Code; a maximised side
//          panel goes back to its own width first, so the terminal shows); taken before a
//          terminal sees it, so it works with the keyboard inside a terminal (it is omher's, not the program's)
// An approval card's own 1/2/3 keys live on the card (src/chat/cards), never here.
// None of these fire while an input method is composing (a Korean, Japanese or Chinese word not yet committed).
import { getFolderPrefs, orderFolders } from "../sessions/folders";
import { useEffect } from "react";
import { getStore, selectAsks, selectSidebarBots, type Ask, type FocusAsk } from "../state/store";
import { getSessions } from "../sessions/sessions";
import { openNewSessionMenu } from "../sessions/newMenu";
import { SESSIONS_ENTRY } from "../sessions/entry";
import { isTerminalRec, termGroups } from "../sessions/agents";
import { composing } from "../lib/ime";
import { getTermPanel, toggleTerminal } from "../terminal/state";

export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** `letter` on a Latin layout; on a non-Latin one (Korean, Japanese, Russian...) the key that stands where it does. */
const isLetter = (e: { key: string; code?: string }, letter: string) =>
  e.key.toLowerCase() === letter || (!/^[a-z]$/i.test(e.key) && e.code === `Key${letter.toUpperCase()}`);

/** What a keydown means, or null. Pure so it can be tested without a DOM. */
export function shortcutFor(
  e: { key: string; code?: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean; isComposing?: boolean; keyCode?: number },
  mac: boolean,
): { kind: "bot"; index: number } | { kind: "session"; step: 1 | -1 } | { kind: "search" | "details" | "settings" | "stop" | "next-ask" | "graph" | "new-session" | "terminal" } | null {
  if (composing(e)) return null;
  // Ctrl+` on every OS: the key left of 1 by where it stands (a Korean or German layout prints another character there)
  if (e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey && (e.code === "Backquote" || (!e.code && e.key === "`"))) return { kind: "terminal" };
  const mod = mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  if (mod && e.shiftKey && !e.altKey && e.key.toLowerCase() === "g") return { kind: "graph" };
  // ⇧ turns ] into } on US layouts: the physical key decides, else the character
  if (mod && e.shiftKey && !e.altKey) {
    if (e.code === "BracketRight" || e.key === "]" || e.key === "}") return { kind: "session", step: 1 };
    if (e.code === "BracketLeft" || e.key === "[" || e.key === "{") return { kind: "session", step: -1 };
  }
  if (mod && !e.altKey && !e.shiftKey) {
    if (/^[1-9]$/.test(e.key)) return { kind: "bot", index: Number(e.key) - 1 };
    if (e.key.toLowerCase() === "k") return { kind: "search" };
    if (e.key === ".") return { kind: "details" };
    if (e.key === ",") return { kind: "settings" };
    if (e.key.toLowerCase() === "j") return { kind: "next-ask" };
    if (isLetter(e, "n") || (mac && isLetter(e, "t"))) return { kind: "new-session" };
  }
  if (e.key === "Escape" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) return { kind: "stop" };
  return null;
}

/** The session ⌘⇧] / ⌘⇧[ goes to from `current` (none open: the first, or the last going back), wrapping. */
export function stepSession(ids: string[], current: string | null, step: 1 | -1): string | null {
  if (!ids.length) return null;
  const at = current ? ids.indexOf(current) : -1;
  if (at < 0) return step === 1 ? ids[0] : ids[ids.length - 1];
  return ids[(at + step + ids.length) % ids.length];
}

/** The ask ⌘J goes to: the one after the last jumped-to (in age order), wrapping; the oldest first. */
export function nextAsk(asks: Ask[], last: FocusAsk | null): Ask | null {
  if (!asks.length) return null;
  const at = last ? asks.findIndex((a) => a.bot === last.bot && a.item.id === last.id) : -1;
  return asks[(at + 1) % asks.length];
}

const inTerminal = (t: EventTarget | null) => !!(t as HTMLElement | null)?.closest?.(".xterm");

/** Open the next (1) or previous (-1) terminal session in TERMINALS order: the folder groups as the sidebar shows them. */
function stepTerminal(step: 1 | -1) {
  const store = getStore();
  const s = store.getState();
  const ss = getSessions().getState();
  const ids = orderFolders(termGroups(ss.list.filter((r) => isTerminalRec(ss.agents, r))), getFolderPrefs().order).flatMap((g) => g.rows.map((r) => r.id));
  const to = stepSession(ids, s.ui.view === "session" ? s.ui.session : null, step);
  if (to) store.actions.openSession(to);
}

export function useShortcuts(): void {
  useEffect(() => {
    // Ctrl+` is taken on the way down, before a focused terminal (xterm stops the keys it handles) can claim it. The
    // panel lives under the chat column, which a maximised side panel hides: showing it restores the side panel first
    const onTerminalKey = (e: KeyboardEvent) => {
      const hit = shortcutFor(e, isMac());
      // Ctrl+Shift+] / [ on Windows and Linux: omher's own chord, which no shell needs; inside a terminal xterm would
      // take it (as Ctrl+] / Ctrl+[), so it is taken here first. Every other Ctrl+key in a terminal stays the program's
      if (hit?.kind === "session" && !isMac() && SESSIONS_ENTRY && inTerminal(e.target)) {
        e.preventDefault();
        e.stopPropagation();
        stepTerminal(hit.step);
        return;
      }
      if (hit?.kind !== "terminal") return;
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;
      const store = getStore();
      if (!getTermPanel().open && store.getState().ui.panelMax) store.actions.setPanelMax(false);
      toggleTerminal();
    };
    const onKey = (e: KeyboardEvent) => {
      const hit = shortcutFor(e, isMac());
      if (!hit || hit.kind === "terminal") return;
      if (!SESSIONS_ENTRY && (hit.kind === "new-session" || hit.kind === "session")) return;
      // In a terminal session, Ctrl+<key> belongs to the program (Ctrl+K kills a line); ⌘ on macOS stays ours.
      if (!isMac() && inTerminal(e.target)) return;
      const store = getStore();
      const s = store.getState();
      const a = store.actions;
      if (hit.kind === "stop") {
        // Esc belongs to whatever is open first (popover, search field, inline rename, a card's input).
        if (e.defaultPrevented) return;
        const t = e.target as HTMLElement | null;
        if (t && t.closest("input, [role=dialog], [role=menu], [role=listbox]")) return;
        // Esc in the bottom terminal panel is the shell's: it neither stops an answer nor closes the panel
        if (t && t.closest(".termpanel")) return;
        // a maximised panel goes back to its own width first (the chat behind it is inert anyway)
        if (s.ui.panelMax && s.ui.panelOpen) {
          e.preventDefault();
          a.setPanelMax(false);
          return;
        }
        const bot = s.selectedBot;
        if (s.ui.view === "chat" && bot && s.chats[bot]?.turn) {
          e.preventDefault();
          void a.interrupt();
        } else if (s.ui.view === "session" && s.ui.session) {
          // a SESSIONS chat: Esc is the agent's own interrupt (Claude Code `interrupt`, Codex `turn/interrupt`,
          // pi `abort`, Hermes `session.interrupt`)
          const key = getSessions().chatKey(s.ui.session);
          if (key && s.chats[key]?.turn) {
            e.preventDefault();
            void getSessions().interrupt(s.ui.session);
          }
        }
        return;
      }
      e.preventDefault();
      if (hit.kind === "graph") {
        // maximise the side panel in place, or restore it; a closed panel opens on Plans
        if (s.ui.panelMax && s.ui.panelOpen) a.setPanelMax(false);
        else if (s.selectedBot) {
          if (s.ui.view !== "chat") a.closeSettings();
          a.setPanelMax(true, s.ui.panelOpen ? undefined : "runs");
        }
      } else if (hit.kind === "bot") {
        const b = selectSidebarBots(s)[hit.index];
        if (b) void a.selectBot(b.name);
      } else if (hit.kind === "new-session") {
        openNewSessionMenu();
      } else if (hit.kind === "session") {
        stepTerminal(hit.step);
      } else if (hit.kind === "next-ask") {
        const n = nextAsk(selectAsks(s), s.ui.focusAsk);
        if (n) void a.jumpToAsk(n.bot, n.item.id);
      } else if (hit.kind === "search") {
        const el = document.querySelector<HTMLInputElement>('[data-testid="bot-search"]');
        el?.focus();
        el?.select();
      } else if (hit.kind === "details") {
        // a SESSIONS chat has its own panel (its Plans); anywhere else the bot's chat comes back first
        if (s.ui.view !== "chat" && s.ui.view !== "session") a.closeSettings();
        a.togglePanel();
      } else if (hit.kind === "settings") {
        if (s.ui.view === "settings") a.closeSettings();
        else a.openSettings();
      }
    };
    window.addEventListener("keydown", onTerminalKey, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onTerminalKey, true);
      window.removeEventListener("keydown", onKey);
    };
  }, []);
}
