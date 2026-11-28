// Settings › Computer (BOUNDARY rule 52): what the page shows and offers, from what the bridge read. Pure, so each
// state reads the same in a test as on the page.
import type { Bot, ComputerStatus, ComputerSwitch } from "../../lib/protocol";
import type { Key } from "../../i18n";

/** Hermes' `sys.platform` as people call it; anything else stays as Hermes wrote it. */
const PLATFORMS: Record<string, string> = { darwin: "macOS", win32: "Windows", linux: "Linux" };
export const platformName = (p: string): string => PLATFORMS[p] ?? p;

export type ComputerRead = Extract<ComputerStatus, { read: true }>;

/** What "This computer" offers besides Check again: Install while there is no driver, Grant access on macOS while a
 *  grant is missing. Nothing on a computer Hermes does not support, or when the state could not be read. */
export function driverActions(st: ComputerStatus | null): ("install" | "grant")[] {
  if (!st || !st.read || !st.platform_supported) return [];
  if (!st.installed) return ["install"];
  if (st.can_grant && (st.accessibility !== true || st.screen_recording !== true)) return ["grant"];
  return [];
}

/** The one overall line: ready, not ready, or not known (no read, or Hermes could not tell). */
export function overall(st: ComputerStatus | null): "ready" | "notReady" | "unknown" {
  if (!st || !st.read || st.ready === null) return "unknown";
  return st.ready ? "ready" : "notReady";
}

/** A macOS grant in words: granted, missing, or not known. */
export const grantKey = (v: boolean | null): Key => (v === true ? "cu.granted" : v === false ? "cu.notGranted" : "cu.notKnown");

/** A driver check's state as Hermes wrote it, in one place for its word and its colour. A state not listed keeps
 *  Hermes' own word and no colour. */
const CHECK_LOOK: Record<string, { key: Key; tone: "ok" | "warn" | "fail" | "skip" }> = {
  ok: { key: "cu.checkOk", tone: "ok" },
  pass: { key: "cu.checkOk", tone: "ok" },
  passed: { key: "cu.checkOk", tone: "ok" },
  warn: { key: "cu.checkWarn", tone: "warn" },
  warning: { key: "cu.checkWarn", tone: "warn" },
  degraded: { key: "cu.checkWarn", tone: "warn" },
  fail: { key: "cu.checkFail", tone: "fail" },
  failed: { key: "cu.checkFail", tone: "fail" },
  error: { key: "cu.checkFail", tone: "fail" },
  skip: { key: "cu.checkSkip", tone: "skip" },
  skipped: { key: "cu.checkSkip", tone: "skip" },
};
export const checkLook = (status: string): { key: Key; tone: string } | { key: null; tone: "" } =>
  CHECK_LOOK[status.trim().toLowerCase()] ?? { key: null, tone: "" };

/** The bridge's refusals that come before anything is asked of Hermes (`no_hermes`: there is no Hermes to run);
 *  any other error leaves the switch unknown. */
const REFUSED_FIRST = new Set(["bad_request", "pinned", "cannot_tell", "busy", "unknown_bot", "remote_bot", "remote_only", "no_hermes"]);

/** What a flip that did not end as asked says: Hermes left the switch as it was (`disagrees`), omher cannot tell
 *  whether it changed (`unknown`), or nothing was asked of Hermes (`notAsked`: a refusal before the run, or a request
 *  the page's client never sent, `sent: false`). */
export function flipFailure(o: { state?: ComputerSwitch; thrownCode?: string; sent?: boolean }): "disagrees" | "unknown" | "notAsked" {
  if (o.thrownCode !== undefined) return o.sent === false || REFUSED_FIRST.has(o.thrownCode) ? "notAsked" : "unknown";
  return o.state === "unknown" || o.state === undefined ? "unknown" : "disagrees";
}

/** Whether coming back to omher reads This computer again: only while a grant waits on macOS' dialog and no other run
 *  (a flip, an install, a read) is under way, so a read never cuts into a run and frees its buttons early. */
export const readOnReturn = (o: { grantAsked: boolean; running: boolean; visible: boolean }): boolean => o.grantAsked && !o.running && o.visible;

export interface SwitchOff {
  key: Key;
  vars?: Record<string, string>;
}

/** Why a bot's switch is off and cannot be pressed, or null when it can. Checked in this order: omher uses a server,
 *  the bot is on another computer, the toolsets are pinned, Hermes does not support this computer, the switch could
 *  not be read (the bot is offline, or its Hermes did not say). `state` undefined: not read yet. */
export function switchOff(
  bot: Bot,
  o: { remote: boolean; status: ComputerStatus | null; state: ComputerSwitch | undefined; why?: string },
): SwitchOff | null {
  if (o.remote) return { key: "cu.offRemote" };
  if (bot.host) return { key: "cu.offPeer", vars: { computer: bot.host.label } };
  if (o.status?.pinned) return { key: "cu.offPinned" };
  if (o.status?.read && !o.status.platform_supported) return { key: "cu.unsupported", vars: { platform: platformName(o.status.platform) } };
  if (o.state === "unknown") return { key: o.why === "offline" ? "cu.offOffline" : "cu.offUnread", vars: { bot: bot.display_name } };
  return null;
}
