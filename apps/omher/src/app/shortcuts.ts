// App-wide keyboard shortcuts. ⌘ on macOS, Ctrl elsewhere:
//   ⌘1…⌘9  open bot 1 to 9 (sidebar order)      ⌘K  focus the bot search
//   ⌘.     show or hide Details                    ⌘,  Settings
//   ⌘J     jump to the next approval or question waiting on you (any bot)
//   Esc    stop the running answer (only when no popover, field or dialog wants Esc first)
// An approval card's own 1/2/3 keys live on the card (src/chat/cards), never here.
import { useEffect } from "react";
import { getStore, selectAsks, selectSidebarBots, type Ask, type FocusAsk } from "../state/store";
import { getSessions } from "../sessions/sessions";

export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** What a keydown means, or null. Pure so it can be tested without a DOM. */
export function shortcutFor(
  e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean },
  mac: boolean,
): { kind: "bot"; index: number } | { kind: "search" | "details" | "settings" | "stop" | "next-ask" } | null {
  const mod = mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  if (mod && !e.altKey && !e.shiftKey) {
    if (/^[1-9]$/.test(e.key)) return { kind: "bot", index: Number(e.key) - 1 };
    if (e.key.toLowerCase() === "k") return { kind: "search" };
    if (e.key === ".") return { kind: "details" };
    if (e.key === ",") return { kind: "settings" };
    if (e.key.toLowerCase() === "j") return { kind: "next-ask" };
  }
  if (e.key === "Escape" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) return { kind: "stop" };
  return null;
}

/** The ask ⌘J goes to: the one after the last jumped-to (in age order), wrapping; the oldest first. */
export function nextAsk(asks: Ask[], last: FocusAsk | null): Ask | null {
  if (!asks.length) return null;
  const at = last ? asks.findIndex((a) => a.bot === last.bot && a.item.id === last.id) : -1;
  return asks[(at + 1) % asks.length];
}

export function useShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const hit = shortcutFor(e, isMac());
      if (!hit) return;
      // In a terminal session, Ctrl+<key> belongs to the program (Ctrl+K kills a line); ⌘ on macOS stays ours.
      if (!isMac() && (e.target as HTMLElement | null)?.closest?.(".xterm")) return;
      const store = getStore();
      const s = store.getState();
      const a = store.actions;
      if (hit.kind === "stop") {
        // Esc belongs to whatever is open first (popover, search field, inline rename, a card's input).
        if (e.defaultPrevented) return;
        const t = e.target as HTMLElement | null;
        if (t && t.closest("input, [role=dialog], [role=menu], [role=listbox]")) return;
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
      if (hit.kind === "bot") {
        const b = selectSidebarBots(s)[hit.index];
        if (b) void a.selectBot(b.name);
      } else if (hit.kind === "next-ask") {
        const n = nextAsk(selectAsks(s), s.ui.focusAsk);
        if (n) void a.jumpToAsk(n.bot, n.item.id);
      } else if (hit.kind === "search") {
        const el = document.querySelector<HTMLInputElement>('input[aria-label="Search bots"]');
        el?.focus();
        el?.select();
      } else if (hit.kind === "details") {
        if (s.ui.view !== "chat") a.closeSettings();
        a.togglePanel();
      } else if (hit.kind === "settings") {
        if (s.ui.view === "settings") a.closeSettings();
        else a.openSettings();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
