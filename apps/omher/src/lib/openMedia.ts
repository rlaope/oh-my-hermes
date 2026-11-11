// Open a file the bot sent (or show it in Finder / Explorer). Only the desktop app can: its `open_media`
// command accepts nothing but a file the bridge just served through `media.read`. In a plain browser (dev,
// e2e) this does nothing.
import { t } from "../i18n";

export const canOpenFiles = () =>
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in (window as unknown as Record<string, unknown>);

export async function openMedia(path: string, reveal = false): Promise<void> {
  if (!canOpenFiles()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("open_media", { path, reveal });
}

export const revealLabel = () =>
  t(typeof navigator !== "undefined" && /Windows/i.test(navigator.userAgent) ? "md.explorer" : "md.finder");
