// Desktop-only calls for Accounts (Tauri commands in src-tauri/src/accounts.rs). In a plain browser (dev,
// e2e) they are absent and the page says so instead of pretending.
type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

export function isDesktop(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const core = (await import("@tauri-apps/api/core")) as { invoke: Invoke };
  return core.invoke<T>(cmd, args);
}

/** Whether a CPA management key is saved in the OS keychain (never the key). */
export const cpaKeyPresent = () => (isDesktop() ? invoke<boolean>("cpa_key_present") : Promise.resolve(false));
/** Saves the key in the OS keychain; it is never stored in a file or read back into the UI. */
export const cpaKeySet = (key: string) => invoke<void>("cpa_key_set", { key });
export const cpaSend = (request: unknown) => invoke<void>("cpa_send", { request });
