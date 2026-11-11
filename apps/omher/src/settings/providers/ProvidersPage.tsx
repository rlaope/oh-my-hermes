// Settings › Providers: one compact row per provider (mark, name, slug, "in use", model count). A row opens
// inline to its models grouped by vendor, one vendor per line; only the provider in use starts open, with
// its current model first. Read-only: providers and keys are set up in Hermes.
import { useEffect, useMemo, useState } from "react";
import type { ModelOptions, ModelProvider } from "../../lib/protocol";
import { useStore } from "../../state/store";
import { ChevronRight } from "../../ui";
import { ProviderMark } from "./ProviderMark";
import { countLabel, filterGroups, groupModels } from "./group";

/** More models than this get a filter box. */
const FILTER_AT = 20;
const SETUP_CMD = "hermes auth add <provider>";

export function ProvidersPage() {
  const s = useStore();
  const name = s.selectedBot ?? s.bots[0]?.name ?? null;
  const opts = name ? s.models[name] : undefined;
  const bot = s.bots.find((b) => b.name === name);
  // explicit open/closed per slug; unset = open only for the provider in use
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    if (name && !opts && bot?.status !== "offline") void s.loadModels(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);
  return (
    <div className="st-page">
      <div className="st-gh st-gh0">Providers</div>
      <SetupLine />
      <div className="st-grp pv-list" data-testid="providers-list">
        {!opts ? (
          <div className="pv-empty">{bot?.status === "offline" ? "Not connected" : "Loading…"}</div>
        ) : (
          opts.providers.map((p) => (
            <ProviderItem
              key={p.slug}
              p={p}
              opts={opts}
              open={open[p.slug] ?? p.slug === opts.current.provider}
              onToggle={(v) => setOpen((o) => ({ ...o, [p.slug]: v }))}
            />
          ))
        )}
      </div>
    </div>
  );
}

function SetupLine() {
  const [copied, setCopied] = useState(false);
  return (
    <p className="st-note pv-setup" data-testid="providers-setup">
      Set up in Hermes · <code>{SETUP_CMD}</code>
      <button
        type="button"
        className="pv-copy"
        aria-label="Copy command"
        data-testid="providers-copy"
        onClick={() => void navigator.clipboard?.writeText(SETUP_CMD).then(() => setCopied(true), () => {})}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </p>
  );
}

function ProviderItem({
  p,
  opts,
  open,
  onToggle,
}: {
  p: ModelProvider;
  opts: ModelOptions;
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const inUse = p.slug === opts.current.provider;
  const bodyId = `pv-models-${p.slug}`;
  return (
    <div className={`pv-item${open ? " open" : ""}`}>
      <button
        type="button"
        className="pv-row"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => onToggle(!open)}
        data-testid={`provider-row-${p.slug}`}
      >
        <span className="pv-mark">
          <ProviderMark names={[p.slug, p.name]} />
        </span>
        <span className="pv-name" title={p.name}>
          {p.name}
        </span>
        <code className="pv-slug" title={p.slug}>
          {p.slug}
        </code>
        {inUse && <small className="st-tag pv-use">in use</small>}
        <span className="pv-count">{countLabel(p.models.length)}</span>
        <span className="pv-chev" aria-hidden="true">
          <ChevronRight size={9} />
        </span>
      </button>
      {open && <ProviderModels id={bodyId} p={p} current={inUse ? opts.current.model : undefined} />}
    </div>
  );
}

function ProviderModels({ id, p, current }: { id: string; p: ModelProvider; current?: string }) {
  const [q, setQ] = useState("");
  const groups = useMemo(() => groupModels(p.models, current), [p.models, current]);
  const shown = filterGroups(groups, q);
  return (
    <div className="pv-body" id={id} data-testid={`provider-models-${p.slug}`}>
      {p.models.length > FILTER_AT && (
        <input
          type="search"
          className="pv-q"
          placeholder={`Filter ${p.models.length} models`}
          aria-label={`Filter ${p.name} models`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid={`provider-filter-${p.slug}`}
        />
      )}
      {p.models.length === 0 && <div className="pv-none">No models</div>}
      {q.trim() && shown.length === 0 && <div className="pv-none">No model matches “{q.trim()}”</div>}
      {shown.map((g) => (
        <div className="pv-g" key={g.vendor || "-"} data-testid="provider-group">
          {g.vendor ? (
            <span className="pv-v" title={g.vendor}>
              <span className="pv-vi">
                <ProviderMark names={[g.vendor]} size={11} />
              </span>
              <span>{g.vendor}</span>
            </span>
          ) : null}
          <span className="pv-ms">
            {g.models.map((e) => (
              <span
                key={e.id}
                className={`pv-m${e.id === current ? " on" : ""}`}
                title={e.id === current ? `${e.id} · in use` : e.id}
                data-testid="provider-model"
                data-id={e.id}
              >
                {e.id === current && (
                  <svg className="pv-on" width="9" height="9" viewBox="0 0 12 12" aria-label="in use" role="img">
                    <path d="M2.5 6.5l2.3 2.3L9.5 3.8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
                <span className="pv-mn">{e.name}</span>
                {e.tag && <small className="pv-sfx">{e.tag}</small>}
              </span>
            ))}
          </span>
        </div>
      ))}
    </div>
  );
}
