// "Answer in progress" marks shared by the sidebar, the chat and away bubbles: a thin rotating ring in the
// accent gradient around a face or a source mark, a three-dot typing indicator, and a one-line text ticker
// that slides up like the activity line. All three go static under prefers-reduced-motion (ui.css).
import { useState, type ReactNode } from "react";

/** The ring's animation delay in seconds: the bot's own angle (`seed`, golden-ratio spread over one 1.2 s turn,
 *  so a handful of bots land far apart) on the page's clock rather than from the moment the ring mounted. A ring
 *  that moves to another row (the typing bubble handing over to the activity line) goes on at the same angle
 *  instead of jumping. `now` is the page clock in ms. */
export function ringDelay(seed: string, now: number): number {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const phase = seed ? Math.round((((h % 1000) * 0.618034) % 1) * 1200) : 0;
  return -((now + phase) % 1200) / 1000;
}

/** The arc itself; its delay is fixed when it mounts, so a re-render never restarts or shifts it. */
function Ring({ s, gap, testId, label, seed }: { s: number; gap: number; testId: string; label?: string; seed: string }) {
  const [delay] = useState(() => ringDelay(seed, performance.now()));
  return (
    <span
      className="ui-ring"
      data-testid={testId}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ width: s, height: s, top: -gap, left: -gap, animationDelay: `${delay}s` }}
    />
  );
}

/** Wraps `children` (an avatar or a mark, `size` px square) and, while `on`, draws a spinner around it: a 2px,
 *  ~110 degree arc whose tail fades in from transparent to the brand gradient, with a round head (ui.css). It is
 *  one CSS conic gradient masked to a 2px band, so every ring has the same shape at any size. The ring is
 *  absolutely positioned `gap` px outside the wrapper, so it never moves the layout. */
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
  return (
    <span className="ui-ring-w" style={{ width: size, height: size }}>
      {children}
      {on && <Ring s={size + gap * 2} gap={gap} testId={testId} label={label} seed={seed} />}
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

/** One line of text; a new text comes in from below while the old one leaves upward (220 ms). `text` keys the
 *  change; `children`, when given, is how that text renders (e.g. with the command in a code span). */
export function Ticker({ text, children }: { text: string; children?: ReactNode }) {
  const node = children ?? text;
  const [cur, setCur] = useState({ text, node, k: 0 });
  const [prev, setPrev] = useState<{ node: ReactNode; k: number } | null>(null);
  if (text !== cur.text) {
    setPrev({ node: cur.node, k: cur.k });
    setCur({ text, node, k: cur.k + 1 });
  }
  return (
    <span className="ui-tick">
      {prev && (
        <span key={`p${prev.k}`} className="ui-tick-t out" aria-hidden onAnimationEnd={() => setPrev(null)}>
          {prev.node}
        </span>
      )}
      <span key={`c${cur.k}`} className={`ui-tick-t${cur.k > 0 ? " in" : ""}`} data-testid="tick-text">
        {cur.node}
      </span>
    </span>
  );
}
