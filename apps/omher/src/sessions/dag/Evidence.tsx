import { useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { t } from "../../i18n";
import type { AgentRun, RunNode } from "../../lib/runs";
import { STATE_WORD } from "../../runs/format";
import { evidenceSurface, readSurface } from "./catalog";
import "./evidence.css";

// No actions, URL handlers, images, raw HTML or custom attributes from evidence. Only typographic Markdown.
function InertText({ value }: { value: string }) {
  return <ReactMarkdown skipHtml unwrapDisallowed allowedElements={["p", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "br", "h1", "h2", "h3", "h4", "h5", "h6", "img"]}
    components={{ img: ({ alt }) => <span>{alt}</span>, h1: "strong", h2: "strong", h3: "strong", h4: "strong", h5: "strong", h6: "strong" }}>{value}</ReactMarkdown>;
}

export function EvidenceSurface({ message, markdown }: { message: unknown; markdown: string }) {
  const records = useMemo(() => readSurface(message), [message]);
  if (!records) return <div className="dag-card" data-evidence="markdown"><InertText value={markdown} /></div>;
  function render(id: string): ReactNode {
    const r = records!.get(id)!;
    switch (r.component) {
      case "Card": return <div key={id} className="dag-card">{render(r.child)}</div>;
      case "Column": return <div key={id} className="dag-column">{r.children.map(render)}</div>;
      case "Divider": return <hr key={id} />;
      case "Text": return <div key={id} className={`dag-${r.variant}`}><InertText value={r.text} /></div>;
    }
  }
  return <div data-evidence="basic-v1">{render("root")}</div>;
}

function Snapshot({ title, status, paragraphs }: { title: string; status: string; paragraphs: string[] }) {
  const message = useMemo(() => evidenceSurface(title, status, paragraphs, `dag-${crypto.randomUUID()}`), [title, status, paragraphs]);
  return <EvidenceSurface message={message} markdown={[title, status, ...paragraphs].join("\n\n")} />;
}

export function RunEvidence({ run, selected, evidence, onNode }: {
  run: AgentRun; selected: string | null; evidence?: { node: RunNode; text: string }; onNode: (id: string | null) => void;
}) {
  const lines = [run.goal, ...run.nodes.map((n) => [n.label, t(STATE_WORD[n.state]),
    n.deps.length ? t("graph.after", { name: n.deps.join(", ") }) : "", n.repairOf && `${t("graph.repair")}: ${n.repairOf}`].filter(Boolean).join(" · "))].filter((v): v is string => !!v);
  const n = evidence?.node.id === selected && run.nodes.some((item) => item.id === selected) ? evidence.node : undefined;
  return <section className="dag-evidence" aria-label={t("plans.dag")}>
    <Snapshot title={run.title} status={t(`graph.run.${run.state}`)} paragraphs={lines} />
    <nav aria-label={t("graph.details")} className="dag-picks">{run.nodes.map((item) =>
      <button type="button" key={item.id} aria-pressed={item.id === selected} data-testid="run-node" data-node={item.id}
        onClick={() => onNode(item.id === selected ? null : item.id)}>{item.label}</button>)}</nav>
    {selected && <section data-testid="run-drawer" data-node={selected} aria-label={t("graph.details")}>
      <h3>{t("graph.details")}</h3>
      {!n ? <p role="status">{t("pn.loading")}</p> : <div data-testid="run-handoff">
        <Snapshot title={n.label} status={t(STATE_WORD[n.state])} paragraphs={[
          ...n.attempts.map((a) => [t("graph.attempt", { n: a.n }), a.outcome, a.lane, a.reason].filter(Boolean).join(" · ")),
          n.summary, evidence?.text || t("rn.noHandoff"),
        ].filter((v): v is string => !!v)} /></div>}
    </section>}
  </section>;
}
