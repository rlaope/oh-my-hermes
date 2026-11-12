// The sidebar's one sign that oh-my-hermes is missing: a quiet "!" circle left of the top row's +, shown only to a
// person who has Hermes and not `omh` (and not after "Don't show again"). It opens a popover right under the top row,
// exactly as wide as the sidebar's rows (their left and right inset), so nothing of a row shows beside it: what
// oh-my-hermes adds, Install (the shell's one fixed installer, its output shown here in the setup screen's own log
// view) and "Don't show again". When the install ends well the agents are read again, `omh` is found and the "!" goes.
// The popover takes its natural height (it has its own border, so it may end partway down a row) and stays inside the
// window, scrolling its text inside when it must.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { IconButton, Popover, Spinner } from "../ui";
import { t } from "../i18n";
import { InstallLog } from "../app/BridgeGate";
import { hermesOnly } from "../sessions/agents";
import { getSessions, useSessions } from "../sessions/sessions";
import { getAddOmh, useAddOmh } from "../sessions/addOmh";

const AlertIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5" strokeLinecap="round" />
    <circle cx="12" cy="16.4" r="0.6" fill="currentColor" />
  </svg>
);

/** Air between the popover and the window's bottom edge. */
const WINDOW_AIR = 6;
/** How far a bot row's live ring reaches past the row's left edge (`.ui-ring`, measured: 4px). */
const RING_BLEED = 4;

export function OmhNotice() {
  const ss = useSessions();
  const add = useAddOmh();
  const inner = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [max, setMax] = useState<number | undefined>(undefined);
  // where the popover sits, from its anchor (the "!" wrapper): the sidebar rows' inset, the top row's bottom edge
  const [place, setPlace] = useState<{ left: number; top: number; width: number } | null>(null);
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const shown = hermesOnly(ss.agents) && !(add.hidden && !add.open);
  useLayoutEffect(() => {
    if (!shown || !add.open) return;
    const measure = () => {
      const box = inner.current;
      const pop = box?.parentElement;
      const anchor = pop?.offsetParent;
      if (!box || !pop || !(anchor instanceof HTMLElement)) return;
      const side = anchor.closest<HTMLElement>(".side");
      const sideTop = side?.querySelector(".side-top");
      if (!side || !sideTop) return;
      // the rows' own box (the sidebar's content box, which a bot row spans), widened by what a row draws past it: the
      // live ring around a working bot's face reaches RING_BLEED px into the sidebar's padding
      const s = side.getBoundingClientRect();
      const cs = getComputedStyle(side);
      const left = s.left + Math.max(0, parseFloat(cs.paddingLeft) - RING_BLEED);
      const width = s.right - Math.max(0, parseFloat(cs.paddingRight) - RING_BLEED) - left;
      const top = sideTop.getBoundingClientRect().bottom;
      const a = anchor.getBoundingClientRect();
      const p = { left: left - a.left, top: top - a.top, width };
      setPlace((o) => (o && o.left === p.left && o.top === p.top && o.width === p.width ? o : p));
      // its natural height, capped so the bottom edge stays WINDOW_AIR above the window's; the text then scrolls
      const chrome = pop.offsetHeight - box.offsetHeight;
      const cap = Math.max(0, Math.floor(innerHeight - WINDOW_AIR - top - chrome));
      setMax((m) => (m === cap ? m : cap));
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (content.current) ro.observe(content.current);
    addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      removeEventListener("resize", measure);
    };
  }, [shown, add.open]);
  if (!shown) return null;
  const running = add.phase === "running";
  const failed = add.phase === "failed";
  const a = getAddOmh();
  return (
    <div
      className="omh-note"
      style={place ? ({ "--omh-pop-l": `${place.left}px`, "--omh-pop-t": `${place.top}px` } as CSSProperties) : undefined}
    >
      <IconButton
        label={t("omh.icon")}
        className="omh-note-b"
        aria-haspopup="dialog"
        aria-expanded={add.open}
        onClick={() => a.setOpen(!add.open)}
        data-testid="omh-notice"
      >
        {running ? <Spinner size={13} label={t("gate.installing")} /> : <AlertIcon />}
      </IconButton>
      <Popover open={add.open} onClose={() => a.setOpen(false)} align="right" width={place?.width ?? "calc(var(--side-w) - 16px)"} label="oh-my-hermes" className="omh-pop">
        <div ref={inner} className="omh-pop-in" style={{ maxHeight: max }} data-testid="omh-pop" data-phase={add.phase}>
          <div ref={content} className="omh-pop-c">
            <b className="omh-pop-t">oh-my-hermes</b>
            <p className="omh-pop-p">{t("omh.pop.body")}</p>
            <InstallLog lines={running ? add.lines : []} compact testId="omh-pop-log" />
            {failed && add.error && (
              <p className="omh-pop-err" role="status" title={add.error} data-testid="omh-pop-error">
                {add.error}
              </p>
            )}
          </div>
          <div className="omh-pop-a">
            <button type="button" className="omh-pop-go" disabled={running} onClick={() => void a.run()} data-testid="omh-pop-install">
              {running ? t("gate.installing") : failed ? t("gate.again") : t("gate.install")}
            </button>
            <button type="button" className="omh-pop-hide" disabled={running} onClick={() => a.hide()} data-testid="omh-pop-hide">
              {t("omh.pop.hide")}
            </button>
          </div>
        </div>
      </Popover>
    </div>
  );
}
