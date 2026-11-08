// Details panel: who the bot is, where it is right now (this chat + read-only sessions elsewhere),
// and its routines from cron. Nothing here writes to another session.
import { useEffect } from "react";
import type { SlotProps } from "../features";
import type { Away, Routine } from "../lib/protocol";
import { useStore } from "../state/store";
import { shortTime } from "../app/time";
import { Avatar, CloseIcon, IconButton } from "../ui";
import logo from "../assets/omh-logo.png";
import { awayTime, cadence, nextRun, sourceList, sourceName } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "detailsPanel";

export default function DetailsPanel({ bot, open, onClose }: SlotProps["detailsPanel"]) {
  const s = useStore();
  const away: Away[] = s.elsewhere[bot.name] ?? [];
  const routines: Routine[] = s.routines[bot.name] ?? [];
  const chat = s.chats[bot.name];
  const now = useNow(open && away.some((a) => a.running));

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
    <div className="details-in ew-panel" data-testid="details-panel">
      <div className="details-h">
        Details
        <IconButton label="Close details" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="details-id">
        <Avatar bot={bot.name} size={40} />
        <div>
          <b>{bot.display_name}</b>
          <span>
            Hermes profile · {bot.name} · {model}
          </span>
        </div>
      </div>
      <div className="ew-scroll">
        <div className="ew-sec" data-testid="where-sec">
          Where {bot.display_name} is<span>{away.length + 1}</span>
        </div>
        <ul className="ew-sess" data-testid="where-list">
          <li className="ew-ss here" data-testid="where-row" data-session="main">
            <span className="t1">This chat</span>
            <span className="st">{hereTime}</span>
            <span className="t2">
              <span className="ew-src">
                <img className="ew-logo" src={logo} alt="" />
                omher
              </span>
            </span>
          </li>
          {away.map((a) => (
            <li
              key={a.id}
              className="ew-ss"
              data-testid="where-row"
              data-session={a.id}
              title={`Read-only here · reply in ${sourceName(a.source)}`}
            >
              <span className="t1">{a.label}</span>
              <span className={`st${a.running ? " run" : ""}`}>{awayTime(a, now)}</span>
              <span className="t2">
                <span className="ew-src">
                  <i className={`src-sq src-${a.source}`} />
                  {sourceName(a.source)}
                </span>
              </span>
            </li>
          ))}
        </ul>
        <div className="ew-note" data-testid="where-note">
          Talk to {bot.display_name} here — it knows what it did in {sources || "Slack and Discord"}. Those threads are{" "}
          <span className="ew-nw">read-only</span> here; reply in their apps.
        </div>
        <div className="ew-sec" data-testid="routines-sec">
          Routines<span>{routines.length}</span>
        </div>
        {routines.length === 0 ? (
          <div className="ew-empty">No routines yet.</div>
        ) : (
          <ul className="ew-sess" data-testid="routine-list">
            {routines.map((r) => (
              <li key={r.id} className={`ew-ss${r.enabled ? "" : " off"}`} data-testid="routine-row" title={r.schedule}>
                <span className="t1">{r.name}</span>
                <span className="st">{nextRun(r, now)}</span>
                <span className="t2">
                  <span className="ew-src">{cadence(r.schedule)}</span>
                  {r.last_status && r.last_status !== "ok" && <span className="st bad">last run {r.last_status}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
