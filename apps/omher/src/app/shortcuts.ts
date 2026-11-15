// App-wide keyboard shortcuts. ⌘ on macOS, Ctrl elsewhere:
//   ⌘1…⌘9  open bot 1 to 9 (sidebar order)      ⌘K  focus the bot search
//   ⌘.     show or hide Details                    ⌘,  Settings
//   ⌘J     jump to the next approval or question waiting on you (any bot or SESSIONS chat)
//   ⌘⇧G   the Runs graph at full size (Esc closes it)
//   ⌘N ⌘T  the SESSIONS + menu (pick an agent for a New session)
//   ⌘⇧]    the next session (sidebar order, wrapping)          ⌘⇧[  the previous session
//   Esc    stop the running answer (only when no popover, field or dialog wants Esc first)
//   Ctrl+` the bottom terminal panel, show or hide, on every OS (Ctrl on macOS too, as in VS Code); taken before a
//          terminal sees it, so it works with the keyboard inside a terminal (it is omher's, not the program's)
// An approval card's own 1/2/3 keys live on the card (src/chat/cards), never here.
// None of these fire while an input method is composing (a Korean, Japanese or Chinese word not yet committed).
import { useEffect } from "react";
import { getStore, selectAsks, selectSidebarBots, type Ask, type FocusAsk } from "../state/store";
import { getSessions } from "../sessions/sessions";
import { openNewSessionMenu } from "../sessions/newMenu";
import { composing } from "../lib/ime";
import { toggleTerminal } from "../terminal/state";

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

export function useShortcuts(): void {
  useEffect(() => {
    // Ctrl+` is taken on the way down, before a focused terminal (xterm stops the keys it handles) can claim it
    const onTerminalKey = (e: KeyboardEvent) => {
      if (shortcutFor(e, isMac())?.kind !== "terminal") return;
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) toggleTerminal();
    };
    const onKey = (e: KeyboardEvent) => {
      const hit = shortcutFor(e, isMac());
      if (!hit || hit.kind === "terminal") return;
      // In a terminal session, Ctrl+<key> belongs to the program (Ctrl+K kills a line); ⌘ on macOS stays ours.
      if (!isMac() && (e.target as HTMLElement | null)?.closest?.(".xterm")) return;
      const store = getStore();
      const s = store.getState();
      const a = store.actions;
      if (hit.kind === "stop") {
        // Esc belongs to whatever is open first (popover, search field, inline rename, a card's input).
        if (e.defaultPrevented) return;
        if (s.ui.runsFull) {
          e.preventDefault();
          a.setRunsFull(false);
          return;
        }
        const t = e.target as HTMLElement | null;
        if (t && t.closest("input, [role=dialog], [role=menu], [role=listbox]")) return;
        // Esc in the bottom terminal panel is the shell's: it neither stops an answer nor closes the panel
        if (t && t.closest(".termpanel")) return;
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
        if (s.ui.runsFull) a.setRunsFull(false);
        else if (s.selectedBot) {
          if (s.ui.view !== "chat") a.closeSettings();
          a.setRunsFull(true);
        }
      } else if (hit.kind === "bot") {
        const b = selectSidebarBots(s)[hit.index];
        if (b) void a.selectBot(b.name);
      } else if (hit.kind === "new-session") {
        openNewSessionMenu();
      } else if (hit.kind === "session") {
        const ids = getSessions()
          .getState()
          .list.map((r) => r.id);
        const to = stepSession(ids, s.ui.view === "session" ? s.ui.session : null, hit.step);
        if (to) a.openSession(to);
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
