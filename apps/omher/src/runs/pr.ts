// The pull request a plan node opened: "#2746" with GitHub's state mark on the node's status line and in its
// detail. The bridge finds the number (`runs.get`) and asks GitHub for the state later (`runs.prs`); this file only
// formats, merges and opens. A PR's page opens in the browser only from a click on its number.
import type { AgentRun, NodePr, PrState } from "../lib/runs";
import { openExternal } from "../lib/openExternal";
import { t } from "../i18n";

/** A pull request's page and nothing else on GitHub (the desktop shell checks the same before it opens one). */
export const PR_URL = /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}\/pull\/(\d{1,7})$/;

/** "#2746". */
export const prLabel = (pr: Pick<NodePr, "number">) => `#${pr.number}`;
/** The state as known so far; none yet is `unknown`. */
export const prState = (pr: Pick<NodePr, "state">): PrState => pr.state ?? "unknown";
/** "Merged", "Open", "Closed", "Draft"; "" for a state not known. */
export const prWord = (state: PrState) => (state === "unknown" ? "" : t(`pr.${state}`));
/** "#2746 · Merged", or "#2746" while the state is not known. */
export const prText = (pr: NodePr) => [prLabel(pr), prWord(prState(pr))].filter(Boolean).join(" · ");

/** The PR's page when it is a GitHub pull request link for this number; null otherwise (then the number is text). */
export function prLink(pr: NodePr): string | null {
  const m = pr.url ? PR_URL.exec(pr.url) : null;
  return m && Number(m[1]) === pr.number ? pr.url! : null;
}

/** The run with each node's PR state from `runs.prs` laid over the number `runs.get` gave (same number only). */
export function withPrs<R extends Pick<AgentRun, "nodes">>(run: R, prs: Record<string, NodePr> | null | undefined): R {
  if (!prs || !run.nodes.some((n) => n.pr && prs[n.id]?.number === n.pr.number)) return run;
  return { ...run, nodes: run.nodes.map((n) => (n.pr && prs[n.id]?.number === n.pr.number ? { ...n, pr: { ...n.pr, ...prs[n.id] } } : n)) };
}

/** Opens the PR's page in the browser (the desktop shell's opener; a new tab in a plain browser). */
export function openPr(pr: NodePr) {
  const url = prLink(pr);
  if (url) void openExternal(url);
}
