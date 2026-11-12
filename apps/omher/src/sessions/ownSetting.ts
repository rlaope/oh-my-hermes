// What an agent says it runs with when the person has picked none of omher's modes: its own config's approval
// policy and sandbox, as the agent itself reported them in `session.info` (Codex `approval: never`,
// `sandbox: dangerFullAccess`; Claude Code's `permissionMode`). Read-only: these values are only recognised to say
// so in plain words. omher never offers, sends or writes any of them (controls.ts holds the modes it offers).
import { t } from "../i18n";
import { MODES } from "./controls";

/** The agent's reported values that mean it asks for nothing before acting. */
const NO_APPROVALS = new Set(["never", "bypassPermissions"]);
/** The agent's reported sandbox values that mean it reaches the whole disk. */
const FULL_DISK = new Set(["dangerFullAccess", "danger-full-access"]);

/** "No approvals · full disk access" (or one of the two) for an agent running its own setting that asks for
 *  nothing or reaches the whole disk; null for anything that still asks inside a sandbox, and once one of omher's
 *  modes is in force. */
export function ownSetting(live: { mode?: string; approval?: string; sandbox?: string } | undefined): string | null {
  if (!live) return null;
  if (live.mode && Object.values(MODES).some((m) => m?.includes(live.mode!))) return null;
  const noAsk = NO_APPROVALS.has(live.approval ?? "") || NO_APPROVALS.has(live.mode ?? "");
  const full = FULL_DISK.has(live.sandbox ?? "");
  if (noAsk && full) return t("ctl.own.noApprovalsFull");
  if (noAsk) return t("ctl.own.noApprovals");
  if (full) return t("ctl.own.fullAccess");
  return null;
}
