// Settings › Providers: one compact row per provider (mark, name, slug, "in use", model count). A row opens
// inline to its models grouped by vendor, one vendor per line; only the provider in use starts open, with
// its current model first. A long list scrolls inside a ~320px box under its filter. Keys are Hermes': "Add key" opens the system terminal running
// `hermes auth add <provider> --type api-key` (BOUNDARY rule 23); omher never sees the key.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ModelOptions, ModelProvider } from "../../lib/protocol";
import { useStore } from "../../state/store";
import { ChevronRight, Popover } from "../../ui";
import { ProviderMark } from "./ProviderMark";
import { PROVIDER_ID, authCommand, authHost, keyProviders } from "./authHost";
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
  const [key, setKey] = useState<{ provider: string; state: "opened" | "manual" | "error"; error?: string } | null>(null);
  useEffect(() => {
    if (name && !opts && bot?.status !== "offline") void s.loadModels(name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name]);
  // After a terminal was opened, read the providers again whenever omher comes back to the front.
  const opened = key?.state === "opened";
  useEffect(() => {
    if (!opened || !name) return;
    const again = () => {
      if (document.visibilityState === "visible") void s.loadModels(name);
    };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => {
      window.removeEventListener("focus", again);
      document.removeEventListener("visibilitychange", again);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, name]);
  const addKey = useCallback((provider: string) => {
    const host = authHost();
    if (!host) {
      setKey({ provider, state: "manual" });
      return;
    }
    host.open(provider).then(
      () => setKey({ provider, state: "opened" }),
      (e: unknown) => setKey({ provider, state: "error", error: e instanceof Error ? e.message : String(e) }),
    );
  }, []);
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
              onAddKey={addKey}
            />
          ))
        )}
      </div>
      <AddKey slugs={opts?.providers.map((p) => p.slug) ?? []} onPick={addKey} />
      {key && (
        <p className="st-note pv-keynote" data-testid="providers-key-note" role="status">
          {key.state === "opened" ? (
            <>
              Terminal opened with <code>{authCommand(key.provider)}</code>. Enter the key there; this list refreshes when you come back.
            </>
          ) : key.state === "manual" ? (
            <>
              Run <code>{authCommand(key.provider)}</code> in a terminal.
            </>
          ) : (
            <>
              Couldn’t open a terminal ({key.error}). Run <code>{authCommand(key.provider)}</code> yourself.
            </>
          )}
        </p>
      )}
    </div>
  );
}

/** The quiet "+ Add key" row under the list: a menu of Hermes provider ids. */
function AddKey({ slugs, onPick }: { slugs: string[]; onPick: (provider: string) => void }) {
  const [open, setOpen] = useState(false);
  const ids = keyProviders(slugs);
  return (
    <div className="pv-add">
      <button
        type="button"
        className="pv-add-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="providers-add-key"
      >
        <span aria-hidden="true">+</span> Add key
      </button>
      <Popover open={open} onClose={() => setOpen(false)} align="left" width={208} label="Add a key for" className="pv-menu">
        <div className="pv-menu-h">Add an API key for</div>
        <div role="menu" data-testid="providers-key-menu">
          {ids.map((id) => (
            <button
              key={id}
              type="button"
              role="menuitem"
              className="pv-menu-i"
              onClick={() => {
                setOpen(false);
                onPick(id);
              }}
              data-testid={`providers-key-${id}`}
            >
              <span className="pv-mark">
                <ProviderMark names={[id]} size={12} />
              </span>
              <code>{id}</code>
            </button>
          ))}
        </div>
      </Popover>
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
  onAddKey,
}: {
  p: ModelProvider;
  opts: ModelOptions;
  open: boolean;
  onToggle: (open: boolean) => void;
  onAddKey: (provider: string) => void;
}) {
  const inUse = p.slug === opts.current.provider;
  const bodyId = `pv-models-${p.slug}`;
  return (
    <div className={`pv-item${open ? " open" : ""}`}>
      <div className="pv-head">
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
        {PROVIDER_ID.test(p.slug) && (
          <button
            type="button"
            className="pv-key"
            aria-label={`Add a ${p.name} API key`}
            title={authCommand(p.slug)}
            onClick={() => onAddKey(p.slug)}
            data-testid={`provider-key-${p.slug}`}
          >
            Add key
          </button>
        )}
      </div>
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
      <div className="pv-scroll" data-testid={`provider-scroll-${p.slug}`}>
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
    </div>
  );
}
