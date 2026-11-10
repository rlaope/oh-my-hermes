// Header right: the ONE control. `● <Model> | <Reasoning> ⌄` opens a popover with the providers' models
// and a reasoning control. Changes go to `chat.set_model` for the bot's main chat; when the bridge refuses
// (e.g. `unsupported`) the old value stays and a one-line note says to change it in Hermes.
// The list has a search field (focused on open; Up/Down/Enter pick, Esc closes) and one chip per vendor.
import { useEffect, useMemo, useRef, useState } from "react";
import "./model.css";
import type { SlotProps } from "../../features";
import { getStore, useStore } from "../../state/store";
import { ChevronDown, ModelIcon, Popover, SearchIcon } from "../../ui";
import { Seg } from "./Seg";
import { CheckIcon } from "./CheckIcon";
import { levelOptions, reasoningLabel } from "./levels";
import { filterRows, modelRows, vendorsPresent, type ModelRow } from "./modelSearch";

export const slot = "modelPicker";

type Change = { model?: string; provider?: string; reasoning?: string };

export default function ModelPicker({ bot, chat }: SlotProps["modelPicker"]) {
  const s = useStore();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const opts = s.models[bot.name];
  const model = chat?.model || opts?.current.model || bot.model;
  const provider = chat?.provider || opts?.current.provider || bot.provider;
  const reasoning = chat?.reasoning || opts?.current.reasoning || "";
  const offline = bot.status === "offline";
  const [query, setQuery] = useState("");
  const [vendor, setVendor] = useState("all");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const pillRef = useRef<HTMLButtonElement>(null);
  const rows = useMemo(() => modelRows(opts?.providers ?? []), [opts]);
  const vendors = useMemo(() => vendorsPresent(rows), [rows]);
  const shown = useMemo(() => filterRows(rows, query, vendor), [rows, query, vendor]);
  const isOn = (r: ModelRow) => r.model === model && r.provider.slug === provider;

  useEffect(() => {
    setOpen(false);
    setNote(null);
  }, [bot.name]);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setVendor("all");
  }, [open]);
  // The keyboard highlight starts on the current model when it is in view, else on the first row.
  useEffect(() => {
    const i = shown.findIndex(isOn);
    setActive(i < 0 ? 0 : i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active, open]);
  useEffect(() => {
    if (open && !opts && !offline) void s.loadModels(bot.name);
    // load once per opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, bot.name]);

  const apply = async (change: Change) => {
    const store = getStore();
    setBusy(true);
    setNote(null);
    // The store reports a failed request only through lastError: clear it, then look after the call.
    store.dispatch({ type: "error", message: null });
    await s.setModel(change);
    const after = store.getState();
    const c = after.chats[bot.name];
    const got: Change = { model: c?.model, provider: c?.provider, reasoning: c?.reasoning };
    const applied = (Object.keys(change) as (keyof Change)[]).every((k) => got[k] === change[k]);
    if (!applied && after.lastError !== null) setNote(after.lastError);
    setBusy(false);
  };

  const pick = (r: ModelRow) => {
    if (!busy && !isOn(r)) void apply({ model: r.model, provider: r.provider.slug });
  };
  const onSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!shown.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + shown.length) % shown.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const r = shown[active];
      if (r) pick(r);
    }
  };
  // Rows grouped back under their provider, keeping each row's index in `shown` for the highlight.
  const groups: { slug: string; name: string; rows: { r: ModelRow; i: number }[] }[] = [];
  shown.forEach((r, i) => {
    const last = groups[groups.length - 1];
    if (last && last.slug === r.provider.slug) last.rows.push({ r, i });
    else groups.push({ slug: r.provider.slug, name: r.provider.name, rows: [{ r, i }] });
  });

  return (
    <div className="mp-wrap">
      <button
        ref={pillRef}
        type="button"
        className={`mp${open ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Model and reasoning"
        data-testid="model-pill"
      >
        <span className="mp-mk" title={offline ? "Not connected" : "Connected"}>
          <ModelIcon model={model} provider={provider} size={14} />
          <span className={`mp-d${offline ? "" : " live"}`} aria-hidden="true" />
        </span>
        <span className="mp-l" title={model || undefined} data-testid="model-label">
          {model || "Pick a model"}
        </span>
        {reasoning && (
          <>
            <span className="sep" />
            <span className="eff" data-testid="reasoning-label">
              {reasoningLabel(reasoning)}
            </span>
          </>
        )}
        <ChevronDown />
      </button>
      <Popover
        open={open}
        onClose={(why) => {
          setOpen(false);
          // Esc hands focus back to the model button instead of dropping it on the page.
          if (why === "escape") pillRef.current?.focus();
        }}
        label="Model and reasoning"
        width={320}
        className="mp-pop"
      >
        <div data-testid="model-pop" aria-busy={busy}>
          <label className="mp-search">
            <SearchIcon />
            <input
              type="search"
              placeholder="Search models"
              aria-label="Search models"
              autoFocus
              autoComplete="off"
              spellCheck={false}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKey}
              data-testid="model-search"
            />
          </label>
          {vendors.length > 1 && (
            <div className="mp-chips" role="group" aria-label="Model makers" data-testid="model-chips">
              {[{ id: "all", label: "All" }, ...vendors].map((v) => {
                const on = v.id === vendor;
                return (
                  <button
                    key={v.id}
                    type="button"
                    className={`mp-chip${on ? " on" : ""}`}
                    aria-pressed={on}
                    onClick={() => setVendor(v.id)}
                    data-testid={`model-chip-${v.id}`}
                  >
                    {v.id !== "all" && <ModelIcon model={v.id === "other" ? undefined : v.label} size={12} />}
                    {v.label}
                  </button>
                );
              })}
            </div>
          )}
          <div className="mp-list" ref={listRef}>
            {!opts ? (
              <div className="mp-empty">{offline ? `${bot.display_name} is offline` : "Loading models…"}</div>
            ) : !shown.length ? (
              <div className="mp-empty" data-testid="model-empty">
                No models match
              </div>
            ) : (
              groups.map((g) => (
                <div key={g.slug} role="group" aria-label={g.name}>
                  <div className="mp-g">{g.name}</div>
                  {g.rows.map(({ r, i }) => {
                    const on = isOn(r);
                    return (
                      <button
                        key={r.model}
                        type="button"
                        className={`mp-opt${on ? " on" : ""}${i === active ? " kb" : ""}`}
                        aria-pressed={on}
                        data-active={i === active}
                        disabled={busy}
                        onClick={() => pick(r)}
                        onMouseMove={() => i !== active && setActive(i)}
                        data-testid="model-opt"
                      >
                        <ModelIcon model={r.model} provider={`${r.provider.slug} ${r.provider.name}`} size={13} />
                        <span className="mp-n">{r.model}</span>
                        <span className="mp-ck">
                          <CheckIcon />
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
          <div className="mp-h mp-h2">Reasoning</div>
          <Seg
            label="Reasoning"
            value={reasoning}
            options={levelOptions(opts?.reasoning_levels)}
            onChange={(r) => void apply({ reasoning: r })}
            disabled={busy || offline}
            testId="reasoning-seg"
          />
          {note !== null && (
            <div className="mp-note" role="status" title={note || undefined} data-testid="model-note">
              Change it in Hermes for now
            </div>
          )}
          <div className="mp-f">
            Applies to this chat ·{" "}
            <button
              type="button"
              className="mp-link"
              onClick={() => {
                setOpen(false);
                s.openSettings(`bot:${bot.name}`);
              }}
            >
              Bot settings
            </button>
          </div>
        </div>
      </Popover>
    </div>
  );
}
