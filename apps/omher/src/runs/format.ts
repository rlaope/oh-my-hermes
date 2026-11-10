// Small display helpers shared by the Runs panel and the full view.
import type { RunNode } from "../lib/runs";

/** "claude-opus-5-5" -> "Opus 5.5"; ids that do not follow that shape stay as they are. */
export function shortModel(model: string): string {
  const m = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(model);
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`;
  return model;
}

/** "Opus 5.5 · high" for a node that ran on a known model, else "". */
export function modelLine(n: Pick<RunNode, "model" | "effort">): string {
  if (!n.model) return "";
  return n.effort ? `${shortModel(n.model)} · ${n.effort}` : shortModel(n.model);
}

export const STATE_WORD: Record<RunNode["state"], string> = {
  done: "done",
  running: "running",
  failed: "failed",
  blocked: "blocked",
  parked: "parked",
  waiting: "waiting",
  cancelled: "cancelled",
};

/** The dag run's short name ("omher-v02") from its id ("dag:<session>/omher-v02"). */
export const runName = (id: string) => id.split("/").pop() ?? id;

export const reducedMotion = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
