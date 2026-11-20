// Two Settings › General choices that reach the shell (src-tauri tray.rs, power.rs):
// - "When the window closes": keep omher running in the menu bar / notification area (default) or quit. The shell
//   hides the window on its close while this is on; the first time it does, one notification says omher still runs.
// - "Keep the computer awake while agents work" (default on): while a TERMINALS agent printed in the last few seconds
//   or a bot turn runs, the page says busy; the shell holds an idle-sleep assertion until a minute after it says idle.
//   Only edges go to the shell (busy at once, idle after a quiet spell), never one call per output.
import { t } from "../i18n";

const CLOSE_KEY = "omher.window.close";
const AWAKE_KEY = "omher.awake";
const HIDDEN_NOTED_KEY = "omher.window.hiddenNoted";

function read(key: string): string | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, v: string): void {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* no storage */
  }
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** The window's close hides omher to the tray (on unless the person chose Quit). */
export const closeHides = (): boolean => read(CLOSE_KEY) !== "quit";
/** Keep the computer awake while agents work (on unless turned off). */
export const awakeEnabled = (): boolean => read(AWAKE_KEY) !== "off";

/** The tray menu's labels in the page's language. */
const trayLabels = () => ({ open: t("tray.open"), quit: t("tray.quit") });

/** Tell the shell whether the close hides the window (and the tray's labels). The mock records it. */
export async function sendWindowPrefs(): Promise<void> {
  const prefs = { hide: closeHides(), ...trayLabels() };
  if (!inTauri()) {
    (window as unknown as { __omherWindowPrefs?: typeof prefs[] }).__omherWindowPrefs ??= [];
    (window as unknown as { __omherWindowPrefs: typeof prefs[] }).__omherWindowPrefs.push(prefs);
    return;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("window_prefs", prefs).catch(() => undefined);
}

export function setCloseHides(on: boolean): void {
  write(CLOSE_KEY, on ? "tray" : "quit");
  void sendWindowPrefs();
}

// ---- busy edges ------------------------------------------------------------------------------

/** Idle is sent only after this long without work (a pause between two outputs is not an edge). */
export const QUIET_MS = 5_000;

/** Turns a busy/idle reading taken now and then into edges: busy at once, idle once it held for `quietMs`. Pure:
 *  the caller passes the clock. */
export function createEdges(send: (busy: boolean) => void, quietMs = QUIET_MS) {
  let sent = false;
  let idleSince: number | null = null;
  return {
    update(busy: boolean, now: number) {
      if (busy) {
        idleSince = null;
        if (!sent) send((sent = true));
        return;
      }
      if (!sent) return;
      idleSince ??= now;
      if (now - idleSince >= quietMs) {
        idleSince = null;
        send((sent = false));
      }
    },
    /** Forget what was sent (the setting went off and the shell let go). */
    reset() {
      sent = false;
      idleSince = null;
    },
    get sent() {
      return sent;
    },
  };
}

/** An agent printed this recently: it is working. */
export const WORK_MS = 5_000;

/** Whether anything works now: a TERMINALS agent (its own or one started in a Shell) printed within `workMs`, or
 *  reports progress, or a bot turn runs. */
export function working(
  terms: { agent: boolean; running: boolean; lastOut?: number; progress?: boolean }[],
  botTurn: boolean,
  now: number,
  workMs = WORK_MS,
): boolean {
  return botTurn || terms.some((r) => r.agent && r.running && (!!r.progress || (!!r.lastOut && now - r.lastOut < workMs)));
}

let started = false;
let edges: ReturnType<typeof createEdges> | null = null;
let sendBusy: ((busy: boolean, now?: boolean) => void) | null = null;

export function setAwakeEnabled(on: boolean): void {
  write(AWAKE_KEY, on ? "on" : "off");
  if (!on && edges?.sent) {
    edges.reset();
    sendBusy?.(false, true);
  }
}

/** Start both (once per page): send the window setting, follow the language, read the work every POLL_MS, and show
 *  the one-time "still running" note the first time the close hides the window. */
export async function startPower(): Promise<void> {
  if (started || typeof window === "undefined") return;
  started = true;
  const [{ getSessions }, { termActs }, { isShell, isTerminalRec }, { getStore }, { getHost }] = await Promise.all([
    import("../sessions/sessions"),
    import("../sessions/termActivity"),
    import("../sessions/agents"),
    import("../state/store"),
    import("../sessions/host"),
  ]);
  void sendWindowPrefs();
  let lang = getStore().getState().ui.lang;
  getStore().subscribe(() => {
    const l = getStore().getState().ui.lang;
    if (l !== lang) {
      lang = l;
      void sendWindowPrefs();
    }
  });

  const host = getHost();
  sendBusy = (busy, now) => void host.power?.(busy, now ?? false).catch(() => undefined);
  // e2e (mock host only) shortens the clock: `window.__omherPowerTiming = { poll, work, quiet }`
  const timing = (!inTauri() && (window as unknown as { __omherPowerTiming?: { poll?: number; work?: number; quiet?: number } }).__omherPowerTiming) || {};
  const poll = timing.poll ?? 2_000;
  const workMs = timing.work ?? WORK_MS;
  edges = createEdges((b) => sendBusy?.(b), timing.quiet ?? QUIET_MS);
  setInterval(() => {
    if (!awakeEnabled()) return;
    const now = Date.now();
    const ss = getSessions().getState();
    const terms = ss.list
      .filter((r) => isTerminalRec(ss.agents, r))
      .map((r) => {
        const a = termActs.get(r.id);
        return { agent: !!r.fgAgent || !isShell(r.agent), running: r.status === "running", lastOut: a.lastOut, progress: a.progress };
      });
    const botTurn = getStore().getState().bots.some((b) => b.running);
    edges?.update(working(terms, botTurn, now, workMs), now);
  }, poll);

  if (inTauri()) {
    const { listen } = await import("@tauri-apps/api/event");
    void listen("window-hidden", () => void onWindowHidden());
  } else {
    (window as unknown as { __omherWindowHidden?: () => Promise<void> }).__omherWindowHidden = onWindowHidden;
  }
}

/** The close hid the window: the first time ever, one notification says where omher went. */
export async function onWindowHidden(): Promise<void> {
  if (read(HIDDEN_NOTED_KEY)) return;
  write(HIDDEN_NOTED_KEY, "1");
  const { showNote } = await import("./notify");
  await showNote({ title: t("tray.stillTitle"), body: t(isMacPlatform() ? "tray.stillBodyMac" : "tray.stillBody"), bot: "", tag: "omher:hidden" });
}

export const isMacPlatform = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
