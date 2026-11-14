// The terminal preview on Settings > Terminal: a real xterm (the one SESSIONS terminals are), made with the same
// options, showing a fixed sample. It takes no typing; it is there to show a theme and the look options before a
// person goes back to a session.
import { useEffect, useRef } from "react";
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import { applyLook, termOptions } from "../../sessions/term/look";
import { SAMPLE_COLS, SAMPLE_ROWS, SAMPLE_SELECT, SAMPLE_WIDE_COLS, termSample } from "../../sessions/term/look-sample";
import type { TermSettings } from "../../sessions/term/settings";
import type { TermTheme } from "../../sessions/term/themes";
import { t } from "../../i18n";

// xterm draws no cursor until its terminal has had the keyboard once, and the preview never has it. Leaving the
// alternate screen (a no-op here: the sample is on the normal one) is the escape sequence that marks the cursor as
// in use, so the picked cursor shape shows.
const SHOW_CURSOR = "\x1b[?47l";

export function TermPreview({ theme, settings }: { theme: TermTheme; settings: TermSettings }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef<{ term: Terminal; fit: FitAddon } | null>(null);
  const now = useRef({ theme, settings });
  now.current = { theme, settings };
  /** Which sample is on screen: the one with the second pane (`true`), the narrow one, or none yet. */
  const wide = useRef<boolean | null>(null);

  /** The look a session's terminal has, except that the cursor keeps its shape: the preview never has the
   *  keyboard, and a terminal without it draws a block cursor as an outline. */
  const look = () => {
    const l = live.current;
    if (!l) return;
    const { theme: th, settings: s } = now.current;
    applyLook(l.term, th.theme, s);
    l.term.options.cursorInactiveStyle = s.cursorStyle;
    // the sample is one screen: it keeps no rows above it, whatever the setting
    l.term.options.scrollback = 0;
  };

  /** The sample's selection (a resize and a rewrite both clear it). */
  const select = () => {
    const l = live.current;
    if (!l) return;
    // wrapped lines (a large font on a narrow page) would put the selection on other text
    if (l.term.cols >= SAMPLE_COLS) l.term.select(SAMPLE_SELECT.col, SAMPLE_SELECT.row, SAMPLE_SELECT.length);
    else l.term.clearSelection();
  };

  /** As many columns as the box is wide, the sample's rows, the sample that suits that width, its selection. */
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
    const w = cols >= SAMPLE_WIDE_COLS;
    if (wide.current === w) return select();
    // the other sample: a box that became wide enough for the second pane, or too narrow for it
    wide.current = w;
    l.term.reset();
    l.term.write(termSample(cols) + SHOW_CURSOR, select);
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
      ro = new ResizeObserver(layout);
      ro.observe(el);
    });
    return () => {
      gone = true;
      ro?.disconnect();
      live.current?.term.dispose();
      live.current = null;
      wide.current = null;
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
