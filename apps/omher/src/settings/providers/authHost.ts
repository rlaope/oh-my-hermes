// Settings › Providers "Add key": ask the desktop app to open the system terminal running exactly
// `hermes auth add <provider> --type api-key` (src-tauri/src/hermes_auth.rs, BOUNDARY rule 23). Hermes asks
// for the key in that terminal; omher never sees it. In a plain browser (dev, e2e) e2e injects a stand-in as
// `window.__omherAuthHost`; without one the page only shows the command to run.

/** Same check as the shell's `valid_provider`. */
export const PROVIDER_ID = /^[a-z0-9][a-z0-9_-]{0,40}$/;

/** Hermes provider ids offered even when the bot's model list does not name them. */
export const KNOWN_PROVIDERS = ["anthropic", "openai", "openrouter", "nous", "gemini", "xai", "deepseek"];

export interface AuthHost {
  open(provider: string): Promise<void>;
}

declare global {
  interface Window {
    __omherAuthHost?: AuthHost;
  }
}

const tauriHost: AuthHost = {
  async open(provider) {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_hermes_auth", { provider });
  },
};

export function authHost(): AuthHost | null {
  if (typeof window === "undefined") return null;
  if (window.__omherAuthHost) return window.__omherAuthHost;
  return "__TAURI_INTERNALS__" in window ? tauriHost : null;
}

/** The known ids first, then the bot's own providers (custom ones such as og, claude-proxy), each once. */
export function keyProviders(slugs: string[]): string[] {
  return [...new Set([...KNOWN_PROVIDERS, ...slugs])].filter((s) => PROVIDER_ID.test(s));
}

export const authCommand = (provider: string) => `hermes auth add ${provider} --type api-key`;
