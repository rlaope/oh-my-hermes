// The run's plan, at the top of the full view and first in the panel: title and goal, the layers as chips
// ("L1 · 3 parts"), how many parts are done / running / waiting / failed, and the time so far. A run nobody has
// started yet says so ("Starts in 0:10" when the run carries a start time) and offers Start now / Edit, which,
// like "Ask in chat", only put a request in the message box: nothing here starts or edits a run.
import type { AgentRun } from "../lib/runs";
import { isRepaired, span } from "../lib/runs";
import { getStore } from "../state/store";
import { runName } from "./format";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

type Tone = "done" | "running" | "failed" | "waiting";

export function PlanCard({ run, mode, nowS, names }: { run: AgentRun & { startsAt?: number }; mode: "panel" | "full"; nowS: number; names?: string[] }) {
  const layers: { n: number; tone: Tone }[] = [];
  for (const node of run.nodes) {
    const l = (layers[node.layer] ??= { n: 0, tone: "done" });
    l.n++;
    const rank: Tone[] = ["done", "waiting", "running", "failed"];
    const t: Tone =
      node.state === "done" || isRepaired(node, run.nodes)
        ? "done"
        : node.state === "running"
          ? "running"
          : node.state === "failed" || node.state === "blocked"
            ? "failed"
            : "waiting";
    if (rank.indexOf(t) > rank.indexOf(l.tone)) l.tone = t;
  }
  const count = (f: (s: string) => boolean) => run.nodes.filter((n) => f(n.state)).length;
  const counts = [
    { k: "done", n: count((s) => s === "done") },
    { k: "running", n: count((s) => s === "running") },
    { k: "waiting", n: count((s) => s === "waiting" || s === "parked") },
    { k: "failed", n: run.nodes.filter((n) => (n.state === "failed" || n.state === "blocked") && !isRepaired(n, run.nodes)).length },
    { k: "repaired", n: run.nodes.filter((n) => isRepaired(n, run.nodes)).length },
  ];
  const started = run.nodes.some((n) => n.started !== undefined);
  const name = runName(run.id);
  const prefill = (text: string) => getStore().actions.prefill(text);
  return (
    <section className={`rp rp-${mode}`} data-testid="run-plan" aria-label="Plan">
      <div className="rp-top">
        <span className="rp-k">Plan</span>
        <b className="rp-title">{layers.length} {layers.length === 1 ? "layer" : "layers"} · {run.nodes.length} parts</b>
        <span className="rp-time" data-testid="run-plan-time">
          {started ? (
            <>
              {run.state === "running" && <i className="rn-live" aria-hidden />}
              {span((run.ended ?? nowS) - run.started)}
            </>
          ) : run.startsAt !== undefined ? (
            `Starts in ${clock(Math.max(0, run.startsAt - nowS))}`
          ) : (
            "Not started"
          )}
        </span>
      </div>
      {run.goal && <p className="rp-goal">{run.goal}</p>}
      <div className="rp-row">
        <ol className="rp-layers" aria-label="Layers">
          {layers.map((l, i) => (
            <li key={i} className={`rp-chip t-${l.tone}`} data-testid="run-plan-layer">
              <i aria-hidden />L{i + 1}
              {mode === "full" && names?.[i] ? ` ${names[i]}` : ""} · {l.n}
              {mode === "full" ? (l.n === 1 ? " part" : " parts") : ""}
            </li>
          ))}
        </ol>
        <span className="rp-counts" data-testid="run-plan-counts">
          {counts
            .filter((c) => c.n > 0 || c.k === "done")
            .map((c) => (
              <span key={c.k} className={`rp-c t-${c.k}`} data-k={c.k}>
                <i aria-hidden />
                {c.n} {c.k}
              </span>
            ))}
        </span>
      </div>
      {!started && (
        <div className="rp-act">
          <button type="button" className="rn-askb rp-go" onClick={() => prefill(`Start run \`${name}\` now`)} data-testid="run-plan-start">
            Start now
          </button>
          <button type="button" className="rn-askb" onClick={() => prefill(`Edit the plan of run \`${name}\`: `)} data-testid="run-plan-edit">
            Edit
          </button>
          <span className="rp-note">Puts a request in the message box. Nothing is sent.</span>
        </div>
      )}
    </section>
  );
}
