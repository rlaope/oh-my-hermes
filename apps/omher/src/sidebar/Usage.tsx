// Subscription usage at the bottom of the sidebar: one agent mark per CLI the person uses, with a ring that
// fills to the larger of its windows (only when the CLI's own files give a %). Hover or click opens a card
// with each window. Read-only: the numbers come from `usage.read`, refreshed every minute.
import { useCallback, useEffect, useRef, useState } from "react";
import type { UsageProvider } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { AgentIcon } from "../ui";
import { PROVIDER_NAME, meterLabel, planText, ringLevel, stateText, topPercent, windowRow } from "./usageFormat";

const REFRESH_MS = 60_000;
const R = 11.5;
const C = 2 * Math.PI * R;

/** The usage ring (also used per account in Settings › Accounts). */
export function Ring({ p }: { p: UsageProvider }) {
  const pct = topPercent(p);
  const fill = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <svg className="usage-ring" width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <circle cx="13" cy="13" r={R} className="usage-track" />
      {pct !== null && fill > 0 && (
        <circle cx="13" cy="13" r={R} className={`usage-fill lv-${ringLevel(pct)}`} strokeDasharray={`${(fill / 100) * C} ${C}`}
          transform="rotate(-90 13 13)" data-testid="usage-fill" />
      )}
    </svg>
  );
}

function Card({ p, now }: { p: UsageProvider; now: number }) {
  const plan = planText(p.plan);
  return (
    <div className="usage-card ui-pop ui-pop-top ui-pop-left" role="dialog" aria-label={`${PROVIDER_NAME[p.id] ?? p.id} usage`}
      data-testid="usage-card">
      <div className="uc-head">
        <AgentIcon id={p.id} size={14} />
        <b>{PROVIDER_NAME[p.id] ?? p.id}</b>
        {plan && <span className="uc-plan">{plan}</span>}
      </div>
      {p.windows.length === 0 ? (
        <div className="uc-row uc-note">{stateText(p)}</div>
      ) : (
        p.windows.map((w, i) => {
          const [label, pct, note] = windowRow(p, w, now);
          return (
            <div className={`uc-row${pct ? "" : " no-pct"}`} key={i} data-testid="usage-window">
              <span className="uc-label">{label}</span>
              {pct && <span className="uc-pct">{pct}</span>}
              <span className={`uc-note${note === "stale" ? " stale" : ""}`}>{note}</span>
            </div>
          );
        })
      )}
    </div>
  );
}

export function Usage() {
  const conn = useStore().conn;
  const [providers, setProviders] = useState<UsageProvider[]>([]);
  const [open, setOpen] = useState<{ id: string; pinned: boolean } | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    getStore()
      .actions.usage()
      .then(
        (r) => {
          setProviders(r.providers);
          setNow(Date.now() / 1000);
        },
        () => undefined, // bridge not up yet: the next tick or reconnect tries again
      );
  }, []);

  useEffect(() => {
    if (conn !== "open") return;
    load();
    const h = setInterval(load, REFRESH_MS);
    return () => clearInterval(h);
  }, [conn, load]);

  useEffect(() => {
    if (!open?.pinned) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(null);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open?.pinned]);

  if (providers.length === 0) return null;
  const shown = providers.find((p) => p.id === open?.id);
  return (
    <div className="usage" ref={ref} data-testid="usage" onMouseLeave={() => !open?.pinned && setOpen(null)}>
      {providers.map((p) => (
        <button
          key={p.id}
          type="button"
          className={`usage-m${open?.id === p.id ? " on" : ""}`}
          data-testid={`usage-${p.id}`}
          data-state={p.state}
          aria-label={meterLabel(p)}
          aria-expanded={open?.id === p.id}
          onMouseEnter={() => !open?.pinned && setOpen({ id: p.id, pinned: false })}
          onFocus={() => !open?.pinned && setOpen({ id: p.id, pinned: false })}
          onClick={() => setOpen((o) => (o?.id === p.id && o.pinned ? null : { id: p.id, pinned: true }))}
        >
          <Ring p={p} />
          <AgentIcon id={p.id} size={14} className="usage-mark" />
          {topPercent(p) === null && <span className={`usage-dot st-${p.state}`} aria-hidden="true" />}
          {topPercent(p) !== null && p.state === "limited" && <span className="usage-dot st-limited" aria-hidden="true" />}
        </button>
      ))}
      {shown && <Card p={shown} now={now} />}
    </div>
  );
}
