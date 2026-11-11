// Files the person attaches in the composer: which Hermes attach call each one takes, the limits, and the
// text that goes with them. Pure, so it is tested without a DOM.
import type { AttachKind, AttachResult } from "../../lib/protocol";
import { extOf } from "./mediaLines";
import { t } from "../../i18n";

export const MAX_FILES = 20;
export const MAX_BYTES = 100 * 1024 * 1024;

/** Hermes' own image extensions (`cli._IMAGE_EXTENSIONS`); anything else that is not a PDF goes as a file. */
const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff", "tif", "svg", "ico"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm", "m4v"]);

export function attachKind(name: string, mime = ""): AttachKind {
  const ext = extOf(name);
  if (ext === "pdf" || mime === "application/pdf") return "pdf";
  if (IMAGE_EXTS.has(ext)) return "image";
  return "file";
}

/** How the chip and the sent bubble show the file. */
export function previewKind(name: string, mime = ""): "image" | "video" | "file" {
  const ext = extOf(name);
  if (IMAGE_EXTS.has(ext)) return "image";
  if (VIDEO_EXTS.has(ext) || mime.startsWith("video/")) return "video";
  return "file";
}

/** Why a file cannot go, or null. `index` is its place among the chips (0-based). */
export function limitReason(size: number, index: number): string | null {
  if (index >= MAX_FILES) return t("att.tooMany", { n: MAX_FILES });
  if (size > MAX_BYTES) return t("att.tooBig");
  return null;
}

/** The badge on a chip with no picture: PDF, or the extension (up to 4 letters). */
export const badgeFor = (name: string) => (extOf(name) || "file").slice(0, 4).toUpperCase();

/** The prompt text: `@file:` refs for staged files first (Hermes reads them from there), then what the person
 * typed. With nothing typed, the attach calls' own lines (`[User attached image: …]`) stand in. */
export function promptText(typed: string, results: AttachResult[]): string {
  const refs = results.map((r) => r.ref_text).filter(Boolean);
  const text = typed.trim();
  const body = text || results.map((r) => (r.ref_text ? "" : r.text)).filter(Boolean).join("\n");
  return [...refs, body].filter(Boolean).join("\n\n");
}
