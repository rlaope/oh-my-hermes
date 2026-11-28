// The top of a session's right panel: what runs in the focused pane, from what omher already knows and the harness's
// own records. Harness mark and name, its conversation's title, folder, program, model, how long it has run, and its
// live state (Working / Needs you / Ready, as the header reads it). A field the source did not give is left out: no
// guessed model, no percentages, no tokens. A plain shell shows its folder, program and running time.
import { useEffect, useState } from "react";
import { getStore } from "../state/store";
import { t, type Key } from "../i18n";
import { harness, harnessByName } from "../harness/registry";
import { modelName } from "../runs/format";
import { span } from "../lib/runs";
import { useNow } from "../elsewhere/useNow";
import { agentDef, folderName, isShell, termStatus, tildePath, type SessionRec } from "./agents";
import { paneHarness, type PaneHarness } from "./paneHarness";
import { pickTitle } from "./titles";
import { TermRowMark, fgName } from "./TermRowMark";
import { useTermFace, termActs } from "./termActivity";
import { usePendingRequests } from "./termShare";
import { useSessions } from "./sessions";

/** What the harness's own files say about its conversation (`cli.title`): title, model, start. Re-read while the
 *  pane is shown, every `every` ms (a rename, a model switch, `/clear` moving to a new conversation). */
export function useHarnessAbout(h: PaneHarness, cwd: string, every = 15_000): { title: string; model: string; started?: number } | null {
  const [got, setGot] = useState<{ key: string; v: { title: string; model: string; started?: number } } | null>(null);
  const key = h.titled ? `${h.titled.agent}:${h.titled.session}` : "";
  useEffect(() => {
    if (!h.titled) return;
    const { agent, session } = h.titled;
    let live = true;
    const read = () =>
      getStore()
        .actions.cliTitle(agent, session, cwd)
        .then((r) => {
          if (!live || !r || typeof r !== "object") return;
          const title = typeof r.title === "string" ? r.title.trim() : "";
          const model = typeof r.model === "string" ? r.model : "";
          const started = typeof r.started === "number" && r.started > 0 ? r.started : undefined;
          setGot({ key: `${agent}:${session}`, v: { title, model, started } });
        })
        .catch(() => undefined); // an older bridge, or no file yet
    void read();
    const timer = setInterval(read, every);
    return () => {
      live = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, cwd, every]);
  return got && got.key === key ? got.v : null;
}

/** The pane's live state as its header reads it, or null when it is not running. */
function useLiveState(rec: SessionRec): { key: Key; cls: string } | null {
  const ss = useSessions();
  const running = rec.status === "running" && !rec.paused;
  const { act, now } = useTermFace(rec.id, rec.startedAt, running);
  const asked = usePendingRequests().some((r) => r.sessionId === rec.id);
  if (!running) return null;
  const st = asked ? "bell" : termStatus({ status: rec.status, exitCode: rec.exitCode, lastOut: act.progress ? now : act.lastOut }, ss.unseen[rec.id], now);
  return st === "busy" ? { key: "ss.working", cls: "busy" } : st === "bell" ? { key: "ss.needsYou", cls: "needs" } : { key: "ss.ready", cls: "idle" };
}

export function SessionDetails({ rec }: { rec: SessionRec }) {
  const ss = useSessions();
  const h = paneHarness(rec);
  const about = useHarnessAbout(h, termActs.get(rec.id).cwd ?? rec.cwd);
  const live = useLiveState(rec);
  const running = rec.status === "running" || rec.status === "starting";
  const now = useNow(running, 1000);
  const id = h.cli ? harnessByName(h.cli) : null;
  const name = h.cli ? (id && id !== "generic" ? harness(id).label : fgName(h.cli)) : agentDef(rec.agent).label;
  const cwd = termActs.get(rec.id).cwd ?? rec.cwd;
  // a harness in a Shell row: its own conversation's title (Claude Code's, a Codex thread's); a row's own title else
  const title = (h.inShell ? about?.title : pickTitle(rec, "").title || about?.title) || "";
  const model = about?.model || (!h.inShell ? rec.model : "") || "";
  // how long the harness has run: from its conversation's first line when its own record says, else (the row's own
  // agent, or a plain shell) since the terminal started
  const sinceS = h.inShell && h.cli ? about?.started : rec.startedAt / 1000;
  const program = h.cli ? (h.inShell ? h.cli : agentDef(rec.agent).program) : isShell(rec.agent) ? (rec.shell ?? agentDef(rec.agent).program) : agentDef(rec.agent).program;
  return (
    <div className="sd" data-testid="session-details" data-harness={h.cli ?? "shell"} data-session={rec.id}>
      <div className="sd-head">
        <TermRowMark agent={h.cli} size={16} />
        <span className="sd-name" data-testid="session-details-harness">
          {name}
        </span>
        {live && (
          <span className={`sd-st ${live.cls}`} data-testid="session-details-state" data-state={live.cls}>
            {t(live.key)}
          </span>
        )}
      </div>
      {title && (
        <div className="sd-title" data-testid="session-details-title" title={title}>
          {title}
        </div>
      )}
      <dl className="sd-facts">
        <dt>{t("sd.folder")}</dt>
        <dd className="sd-mono" data-testid="session-details-folder" title={cwd}>
          {tildePath(cwd, ss.home) || folderName(cwd)}
        </dd>
        <dt>{t("sd.program")}</dt>
        <dd className="sd-mono" data-testid="session-details-program">
          {program}
        </dd>
        {model && (
          <>
            <dt>{t("ss.model")}</dt>
            <dd data-testid="session-details-model" title={model}>
              {modelName(model)}
            </dd>
          </>
        )}
        {sinceS !== undefined && running && (
          <>
            <dt>{t("sd.running")}</dt>
            <dd data-testid="session-details-time">{span(now / 1000 - sinceS)}</dd>
          </>
        )}
      </dl>
    </div>
  );
}
