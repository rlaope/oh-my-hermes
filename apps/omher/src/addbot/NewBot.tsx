// Add bot › New bot (BOUNDARY rule 44): pick one of OMH's bot templates (or none), name the bot, press Create. The
// bridge runs Hermes' own `hermes -p default profile create <name> --no-alias` and reads back the folder Hermes made;
// omher writes nothing in the profile. With a template, the new bot's main chat gets one message (applyMessage) and the
// bot applies it with its own tools and approvals, every schedule paused. A bot that cannot see the template skill yet
// (OMH reaches a new profile on the next `omh update`) waits for the person's Apply template, here or on its page.
import { useEffect, useRef, useState } from "react";
import type { BotTemplate, BotTemplates } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { t, tx, type Key } from "../i18n";
import { Spinner } from "../ui";
import { addToList, withBridge } from "./bots";
import { applyMessage, checkName, normalizeName, type NameCheck } from "./templates";
import { applyTemplate, hasApplySkill, setPendingTemplate } from "./pending";

const CREATE_CMD = "hermes profile create";
const UPDATE_CMD = "omh update";
/** Hermes' own command for the `<name>` wrapper `--no-alias` left out (hermes_cli/subcommands/profile.py `alias`). */
const aliasCmd = (bot: string) => `hermes profile alias ${bot}`;

type Step =
  | { kind: "form"; line?: string }
  | { kind: "creating" }
  | { kind: "done"; bot: string; applied: boolean; partial?: string }
  | { kind: "waiting"; bot: string; template: string; again?: boolean };

const NAME_LINE: Record<Exclude<NameCheck, "ok" | "empty">, Key> = {
  rule: "ab.nameRule",
  reserved: "ab.nameReserved",
  omh: "ab.nameOmh",
  taken: "ab.nameTaken",
};

export function NewBot({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const s = useStore();
  const [list, setList] = useState<BotTemplates | null>(null);
  const [pick, setPick] = useState<string>("");
  const [raw, setRaw] = useState("");
  const [step, setStep] = useState<Step>({ kind: "form" });
  // one create and one apply at a time: a double click or two Enters in one tick start nothing twice
  const creating = useRef(false);
  const [applying, setApplying] = useState(false);
  const applyingRef = useRef(false);

  useEffect(() => {
    let live = true;
    withBridge((b) => b.request("bots.templates", {}))
      .then((r) => live && setList(r))
      .catch(() => live && setList({ omh: "unavailable", templates: [] }));
    return () => {
      live = false;
    };
  }, []);

  const name = normalizeName(raw);
  const taken = s.bots.filter((b) => !b.host).map((b) => b.name);
  const check = checkName(name, taken);
  const busy = step.kind === "creating";

  const create = async () => {
    if (check !== "ok" || busy || creating.current) return;
    creating.current = true;
    const template = pick;
    setStep({ kind: "creating" });
    try {
      const r = await withBridge((b) => b.request("bots.create", { name }));
      if (r.outcome === "partial" && r.bot) {
        // made but not set up: listed, and its template (if any) waits for the person on its page, never applied here
        if (template) setPendingTemplate(r.bot, template);
        await addToList(getStore(), r.bot);
        setStep({ kind: "done", bot: r.bot, applied: false, partial: r.line || t("ab.createFailed") });
        return;
      }
      if (r.outcome !== "ok" || !r.bot) {
        setStep({ kind: "form", line: r.line || t("ab.createFailed") });
        return;
      }
      const bot = r.bot;
      const ready = !!template && (await hasApplySkill(bot).catch(() => false));
      await addToList(getStore(), bot, { open: !template || ready });
      if (!template) setStep({ kind: "done", bot, applied: false });
      else if (await applyTemplate(bot, template)) setStep({ kind: "done", bot, applied: true });
      else setStep({ kind: "waiting", bot, template });
    } catch (e) {
      setStep({ kind: "form", line: (e as { message?: string })?.message || t("ab.createFailed") });
    } finally {
      creating.current = false;
    }
  };

  const applyNow = async (bot: string, template: string) => {
    if (applyingRef.current) return;
    applyingRef.current = true;
    setApplying(true);
    try {
      if (await applyTemplate(bot, template)) onDone();
      else setStep({ kind: "waiting", bot, template, again: true });
    } finally {
      applyingRef.current = false;
      setApplying(false);
    }
  };

  const alias = (bot: string) => (
    <div className="ab-hint" data-testid="addbot-alias">
      {tx("ab.alias", { cmd: <code>{aliasCmd(bot)}</code> })}
    </div>
  );

  if (step.kind === "done") {
    return (
      <div className="ab-new" data-testid="addbot-done">
        <div className="ab-h">{t("ab.new")}</div>
        {step.partial ? (
          <div className="ab-err" data-testid="addbot-partial">
            {step.partial}
          </div>
        ) : (
          <div className="ab-line">{t(step.applied ? "ab.createdApplied" : "ab.created", { name: step.bot })}</div>
        )}
        {alias(step.bot)}
        <div className="ab-actions">
          <button type="button" className="ab-btn ab-primary" data-testid="addbot-close" onClick={onDone}>
            {t("ab.close")}
          </button>
        </div>
      </div>
    );
  }

  if (step.kind === "waiting") {
    const { bot, template } = step;
    return (
      <div className="ab-new" data-testid="addbot-waiting">
        <div className="ab-h">{t("ab.new")}</div>
        <div className="ab-line">
          {tx(step.again ? "ab.stillNoSkill" : "ab.needOmh", { name: bot, cmd: <code>{UPDATE_CMD}</code> })}
        </div>
        <div className="ab-hint">{t("ab.later")}</div>
        <div className="ab-hint">{tx("ab.orSend", { msg: <code>{applyMessage(template)}</code> })}</div>
        {alias(bot)}
        <div className="ab-actions">
          <button type="button" className="ab-btn" onClick={() => void (getStore().actions.selectBot(bot), onDone())}>
            {t("ab.openChat")}
          </button>
          <button
            type="button"
            className="ab-btn ab-primary"
            data-testid="addbot-apply"
            disabled={applying}
            onClick={() => void applyNow(bot, template)}
          >
            {t("ab.apply")}
          </button>
        </div>
      </div>
    );
  }

  const templates: BotTemplate[] = list?.omh === "ok" ? list.templates : [];
  return (
    <div className="ab-new" data-testid="addbot-new">
      <div className="ab-h ab-hrow">
        <button type="button" className="ab-back" onClick={onBack} aria-label={t("ab.back")}>
          ‹
        </button>
        {t("ab.new")}
      </div>
      <div className="ab-sub">{t("ab.gallery")}</div>
      <div className="ab-gallery" role="radiogroup" aria-label={t("ab.gallery")} data-testid="addbot-gallery">
        <TemplateRow id="" title={t("ab.noTemplate")} sub={t("ab.noTemplateSub")} pick={pick} onPick={setPick} />
        {templates.map((tp) => (
          <TemplateRow
            key={tp.id}
            id={tp.id}
            title={tp.title}
            sub={tp.summary}
            meta={tp.schedules.length ? t("ab.paused", { n: tp.schedules.length }) : undefined}
            pick={pick}
            onPick={setPick}
          />
        ))}
        {!list && (
          <div className="ab-hint" data-testid="addbot-templates-loading">
            <Spinner /> {t("ab.loading")}
          </div>
        )}
        {list && list.omh !== "ok" && (
          <div className="ab-hint" data-testid={`addbot-omh-${list.omh}`}>
            {list.omh === "missing" ? t("ab.omhMissing") : tx("ab.omhUnavailable", { cmd: <code>{UPDATE_CMD}</code> })}
          </div>
        )}
      </div>
      <label className="ab-sub" htmlFor="addbot-name">
        {t("ab.name")}
      </label>
      <input
        id="addbot-name"
        className="ab-input"
        data-testid="addbot-name"
        value={raw}
        placeholder={t("ab.namePh")}
        spellCheck={false}
        autoCapitalize="off"
        autoComplete="off"
        disabled={busy}
        onChange={(e) => setRaw(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void create();
        }}
      />
      {check !== "ok" && check !== "empty" && (
        <div className="ab-err" data-testid="addbot-name-error">
          {t(NAME_LINE[check], { name })}
        </div>
      )}
      {step.kind === "form" && step.line && (
        <div className="ab-err" data-testid="addbot-create-error">
          {step.line}
        </div>
      )}
      <div className="ab-hint" data-testid="addbot-mirror">
        {t("ab.mirror")}
      </div>
      <div className="ab-hint">{tx("ab.createWhat", { cmd: <code>{CREATE_CMD}</code> })}</div>
      <div className="ab-actions">
        <button
          type="button"
          className="ab-btn ab-primary"
          data-testid="addbot-create"
          disabled={check !== "ok" || busy}
          onClick={() => void create()}
        >
          {busy ? t("ab.creating", { name }) : t("ab.create")}
        </button>
      </div>
    </div>
  );
}

function TemplateRow({
  id,
  title,
  sub,
  meta,
  pick,
  onPick,
}: {
  id: string;
  title: string;
  sub: string;
  meta?: string;
  pick: string;
  onPick: (id: string) => void;
}) {
  const on = pick === id;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      className={`ab-tpl${on ? " on" : ""}`}
      data-testid={`addbot-template-${id || "none"}`}
      onClick={() => onPick(id)}
    >
      <span className="ab-n">{title}</span>
      <span className="ab-tsub">{sub}</span>
      {meta && <span className="ab-meta">{meta}</span>}
    </button>
  );
}
