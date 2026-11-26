// Files the person attaches in the composer: which Hermes attach call each one takes, the limits, and the
// text that goes with them. Pure, so it is tested without a DOM.
import type { AttachKind, AttachResult } from "../../lib/protocol";
import { extOf } from "./mediaLines";
import { t } from "../../i18n";

export const MAX_FILES = 20;
export const MAX_IMAGES = 10;
export const MAX_BYTES = 100 * 1024 * 1024;

/** Canonical Hermes image formats (`gateway/session_images.py`) plus Windows `.jfif` (sniffs as JPEG);
 * other image formats (BMP/TIFF/SVG/ICO) preview as images but upload through `file.attach` so canonical
 * `image.attach_bytes` does not reject them. */
const ATTACH_IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "jfif", "gif", "webp"]);
const ATTACH_IMAGE_MIMES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const PREVIEW_IMAGE_EXTS = new Set([...ATTACH_IMAGE_EXTS, "bmp", "tiff", "tif", "svg", "ico"]);
const PREVIEW_IMAGE_MIMES = new Set([
  ...ATTACH_IMAGE_MIMES,
  "image/bmp",
  "image/tiff",
  "image/svg+xml",
  "image/x-icon",
  "image/vnd.microsoft.icon",
]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm", "m4v"]);

export function attachKind(name: string, mime = ""): AttachKind {
  const ext = extOf(name);
  const low = mime.toLowerCase();
  if (ext === "pdf" || low === "application/pdf") return "pdf";
  if (ATTACH_IMAGE_EXTS.has(ext) || ATTACH_IMAGE_MIMES.has(low)) return "image";
  return "file";
}

/** How the chip and the sent bubble show the file. */
export function previewKind(name: string, mime = ""): "image" | "video" | "file" {
  const ext = extOf(name);
  const low = mime.toLowerCase();
  if (PREVIEW_IMAGE_EXTS.has(ext) || PREVIEW_IMAGE_MIMES.has(low)) return "image";
  if (VIDEO_EXTS.has(ext) || low.startsWith("video/")) return "video";
  return "file";
}

/** Why a file cannot go, or null. `index` is its place among the chips (0-based); `imageIndex` is its
 * 0-based place among image attachments (capped at Hermes' `_ATTACHMENT_LIMIT = 10`). */
export function limitReason(size: number, index: number, imageIndex = 0): string | null {
  if (index >= MAX_FILES) return t("att.tooMany", { n: MAX_FILES });
  if (imageIndex >= MAX_IMAGES) return t("att.tooManyImages", { n: MAX_IMAGES });
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
  const body =
    text ||
    results
      .map((r) => (r.ref_text ? "" : r.text || (r.kind === "image" ? `[User attached image: ${r.name}]` : "")))
      .filter(Boolean)
      .join("\n");
  return [...refs, body].filter(Boolean).join("\n\n");
}
