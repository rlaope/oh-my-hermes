// Approval and clarify cards (timeline slot "cards"). While open: a small card with buttons. Once answered
// (or once its turn is over without an answer) it collapses to one gray line.
import "./cards.css";
import { useState } from "react";
import type { SlotProps } from "../../features";
import type { ApprovalChoice } from "../../lib/protocol";
import { getStore, useStore, type ApprovalItem, type ClarifyItem } from "../../state/store";

export const slot = "cards";

const ALLOW_LABEL: Record<ApprovalChoice, string> = {
  once: "Allowed once",
  session: "Allowed for session",
  always: "Always allowed",
  deny: "Denied",
};

/** Buttons in display order; only those the request offers are shown. All carry the same weight: the card
 *  never nudges toward allowing (a `rm -rf` must not have a bright "Allow" next to a faint "Deny"). Deny comes
 *  first so the left-most, first-tabbed answer is the safe one. */
const BUTTONS: { choice: ApprovalChoice; label: string; cls: string }[] = [
  { choice: "deny", label: "Deny", cls: "soft" },
  { choice: "once", label: "Allow once", cls: "soft" },
  { choice: "session", label: "Allow for session", cls: "soft" },
];

/** False once the turn that raised the card is over (the request expired unanswered). A card raised outside
 *  any known turn stays open. */
function useOpen(bot: string, ts: number): boolean {
  const items = useStore().chats[bot]?.items ?? [];
  let owner: number | undefined;
  for (const i of items) if (i.kind === "activity" && i.turn.startedAt <= ts * 1000 + 1) owner = i.turn.endedAt ?? -1;
  return owner === undefined || owner === -1;
}

/** Runs a respond action. The store only marks the card answered after the bridge said ok, so a card that is
 *  still open afterwards failed; returns the store's error text then. */
async function respond(bot: string, id: string, run: () => Promise<void>): Promise<string | null> {
  await run();
  const st = getStore().getState();
  const it = st.chats[bot]?.items.find((i) => i.id === id);
  const done = it?.kind === "approval" ? !!it.resolved : it?.kind === "clarify" ? it.answer !== undefined : true;
  return done ? null : st.lastError || "the bridge did not take it";
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

function Approval({ bot, item }: { bot: string; item: ApprovalItem }) {
  const s = useStore();
  const open = useOpen(bot, item.ts);
  const [busy, setBusy] = useState<ApprovalChoice | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (item.resolved) {
    const denied = item.resolved === "deny";
    return <Line icon={denied ? "✕" : "✓"} text={ALLOW_LABEL[item.resolved]} detail={item.command || item.title} testid="card-line" />;
  }
  if (!open && !busy) return <Line icon="–" text="Not answered" detail={item.command || item.title} testid="card-line" />;

  const pick = async (choice: ApprovalChoice) => {
    setBusy(choice);
    setErr(null);
    const e = await respond(bot, item.id, () => s.respondApproval(item.request_id, choice, bot));
    setErr(e);
    setBusy(null);
  };

  return (
    <div className="card" data-testid="card-approval" role="group" aria-label={item.title}>
      <div className="card-title">{item.title || "Approval needed"}</div>
      {item.command && <pre className="card-cmd">{item.command}</pre>}
      <div className="card-acts">
        {BUTTONS.filter((b) => item.choices.includes(b.choice)).map((b) => (
          <button
            key={b.choice}
            type="button"
            className={`card-btn ${b.cls}`}
            disabled={!!busy}
            onClick={() => void pick(b.choice)}
          >
            {b.label}
          </button>
        ))}
        {err && <span className="card-err">Not sent · {err}</span>}
      </div>
    </div>
  );
}

function Clarify({ bot, item }: { bot: string; item: ClarifyItem }) {
  const s = useStore();
  const open = useOpen(bot, item.ts);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");

  if (item.answer !== undefined) return <Line icon="✓" text={`Answered: ${item.answer}`} detail={item.question} testid="card-line" />;
  if (!open && !busy) return <Line icon="–" text="Not answered" detail={item.question} testid="card-line" />;

  const answer = async (a: string) => {
    if (!a.trim() || busy) return;
    setBusy(true);
    setErr(null);
    const e = await respond(bot, item.id, () => s.respondClarify(item.request_id, a.trim(), bot));
    setErr(e);
    setBusy(false);
  };
  const choices = item.choices?.filter((c) => c.trim()) ?? [];

  return (
    <div className="card" data-testid="card-clarify" role="group" aria-label="Question">
      <div className="card-title">{item.question}</div>
      <div className="card-acts">
        {choices.length > 0 ? (
          choices.map((c) => (
            <button key={c} type="button" className="card-btn soft" disabled={busy} onClick={() => void answer(c)}>
              {c}
            </button>
          ))
        ) : (
          <form
            className="card-ask"
            onSubmit={(e) => {
              e.preventDefault();
              void answer(text);
            }}
          >
            <input
              className="card-in"
              value={text}
              disabled={busy}
              placeholder="Your answer"
              aria-label="Your answer"
              onChange={(e) => setText(e.target.value)}
            />
            <button type="submit" className="card-btn soft" disabled={busy || !text.trim()}>
              Answer
            </button>
          </form>
        )}
        {err && <span className="card-err">Not sent · {err}</span>}
      </div>
    </div>
  );
}

export default function Cards({ bot, item }: SlotProps["cards"]) {
  return item.kind === "approval" ? <Approval bot={bot} item={item} /> : <Clarify bot={bot} item={item} />;
}
