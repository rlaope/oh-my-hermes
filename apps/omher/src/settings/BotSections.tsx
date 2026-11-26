// The bot page's sections under its picture and name: its messaging platforms (BOUNDARY rule 43), Persona
// (`SOUL.md`), Memory (Hermes' built-in targets), its Automations, where else it is talking, and its open threads. Persona and memory are files of the bot's own profile,
// read through `bots.page` when the page opens and on Read again (BOUNDARY rule 42); a bot on another computer is read
// there by its own bridge. Nothing here writes: Edit opens the bot's main chat with a request in the composer, and
// only the person sends it. File text is shown as plain text, never as HTML.
import { useEffect, useState } from "react";
import type { Bot, BotPage, MemoryTarget } from "../lib/protocol";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { Spinner, SourceIcon } from "../ui";
import { fileSize } from "../chat/parts/mediaLines";
import { openExternal } from "../lib/openExternal";
import { awayTime, sourceName } from "../elsewhere/format";
import { useNow } from "../elsewhere/useNow";
import { scheduleWords } from "../pages/schedule";
import { statusOf } from "../pages/Automations";
import { errorLine } from "../pages/kit";
import { rowStatus } from "../threads/ThreadTree";
import { StatusGlyph } from "../threads/StatusGlyph";
import { botAutomations, botElsewhere, editDraft, fileProblem, memoryUse, type DraftKind } from "./botPage";
import { PlatformsSection } from "../platforms/PlatformSection";
import { PendingTemplate } from "../addbot/PendingTemplate";

const AUTO_STATUS = { ok: "bp.autoOk", failed: "bp.autoFailed", never: "bp.autoNever", paused: "bp.autoPaused" } as const;

export function BotSections({ bot }: { bot: Bot }) {
  const s = useStore();
  const remote = !!bot.host;
  // undefined: reading; null: the read failed (err says why)
  const [page, setPage] = useState<BotPage | null | undefined>(undefined);
  const [err, setErr] = useState("");
  const [seq, setSeq] = useState(0);

  // read when the page opens and on Read again; no polling
  useEffect(() => {
    let live = true;
    setPage(undefined);
    s.botPage(bot.name).then(
      (r) => live && setPage(r),
      (e) => {
        if (!live) return;
        setErr(errorLine(e, bot.display_name));
        setPage(null);
      },
    );
    void s.loadElsewhere(bot.name);
    void s.loadAutomations();
    // a bot on another computer is read there (rule 45): Read again re-asks this bridge, which never forwards `fresh`
    void s.loadPlatforms(!remote && seq > 0);
    void s.loadThreads(bot.name);
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name, seq]);

  const edit = (kind: DraftKind) => void s.draftTo(bot.name, editDraft(kind));

  return (
    <div className="bp" data-testid="bot-sections">
      <div className="bp-bar">
        <span>{remote && bot.host ? t("bp.remote", { label: bot.host.label }) : t("bp.local")}</span>
        <button type="button" className="st-btn" onClick={() => setSeq((n) => n + 1)} disabled={page === undefined} data-testid="bp-refresh">
          {t("bp.refresh")}
        </button>
      </div>

      <PendingTemplate bot={bot} />

      <PlatformsSection bot={bot} />

      <div className="st-gh">{t("bp.persona")}</div>
      <div className="st-grp bp-grp" data-testid="bp-persona">
        {page === undefined ? (
          <Loading />
        ) : page === null ? (
          <p className="bp-empty bad" role="alert">
            {err}
          </p>
        ) : (
          <Soul soul={page.soul} onEdit={() => edit("soul")} />
        )}
      </div>

      <div className="st-gh">{t("bp.memory")}</div>
      <div className="bp-mems" data-testid="bp-memory">
        {page === undefined ? (
          <div className="st-grp bp-grp">
            <Loading />
          </div>
        ) : page === null ? (
          <div className="st-grp bp-grp">
            <p className="bp-empty bad">{err}</p>
          </div>
        ) : (
          page.memory.map((m) => <Memory key={m.target} m={m} onEdit={() => edit(m.target)} />)
        )}
      </div>

      <Automations bot={bot} />
      <Elsewhere bot={bot} />
      <Threads bot={bot} />
    </div>
  );
}

function Loading() {
  return (
    <div className="bp-empty">
      <Spinner size={12} label={t("id.loading")} />
    </div>
  );
}

/** Edit, on the right of a file card's header: the same place for the persona and each memory file. */
function EditLink({ onEdit, testId }: { onEdit: () => void; testId: string }) {
  return (
    <button type="button" className="bp-link" onClick={onEdit} title={t("bp.editTip")} data-testid={testId}>
      {t("bp.edit")}
    </button>
  );
}

function Soul({ soul, onEdit }: { soul: BotPage["soul"]; onEdit: () => void }) {
  const problem = fileProblem(soul);
  // asking the bot to write or fix the file is offered whatever state it is in
  const head = (
    <div className="bp-mem-h">
      <div className="bp-meta">
        <code>{soul.file}</code>
        {!problem && soul.state !== "missing" && <span data-testid="bp-soul-size">{fileSize(soul.size ?? 0)}</span>}
      </div>
      <EditLink onEdit={onEdit} testId="bp-edit-soul" />
    </div>
  );
  if (problem)
    return (
      <div className="bp-file">
        {head}
        <p className="bp-empty bad">{problem}</p>
      </div>
    );
  if (soul.state === "missing")
    return (
      <div className="bp-file">
        {head}
        <p className="bp-empty" data-testid="bp-soul-missing">
          {t("bp.noSoul")}
        </p>
      </div>
    );
  return (
    <div className="bp-file">
      {head}
      {soul.lossy && <p className="bp-note">{t("bp.lossy")}</p>}
      {soul.text.trim() ? (
        <pre className="bp-text" data-testid="bp-soul-text">
          {soul.text}
        </pre>
      ) : (
        <p className="bp-empty">{t("bp.soulEmpty")}</p>
      )}
    </div>
  );
}

function Memory({ m, onEdit }: { m: MemoryTarget; onEdit: () => void }) {
  const use = memoryUse(m);
  const problem = fileProblem(m);
  const title = m.target === "user" ? t("bp.memUser") : t("bp.memBot");
  return (
    <section className="st-grp bp-grp bp-mem" data-testid={`bp-mem-${m.target}`} aria-label={title}>
      <div className="bp-mem-h">
        <div className="bp-mem-t">
          <b>{title}</b>
          <code>{m.file}</code>
          {!m.enabled && (
            <span className="bp-off" data-testid={`bp-off-${m.target}`} title={t("bp.offTip")}>
              {t("bp.off")}
            </span>
          )}
        </div>
        {/* a switched-off target: the bot cannot change it, so Edit is not offered (the note below says why) */}
        {m.enabled && <EditLink onEdit={onEdit} testId={`bp-edit-${m.target}`} />}
      </div>
      {/* an empty file says so below; an empty track beside it would only repeat that */}
      {!problem && m.chars > 0 && (
        <div className="bp-use" data-testid={`bp-use-${m.target}`}>
          <span className={`bp-bar-in${use.over ? " over" : ""}`} aria-hidden="true">
            <i style={{ width: `${use.pct}%` }} />
          </span>
          <span>{t("bp.chars", { n: m.chars.toLocaleString(), limit: m.limit.toLocaleString() })}</span>
        </div>
      )}
      {!m.enabled && <p className="bp-note">{t("bp.offNote")}</p>}
      {m.lossy && <p className="bp-note">{t("bp.lossy")}</p>}
      {problem ? (
        <p className="bp-empty bad">{problem}</p>
      ) : m.entries.length === 0 ? (
        <p className="bp-empty" data-testid={`bp-mem-empty-${m.target}`}>
          {t("bp.noEntries")}
        </p>
      ) : (
        <ol className="bp-entries" data-testid={`bp-entries-${m.target}`}>
          {m.entries.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Automations({ bot }: { bot: Bot }) {
  const s = useStore();
  const list = botAutomations(s.automations, bot.name);
  return (
    <>
      <div className="st-gh bp-gh">
        <span>{t("bp.automations")}</span>
        <button
          type="button"
          className="bp-link"
          onClick={() => s.openAutomations(null, list.length ? bot.name : null)}
          data-testid="bp-open-automations"
        >
          {t("bp.openAutomations")}
        </button>
      </div>
      <div className="st-grp bp-grp" data-testid="bp-automations">
        {s.automations === null ? (
          <Loading />
        ) : list.length === 0 ? (
          <p className="bp-empty">{t("bp.noAutomations")}</p>
        ) : (
          <ul className="bp-rows">
            {list.map((a) => (
              <li key={a.id}>
                <button type="button" className="bp-row" onClick={() => s.openAutomations(`${a.bot}:${a.id}`, bot.name)} data-testid="bp-automation">
                  <span className="bp-row-t">{a.name}</span>
                  <span className="bp-row-s">{scheduleWords(a.schedule)}</span>
                  <span className={`bp-row-st ${statusOf(a)}`}>{t(AUTO_STATUS[statusOf(a)])}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Elsewhere({ bot }: { bot: Bot }) {
  const s = useStore();
  const away = botElsewhere(s.elsewhere[bot.name]);
  const now = useNow(away.some((a) => a.running));
  return (
    <>
      <div className="st-gh">{t("bp.elsewhere")}</div>
      <div className="st-grp bp-grp" data-testid="bp-elsewhere">
        {away.length === 0 ? (
          <p className="bp-empty">{t("bp.noElsewhere")}</p>
        ) : (
          <ul className="bp-rows">
            {away.map((a) => {
              const src = sourceName(a.source);
              const name = a.label?.trim() || a.title?.trim() || t("aw.session", { app: src });
              const body = (
                <>
                  <SourceIcon source={a.source} size={12} />
                  <span className="bp-row-t">{name}</span>
                  <span className="bp-row-s">{a.place ? `${src} ${a.place}` : src}</span>
                  <span className={`bp-row-st${a.running ? " run" : ""}`}>{awayTime(a, now)}</span>
                </>
              );
              return (
                <li key={a.id} data-testid="bp-away">
                  {a.url ? (
                    <a
                      className="bp-row"
                      href={a.url}
                      title={t("pn.openIn", { app: src })}
                      onClick={(e) => {
                        e.preventDefault();
                        void openExternal(a.url!);
                      }}
                    >
                      {body}
                    </a>
                  ) : (
                    <div className="bp-row" title={t("pn.readOnly", { app: src })}>
                      {body}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </>
  );
}

function Threads({ bot }: { bot: Bot }) {
  const s = useStore();
  const rows = s.threads[bot.name] ?? [];
  return (
    <>
      <div className="st-gh">{t("bp.threads")}</div>
      <div className="st-grp bp-grp" data-testid="bp-threads">
        {rows.length === 0 ? (
          <p className="bp-empty">{t("bp.noThreads")}</p>
        ) : (
          <ul className="bp-rows">
            {rows.map((r) => (
              <li key={r.thread}>
                <button type="button" className="bp-row" onClick={() => void s.openThread(bot.name, r.thread)} data-testid="bp-thread">
                  <StatusGlyph status={rowStatus(s, bot.name, r)} />
                  <span className="bp-row-t">{r.title || t("thread.untitled")}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
