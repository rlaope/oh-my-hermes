// Settings › Bots › <bot> › Model › Backup model (BOUNDARY rule 55): Hermes' own fallback chain for this bot, the models
// Hermes goes on with when the bot's model cannot respond. The list is read from the bot's config.yaml through
// `fallback.get` (each entry's provider and model, nothing else); Add and Remove send the whole new list through
// `fallback.set`, which runs Hermes' own `config set`, and the section shows the list Hermes stored. The models to pick
// from are the bot's own `models.options` list, the one the chat's model picker shows, in that picker's list style. A
// list written in Hermes' config (an endpoint or key of its own, the legacy key) is shown and never rewritten. A bot on
// another computer and a server (remote-only mode) are set where the bot runs, so nothing is asked there.
import { useEffect, useMemo, useState } from "react";
import "../chat/model/model.css";
import type { BackupChain, Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import { useServerMode } from "../app/remote";
import { t } from "../i18n";
import { ModelIcon, Popover, SearchIcon } from "../ui";
import { errorLine } from "../pages/kit";
import { filterRows, modelRows, type ModelRow } from "../chat/model/modelSearch";
import { BACKUP_MAX, backupOptions, withBackup, withoutBackup, type BackupPair } from "./backupChain";

export function BackupModel({ bot }: { bot: Bot }) {
  const s = useStore();
  const remote = useServerMode().mode === "remote";
  const away = !!bot.host || remote;
  const offline = bot.status === "offline";
  const opts = s.models[bot.name];
  // undefined: reading; null: the read failed (err says why)
  const [read, setRead] = useState<BackupChain | null | undefined>(undefined);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (away) return;
    let live = true;
    setRead(undefined);
    setErr("");
    s.fallbackGet(bot.name).then(
      (r) => live && setRead(r),
      (e) => {
        if (!live) return;
        setErr(errorLine(e, bot.display_name));
        setRead(null);
      },
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name, away]);
  useEffect(() => {
    if (!open) return;
    setQuery("");
    if (!opts && !offline) void s.loadModels(bot.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const chain = read?.chain ?? [];
  const rows = useMemo(
    () => backupOptions(modelRows(opts?.providers ?? []), chain, { provider: bot.provider, model: bot.model }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [opts, read, bot.provider, bot.model],
  );
  const shown = useMemo(() => filterRows(rows, query, "all"), [rows, query]);
  const groups: { slug: string; name: string; rows: ModelRow[] }[] = [];
  for (const r of shown) {
    const last = groups[groups.length - 1];
    if (last && last.slug === r.provider.slug) last.rows.push(r);
    else groups.push({ slug: r.provider.slug, name: r.provider.name, rows: [r] });
  }
  const providerLabel = (slug: string) => opts?.providers.find((p) => p.slug === slug)?.name ?? slug;

  const save = async (next: BackupPair[]) => {
    setOpen(false);
    setBusy(true);
    setErr("");
    try {
      const out = await s.fallbackSet(bot.name, next);
      setRead({ chain: out.chain, editable: out.editable });
      if (out.outcome !== "ok") setErr(t("page.failed", { error: out.line ?? "" }));
    } catch (e) {
      setErr(errorLine(e, bot.display_name));
    }
    setBusy(false);
  };

  const body = () => {
    if (away) {
      return (
        <p className="bp-empty" data-testid="backup-away">
          {bot.host ? t("backup.offPeer", { bot: bot.display_name, label: bot.host.label }) : t("backup.offRemote")}
        </p>
      );
    }
    if (read === undefined) return <p className="bp-empty">{t("backup.loading")}</p>;
    if (read === null) {
      return (
        <p className="bp-empty bad" role="alert" data-testid="backup-error">
          {err}
        </p>
      );
    }
    const full = chain.length >= BACKUP_MAX;
    return (
      <>
        {chain.length ? (
          <ol className="bk-list" data-testid="backup-list">
            {chain.map((e, i) => (
              <li key={`${e.provider}:${e.model}`} className="bk-row" data-testid="backup-entry">
                <span className="bk-i">{i + 1}</span>
                <ModelIcon model={e.model} provider={e.provider} size={13} />
                <span className="bk-t" title={`${e.provider} · ${e.model}`}>
                  {providerLabel(e.provider)} · {e.model}
                </span>
                {e.custom && <span className="st-tag">{t("backup.custom")}</span>}
                {read.editable && (
                  <button
                    type="button"
                    className="st-btn"
                    disabled={busy}
                    aria-label={t("backup.removeOne", { model: e.model })}
                    onClick={() => void save(withoutBackup(chain, i))}
                    data-testid="backup-remove"
                  >
                    {t("backup.remove")}
                  </button>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="bp-empty" data-testid="backup-empty">
            {t("backup.empty", { bot: bot.display_name })}
          </p>
        )}
        {read.editable ? (
          <div className="bk-acts">
            <div className="mp-wrap">
              <button
                type="button"
                className="st-btn"
                onClick={() => setOpen((v) => !v)}
                disabled={busy || full}
                aria-haspopup="dialog"
                aria-expanded={open}
                data-testid="backup-add"
              >
                {t("backup.add")}
              </button>
              <Popover open={open} onClose={() => setOpen(false)} label={t("backup.add")} width={320} align="left" className="mp-pop">
                <div data-testid="backup-pop">
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
                      data-testid="backup-search"
                    />
                  </label>
                  <div className="mp-list">
                    {!opts ? (
                      <div className="mp-empty">{offline ? t("mp.offline", { bot: bot.display_name }) : t("mp.loading")}</div>
                    ) : !shown.length ? (
                      <div className="mp-empty" data-testid="backup-none">
                        {rows.length ? t("mp.none") : t("backup.noOptions")}
                      </div>
                    ) : (
                      groups.map((g) => (
                        <div key={g.slug} role="group" aria-label={g.name}>
                          <div className="mp-g">{g.name}</div>
                          {g.rows.map((r) => (
                            <button
                              key={r.model}
                              type="button"
                              className="mp-opt"
                              onClick={() => void save(withBackup(chain, { provider: r.provider.slug, model: r.model }))}
                              data-testid="backup-opt"
                            >
                              <ModelIcon model={r.model} provider={`${r.provider.slug} ${r.provider.name}`} size={13} />
                              <span className="mp-n" title={r.label === r.model ? undefined : r.model}>
                                {r.label}
                              </span>
                            </button>
                          ))}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </Popover>
            </div>
            {busy ? (
              <span className="bk-st" role="status" data-testid="backup-saving">
                {t("backup.saving")}
              </span>
            ) : full ? (
              <span className="bk-st">{t("backup.max", { n: BACKUP_MAX })}</span>
            ) : null}
          </div>
        ) : (
          <p className="bp-note" data-testid="backup-readonly">
            {t("backup.readOnly")}
          </p>
        )}
        {err && (
          <p className="bp-empty bad" role="alert" data-testid="backup-error">
            {err}
          </p>
        )}
      </>
    );
  };

  return (
    <div className="st-row ap-row-col bk" data-testid="backup-model" aria-busy={busy}>
      <div className="st-k">
        <b>{t("backup.title")}</b>
        <span>{t("backup.hint")}</span>
      </div>
      {body()}
    </div>
  );
}
