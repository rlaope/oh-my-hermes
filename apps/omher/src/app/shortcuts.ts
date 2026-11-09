// App-wide keyboard shortcuts. ⌘ on macOS, Ctrl elsewhere:
//   ⌘1…⌘9  open bot 1 to 9 (sidebar order)      ⌘K  focus the bot search
//   ⌘.     show or hide Details                    ⌘,  Settings
//   Esc    stop the running answer (only when no popover, field or dialog wants Esc first)
import { useEffect } from "react";
import { getStore } from "../state/store";

export const isMac = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** What a keydown means, or null. Pure so it can be tested without a DOM. */
export function shortcutFor(
  e: { key: string; metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean },
  mac: boolean,
): { kind: "bot"; index: number } | { kind: "search" | "details" | "settings" | "stop" } | null {
  const mod = mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  if (mod && !e.altKey && !e.shiftKey) {
    if (/^[1-9]$/.test(e.key)) return { kind: "bot", index: Number(e.key) - 1 };
    if (e.key.toLowerCase() === "k") return { kind: "search" };
    if (e.key === ".") return { kind: "details" };
    if (e.key === ",") return { kind: "settings" };
  }
  if (e.key === "Escape" && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) return { kind: "stop" };
  return null;
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
        }
        return;
      }
      e.preventDefault();
      if (hit.kind === "bot") {
        const b = s.bots[hit.index];
        if (b) void a.selectBot(b.name);
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
