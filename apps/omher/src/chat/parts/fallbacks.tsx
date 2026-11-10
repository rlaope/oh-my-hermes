// One-line plain fallbacks used until a feature node registers its slot.
import { useEffect, useState } from "react";
import type { ActivitySlotProps, CardsSlotProps, ElsewhereLineSlotProps, RoutineLineSlotProps } from "../../features";
import { SourceIcon, Spinner } from "../../ui";
import { elapsed, hhmm } from "../../app/time";

export function ActivityFallback({ item, live }: ActivitySlotProps) {
  const t = item.turn;
  const [, tick] = useState(0);
  useEffect(() => {
    if (!live) return;
    const h = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(h);
  }, [live]);
  const ms = (t.endedAt ?? Date.now()) - t.startedAt;
  let text: string;
  if (live) text = t.status || "Working…";
  else if (t.outcome === "interrupted") text = `Stopped after ${elapsed(ms)}`;
  else if (t.outcome === "ended") text = `Ended after ${elapsed(ms)}`;
  else if (t.outcome === "error") text = `Failed${t.error ? ` · ${t.error}` : ""}`;
  else text = `Worked for ${elapsed(ms)} · ${t.steps.length} step${t.steps.length === 1 ? "" : "s"}`;
  return (
    <div className="line" data-testid="activity-fallback">
      {live ? <Spinner /> : <span className="line-ic">✓</span>}
      <span className="line-t">{text}</span>
      {live && <span className="line-tm">{elapsed(ms)}</span>}
    </div>
  );
}

export function CardFallback({ item }: CardsSlotProps) {
  const text =
    item.kind === "approval"
      ? item.resolved
        ? `${item.title} · ${item.resolved === "deny" ? "Denied" : "Allowed"}`
        : `Waiting for approval · ${item.title}`
      : item.answer
        ? `Answered: ${item.answer}`
        : `Question · ${item.question}`;
  return (
    <div className="line" data-testid="card-fallback">
      <span className="line-ic">?</span>
      <span className="line-t">{text}</span>
    </div>
  );
}

const SOURCE: Record<string, string> = { slack: "Slack", discord: "Discord", telegram: "Telegram", cron: "Cron" };
export const sourceName = (s: string) => SOURCE[s] ?? (s ? s[0].toUpperCase() + s.slice(1) : "Elsewhere");

export function ElsewhereFallback({ item }: ElsewhereLineSlotProps) {
  const a = item.away;
  return (
    <div className="line" data-testid="away-fallback">
      <SourceIcon source={a.source} size={12} />
      <span className="line-src">{sourceName(a.source)}</span>
      <span className="line-t strong">{a.label}</span>
      <span className="line-tm">{a.running ? "working" : hhmm(new Date(a.last_active * 1000))}</span>
    </div>
  );
}

export function RoutineFallback({ item }: RoutineLineSlotProps) {
  return (
    <div className="line" data-testid="routine-fallback">
      <span className="line-ic">⏱</span>
      <span className="line-t">
        Routine · {item.name} · {item.status}
      </span>
      <span className="line-tm">{hhmm(new Date(item.ts * 1000))}</span>
    </div>
  );
}
