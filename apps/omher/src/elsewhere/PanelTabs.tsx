// Right panel tabs next to Details: Terminal, Schedule, Worktrees, Diff. Everything here is read-only:
// the bot runs things, omher shows what it ran and what it changed.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactElement } from "react";
import type { Bot, Routine, TerminalRun, Worktree, WorktreeDiff } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { shortTime } from "../app/time";
import { t, tx, type Key } from "../i18n";
import { SourceIcon, Spinner } from "../ui";
import { cadence, isFailure, nextRun, sourceName, statusText } from "./format";
import "./panel.css";

export type PanelTab = "details" | "terminal" | "schedule" | "worktrees" | "diff" | "runs";

const TAB_KEY: Record<PanelTab, Key> = {
  details: "pn.details",
  terminal: "pn.terminal",
  schedule: "pn.schedule",
  worktrees: "pn.worktrees",
  diff: "pn.diff",
  runs: "plans.tab",
};
/** The tabs in order; each label is read in the current language. */
export const TABS: { id: PanelTab; readonly label: string }[] = (Object.keys(TAB_KEY) as PanelTab[]).map((id) => ({
  id,
  get label() {
    return t(TAB_KEY[id]);
  },
}));

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

/** The tab row's maximise / restore control: the panel grows in place to every pixel right of the sidebar and
 *  comes back to the width it had. A double click on the row's free space does the same (`onPanelRowDoubleClick`). */
export function PanelMaxButton() {
  const s = useStore();
  const max = s.ui.panelMax;
  const label = max ? t("panel.restore") : t("panel.max");
  return (
    <button
      type="button"
      className="ui-ib pn-max"
      aria-label={label}
      title={label}
      aria-pressed={max}
      onClick={() => s.setPanelMax(!max)}
      data-testid="panel-max"
    >
      {max ? (
        <svg viewBox="0 0 24 24" {...I} width="14" height="14" aria-hidden="true">
          <path d="M4 14h6v6M20 10h-6V4M14 10l6.5-6.5M10 14l-6.5 6.5" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" {...I} width="14" height="14" aria-hidden="true">
          <path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5" />
        </svg>
      )}
    </button>
  );
}

/** Free space of the tab row: the row itself or anything in it that is not a tab or a button. */
const onFreeRow = (e: { target: EventTarget | null; currentTarget: EventTarget }) => {
  const hit = e.target as HTMLElement | null;
  return hit === e.currentTarget || !hit?.closest("button, a, input, select");
};
const togglePanelMax = () => {
  const st = getStore();
  st.actions.setPanelMax(!st.getState().ui.panelMax);
};

// A double click on the tab row is read from its two presses, not from the browser's dblclick: maximise / restore
// slides the row (app.css .panel-maxing), so a person's second press can land on whatever slid in under the pointer,
// and the native dblclick never reaches the row. The first press on free row space arms; a second press within
// PAIR_MS and PAIR_PX (screen pixels) toggles, wherever its target now is.
const PAIR_MS = 500;
const PAIR_PX = 6;
let armed: { by: Event; t: number; x: number; y: number; timer: ReturnType<typeof setTimeout> } | null = null;
/** The press that ended the last pair (the row must not arm on it again) and whether this gesture already toggled. */
let paired: Event | null = null;
let toggled = false;

function disarm() {
  if (!armed) return;
  clearTimeout(armed.timer);
  armed = null;
  window.removeEventListener("pointerdown", onSecondPress, true);
}
function onSecondPress(e: PointerEvent) {
  const a = armed;
  disarm();
  if (!a || e.button !== 0) return;
  if (e.timeStamp - a.t > PAIR_MS || Math.abs(e.screenX - a.x) > PAIR_PX || Math.abs(e.screenY - a.y) > PAIR_PX) return;
  // a control outside the row that slid under the pointer and was actually hit (the model pill) is the person's: it
  // takes the press, and the pair does not toggle
  if (onControl(e.target)) return;
  paired = e;
  toggled = true;
  // the second press belongs to the row's double click: a tab or button that slid under it is not also clicked
  const swallow = (c: MouseEvent) => {
    c.stopPropagation();
    c.preventDefault();
  };
  window.addEventListener("click", swallow, { capture: true, once: true });
  setTimeout(() => window.removeEventListener("click", swallow, true), PAIR_MS);
  togglePanelMax();
}

function arm(n: PointerEvent) {
  disarm();
  toggled = false;
  armed = { by: n, t: n.timeStamp, x: n.screenX, y: n.screenY, timer: setTimeout(disarm, PAIR_MS) };
  window.addEventListener("pointerdown", onSecondPress, true);
}

/** First press of a double click on the tab row's free space (the second is caught on the window, above). */
export function onPanelRowPointerDown(e: { target: EventTarget | null; currentTarget: EventTarget; button: number; nativeEvent: PointerEvent }) {
  // this press already ended a pair, or already armed as a press aimed at the swept row (below)
  if (e.nativeEvent === paired || e.nativeEvent === armed?.by) return;
  disarm();
  if (e.button !== 0 || !onFreeRow(e)) return;
  arm(e.nativeEvent);
}

// While the panel slides (maximise / restore) the row can move out from under a pointer aimed at its free space
// before the first press even lands. Each frame of the slide records the free space the row shows; a press on a spot
// the free space covered in the last AIM_MS belongs to the row, whatever slid in under it: the chat header's bare
// background (never a control in it, which the person hit and which always wins), or a tab
// while the slide is still moving it (a tab pressed once it has stopped moving is the tab's). Such a press arms, and its
// click goes nowhere else.
const INTERACTIVE =
  'button, a[href], input, textarea, select, [role="button"], [role="menuitem"], [role="tab"], [role="combobox"], [role="link"], [contenteditable]:not([contenteditable="false"]), [tabindex]:not([tabindex="-1"])';
/** A press on an interactive element outside the tab row: always that element's, never claimed by the row. */
const onControl = (t: EventTarget | null) => {
  const hit = t instanceof Element ? t : null;
  return !!hit && !hit.closest('[data-testid="panel-tabs"]') && !!hit.closest(INTERACTIVE);
};
const SWEEP_MS = 320;
const AIM_MS = 200;
type Box = { at: number; x0: number; x1: number; y0: number; y1: number };
let swept: Box[] = [];
let sweepEnd = 0;

function freeBox(row: HTMLElement): Box | null {
  const b = row.getBoundingClientRect();
  const tabs = [...row.querySelectorAll(".pn-tab")].map((t) => t.getBoundingClientRect().right);
  const rest = [...row.querySelectorAll("button:not(.pn-tab)")].map((t) => t.getBoundingClientRect().left);
  const x0 = tabs.length ? Math.max(...tabs) : b.left;
  // the row's own buttons sit past the window's edge while the panel grows: only what the window shows counts
  const x1 = Math.min(rest.length ? Math.min(...rest) : b.right, window.innerWidth);
  return x1 > x0 ? { at: performance.now(), x0, x1, y0: b.top, y1: b.bottom } : null;
}
/** The row moved more than a pixel in the last MOVE_MS, or the slide itself still runs (the window's grid, or the
 *  overlay panel): what is under the pointer is not what the person aimed at. A busy main thread draws the slide's
 *  frames further apart than MOVE_MS, so two samples alone can miss a row that is still moving. */
const MOVE_MS = 60;
const sliding = () =>
  [document.querySelector(".window"), document.querySelector(".details")].some((el) => el?.getAnimations().some((a) => a instanceof CSSTransition));
const moving = (now: number) => {
  if (sliding()) return true;
  const last = swept.filter((b) => now - b.at <= MOVE_MS).map((b) => b.x0);
  return last.length > 1 && Math.max(...last) - Math.min(...last) > 1;
};

function onSweptPress(e: PointerEvent) {
  // the press's own time, not when this handler runs: a busy main thread hands it over late, and the person aimed at
  // the frame they saw when they pressed
  const now = e.timeStamp;
  if (armed || e === paired || e.button !== 0 || now > sweepEnd + AIM_MS) return;
  const hit = e.target as Element | null;
  const row = hit?.closest('[data-testid="panel-tabs"]');
  // on the row's free space now: the row's own handler arms; on the row's maximise / close buttons: theirs
  if (row && !hit?.closest(".pn-tab")) return;
  // a control the person actually hit outside the row (the model pill, the places chip) always wins: only the
  // header's bare background (and tabs still moving) can be claimed
  if (onControl(hit)) return;
  if (row && !moving(now)) return;
  const aimed = (b: Box) => now - b.at <= AIM_MS && e.clientX >= b.x0 && e.clientX <= b.x1 && e.clientY >= b.y0 && e.clientY <= b.y1;
  if (!swept.some(aimed)) return;
  const swallow = (c: MouseEvent) => {
    c.stopPropagation();
    c.preventDefault();
  };
  window.addEventListener("click", swallow, { capture: true, once: true });
  setTimeout(() => window.removeEventListener("click", swallow, true), PAIR_MS);
  arm(e);
}

/** Records the tab row's free space every frame while maximise / restore slides it (`max` flips), see above. */
export function usePanelRowSweep(row: () => HTMLElement | null, max: boolean) {
  const first = useRef(true);
  useLayoutEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    let frame = 0;
    const start = performance.now();
    swept = [];
    sweepEnd = start + SWEEP_MS;
    const sample = () => {
      const r = row();
      const b = r && freeBox(r);
      if (b) swept.push(b);
      if (performance.now() - start < SWEEP_MS) frame = requestAnimationFrame(sample);
    };
    sample();
    window.addEventListener("pointerdown", onSweptPress, true);
    const off = setTimeout(() => window.removeEventListener("pointerdown", onSweptPress, true), SWEEP_MS + AIM_MS);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(off);
      window.removeEventListener("pointerdown", onSweptPress, true);
    };
  }, [max]);
}

/** The browser's double click on the tab row (not on a tab or a button) toggles too, unless the presses already did:
 *  one double click never toggles twice. */
export function onPanelRowDoubleClick(e: { target: EventTarget | null; currentTarget: EventTarget }) {
  if (toggled || !onFreeRow(e)) return;
  togglePanelMax();
}

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

/** One worktree list per bot, shared by the Worktrees and Diff tabs; Refresh (or 10 s) reads it again. */
const TREES_TTL = 10_000;
const trees = new Map<string, { at: number; p: Promise<{ worktrees: Worktree[] }> }>();
function loadTrees(bot: string, fresh = false): Promise<{ worktrees: Worktree[] }> {
  const hit = trees.get(bot);
  if (hit && !fresh && Date.now() - hit.at < TREES_TTL) return hit.p;
  const p = act().panelWorktrees(bot);
  trees.set(bot, { at: Date.now(), p });
  p.catch(() => trees.get(bot)?.p === p && trees.delete(bot));
  return p;
}
function Loading({ error, empty }: { error: string | null; empty?: string }) {
  if (error) return <div className="pn-empty bad">{error}</div>;
  if (empty) return <div className="pn-empty">{empty}</div>;
  return (
    <div className="pn-empty">
      <Spinner size={12} label={t("pn.loading")} />
    </div>
  );
}

function Refresh({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="pn-ref" onClick={onClick} title={t("pn.refresh")} aria-label={t("pn.refresh")}>
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
  const running = !!useStore().chats[bot.name]?.turn;
  const { data, error, reload } = useLoad(`t:${bot.name}`, () => act().panelTerminal(bot.name));
  // a finished turn may have run commands: re-read when the running turn ends (not on first mount,
  // where useLoad already reads)
  const was = useRef(running);
  useEffect(() => {
    if (was.current && !running) reload();
    was.current = running;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <Loading error={error} />;
  const runs: TerminalRun[] = data.runs;
  return (
    <div className="pn-body" data-testid="panel-terminal">
      <div className="pn-sec">
        {t("pn.ran", { bot: bot.display_name })}
        <span>{t("pn.ro")}</span>
        <Refresh onClick={reload} />
      </div>
      {runs.length === 0 && <Loading error={null} empty={t("pn.noRuns", { bot: bot.display_name })} />}
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
                {all ? t("pn.less") : t("pn.showAll")}
              </button>
            )}
            <div className="pn-meta">
              {r.source && r.source !== "tui" && r.source !== "local" && (
                <span className="pn-src" title={t("pn.runFrom", { app: sourceName(r.source) })}>
                  <SourceIcon source={r.source} size={10} />
                  {sourceName(r.source)}
                </span>
              )}
              {r.cwd && (
                <span className="pn-cwd" title={r.cwd}>
                  {shortPath(r.cwd)}
                </span>
              )}
              {r.exit_code !== null && r.exit_code !== 0 && <span className="pn-exit">{t("pn.exit", { code: r.exit_code })}</span>}
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
        {t("pn.botRoutines", { bot: bot.display_name })}
        <span>{routines.length}</span>
      </div>
      {routines.length === 0 && (
        <div className="pn-empty">
          {t("pn.noRoutines")}
          <br />
          {t("pn.askRoutine", { bot: bot.display_name })}
        </div>
      )}
      {sorted.map((r) => (
        <div key={r.id} className={`pn-row${r.enabled ? "" : " off"}`} data-testid="panel-routine" title={r.schedule}>
          <b>{r.name}</b>
          <span className="pn-r">{nextRun(r)}</span>
          <span className="pn-s">
            {cadence(r.schedule)}
            {r.last_run_at ? t("pn.lastRan", { when: shortTime(toSec(r.last_run_at)) }) : ""}
          </span>
          <span className={`pn-st ${r.last_status && isFailure(r.last_status) ? "bad" : r.last_status ? "ok" : ""}`}>
            {r.enabled ? (r.last_status ? statusText(r.last_status) : t("pn.notRun")) : t("pn.paused")}
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
  const fresh = useRef(false); // Refresh reads again; opening the tab reuses the shared list
  const { data, error, reload } = useLoad(`w:${bot.name}`, () => {
    const f = fresh.current;
    fresh.current = false;
    return loadTrees(bot.name, f);
  });
  if (!data) return <Loading error={error} />;
  const list: Worktree[] = data.worktrees;
  return (
    <div className="pn-body" data-testid="panel-worktrees">
      <div className="pn-sec">
        {t("pn.worked", { bot: bot.display_name })}
        <span>{list.length}</span>
        <Refresh
          onClick={() => {
            fresh.current = true;
            reload();
          }}
        />
      </div>
      {list.length === 0 && <div className="pn-empty">{t("pn.noTrees", { bot: bot.display_name })}</div>}
      {list.map((w) => (
        <button key={w.path} type="button" className="pn-row link" onClick={() => onOpenDiff(w.path)} data-testid="panel-tree" title={w.path}>
          <b className="mono">{w.branch || (w.head ? t("pn.detachedAt", { sha: w.head.slice(0, 7) }) : t("pn.detached"))}</b>
          <span className="pn-r">{shortTime(w.last)}</span>
          <span className="pn-s">
            {w.repo} · <span className="mono">{leaf(w.path)}</span>
          </span>
          <span className={`pn-st ${w.dirty ? "warn" : w.dirty === 0 ? "ok" : ""}`}>
            {w.dirty === null ? "?" : w.dirty === 0 ? t("pn.clean") : t("pn.changed", { n: w.dirty })}
          </span>
        </button>
      ))}
    </div>
  );
}

export function DiffTab({ bot, path, onPick }: { bot: Bot; path: string | null; onPick: (p: string) => void }) {
  const trees = useLoad(`w:${bot.name}`, () => loadTrees(bot.name));
  const target = path ?? trees.data?.worktrees[0]?.path ?? null;
  const diff = useLoad(`d:${bot.name}:${target ?? ""}`, () =>
    target ? act().panelDiff(bot.name, target) : Promise.resolve(null as WorktreeDiff | null),
  );
  const lines = useMemo(() => (diff.data?.patch ?? "").split("\n"), [diff.data]);
  const fresh = useMemo(() => (diff.data?.files ?? []).filter((f) => f.untracked), [diff.data]);
  if (!trees.data) return <Loading error={trees.error} />;
  if (!target) return <div className="pn-empty">{t("pn.noTrees", { bot: bot.display_name })}</div>;
  const d = diff.data;
  return (
    <div className="pn-body" data-testid="panel-diff">
      <div className="pn-pick">
        <select value={target} onChange={(e) => onPick(e.target.value)} aria-label={t("pn.worktree")} data-testid="panel-diff-pick">
          {trees.data.worktrees.map((w) => (
            <option key={w.path} value={w.path}>
              {w.branch || t("pn.detachedAt", { sha: w.head.slice(0, 7) })} · {w.repo}
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
            {d.scope === "uncommitted" ? t("pn.uncommitted") : t("pn.lastCommit")}
            <span>
              {d.files.length === 1 ? t("pn.file1") : t("pn.files", { n: d.files.length })} · +{d.files.reduce((a, f) => a + f.add, 0)} −
              {d.files.reduce((a, f) => a + f.del, 0)}
            </span>
          </div>
          {d.files.length === 0 && <div className="pn-empty">{t("pn.nothing")}</div>}
          {fresh.length > 0 && (
            <div className="pn-new" data-testid="panel-diff-untracked">
              <div className="df-f">
                {t("pn.untracked")}
                <span>{fresh.length}</span>
              </div>
              {fresh.map((f) => (
                <div key={f.path} className="df-l a mono" title={f.path}>
                  {f.path}
                </div>
              ))}
            </div>
          )}
          <div className="pn-diff" data-testid="panel-diff-patch">
            {lines.map((l, i) => {
              const file = /^diff --git (?:"a\/.*"|a\/.+?) (?:"b\/(.*)"|b\/(.+))$/.exec(l);
              if (file) {
                const name = file[1] ?? file[2];
                const f = d.files.find((x) => x.path === name);
                return (
                  <div key={i} className="df-f">
                    {name}
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
          {d.truncated && <div className="pn-empty">{t("pn.truncated")}</div>}
          <div className="pn-foot">{t("pn.foot", { bot: bot.display_name })}</div>
        </>
      )}
    </div>
  );
}
