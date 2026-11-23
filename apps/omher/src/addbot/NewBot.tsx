// Add bot › New bot (BOUNDARY rule 43): pick one of OMH's bot templates (or none), name the bot, press Create. The
// bridge runs Hermes' own `hermes -p default profile create <name>` and reads back the folder Hermes made; omher writes
// nothing in the profile. With a template, the new bot's main chat gets one message (applyMessage) and the bot applies
// it with its own tools and approvals, every schedule paused. A bot that cannot see the template skill yet (OMH reaches
// a new profile on the next `omh update`) waits for the person's Apply template.
import { useEffect, useState } from "react";
import type { BotTemplate, BotTemplates } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { t, tx, type Key } from "../i18n";
import { Spinner } from "../ui";
import { addToList, withBridge } from "./bots";
import { APPLY_SKILL, applyMessage, checkName, normalizeName, type NameCheck } from "./templates";

const CREATE_CMD = "hermes profile create";
const UPDATE_CMD = "omh update";

type Step =
  | { kind: "form"; line?: string }
  | { kind: "creating" }
  | { kind: "waiting"; bot: string; template: string; again?: boolean };

const NAME_LINE: Record<Exclude<NameCheck, "ok" | "empty">, Key> = {
  rule: "ab.nameRule",
  reserved: "ab.nameReserved",
  taken: "ab.nameTaken",
};

/** Whether the bot's own skill folders hold the template skill (rule 19's read, `skills.list`). */
async function hasApplySkill(bot: string): Promise<boolean> {
  const { skills } = await withBridge((b) => b.request("skills.list", { bot }));
  return skills.some((s) => s.name === APPLY_SKILL);
}

export function NewBot({ onBack, onDone }: { onBack: () => void; onDone: () => void }) {
  const s = useStore();
  const [list, setList] = useState<BotTemplates | null>(null);
  const [pick, setPick] = useState<string>("");
  const [raw, setRaw] = useState("");
  const [step, setStep] = useState<Step>({ kind: "form" });

  useEffect(() => {
    let live = true;
    withBridge((b) => b.request("bots.templates", {}))
      .then((r) => live && setList(r))
      .catch(() => live && setList({ omh: "failed", templates: [] }));
    return () => {
      live = false;
    };
  }, []);

  const name = normalizeName(raw);
  const taken = s.bots.filter((b) => !b.host).map((b) => b.name);
  const check = checkName(name, taken);
  const busy = step.kind === "creating";

  const send = async (bot: string, template: string) => {
    await getStore().actions.sendTo(bot, applyMessage(template));
    onDone();
  };

  const create = async () => {
    if (check !== "ok" || busy) return;
    const template = pick;
    setStep({ kind: "creating" });
    try {
      const r = await withBridge((b) => b.request("bots.create", { name }));
      if (r.outcome !== "ok" || !r.bot) {
        setStep({ kind: "form", line: r.line || t("ab.createFailed") });
        return;
      }
      const bot = r.bot;
      if (!template) {
        await addToList(getStore(), bot);
        onDone();
        return;
      }
      const ready = await hasApplySkill(bot).catch(() => false);
      await addToList(getStore(), bot, { open: ready });
      if (ready) await send(bot, template);
      else setStep({ kind: "waiting", bot, template });
    } catch (e) {
      setStep({ kind: "form", line: (e as { message?: string })?.message || t("ab.createFailed") });
    }
  };

  const applyNow = async (bot: string, template: string) => {
    const ready = await hasApplySkill(bot).catch(() => false);
    if (ready) await send(bot, template);
    else setStep({ kind: "waiting", bot, template, again: true });
  };

  if (step.kind === "waiting") {
    const { bot, template } = step;
    return (
      <div className="ab-new" data-testid="addbot-waiting">
        <div className="ab-h">{t("ab.new")}</div>
        <div className="ab-line">
          {tx(step.again ? "ab.stillNoSkill" : "ab.needOmh", { name: bot, cmd: <code>{UPDATE_CMD}</code> })}
        </div>
        <div className="ab-hint">{tx("ab.orSend", { msg: <code>{applyMessage(template)}</code> })}</div>
        <div className="ab-actions">
          <button type="button" className="ab-btn" onClick={() => void (getStore().actions.selectBot(bot), onDone())}>
            {t("ab.openChat")}
          </button>
          <button type="button" className="ab-btn ab-primary" data-testid="addbot-apply" onClick={() => void applyNow(bot, template)}>
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
            {list.omh === "missing"
              ? t("ab.omhMissing")
              : list.omh === "old"
                ? tx("ab.omhOld", { cmd: <code>{UPDATE_CMD}</code> })
                : t("ab.omhFailed", { line: list.line ?? "" })}
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
