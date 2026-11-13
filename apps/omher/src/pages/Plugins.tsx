// Plugins: one bot's plugins (its own `plugins.manage list`), the curated catalog (the profile's catalog cache file,
// read-only) and Hermes' built-in ones. Install is catalog-only and always inspect → confirm → install with the
// inspected pin; toggle, update and remove are `plugins.manage` too (BOUNDARY rule 25). No Git URL install.
import { useCallback, useEffect, useState } from "react";
import type { Bot, CatalogEntry, CatalogResult, InspectResult, PluginRow } from "../lib/protocol";
import { useStore } from "../state/store";
import { t, type Key } from "../i18n";
import { Avatar, Popover, SearchIcon } from "../ui";
import { AskBox, BotChip, errorLine, PageHead, Toggle } from "./kit";
import { CategoryIcon, DotsIcon } from "./icons";
import { PluginLoad } from "./PluginLoad";

type Tab = "installed" | "browse" | "builtin";
const CATEGORIES = ["automation", "tools", "memory", "voice", "web", "desktop", "models", "platform", "general"] as const;
const TIERS = new Set(["official", "verified", "community", "bundled", "user"]);

const tierWord = (tier: string) => (TIERS.has(tier) ? t(`plug.tier.${tier}` as Key) : tier);
const catWord = (c: string) => ((CATEGORIES as readonly string[]).includes(c) ? t(`plug.cat.${c}` as Key) : c);
const toolsWord = (n: number) => (n === 1 ? t("plug.tool1") : t("plug.tools", { n }));
const hooksWord = (n: number) => (n === 1 ? t("plug.hook1") : t("plug.hooks", { n }));

/** "4 tools · 1 hook" for a card's chips; a messaging platform says so. */
export function addsOf(p: { tools: number; hooks: number; category: string }): string[] {
  const out: string[] = [];
  if (p.tools) out.push(toolsWord(p.tools));
  if (p.hooks) out.push(hooksWord(p.hooks));
  if (p.category === "platform") out.push(t("plug.channel"));
  return out;
}

export function PluginsPage() {
  const s = useStore();
  const bots = s.bots;
  const scope = bots.find((b) => b.name === s.ui.pluginsBot) ?? bots.find((b) => b.name === s.selectedBot) ?? bots[0];
  const [tab, setTab] = useState<Tab>("installed");
  const [askBot, setAskBot] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [rows, setRows] = useState<PluginRow[] | null>(null);
  const [catalog, setCatalog] = useState<CatalogResult | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // after an enable or update: when it takes effect, from Hermes' own answer (PluginLoad), until the next action
  const [loaded, setLoaded] = useState<{ plugin: string; load: "live" | "reload" | "restart"; restartBot?: string; n: number } | null>(null);
  const [sheet, setSheet] = useState<CatalogEntry | null>(null);
  const askTo = bots.find((b) => b.name === askBot) ?? scope;
  const scopeName = scope?.name;

  const reload = useCallback(async () => {
    if (!scopeName) return;
    try {
      setRows(await s.pluginsList(scopeName));
      setErr(null);
    } catch (e) {
      setRows([]);
      setErr(errorLine(e, bots.find((b) => b.name === scopeName)?.display_name ?? scopeName));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeName]);

  useEffect(() => {
    setRows(null);
    setNote(null);
    void reload();
  }, [reload]);

  // the bot installed something from its chat: re-read
  useEffect(
    () =>
      s.onBridgeEvent((ev) => {
        if ((ev.event === "plugins.update" || ev.event === "plugin.added") && ev.bot === scopeName) void reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scopeName, reload],
  );

  useEffect(() => {
    if (!scopeName) return;
    let live = true;
    const h = setTimeout(
      () =>
        void s
          .pluginsCatalog(scopeName, query.trim(), category)
          .then((c) => live && setCatalog(c))
          .catch(() => live && setCatalog({ total: 0, matched: 0, entries: [], categories: {}, generated_at: null })),
      query ? 180 : 0,
    );
    return () => {
      live = false;
      clearTimeout(h);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeName, query, category]);

  const own = (rows ?? []).filter((r) => r.source !== "bundled");
  const builtin = (rows ?? []).filter((r) => r.source === "bundled");
  const installedNames = new Set((rows ?? []).flatMap((r) => [r.name, r.catalog_name ?? ""]));

  const send = () => {
    if (!askTo || !text.trim()) return;
    const msg = text.trim();
    setText("");
    void s.sendTo(askTo.name, msg);
  };

  const run = async (fn: () => Promise<string | null>) => {
    setErr(null);
    setNote(null);
    setLoaded(null);
    try {
      setNote(await fn());
    } catch (e) {
      setErr(errorLine(e, scope?.display_name ?? ""));
    }
    await reload();
  };

  const tabs: [Tab, string, number | null][] = [
    ["installed", t("plug.tab.installed"), rows ? own.length : null],
    ["browse", t("plug.tab.browse"), catalog ? catalog.total : null],
    ["builtin", t("plug.tab.builtin"), rows ? builtin.length : null],
  ];

  return (
    <div className="pg" data-testid="plugins">
      <PageHead
        title={t("plug.title")}
        sub={t("plug.sub")}
        right={
          <BotChip
            bots={bots}
            bot={scope}
            wide
            label={scope ? t("plug.scope", { bot: scope.display_name }) : undefined}
            onPick={(n) => s.openPlugins(n)}
            testId="plug-scope"
          />
        }
      />
      <div className="pg-body">
        <div className="pg-scroll">
          <AskBox bots={bots} bot={askTo} onBot={setAskBot} value={text} onChange={setText} placeholder={t("plug.placeholder")} onSend={send} />
          <div className="pl-tabs" role="tablist" data-testid="plug-tabs">
            {tabs.map(([id, label, n]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                className={tab === id ? "on" : undefined}
                onClick={() => setTab(id)}
                data-testid={`plug-tab-${id}`}
              >
                {label}
                {n !== null && <small>{n.toLocaleString()}</small>}
              </button>
            ))}
          </div>
          {err && (
            <p className="pg-err" role="alert" data-testid="page-error">
              {err}
            </p>
          )}
          {note && (
            <p className="pg-note" role="status" data-testid="page-note">
              {note}
            </p>
          )}
          {loaded && scope && (
            <p className="pg-note" role="status">
              <PluginLoad key={loaded.n} bot={scope} plugin={loaded.plugin} load={loaded.load} restartBot={loaded.restartBot} testId="page-load" />
            </p>
          )}
          {tab === "browse" ? (
            <Browse
              bot={scope}
              catalog={catalog}
              query={query}
              setQuery={setQuery}
              category={category}
              setCategory={setCategory}
              installed={installedNames}
              onInstall={setSheet}
              onDetails={setSheet}
            />
          ) : rows === null ? (
            <div className="pg-empty">{t("plug.loading")}</div>
          ) : (tab === "installed" ? own : builtin).length === 0 ? (
            <div className="pg-empty" data-testid="plug-empty">
              <b>{tab === "installed" ? t("plug.emptyInstalled", { bot: scope?.display_name ?? "" }) : t("plug.emptyBuiltin")}</b>
              {tab === "installed" && <span>{t("plug.emptyInstalledHint", { bot: scope?.display_name ?? "" })}</span>}
            </div>
          ) : (
            <div className="pl-grid" data-testid={`plug-grid-${tab}`}>
              {(tab === "installed" ? own : builtin).map((r) => (
                <InstalledCard
                  key={r.key}
                  r={r}
                  bot={scope!}
                  onToggle={(on) =>
                    void run(async () => {
                      const res = await s.pluginsToggle(scope!.name, r.key, on);
                      if (on && res.load && res.load !== "live")
                        setLoaded({ plugin: r.name, load: res.load, restartBot: res.restart_bot, n: Date.now() });
                      return null;
                    })
                  }
                  onUpdate={() =>
                    void run(async () => {
                      const u = await s.pluginsUpdate(scope!.name, r.name);
                      if (!u.unchanged && u.load && u.load !== "live")
                        setLoaded({ plugin: r.name, load: u.load, restartBot: u.restart_bot, n: Date.now() });
                      return u.unchanged ? t("plug.upToDate", { name: r.title || r.name }) : t("plug.updated", { name: r.title || r.name });
                    })
                  }
                  onRemove={() =>
                    void run(async () => {
                      await s.pluginsRemove(scope!.name, r.name);
                      return t("plug.removed", { name: r.title || r.name });
                    })
                  }
                />
              ))}
            </div>
          )}
        </div>
      </div>
      {sheet && scope && (
        <InstallSheet
          entry={sheet}
          bot={scope}
          onClose={() => setSheet(null)}
          onInstalled={() => {
            void reload();
          }}
        />
      )}
    </div>
  );
}

function CardShell({
  category,
  name,
  tier,
  description,
  chips,
  warn,
  control,
  testId,
}: {
  category: string;
  name: string;
  tier: string;
  description: string;
  chips: string[];
  warn?: string;
  control: React.ReactNode;
  testId: string;
}) {
  return (
    <div className="pl-card" data-testid={testId}>
      <span className="pl-pic" aria-hidden="true">
        <CategoryIcon category={category} />
      </span>
      <div className="pl-main">
        <div className="pl-nm">
          <span className="pl-nm-t">{name}</span>
          <span className="pl-badge">{tierWord(tier)}</span>
        </div>
        <p className="pl-ds">{description}</p>
        {(chips.length > 0 || warn) && (
          <div className="pl-adds">
            {chips.map((c) => (
              <span key={c}>{c}</span>
            ))}
            {warn && (
              <span className="need" data-testid="needs-key">
                {warn}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="pl-ctl">{control}</div>
    </div>
  );
}

function InstalledCard({
  r,
  bot,
  onToggle,
  onUpdate,
  onRemove,
}: {
  r: PluginRow;
  bot: Bot;
  onToggle: (on: boolean) => void;
  onUpdate: () => void;
  onRemove: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const label = r.title || r.name;
  const own = r.source !== "bundled";
  return (
    <CardShell
      category={r.category || "general"}
      name={label}
      tier={r.tier}
      description={r.description}
      chips={[...addsOf(r), ...(r.update_available ? [t("plug.updateAvail")] : [])]}
      warn={r.needs_env.length && !r.enabled ? t("plug.needsKey") : undefined}
      testId={`plug-card-${r.name}`}
      control={
        <>
          <Toggle on={r.enabled} label={label} onChange={onToggle} testId={`plug-toggle-${r.name}`} />
          {own && (
            <span className="pl-menu">
              <button type="button" className="pl-dots" aria-label={t("page.more", { name: label })} onClick={() => setMenu((m) => !m)} data-testid={`plug-menu-${r.name}`}>
                <DotsIcon />
              </button>
              <Popover
                open={menu}
                onClose={() => {
                  setMenu(false);
                  setConfirm(false);
                }}
                width={220}
                label={label}
              >
                {confirm ? (
                  <div className="pl-confirm" role="alertdialog">
                    <span>{t("plug.confirmRemove", { name: label, bot: bot.display_name })}</span>
                    <div className="pg-btns">
                      <button
                        type="button"
                        className="pg-btn danger-fill"
                        onClick={() => {
                          setMenu(false);
                          setConfirm(false);
                          onRemove();
                        }}
                        data-testid="plug-confirm-remove"
                      >
                        {t("plug.remove")}
                      </button>
                      <button type="button" className="pg-btn" onClick={() => setConfirm(false)}>
                        {t("page.cancel")}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="pg-menu">
                    {r.catalog_name && (
                      <button
                        type="button"
                        onClick={() => {
                          setMenu(false);
                          onUpdate();
                        }}
                        data-testid="plug-update"
                      >
                        {t("plug.update")}
                      </button>
                    )}
                    <button type="button" className="danger" onClick={() => setConfirm(true)} data-testid="plug-remove">
                      {t("plug.remove")}
                    </button>
                  </div>
                )}
              </Popover>
            </span>
          )}
        </>
      }
    />
  );
}

function Browse({
  bot,
  catalog,
  query,
  setQuery,
  category,
  setCategory,
  installed,
  onInstall,
  onDetails,
}: {
  bot: Bot | undefined;
  catalog: CatalogResult | null;
  query: string;
  setQuery: (q: string) => void;
  category: string;
  setCategory: (c: string) => void;
  installed: Set<string>;
  onInstall: (e: CatalogEntry) => void;
  onDetails: (e: CatalogEntry) => void;
}) {
  if (catalog && catalog.total === 0)
    return (
      <div className="pg-empty" data-testid="plug-no-catalog">
        <b>{t("plug.noCatalog")}</b>
        <span>{t("plug.noCatalogHint", { bot: bot?.display_name ?? "" })}</span>
      </div>
    );
  return (
    <>
      <div className="pl-browsebar">
        <label className="pl-search">
          <SearchIcon />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("plug.search")} aria-label={t("plug.search")} data-testid="plug-search" />
        </label>
        <div className="pl-cats" data-testid="plug-cats">
          <button type="button" className={`pg-chip${category === "" ? " on" : ""}`} onClick={() => setCategory("")}>
            {t("plug.cat.all")}
          </button>
          {CATEGORIES.filter((c) => catalog?.categories[c]).map((c) => (
            <button key={c} type="button" className={`pg-chip${category === c ? " on" : ""}`} onClick={() => setCategory(c)} data-testid={`plug-cat-${c}`}>
              {catWord(c)}
            </button>
          ))}
        </div>
      </div>
      {!catalog ? (
        <div className="pg-empty">{t("plug.loading")}</div>
      ) : catalog.entries.length === 0 ? (
        <div className="pg-empty">{t("plug.noMatch")}</div>
      ) : (
        <>
          <div className="pl-grid" data-testid="plug-grid-browse">
            {catalog.entries.map((e) => {
              const has = installed.has(e.name);
              return (
                <CardShell
                  key={e.name}
                  category={e.category}
                  name={e.title || e.name}
                  tier={e.tier}
                  description={e.description}
                  chips={addsOf({ tools: e.tools.length, hooks: e.hooks.length, category: e.category })}
                  warn={e.requires_env.length ? t("plug.needsKey") : undefined}
                  testId={`plug-card-${e.name}`}
                  control={
                    <>
                      <button
                        type="button"
                        className="pg-btn"
                        onClick={() => onDetails(e)}
                        aria-label={t("plug.detailsFor", { name: e.title || e.name })}
                        data-testid={`plug-details-${e.name}`}
                      >
                        {t("plug.details")}
                      </button>
                      {has ? (
                        <span className="pl-done">{t("plug.installed")}</span>
                      ) : (
                        <button type="button" className="pg-btn" onClick={() => onInstall(e)} data-testid={`plug-install-${e.name}`}>
                          {t("plug.install")}
                        </button>
                      )}
                    </>
                  }
                />
              );
            })}
          </div>
          {catalog.matched > catalog.entries.length && (
            <p className="pg-foot">{t("plug.showing", { n: catalog.entries.length, total: catalog.matched.toLocaleString() })}</p>
          )}
        </>
      )}
    </>
  );
}

type SheetState =
  | { step: "checking" }
  | { step: "ready"; ins: InspectResult }
  | { step: "installing"; ins: InspectResult }
  | { step: "done"; off: string | null; load: "live" | "reload" | "restart"; restartBot?: string }
  | { step: "refused"; line: string; recheck: boolean }
  | { step: "failed"; line: string };

/** Install: Hermes inspects the entry at its catalog pin first (installs nothing), the person sees what it adds and
 *  for which bot, and only then Install sends that same pin back. */
function InstallSheet({ entry, bot, onClose, onInstalled }: { entry: CatalogEntry; bot: Bot; onClose: () => void; onInstalled: () => void }) {
  const s = useStore();
  const [st, setSt] = useState<SheetState>({ step: "checking" });
  const label = entry.title || entry.name;

  const inspect = useCallback(() => {
    setSt({ step: "checking" });
    s.pluginsInspect(bot.name, entry.name)
      .then((ins) => setSt({ step: "ready", ins }))
      .catch((e) => setSt({ step: "failed", line: errorLine(e, bot.display_name) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name, entry.name]);
  useEffect(inspect, [inspect]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const install = async (ins: InspectResult) => {
    setSt({ step: "installing", ins });
    try {
      const r = await s.pluginsInstall(bot.name, entry.name, ins.sha);
      const env = r.missing_env.join(", ");
      setSt({
        step: "done",
        // the title says it is installed; the body says only what is new: off until a value is set, or when it loads
        off: r.enabled ? null : t("plug.sheet.doneOff", { env }),
        // when it takes effect, from Hermes' own answer; an older bridge without `load` falls back to restart_required
        load: !r.enabled ? "live" : (r.load ?? (r.restart_required ? "reload" : "live")),
        restartBot: r.restart_bot,
      });
      onInstalled();
    } catch (e) {
      // Hermes' refusals carry a reason code; its message may come from a git server, so it is never shown here
      const code = (e as { code?: string })?.code;
      if (code === "exists") setSt({ step: "refused", line: t("plug.sheet.exists", { bot: bot.display_name, name: entry.name }), recheck: false });
      else if (code === "source_moved") setSt({ step: "refused", line: t("plug.sheet.moved", { name: label }), recheck: true });
      else setSt({ step: "failed", line: errorLine(e, bot.display_name) });
    }
  };

  const e = st.step === "ready" || st.step === "installing" ? st.ins.entry : entry;
  const adds = [...e.tools.slice(0, 6), ...(e.tools.length > 6 ? [`+${e.tools.length - 6}`] : [])].join(", ");
  return (
    <div className="pl-scrim" onMouseDown={(ev) => ev.target === ev.currentTarget && onClose()}>
      <div className="pl-sheet" role="dialog" aria-modal="true" aria-label={t("plug.sheet.title", { name: label })} data-testid="install-sheet">
        <div className="pl-sheet-top">
          <span className="pl-pic" aria-hidden="true">
            <CategoryIcon category={e.category} />
          </span>
          <div>
            <h2 data-testid="sheet-title">{st.step === "done" ? t("plug.sheet.titleDone", { name: label }) : t("plug.sheet.title", { name: label })}</h2>
            <p className="pl-ds">{e.description}</p>
          </div>
        </div>
        {st.step === "checking" ? (
          <p className="pl-sheet-wait" data-testid="sheet-checking">
            {t("plug.sheet.checking", { name: label })}
          </p>
        ) : st.step === "done" ? (
          <div className="pl-sheet-res" data-testid="sheet-done">
            {st.off ? (
              <span data-testid="sheet-off">{st.off}</span>
            ) : (
              <PluginLoad bot={bot} plugin={entry.name} load={st.load} restartBot={st.restartBot} testId="sheet-load" />
            )}
          </div>
        ) : st.step === "refused" || st.step === "failed" ? (
          <p className="pg-err" role="alert" data-testid="sheet-error">
            {st.line}
          </p>
        ) : (
          <dl className="pl-facts" data-testid="sheet-facts">
            <dt>{t("plug.sheet.source")}</dt>
            <dd>
              <span className="pl-badge">{tierWord(e.tier)}</span> <span className="mono">{e.repo.replace(/^https:\/\/github\.com\//, "")}</span>
            </dd>
            {e.version && (
              <>
                <dt>{t("plug.sheet.version")}</dt>
                <dd>
                  {e.version} <span className="mono pl-quiet">@{st.ins.sha.slice(0, 7)}</span>
                </dd>
              </>
            )}
            <dt>{t("plug.sheet.adds")}</dt>
            <dd>
              {e.tools.length || e.hooks.length ? (
                <>
                  {addsOf({ tools: e.tools.length, hooks: e.hooks.length, category: e.category }).join(" · ")}
                  {adds && <span className="mono pl-quiet pl-toolnames"> ({adds})</span>}
                </>
              ) : (
                t("plug.sheet.nothing")
              )}
            </dd>
            {e.requires_env.length > 0 && (
              <>
                <dt>{t("plug.sheet.env")}</dt>
                <dd>
                  <span className="mono">{e.requires_env.join(", ")}</span>
                  <span className="pl-quiet"> · {t("plug.sheet.envHint", { env: e.requires_env[0] })}</span>
                </dd>
              </>
            )}
            <dt>{t("plug.sheet.scope")}</dt>
            <dd className="pl-scope">
              <Avatar bot={bot.name} size={14} />
              {t("plug.sheet.scopeLine", { bot: bot.display_name })}
            </dd>
          </dl>
        )}
        {(st.step === "ready" || st.step === "installing") && st.ins.warnings.length > 0 && (
          <div className="pl-warn">
            {st.ins.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
        )}
        <div className="pg-btns pl-sheet-btns">
          {st.step === "ready" || st.step === "installing" ? (
            <>
              <button type="button" className="pg-btn pri" disabled={st.step === "installing"} onClick={() => void install(st.ins)} data-testid="sheet-install">
                {st.step === "installing" ? t("plug.sheet.installing") : t("plug.sheet.install")}
              </button>
              <button type="button" className="pg-btn" onClick={onClose} data-testid="sheet-cancel">
                {t("page.cancel")}
              </button>
            </>
          ) : st.step === "refused" && st.recheck ? (
            <>
              <button type="button" className="pg-btn pri" onClick={inspect} data-testid="sheet-recheck">
                {t("plug.sheet.recheck")}
              </button>
              <button type="button" className="pg-btn" onClick={onClose}>
                {t("page.cancel")}
              </button>
            </>
          ) : (
            <button type="button" className="pg-btn" onClick={onClose} data-testid="sheet-close">
              {st.step === "checking" ? t("page.cancel") : t("page.close")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
