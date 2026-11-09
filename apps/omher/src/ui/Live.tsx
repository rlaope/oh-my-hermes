// "Answer in progress" marks shared by the sidebar, the chat and away bubbles: a thin rotating ring in the
// accent gradient around a face or a source mark, a three-dot typing indicator, and a one-line text ticker
// that slides up like the activity line. All three go static under prefers-reduced-motion (ui.css).
import { useId, useState, type ReactNode } from "react";

/** Wraps `children` (an avatar or a mark, `size` px square) and, while `on`, draws a 1.5px arc around it.
 *  The ring is absolutely positioned `gap` px outside the wrapper, so it never moves the layout. */
export function LiveRing({
  on,
  size,
  gap = 3,
  label,
  testId = "live-ring",
  seed = "",
  children,
}: {
  on: boolean;
  size: number;
  gap?: number;
  /** When set, the ring is announced (role=status); otherwise it is decorative. */
  label?: string;
  testId?: string;
  /** Rings with different seeds (bot names) start at different angles, so two working bots never spin in step. */
  seed?: string;
  children: ReactNode;
}) {
  const id = `ring${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const s = size + gap * 2;
  const c = s / 2;
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  // golden-ratio spread of the hash over one turn (1.2s), so a handful of bots land far apart
  const phase = seed ? -Math.round((((h % 1000) * 0.618034) % 1) * 1200) / 1000 : 0;
  return (
    <span className="ui-ring-w" style={{ width: size, height: size }}>
      {children}
      {on && (
        <svg
          className="ui-ring"
          data-testid={testId}
          role={label ? "status" : undefined}
          aria-label={label}
          aria-hidden={label ? undefined : true}
          width={s}
          height={s}
          viewBox={`0 0 ${s} ${s}`}
          style={{ top: -gap, left: -gap, animationDelay: `${phase}s` }}
        >
          <defs>
            <linearGradient id={id} x1="1" y1="1" x2="0" y2="0">
              <stop offset="0" className="ui-ring-s1" />
              <stop offset="0.55" className="ui-ring-s2" />
              <stop offset="1" className="ui-ring-s3" />
            </linearGradient>
          </defs>
          {/* a faint full track, so a still frame reads as a ring with its arc, not a broken outline */}
          <circle className="ui-ring-track" cx={c} cy={c} r={c - 0.75} fill="none" strokeWidth={1.5} />
          <circle
            className="ui-ring-arc"
            cx={c}
            cy={c}
            r={c - 0.75}
            fill="none"
            stroke={`url(#${id})`}
            strokeWidth={1.5}
            strokeLinecap="round"
            pathLength={100}
            strokeDasharray="40 60"
          />
        </svg>
      )}
    </span>
  );
}

/** Three dots that bounce in turn (1s cycle). `size` is the dot diameter in px. */
export function TypingDots({ size = 6, testId }: { size?: number; testId?: string }) {
  return (
    <span className="ui-typing" data-testid={testId} aria-hidden style={{ ["--dot" as string]: `${size}px` }}>
      <i />
      <i />
      <i />
    </span>
  );
}

/** One line of text; a new text comes in from below while the old one leaves upward (220 ms). */
export function Ticker({ text }: { text: string }) {
  const [cur, setCur] = useState({ text, k: 0 });
  const [prev, setPrev] = useState<{ text: string; k: number } | null>(null);
  if (text !== cur.text) {
    setPrev({ text: cur.text, k: cur.k });
    setCur({ text, k: cur.k + 1 });
  }
  return (
    <span className="ui-tick">
      {prev && (
        <span key={`p${prev.k}`} className="ui-tick-t out" aria-hidden onAnimationEnd={() => setPrev(null)}>
          {prev.text}
        </span>
      )}
      <span key={`c${cur.k}`} className={`ui-tick-t${cur.k > 0 ? " in" : ""}`} data-testid="tick-text">
        {cur.text}
      </span>
    </span>
  );
}
