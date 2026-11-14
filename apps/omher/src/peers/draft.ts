// A bot's SSH draft: a fenced ```omher-peer block in its reply holding one JSON object
// `{"host": "<ssh alias or user@host>", "label": "<short name>", "port"?: 22}` (unknown keys ignored). The block still
// renders as a code block; each one also gets a "Connect over SSH" chip under the reply (PeerChip.tsx) that opens the
// same confirm card as the sidebar's Connect over SSH, filled from the draft and checked again by the shell. Nothing
// connects until that card's Connect. Drafts are read only from bot replies in a bot's main chat, never from tool
// output, Slack/Discord mirrors (elsewhere lines) or a SESSIONS chat.

/** One draft as the bot wrote it: the fields the card takes, nothing else. */
export interface PeerDraft {
  host: string;
  label: string;
  port?: number;
}

/** Why a block cannot be a draft (`peer.why.<code>`). */
export type PeerWhy = "json" | "shape" | "host" | "label" | "port";

export type PeerDraftBlock = { draft: PeerDraft; why: null } | { draft: PeerDraft | null; why: PeerWhy };

/** The shell's own host check (peers.rs `valid_host`): an ssh alias or `[user@]host`, never an option or shell text. */
const USER = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,31}$/;
const NAME = /^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$/;
export function validHost(host: string): boolean {
  const at = host.indexOf("@");
  if (at === -1) return NAME.test(host);
  return USER.test(host.slice(0, at)) && NAME.test(host.slice(at + 1));
}

/** 1 to 40 characters, not blank, no control characters (peers.rs `valid_label`). */
export function validLabel(label: string): boolean {
  const n = [...label].length;
  // eslint-disable-next-line no-control-regex
  return n >= 1 && n <= 40 && label.trim() !== "" && !/[\u0000-\u001f\u007f]/.test(label);
}

/** A default label from the host: `sionic@mac-mini.local` -> `mac-mini`. */
export function labelFor(host: string): string {
  const name = host.split("@").pop() ?? host;
  const first = /^\d+(\.\d+){3}$/.test(name) ? name : name.split(".")[0];
  return [...first].slice(0, 40).join("");
}

/** A ```omher-peer fence (or ~~~), from its opening line to its closing one; or an inline one-line ```omher-peer {...}```. */
const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*omher-peer[ \t]*\r?\n([\s\S]*?)\r?\n {0,3}\1[ \t]*$/gm;
const INLINE = /(`{3,})omher-peer[ \t]+(\{[^`\n]*\})[ \t]*\1/g;

/** Each omher-peer block of `text`, in order, checked as the shell will check it again. */
export function parsePeerDrafts(text: string): PeerDraftBlock[] {
  if (!text.includes("omher-peer")) return [];
  const found: { at: number; body: string }[] = [];
  for (const m of text.matchAll(FENCE)) found.push({ at: m.index ?? 0, body: m[2] });
  for (const m of text.matchAll(INLINE)) found.push({ at: m.index ?? 0, body: m[2] });
  return found.sort((a, b) => a.at - b.at).map((f) => parseOne(f.body));
}

function parseOne(body: string): PeerDraftBlock {
  let v: unknown;
  try {
    v = JSON.parse(body);
  } catch {
    return { draft: null, why: "json" };
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return { draft: null, why: "json" };
  const o = v as Record<string, unknown>;
  if (typeof o.host !== "string" || (o.label !== undefined && typeof o.label !== "string") || (o.port !== undefined && typeof o.port !== "number"))
    return { draft: null, why: "shape" };
  const host = o.host.trim();
  const label = typeof o.label === "string" && o.label.trim() ? o.label.trim() : labelFor(host);
  const draft: PeerDraft = { host, label, ...(typeof o.port === "number" ? { port: o.port } : {}) };
  if (!validHost(host)) return { draft, why: "host" };
  if (!validLabel(label)) return { draft, why: "label" };
  if (draft.port !== undefined && !(Number.isInteger(draft.port) && draft.port >= 1 && draft.port <= 65535)) return { draft, why: "port" };
  return { draft, why: null };
}

/** Chats whose bot replies may carry drafts: a bot's main chat only (its profile name, no `fold:` / `agent:` key). A
 *  bot on another computer (`<peer>:<name>`) may propose one too: the card still runs on this computer. */
export const peerDraftsAllowed = (chatKey: string): boolean => !chatKey.startsWith("fold:") && !chatKey.startsWith("agent:");
