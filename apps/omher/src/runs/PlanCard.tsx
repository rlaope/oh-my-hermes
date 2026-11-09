// The run's plan, at the top of the full view and first in the panel: title and goal, the layers as chips
// ("L1 · 3 parts"), how many parts are done / running / waiting / failed, and the time so far. In the panel it is
// compact so the graph keeps the height: one line ("3 layers · 7 parts · 3 done · 2 running"), the goal as the
// card's tooltip, and the layer chips on a second line only when all of them fit on it (and there is more than one). A run nobody has
// started yet says so ("Starts in 0:10" when the run carries a start time) and offers Start now / Edit, which,
// like "Ask in chat", only put a request in the message box: nothing here starts or edits a run.
import { useLayoutEffect, useRef, useState } from "react";
import type { AgentRun } from "../lib/runs";
import { isRepaired, span } from "../lib/runs";
import { getStore } from "../state/store";
import { runName } from "./format";
import { layerName } from "./layout";

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
  const chipsRef = useRef<HTMLOListElement>(null);
  const chipsFit = useFits(chipsRef, mode === "panel", layers.length);
  const title = `${layers.length} ${layers.length === 1 ? "layer" : "layers"} · ${run.nodes.length} ${run.nodes.length === 1 ? "part" : "parts"}`;
  const countSpans = counts
    .filter((c) => c.n > 0 || c.k === "done")
    .map((c) => (
      <span key={c.k} className={`rp-c t-${c.k}`} data-k={c.k}>
        <i aria-hidden />
        {c.n} {c.k}
      </span>
    ));
  const chips = (
    <ol className="rp-layers" aria-label="Layers" ref={chipsRef}>
      {layers.map((l, i) => (
        <li key={i} className={`rp-chip t-${l.tone}`} data-testid="run-plan-layer" title={mode === "panel" ? `${l.n} ${l.n === 1 ? "part" : "parts"}` : undefined}>
          <i aria-hidden />
          {mode === "full" ? `L${i + 1}${names?.[i] ? ` ${names[i]}` : ""} · ${l.n} ${l.n === 1 ? "part" : "parts"}` : names?.[i] ? layerName(i, names[i]) : `L${i + 1} · ${l.n}`}
        </li>
      ))}
    </ol>
  );
  const time = (
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
  );
  const actions = !started && (
    <div className="rp-act">
      <button type="button" className="rn-askb rp-go" onClick={() => prefill(`Start run \`${name}\` now`)} data-testid="run-plan-start">
        Start now
      </button>
      <button type="button" className="rn-askb" onClick={() => prefill(`Edit the plan of run \`${name}\`: `)} data-testid="run-plan-edit">
        Edit
      </button>
      <span className="rp-note">Puts a request in the message box. Nothing is sent.</span>
    </div>
  );
  if (mode === "panel")
    return (
      <section className="rp rp-panel" data-testid="run-plan" aria-label="Plan" title={run.goal || undefined}>
        <div className="rp-top">
          <span className="rp-line">
            <b className="rp-title">{title}</b>
            <span className="rp-counts" data-testid="run-plan-counts">
              {countSpans}
            </span>
          </span>
          {time}
        </div>
        <div className={`rp-row${chipsFit && layers.length > 1 ? "" : " rp-hide"}`} data-testid="run-plan-chips" data-fits={chipsFit ? "true" : "false"}>
          {chips}
        </div>
        {actions}
      </section>
    );
  return (
    <section className={`rp rp-${mode}`} data-testid="run-plan" aria-label="Plan">
      <div className="rp-top">
        <span className="rp-k">Plan</span>
        <b className="rp-title">{title}</b>
        {time}
      </div>
      {run.goal && <p className="rp-goal">{run.goal}</p>}
      <div className="rp-row">
        {chips}
        <span className="rp-counts" data-testid="run-plan-counts">
          {countSpans}
        </span>
      </div>
      {actions}
    </section>
  );
}

/** Whether a row's content fits its width on one line (panel only; the full view always shows it). */
function useFits(ref: React.RefObject<HTMLElement | null>, on: boolean, n: number): boolean {
  const [fits, setFits] = useState(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!on || !el) return;
    const read = () => {
      const fits = el.scrollWidth <= el.clientWidth + 1;
      // hide the row now, not on the re-render: the Runs panel sizes its graph box from where the box starts, in
      // the same layout pass (useRoom), and a late hide left that box 26px short until a later resize
      el.parentElement?.classList.toggle("rp-hide", !(fits && n > 1));
      setFits(fits);
    };
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, on, n]);
  return fits;
}
