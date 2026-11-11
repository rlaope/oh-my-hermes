// Files in a SESSIONS chat: which attached pictures go to the agent as its own image input, the message text that
// names every other file by its saved copy's path, and the shell quoting of a path typed at a terminal's prompt.
// Pure, so it is tested without a DOM or a shell. The copies themselves are saved by the shell
// (src-tauri/src/session_files.rs) under `~/.omher/session-files/<session>/`.
import { extOf } from "../chat/parts/mediaLines";

/** Pictures an agent's image input takes (Claude Code, Codex, OmO / pi / oh-my-pi all read these four). */
const INLINE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
/** Bigger pictures are named by path instead (the agents' image inputs refuse very large ones). Same as the shell's `INLINE_MAX`. */
export const INLINE_MAX = 5 * 1024 * 1024;

/** Whether this file goes to the agent as a picture (else it is named by its saved path). */
export const inlinePicture = (name: string, size: number) => INLINE_EXTS.has(extOf(name)) && size <= INLINE_MAX;

/** What the agent reads: the text as typed, then one line per file it should open with its own tools. */
export function wireText(typed: string, paths: string[]): string {
  const text = typed.trim();
  if (!paths.length) return text;
  const head = paths.length === 1 ? "Attached file (a copy omher saved; open it with your tools):" : "Attached files (copies omher saved; open them with your tools):";
  return [text, [head, ...paths.map((p) => `- ${p}`)].join("\n")].filter(Boolean).join("\n\n");
}

/** A path as a terminal types it for a dropped file: bare when it is plain, else quoted for the shell (single
 *  quotes on macOS and Linux, double quotes on Windows). */
export function shellQuote(path: string, windows = false): string {
  if (/^[\w@%+=:,./-]+$/.test(path)) return path;
  return windows ? `"${path.replace(/"/g, '""')}"` : `'${path.replace(/'/g, `'\\''`)}'`;
}

/** The bytes of a base64 string (the composer's chips read files as base64). */
export function bytesOf(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  bmp: "image/bmp",
  svg: "image/svg+xml",
  mp4: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
  m4v: "video/mp4",
};

/** The type a sent bubble's preview is drawn with, from the file name. */
export const blobType = (name: string) => TYPES[extOf(name)] ?? "application/octet-stream";

/** A file a session's chat sent, as kept on this computer so its bubble shows it again after omher restarts. */
export interface SavedFile {
  name: string;
  size: number;
  kind: "image" | "video" | "file";
  path: string;
}

/** One sent message's files, with the text typed with them and when (seconds): after a restart the bubble that
 *  has this text at about this time takes the files back; one sent with no text comes back by itself. */
export interface SentEntry {
  ts: number;
  text: string;
  files: SavedFile[];
}

/** Sent files by session id, then by message id. */
export type SentFilesBook = Record<string, Record<string, SentEntry>>;
export const SENT_FILES_KEY = "omher.sessions.files";
const MAX_PER_SESSION = 40;

const isFile = (v: unknown): v is SavedFile => {
  const f = v as SavedFile;
  return !!f && typeof f.name === "string" && typeof f.size === "number" && typeof f.path === "string" && (f.kind === "image" || f.kind === "video" || f.kind === "file");
};

/** The book from storage; anything malformed is dropped. */
export function parseSentFiles(raw: string | null): SentFilesBook {
  let v: unknown;
  try {
    v = raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
  const out: SentFilesBook = {};
  if (!v || typeof v !== "object" || Array.isArray(v)) return out;
  for (const [sid, msgs] of Object.entries(v as Record<string, unknown>)) {
    if (!/^s\d{1,9}$/.test(sid) || !msgs || typeof msgs !== "object" || Array.isArray(msgs)) continue;
    const keep: Record<string, SentEntry> = {};
    for (const [mid, e] of Object.entries(msgs as Record<string, unknown>)) {
      const x = e as SentEntry;
      if (!x || typeof x.ts !== "number" || typeof x.text !== "string" || !Array.isArray(x.files) || !x.files.length || !x.files.every(isFile)) continue;
      keep[mid] = { ts: x.ts, text: x.text, files: x.files.map(({ name, size, kind, path }) => ({ name, size, kind, path })) };
    }
    if (Object.keys(keep).length) out[sid] = keep;
  }
  return out;
}

/** The book with one more sent message (its session keeps its last 40). */
export function putSentFiles(book: SentFilesBook, sid: string, mid: string, entry: SentEntry): SentFilesBook {
  const msgs = Object.entries({ ...book[sid], [mid]: entry }).slice(-MAX_PER_SESSION);
  return { ...book, [sid]: Object.fromEntries(msgs) };
}
