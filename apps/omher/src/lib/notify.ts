// System notifications while omher is in the background: a bot finished its answer, needs an approval,
// or asked a question. Nothing fires while you are looking at that bot's chat. In the desktop app this
// goes through the Tauri notification plugin (macOS Notification Center, Windows toasts); in a plain
// browser (dev, e2e) through the Web Notification API.
import type { BridgeEvent } from "./protocol";
import { t } from "../i18n";

export interface Note {
  title: string;
  body: string;
  /** Which bot to open when the notification is clicked (browser build only). */
  bot: string;
  /** Collapse repeats of the same kind for the same bot. */
  tag: string;
}

const clip = (s: string, n = 140) => {
  const t = s.replace(/[`*_#>]+/g, "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};

/** The notification for `ev`, or null when there is nothing worth interrupting for. Pure: no globals. */
export function noteFor(
  ev: BridgeEvent,
  ctx: { name: (bot: string) => string; watching: (bot: string) => boolean },
): Note | null {
  const bot = ev.bot;
  if (!bot || ctx.watching(bot)) return null;
  const who = ctx.name(bot);
  switch (ev.event) {
    case "message":
      if (ev.watch) return ev.text.trim() ? watchNote(who, bot, ev.watch.name, ev.text) : null;
      return ev.text.trim() ? { title: who, body: clip(ev.text), bot, tag: `${bot}:message` } : null;
    case "approval.request":
      return {
        title: t("note.approval", { bot: who }),
        body: clip(ev.command || ev.title || t("ask.allowThis")),
        bot,
        tag: `${bot}:approval`,
      };
    case "clarify.request":
      return { title: t("note.question", { bot: who }), body: clip(ev.question), bot, tag: `${bot}:clarify` };
    case "turn.end":
      return ev.outcome === "error"
        ? { title: t("note.error", { bot: who }), body: clip(ev.error || t("note.failed")), bot, tag: `${bot}:error` }
        : null;
    default:
      return null;
  }
}

/** An automation's answer: "<bot> · <watch>", its first line. */
export function watchNote(who: string, bot: string, name: string, text: string): Note {
  const first = text.split("\n").find((l) => l.trim()) ?? text;
  return { title: `${who} · ${name}`, body: clip(first), bot, tag: `${bot}:watch` };
}

/** Answers that came in while omher was closed: one note for the bot, never one per answer. */
export function watchMissedNote(who: string, bot: string, rows: { text: string; watch?: { name: string } }[]): Note | null {
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  if (rows.length === 1) return watchNote(who, bot, last.watch?.name ?? "", last.text);
  return { title: t("note.watchMany", { bot: who, n: rows.length }), body: clip(last.text.split("\n")[0] ?? ""), bot, tag: `${bot}:watch` };
}

/** Something a SESSIONS session did that is not a chat event: its program ended, it could not start, or its
 *  terminal rang its bell. */
export interface SessionNote {
  kind: "ended" | "failed" | "bell";
  /** `web-app · Claude Code` */
  name: string;
  code?: number | null;
  error?: string;
}

/** The notification for `n` of session `id`. Pure: no globals. */
export function sessionNote(id: string, n: SessionNote): Note {
  const title = t(n.kind === "bell" ? "note.session.bell" : n.kind === "failed" ? "note.session.failed" : "note.session.ended", { name: n.name });
  const exit = typeof n.code === "number" && n.code !== 0 ? t("ss.endedExit", { code: n.code }) : "";
  const body = n.kind === "bell" ? t("note.session.bellBody") : clip(n.error || exit || t(n.kind === "failed" ? "ss.couldNotStart" : "note.session.endedBody"));
  return { title, body, bot: id, tag: `${id}:${n.kind}` };
}

const isTauri = () => !!(window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;

let granted: boolean | null = null;

async function permitted(): Promise<boolean> {
  if (granted !== null) return granted;
  try {
    if (isTauri()) {
      const n = await import("@tauri-apps/plugin-notification");
      granted = (await n.isPermissionGranted()) || (await n.requestPermission()) === "granted";
    } else if (typeof Notification !== "undefined") {
      granted = Notification.permission === "granted" || (await Notification.requestPermission()) === "granted";
    } else {
      granted = false;
    }
  } catch {
    granted = false;
  }
  return granted ?? false;
}

/** The bot to open when omher next gets focus after a desktop notification (the desktop plugin reports no click). */
let openOnFocus: (() => void) | null = null;
let focusHooked = false;
function armFocusOpen(open: () => void): void {
  openOnFocus = open;
  if (focusHooked || typeof window === "undefined") return;
  focusHooked = true;
  window.addEventListener("focus", () => {
    const fn = openOnFocus;
    openOnFocus = null;
    fn?.();
  });
}

/** Show `note`. `onClick` opens that bot's chat: on a click (browser build), or with `focusOpen` when the desktop app
 *  next gets focus after it was shown in the background. Never throws. */
export async function showNote(note: Note, onClick?: () => void, focusOpen = false): Promise<void> {
  if (!(await permitted())) return;
  try {
    if (isTauri()) {
      const n = await import("@tauri-apps/plugin-notification");
      n.sendNotification({ title: note.title, body: note.body });
      if (focusOpen && onClick && !windowWatched()) armFocusOpen(onClick);
      return;
    }
    const n = new Notification(note.title, { body: note.body, tag: note.tag });
    n.onclick = () => {
      window.focus();
      onClick?.();
      n.close();
    };
  } catch {
    /* notifications are best effort */
  }
}

/** True while the person can see the omher window. */
export function windowWatched(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "visible" && document.hasFocus();
}
