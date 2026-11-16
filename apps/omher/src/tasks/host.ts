// Where the Tasks page's lists come from. In the desktop app: the shell's `tasks_*` commands (src-tauri/src/tasks.rs),
// which run the person's own `gh` / `glab` with a fixed, read-only argv. In a plain browser (dev, e2e against the mock
// bridge) a mock answers from `window.__omherTasks` and records every call in `window.__omherTaskCalls`.
import type { CliSource, CliStatus, TaskDetail, TaskFilter, TaskItem, TaskKind, TaskPage, TaskRemote } from "./types";
import { PAGE } from "./types";

export interface TaskHost {
  readonly kind: "tauri" | "mock";
  status(source: CliSource, fresh?: boolean): Promise<CliStatus>;
  list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number): Promise<TaskPage>;
  view(source: CliSource, repo: string, kind: TaskKind, number: number): Promise<TaskDetail>;
  /** The GitHub / GitLab repository folder `cwd` is in (its `.git/config`), or null. */
  remote(cwd: string): Promise<TaskRemote | null>;
}

class TauriTaskHost implements TaskHost {
  readonly kind = "tauri" as const;
  private core = () => import("@tauri-apps/api/core");
  async status(source: CliSource, fresh = false) {
    const { invoke } = await this.core();
    return invoke<CliStatus>("tasks_status", { source, fresh });
  }
  async list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number) {
    const { invoke } = await this.core();
    return invoke<TaskPage>("tasks_list", { source, repo, kind, filter, page });
  }
  async view(source: CliSource, repo: string, kind: TaskKind, number: number) {
    const { invoke } = await this.core();
    return invoke<TaskDetail>("tasks_view", { source, repo, kind, number });
  }
  async remote(cwd: string) {
    const { invoke } = await this.core();
    return invoke<TaskRemote | null>("tasks_remote", { cwd });
  }
}

// ---- Mock -----------------------------------------------------------------------------------

/** What the mock answers, set by a test before the page loads (`window.__omherTasks`). */
export interface MockTasks {
  status?: Partial<Record<CliSource, CliStatus>>;
  /** `<source>:<repo>:<kind>` -> every open row (the mock filters and pages them) */
  items?: Record<string, (TaskItem & { assignee?: boolean; mine?: boolean; mentions?: boolean })[]>;
  /** `<source>:<repo>:<kind>:<number>` -> the drawer's detail (else one made from the row) */
  details?: Record<string, Partial<TaskDetail>>;
  /** folder -> remote */
  remotes?: Record<string, TaskRemote>;
  /** `<source>:<repo>` -> an error line the list fails with */
  errors?: Record<string, string>;
}

export type MockTaskCall =
  | { op: "status"; source: CliSource }
  | { op: "list"; source: CliSource; repo: string; kind: TaskKind; filter: TaskFilter; page: number }
  | { op: "view"; source: CliSource; repo: string; kind: TaskKind; number: number }
  | { op: "remote"; cwd: string };

type G = { __omherTasks?: MockTasks; __omherTaskCalls?: MockTaskCall[] };

class MockTaskHost implements TaskHost {
  readonly kind = "mock" as const;
  constructor(private g: G = globalThis as G) {}
  private log(c: MockTaskCall) {
    (this.g.__omherTaskCalls ??= []).push(c);
  }
  private get data(): MockTasks {
    return this.g.__omherTasks ?? {};
  }
  async status(source: CliSource) {
    this.log({ op: "status", source });
    return this.data.status?.[source] ?? { installed: true, signed_in: true };
  }
  async list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number) {
    this.log({ op: "list", source, repo, kind, filter, page });
    await new Promise((r) => setTimeout(r, 30));
    const err = this.data.errors?.[`${source}:${repo}`];
    if (err) throw new Error(err);
    const all = (this.data.items?.[`${source}:${repo}:${kind}`] ?? []).filter((i) =>
      filter === "assigned" ? i.assignee : filter === "created" ? i.mine : filter === "mentioned" ? i.mentions : true,
    );
    const items = all.slice(page * PAGE, (page + 1) * PAGE).map(({ assignee: _a, mine: _m, mentions: _n, ...i }) => i);
    return { items, more: all.length > (page + 1) * PAGE };
  }
  async view(source: CliSource, repo: string, kind: TaskKind, number: number) {
    this.log({ op: "view", source, repo, kind, number });
    await new Promise((r) => setTimeout(r, 30));
    const row = (this.data.items?.[`${source}:${repo}:${kind}`] ?? []).find((i) => i.number === number);
    if (!row) throw new Error(`no #${number}`);
    const { assignee: _a, mine: _m, mentions: _n, ...item } = row;
    const d = this.data.details?.[`${source}:${repo}:${kind}:${number}`] ?? {};
    return { item, body: d.body ?? "", comments: d.comments ?? [], checks: d.checks ?? [] };
  }
  async remote(cwd: string) {
    this.log({ op: "remote", cwd });
    return this.data.remotes?.[cwd] ?? null;
  }
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let host: TaskHost | null = null;
export function taskHost(): TaskHost {
  return (host ??= inTauri() ? new TauriTaskHost() : new MockTaskHost());
}
