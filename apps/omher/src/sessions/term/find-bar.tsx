// The find bar of a SESSIONS terminal: a field, "2 of 14", previous and next, close. It sits at the terminal's top
// right only while it is open (a closed bar covers nothing), Enter / Shift+Enter move between matches and Esc
// closes it and gives the keyboard back to the terminal. Two toggles, Match case (Aa, Alt+C) and Regular expression
// (.*, Alt+R), hold for the rest of the page load, in every terminal's bar. A pattern that is not a valid regular
// expression shows the field in an error state and finds nothing. The matching itself is engine-find.ts.
import { useEffect, useRef, useState } from "react";
import "./find.css";
import { ChevronDown, CloseIcon } from "../../ui";
import { composing } from "../../lib/ime";
import { t } from "../../i18n";
import { FIND_PLAIN, validPattern, type FindOptions, type FindRequest, type FindResults } from "./engine-find";
import { findOptionKey, isFindKey } from "./engine-input";
import { isMacPlatform } from "./engine-links";

/** "2 of 14"; "No matches" for a search that found none; "14+" when the add-on stopped counting at its limit. */
export function findCountText(r: FindResults, text: string): string {
  if (!text) return "";
  if (r.count === 0) return t("find.none");
  return t(r.capped ? "find.countMore" : "find.count", { n: r.index >= 0 ? r.index + 1 : "–", total: r.count });
}

/** What the two toggles show: the same in every language, as in other editors' find bars. */
const CASE_GLYPH = "Aa";
const REGEX_GLYPH = ".*";

/** The toggles as the person last left them: kept for the page load, not saved. */
let kept: FindOptions = FIND_PLAIN;

export function FindBar({ req, onClose }: { req: FindRequest; onClose: () => void }) {
  const { term, finder } = req;
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(() => {
    // what is selected in the terminal (one short line) is what the person most likely wants to find
    const sel = term.hasSelection() ? term.getSelection() : "";
    return sel && sel.length <= 200 && !/[\r\n]/.test(sel) ? sel : "";
  });
  const [opts, setOpts] = useState<FindOptions>(kept);
  const [res, setRes] = useState<FindResults>({ index: -1, count: 0, capped: false });
  const bad = opts.regex && !!text && !validPattern(text);
  useEffect(() => finder.onResults(setRes), [finder]);
  // The bar goes with its terminal's view (another session, Settings, a bot): the highlights go with the bar, so
  // none are left on a terminal that shows no bar to close them with.
  useEffect(() => () => finder.clear(), [finder]);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
    if (text) finder.search(text, "next", true, opts);
    // opening runs once; typing searches in onChange
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    finder.clear();
    onClose();
    term.focus();
  };
  const go = (dir: "next" | "previous") => text && finder.search(text, dir, false, opts);
  // a toggle clicked leaves the keyboard in the field, so Enter goes on to the next match
  const keepField = (e: React.MouseEvent) => e.preventDefault();
  const flip = (k: keyof FindOptions) => {
    const next = { ...opts, [k]: !opts[k] };
    kept = next;
    setOpts(next);
    finder.search(text, "next", true, next);
  };

  return (
    <div
      className="tfind"
      role="search"
      aria-label={t("find.label")}
      data-testid="term-find"
      onMouseDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        // Esc closes from the field and from a button the person clicked last
        if (e.key === "Escape" && !composing(e)) {
          e.preventDefault();
          e.stopPropagation();
          close();
          return;
        }
        const k = composing(e) ? null : findOptionKey(e);
        if (k) {
          e.preventDefault();
          e.stopPropagation();
          flip(k);
        }
      }}
    >
      <input
        ref={input}
        type="text"
        className={bad ? "tfind-q tfind-bad" : "tfind-q"}
        aria-invalid={bad || undefined}
        title={bad ? t("find.badRegex") : undefined}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        placeholder={t("find.placeholder")}
        aria-label={t("find.label")}
        value={text}
        data-testid="term-find-input"
        onChange={(e) => {
          setText(e.target.value);
          finder.search(e.target.value, "next", true, opts);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (!composing(e)) go(e.shiftKey ? "previous" : "next");
          } else if (isFindKey(e.nativeEvent, isMacPlatform(), false)) {
            // find again while the bar is open: back to its field
            e.preventDefault();
            e.currentTarget.select();
          }
        }}
      />
      <span className={bad ? "tfind-n tfind-bad" : "tfind-n"} aria-live="polite" data-testid="term-find-count">
        {bad ? t("find.badRegex") : findCountText(res, text)}
      </span>
      <button
        type="button"
        className="tfind-b tfind-opt"
        aria-label={t("find.matchCase")}
        title={t("find.matchCaseTip")}
        aria-pressed={opts.caseSensitive}
        onMouseDown={keepField}
        onClick={() => flip("caseSensitive")}
        data-testid="term-find-case"
      >
        {CASE_GLYPH}
      </button>
      <button
        type="button"
        className="tfind-b tfind-opt"
        aria-label={t("find.regex")}
        title={t("find.regexTip")}
        aria-pressed={opts.regex}
        onMouseDown={keepField}
        onClick={() => flip("regex")}
        data-testid="term-find-regex"
      >
        {REGEX_GLYPH}
      </button>
      <button type="button" className="tfind-b" aria-label={t("find.prev")} title={t("find.prev")} disabled={!text || res.count === 0} onClick={() => go("previous")} data-testid="term-find-prev">
        <span className="tfind-up">
          <ChevronDown size={10} />
        </span>
      </button>
      <button type="button" className="tfind-b" aria-label={t("find.next")} title={t("find.next")} disabled={!text || res.count === 0} onClick={() => go("next")} data-testid="term-find-next">
        <ChevronDown size={10} />
      </button>
      <button type="button" className="tfind-b" aria-label={t("find.close")} title={t("find.close")} onClick={close} data-testid="term-find-close">
        <CloseIcon />
      </button>
    </div>
  );
}
