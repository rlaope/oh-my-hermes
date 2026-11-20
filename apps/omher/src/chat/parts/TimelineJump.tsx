// The timeline's way back: a "Jump to bottom" pill when the view is more than a screen above the bottom (with "· N new"
// once messages came in since the person scrolled up), and a one-line header with the person's last message while the
// answer below it is read (that bubble scrolled off the top). Both sit in the scrolling column on 0-high sticky anchors,
// so they take no room and never move the messages.
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { t } from "../../i18n";
import type { TimelineItem } from "../../state/store";

/** The kinds that count as a new message under the pill. */
const counts = (it: TimelineItem) => it.kind === "user" || it.kind === "assistant";

const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
export const scrollBehavior = (): ScrollBehavior => (reduced() ? "auto" : "smooth");

export interface TimelineNav {
  /** more than a screen from the bottom */
  away: boolean;
  /** messages that arrived since the person let go of the bottom */
  fresh: number;
  /** the person's last message while its bubble is above the view, else null */
  pin: { id: string; text: string } | null;
  /** read the scroll position again (after a scroll, a reflow, new items) */
  measure(): void;
  /** the person let go of the bottom (true) or came back to it (false) */
  letGo(off: boolean): void;
  jump(): void;
  showPin(): void;
}

/** `pinned` is the Timeline's own stick-to-bottom flag: the pill's click sets it again. */
export function useTimelineNav(ref: RefObject<HTMLDivElement | null>, items: TimelineItem[], bot: string, pinned: { current: boolean }): TimelineNav {
  const [away, setAway] = useState(false);
  const [pin, setPin] = useState<{ id: string; text: string } | null>(null);
  const [since, setSince] = useState<Set<string> | null>(null);
  const itemsRef = useRef(items);
  itemsRef.current = items;
  // the latest own message, the only one the header carries
  const own = [...items].reverse().find((i) => i.kind === "user");
  const ownId = own?.id ?? null;
  const ownText = own && own.kind === "user" ? own.text.replace(/\s+/g, " ").trim() : "";

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setAway(el.scrollHeight - el.scrollTop - el.clientHeight > el.clientHeight);
    let next: { id: string; text: string } | null = null;
    if (ownId && ownText) {
      const row = el.querySelector<HTMLElement>(`[data-item="${CSS.escape(ownId)}"]`);
      // only while something is drawn under it (the answer being read) and its bubble is wholly above the view
      const after = row?.nextElementSibling;
      if (row && after && !after.classList.contains("tl-anchor") && row.getBoundingClientRect().bottom <= el.getBoundingClientRect().top + 4) next = { id: ownId, text: ownText };
    }
    setPin((p) => (p?.id === next?.id && p?.text === next?.text ? p : next));
  }, [ref, ownId, ownText]);

  const letGo = useCallback((off: boolean) => {
    setSince((s) => (off ? (s ?? new Set(itemsRef.current.filter(counts).map((i) => i.id))) : null));
  }, []);

  // another chat: start over
  useEffect(() => {
    setSince(null);
    setAway(false);
    setPin(null);
  }, [bot]);

  useEffect(() => measure(), [measure, items]);

  const jump = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    pinned.current = true;
    setSince(null);
    setAway(false);
    el.scrollTo({ top: el.scrollHeight, behavior: scrollBehavior() });
  }, [ref, pinned]);

  const showPin = useCallback(() => {
    const el = ref.current;
    if (!el || !pin) return;
    el.querySelector<HTMLElement>(`[data-item="${CSS.escape(pin.id)}"]`)?.scrollIntoView({ block: "start", behavior: scrollBehavior() });
  }, [ref, pin]);

  const fresh = since ? items.filter((i) => counts(i) && !since.has(i.id)).length : 0;
  return { away, fresh, pin, measure, letGo, jump, showPin };
}

/** The sticky top anchor with the person's last message (one muted line; a click brings the bubble back). */
export function PinnedOwn({ nav }: { nav: TimelineNav }) {
  return (
    <div className="tl-anchor tl-anchor-top" aria-hidden={nav.pin ? undefined : true}>
      {nav.pin && (
        <button type="button" className="tl-pin" data-testid="pinned-own" data-pin={nav.pin.id} title={nav.pin.text} aria-label={t("tl.pinnedOwn", { text: nav.pin.text })} onClick={nav.showPin}>
          <span className="tl-pin-t">{nav.pin.text}</span>
        </button>
      )}
    </div>
  );
}

/** The sticky bottom anchor with the pill. */
export function JumpPill({ nav }: { nav: TimelineNav }) {
  const label = nav.fresh ? `${t("tl.jump")} · ${t("tl.jumpNew", { n: nav.fresh })}` : t("tl.jump");
  return (
    <div className="tl-anchor tl-anchor-bottom" aria-hidden={nav.away ? undefined : true}>
      {nav.away && (
        <button type="button" className="tl-jump" data-testid="jump-bottom" data-new={nav.fresh} onClick={nav.jump}>
          {label}
        </button>
      )}
    </div>
  );
}
