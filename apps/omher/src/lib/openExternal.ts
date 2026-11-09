// Open a thread in its own app. In the desktop app this goes through the Tauri command, which only
// accepts Slack / Discord / Telegram links; in a plain browser (dev, e2e) it opens a new tab.
export async function openExternal(url: string): Promise<void> {
  const w = window as unknown as { __TAURI_INTERNALS__?: unknown };
  if (w.__TAURI_INTERNALS__) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_external", { url });
    return;
  }
  window.open(url, "_blank", "noopener");
}
