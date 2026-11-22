// Tasks › 나 (Me): across every repository, for the GitHub accounts chosen in Settings › Accounts, the open pull
// requests that ask for my review, my own open pull requests, the open issues assigned to me and the last week's
// mentions of me. Items needing action come first (CI failed, changes requested, merge conflict, then review requests
// by how long they waited); the list groups by section or by repository. Keys: j / k move, Enter opens the drawer, o
// opens the item in the browser, t starts a thread on it. Read-only (BOUNDARY rule 33): the only actions are Open in
// browser, Start in thread and Open terminal here (a clone omher knows), all in the same drawer as "이 저장소".
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { Spinner } from "../ui";
import { openExternal } from "../lib/openExternal";
import { taskHost } from "./host";
import { setGroup, setMeAccount, setMentionsOpen, useTasks } from "./state";
import { accountState, chipsFor, detectAccounts, groupRows, readAccount, readMore, refreshMe, shownAccounts, useMeData, waitingSince, type Chip, type MeRow } from "./me";
import { firstMessage, threadTitle } from "./message";
import { Drawer, StateMark, ago } from "./TasksPage";
import { ME_SECTIONS, accountId, type MeItem, type MeSection, type TaskItem } from "./types";
import "./tasks.css";

const SECTION_KEY = { review: "tasks.me.review", authored: "tasks.me.authored", assigned: "tasks.me.assigned", mentions: "tasks.me.mentions" } as const;

/** An account's colour dot. */
export function AccountDot({ color }: { color: string }) {
  return <i className="tk-dot" style={{ background: color }} aria-hidden="true" />;
}

/** A "나" row as the drawer's item. */
export const asTaskItem = (r: MeItem): TaskItem => ({ number: r.number, title: r.title, state: r.state, url: r.url, labels: r.labels, author: r.author, created: r.created, updated: r.updated, checks: null });

const rowKey = (r: MeRow) => `${r.account}|${r.repo}#${r.number}|${r.section}`;

function chipText(c: Chip, r: MeItem): string {
  switch (c.kind) {
    case "draft":
      return t("tasks.st.draft");
    case "ciPassed":
      return t("tasks.chip.ciPassed");
    case "ciFailed":
      return t("tasks.chip.ciFailed");
    case "ciPending":
      return t("tasks.chip.ciPending");
    case "approved":
      return t("tasks.chip.approved");
    case "changes":
      return t("tasks.chip.changes");
    case "conflict":
      return t("tasks.chip.conflict");
    case "waiting":
      return t("tasks.chip.waiting", { age: ago(waitingSince(r)) });
  }
}

export function MeView() {
  const s = useStore();
  const tk = useTasks();
  const me = useMeData();
  const [sel, setSel] = useState<MeRow | null>(null);
  const [cursor, setCursor] = useState(0);
  const rowsRef = useRef(new Map<string, HTMLButtonElement>());
  const ids = shownAccounts(tk.accounts, tk.meAccount);
  const idsKey = ids.join(",");

  // read on open: gh's accounts (a chip's "sign in again") and every shown account's lists not read yet
  useEffect(() => {
    void detectAccounts();
  }, []);
  useEffect(() => {
    for (const id of idsKey ? idsKey.split(",") : []) if (!me.lists[id]) void readAccount(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const colorOf = useMemo(() => Object.fromEntries(tk.accounts.map((a) => [accountId(a), a.color])), [tk.accounts]);
  const rows = useMemo<MeRow[]>(
    () => ids.flatMap((id) => ME_SECTIONS.flatMap((sec) => (me.lists[id]?.sections[sec]?.items ?? []).map((i) => ({ ...i, account: id, section: sec })))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [me.lists, idsKey],
  );
  const groups = useMemo(() => groupRows(rows, tk.group), [rows, tk.group]);
  const folded = (key: string) => tk.group === "section" && key === "mentions" && !tk.mentionsOpen;
  const visible = useMemo(() => groups.flatMap((g) => (folded(g.key) ? [] : g.rows)), [groups, tk.group, tk.mentionsOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tk.accounts.length) {
    return (
      <div className="tk-empty tk-me-connect" data-testid="me-connect">
        <p>{t("tasks.me.connectLine")}</p>
        <button type="button" className="tk-btn primary" onClick={() => s.openSettings("accounts")} data-testid="me-connect-btn">
          {t("tasks.me.connect")}
        </button>
      </div>
    );
  }

  const lists = ids.map((id) => me.lists[id]);
  const loading = lists.some((l) => !l || l.loading);
  const rate = lists.some((l) => l?.rate);
  const failed = ids.filter((id) => me.lists[id]?.fail && me.lists[id]?.fail?.kind !== "auth");
  const relogin = (id: string) => {
    const a = tk.accounts.find((x) => accountId(x) === id);
    return me.lists[id]?.fail?.kind === "auth" || (!!a && accountState(a, me.detected) === "relogin");
  };
  const loginOf = (id: string) => id.slice(0, id.indexOf("@"));

  const startThread = async (r: MeRow) => {
    const local = s.bots.filter((b) => !b.host && b.status !== "offline");
    const to = local.find((b) => b.name === s.selectedBot) ?? local[0];
    if (!to) return;
    const item = asTaskItem(r);
    const d = await taskHost()
      .view("github", r.repo, r.pr ? "prs" : "issues", r.number, r.account)
      .catch(() => null);
    await s.startTaskThread(to.name, threadTitle(item), firstMessage(d ?? { item, body: "" }));
  };

  const focusRow = (n: number) => {
    const r = visible[Math.max(0, Math.min(visible.length - 1, n))];
    if (!r) return;
    setCursor(visible.indexOf(r));
    rowsRef.current.get(rowKey(r))?.focus();
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement).closest("input, textarea")) return;
    const r = visible[cursor];
    if (e.key === "j" || e.key === "ArrowDown") focusRow(cursor + 1);
    else if (e.key === "k" || e.key === "ArrowUp") focusRow(cursor - 1);
    // Enter on a row opens its drawer; on any other button (Show more, the mentions header) it presses that button
    else if (e.key === "Enter" && r && (e.target as HTMLElement).closest(".tk-me-row")) setSel(r);
    else if (e.key === "o" && r?.url) void openExternal(r.url);
    else if (e.key === "t" && r) void startThread(r);
    else return;
    e.preventDefault();
  };

  const moreFor = (sec: MeSection) => ids.filter((id) => me.lists[id]?.sections[sec]?.more);

  return (
    <div className={`tk-body${sel ? " has-detail" : ""}`} data-testid="me-view">
      <div className="tk-main">
        <div className="tk-chrome">
          <div className="tk-seg" role="group" aria-label={t("tasks.me.accounts")}>
            <button type="button" className={tk.meAccount === "all" ? "on" : undefined} aria-pressed={tk.meAccount === "all"} onClick={() => setMeAccount("all")} data-testid="me-acct-all">
              {t("tasks.me.all")}
            </button>
            {tk.accounts.map((a) => {
              const id = accountId(a);
              const bad = relogin(id);
              return (
                <button
                  key={id}
                  type="button"
                  className={tk.meAccount === id ? "on" : undefined}
                  aria-pressed={tk.meAccount === id}
                  title={bad ? t("tasks.me.reloginTip", { account: a.login, error: me.lists[id]?.fail?.line ?? t("acc.gh.gone") }) : `${a.login} · ${a.host}`}
                  data-state={bad ? "relogin" : "ok"}
                  onClick={() => setMeAccount(id)}
                  data-testid={`me-acct-${a.login}`}
                >
                  <AccountDot color={a.color} />
                  {a.login}
                  {bad && (
                    <span className="tk-relogin" data-testid={`me-relogin-${a.login}`}>
                      {t("tasks.me.relogin")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <div className="tk-seg" role="group" aria-label={t("tasks.me.group")}>
            {(["section", "repo"] as const).map((g) => (
              <button key={g} type="button" className={tk.group === g ? "on" : undefined} aria-pressed={tk.group === g} onClick={() => setGroup(g)} data-testid={`me-group-${g}`}>
                {g === "section" ? t("tasks.me.bySection") : t("tasks.me.byRepo")}
              </button>
            ))}
          </div>
          <span className="tk-me-keys">{t("tasks.me.keys")}</span>
          <button type="button" className="tk-btn ghost tk-me-refresh" aria-label={t("tasks.me.refresh")} title={t("tasks.me.refresh")} disabled={loading} onClick={() => void refreshMe(true)} data-testid="me-refresh">
            ⟳
          </button>
        </div>
        {rate && (
          <p className="tk-me-note" role="status" data-testid="me-rate">
            {t("tasks.me.rate")}
          </p>
        )}
        {failed.map((id) => (
          <p key={id} className="tk-me-note tk-err" data-testid={`me-failed-${loginOf(id)}`}>
            {t("tasks.me.failed", { account: loginOf(id), error: me.lists[id]?.fail?.line ?? "" })}
          </p>
        ))}
        <div className="tk-list" data-testid="me-list" onKeyDown={onKey}>
          {rows.length === 0 && loading ? (
            <div className="tk-empty">
              <Spinner />
            </div>
          ) : (
            groups.map((g) => {
              const sec = tk.group === "section" ? (g.key as MeSection) : null;
              const more = sec ? moreFor(sec) : [];
              return (
                <section key={g.key} className="tk-me-sec" data-testid={`me-sec-${g.key}`}>
                  {sec === "mentions" ? (
                    <button type="button" className="tk-me-sh tk-me-fold" aria-expanded={tk.mentionsOpen} onClick={() => setMentionsOpen(!tk.mentionsOpen)} data-testid="me-sec-mentions-toggle">
                      <span aria-hidden="true">{tk.mentionsOpen ? "▾" : "▸"}</span> {t(SECTION_KEY.mentions)} <span className="tk-me-n">{g.rows.length}</span>
                    </button>
                  ) : (
                    <div className="tk-me-sh">
                      {sec ? t(SECTION_KEY[sec]) : g.key} <span className="tk-me-n">{g.rows.length}</span>
                    </div>
                  )}
                  {!folded(g.key) &&
                    (g.rows.length === 0 ? (
                      <p className="tk-me-none">{t("tasks.me.none")}</p>
                    ) : (
                      g.rows.map((r) => {
                        const k = rowKey(r);
                        const n = visible.indexOf(r);
                        return (
                          <button
                            key={k}
                            ref={(el) => {
                              if (el) rowsRef.current.set(k, el);
                              else rowsRef.current.delete(k);
                            }}
                            type="button"
                            className={`tk-row tk-me-row${sel && rowKey(sel) === k ? " on" : ""}${n === cursor ? " cur" : ""}`}
                            onClick={() => {
                              setCursor(n);
                              setSel(r);
                            }}
                            onFocus={() => setCursor(n)}
                            data-testid={`me-row-${r.repo}#${r.number}`}
                            data-account={r.account}
                            data-section={r.section}
                          >
                            <AccountDot color={colorOf[r.account] ?? "var(--quiet)"} />
                            <span className="tk-row-st">
                              <StateMark item={asTaskItem(r)} kind={r.pr ? "prs" : "issues"} />
                            </span>
                            <span className="tk-me-repo">{r.repo}</span>
                            <span className="tk-row-n">#{r.number}</span>
                            <span className="tk-row-t">
                              <span className="tk-row-title">{r.title}</span>
                            </span>
                            {chipsFor(r).map((c) => (
                              <span key={c.kind} className="tk-chip" data-tone={c.tone} data-chip={c.kind}>
                                {chipText(c, r)}
                              </span>
                            ))}
                            <span className="tk-age" title={new Date(r.updated * 1000).toLocaleString()}>
                              {ago(r.updated || r.created)}
                            </span>
                          </button>
                        );
                      })
                    ))}
                  {!folded(g.key) && sec && more.length > 0 && (
                    <button type="button" className="tk-btn ghost tk-me-more" onClick={() => more.forEach((id) => void readMore(id, sec))} data-testid={`me-more-${sec}`}>
                      {t("tasks.me.more")}
                    </button>
                  )}
                </section>
              );
            })
          )}
        </div>
      </div>
      {sel && (
        <Drawer
          source="github"
          repo={sel.repo}
          kind={sel.pr ? "prs" : "issues"}
          item={asTaskItem(sel)}
          account={sel.account}
          folder={tk.folders[`github:${sel.repo}`] ?? null}
          onClose={() => setSel(null)}
        />
      )}
    </div>
  );
}
