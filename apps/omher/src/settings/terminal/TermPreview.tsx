// The terminal preview on Settings > Terminal: a real xterm (the one SESSIONS terminals are), made with the same
// options, showing a fixed sample. It takes no typing; it is there to show a theme and the look options before a
// person goes back to a session.
import { useEffect, useRef } from "react";
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { applyLook, termOptions } from "../../sessions/term/look";
import { SAMPLE_COLS, SAMPLE_ROWS, SAMPLE_SELECT, termSample } from "../../sessions/term/look-sample";
import type { TermSettings } from "../../sessions/term/settings";
import type { TermTheme } from "../../sessions/term/themes";
import { t } from "../../i18n";

export function TermPreview({ theme, settings }: { theme: TermTheme; settings: TermSettings }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef<{ term: Terminal; fit: FitAddon } | null>(null);
  const now = useRef({ theme, settings });
  now.current = { theme, settings };

  /** The look a session's terminal has, except that the cursor keeps its shape: the preview never has the
   *  keyboard, and a terminal without it draws a block cursor as an outline. */
  const look = () => {
    const l = live.current;
    if (!l) return;
    const { theme: th, settings: s } = now.current;
    applyLook(l.term, th.theme, s);
    l.term.options.cursorInactiveStyle = s.cursorStyle;
  };

  /** As many columns as the box is wide, the sample's rows, and the sample's selection (a resize clears it). */
  const layout = () => {
    const l = live.current;
    if (!l || !host.current?.isConnected) return;
    let cols = l.term.cols;
    try {
      const d = l.fit.proposeDimensions();
      if (d && Number.isFinite(d.cols)) cols = d.cols;
    } catch {
      /* not measurable yet */
    }
    if (cols !== l.term.cols || l.term.rows !== SAMPLE_ROWS) l.term.resize(cols, SAMPLE_ROWS);
    // wrapped lines (a large font on a narrow page) would put the selection on other text
    if (cols >= SAMPLE_COLS) l.term.select(SAMPLE_SELECT.col, SAMPLE_SELECT.row, SAMPLE_SELECT.length);
    else l.term.clearSelection();
  };

  useEffect(() => {
    let gone = false;
    let ro: ResizeObserver | null = null;
    void Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit"), import("@xterm/xterm/css/xterm.css")]).then(([{ Terminal }, { FitAddon }]) => {
      const el = host.current;
      if (gone || !el) return;
      const { theme: th, settings: s } = now.current;
      const term = new Terminal({ ...termOptions(th.theme, s), disableStdin: true, scrollback: 0, rows: SAMPLE_ROWS });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(el);
      live.current = { term, fit };
      look();
      layout();
      term.write(termSample(), layout);
      ro = new ResizeObserver(layout);
      ro.observe(el);
    });
    return () => {
      gone = true;
      ro?.disconnect();
      live.current?.term.dispose();
      live.current = null;
    };
    // made once; the look follows in the effect below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    look();
    layout();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, settings]);

  return (
    <div className="term-pv" role="img" aria-label={t("term.preview")} data-testid="term-preview" data-theme-id={theme.id}>
      <div className="term-pv-host" ref={host} />
    </div>
  );
}
