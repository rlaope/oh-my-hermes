// Details panel: who the bot is, where it is right now (this chat + read-only sessions elsewhere),
// and its routines from cron. Nothing here writes to another session.
import { useEffect, useState } from "react";
import type { SlotProps } from "../features";
import type { ReactNode as JSXChild } from "react";
import type { Away, Bot, Routine } from "../lib/protocol";
import { useStore } from "../state/store";
import { openExternal } from "../lib/openExternal";
import { shortTime } from "../app/time";
import { Avatar, CloseIcon, IconButton, SourceIcon } from "../ui";
import logo from "../assets/omher-mark.png";
import { awayTime, cadence, nextRun, sourceList, sourceName } from "./format";
import { DiffTab, ScheduleTab, TAB_ICON, TABS, TerminalTab, WorktreesTab, type PanelTab } from "./PanelTabs";
import { useNow } from "./useNow";
import { RunsTab } from "../runs/RunsTab";
import "./elsewhere.css";
import { t as tr } from "../i18n";

export const slot = "detailsPanel";

const SHOW = 6;

export default function DetailsPanel({ bot, open, onClose }: SlotProps["detailsPanel"]) {
  const s = useStore();
  const tab = s.ui.panelTab;
  const [diffPath, setDiffPath] = useState<string | null>(null);
  useEffect(() => setDiffPath(null), [bot.name]);
  const head = (
    <div className="details-h pn-tabs" role="tablist" aria-label={tr("pn.panel")}>
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={tab === t.id}
          title={t.label}
          className={`pn-tab${tab === t.id ? " on" : ""}`}
          onClick={() => s.setPanelTab(t.id)}
          data-testid={`panel-tab-${t.id}`}
        >
          {TAB_ICON[t.id]}
          {tab === t.id && <span>{t.label}</span>}
        </button>
      ))}
      <IconButton label={tr("pn.close")} onClick={onClose}>
        <CloseIcon />
      </IconButton>
    </div>
  );
  if (tab !== "details") {
    const openDiff = (p: string) => {
      setDiffPath(p);
      s.setPanelTab("diff");
    };
    return (
      <div className="details-in ew-panel pn-wide" data-testid="details-panel" data-tab={tab}>
        {head}
        <div className="pn-scroll">
          {open && tab === "terminal" && <TerminalTab bot={bot} />}
          {open && tab === "schedule" && <ScheduleTab bot={bot} />}
          {open && tab === "worktrees" && <WorktreesTab bot={bot} onOpenDiff={openDiff} />}
          {open && tab === "diff" && <DiffTab bot={bot} path={diffPath} onPick={setDiffPath} />}
          {open && tab === "runs" && <RunsTab bot={bot} />}
        </div>
      </div>
    );
  }
  return <DetailsTab bot={bot} open={open} head={head} />;
}

function DetailsTab({ bot, open, head }: { bot: Bot; open: boolean; head: JSXChild }) {
  const s = useStore();
  const away: Away[] = s.elsewhere[bot.name] ?? [];
  const routines: Routine[] = s.routines[bot.name] ?? [];
  const chat = s.chats[bot.name];
  const now = useNow(open && away.some((a) => a.running));
  const [all, setAll] = useState(false);
  // Running sessions first, then most recent; a short list keeps Routines on screen.
  const sorted = [...away].sort((x, y) => Number(y.running) - Number(x.running) || y.last_active - x.last_active);
  const shown = all ? sorted : sorted.slice(0, SHOW);

  // Fresh lists each time the panel opens. While open, the store itself re-reads the elsewhere list on
  // `elsewhere.update` and the routines on `routine.ran`, and this panel re-renders from that state.
  useEffect(() => {
    if (!open) return;
    void s.loadElsewhere(bot.name);
    void s.loadRoutines(bot.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bot.name]);

  const model = chat?.model || bot.model;
  const last = chat?.messages[chat.messages.length - 1];
  const hereTime = chat?.turn ? "working" : last ? shortTime(last.ts, now) : "now";
  const sources = sourceList(away.map((a) => a.source));

  return (
    <div className="details-in ew-panel" data-testid="details-panel" data-tab="details">
      {head}
      <div className="details-id">
        <Avatar bot={bot.name} size={40} />
        <div>
          <b>{bot.display_name}</b>
          <span className="details-sub">{tr("pn.profile", { name: bot.name })}</span>
          <span className="details-sub mono" title={model}>
            {model}
          </span>
        </div>
        <button
          type="button"
          className="details-edit"
          onClick={() => s.openSettings(`bot:${bot.name}`)}
          title={tr("pn.editTip")}
          data-testid="details-edit"
        >
          {tr("pn.edit")}
        </button>
      </div>
      <div className="ew-scroll">
        <div className="ew-sec" data-testid="where-sec">
          {tr("pn.where", { bot: bot.display_name })}
          <span>{away.length + 1}</span>
        </div>
        <ul className="ew-sess" data-testid="where-list">
          <li className="ew-ss here" data-testid="where-row" data-session="main">
            <span className="t1">{tr("pn.thisChat")}</span>
            <span className="st">{hereTime}</span>
            <span className="t2">
              <span className="ew-src">
                <img className="ew-logo" src={logo} alt="" />
                omher
              </span>
            </span>
          </li>
          {shown.map((a) => {
            const src = sourceName(a.source);
            const row = (
              <>
                <span className="t1" title={a.label}>
                  {a.label}
                </span>
                <span className={`st${a.running ? " run" : ""}`}>
                  {a.running && <i className="ew-live" aria-hidden />}
                  {awayTime(a, now)}
                </span>
                <span className="t2">
                  <span className="ew-src">
                    <SourceIcon source={a.source} size={12} />
                    {a.place ? `${src} ${a.place}` : src}
                  </span>
                  {a.url && <span className="ew-go">↗</span>}
                </span>
              </>
            );
            return (
              <li key={a.id} data-testid="where-row" data-session={a.id}>
                {a.url ? (
                  <a
                    className="ew-ss link"
                    href={a.url}
                    title={tr("pn.openIn", { app: src })}
                    onClick={(e) => {
                      e.preventDefault();
                      void openExternal(a.url!);
                    }}
                  >
                    {row}
                  </a>
                ) : (
                  <div className="ew-ss" title={tr("pn.readOnly", { app: src })}>
                    {row}
                  </div>
                )}
              </li>
            );
          })}
          {sorted.length > SHOW && (
            <li>
              <button type="button" className="ew-more" data-testid="where-more" onClick={() => setAll((v) => !v)}>
                {all ? tr("pn.fewer") : tr("pn.all", { n: sorted.length })}
              </button>
            </li>
          )}
        </ul>
        <div className="ew-note" data-testid="where-note">
          {tr("pn.note", { bot: bot.display_name, places: sources || tr("pn.slackDiscord") })}
        </div>
        <div className="ew-sec" data-testid="routines-sec">
          {tr("pn.routines")}
          <span>{routines.length}</span>
        </div>
        {routines.length === 0 ? (
          <div className="ew-empty">{tr("pn.noRoutines")}</div>
        ) : (
          <ul className="ew-sess" data-testid="routine-list">
            {routines.map((r) => (
              <li key={r.id} className={`ew-ss${r.enabled ? "" : " off"}`} data-testid="routine-row" title={r.schedule}>
                <span className="t1">{r.name}</span>
                <span className="st">{nextRun(r, now)}</span>
                <span className="t2">
                  <span className="ew-src">{cadence(r.schedule)}</span>
                  {r.last_status && r.last_status !== "ok" && <span className="st bad">{tr("pn.lastRun", { status: r.last_status })}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
