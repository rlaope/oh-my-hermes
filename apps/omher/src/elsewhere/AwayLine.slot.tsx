// Timeline: one read-only line per elsewhere session; expands to a peek of its last messages.
// There is never an input here: those threads are answered in their own apps.
import { useEffect, useState } from "react";
import type { SlotProps } from "../features";
import { useStore } from "../state/store";
import { ChevronRight, Spinner } from "../ui";
import { awayTime, sourceName } from "./format";
import { useNow } from "./useNow";
import "./elsewhere.css";

export const slot = "elsewhereLine";

const PEEK_LIMIT = 4;

export default function AwayLine({ bot, item }: SlotProps["elsewhereLine"]) {
  const s = useStore();
  const a = item.away;
  const [open, setOpen] = useState(false);
  const now = useNow(a.running);
  const peek = s.peeks[a.id];
  const src = sourceName(a.source);

  // Read the peek on expand, and again whenever the session moves on while expanded.
  useEffect(() => {
    if (open) void s.peek(a.id, PEEK_LIMIT, bot);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, a.id, a.last_active, a.message_count, bot]);

  const shown = peek?.messages.length ?? 0;
  const more = Math.max(0, (peek?.total ?? a.message_count) - shown);

  return (
    <div className={`ew-away${open ? " open" : ""}`} data-testid="away" data-source={a.source} data-session={a.id}>
      <button
        type="button"
        className="ew-away-h"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={open ? "Hide messages" : `Show the last messages in ${src}`}
      >
        <span className="ew-src">
          <i className={`src-sq src-${a.source}`} />
          {src}
        </span>
        <span className="ew-ttl">{a.label}</span>
        {a.running && <Spinner size={11} label={`${src} session working`} />}
        <span className="ew-tm" data-testid="away-time">
          {awayTime(a, now)}
        </span>
        <span className="ew-chev" aria-hidden="true">
          <ChevronRight />
        </span>
      </button>
      {open && (
        <div className="ew-away-b" data-testid="peek">
          {peek?.error ? (
            <div className="ew-peek-note">Could not read this thread: {peek.error}</div>
          ) : !peek || (peek.loading && shown === 0) ? (
            <div className="ew-peek-note">Loading…</div>
          ) : shown === 0 ? (
            <div className="ew-peek-note">No messages yet.</div>
          ) : (
            <div className="ew-peek">
              {peek.messages.map((m, i) => (
                <div key={`${m.ts}-${i}`} className="ew-peek-m" data-testid="peek-msg">
                  <b>{m.author || (m.role === "assistant" ? s.bots.find((b) => b.name === bot)?.display_name ?? bot : "User")}</b>
                  <span>{m.text}</span>
                </div>
              ))}
            </div>
          )}
          <div className="ew-peek-f">
            {/* v0.1 opens nothing: the link only says where the thread lives. */}
            <span className="ew-open" title={`Opens in ${src}`} aria-disabled="true">
              Open in {src} ↗
            </span>
            <em>{more > 0 ? `+${more} message${more === 1 ? "" : "s"} · read-only here` : "read-only here"}</em>
          </div>
        </div>
      )}
    </div>
  );
}
