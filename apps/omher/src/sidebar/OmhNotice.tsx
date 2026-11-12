// The sidebar's one sign that oh-my-hermes is missing: a quiet "!" circle left of the top row's +, shown only to a
// person who has Hermes and not `omh` (and not after "Don't show again"). It opens a small popover under it, right-
// aligned to it: what oh-my-hermes adds, Install (the shell's one fixed installer, its output shown here in the setup
// screen's own log view) and "Don't show again". When the install ends well the agents are read again, `omh` is found
// and the "!" goes. The popover's bottom edge lands on a sidebar row boundary (the + menu's rule), so no row shows
// half under it, and it stays inside the window, scrolling inside when it must.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
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

/** Air between the popover and the window's bottom edge, and between its edge and a row it stops above. */
const WINDOW_AIR = 6;
const ROW_CLEAR = 2;
/** The sidebar rows a popover edge may not cut (the + menu's rows, without the top row it hangs from). */
const ROWS = ".bot-list > *, .ss-list > *, .side-sec > .side-sh, .side > :not(.side-sec):not(.side-top)";

type Box = { top: number; bottom: number };

/** Where the popover's bottom edge goes, as its inner height: a row it would cut is then covered whole (its edge
 *  moves down to that row's bottom) when that stays inside the window; else the edge moves up above every row it
 *  would cut and the content scrolls. `min` keeps it that tall, `max` caps it. */
export function fitNotice(top: number, natural: number, chrome: number, limit: number, rows: Box[]): { min?: number; max?: number } {
  const cutAt = (b: number) => rows.find((r) => r.top >= top && r.top < b && r.bottom > b);
  let bottom = Math.min(top + chrome + natural, limit);
  const cut = cutAt(bottom);
  if (cut && cut.bottom <= limit && bottom === top + chrome + natural) {
    bottom = cut.bottom;
    // that row's bottom may itself sit inside a taller neighbour (rows never overlap, so this ends)
    for (let c; (c = cutAt(bottom)) && c.bottom <= limit; ) bottom = c.bottom;
  }
  for (let c; (c = cutAt(bottom)); ) bottom = c.top - ROW_CLEAR;
  const inner = bottom - top - chrome;
  // whole px toward the safe side: a taller box covers its last row whole, a shorter one stays above the row
  return inner >= natural ? { min: Math.ceil(inner) } : { max: Math.max(0, Math.floor(inner)) };
}

export function OmhNotice() {
  const ss = useSessions();
  const add = useAddOmh();
  const inner = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const actions = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState<{ min?: number; max?: number }>({});
  useEffect(() => {
    if (ss.agents === null) void getSessions().loadAgents();
  }, [ss.agents]);
  const shown = hermesOnly(ss.agents) && !(add.hidden && !add.open);
  useLayoutEffect(() => {
    if (!shown || !add.open) return;
    const measure = () => {
      const box = inner.current;
      const c = content.current;
      const act = actions.current;
      const pop = box?.parentElement;
      const anchor = pop?.offsetParent;
      if (!box || !c || !act || !pop || !(anchor instanceof HTMLElement)) return;
      // offsets, not the popover's own rect: they ignore its pop-in transform
      const top = anchor.getBoundingClientRect().top + pop.offsetTop;
      const chrome = pop.offsetHeight - box.offsetHeight;
      const rows = [...(anchor.closest(".side")?.querySelectorAll(ROWS) ?? [])].map((r) => r.getBoundingClientRect()).filter((r) => r.height > 0);
      // its natural height: all of the text (scrolled or not) and the actions under it, never the room a `min` adds
      const natural = c.scrollHeight + (act.offsetTop + act.offsetHeight - (c.offsetTop + c.offsetHeight));
      const next = fitNotice(top, natural, chrome, innerHeight - WINDOW_AIR, rows);
      setFit((f) => (f.min === next.min && f.max === next.max ? f : next));
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
    <div className="omh-note">
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
      <Popover open={add.open} onClose={() => a.setOpen(false)} align="right" width={200} label="oh-my-hermes" className="omh-pop">
        <div ref={inner} className="omh-pop-in" style={{ minHeight: fit.min, maxHeight: fit.max }} data-testid="omh-pop" data-phase={add.phase}>
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
          <div ref={actions} className="omh-pop-a">
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
