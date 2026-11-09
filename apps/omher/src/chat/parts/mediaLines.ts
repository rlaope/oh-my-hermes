// `MEDIA:/abs/path` lines in a bot answer (Hermes' attachment convention). Only whole lines count, and not
// inside fenced code; the bridge parses the same way (bridge/omher_bridge.py `media_paths`), so every path
// shown here is one `media.read` will serve.

export type MediaKind = "image" | "video" | "audio" | "file";

const LINE = /^[ \t]*MEDIA:[ \t]*(.+?)[ \t]*$/;
const ABS = /^(?:\/|~\/|[A-Za-z]:[\\/])/;
const FENCE = /^[ \t]*(```|~~~)/;

const KINDS: Record<string, MediaKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  mp4: "video",
  mov: "video",
  webm: "video",
  m4v: "video",
  mp3: "audio",
  m4a: "audio",
  wav: "audio",
  ogg: "audio",
};

function pathOf(line: string): string | null {
  const m = LINE.exec(line);
  if (!m) return null;
  let p = m[1];
  if (p.length >= 2 && p[0] === p[p.length - 1] && "`\"'".includes(p[0])) p = p.slice(1, -1).trim();
  return ABS.test(p) ? p : null;
}

/** The answer without its MEDIA lines, and the paths those lines named, in order. */
export function splitMedia(text: string): { text: string; paths: string[] } {
  if (!text.includes("MEDIA:")) return { text, paths: [] };
  const keep: string[] = [];
  const paths: string[] = [];
  let fence = false;
  for (const line of text.split(/\r?\n/)) {
    if (FENCE.test(line)) fence = !fence;
    const p = fence ? null : pathOf(line);
    if (p) paths.push(p);
    else keep.push(line);
  }
  return { text: keep.join("\n").trim(), paths };
}

export const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

export function extOf(path: string): string {
  const name = fileName(path);
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i + 1).toLowerCase() : "";
}

export const mediaKind = (path: string): MediaKind => KINDS[extOf(path)] ?? "file";

export function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}
