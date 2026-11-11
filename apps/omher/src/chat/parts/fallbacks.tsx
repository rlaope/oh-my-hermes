// One-line plain fallbacks used until a feature node registers its slot.
import { useEffect, useState } from "react";
import type { ActivitySlotProps, CardsSlotProps, ElsewhereLineSlotProps, RoutineLineSlotProps } from "../../features";
import { SourceIcon, Spinner } from "../../ui";
import { elapsed, hhmm } from "../../app/time";
import { t as tr } from "../../i18n";
import { WORKING } from "../../state/store";

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
  if (live) text = !t.status || t.status === WORKING ? tr("act.working") : t.status;
  else if (t.outcome === "interrupted") text = tr("act.stopped", { t: elapsed(ms) });
  else if (t.outcome === "ended") text = tr("act.ended", { t: elapsed(ms) });
  else if (t.outcome === "error") text = `${tr("act.failed")}${t.error ? ` · ${t.error}` : ""}`;
  else text = t.steps.length === 1 ? tr("act.worked1", { t: elapsed(ms) }) : tr("act.worked", { t: elapsed(ms), n: t.steps.length });
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
        ? `${item.title} · ${item.resolved === "deny" ? tr("fb.denied") : tr("fb.allowed")}`
        : tr("fb.waiting", { title: item.title })
      : item.answer
        ? tr("fb.answered", { answer: item.answer })
        : tr("fb.question", { q: item.question });
  return (
    <div className="line" data-testid="card-fallback">
      <span className="line-ic">?</span>
      <span className="line-t">{text}</span>
    </div>
  );
}

const SOURCE: Record<string, string> = { slack: "Slack", discord: "Discord", telegram: "Telegram", cron: "Cron" };
export const sourceName = (s: string) => SOURCE[s] ?? (s ? s[0].toUpperCase() + s.slice(1) : tr("fb.elsewhere"));

export function ElsewhereFallback({ item }: ElsewhereLineSlotProps) {
  const a = item.away;
  return (
    <div className="line" data-testid="away-fallback">
      <SourceIcon source={a.source} size={12} />
      <span className="line-src">{sourceName(a.source)}</span>
      <span className="line-t strong">{a.label}</span>
      <span className="line-tm">{a.running ? tr("act.dag.working") : hhmm(new Date(a.last_active * 1000))}</span>
    </div>
  );
}

export function RoutineFallback({ item }: RoutineLineSlotProps) {
  return (
    <div className="line" data-testid="routine-fallback">
      <span className="line-ic">⏱</span>
      <span className="line-t">
        {tr("fb.routine", { name: item.name, status: item.status })}
      </span>
      <span className="line-tm">{hhmm(new Date(item.ts * 1000))}</span>
    </div>
  );
}
