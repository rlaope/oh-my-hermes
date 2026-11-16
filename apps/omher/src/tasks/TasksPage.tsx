// The Tasks page: open issues and pull / merge requests of one repository, from GitHub or GitLab through the person's
// own CLI (the desktop shell's tasks_* commands), read-only; Linear through the bot (connect screen). A row opens a
// read-only drawer; "Start in thread" hands the item to a bot, "Open terminal here" opens a TERMINALS shell in the
// repository's folder. omher writes nothing to GitHub, GitLab or Linear (BOUNDARY rule 33).
//
// After Orca's task page (stablyai/orca, MIT License, Copyright (c) 2026 Lovecast Inc.: task-page/TaskPage.tsx,
// SourceBar.tsx, ProviderFilters.tsx, ListChrome.tsx, PaginationBar.tsx); the layout is ported, the code is omher's.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../state/store";
import { t, type Key } from "../i18n";
import { CloseIcon, IconButton, Popover, PrIcon, SearchIcon, Spinner } from "../ui";
import { BotChip } from "../pages/kit";
import { Markdown } from "../chat/parts/Markdown";
import { CopyButton } from "../chat/parts/Copy";
import { openExternal } from "../lib/openExternal";
import { addTerminalTab, getTermPanel, setTerminalCwd } from "../terminal/state";
import { taskHost } from "./host";
import { setFilter, setKind, setPage, setRepo, setSource, useTasks } from "./state";
import { SourceMark, IssueMark } from "./marks";
import { firstMessage, threadTitle } from "./message";
import { SOURCE_NAME } from "./TasksBar";
import { FILTERS, KINDS, SOURCES, repoOk, type CliSource, type CliStatus, type TaskDetail, type TaskItem, type TaskPage as TPage } from "./types";
import "./tasks.css";

const FILTER_KEY: Record<string, Key> = { open: "tasks.f.open", assigned: "tasks.f.assigned", created: "tasks.f.created", mentioned: "tasks.f.mentioned" };

/** "now", "5m", "3h", "2d", "4mo", "1y": how long ago. */
export function ago(ts: number, nowMs = Date.now()): string {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(nowMs / 1000 - ts));
  if (s < 60) return t("time.nowShort");
  if (s < 3600) return t("unit.m", { n: Math.floor(s / 60) });
  if (s < 86_400) return t("unit.h", { n: Math.floor(s / 3600) });
  if (s < 30 * 86_400) return t("unit.d", { n: Math.floor(s / 86_400) });
  if (s < 365 * 86_400) return t("tasks.mo", { n: Math.floor(s / (30 * 86_400)) });
  return t("tasks.y", { n: Math.floor(s / (365 * 86_400)) });
}

const initials = (who: string) => (who.replace(/[^A-Za-z0-9]/g, "").slice(0, 2) || "?").toUpperCase();

/** A label in its own colour as a thin outline and dot (never a filled badge). */
function LabelChip({ name, color }: { name: string; color: string }) {
  const c = /^[0-9a-fA-F]{6}$/.test(color) ? `#${color}` : "var(--quiet)";
  return (
    <span className="tk-label" title={name}>
      <i style={{ background: c }} />
      {name}
    </span>
  );
}

function ChecksPill({ item }: { item: TaskItem }) {
  const c = item.checks;
  if (!c) return null;
  const tone = c.total === 0 ? "none" : c.failed ? "fail" : c.pending ? "pending" : "ok";
  const text =
    c.total === 0 ? t("tasks.checks.none") : c.failed ? t("tasks.checks.failing", { n: c.failed }) : c.pending ? t("tasks.checks.pending", { n: c.pending }) : t("tasks.checks.passing", { n: c.passed, total: c.total });
  return (
    <span className="tk-checks" data-tone={tone} data-testid="tasks-checks">
      {text}
    </span>
  );
}

function StateMark({ item, kind }: { item: TaskItem; kind: "issues" | "prs" }) {
  return kind === "prs" ? <PrIcon state={item.state === "closed" || item.state === "merged" || item.state === "draft" ? item.state : "open"} size={13} /> : <IssueMark state={item.state} />;
}

/** The folder the open thread (else the terminal panel's front tab) works in: where the default repository comes from. */
function useContextFolder(): string | null {
  const s = useStore();
  const bot = s.selectedBot;
  const thread = s.ui.thread;
  const threadCwd = bot && thread ? ((s.threads[bot] ?? []).find((r) => r.thread === thread)?.cwd ?? null) : null;
  if (threadCwd) return threadCwd;
  const tp = getTermPanel();
  return tp.tabs.find((x) => x.key === tp.active)?.cwd ?? tp.cwd ?? null;
}

function RepoPicker({ source, repo, recent, onPick }: { source: CliSource; repo: string; recent: string[]; onPick: (r: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const ok = repoOk(source, text.trim());
  const pick = (r: string) => {
    onPick(r);
    setOpen(false);
    setText("");
  };
  return (
    <span className="pg-chipwrap">
      <button type="button" className="tk-repo" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="tasks-repo">
        <SourceMark source={source} size={12} />
        <span>{repo || t("tasks.pickRepo")}</span>
      </button>
      <Popover open={open} onClose={() => setOpen(false)} align="left" width={280} label={t("tasks.pickRepo")}>
        <form
          className="tk-repo-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (ok) pick(text.trim());
          }}
        >
          <input
            autoFocus
            className="tk-repo-in"
            value={text}
            placeholder={source === "github" ? t("tasks.repoPhGh") : t("tasks.repoPhGl")}
            aria-label={t("tasks.pickRepo")}
            onChange={(e) => setText(e.target.value)}
            data-testid="tasks-repo-input"
          />
          <button type="submit" className="tk-btn" disabled={!ok} data-testid="tasks-repo-go">
            {t("tasks.show")}
          </button>
        </form>
        {recent.length > 0 && (
          <div className="tk-repo-list" role="listbox">
            {recent.map((r) => (
              <button key={r} type="button" role="option" aria-selected={r === repo} className={r === repo ? "on" : undefined} onClick={() => pick(r)}>
                {r}
              </button>
            ))}
          </div>
        )}
      </Popover>
    </span>
  );
}

function openShellAt(folder: string | null) {
  setTerminalCwd(folder);
  addTerminalTab();
}

export function TasksPage() {
  const s = useStore();
  const tk = useTasks();
  const host = taskHost();
  const ctx = useContextFolder();
  const cli: CliSource | null = tk.source === "linear" ? null : tk.source;
  const repo = cli ? tk.repo[cli] : "";
  const [status, setStatus] = useState<Partial<Record<CliSource, CliStatus>>>({});
  const [page, setPageData] = useState<TPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<TaskItem | null>(null);

  // the CLI's status, once per source shown
  useEffect(() => {
    if (!cli || status[cli]) return;
    void host.status(cli).then((st) => setStatus((m) => ({ ...m, [cli]: st })), () => setStatus((m) => ({ ...m, [cli]: { installed: false, signed_in: false } })));
  }, [cli, status, host]);

  // the default repository: the open thread's (or terminal's) folder's remote, when it is on this source
  const asked = useRef<string | null>(null);
  useEffect(() => {
    if (!ctx || asked.current === ctx) return;
    asked.current = ctx;
    void host.remote(ctx).then((r) => {
      if (!r) return;
      setRepo(r.source, r.repo, ctx);
      if (tk.source !== "linear" && tk.source !== r.source && !tk.repo[tk.source]) setSource(r.source);
    }, () => undefined);
  }, [ctx, host, tk.source, tk.repo]);

  const st = cli ? status[cli] : undefined;
  const ready = !!cli && !!repo && !!st?.installed && !!st?.signed_in;
  const load = useCallback(async () => {
    if (!cli || !repo) return;
    setLoading(true);
    setErr(null);
    try {
      setPageData(await host.list(cli, repo, tk.kind, tk.filter, tk.page));
    } catch (e) {
      setPageData(null);
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [cli, repo, tk.kind, tk.filter, tk.page, host]);
  useEffect(() => {
    if (ready) void load();
    else setPageData(null);
  }, [ready, load]);
  useEffect(() => setSel(null), [cli, repo, tk.kind]);

  const needle = q.trim().toLowerCase();
  const rows = useMemo(
    () => (page?.items ?? []).filter((i) => !needle || i.title.toLowerCase().includes(needle) || `#${i.number}`.includes(needle) || i.labels.some((l) => l.name.toLowerCase().includes(needle))),
    [page, needle],
  );
  const folder = cli && repo ? (tk.folders[`${cli}:${repo}`] ?? null) : null;
  const filters = cli === "gitlab" ? FILTERS.filter((f) => f !== "mentioned") : FILTERS;

  return (
    <div className="pg tk" data-testid="tasks-page">
      <header className="head pg-head tk-head" data-testid="header">
        <span className="head-title">{t("tasks.title")}</span>
        <nav className="tk-src" aria-label={t("tasks.sources")}>
          {SOURCES.map((src) => (
            <button key={src} type="button" className={`tk-src-b${tk.source === src ? " on" : ""}`} aria-pressed={tk.source === src} onClick={() => setSource(src)} data-testid={`tasks-src-${src}`}>
              <SourceMark source={src} size={12} />
              {SOURCE_NAME[src]}
            </button>
          ))}
        </nav>
        <div className="head-right">
          <IconButton label={t("tasks.close")} onClick={() => s.closeSettings()}>
            <CloseIcon />
          </IconButton>
        </div>
      </header>
      {cli ? (
        <div className={`tk-body${sel ? " has-detail" : ""}`}>
          <div className="tk-main">
            <div className="tk-chrome">
              <RepoPicker source={cli} repo={repo} recent={tk.recent[cli]} onPick={(r) => setRepo(cli, r)} />
              <div className="tk-seg" role="group" aria-label={t("tasks.kind")}>
                {KINDS.map((k) => (
                  <button key={k} type="button" className={tk.kind === k ? "on" : undefined} aria-pressed={tk.kind === k} onClick={() => setKind(k)} data-testid={`tasks-kind-${k}`}>
                    {k === "issues" ? t("tasks.issues") : cli === "gitlab" ? t("tasks.mrs") : t("tasks.prs")}
                  </button>
                ))}
              </div>
              <div className="tk-seg" role="group" aria-label={t("tasks.filter")}>
                {filters.map((f) => (
                  <button key={f} type="button" className={tk.filter === f ? "on" : undefined} aria-pressed={tk.filter === f} onClick={() => setFilter(f)} data-testid={`tasks-f-${f}`}>
                    {t(FILTER_KEY[f])}
                  </button>
                ))}
              </div>
              <label className="tk-search">
                <SearchIcon />
                <input type="search" value={q} placeholder={t("tasks.search")} aria-label={t("tasks.search")} onChange={(e) => setQ(e.target.value)} data-testid="tasks-search" />
              </label>
            </div>
            <div className="tk-list" data-testid="tasks-list">
              {!st ? (
                <div className="tk-empty">
                  <Spinner />
                </div>
              ) : !st.installed ? (
                <div className="tk-empty" data-testid="tasks-missing">
                  <p>{cli === "github" ? t("tasks.ghMissing") : t("tasks.glabMissing")}</p>
                </div>
              ) : !st.signed_in ? (
                <div className="tk-empty" data-testid="tasks-signin">
                  <p>{t("tasks.signIn", { cmd: cli === "github" ? "gh auth login" : "glab auth login" })}</p>
                  <div className="tk-acts">
                    <button type="button" className="tk-btn" onClick={() => openShellAt(null)} data-testid="tasks-signin-terminal">
                      {t("tasks.openTerminal")}
                    </button>
                    <button type="button" className="tk-btn ghost" onClick={() => setStatus((m) => ({ ...m, [cli]: undefined }))} data-testid="tasks-signin-again">
                      {t("tasks.checkAgain")}
                    </button>
                  </div>
                </div>
              ) : !repo ? (
                <div className="tk-empty" data-testid="tasks-norepo">
                  <p>{t("tasks.noRepo")}</p>
                </div>
              ) : err ? (
                <div className="tk-empty tk-err" data-testid="tasks-error">
                  <p>{t("page.failed", { error: err })}</p>
                  <button type="button" className="tk-btn ghost" onClick={() => void load()}>
                    {t("tasks.retry")}
                  </button>
                </div>
              ) : !page ? (
                <div className="tk-empty">
                  <Spinner />
                </div>
              ) : rows.length === 0 ? (
                <div className="tk-empty" data-testid="tasks-none">
                  <p>{needle ? t("tasks.noMatch") : t("tasks.none")}</p>
                </div>
              ) : (
                rows.map((i) => (
                  <button key={i.number} type="button" className={`tk-row${sel?.number === i.number ? " on" : ""}`} onClick={() => setSel(i)} data-testid={`tasks-row-${i.number}`}>
                    <span className="tk-row-st">
                      <StateMark item={i} kind={tk.kind} />
                    </span>
                    <span className="tk-row-n">#{i.number}</span>
                    <span className="tk-row-t">
                      <span className="tk-row-title">{i.title}</span>
                      {i.labels.slice(0, 4).map((l) => (
                        <LabelChip key={l.name} {...l} />
                      ))}
                    </span>
                    {tk.kind === "prs" && <ChecksPill item={i} />}
                    <span className="tk-who" title={i.author}>
                      {initials(i.author)}
                    </span>
                    <span className="tk-age" title={new Date(i.updated * 1000).toLocaleString()}>
                      {ago(i.updated || i.created)}
                    </span>
                  </button>
                ))
              )}
              {loading && page && <div className="tk-loading" aria-hidden="true" />}
            </div>
            {ready && page && (page.more || tk.page > 0) && (
              <nav className="tk-pages" aria-label={t("tasks.pages")} data-testid="tasks-pages">
                <button type="button" className="tk-btn ghost" disabled={tk.page === 0 || loading} onClick={() => setPage(tk.page - 1)} data-testid="tasks-prev">
                  {t("tasks.prev")}
                </button>
                <span className="tk-pages-n">{t("tasks.page", { n: tk.page + 1 })}</span>
                <button type="button" className="tk-btn ghost" disabled={!page.more || loading} onClick={() => setPage(tk.page + 1)} data-testid="tasks-next">
                  {t("tasks.next")}
                </button>
              </nav>
            )}
          </div>
          {sel && <Drawer source={cli} repo={repo} kind={tk.kind} item={sel} folder={folder ?? (ctx && tk.folders[`${cli}:${repo}`] ? ctx : null)} onClose={() => setSel(null)} />}
        </div>
      ) : (
        <LinearPane />
      )}
    </div>
  );
}

function Drawer({ source, repo, kind, item, folder, onClose }: { source: CliSource; repo: string; kind: "issues" | "prs"; item: TaskItem; folder: string | null; onClose: () => void }) {
  const s = useStore();
  const host = taskHost();
  const [d, setD] = useState<TaskDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [bot, setBot] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setD(null);
    setErr(null);
    host.view(source, repo, kind, item.number).then(
      (v) => live && setD(v),
      (e) => live && setErr(e instanceof Error ? e.message : String(e)),
    );
    return () => {
      live = false;
    };
  }, [source, repo, kind, item.number, host]);
  const local = s.bots.filter((b) => !b.host && b.status !== "offline");
  const to = local.find((b) => b.name === bot) ?? local.find((b) => b.name === s.selectedBot) ?? local[0];
  const start = async () => {
    if (!to || busy) return;
    setBusy(true);
    const detail = d ?? { item, body: "" };
    await s.startTaskThread(to.name, threadTitle(item), firstMessage(detail));
    setBusy(false);
  };
  return (
    <aside className="tk-drawer" aria-label={threadTitle(item)} data-testid="tasks-drawer">
      <div className="tk-dr-head">
        <StateMark item={item} kind={kind} />
        <span className="tk-dr-n">#{item.number}</span>
        <span className="tk-dr-state">{t(`tasks.st.${item.state}` as Key)}</span>
        <span className="tk-dr-sp" />
        <IconButton label={t("tasks.closeDetail")} onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <h2 className="tk-dr-title" data-testid="tasks-drawer-title">
        {item.title}
      </h2>
      <div className="tk-dr-meta">
        <span className="tk-who">{initials(item.author)}</span>
        <span>{item.author}</span>
        <span className="tk-age">{ago(item.created)}</span>
        {item.labels.map((l) => (
          <LabelChip key={l.name} {...l} />
        ))}
      </div>
      <div className="tk-dr-acts">
        <span className="tk-dr-start">
          <BotChip bots={local} bot={to} onPick={setBot} testId="tasks-bot" />
          <button type="button" className="tk-btn primary" disabled={!to || busy} onClick={() => void start()} data-testid="tasks-start">
            {t("tasks.startThread")}
          </button>
        </span>
        <button type="button" className="tk-btn ghost" disabled={!folder} title={folder ? folder : t("tasks.notCloned")} onClick={() => folder && openShellAt(folder)} data-testid="tasks-terminal">
          {t("tasks.terminalHere")}
        </button>
        <button type="button" className="tk-btn ghost" disabled={!item.url} onClick={() => void openExternal(item.url)} data-testid="tasks-browser">
          {t("tasks.openBrowser")}
        </button>
      </div>
      <div className="tk-dr-body">
        {err ? (
          <p className="tk-err">{t("page.failed", { error: err })}</p>
        ) : !d ? (
          <Spinner />
        ) : (
          <>
            {d.checks.length > 0 && (
              <section className="tk-dr-sec" data-testid="tasks-drawer-checks">
                <div className="tk-dr-sh">{t("tasks.checks")}</div>
                {d.checks.map((c, n) => (
                  <div key={`${c.name}-${n}`} className="tk-check" data-state={c.state}>
                    <i />
                    <span>{c.name}</span>
                    <span className="tk-check-st">{t(`tasks.ck.${c.state}` as Key)}</span>
                  </div>
                ))}
              </section>
            )}
            <section className="tk-dr-sec tk-md" data-testid="tasks-drawer-body">
              {d.body.trim() ? <Markdown text={d.body} /> : <p className="tk-quiet">{t("tasks.noBody")}</p>}
            </section>
            {d.comments.length > 0 && (
              <section className="tk-dr-sec" data-testid="tasks-drawer-comments">
                <div className="tk-dr-sh">{t("tasks.comments", { n: d.comments.length })}</div>
                {d.comments.map((c, n) => (
                  <div key={n} className="tk-cmt">
                    <div className="tk-cmt-h">
                      <span className="tk-who">{initials(c.author)}</span>
                      <span>{c.author}</span>
                      <span className="tk-age">{ago(c.created)}</span>
                    </div>
                    <div className="tk-md">
                      <Markdown text={c.body} />
                    </div>
                  </div>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

/** Linear: omher holds no Linear key. It asks whether the bot has a Linear MCP server in its Hermes config; Hermes'
 *  gateway has no call that runs an MCP tool for an app, so omher lists nothing itself and says how to connect. */
function LinearPane() {
  const s = useStore();
  const local = s.bots.filter((b) => !b.host);
  const [pick, setPick] = useState<string | null>(null);
  const bot = local.find((b) => b.name === pick) ?? local.find((b) => b.name === s.selectedBot) ?? local[0];
  const [res, setRes] = useState<{ configured: boolean; server: string } | null>(null);
  useEffect(() => {
    if (!bot) return;
    let live = true;
    setRes(null);
    s.tasksLinear(bot.name).then(
      (r) => live && setRes(r),
      () => live && setRes({ configured: false, server: "" }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot?.name]);
  const cmd = bot ? `hermes -p ${bot.name} mcp install linear` : "";
  return (
    <div className="tk-linear" data-testid="tasks-linear">
      <div className="tk-chrome">
        <BotChip bots={local} bot={bot} onPick={setPick} testId="tasks-linear-bot" />
      </div>
      {!bot ? null : !res ? (
        <Spinner />
      ) : res.configured ? (
        <div className="tk-empty" data-testid="tasks-linear-on">
          <p>{t("tasks.linearOn", { bot: bot.display_name, server: res.server })}</p>
        </div>
      ) : (
        <div className="tk-empty" data-testid="tasks-linear-connect">
          <p className="tk-big">{t("tasks.linearConnect", { bot: bot.display_name })}</p>
          <p>{t("tasks.linearHow")}</p>
          <code className="tk-cmd" data-testid="tasks-linear-cmd">
            {cmd}
            <CopyButton text={() => cmd} />
          </code>
          <div className="tk-acts">
            <button type="button" className="tk-btn" onClick={() => openShellAt(null)} data-testid="tasks-linear-terminal">
              {t("tasks.openTerminal")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
