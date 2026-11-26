// Header right: the ONE control. `● <Model> | <Reasoning> ⌄` opens a popover with the providers' models
// and a reasoning control. Changes go to `chat.set_model` for the bot's main chat; when the bridge refuses
// (e.g. `unsupported`) the old value stays and a one-line note says to change it in Hermes.
// The list has a search field (focused on open; Up/Down/Enter pick, Esc closes) and one chip per vendor.
// A bot Hermes says cannot answer (ready.ts, the chat's connect block) has a gray dot, not the green one.
// Rows and the button name a model as people say it ("Opus 5.5", "GPT-6.1 Terra"); the id is the title. The chat may
// carry a display name ("Opus 5.5") where the catalog has the id, so the current row is found by name as well.
// With no model at all (no AI account yet, or a Hermes that lists none) the popover is only that line and the way to
// Bot settings: no search field, chips or reasoning to work on an empty list.
import { useEffect, useMemo, useRef, useState } from "react";
import "./model.css";
import type { SlotProps } from "../../features";
import { getStore, useStore } from "../../state/store";
import { ChevronDown, ModelIcon, Popover, SearchIcon } from "../../ui";
import { Seg } from "./Seg";
import { CheckIcon } from "./CheckIcon";
import { levelOptions, reasoningLabel, sentLevel } from "./levels";
import { filterRows, isCurrent, modelRows, vendorsPresent, type ModelRow } from "./modelSearch";
import { modelName } from "../../runs/format";
import { t, tx } from "../../i18n";
import { composing } from "../../lib/ime";
import { useBotReady } from "../connect/ready";

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
  // what the route sends for that level, from the same source as the level itself
  const wire = chat?.reasoning ? chat.reasoningWire : opts?.current.reasoning_wire;
  // the control selects the level the route sends: a saved `ultra` on a route that sends max selects max, and a
  // saved `none` on a route that cannot send it selects nothing
  const sent = sentLevel(reasoning, wire, opts?.reasoning_levels);
  const offline = bot.status === "offline";
  const noAccount = useBotReady(bot.name).status === "not";
  const [query, setQuery] = useState("");
  const [vendor, setVendor] = useState("all");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const chipsRef = useRef<HTMLDivElement>(null);
  // which edge of the chip row has more chips past it ("start", "end", "both"); the row fades there (model.css)
  const [more, setMore] = useState("");
  const measureChips = () => {
    const el = chipsRef.current;
    if (!el) return;
    const start = el.scrollLeft > 1;
    const end = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    setMore(start && end ? "both" : start ? "start" : end ? "end" : "");
  };
  // the same for the model list, top and bottom ("above", "below", "both")
  const [listMore, setListMore] = useState("");
  const measureList = () => {
    const el = listRef.current;
    if (!el) return;
    const above = el.scrollTop > 1;
    const below = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setListMore(above && below ? "both" : above ? "above" : below ? "below" : "");
  };
  const pillRef = useRef<HTMLButtonElement>(null);
  const rows = useMemo(() => modelRows(opts?.providers ?? []), [opts]);
  const vendors = useMemo(() => vendorsPresent(rows), [rows]);
  const shown = useMemo(() => filterRows(rows, query, vendor), [rows, query, vendor]);
  const isOn = (r: ModelRow) => isCurrent(r, model, provider);
  // loaded, and nothing to pick from: the popover says so and offers Bot settings, nothing else
  const empty = !!opts && !rows.length;

  useEffect(() => {
    setOpen(false);
    setNote(null);
  }, [bot.name]);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setVendor("all");
  }, [open]);
  // The keyboard highlight starts on the current model when it is in view, else on the first row; it follows the
  // current model when that arrives after the list (the chat's own model and provider can land after the catalog).
  useEffect(() => {
    const i = shown.findIndex(isOn);
    setActive(i < 0 ? 0 : i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, model, provider]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
    measureList();
  }, [active, open, shown]);
  // the chosen chip in view, then the fades for where the row now stands
  useEffect(() => {
    chipsRef.current?.querySelector<HTMLElement>(".mp-chip.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
    measureChips();
  }, [vendor, open, vendors.length]);
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
      // Enter that commits an IME composition (pinyin, kana, hangul) is not a pick
      if (composing(e)) return;
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
        title={t("mp.title")}
        data-testid="model-pill"
      >
        <span
          className="mp-mk"
          title={offline ? t("bot.offline") : noAccount ? t("cn.needs", { bot: bot.display_name }) : t("bot.online")}
        >
          <ModelIcon model={model} provider={provider} size={14} />
          <span className={`mp-d${offline || noAccount ? "" : " live"}`} aria-hidden="true" data-testid="model-dot" />
        </span>
        <span className="mp-l" title={model || undefined} data-testid="model-label">
          {model ? modelName(model) : t("mp.pick")}
        </span>
        {sent && (
          <>
            <span className="sep" />
            <span className="eff" data-testid="reasoning-label">
              {reasoningLabel(sent)}
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
        label={t("mp.title")}
        width={320}
        className="mp-pop"
      >
        <div data-testid="model-pop" aria-busy={busy} data-empty={empty || undefined}>
          {!empty && (
            <label className="mp-search">
              <SearchIcon />
              <input
                type="search"
                placeholder={t("mp.search")}
                aria-label={t("mp.search")}
                autoFocus
                autoComplete="off"
                spellCheck={false}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onSearchKey}
                data-testid="model-search"
              />
            </label>
          )}
          {!empty && vendors.length > 1 && (
            <div
              ref={chipsRef}
              className="mp-chips"
              role="group"
              aria-label={t("mp.makers")}
              data-more={more || undefined}
              onScroll={measureChips}
              // a mouse wheel turns the row: only a trackpad scrolls sideways on its own
              onWheel={(e) => {
                const el = e.currentTarget;
                if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth) el.scrollLeft += e.deltaY;
              }}
              data-testid="model-chips"
            >
              {[{ id: "all", label: t("mp.all") }, ...vendors].map((v) => {
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
                    {v.id === "other" ? t("mp.other") : v.label}
                  </button>
                );
              })}
            </div>
          )}
          <div className="mp-list" ref={listRef} data-more={listMore || undefined} onScroll={measureList}>
            {!opts ? (
              <div className="mp-empty">{offline ? t("mp.offline", { bot: bot.display_name }) : t("mp.loading")}</div>
            ) : !shown.length ? (
              <div className="mp-empty" data-testid="model-empty">
                {!empty ? t("mp.none") : t(noAccount ? "mp.noAccount" : "mp.noModels", { bot: bot.display_name })}
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
                        <span className="mp-n" title={r.label === r.model ? undefined : r.model}>
                          {r.label}
                        </span>
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
          {!empty && (
            <>
              <div className="mp-h mp-h2">{t("mp.reasoning")}</div>
              <Seg
                label={t("mp.reasoning")}
                value={sent}
                options={levelOptions(opts?.reasoning_levels)}
                onChange={(r) => void apply({ reasoning: r })}
                repick={sent !== reasoning}
                disabled={busy || offline}
                testId="reasoning-seg"
              />
            </>
          )}
          {note !== null && (
            <div className="mp-note" role="status" title={note || undefined} data-testid="model-note">
              {t("mp.inHermes")}
            </div>
          )}
          <div className="mp-f">
            {tx(empty ? "mp.setUp" : "mp.appliesChat", {
              link: (
                <button
                  type="button"
                  className="mp-link"
                  onClick={() => {
                    setOpen(false);
                    s.openSettings(`bot:${bot.name}`);
                  }}
                >
                  {t("mp.botSettings")}
                </button>
              ),
            })}
          </div>
        </div>
      </Popover>
    </div>
  );
}
