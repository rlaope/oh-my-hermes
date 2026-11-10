// In-app updates. The Tauri shell's updater plugin reads one fixed endpoint (tauri.conf.json:
// the `omher-latest` release's latest.json on GitHub) and installs only a build signed with the key whose
// public half is pinned there. Outside Tauri (browser dev, e2e) there is no updater, unless the page sets
// `window.__omherUpdateHost`, the e2e stand-in.

/** Download progress: bytes so far and the total when the server sent one. */
export type UpdateProgress = { done: number; total: number | null };

export interface PendingUpdate {
  version: string;
  /** Download, verify and install; reports progress as it goes. */
  install(onProgress: (p: UpdateProgress) => void): Promise<void>;
}

export interface UpdateHost {
  /** A newer signed release, or null when this is the newest. */
  check(): Promise<PendingUpdate | null>;
  relaunch(): Promise<void>;
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

function tauriHost(): UpdateHost {
  return {
    async check() {
      const { check } = await import("@tauri-apps/plugin-updater");
      const u = await check();
      if (!u) return null;
      return {
        version: u.version,
        async install(onProgress) {
          let done = 0;
          let total: number | null = null;
          await u.downloadAndInstall((e) => {
            if (e.event === "Started") total = e.data.contentLength ?? null;
            else if (e.event === "Progress") done += e.data.chunkLength;
            onProgress({ done, total });
          });
        },
      };
    },
    async relaunch() {
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    },
  };
}

export function updateHost(): UpdateHost | null {
  if (typeof window === "undefined") return null;
  const injected = (window as unknown as { __omherUpdateHost?: UpdateHost }).__omherUpdateHost;
  if (injected) return injected;
  return inTauri() ? tauriHost() : null;
}

/** Whole percent of a download, or null when the size is unknown. */
export function percent(p: UpdateProgress): number | null {
  if (!p.total || p.total <= 0) return null;
  return Math.min(100, Math.floor((p.done / p.total) * 100));
}

/** One short line for a failed check or install. */
export function shortError(e: unknown): string {
  const raw = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  const line = raw.split("\n")[0].trim();
  if (!line) return "Update failed";
  return line.length > 80 ? `${line.slice(0, 79)}…` : line;
}
