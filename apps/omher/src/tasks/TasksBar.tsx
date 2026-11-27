// The sidebar's Tasks row (after Orca's SidebarTaskNavButton: stablyai/orca, MIT License, Copyright (c) 2026 Lovecast
// Inc.; ported, not copied): a list mark and "Tasks", and on its right the GitHub, GitLab and Linear marks, each
// opening the Tasks page on that source. Right-click: "Hide from sidebar" (Settings › General shows it again). With
// GitHub accounts chosen, a badge counts the reviews asked of me (summed over the accounts the "나" chip shows); the
// row keeps their lists read while omher runs (me.ts startMePolling). With a github.com account chosen, a GitHub row
// under it opens the Tasks page on the GitHub dashboard (DashView.tsx) in one click.
import { useEffect, useRef, useState } from "react";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { setBar, setScope, setSource, useTasks } from "./state";
import { reviewBadge, shownAccounts, startMePolling, useMeData } from "./me";
import { ListIcon, SourceMark } from "./marks";
import { SOURCES, type TaskSource } from "./types";
import "./tasks.css";

const NAME: Record<TaskSource, string> = { github: "GitHub", gitlab: "GitLab", linear: "Linear" };

export function TasksBar() {
  const s = useStore();
  const tk = useTasks();
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const me = useMeData();
  useEffect(() => startMePolling(), []);
  useEffect(() => {
    if (!menu) return;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener("mousedown", down);
    return () => document.removeEventListener("mousedown", down);
  }, [menu]);
  if (!tk.bar) return null;
  const on = s.ui.view === "tasks" && tk.scope !== "gh";
  const reviews = tk.accounts.length ? reviewBadge(me.lists, shownAccounts(tk.accounts, tk.meAccount)) : 0;
  const open = (src?: TaskSource) => {
    if (src) {
      setSource(src);
      setScope("repo");
    }
    s.openTasks();
  };
  return (
    <div
      className={`tk-bar${on ? " on" : ""}`}
      data-testid="tasks-bar"
      onContextMenu={(e) => {
        e.preventDefault();
        setMenu({ x: e.clientX, y: e.clientY });
      }}
    >
      <button type="button" className="tk-bar-main" aria-current={on ? "page" : undefined} onClick={() => open()} data-testid="tasks-open">
        <ListIcon />
        <span>{t("tasks.title")}</span>
      </button>
      {reviews > 0 && (
        <button
          type="button"
          className="tk-badge"
          aria-label={t("tasks.me.badge", { n: reviews })}
          title={t("tasks.me.badge", { n: reviews })}
          onClick={() => {
            setScope("me");
            s.openTasks();
          }}
          data-testid="tasks-badge"
        >
          {reviews}
        </button>
      )}
      <span className="tk-bar-src">
        {SOURCES.map((src) => (
          <button key={src} type="button" className="tk-bar-ic" aria-label={t("tasks.openSource", { source: NAME[src] })} title={t("tasks.openSource", { source: NAME[src] })} onClick={() => open(src)} data-testid={`tasks-bar-${src}`}>
            <SourceMark source={src} />
          </button>
        ))}
      </span>
      {menu && (
        <div
          ref={ref}
          className="row-menu"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          data-testid="tasks-bar-menu"
          onKeyDown={(e) => e.key === "Escape" && setMenu(null)}
        >
          <button
            type="button"
            role="menuitem"
            className="row-mi"
            onClick={() => {
              setMenu(null);
              setBar(false);
            }}
            data-testid="tasks-bar-hide"
          >
            {t("tasks.hide")}
          </button>
        </div>
      )}
    </div>
  );
}

/** The sidebar's GitHub row: shown once a github.com account is chosen (Settings › Accounts › GitHub); it opens the
 *  Tasks page on the GitHub dashboard. */
export function GhDashBar() {
  const s = useStore();
  const tk = useTasks();
  if (!tk.accounts.some((a) => a.host === "github.com")) return null;
  const on = s.ui.view === "tasks" && tk.scope === "gh";
  return (
    <div className={`tk-bar tk-bar-gh${on ? " on" : ""}`} data-testid="ghdash-bar">
      <button
        type="button"
        className="tk-bar-main"
        aria-current={on ? "page" : undefined}
        onClick={() => {
          setScope("gh");
          s.openTasks();
        }}
        data-testid="ghdash-open"
      >
        <SourceMark source="github" size={14} />
        <span>{t("tasks.gh.bar")}</span>
      </button>
    </div>
  );
}

export { NAME as SOURCE_NAME };
