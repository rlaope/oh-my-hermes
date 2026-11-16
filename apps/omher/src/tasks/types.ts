// Tasks (the sidebar's Tasks row and the Tasks page): the shapes the desktop shell's `tasks_*` commands answer
// (src-tauri/src/tasks.rs), and the words the page sends. Read-only (BOUNDARY rule 33).
//
// The idea and the page's shape come from Orca's Tasks (stablyai/orca, MIT License, Copyright (c) 2026 Lovecast Inc.).

export type TaskSource = "github" | "gitlab" | "linear";
/** The sources the shell lists through a CLI. */
export type CliSource = Exclude<TaskSource, "linear">;
export type TaskKind = "issues" | "prs";
export type TaskFilter = "assigned" | "created" | "mentioned" | "open";

export const SOURCES: readonly TaskSource[] = ["github", "gitlab", "linear"];
export const FILTERS: readonly TaskFilter[] = ["open", "assigned", "created", "mentioned"];
export const KINDS: readonly TaskKind[] = ["issues", "prs"];
/** Rows a page shows (tasks.rs PAGE). */
export const PAGE = 25;

export interface TaskLabel {
  name: string;
  /** `rrggbb`, or "" */
  color: string;
}

export interface TaskChecks {
  passed: number;
  failed: number;
  pending: number;
  total: number;
}

export interface TaskItem {
  number: number;
  title: string;
  state: "open" | "closed" | "merged" | "draft";
  url: string;
  labels: TaskLabel[];
  author: string;
  /** seconds since the epoch (0: unknown) */
  created: number;
  updated: number;
  checks: TaskChecks | null;
}

export interface TaskComment {
  author: string;
  body: string;
  created: number;
}

export interface TaskCheck {
  name: string;
  state: "passed" | "failed" | "pending" | "skipped";
  url: string;
}

export interface TaskDetail {
  item: TaskItem;
  body: string;
  comments: TaskComment[];
  checks: TaskCheck[];
}

export interface TaskPage {
  items: TaskItem[];
  more: boolean;
}

export interface CliStatus {
  installed: boolean;
  signed_in: boolean;
}

export interface TaskRemote {
  source: CliSource;
  repo: string;
}

/** The same check the shell makes (tasks.rs check_repo), so the page refuses a name before it asks. */
export function repoOk(source: CliSource, repo: string): boolean {
  const parts = repo.split("/");
  const n = source === "github" ? parts.length === 2 : parts.length >= 2 && parts.length <= 6;
  return n && parts.every((p) => /^[A-Za-z0-9._-]{1,100}$/.test(p) && !p.startsWith("-") && !p.startsWith("."));
}
