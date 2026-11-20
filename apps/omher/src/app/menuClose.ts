// Close Window (⌘W) on macOS is omher's own menu item (src-tauri app_menu.rs): the shell sends `menu-close` and the
// page decides. A split pane with the keyboard (a TERMINALS split, or a bottom-panel tab of several panes) closes, as
// the ⌘W key in it does. A TERMINALS terminal on its own closes its session when that close can be undone (Settings ›
// Terminal › Undo window after closing; the toast brings it back), as a terminal app closes a tab, or when it has
// ended; anything else asks the shell to close the window, as the system item did (with the undo window Off, a running
// agent is not ended on ⌘W). A press that the page already took as a pane key does not close a second pane when the
// menu hears the same press.
import { getStore } from "../state/store";
import { closePane, getTermPanel } from "../terminal/state";
import { getSplit, groupOf, splitPaneOf } from "../sessions/splitState";

/** How long after a pane closed on the key the menu's Close counts as the same press. */
const SAME_PRESS_MS = 300;
let lastPaneClose = -Infinity;

/** A pane closed on the ⌘W key now (the menu may hear the same press). */
export function markPaneClosed(): void {
  lastPaneClose = performance.now();
}

const paneJustClosed = (): boolean => performance.now() - lastPaneClose < SAME_PRESS_MS;

// One press, one close: a held ⌘W repeats, and the menu hears every repeat. Without this each repeat would close the
// next session that comes to the front, then the window. While ⌘W stays down after it closed something, the menu's
// Close Window does nothing; letting go of W or ⌘ (or the window losing focus) ends the press.
const MENU_FIRST_MS = 60;
let wHeld = false;
let closedThisPress = false;
let lastMenuClose = -Infinity;
const isCloseKey = (e: KeyboardEvent) => e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey && (e.code === "KeyW" || e.key.toLowerCase() === "w");

function watchCloseKey(): void {
  addEventListener(
    "keydown",
    (e) => {
      if (!isCloseKey(e) || e.repeat) return;
      wHeld = true;
      // the menu may have heard this press a moment before the page did (a few ms; a second press is slower)
      closedThisPress = performance.now() - lastMenuClose < MENU_FIRST_MS;
    },
    true,
  );
  const up = (e: KeyboardEvent) => {
    if (e.key === "Meta" || e.code === "KeyW" || e.key.toLowerCase() === "w") wHeld = false;
  };
  addEventListener("keyup", up, true);
  addEventListener("blur", () => (wHeld = false));
}

type Target = { kind: "split"; session: string } | { kind: "session"; session: string } | { kind: "panel"; pane: number } | { kind: "window" };

/** What Close Window closes, from where the keyboard is: a TERMINALS split pane, a TERMINALS session, a bottom-panel
 *  pane, or the window. */
export function closeTarget(active: Element | null): Target {
  const panel = active?.closest?.(".termpanel");
  if (panel) {
    const p = getTermPanel();
    const tab = p.tabs.find((t) => t.key === p.active);
    if (p.open && tab && tab.panes.length > 1) return { kind: "panel", pane: tab.focus };
    return { kind: "window" };
  }
  const ui = getStore().getState().ui;
  // the pane that holds the keyboard, as the ⌘W key in it decides (not the pane last clicked)
  const at = ui.view === "session" ? splitPaneOf(active, ui.session) : null;
  if (at && groupOf(getSplit().groups, at)) return { kind: "split", session: at };
  // the open TERMINALS session's own terminal, with the keyboard
  const own = ui.view === "session" && ui.session ? active?.closest?.(`[data-testid="terminal"][data-session="${ui.session}"]`) : null;
  if (own && ui.session) return { kind: "session", session: ui.session };
  return { kind: "window" };
}

async function closeWindow(): Promise<void> {
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("window_close");
    return;
  }
  // the mock host: recorded for the tests
  const w = window as unknown as { __omherWindowCloses?: number };
  w.__omherWindowCloses = (w.__omherWindowCloses ?? 0) + 1;
}

/** The menu's Close Window was chosen (or ⌘W reached the menu). */
export async function onMenuClose(): Promise<void> {
  lastMenuClose = performance.now();
  if (wHeld && closedThisPress) return;
  if (wHeld) closedThisPress = true;
  if (paneJustClosed()) return;
  const to = closeTarget(document.activeElement);
  if (to.kind === "panel") closePane(to.pane);
  else if (to.kind === "split") {
    const { leaveSplit } = await import("../sessions/SplitView");
    leaveSplit(to.session);
  } else if (to.kind === "session") {
    const { closeLone } = await import("../sessions/SplitView");
    if (!closeLone(to.session)) await closeWindow();
  } else await closeWindow();
}

let listening = false;
/** Hear the shell's `menu-close` (once per page). The mock host gets `window.__omherMenuClose()` instead. */
export function listenMenuClose(): void {
  if (listening || typeof window === "undefined") return;
  listening = true;
  watchCloseKey();
  if (!("__TAURI_INTERNALS__" in window)) {
    (window as unknown as { __omherMenuClose?: () => Promise<void> }).__omherMenuClose = onMenuClose;
    return;
  }
  void import("@tauri-apps/api/event")
    .then(({ listen }) => listen("menu-close", () => void onMenuClose()))
    .catch(() => {
      listening = false;
    });
}
