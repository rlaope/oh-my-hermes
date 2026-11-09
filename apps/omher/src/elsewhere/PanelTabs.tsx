// Right panel tabs next to Details: Terminal, Schedule, Worktrees, Diff. Everything here is read-only:
// the bot runs things, omher shows what it ran and what it changed.
import { useEffect, useMemo, useState, type ReactElement } from "react";
import type { Bot, Routine, TerminalRun, Worktree, WorktreeDiff } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { shortTime } from "../app/time";
import { SourceIcon, Spinner } from "../ui";
import { cadence, nextRun, sourceName } from "./format";
import "./panel.css";

export type PanelTab = "details" | "terminal" | "schedule" | "worktrees" | "diff" | "runs";

export const TABS: { id: PanelTab; label: string }[] = [
  { id: "details", label: "Details" },
  { id: "terminal", label: "Terminal" },
  { id: "schedule", label: "Schedule" },
  { id: "worktrees", label: "Worktrees" },
  { id: "diff", label: "Diff" },
  { id: "runs", label: "Runs" },
];

const I = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
export const TAB_ICON: Record<PanelTab, ReactElement> = {
  details: (
    <svg viewBox="0 0 24 24" {...I}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7.5v.01" />
    </svg>
  ),
  terminal: (
    <svg viewBox="0 0 24 24" {...I}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="m7 9 3 3-3 3M13 15h4" />
    </svg>
  ),
  schedule: (
    <svg viewBox="0 0 24 24" {...I}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  ),
  worktrees: (
    <svg viewBox="0 0 24 24" {...I}>
      <circle cx="6" cy="5" r="2" />
      <circle cx="6" cy="19" r="2" />
      <circle cx="18" cy="8" r="2" />
      <path d="M6 7v10M18 10c0 4-5 4-11 7" />
    </svg>
  ),
  diff: (
    <svg viewBox="0 0 24 24" {...I}>
      <path d="M8 3v8M4 7h8M4 18h8M15 6h6M15 18h6M15 12h6" />
    </svg>
  ),
  // three nodes with edges: one on the left feeding two on the right
  runs: (
    <svg viewBox="0 0 24 24" {...I}>
      <rect x="2.5" y="9.5" width="5" height="5" rx="1" />
      <rect x="16.5" y="3.5" width="5" height="5" rx="1" />
      <rect x="16.5" y="15.5" width="5" height="5" rx="1" />
      <path d="M7.5 12c4.5 0 4.5-6 9-6M7.5 12c4.5 0 4.5 6 9 6" />
    </svg>
  ),
};

/** Load once per (bot, tab open); `reload` re-reads. */
function useLoad<T>(key: string, load: () => Promise<T>): { data: T | null; error: string | null; reload: () => void } {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null }>({ key: "", data: null, error: null });
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setState((s) => (s.key === key ? s : { key, data: null, error: null }));
    load().then(
      (data) => live && setState({ key, data, error: null }),
      (e) => live && setState({ key, data: null, error: String(e?.message ?? e) }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, n]);
  return { data: state.key === key ? state.data : null, error: state.key === key ? state.error : null, reload: () => setN((x) => x + 1) };
}

const act = () => getStore().actions;
function Loading({ error, empty }: { error: string | null; empty?: string }) {
  if (error) return <div className="pn-empty bad">{error}</div>;
  if (empty) return <div className="pn-empty">{empty}</div>;
  return (
    <div className="pn-empty">
      <Spinner size={12} label="Loading" />
    </div>
  );
}

function Refresh({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="pn-ref" onClick={onClick} title="Refresh" aria-label="Refresh">
      <svg viewBox="0 0 24 24" {...I} width="12" height="12">
        <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" />
      </svg>
    </button>
  );
}

const home = (p: string) => p.replace(/^\/Users\/[^/]+|^C:\\Users\\[^\\]+/i, "~");
/** "~/Desktop/khope/oh-my-hermes-worktrees/omher-panel" -> "~/…/oh-my-hermes-worktrees/omher-panel" */
const shortPath = (p: string) => {
  const h = home(p);
  const sep = h.includes("\\") && !h.includes("/") ? "\\" : "/";
  const parts = h.split(sep);
  return parts.length <= 4 ? h : [parts[0], "…", ...parts.slice(-2)].join(sep);
};
const CMD_LINES = 4;
const leaf = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() ?? p;

export function TerminalTab({ bot }: { bot: Bot }) {
  const running = useStore().chats[bot.name]?.turn;
  const { data, error, reload } = useLoad(`t:${bot.name}`, () => act().panelTerminal(bot.name));
  // a finished turn may have run commands: re-read when the running turn ends
  useEffect(() => {
    if (!running) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!running]);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <Loading error={error} />;
  const runs: TerminalRun[] = data.runs;
  return (
    <div className="pn-body" data-testid="panel-terminal">
      <div className="pn-sec">
        What {bot.display_name} ran<span>read-only</span>
        <Refresh onClick={reload} />
      </div>
      {runs.length === 0 && <Loading error={null} empty={`${bot.display_name} has not run a command yet.`} />}
      {runs.map((r) => {
        const all = open === r.id;
        const long = r.output.split("\n").length > 6 || r.output.length > 360;
        const shown = all || !long ? r.output : r.output.split("\n").slice(0, 6).join("\n").slice(0, 360);
        const cmdLines = r.command.split("\n");
        const tallCmd = cmdLines.length > CMD_LINES || r.command.length > 180;
        const cmd = all || !tallCmd ? r.command : cmdLines.slice(0, CMD_LINES).join("\n").slice(0, 280) + " …";
        return (
          <div key={r.id} className={`pn-run${r.exit_code ? " bad" : ""}`} data-testid="panel-run">
            <div className="pn-run-h">
              <code className={`pn-cmd${all ? " all" : ""}`} title={tallCmd && !all ? r.command : undefined}>
                {cmd}
              </code>
            </div>
            {r.output && <pre className="pn-out">{shown}</pre>}
            {(long || tallCmd) && (
              <button type="button" className="pn-more" onClick={() => setOpen(all ? null : r.id)}>
                {all ? "Show less" : "Show all"}
              </button>
            )}
            <div className="pn-meta">
              {r.source && r.source !== "tui" && r.source !== "local" && (
                <span className="pn-src" title={`Run from ${sourceName(r.source)}`}>
                  <SourceIcon source={r.source} size={10} />
                  {sourceName(r.source)}
                </span>
              )}
              {r.cwd && (
                <span className="pn-cwd" title={r.cwd}>
                  {shortPath(r.cwd)}
                </span>
              )}
              {r.exit_code !== null && r.exit_code !== 0 && <span className="pn-exit">exit {r.exit_code}</span>}
              <span className="pn-ts">{shortTime(r.ts)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function ScheduleTab({ bot }: { bot: Bot }) {
  const s = useStore();
  const routines: Routine[] | undefined = s.routines[bot.name];
  useEffect(() => {
    void s.loadRoutines(bot.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name]);
  if (!routines) return <Loading error={null} />;
  const sorted = [...routines].sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.name.localeCompare(b.name));
  return (
    <div className="pn-body" data-testid="panel-schedule">
      <div className="pn-sec">
        {bot.display_name}'s routines<span>{routines.length}</span>
      </div>
      {routines.length === 0 && (
        <div className="pn-empty">
          No routines yet.
          <br />
          Ask {bot.display_name} in the chat, e.g. “every morning at 9, check new PRs”.
        </div>
      )}
      {sorted.map((r) => (
        <div key={r.id} className={`pn-row${r.enabled ? "" : " off"}`} data-testid="panel-routine" title={r.schedule}>
          <b>{r.name}</b>
          <span className="pn-r">{nextRun(r)}</span>
          <span className="pn-s">
            {cadence(r.schedule)}
            {r.last_run_at ? ` · last ran ${shortTime(toSec(r.last_run_at))}` : ""}
          </span>
          <span className={`pn-st ${r.last_status && r.last_status !== "ok" ? "bad" : r.last_status ? "ok" : ""}`}>
            {r.enabled ? r.last_status || "not run yet" : "paused"}
          </span>
        </div>
      ))}
    </div>
  );
}

function toSec(v: number | string): number {
  return typeof v === "number" ? (v > 1e12 ? v / 1000 : v) : Date.parse(v) / 1000;
}

export function WorktreesTab({ bot, onOpenDiff }: { bot: Bot; onOpenDiff: (path: string) => void }) {
  const { data, error, reload } = useLoad(`w:${bot.name}`, () => act().panelWorktrees(bot.name));
  if (!data) return <Loading error={error} />;
  const trees: Worktree[] = data.worktrees;
  return (
    <div className="pn-body" data-testid="panel-worktrees">
      <div className="pn-sec">
        Where {bot.display_name} worked<span>{trees.length}</span>
        <Refresh onClick={reload} />
      </div>
      {trees.length === 0 && <div className="pn-empty">No git worktrees in {bot.display_name}'s recent commands.</div>}
      {trees.map((w) => (
        <button key={w.path} type="button" className="pn-row link" onClick={() => onOpenDiff(w.path)} data-testid="panel-tree" title={w.path}>
          <b className="mono">{w.branch || (w.head ? `detached @ ${w.head.slice(0, 7)}` : "detached")}</b>
          <span className="pn-r">{shortTime(w.last)}</span>
          <span className="pn-s">
            {w.repo} · <span className="mono">{leaf(w.path)}</span>
          </span>
          <span className={`pn-st ${w.dirty ? "warn" : w.dirty === 0 ? "ok" : ""}`}>
            {w.dirty === null ? "?" : w.dirty === 0 ? "clean" : `${w.dirty} changed`}
          </span>
        </button>
      ))}
    </div>
  );
}

export function DiffTab({ bot, path, onPick }: { bot: Bot; path: string | null; onPick: (p: string) => void }) {
  const trees = useLoad(`w:${bot.name}`, () => act().panelWorktrees(bot.name));
  const target = path ?? trees.data?.worktrees[0]?.path ?? null;
  const diff = useLoad(`d:${bot.name}:${target ?? ""}`, () =>
    target ? act().panelDiff(bot.name, target) : Promise.resolve(null as WorktreeDiff | null),
  );
  const lines = useMemo(() => (diff.data?.patch ?? "").split("\n"), [diff.data]);
  if (!trees.data) return <Loading error={trees.error} />;
  if (!target) return <div className="pn-empty">No git worktrees in {bot.display_name}'s recent commands.</div>;
  const d = diff.data;
  return (
    <div className="pn-body" data-testid="panel-diff">
      <div className="pn-pick">
        <select value={target} onChange={(e) => onPick(e.target.value)} aria-label="Worktree" data-testid="panel-diff-pick">
          {trees.data.worktrees.map((w) => (
            <option key={w.path} value={w.path}>
              {w.branch || `detached @ ${w.head.slice(0, 7)}`} · {w.repo}
            </option>
          ))}
        </select>
        <Refresh onClick={diff.reload} />
      </div>
      {!d ? (
        <Loading error={diff.error} />
      ) : (
        <>
          <div className="pn-sec">
            {d.scope === "uncommitted" ? "Uncommitted changes" : "Last commit"}
            <span>
              {d.files.length} file{d.files.length === 1 ? "" : "s"} · +{d.files.reduce((a, f) => a + f.add, 0)} −
              {d.files.reduce((a, f) => a + f.del, 0)}
            </span>
          </div>
          {d.files.length === 0 && <div className="pn-empty">Nothing changed.</div>}
          <div className="pn-diff" data-testid="panel-diff-patch">
            {lines.map((l, i) => {
              const file = /^diff --git a\/.+ b\/(.+)$/.exec(l);
              if (file) {
                const f = d.files.find((x) => x.path === file[1]);
                return (
                  <div key={i} className="df-f">
                    {file[1]}
                    {f && (
                      <span>
                        <i className="n-add">+{f.add}</i> <i className="n-del">−{f.del}</i>
                      </span>
                    )}
                  </div>
                );
              }
              if (/^(---|\+\+\+|index |new file|deleted file|similarity|rename )/.test(l)) return null;
              const cls = l.startsWith("@@") ? "h" : l.startsWith("+") ? "a" : l.startsWith("-") ? "d" : "";
              return (
                <div key={i} className={`df-l ${cls}`}>
                  {l || " "}
                </div>
              );
            })}
          </div>
          {d.truncated && <div className="pn-empty">Long diff: the rest is cut. Open the worktree to see all of it.</div>}
          <div className="pn-foot">Read-only. {bot.display_name} makes the changes; you see them here.</div>
        </>
      )}
    </div>
  );
}
