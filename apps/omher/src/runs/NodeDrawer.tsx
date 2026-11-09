// One node's detail, shared by the panel and the full view: attempt k of n, model, route, time, the last
// reason, earlier attempts, the helper's summary and the handoff. Read-only: the one button only prefills the
// chat composer so the person can ask the bot; it never sends.
import { useEffect, useState } from "react";
import type { RunNode } from "../lib/runs";
import { span } from "../lib/runs";
import { Markdown } from "../chat/parts/Markdown";
import { CloseIcon, IconButton } from "../ui";
import { getStore } from "../state/store";
import { modelLine, runName, STATE_WORD } from "./format";

const PREVIEW = 1200;

export function NodeDrawer({
  runId,
  node,
  text,
  nowS,
  onClose,
}: {
  runId: string;
  node: RunNode;
  text?: string;
  nowS: number;
  onClose: () => void;
}) {
  const [all, setAll] = useState(false);
  useEffect(() => setAll(false), [node.id]);
  const last = node.attempts[node.attempts.length - 1];
  const t = node.started === undefined ? "" : span((node.ended ?? nowS) - node.started);
  const facts = [modelLine(node), node.lane, t].filter(Boolean).join(" · ");
  const long = (text?.length ?? 0) > PREVIEW;
  const bad = node.state === "failed" || node.state === "blocked";
  const ask = () => {
    const s = getStore();
    if (s.getState().ui.runsFull) s.actions.setRunsFull(false);
    s.actions.prefill(`Retry \`${node.id}\` in run \`${runName(runId)}\``);
  };
  return (
    <div className={`rn-drawer${bad ? " bad" : ""}`} data-testid="run-drawer" data-node={node.id}>
      <div className="rn-dh">
        <b title={node.label}>{node.label}</b>
        <IconButton label="Close node" onClick={onClose}>
          <CloseIcon />
        </IconButton>
      </div>
      <div className="rn-df">
        <span className={`rn-word s-${node.state}`} data-testid="run-state-word">
          {STATE_WORD[node.state]}
        </span>
        <span data-testid="run-attempt">{node.attempts.length ? `attempt ${last.n} of ${node.attempts.length}` : "not started"}</span>
        {facts && <span>{facts}</span>}
        {node.route && (
          <span className="rn-routeline">
            route {node.route}
            {node.routeWhy ? ` · ${node.routeWhy}` : ""}
          </span>
        )}
      </div>
      {last?.reason && (
        <div className={`rn-reason${bad ? " bad" : ""}`} data-testid="run-reason">
          {bad && <b>Why: </b>}
          {last.reason}
        </div>
      )}
      {node.attempts.length > 1 && (
        <ol className="rn-atts">
          {node.attempts.slice(0, -1).map((a) => (
            <li key={a.n}>
              #{a.n} {a.outcome || "open"}
              {a.model ? ` · ${a.model}` : ""}
              {a.reason && <span> · {a.reason}</span>}
            </li>
          ))}
        </ol>
      )}
      {node.summary && !text && <div className="rn-sum" data-testid="run-summary">{node.summary}</div>}
      {text ? (
        <>
          <div className="rn-md md" data-testid="run-handoff">
            <Markdown text={all || !long ? text : text.slice(0, PREVIEW) + " …"} />
          </div>
          {long && (
            <button type="button" className="pn-more" onClick={() => setAll((v) => !v)} data-testid="run-handoff-more">
              {all ? "Show less" : "Show all"}
            </button>
          )}
        </>
      ) : (
        !node.summary && <div className="rn-none">No handoff written.</div>
      )}
      {bad && (
        <div className="rn-ask">
          <button type="button" className="rn-askb" onClick={ask} data-testid="run-ask">
            Ask in chat
          </button>
          <span>Puts a retry request in the message box. Nothing is sent.</span>
        </div>
      )}
    </div>
  );
}
