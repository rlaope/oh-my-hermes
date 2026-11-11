// Approval and clarify cards (timeline slot "cards"). While open: a small card with buttons. Once answered
// (or once its turn is over, or the gateway gave up on it) it collapses to one gray line.
//
// Keys, only while the card has focus (never global): on an approval 1 / 2 / 3 = Deny / Allow once / Allow for
// session; on a question Enter picks the focused choice or sends the text. The sidebar's Needs-you strip and ⌘J
// scroll a card into view and focus it.
import "./cards.css";
import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import type { SlotProps } from "../../features";
import type { ApprovalChoice, ClarifyAnswers, ClarifyQuestion } from "../../lib/protocol";
import { askOpen, getStore, useStore, type ApprovalItem, type AskExpiry, type ClarifyItem } from "../../state/store";
import { answerOf, EMPTY, type Pick } from "./answers";
import { riskOf } from "./risk";
import { t, type Key } from "../../i18n";
import { holdImeEnter } from "../../lib/ime";

export const slot = "cards";

const ALLOW_LABEL: Record<ApprovalChoice, Key> = {
  once: "card.allowedOnce",
  session: "card.allowedSession",
  always: "card.allowedAlways",
  deny: "card.denied",
};

const EXPIRED_LABEL: Record<AskExpiry, Key> = {
  timeout: "card.timedOut",
  resolved: "card.answeredElsewhere",
  cancelled: "card.notAnswered",
};

/** Buttons in display order; only those the request offers are shown. All carry the same weight: the card
 *  never nudges toward allowing (a `rm -rf` must not have a bright "Allow" next to a faint "Deny"). Deny comes
 *  first so the left-most, first-tabbed answer is the safe one. `key` is its number while the card has focus. */
const BUTTONS: { choice: ApprovalChoice; label: Key; key: string }[] = [
  { choice: "deny", label: "card.deny", key: "1" },
  { choice: "once", label: "card.allowOnce", key: "2" },
  { choice: "session", label: "card.allowSession", key: "3" },
];

/** Cards already scrolled to for a given focus request, so a re-mount does not steal focus again. */
const handled = new Set<number>();

/** Scrolls the card into view and focuses it when the Needs-you strip or ⌘J asked for it. */
function useFocusRequest(bot: string, id: string, ref: RefObject<HTMLElement | null>, open: boolean) {
  const req = useStore().ui.focusAsk;
  useEffect(() => {
    if (!open || !req || req.bot !== bot || req.id !== id || handled.has(req.seq)) return;
    const el = ref.current;
    if (!el) return;
    handled.add(req.seq);
    el.scrollIntoView({ block: "center" });
    el.focus({ preventScroll: true });
  }, [req, bot, id, open, ref]);
}

/** Runs a respond action. The store only marks the card answered after the bridge said ok, so a card that is
 *  still open afterwards failed; returns the store's error text then. */
async function respond(bot: string, id: string, run: () => Promise<void>): Promise<string | null> {
  await run();
  const st = getStore().getState();
  const it = st.chats[bot]?.items.find((i) => i.id === id);
  const done = it?.kind === "approval" ? !!it.resolved : it?.kind === "clarify" ? it.answer !== undefined : true;
  return done ? null : st.lastError || t("card.notTaken");
}

function Line({ icon, text, detail, testid }: { icon: string; text: string; detail?: string; testid: string }) {
  return (
    <div className="line card-line" data-testid={testid}>
      <span className="line-ic">{icon}</span>
      <span className="line-t">
        {text}
        {detail && <span className="card-line-d"> · {detail}</span>}
      </span>
    </div>
  );
}

function useOpen(bot: string, item: ApprovalItem | ClarifyItem): boolean {
  const items = useStore().chats[bot]?.items ?? [];
  return askOpen(items, item);
}

function Approval({ bot, item }: { bot: string; item: ApprovalItem }) {
  const s = useStore();
  const open = useOpen(bot, item);
  const [busy, setBusy] = useState<ApprovalChoice | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useFocusRequest(bot, item.id, ref, open);

  if (item.resolved) {
    const denied = item.resolved === "deny";
    return <Line icon={denied ? "✕" : "✓"} text={t(ALLOW_LABEL[item.resolved])} detail={item.command || item.title} testid="card-line" />;
  }
  if (item.expired && !busy) return <Line icon="–" text={t(EXPIRED_LABEL[item.expired])} detail={item.command || item.title} testid="card-line" />;
  if (!open && !busy) return <Line icon="–" text={t("card.notAnswered")} detail={item.command || item.title} testid="card-line" />;

  const pick = async (choice: ApprovalChoice) => {
    if (busy) return;
    setBusy(choice);
    setErr(null);
    const e = await respond(bot, item.id, () => s.respondApproval(item.request_id, choice, bot));
    setErr(e);
    setBusy(null);
  };
  const shown = BUTTONS.filter((b) => item.choices.includes(b.choice));
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
    const b = shown.find((x) => x.key === e.key);
    if (!b) return;
    e.preventDefault();
    void pick(b.choice);
  };

  const risks = riskOf(item.command || "");
  return (
    <div
      ref={ref}
      tabIndex={-1}
      className={`card${risks.length ? " risky" : ""}`}
      data-testid="card-approval"
      role="group"
      aria-label={item.title}
      aria-keyshortcuts={shown.map((b) => b.key).join(" ")}
      onKeyDown={onKey}
    >
      <div className="card-title">{item.title || t("card.approvalNeeded")}</div>
      {risks.length > 0 && (
        <div className="card-risk" data-testid="card-risk" role="note">
          <span className="card-risk-ic" aria-hidden="true">!</span>
          {risks.join(" · ")}
        </div>
      )}
      {item.command && <pre className="card-cmd">{item.command}</pre>}
      {item.cwd && (
        <div className="card-cwd" title={item.cwd} data-testid="card-cwd">
          {t("card.inCwd", { cwd: item.cwd })}
        </div>
      )}
      <div className="card-acts">
        {shown.map((b) => (
          <button key={b.choice} type="button" className="card-btn soft" disabled={!!busy} onClick={() => void pick(b.choice)}>
            {t(b.label)}
          </button>
        ))}
        <span className="card-keys" aria-hidden="true">
          {shown.map((b) => b.key).join(" · ")}
        </span>
        {err && <span className="card-err">{t("card.notSent", { error: err })}</span>}
      </div>
    </div>
  );
}


/** One question's choices as chips (gray when selected) plus a free-text "Other", or just the text field. The
 *  "Other…" chip looks like its siblings and, once clicked, opens a text field as wide as the chip row (the same
 *  for single and multi select); emptied and left, it folds back into the chip. */
function QuestionInput({
  q,
  pick,
  disabled,
  onChange,
  index,
}: {
  q: ClarifyQuestion;
  pick: Pick;
  disabled: boolean;
  onChange: (p: Pick) => void;
  index: number;
}) {
  const choices = q.choices?.filter((c) => c.trim()) ?? [];
  const multi = !!q.multi_select && choices.length > 0;
  const [otherOpen, setOtherOpen] = useState(false);
  const toggle = (c: string) => {
    const on = pick.chosen.includes(c);
    if (multi) onChange({ ...pick, chosen: on ? pick.chosen.filter((x) => x !== c) : [...pick.chosen, c] });
    else onChange({ chosen: on ? [] : [c], other: "" });
  };
  if (!choices.length) {
    return (
      <input
        className="card-in iv-in"
        value={pick.other}
        disabled={disabled}
        placeholder={t("card.answerOpt")}
        aria-label={t("card.answerN", { n: index + 1 })}
        onChange={(e) => onChange({ chosen: [], other: e.target.value })}
      />
    );
  }
  const showOther = otherOpen || !!pick.other;
  return (
    <div className="iv-chips" role={multi ? "group" : "radiogroup"} aria-label={q.question}>
      {/* the Other chip stays in the row (pressed while its field is open); the field takes the next line */}
      {choices.map((c) => {
        const on = pick.chosen.includes(c);
        return (
          <button
            key={c}
            type="button"
            className={`iv-chip${on ? " on" : ""}`}
            role={multi ? "checkbox" : "radio"}
            aria-checked={on}
            disabled={disabled}
            onClick={() => toggle(c)}
          >
            {multi && <span className="iv-box" aria-hidden="true">{on ? "✓" : ""}</span>}
            {c}
          </button>
        );
      })}
      <button
        type="button"
        className={`iv-chip iv-more${showOther ? " open" : ""}${pick.other.trim() ? " on" : ""}`}
        aria-expanded={showOther}
        disabled={disabled}
        onClick={() => setOtherOpen(true)}
      >
        {multi && <span className="iv-box" aria-hidden="true">{pick.other.trim() ? "✓" : ""}</span>}
        {t("card.other")}
      </button>
      {showOther && (
        <input
          className="card-in iv-in iv-other"
          value={pick.other}
          disabled={disabled}
          autoFocus={otherOpen && !pick.other}
          placeholder={multi ? t("card.otherMulti") : t("card.otherOne")}
          aria-label={t("card.otherN", { n: index + 1 })}
          onChange={(e) => onChange({ chosen: multi ? pick.chosen : [], other: e.target.value })}
          onBlur={() => {
            if (!pick.other.trim()) setOtherOpen(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !pick.other) {
              e.stopPropagation();
              setOtherOpen(false);
            }
          }}
        />
      )}
    </div>
  );
}

/** Several questions at once (Hermes' clarify with 2-5 questions): numbered, all answered with one Submit.
 *  Questions left blank go back as skipped. */
function Interview({ bot, item, cardRef }: { bot: string; item: ClarifyItem; cardRef: RefObject<HTMLFormElement | null> }) {
  const s = useStore();
  const qs = item.questions ?? [];
  const [picks, setPicks] = useState<Record<string, Pick>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const answers = (): ClarifyAnswers =>
    Object.fromEntries(qs.map((q) => [q.qid, answerOf(picks[q.qid] ?? EMPTY, !!q.multi_select && !!q.choices?.length)]));
  const given = Object.values(answers()).filter((v) => v !== null).length;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    const a = answers();
    const e = await respond(bot, item.id, () => s.respondClarify(item.request_id, a, bot));
    setErr(e);
    setBusy(false);
  };

  return (
    <form
      ref={cardRef}
      tabIndex={-1}
      className="card iv"
      onKeyDown={holdImeEnter}
      data-testid="card-interview"
      role="group"
      aria-label={t("card.questions", { n: qs.length })}
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <div className="card-title">{t("card.questions", { n: qs.length })}</div>
      <ol className="iv-list">
        {qs.map((q, i) => (
          <li key={q.qid} className="iv-q" data-testid="iv-question">
            <div className="iv-text">
              <span className="iv-n">{i + 1}</span>
              {q.question}
              {q.choices?.length ? <span className="iv-hint"> · {q.multi_select ? t("card.pickAny") : t("card.pickOne")}</span> : null}
            </div>
            <QuestionInput
              q={q}
              index={i}
              pick={picks[q.qid] ?? EMPTY}
              disabled={busy}
              onChange={(p) => setPicks((cur) => ({ ...cur, [q.qid]: p }))}
            />
          </li>
        ))}
      </ol>
      <div className="card-acts">
        <button type="submit" className="card-btn primary" disabled={busy}>
          {t("card.submit")}
        </button>
        <span className="iv-count" data-testid="iv-count">
          {t("card.answered", { given, n: qs.length })}
          {given < qs.length ? t("card.skipped", { n: qs.length - given }) : ""}
        </span>
        {err && <span className="card-err">{t("card.notSent", { error: err })}</span>}
      </div>
    </form>
  );
}

function Clarify({ bot, item }: { bot: string; item: ClarifyItem }) {
  const s = useStore();
  const open = useOpen(bot, item);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const interview = (item.questions?.length ?? 0) > 1;
  useFocusRequest(bot, item.id, interview ? formRef : ref, open);

  const detail = interview ? t("card.questions", { n: item.questions!.length }) : item.question;
  if (item.answer !== undefined) return <Line icon="✓" text={t("card.answeredWith", { answer: item.answer })} detail={detail} testid="card-line" />;
  if (item.expired && !busy) return <Line icon="–" text={t(EXPIRED_LABEL[item.expired])} detail={detail} testid="card-line" />;
  if (!open && !busy) return <Line icon="–" text={t("card.notAnswered")} detail={detail} testid="card-line" />;
  if (interview) return <Interview bot={bot} item={item} cardRef={formRef} />;

  const answer = async (a: string) => {
    if (!a.trim() || busy) return;
    setBusy(true);
    setErr(null);
    const e = await respond(bot, item.id, () => s.respondClarify(item.request_id, a.trim(), bot));
    setErr(e);
    setBusy(false);
  };
  const choices = item.choices?.filter((c) => c.trim()) ?? [];
  const multi = !!item.multi && choices.length > 0;

  return (
    <div ref={ref} tabIndex={-1} className="card" data-testid="card-clarify" role="group" aria-label={t("card.question")}>
      <div className="card-title">{item.question}</div>
      <div className="card-acts">
        {multi ? (
          <>
            {choices.map((c) => {
              const on = chosen.includes(c);
              return (
                <button
                  key={c}
                  type="button"
                  role="checkbox"
                  aria-checked={on}
                  className={`iv-chip${on ? " on" : ""}`}
                  disabled={busy}
                  onClick={() => setChosen((cur) => (on ? cur.filter((x) => x !== c) : [...cur, c]))}
                >
                  <span className="iv-box" aria-hidden="true">{on ? "✓" : ""}</span>
                  {c}
                </button>
              );
            })}
            <button
              type="button"
              className="card-btn soft"
              disabled={busy || !chosen.length}
              onClick={() => void answer(JSON.stringify(chosen))}
            >
              {t("card.answer")}
            </button>
          </>
        ) : choices.length > 0 ? (
          choices.map((c) => (
            <button key={c} type="button" className="iv-chip" disabled={busy} onClick={() => void answer(c)}>
              {c}
            </button>
          ))
        ) : (
          <form
            className="card-ask"
            onKeyDown={holdImeEnter}
            onSubmit={(e) => {
              e.preventDefault();
              void answer(text);
            }}
          >
            <input
              className="card-in"
              value={text}
              disabled={busy}
              placeholder={t("card.yourAnswer")}
              aria-label={t("card.yourAnswer")}
              onChange={(e) => setText(e.target.value)}
            />
            <button type="submit" className="card-btn soft" disabled={busy || !text.trim()}>
              {t("card.answer")}
            </button>
          </form>
        )}
        {err && <span className="card-err">{t("card.notSent", { error: err })}</span>}
      </div>
    </div>
  );
}

export default function Cards({ bot, item }: SlotProps["cards"]) {
  return item.kind === "approval" ? <Approval bot={bot} item={item} /> : <Clarify bot={bot} item={item} />;
}
