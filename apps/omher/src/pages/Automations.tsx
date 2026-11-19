// Automations: every bot's cron jobs in one list (read from each profile's cron/jobs.json by the bridge), a detail
// panel for the one picked, and the "say it in words" box that hands a request to a bot's chat. The only changes
// this page makes itself go through the bot's own `cron.manage` (add, pause, resume, remove); Run now and Edit are
// chat messages, because cron.manage has neither (BOUNDARY rule 24).
import { useEffect, useMemo, useRef, useState } from "react";
import type { Automation, Bot } from "../lib/protocol";
import { useStore } from "../state/store";
import { t } from "../i18n";
import { RunOnce } from "./RunOnce";
import { holdImeEnter } from "../lib/ime";
import { Avatar, PlusIcon, SourceIcon } from "../ui";
import { Seg } from "../chat/model/Seg";
import { AskBox, BotChip, errorLine, PageHead, Toggle, atWords, dateWords, nextWords, toSec } from "./kit";
import { scheduleWords } from "./schedule";
import { isBrief, PLATFORM_NAME, reasonWords, scheduleOf, watchOf, watchSentence, whereOf, WATCH_EVERY, type WatchInfo } from "./watch";

const OK = new Set(["ok", "success", "done", "completed", "delivered"]);
type Status = "ok" | "failed" | "never" | "paused";

export function statusOf(a: Automation): Status {
  if (a.paused) return "paused";
  // a channel watch the bot can't read is never shown as done, whatever the run's own status says
  if (watchOf(a)?.state === "not_readable") return "failed";
  if (!a.last_run_at || !a.last_status) return "never";
  return OK.has(String(a.last_status).toLowerCase()) ? "ok" : "failed";
}

const keyOf = (a: Automation) => `${a.bot}:${a.id}`;
const firstLine = (s: string) => s.split("\n").find((l) => l.trim())?.trim() ?? "";
/** What the job does, in a line: its prompt, or for a script job (no prompt, no model) the script it runs. */
export const whatOf = (a: Pick<Automation, "prompt" | "script">) => a.prompt.trim() || (a.script ? t("auto.script", { script: a.script }) : "");
const PLATFORM: Record<string, string> = { discord: "Discord", slack: "Slack", telegram: "Telegram", whatsapp: "WhatsApp", signal: "Signal" };

/** Where a job's result goes, as one or more `{icon, text}` parts (Hermes' `deliver` may combine targets). */
export function deliverParts(a: Automation, bots: Bot[]): { source: string | null; bot: string | null; text: string }[] {
  const nameOf = (n: string) => bots.find((b) => b.name === n)?.display_name ?? n;
  return (a.deliver || "local").split(",").map((raw) => {
    const d = raw.trim();
    const low = d.toLowerCase();
    if (low === "bot-chat" || low.startsWith("bot-chat:")) {
      const who = d.slice(9).trim() || a.bot;
      return { source: null, bot: who, text: t("auto.dl.chat", { bot: nameOf(who) }) };
    }
    if (low === "local" || !low) return { source: null, bot: null, text: t("auto.dl.local") };
    if (low === "all") return { source: null, bot: null, text: t("auto.dl.all") };
    if (low === "origin") {
      if (!a.origin) return { source: null, bot: null, text: t("auto.dl.origin") };
      const p = a.origin.platform;
      return { source: p, bot: null, text: t("auto.dl.place", { platform: PLATFORM[p] ?? p, place: a.origin.place }).trim() };
    }
    const p = low.split(":")[0];
    return { source: p, bot: null, text: PLATFORM[p] ?? p };
  });
}

export function AutomationsPage() {
  const s = useStore();
  const list = s.automations ?? [];
  const bots = s.bots;
  const [askBot, setAskBot] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addingWatch, setAddingWatch] = useState(false);
  const askRef = useRef<HTMLInputElement>(null);

  const bot = bots.find((b) => b.name === askBot) ?? bots.find((b) => b.name === s.selectedBot) ?? bots[0];
  const shown = filter ? list.filter((a) => a.bot === filter) : list;
  const sel = list.find((a) => keyOf(a) === s.ui.automation) ?? null;
  const counts = useMemo(() => {
    const by: Record<string, number> = {};
    for (const a of list) by[a.bot] = (by[a.bot] ?? 0) + 1;
    return by;
  }, [list]);
  const failed = shown.filter((a) => statusOf(a) === "failed").length;
  const paused = shown.filter((a) => a.paused).length;
  const nameOf = (n: string) => bots.find((b) => b.name === n)?.display_name ?? n;

  useEffect(() => {
    void s.loadAutomations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = () => {
    if (!bot || !text.trim()) return;
    const msg = text.trim();
    setText("");
    void s.sendTo(bot.name, msg);
  };

  const act = async (a: Automation, action: "pause" | "resume" | "remove") => {
    setErr(null);
    setBusy(keyOf(a));
    try {
      await s.automationDo(a.bot, a.id, action);
      if (action === "remove" && s.ui.automation === keyOf(a)) s.openAutomations(null);
    } catch (e) {
      setErr(errorLine(e, nameOf(a.bot)));
    } finally {
      setBusy(null);
    }
  };

  const summary = [failed ? t("auto.nFailed", { n: failed }) : "", paused ? t("auto.nPaused", { n: paused }) : ""].filter(Boolean).join(" · ");

  return (
    <div className="pg" data-testid="automations">
      <PageHead title={t("auto.title")} sub={t("auto.sub")} />
      <div className={`pg-body${sel ? " has-detail" : ""}`}>
        <div className="pg-scroll">
          <AskBox
            bots={bots}
            bot={bot}
            onBot={setAskBot}
            value={text}
            onChange={setText}
            placeholder={t("auto.placeholder")}
            onSend={send}
            inputRef={askRef}
          />
          <div className="pg-sug" data-testid="suggestions">
            {(["auto.sug1", "auto.sug2", "auto.sug3"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => {
                  setText(t(k));
                  askRef.current?.focus();
                }}
              >
                {t(k)}
              </button>
            ))}
          </div>
          <div className="pg-filters" data-testid="auto-filters">
            <button type="button" className={`pg-chip${filter === null ? " on" : ""}`} onClick={() => setFilter(null)} data-testid="filter-all">
              {t("auto.all")} <span className="pg-n">{list.length}</span>
            </button>
            {bots
              .filter((b) => counts[b.name])
              .map((b) => (
                <button
                  key={b.name}
                  type="button"
                  className={`pg-chip${filter === b.name ? " on" : ""}`}
                  onClick={() => setFilter(b.name)}
                  data-testid={`filter-${b.name}`}
                >
                  {b.display_name} <span className="pg-n">{counts[b.name]}</span>
                </button>
              ))}
            <span className="pg-summary" data-testid="auto-summary">
              {summary}
            </span>
            <button
              type="button"
              className="pg-btn"
              onClick={() => {
                setAdding(false);
                if (!addingWatch) s.openAutomations(null);
                setAddingWatch((v) => !v);
              }}
              aria-expanded={addingWatch}
              data-testid="watch-new"
            >
              <PlusIcon size={12} />
              {t("watch.new")}
            </button>
            <button
              type="button"
              className="pg-btn"
              onClick={() => {
                setAddingWatch(false);
                setAdding((v) => !v);
              }}
              aria-expanded={adding}
              data-testid="auto-new"
            >
              <PlusIcon size={12} />
              {t("auto.new")}
            </button>
          </div>
          {err && (
            <p className="pg-err" role="alert" data-testid="page-error">
              {err}
            </p>
          )}
          {adding && <NewForm bots={bots} initial={bot?.name} onDone={() => setAdding(false)} />}
          {addingWatch && <NewWatchForm bots={bots} initial={bot?.name} onDone={() => setAddingWatch(false)} />}
          {shown.length === 0 ? (
            <div className="pg-empty" data-testid="auto-empty">
              <b>{filter ? t("auto.emptyBot", { bot: nameOf(filter) }) : t("auto.empty")}</b>
              {!filter && <span>{t("auto.emptyHint")}</span>}
            </div>
          ) : (
            <div className="au-list" role="list" data-testid="auto-list">
              {shown.map((a) => (
                <Row
                  key={keyOf(a)}
                  a={a}
                  on={sel ? keyOf(sel) === keyOf(a) : false}
                  busy={busy === keyOf(a)}
                  onOpen={() => s.openAutomations(keyOf(a))}
                  onToggle={(on) => void act(a, on ? "resume" : "pause")}
                />
              ))}
            </div>
          )}
        </div>
        {sel && (
          <Detail
            a={sel}
            bots={bots}
            busy={busy === keyOf(sel)}
            onClose={() => s.openAutomations(null)}
            onRun={() => void s.sendTo(sel.bot, t("auto.runMsg", { name: sel.name, id: sel.id }))}
            onEdit={() => {
              setAskBot(sel.bot);
              setText(t("auto.editMsg", { name: sel.name }));
              requestAnimationFrame(() => {
                const el = askRef.current;
                if (!el) return;
                el.focus();
                el.setSelectionRange(el.value.length, el.value.length);
              });
            }}
            onAct={(action) => void act(sel, action)}
          />
        )}
      </div>
    </div>
  );
}

function statusText(a: Automation, st: Status = statusOf(a)): string {
  const at = toSec(a.last_run_at);
  if (st === "paused") return t("auto.st.paused");
  if (watchOf(a)?.state === "not_readable") return t("watch.st.unreadable");
  if (watchOf(a)) return st === "never" ? t("watch.st.never") : t("watch.st.ok", { at: at ? atWords(at) : "" });
  if (st === "never") return t("auto.st.never");
  return t(st === "ok" ? "auto.st.ok" : "auto.st.failed", { at: at ? atWords(at) : "" });
}

function StatusMark({ a, st = statusOf(a), text = statusText(a, st) }: { a: Automation; st?: Status; text?: string }) {
  return (
    <span className={`au-st ${st}`} data-status={st} title={text}>
      <i aria-hidden="true" />
      <span className="au-st-t">{text}</span>
    </span>
  );
}

function Row({ a, on, busy, onOpen, onToggle }: { a: Automation; on: boolean; busy: boolean; onOpen: () => void; onToggle: (on: boolean) => void }) {
  const next = toSec(a.next_run_at);
  const w = watchOf(a);
  return (
    <div
      role="listitem"
      className={`au-row${on ? " on" : ""}${a.paused ? " paused" : ""}${w ? " watch" : ""}`}
      onClick={onOpen}
      data-testid={`auto-row-${a.id}`}
      data-watch={w ? w.state : undefined}
    >
      <Avatar bot={a.bot} size={26} />
      <button type="button" className="au-main" onClick={onOpen} aria-current={on ? "true" : undefined}>
        <span className="au-name">
          {w && <span className="au-tag" data-testid="watch-tag">{t(isBrief(a) ? "brief.line" : "watch.line")}</span>}
          {a.name}
        </span>
        {w ? (
          <span className="au-desc au-watch-desc" data-testid="watch-desc">
            {w.platform && <SourceIcon source={w.platform} size={11} />}
            <span>{[whereOf(w), w.what].filter(Boolean).join(" · ")}</span>
          </span>
        ) : (
          <span className="au-desc">{firstLine(whatOf(a))}</span>
        )}
      </button>
      <span className="au-when">
        <span className="au-sched" title={a.schedule} data-testid={`auto-sched-${a.id}`}>
          {scheduleOf(a)}
        </span>
        <small>{t("auto.next", { when: !a.paused && next ? nextWords(next) : t("auto.nextNone") })}</small>
      </span>
      <StatusMark a={a} />
      <Toggle on={!a.paused} label={t("auto.toggle", { name: a.name })} onChange={onToggle} disabled={busy} testId={`auto-toggle-${a.id}`} />
    </div>
  );
}

function Detail({
  a,
  bots,
  busy,
  onClose,
  onRun,
  onEdit,
  onAct,
}: {
  a: Automation;
  bots: Bot[];
  busy: boolean;
  onClose: () => void;
  onRun: () => void;
  onEdit: () => void;
  onAct: (action: "pause" | "resume" | "remove") => void;
}) {
  const [confirm, setConfirm] = useState(false);
  useEffect(() => setConfirm(false), [a.id]);
  const botName = bots.find((b) => b.name === a.bot)?.display_name ?? a.bot;
  const created = toSec(a.created_at);
  const next = toSec(a.next_run_at);
  const last = toSec(a.last_run_at);
  const st = statusOf(a);
  const w = watchOf(a);
  return (
    <aside className="au-detail" aria-label={a.name} data-testid="auto-detail">
      <div className="au-d-top">
        <h2>{a.name}</h2>
        <button type="button" className="pg-x" aria-label={t("page.close")} onClick={onClose}>
          ×
        </button>
      </div>
      <div className="au-d-meta">
        <Avatar bot={a.bot} size={16} />
        {created ? t("auto.made", { bot: botName, date: dateWords(created) }) : botName}
      </div>
      <div className="au-k">{t("auto.when")}</div>
      <div className="au-v">
        <span title={a.schedule}>{scheduleOf(a)}</span>
        {!a.paused && next && <span className="au-quiet"> · {t("auto.next", { when: nextWords(next) })}</span>}
      </div>
      {w ? (
        <WatchFacts w={w} />
      ) : (
        <>
          <div className="au-k">{t("auto.what")}</div>
          <div className="au-prompt" data-testid="auto-prompt">
            {whatOf(a)}
          </div>
        </>
      )}
      <div className="au-k">{t("auto.deliver")}</div>
      <div className="au-v au-dl" data-testid="auto-deliver">
        {deliverParts(a, bots).map((d, i) => (
          <span key={i} className="au-dl-p">
            {d.bot ? <Avatar bot={d.bot} size={14} /> : d.source ? <SourceIcon source={d.source} size={13} /> : null}
            {d.text}
          </span>
        ))}
      </div>
      <div className="au-k">{t("auto.last")}</div>
      <div className="au-v" data-testid="auto-last">
        {st === "never" || !last ? (
          t("auto.lastNever")
        ) : (
          (() => {
            const ran = statusOf({ ...a, paused: false });
            return <StatusMark a={a} st={ran} text={t("auto.lastLine", { status: statusText(a, ran), n: a.repeat.completed })} />;
          })()
        )}
        {a.last_error && st === "failed" && !w && <div className="au-errline">{t("auto.lastError", { error: a.last_error })}</div>}
      </div>
      {confirm ? (
        <div className="pg-confirm" role="alertdialog" data-testid="auto-confirm">
          <span>{t("auto.confirmDelete", { name: a.name, bot: botName })}</span>
          <div className="pg-btns">
            <button type="button" className="pg-btn danger-fill" disabled={busy} onClick={() => onAct("remove")} data-testid="auto-confirm-delete">
              {t("auto.delete")}
            </button>
            <button type="button" className="pg-btn" onClick={() => setConfirm(false)}>
              {t("page.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="pg-btns au-btns">
          <button type="button" className="pg-btn" onClick={onEdit} data-testid="auto-edit">
            {t("auto.edit")}
          </button>
          <button type="button" className="pg-btn" disabled={busy} onClick={() => onAct(a.paused ? "resume" : "pause")} data-testid="auto-pause">
            {a.paused ? t("auto.resume") : t("auto.pause")}
          </button>
          <button type="button" className="pg-btn danger" onClick={() => setConfirm(true)} data-testid="auto-delete">
            {t("auto.delete")}
          </button>
          {/* outside the schedule, so quiet and one step more: never the button that asks to be pressed */}
          <RunOnce label={t("auto.run")} onRun={onRun} resetKey={a.id} testId="auto-run" />
        </div>
      )}
      <p className="au-note" data-testid="auto-note">{t(w ? "watch.note" : "auto.note", { bot: botName, name: a.name })}</p>
    </aside>
  );
}

/** "+ New": a job through the bot's own `cron.manage add`. Hermes reads the schedule and says so when it can't. */
function NewForm({ bots, initial, onDone }: { bots: Bot[]; initial?: string; onDone: () => void }) {
  const s = useStore();
  const [botName, setBotName] = useState(initial ?? bots[0]?.name ?? "");
  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState("");
  const [prompt, setPrompt] = useState("");
  const [deliver, setDeliver] = useState<"chat" | "none">("chat");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bot = bots.find((b) => b.name === botName);
  const ready = !!bot && name.trim() && schedule.trim() && prompt.trim();
  const submit = async () => {
    if (!bot || !ready) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await s.addAutomation({
        bot: bot.name,
        name: name.trim(),
        schedule: schedule.trim(),
        prompt: prompt.trim(),
        ...(deliver === "chat" ? { deliver: `bot-chat:${bot.name}` } : {}),
      });
      onDone();
      s.openAutomations(`${bot.name}:${r.job}`);
    } catch (e) {
      setErr(errorLine(e, bot.display_name));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="au-form"
      onKeyDown={holdImeEnter}
      data-testid="auto-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="au-form-h">{t("auto.form.title")}</div>
      <label className="au-f">
        <span>{t("auto.form.bot")}</span>
        <BotChip bots={bots} bot={bot} onPick={setBotName} testId="form-bot" />
      </label>
      <label className="au-f">
        <span>{t("auto.form.name")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("auto.form.namePh")} maxLength={120} data-testid="form-name" />
      </label>
      <label className="au-f">
        <span>{t("auto.form.schedule")}</span>
        <input value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder={t("auto.form.schedulePh")} maxLength={200} data-testid="form-schedule" />
      </label>
      <label className="au-f">
        <span>{t("auto.form.prompt")}</span>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={t("auto.form.promptPh")} rows={3} maxLength={8000} data-testid="form-prompt" />
      </label>
      <div className="au-f">
        <span>{t("auto.form.deliver")}</span>
        <Seg
          small
          label={t("auto.form.deliver")}
          value={deliver}
          onChange={(v) => setDeliver(v as "chat" | "none")}
          options={[
            { value: "chat", label: t("auto.dl.chat", { bot: bot?.display_name ?? "" }) },
            { value: "none", label: t("auto.form.deliverNone") },
          ]}
          testId="form-deliver"
        />
      </div>
      <p className="au-f-hint">{t("auto.form.hint")}</p>
      {err && (
        <p className="pg-err" role="alert" data-testid="form-error">
          {err}
        </p>
      )}
      <div className="pg-btns">
        <button type="submit" className="pg-btn pri" disabled={!ready || busy} data-testid="form-add">
          {t("auto.form.add")}
        </button>
        <button type="button" className="pg-btn" onClick={onDone}>
          {t("page.cancel")}
        </button>
      </div>
    </form>
  );
}

/** A watch's own facts in the detail panel: where, the condition, last check and alert, and why it can't read. */
function WatchFacts({ w }: { w: WatchInfo }) {
  const check = toSec(w.last_check);
  return (
    <>
      {w.state === "not_readable" && (
        <div className="au-unread" role="status" data-testid="watch-unreadable">
          <b>{t("watch.st.unreadable")}</b>
          <span data-testid="watch-reason">{reasonWords(w)}</span>
        </div>
      )}
      <div className="au-k">{t("watch.k.where")}</div>
      <div className="au-v au-dl" data-testid="watch-where">
        <span className="au-dl-p">
          {w.platform && <SourceIcon source={w.platform} size={13} />}
          {whereOf(w) || t("watch.unknown")}
        </span>
      </div>
      <div className="au-k">{t("watch.k.what")}</div>
      <div className="au-prompt" data-testid="watch-what">
        {w.what || t("watch.unknown")}
      </div>
      <div className="au-k">{t("watch.k.checks")}</div>
      <div className="au-v" data-testid="watch-checks">
        {check ? t(w.state === "not_readable" ? "watch.st.tried" : "watch.st.ok", { at: atWords(check) }) : t("watch.st.never")}
        {(w.last_alert || w.state !== "not_readable") && (
          <span className="au-quiet"> · {w.last_alert ? t("watch.lastAlert", { at: atWords(w.last_alert) }) : t("watch.noAlert")}</span>
        )}
      </div>
    </>
  );
}

/** "+ New watch": fills one sentence and sends it to that bot's chat, then opens the chat. It makes no job itself;
 *  the bot confirms the details with the person and sets the watch up with its own tools. */
function NewWatchForm({ bots, initial, onDone }: { bots: Bot[]; initial?: string; onDone: () => void }) {
  const s = useStore();
  const [botName, setBotName] = useState(initial ?? bots[0]?.name ?? "");
  const [platform, setPlatform] = useState<"slack" | "discord">("slack");
  const [channel, setChannel] = useState("");
  const [what, setWhat] = useState("");
  const [every, setEvery] = useState<number>(WATCH_EVERY[0]);
  const bot = bots.find((b) => b.name === botName);
  const ready = !!bot && channel.trim() && what.trim();
  const sentence = ready ? watchSentence({ platform, channel, what, minutes: every }) : "";
  return (
    <form
      className="au-form"
      onKeyDown={holdImeEnter}
      data-testid="watch-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!bot || !ready) return;
        onDone();
        void s.sendTo(bot.name, sentence);
      }}
    >
      <div className="au-form-h">{t("watch.form.title")}</div>
      <label className="au-f">
        <span>{t("auto.form.bot")}</span>
        <BotChip bots={bots} bot={bot} onPick={setBotName} testId="watch-form-bot" />
      </label>
      <div className="au-f">
        <span>{t("watch.form.platform")}</span>
        <Seg
          small
          label={t("watch.form.platform")}
          value={platform}
          onChange={(v) => setPlatform(v as "slack" | "discord")}
          options={[
            { value: "slack", label: PLATFORM_NAME.slack },
            { value: "discord", label: PLATFORM_NAME.discord },
          ]}
          testId="watch-form-platform"
        />
      </div>
      <label className="au-f">
        <span>{t("watch.form.channel")}</span>
        <input value={channel} onChange={(e) => setChannel(e.target.value)} placeholder={t("watch.form.channelPh")} maxLength={120} data-testid="watch-form-channel" />
      </label>
      <label className="au-f">
        <span>{t("watch.form.what")}</span>
        <input value={what} onChange={(e) => setWhat(e.target.value)} placeholder={t("watch.form.whatPh")} maxLength={400} data-testid="watch-form-what" />
      </label>
      <div className="au-f">
        <span>{t("watch.form.every")}</span>
        <Seg
          small
          label={t("watch.form.every")}
          value={String(every)}
          onChange={(v) => setEvery(Number(v))}
          options={WATCH_EVERY.map((m) => ({ value: String(m), label: scheduleWords(`every ${m}m`) }))}
          testId="watch-form-every"
        />
      </div>
      {sentence && (
        <p className="au-f-say" data-testid="watch-form-sentence">
          {sentence}
        </p>
      )}
      <p className="au-f-hint">{t("watch.form.hint", { bot: bot?.display_name ?? "" })}</p>
      <div className="pg-btns">
        <button type="submit" className="pg-btn pri" disabled={!ready} data-testid="watch-form-send">
          {t("watch.form.send", { bot: bot?.display_name ?? "" })}
        </button>
        <button type="button" className="pg-btn" onClick={onDone}>
          {t("page.cancel")}
        </button>
      </div>
    </form>
  );
}
