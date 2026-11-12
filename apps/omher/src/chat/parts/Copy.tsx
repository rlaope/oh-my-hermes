// A quiet copy control: an icon that shows on hover of its row (CSS), copies its text, and says "Copied" for a
// moment. Used on a bot answer and on each code block, in the bot chat and SESSIONS chats alike.
import { useEffect, useRef, useState } from "react";
import { t } from "../../i18n";
import "./copy.css";

const CopyIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" aria-hidden="true">
    <rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2" />
    <path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5" />
  </svg>
);
const CheckIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);

/** Copies `text` (a function: read when clicked, so a code block's text is never held twice). */
export function CopyButton({ text, className, testId }: { text: () => string; className?: string; testId?: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);
  const label = done ? t("copy.done") : t("copy.copy");
  return (
    <button
      type="button"
      className={`copy-btn${done ? " done" : ""}${className ? ` ${className}` : ""}`}
      aria-label={label}
      title={label}
      data-testid={testId}
      onClick={(e) => {
        e.stopPropagation();
        void navigator.clipboard?.writeText(text()).then(
          () => {
            setDone(true);
            if (timer.current) clearTimeout(timer.current);
            timer.current = setTimeout(() => setDone(false), 1400);
          },
          () => {},
        );
      }}
    >
      {done ? <CheckIcon /> : <CopyIcon />}
    </button>
  );
}
