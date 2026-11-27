// Tasks › GitHub, the dashboard: one screen, three columns that each scroll inside themselves. Left, the repositories
// the person pinned ("모든 repo" first; a dot for each default branch's CI; suggestions from folders omher knows);
// centre, the open pull requests of the repositories picked on the left, in GitHub's list style, with the tabs "전체"
// and "내 리뷰 요청"; right, the recent Actions runs above the latest Releases (with the commits the default branch has
// since). A pull request opens the same read-only drawer as the rest of Tasks (Start in thread, Open terminal here,
// Open in browser); a run or a release opens in the browser. Read-only (BOUNDARY rule 51).
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useStore } from "../state/store";
import { t, type Key } from "../i18n";
import { IconButton, PrIcon, Spinner } from "../ui";
import { openExternal } from "../lib/openExternal";
import { getTermPanel } from "../terminal/state";
import { pinRepo, setDashRepo, setDashTab, unpinRepo, useTasks } from "./state";
import { dashAccount, findRepos, getDash, formatDuration, inTab, prsOf, refreshDash, readRepo, releasesOf, runSeconds, runsOf, shownRepos, startDashPolling, suggestions, tabCounts, useDash } from "./dash";
import { asTaskItem } from "./MeView";
import { Drawer, ago } from "./TasksPage";
import { DASH_TABS, repoOk, type DashRun, type MeItem, type TaskLabel } from "./types";
import "./tasks.css";

const CI_MARK: Record<string, string> = { passed: "✓", failed: "✗", pending: "●" };
const RUN_MARK: Record<DashRun["state"], string> = { passed: "✓", failed: "✗", pending: "●", cancelled: "⊘", skipped: "–" };

/** A label as GitHub draws it: a pill in the label's own colour (a tint, an outline and a lighter text). */
function Pill({ name, color }: TaskLabel) {
  const ok = /^[0-9a-fA-F]{6}$/.test(color);
  const n = ok ? parseInt(color, 16) : 0;
  const rgb = `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  const style = ok ? ({ "--lc": `#${color}`, background: `rgba(${rgb}, 0.18)`, borderColor: `rgba(${rgb}, 0.5)` } as CSSProperties) : undefined;
  return (
    <span className="tk-pill" style={style} title={name}>
      {name}
    </span>
  );
}

function reviewWord(p: MeItem): { text: string; tone: string } | null {
  if (p.conflict) return { text: t("tasks.chip.conflict"), tone: "fail" };
  if (p.draft) return { text: t("tasks.st.draft"), tone: "quiet" };
  if (p.review === "approved") return { text: t("tasks.chip.approved"), tone: "ok" };
  if (p.review === "changes") return { text: t("tasks.chip.changes"), tone: "fail" };
  if (p.review === "required") return { text: t("tasks.gh.required"), tone: "quiet" };
  return null;
}

/** The folders omher knows: every thread's, and the terminal panel's tabs. */
function useKnownFolders(): string[] {
  const s = useStore();
  return useMemo(() => {
    const out = new Set<string>();
    for (const rows of Object.values(s.threads)) for (const r of rows) if (r.cwd) out.add(r.cwd);
    for (const tab of getTermPanel().tabs) {
      const f = tab.cwd ?? tab.want;
      if (f) out.add(f);
    }
    return [...out];
  }, [s.threads]);
}

export function DashView() {
  const s = useStore();
  const tk = useTasks();
  const dash = useDash();
  const folders = useKnownFolders();
  const [sel, setSel] = useState<MeItem | null>(null);
  const [text, setText] = useState("");
  const hasAccount = tk.accounts.some((a) => a.host === "github.com");
  const pinsKey = tk.pins.join(",");

  useEffect(() => (hasAccount ? startDashPolling() : undefined), [hasAccount]);
  // a repository pinned since: read it now
  useEffect(() => {
    if (hasAccount) for (const r of pinsKey ? pinsKey.split(",") : []) if (!getDash().repos[r]) void readRepo(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinsKey, hasAccount]);
  const foldersKey = folders.join("\n");
  useEffect(() => {
    void findRepos(foldersKey ? foldersKey.split("\n") : []);
  }, [foldersKey]);

  const repos = shownRepos(tk.pins, tk.dashRepo);
  const prs = useMemo(() => prsOf(dash.repos, repos), [dash.repos, repos.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = tabCounts(prs);
  const rows = inTab(prs, tk.dashTab);
  const runs = useMemo(() => runsOf(dash.repos, repos), [dash.repos, repos.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const releases = useMemo(() => releasesOf(dash.repos, repos), [dash.repos, repos.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  // what Tasks already knows (a repository found in a folder) and what the folders hold now
  const known = Object.keys(tk.folders)
    .filter((k) => k.startsWith("github:"))
    .map((k) => ({ source: "github" as const, repo: k.slice("github:".length) }));
  const suggest = suggestions(tk.pins, [...dash.found, ...known]);

  if (!hasAccount) {
    return (
      <div className="tk-empty tk-me-connect" data-testid="dash-connect">
        <p>{t("tasks.gh.connectLine")}</p>
        <button type="button" className="tk-btn primary" onClick={() => s.openSettings("accounts")} data-testid="dash-connect-btn">
          {t("tasks.me.connect")}
        </button>
      </div>
    );
  }

  const states = tk.pins.map((r) => dash.repos[r]);
  const loading = states.some((x) => x?.loading);
  const rate = states.some((x) => x?.rate);
  const failed = repos.filter((r) => dash.repos[r]?.fail);
  const lastRead = Math.max(0, ...states.map((x) => x?.at ?? 0));
  const ok = repoOk("github", text.trim());
  const pin = () => {
    if (ok && pinRepo(text.trim())) setText("");
  };
  const allPrs = prsOf(dash.repos, tk.pins).length;

  return (
    <div className="tk-dash" data-testid="dash-view">
      <div className="tk-dash-bar">
        {rate && (
          <span className="tk-me-note" role="status" data-testid="dash-rate">
            {t("tasks.me.rate")}
          </span>
        )}
        <span className="tk-dash-sp" />
        {lastRead > 0 && <span className="tk-dash-at">{t("tasks.gh.readAt", { time: new Date(lastRead).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) })}</span>}
        <button type="button" className="tk-btn ghost tk-me-refresh" aria-label={t("tasks.me.refresh")} title={t("tasks.me.refresh")} disabled={loading || !tk.pins.length} onClick={() => void refreshDash(true)} data-testid="dash-refresh">
          ⟳
        </button>
      </div>
      <div className="tk-dash-cols">
        {/* left: the pinned repositories */}
        <section className="tk-dash-col tk-dash-repos" aria-label={t("tasks.gh.repos")} data-testid="dash-repos">
          <div className="tk-dash-h">{t("tasks.gh.repos")}</div>
          <div className="tk-dash-scroll">
            <button type="button" className={`tk-dash-repo${tk.dashRepo === "all" ? " on" : ""}`} aria-pressed={tk.dashRepo === "all"} onClick={() => setDashRepo("all")} data-testid="dash-repo-all">
              <span className="tk-dash-av">*</span>
              <span className="tk-dash-rn">
                <b>{t("tasks.gh.allRepos")}</b>
                <small>{t("tasks.gh.allSub", { n: tk.pins.length, prs: allPrs })}</small>
              </span>
            </button>
            {tk.pins.map((r) => {
              const st = dash.repos[r];
              const ci = st?.data?.ci ?? "";
              return (
                <div key={r} className={`tk-dash-repo-row${tk.dashRepo === r ? " on" : ""}`}>
                  <button type="button" className={`tk-dash-repo${tk.dashRepo === r ? " on" : ""}`} aria-pressed={tk.dashRepo === r} onClick={() => setDashRepo(r)} data-testid={`dash-repo-${r}`}>
                    <span className="tk-dash-av">{r.split("/")[1]?.[0]?.toUpperCase() ?? "?"}</span>
                    <span className="tk-dash-rn">
                      <b title={r}>{r}</b>
                      <small>{st?.data ? t("tasks.gh.repoSub", { n: st.data.prs.length }) : st && !st.loading ? t("tasks.gh.unread") : "…"}</small>
                    </span>
                    {ci && (
                      <i
                        className="tk-dash-ci"
                        data-ci={ci}
                        title={t(`tasks.gh.ci.${ci}` as Key, { branch: st?.data?.branch || "main" })}
                        aria-label={t(`tasks.gh.ci.${ci}` as Key, { branch: st?.data?.branch || "main" })}
                        data-testid={`dash-ci-${r}`}
                      />
                    )}
                  </button>
                  <IconButton className="tk-dash-x" label={t("tasks.gh.unpin", { repo: r })} onClick={() => unpinRepo(r)} data-testid={`dash-unpin-${r}`}>
                    ×
                  </IconButton>
                </div>
              );
            })}
            {suggest.length > 0 && (
              <div className="tk-dash-sug" data-testid="dash-suggest">
                <div className="tk-dash-sh">{t("tasks.gh.suggested")}</div>
                {suggest.map((r) => (
                  <button key={r} type="button" className="tk-dash-sug-b" onClick={() => pinRepo(r)} aria-label={t("tasks.gh.pinThis", { repo: r })} data-testid={`dash-suggest-${r}`}>
                    <span aria-hidden="true">+</span>
                    {r}
                  </button>
                ))}
              </div>
            )}
          </div>
          <form
            className="tk-dash-pin"
            onSubmit={(e) => {
              e.preventDefault();
              pin();
            }}
          >
            <input value={text} placeholder={t("tasks.repoPhGh")} aria-label={t("tasks.gh.pinLabel")} onChange={(e) => setText(e.target.value)} data-testid="dash-pin-input" />
            <button type="submit" className="tk-btn" disabled={!ok} data-testid="dash-pin-go">
              {t("tasks.gh.pin")}
            </button>
          </form>
        </section>

        {/* centre: the open pull requests */}
        <section className="tk-dash-col tk-dash-prs" aria-label={t("tasks.prs")} data-testid="dash-prs">
          <div className="tk-dash-tabs" role="tablist">
            {DASH_TABS.map((tab) => (
              <button key={tab} type="button" role="tab" aria-selected={tk.dashTab === tab} className={tk.dashTab === tab ? "on" : undefined} onClick={() => setDashTab(tab)} data-testid={`dash-tab-${tab}`}>
                {tab === "all" ? t("tasks.gh.tab.all") : t("tasks.gh.tab.asked")}
                <span className="tk-dash-count">{counts[tab]}</span>
              </button>
            ))}
          </div>
          <div className="tk-dash-lh" data-testid="dash-open-count">
            <PrIcon state="open" size={14} />
            <b>{t("tasks.gh.openCount", { n: rows.length })}</b>
          </div>
          {failed.map((r) => (
            <p key={r} className="tk-me-note tk-err" data-testid={`dash-failed-${r}`}>
              {t("tasks.gh.failed", { repo: r, error: dash.repos[r]?.fail?.line ?? "" })}
            </p>
          ))}
          <div className="tk-dash-scroll" data-testid="dash-pr-list">
            {!tk.pins.length ? (
              <p className="tk-dash-none" data-testid="dash-no-pins">
                {t("tasks.gh.noPins")}
              </p>
            ) : rows.length === 0 && repos.some((r) => !dash.repos[r]?.data && !dash.repos[r]?.fail) ? (
              <div className="tk-empty">
                <Spinner />
              </div>
            ) : rows.length === 0 ? (
              <p className="tk-dash-none" data-testid="dash-no-prs">
                {tk.dashTab === "asked" ? t("tasks.gh.noAsked") : t("tasks.gh.noPrs")}
              </p>
            ) : (
              rows.map((p) => {
                const rv = reviewWord(p);
                const k = `${p.repo}#${p.number}`;
                return (
                  <div key={k} className={`tk-dash-pr${sel && `${sel.repo}#${sel.number}` === k ? " on" : ""}`} data-testid={`dash-pr-${k}`}>
                    <button type="button" className="tk-dash-pr-main" onClick={() => setSel(p)}>
                      <span className="tk-dash-pr-ic">
                        <PrIcon state={p.draft ? "draft" : "open"} size={14} />
                      </span>
                      <span className="tk-dash-pr-body">
                        <span className="tk-dash-pr-l1">
                          {repos.length > 1 && <span className="tk-dash-pr-repo">{p.repo}</span>}
                          <span className="tk-dash-pr-title">{p.title}</span>
                          {p.ci && (
                            <span className="tk-dash-mark" data-ci={p.ci} title={t(`tasks.chip.ci${p.ci[0].toUpperCase()}${p.ci.slice(1)}` as Key)} data-testid={`dash-pr-ci-${k}`}>
                              {CI_MARK[p.ci]}
                            </span>
                          )}
                          {p.labels.slice(0, 5).map((l) => (
                            <Pill key={l.name} {...l} />
                          ))}
                        </span>
                        <span className="tk-dash-pr-l2">
                          #{p.number} · {t("tasks.gh.updated", { age: ago(p.updated || p.created) })} · {p.author}
                          {rv && (
                            <>
                              {" · "}
                              <span className="tk-dash-rv" data-tone={rv.tone}>
                                {rv.text}
                              </span>
                            </>
                          )}
                          {p.asked && (
                            <>
                              {" · "}
                              <span className="tk-dash-rv" data-tone="asked" data-testid={`dash-asked-${k}`}>
                                {t("tasks.gh.askedMe")}
                              </span>
                            </>
                          )}
                        </span>
                      </span>
                    </button>
                    <IconButton className="tk-dash-x" label={t("tasks.openBrowser")} disabled={!p.url} onClick={() => p.url && void openExternal(p.url)} data-testid={`dash-pr-open-${k}`}>
                      ↗
                    </IconButton>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* right: Actions above Releases */}
        <div className="tk-dash-col tk-dash-side">
          <section className="tk-dash-box" aria-label={t("tasks.gh.actions")} data-testid="dash-actions">
            <div className="tk-dash-h">
              {t("tasks.gh.actions")}
              <span className="tk-dash-count">{t("tasks.gh.runs", { n: runs.length })}</span>
            </div>
            <div className="tk-dash-scroll">
              {runs.length === 0 ? (
                <p className="tk-dash-none">{t("tasks.gh.noRuns")}</p>
              ) : (
                runs.map((r) => {
                  const secs = runSeconds(r);
                  return (
                    <button key={`${r.repo}-${r.id}`} type="button" className="tk-dash-run" disabled={!r.url} onClick={() => r.url && void openExternal(r.url)} data-testid={`dash-run-${r.id}`}>
                      <span className="tk-dash-mark" data-ci={r.state} title={t(`tasks.gh.run.${r.state}` as Key)}>
                        {RUN_MARK[r.state]}
                      </span>
                      <span className="tk-dash-run-b">
                        <b>{r.workflow || r.title}</b>
                        <small>
                          {r.repo} · {r.branch}
                        </small>
                      </span>
                      <span className="tk-dash-when">
                        <span>{ago(r.created || r.started)}</span>
                        {secs !== null && <small>{formatDuration(secs)}</small>}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </section>
          <section className="tk-dash-box" aria-label={t("tasks.gh.releases")} data-testid="dash-releases">
            <div className="tk-dash-h">{t("tasks.gh.releases")}</div>
            <div className="tk-dash-scroll">
              {releases.length === 0 ? (
                <p className="tk-dash-none">{t("tasks.gh.noRelease")}</p>
              ) : (
                releases.map((x) => (
                  <button key={x.repo} type="button" className="tk-dash-rel" disabled={!x.release.url} onClick={() => x.release.url && void openExternal(x.release.url)} data-testid={`dash-release-${x.repo}`}>
                    <span className="tk-dash-rel-l1">
                      <b>{x.release.tag}</b>
                      {x.release.latest && <span className="tk-dash-latest">{t("tasks.gh.latest")}</span>}
                      {x.release.prerelease && <span className="tk-dash-pre">{t("tasks.gh.pre")}</span>}
                      <span className="tk-dash-sp" />
                      <small>{ago(x.release.published)}</small>
                    </span>
                    <small className="tk-dash-rel-l2">
                      {x.repo}
                      {x.ahead !== null && x.branch && <> · {t("tasks.gh.ahead", { n: x.ahead, branch: x.branch })}</>}
                    </small>
                  </button>
                ))
              )}
            </div>
          </section>
        </div>
      </div>
      {sel && (
        <div className="tk-dash-drawer">
          <Drawer
            source="github"
            repo={sel.repo}
            kind="prs"
            item={asTaskItem(sel)}
            account={dashAccount(tk.accounts, sel.repo) ?? undefined}
            folder={tk.folders[`github:${sel.repo}`] ?? null}
            onClose={() => setSel(null)}
          />
        </div>
      )}
    </div>
  );
}
