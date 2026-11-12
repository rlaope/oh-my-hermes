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

/** Show `note`. `onClick` (browser build) opens that bot's chat. Never throws. */
export async function showNote(note: Note, onClick?: () => void): Promise<void> {
  if (!(await permitted())) return;
  try {
    if (isTauri()) {
      const n = await import("@tauri-apps/plugin-notification");
      n.sendNotification({ title: note.title, body: note.body });
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
