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

// ---- Tasks › 나 (Me): my pull requests, reviews, issues and mentions across repositories, per GitHub account --------
// (src-tauri/src/gh_me.rs)

/** A GitHub account gh is signed in to (`gh auth status --json hosts`: these fields only, never a token). */
export interface GhAccount {
  host: string;
  login: string;
  /** gh's active account on its host */
  active: boolean;
  /** `success`, else it must sign in again */
  state: string;
  scopes: string[];
}

export interface GhAccounts {
  installed: boolean;
  accounts: GhAccount[];
}

/** A GitHub account the person chose in omher (Settings › Accounts › GitHub): its host, login and colour. */
export interface ChosenAccount {
  host: string;
  login: string;
  /** one of ACCOUNT_COLORS */
  color: string;
}

export type MeSection = "review" | "authored" | "assigned" | "mentions";
/** The sections, in the order the page shows them. */
export const ME_SECTIONS: readonly MeSection[] = ["review", "authored", "assigned", "mentions"];

export interface MeItem {
  /** `owner/repo` */
  repo: string;
  number: number;
  title: string;
  url: string;
  pr: boolean;
  draft: boolean;
  state: "open" | "closed" | "merged" | "draft";
  author: string;
  labels: TaskLabel[];
  created: number;
  updated: number;
  /** my review is asked for */
  asked: boolean;
  ci: "" | "passed" | "failed" | "pending";
  review: "" | "approved" | "changes" | "required";
  conflict: boolean;
  /** when my review was asked for (0: unknown) */
  requested: number;
}

export interface MePage {
  items: MeItem[];
  more: boolean;
}

/** Why an account's list failed: `rate` (GitHub's rate limit: try again soon), `auth` (sign in again), `other`. */
export type MeFailKind = "rate" | "auth" | "other";

/** `<login>@<host>`: the id the page sends for an account. */
export const accountId = (a: { login: string; host: string }) => `${a.login}@${a.host}`;

/** The same check the shell makes (gh_me.rs parse_account_id). */
export function accountIdOk(id: string): boolean {
  const at = id.indexOf("@");
  if (at < 1 || id.indexOf("@", at + 1) >= 0) return false;
  const login = id.slice(0, at);
  const host = id.slice(at + 1);
  const hostOk = host.length <= 253 && host.split(".").length >= 2 && host.split(".").every((p) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(p));
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(login) && hostOk;
}
