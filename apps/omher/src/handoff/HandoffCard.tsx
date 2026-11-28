// "Handed to <bot>": the card under an answer the person handed to another bot (BOUNDARY rule 56). It follows the new
// thread's first turn (src/handoff/card.ts): working, waiting for the person there, done with that turn's answer, or
// stopped. Open thread always opens it; once done, Give to <bot> sends that answer once into this chat as the person's
// own message, from its click only (never an effect), and nothing comes back by itself. Given lasts while the row that
// carries it stands; a refused or deleted row offers Give again. A thread or bot that is gone leaves one plain line.
import { useLayoutEffect, useRef, useState } from "react";
import { chatTarget, botNames, useStore, type HandoffItem } from "../state/store";
import { t, type Key } from "../i18n";
import { Avatar, LiveRing } from "../ui";
import { koText } from "../chat/parts/textLang";
import "../chat/cards/cards.css";
import "./handoff.css";

const STOPPED: Record<string, Key> = { interrupted: "handoff.stopped", ended: "handoff.stopped" };

export function HandoffCard({ chat, item }: { chat: string; item: HandoffItem }) {
  const s = useStore();
  const [more, setMore] = useState(false);
  const [long, setLong] = useState(false);
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const to = s.bots.find((b) => b.name === item.bot);
  const origin = chatTarget(chat, botNames(s)).bot;
  const fromName = s.bots.find((b) => b.name === origin)?.display_name || origin;
  const name = to?.display_name || item.bot;
  // the bot itself went (deleted, or its computer removed): the card cannot reach the thread either
  const phase = to ? item.phase : "gone";
  useLayoutEffect(() => {
    const el = body.current;
    if (el && !more) setLong(el.scrollHeight > el.clientHeight + 1);
  }, [item.answer, more, phase]);

  const state =
    phase === "working"
      ? t("handoff.working", { bot: name })
      : phase === "waiting"
        ? t("handoff.waiting", { bot: name })
        : phase === "done"
          ? t("handoff.done", { bot: name })
          : phase === "stopped"
            ? item.error
              ? t("handoff.failed", { bot: name, error: item.error })
              : t(STOPPED[item.outcome ?? ""] ?? "handoff.ended", { bot: name, outcome: item.outcome ?? "" })
            : t("handoff.gone");
  const give = async () => {
    if (busy) return;
    setBusy(true);
    await s.handoffGive(chat, item.id);
    setBusy(false);
  };
  return (
    <div className="card hf-card" role="group" aria-label={t("handoff.card", { bot: name })} data-testid="handoff-card" data-state={phase} data-thread={item.thread} data-bot={item.bot}>
      <div className="card-title hf-title">
        <LiveRing on={phase === "working"} size={18} gap={2} seed={item.bot}>
          <Avatar bot={item.bot} size={18} />
        </LiveRing>
        <span>{t("handoff.card", { bot: name })}</span>
      </div>
      <div className={`hf-state${phase === "waiting" ? " wait" : ""}`} aria-live="polite" data-testid="handoff-state">
        {state}
      </div>
      {phase === "done" && item.answer ? (
        <>
          <div ref={body} className={`hf-answer${more ? " open" : ""}`} lang={koText(item.answer)} data-testid="handoff-answer">
            {item.answer}
          </div>
          {(long || more) && (
            <button type="button" className="hf-more" aria-expanded={more} onClick={() => setMore(!more)} data-testid="handoff-more">
              {more ? t("handoff.less") : t("handoff.more")}
            </button>
          )}
        </>
      ) : phase === "done" ? (
        <div className="hf-state" data-testid="handoff-answer-none">
          {t("handoff.noText", { bot: name })}
        </div>
      ) : null}
      {phase !== "gone" && (
        <div className="card-acts">
          <button type="button" className="card-btn soft" onClick={() => void s.openThread(item.bot, item.thread)} data-testid="handoff-open">
            {t("handoff.open")}
          </button>
          {phase === "done" && item.answer && (
            <button type="button" className="card-btn primary" disabled={!!item.given || busy} onClick={() => void give()} data-testid="handoff-give">
              {item.given ? t("handoff.given") : t("handoff.give", { bot: fromName })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
