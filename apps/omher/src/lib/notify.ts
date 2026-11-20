// System notifications while omher is in the background: a bot finished its answer, needs an approval,
// or asked a question. Nothing fires while you are looking at that bot's chat. Errors and clean program ends only
// mark their row; the body is what the bot said, as it would say it (`spoken`). In the desktop app this
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

/** A URL as its host, a path with folders as its last name: `https://x.y/z?q` -> `x.y`, `/a/b/c.ts` -> `c.ts`. */
export function shortenRefs(s: string): string {
  return s
    .replace(/\b[a-z][a-z0-9+.-]*:\/\/([^\s/?#)]+)[^\s)]*/gi, "$1")
    .replace(/(?:~|\.{1,2})?(?:\/[^\s/]+){2,}\/?|\b[\w.-]+(?:\/[\w.-]+){2,}\/?/g, (m) => m.replace(/\/$/, "").split("/").pop() || m);
}

/** Honorifics a greeting carries; with them and the punctuation gone, a greeting is a few letters. */
const HONORIFIC = /선생님|님|sir|ma'?am|madam|さん|様|先生/gi;
/** A sentence that is only a greeting or filler ("Done!", "네, 선생님!"): six letters or fewer once the honorifics go. */
const filler = (s: string) => (s.replace(HONORIFIC, "").match(/[\p{L}\p{N}]/gu) ?? []).length <= 6;

/** What a bot or agent said, as a notification says it: its first sentence, or up to three when the first is only a
 *  greeting, at most 140 characters. Code blocks, tables, headings, markdown marks, list bullets and asides in
 *  brackets go; a path keeps its last name, a URL its host. Pure. */
export function spoken(text: string, max = 140): string {
  const lines = text
    .replace(/```[\s\S]*?(?:```|$)/g, "\n")
    .replace(/~~~[\s\S]*?(?:~~~|$)/g, "\n")
    .split(/\r?\n/)
    .map((l) => l.trim())
    // tables and headings carry no sentence of the bot's own
    .filter((l) => l && !l.startsWith("|") && !/^#{1,6}\s/.test(l) && !/^[-=*_]{3,}$/.test(l))
    .map((l) =>
      shortenRefs(
        l
          .replace(/^(?:>\s*)+/, "")
          .replace(/^(?:[-*+•]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/, "")
          .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
          .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, "$1"),
      )
        .replace(/\s*\([^()]*\)|\s*（[^（）]*）/g, "")
        .replace(/\*\*|__|~~|`/g, "")
        .replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s.,!?;:)]|$)/g, "$1$2")
        .replace(/\s+/g, " ")
        .trim(),
    )
    .filter(Boolean);
  // `.` `!` `?` end a sentence before a space (not `c.ts`, `x.y`); full-width marks end one wherever they stand
  const sentences = lines.flatMap((l) => l.split(/(?<=[.!?])\s+|(?<=[。！？])(?![。！？])/).map((x) => x.trim()).filter(Boolean));
  const picked: string[] = [];
  for (const x of sentences) {
    picked.push(x);
    if (picked.length >= 3 || !filler(x)) break;
  }
  const out = picked.join(" ").replace(/([。！？])\s+/g, "$1").replace(/\s+/g, " ").trim();
  return out.length > max ? `${out.slice(0, max - 1).trimEnd()}…` : out;
}

/** `spoken(text)`, or the plain clipped text when nothing sayable is left (an answer that is only a code block). */
const say = (text: string) => spoken(text) || clip(shortenRefs(text));

/** The notification for `ev`, or null when there is nothing worth interrupting for: an answer, an approval, a question.
 *  A turn that ended with an error only marks its chat unless `ctx.errors` ("Also notify on errors"). Pure: no globals. */
export function noteFor(
  ev: BridgeEvent,
  ctx: { name: (bot: string) => string; watching: (bot: string) => boolean; errors?: boolean },
): Note | null {
  const bot = ev.bot;
  if (!bot || ctx.watching(bot)) return null;
  const who = ctx.name(bot);
  switch (ev.event) {
    case "message":
      if (ev.watch) return ev.text.trim() ? watchNote(who, bot, ev.watch.name, ev.text) : null;
      return ev.text.trim() ? { title: who, body: say(ev.text), bot, tag: `${bot}:message` } : null;
    case "approval.request":
      return {
        title: t("note.approval", { bot: who }),
        body: clip(shortenRefs(ev.command || ev.title || t("ask.allowThis"))),
        bot,
        tag: `${bot}:approval`,
      };
    case "clarify.request":
      return { title: t("note.question", { bot: who }), body: ev.question.trim() ? say(ev.question) : t("note.waiting"), bot, tag: `${bot}:clarify` };
    case "turn.end":
      return ev.outcome === "error" && ctx.errors
        ? { title: t("note.error", { bot: who }), body: say(ev.error || t("note.failed")), bot, tag: `${bot}:error` }
        : null;
    default:
      return null;
  }
}

/** An automation's answer: "<bot> · <watch>", its first line. */
export function watchNote(who: string, bot: string, name: string, text: string): Note {
  // omher's own Slack briefing reads as "<bot> · Brief", not its job name
  return { title: `${who} · ${name === "omher-brief" ? t("brief.line") : name}`, body: say(text), bot, tag: `${bot}:watch` };
}

/** Answers that came in while omher was closed: one note for the bot, never one per answer. */
export function watchMissedNote(who: string, bot: string, rows: { text: string; watch?: { name: string } }[]): Note | null {
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  if (rows.length === 1) return watchNote(who, bot, last.watch?.name ?? "", last.text);
  return { title: t("note.watchMany", { bot: who, n: rows.length }), body: say(last.text), bot, tag: `${bot}:watch` };
}

/** Something a SESSIONS session did that is not a chat event: its program ended, it could not start, or its
 *  terminal rang its bell. */
export interface SessionNote {
  kind: "ended" | "failed" | "bell";
  /** `web-app · Claude Code` */
  name: string;
  code?: number | null;
  error?: string;
  /** How long its program ran, ms (ended). */
  ms?: number;
  /** The turn that failed with this end already said why (its own error notification, when those are on). */
  told?: boolean;
}

/** A program that ends this soon after it started did not really run. */
export const EARLY_END_MS = 5000;

/** Whether `n` is worth a notification: a ring, a start that failed, and an end that went wrong (an exit code, a reason,
 *  or within its first 5 s). A clean exit only marks the row. Pure. */
export function sessionRings(n: SessionNote): boolean {
  if (n.kind !== "ended") return true;
  if (n.error || (typeof n.code === "number" && n.code !== 0)) return true;
  return typeof n.ms === "number" && n.ms < EARLY_END_MS;
}

/** The notification for `n` of session `id`. Pure: no globals. */
export function sessionNote(id: string, n: SessionNote): Note {
  const title = t(n.kind === "bell" ? "note.session.bell" : n.kind === "failed" ? "note.session.failed" : "note.session.ended", { name: n.name });
  const exit = typeof n.code === "number" && n.code !== 0 ? t("ss.endedExit", { code: n.code }) : "";
  const body = n.kind === "bell" ? t("note.session.bellBody") : n.error ? say(n.error) : clip(exit || t(n.kind === "failed" ? "ss.couldNotStart" : "note.session.endedBody"));
  return { title, body, bot: id, tag: `${id}:${n.kind}` };
}

/** How long a ring with no words waits for the question that says what it wants. */
export const HOLD_MS = 8000;

/** The notification gate for chats. A ring with no words (a bell, an OSC 9 ring, a question with no text) waits
 *  `ms` per chat: an agent often rings just before the question that says what it wants, and both rang. A texted
 *  question or approval for the same chat takes its place; with nothing in `ms` the held one fires. */
export function createNoteGate(ms = HOLD_MS) {
  const held = new Map<string, ReturnType<typeof setTimeout>>();
  const drop = (key: string) => {
    const h = held.get(key);
    if (h === undefined) return;
    clearTimeout(h);
    held.delete(key);
  };
  return {
    /** `fire` shows chat `key`'s note: `empty` (a ring with no words) is held, `ask` (a texted question or approval)
     *  replaces a held one, `plain` goes out as is. */
    offer(key: string, how: "empty" | "ask" | "plain", fire: () => void) {
      if (how === "empty") {
        drop(key);
        held.set(
          key,
          setTimeout(() => {
            held.delete(key);
            fire();
          }, ms),
        );
        return;
      }
      if (how === "ask") drop(key);
      fire();
    },
    /** Chats with a ring waiting. */
    pending: () => [...held.keys()],
  };
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
