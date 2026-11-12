// What a SESSIONS agent showed of its work inside one turn's activity line: a file edit's change (DiffView), its
// todo list (PlanList) and its thinking (ThinkingText). The adapters send all three in one agent-neutral shape
// (`tool.diff`, `plan`, `thinking.text`); an agent that sends none of them shows none of these.
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { DiffFile, PlanItem } from "../../lib/protocol";
import { t, type Key } from "../../i18n";
import { ChevronRight } from "../../ui";
import "./work.css";

/** One file's change: path and counts, then its lines in mono, capped in height with their own scroll. */
function DiffFileView({ f }: { f: DiffFile }) {
  return (
    <div className="dv-file" data-testid="diff-file">
      <div className="dv-head">
        <span className="dv-path" title={f.path}>
          {f.path}
        </span>
        {f.kind === "add" && <span className="dv-kind">{t("diff.new")}</span>}
        {f.kind === "delete" && <span className="dv-kind">{t("diff.deleted")}</span>}
        {f.added > 0 && <span className="dv-add">+{f.added}</span>}
        {f.removed > 0 && <span className="dv-del">−{f.removed}</span>}
      </div>
      <div className="dv-body" data-testid="diff-body">
        {f.lines.map((l, i) => {
          const k = l.startsWith("@@") ? "hunk" : l[0] === "+" ? "add" : l[0] === "-" ? "del" : "ctx";
          return (
            <div key={i} className={`dv-l ${k}`} data-kind={k}>
              {k === "hunk" ? "⋯" : l.slice(1) || " "}
            </div>
          );
        })}
        {f.more ? <div className="dv-l more">{t("diff.more", { n: f.more })}</div> : null}
      </div>
    </div>
  );
}

/** A file edit's change, per file. Opened by a click, it scrolls itself into view (only then: never while an
 *  answer streams). */
export function DiffView({ files }: { files: DiffFile[] }) {
  const ref = useRef<HTMLDivElement>(null);
  // a block body: newer Chromium (WebView2) returns a Promise from scrollIntoView, which React would then call as
  // this effect's cleanup when the diff closes or its turn is taken back ("destroy is not a function", blank app)
  useLayoutEffect(() => {
    ref.current?.scrollIntoView?.({ block: "nearest" });
  }, []);
  return (
    <div className="dv" data-testid="diff-view" ref={ref}>
      {files.map((f, i) => (
        <DiffFileView key={`${f.path}-${i}`} f={f} />
      ))}
    </div>
  );
}

const PLAN_STATE: Record<PlanItem["status"], Key> = { pending: "plan.pending", in_progress: "plan.doing", completed: "plan.done" };

/** The agent's todo list, one row per item; the list changes in place as the agent updates it. */
export function PlanList({ items }: { items: PlanItem[] }) {
  const done = items.filter((i) => i.status === "completed").length;
  return (
    <div className="pl" data-testid="plan">
      <div className="pl-head">{t("plan.count", { done, n: items.length })}</div>
      {items.map((i, k) => (
        <div key={k} className={`pl-row ${i.status}`} data-testid="plan-row" data-status={i.status}>
          <span className="pl-box" aria-label={t(PLAN_STATE[i.status])} role="img">
            {i.status === "completed" ? "✓" : i.status === "in_progress" ? "•" : ""}
          </span>
          <span className="pl-t">{i.text}</span>
        </div>
      ))}
    </div>
  );
}

/** `name` spans as inline code, the way the answer shows them; the rest of markdown stays plain text here. */
function inlineCode(text: string): ReactNode[] {
  return text.split(/`([^`\n]+)`/).map((part, i) => (i % 2 ? <code key={i}>{part}</code> : part));
}

/** What the agent thought: one quiet line, closed by default; a click opens the text. */
export function ThinkingText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`th${open ? " open" : ""}`} data-testid="thinking">
      <button type="button" className="th-h" aria-expanded={open} onClick={() => setOpen((o) => !o)} data-testid="thinking-toggle">
        {t("think.label")}
        <span className="th-chev" aria-hidden>
          <ChevronRight size={9} />
        </span>
      </button>
      {open && (
        <div className="th-body" data-testid="thinking-text">
          {inlineCode(text.trim())}
        </div>
      )}
    </div>
  );
}
