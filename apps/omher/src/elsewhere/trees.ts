// One worktree list per bot, shared by the Worktrees and Diff tabs and "Hand to <bot>" (src/handover/); Refresh (or
// 10 s) reads it again.
import type { Worktree } from "../lib/protocol";
import { getStore } from "../state/store";

const TREES_TTL = 10_000;
const trees = new Map<string, { at: number; p: Promise<{ worktrees: Worktree[] }> }>();

export function loadTrees(bot: string, fresh = false): Promise<{ worktrees: Worktree[] }> {
  const hit = trees.get(bot);
  if (hit && !fresh && Date.now() - hit.at < TREES_TTL) return hit.p;
  const p = getStore().actions.panelWorktrees(bot);
  trees.set(bot, { at: Date.now(), p });
  p.catch(() => trees.get(bot)?.p === p && trees.delete(bot));
  return p;
}
