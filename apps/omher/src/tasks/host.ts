// Where the Tasks page's lists come from. In the desktop app: the shell's `tasks_*` commands (src-tauri/src/tasks.rs),
// which run the person's own `gh` / `glab` with a fixed, read-only argv. In a plain browser (dev, e2e against the mock
// bridge) a mock answers from `window.__omherTasks` and records every call in `window.__omherTaskCalls`.
//
// The "나" (Me) scope and the GitHub accounts (src-tauri/src/gh_me.rs) come through the same host: the page sends
// only an account id (`<login>@<host>`), a section word and a page number; a non-active account's token never
// reaches the page (the shell reads it for one `gh` call and drops it).
import { maskSecrets } from "../lib/secrets";
import type { CliSource, CliStatus, GhAccount, GhAccounts, MeFailKind, MeItem, MePage, MeSection, TaskDetail, TaskFilter, TaskItem, TaskKind, TaskPage, TaskRemote } from "./types";
import { PAGE } from "./types";

/** A "나" list that failed, with why (`rate`: GitHub's rate limit, `auth`: sign in again, `other`). */
export class MeFail extends Error {
  constructor(
    readonly kind: MeFailKind,
    line: string,
  ) {
    super(line);
  }
}

const failOf = (e: unknown): MeFail => {
  if (e instanceof MeFail) return e;
  const o = e && typeof e === "object" ? (e as { kind?: unknown; line?: unknown; message?: unknown }) : null;
  const kind = o?.kind === "rate" || o?.kind === "auth" ? o.kind : "other";
  const line = typeof o?.line === "string" ? o.line : typeof o?.message === "string" ? o.message : String(e);
  return new MeFail(kind, line);
};

export interface TaskHost {
  readonly kind: "tauri" | "mock";
  status(source: CliSource, fresh?: boolean): Promise<CliStatus>;
  /** `account` (GitHub): a chosen account's id; none: gh's own active account. */
  list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number, account?: string): Promise<TaskPage>;
  view(source: CliSource, repo: string, kind: TaskKind, number: number, account?: string): Promise<TaskDetail>;
  /** The GitHub / GitLab repository folder `cwd` is in (its `.git/config`), or null. */
  remote(cwd: string): Promise<TaskRemote | null>;
  /** The GitHub accounts gh is signed in to. */
  ghAccounts(fresh?: boolean): Promise<GhAccounts>;
  /** One page of a "나" section as `account`; fails with a MeFail. `fresh` (⟳, window focus): read again past a
   *  short gap instead of the minute's answer. */
  me(account: string, section: MeSection, page: number, fresh?: boolean): Promise<MePage>;
}

class TauriTaskHost implements TaskHost {
  readonly kind = "tauri" as const;
  private core = () => import("@tauri-apps/api/core");
  async status(source: CliSource, fresh = false) {
    const { invoke } = await this.core();
    return invoke<CliStatus>("tasks_status", { source, fresh });
  }
  async list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number, account?: string) {
    const { invoke } = await this.core();
    return invoke<TaskPage>("tasks_list", { source, repo, kind, filter, page, account: account ?? null });
  }
  async view(source: CliSource, repo: string, kind: TaskKind, number: number, account?: string) {
    const { invoke } = await this.core();
    return invoke<TaskDetail>("tasks_view", { source, repo, kind, number, account: account ?? null });
  }
  async remote(cwd: string) {
    const { invoke } = await this.core();
    return invoke<TaskRemote | null>("tasks_remote", { cwd });
  }
  async ghAccounts(fresh = false) {
    const { invoke } = await this.core();
    return invoke<GhAccounts>("gh_accounts", { fresh });
  }
  async me(account: string, section: MeSection, page: number, fresh = false) {
    const { invoke } = await this.core();
    return invoke<MePage>("tasks_me", { account, section, page, fresh }).catch((e) => Promise.reject(failOf(e)));
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
  /** the GitHub accounts and the "나" lists */
  gh?: {
    installed?: boolean;
    accounts?: GhAccount[];
    /** `<login>@<host>:<section>` -> every row of that section */
    me?: Record<string, MeItem[]>;
    /** `<login>@<host>` -> why every list of that account fails */
    fail?: Record<string, { kind: MeFailKind; line: string }>;
  };
}

export type MockTaskCall =
  | { op: "status"; source: CliSource }
  | { op: "list"; source: CliSource; repo: string; kind: TaskKind; filter: TaskFilter; page: number; account?: string }
  | { op: "view"; source: CliSource; repo: string; kind: TaskKind; number: number; account?: string }
  | { op: "remote"; cwd: string }
  | { op: "ghAccounts"; fresh: boolean }
  | { op: "me"; account: string; section: MeSection; page: number; fresh: boolean };

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
  async list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number, account?: string) {
    this.log({ op: "list", source, repo, kind, filter, page, ...(account ? { account } : {}) });
    await new Promise((r) => setTimeout(r, 30));
    const err = this.data.errors?.[`${source}:${repo}`];
    if (err) throw new Error(err);
    const all = (this.data.items?.[`${source}:${repo}:${kind}`] ?? []).filter((i) =>
      filter === "assigned" ? i.assignee : filter === "created" ? i.mine : filter === "mentioned" ? i.mentions : true,
    );
    const items = all.slice(page * PAGE, (page + 1) * PAGE).map(({ assignee: _a, mine: _m, mentions: _n, ...i }) => i);
    return { items, more: all.length > (page + 1) * PAGE };
  }
  async view(source: CliSource, repo: string, kind: TaskKind, number: number, account?: string) {
    this.log({ op: "view", source, repo, kind, number, ...(account ? { account } : {}) });
    await new Promise((r) => setTimeout(r, 30));
    let row = (this.data.items?.[`${source}:${repo}:${kind}`] ?? []).find((i) => i.number === number);
    // a "나" row: the drawer reads it as its account
    if (!row && account)
      for (const [k, rows] of Object.entries(this.data.gh?.me ?? {})) {
        const m = k.startsWith(`${account}:`) ? rows.find((i) => i.repo === repo && i.number === number) : undefined;
        if (m) row = { number: m.number, title: m.title, state: m.state, url: m.url, labels: m.labels, author: m.author, created: m.created, updated: m.updated, checks: null };
      }
    if (!row) throw new Error(`no #${number}`);
    const { assignee: _a, mine: _m, mentions: _n, ...item } = row;
    const d = this.data.details?.[`${source}:${repo}:${kind}:${number}`] ?? {};
    return { item, body: d.body ?? "", comments: d.comments ?? [], checks: d.checks ?? [] };
  }
  async remote(cwd: string) {
    this.log({ op: "remote", cwd });
    return this.data.remotes?.[cwd] ?? null;
  }
  async ghAccounts(fresh = false) {
    this.log({ op: "ghAccounts", fresh });
    const gh = this.data.gh ?? {};
    return { installed: gh.installed ?? true, accounts: gh.accounts ?? [] };
  }
  async me(account: string, section: MeSection, page: number, fresh = false) {
    this.log({ op: "me", account, section, page, fresh });
    await new Promise((r) => setTimeout(r, 30));
    const fail = this.data.gh?.fail?.[account];
    if (fail) throw new MeFail(fail.kind, fail.line);
    const all = this.data.gh?.me?.[`${account}:${section}`] ?? [];
    const base = section === "mentions" ? 30 : 50;
    return { items: all.slice(page * base, (page + 1) * base), more: all.length > (page + 1) * base };
  }
}

// ---- Masking --------------------------------------------------------------------------------

const maskItem = (i: TaskItem): TaskItem => ({ ...i, title: maskSecrets(i.title), labels: i.labels.map((l) => ({ ...l, name: maskSecrets(l.name) })) });

/** A failed call as an Error whose message has no token-like string in it. */
const masked = (e: unknown) => new Error(maskSecrets(e instanceof Error ? e.message : String(e)));

/** `inner` with every text it answers (titles, labels, descriptions, comments, check names, error lines) passed
 *  through omher's one masker (src/lib/secrets.ts). The shell masks the same strings already; this keeps every
 *  surface the page draws from (the list, the drawer, Start in thread's text, the error line) masked whichever
 *  host answered. */
export class MaskingTaskHost implements TaskHost {
  constructor(private inner: TaskHost) {}
  get kind() {
    return this.inner.kind;
  }
  status(source: CliSource, fresh?: boolean) {
    return this.inner.status(source, fresh).catch((e) => Promise.reject(masked(e)));
  }
  async list(source: CliSource, repo: string, kind: TaskKind, filter: TaskFilter, page: number, account?: string): Promise<TaskPage> {
    const p = await this.inner.list(source, repo, kind, filter, page, account).catch((e) => Promise.reject(masked(e)));
    return { ...p, items: p.items.map(maskItem) };
  }
  async view(source: CliSource, repo: string, kind: TaskKind, number: number, account?: string): Promise<TaskDetail> {
    const d = await this.inner.view(source, repo, kind, number, account).catch((e) => Promise.reject(masked(e)));
    return {
      item: maskItem(d.item),
      body: maskSecrets(d.body),
      comments: d.comments.map((c) => ({ ...c, body: maskSecrets(c.body) })),
      checks: d.checks.map((c) => ({ ...c, name: maskSecrets(c.name) })),
    };
  }
  remote(cwd: string) {
    return this.inner.remote(cwd).catch((e) => Promise.reject(masked(e)));
  }
  ghAccounts(fresh?: boolean) {
    return this.inner.ghAccounts(fresh).catch((e) => Promise.reject(masked(e)));
  }
  async me(account: string, section: MeSection, page: number, fresh?: boolean): Promise<MePage> {
    const p = await this.inner.me(account, section, page, fresh).catch((e) => {
      const f = failOf(e);
      return Promise.reject(new MeFail(f.kind, maskSecrets(f.message)));
    });
    return { ...p, items: p.items.map((i) => ({ ...i, title: maskSecrets(i.title), labels: i.labels.map((l) => ({ ...l, name: maskSecrets(l.name) })) })) };
  }
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let host: TaskHost | null = null;
export function taskHost(): TaskHost {
  return (host ??= new MaskingTaskHost(inTauri() ? new TauriTaskHost() : new MockTaskHost()));
}
