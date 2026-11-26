// Remote-only mode (BOUNDARY rule 46): the shell keeps one `ssh` link to a Hermes on a server and the page talks only
// to that server's bridge. The page learns the mode from `bridge_status` (`mode: "remote"`, `host`, `label`), which the
// gate polls; this module keeps the last answer so any gate that would hand THIS computer's folders or files to a bot
// can ask `remoteOnly()` (a bot there cannot read a folder here, the same reason a peer bot is never offered one).
import { useSyncExternalStore } from "react";

export interface ServerMode {
  mode: "local" | "remote";
  host?: string;
  label?: string;
}

let current: ServerMode = { mode: "local" };
const subs = new Set<() => void>();
let markKnown: () => void = () => {};
const known = new Promise<void>((r) => (markKnown = r));
// no shell to ask (browser dev, e2e without the gate stand-in, unit tests): local mode, as before rule 46
if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window || "__OMHER_GATE__" in window)) markKnown();

/** Settles once the mode is known: the gate's first `bridge_status` answer, or at once when there is no shell to ask.
 *  What would send a folder of this computer on its own (a restart's folder chats) waits for it. */
export const modeKnown = (): Promise<void> => known;

/** The gate's latest `bridge_status`: the mode it names (a status without one is local, as before rule 46). */
export function noteServerMode(s: { mode?: string; host?: string; label?: string } | null | undefined): void {
  const next: ServerMode = s?.mode === "remote" ? { mode: "remote", host: s.host, label: s.label } : { mode: "local" };
  markKnown();
  if (next.mode === current.mode && next.host === current.host && next.label === current.label) return;
  current = next;
  for (const f of subs) f();
}

export const serverMode = (): ServerMode => current;

/** True while omher is connected to a server instead of a Hermes on this computer. */
export const remoteOnly = (): boolean => current.mode === "remote";

export function useServerMode(): ServerMode {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => current,
    () => current,
  );
}

/** How the server is named on screen: its label, else the host. */
export const serverLabel = (s: { host?: string; label?: string } | null | undefined): string => s?.label || s?.host || "";

/** The port field: empty is ssh's own default (undefined), a whole number 1-65535 is that port, anything else null. */
export function parsePort(text: string): number | undefined | null {
  const s = text.trim();
  if (!s) return undefined;
  if (!/^[0-9]{1,5}$/.test(s)) return null;
  const n = Number(s);
  return n >= 1 && n <= 65535 ? n : null;
}

/** Asks the gate to show its Connect form over the app (Settings › Server › Change server). */
export const CHANGE_SERVER_EVENT = "omher:change-server";
export function openChangeServer(): void {
  window.dispatchEvent(new Event(CHANGE_SERVER_EVENT));
}
