// The "Add agent" chips under a bot reply that holds `omher-agent` drafts (agentDraft.ts): one compact chip per
// draft, the reply chips' look. A click asks the shell to check the draft again (stricter than the form: no shell,
// interpreter or built-in program) and opens Settings › Agents' own confirm card (AgentConfirmCard) with one more
// quiet line naming the bot that proposed it. Only that card's Add writes, through the same one call the form uses.
// A draft that fails its check shows its chip disabled, the form's refusal in the tooltip.
import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import "../../settings/settings.css";
import { AgentConfirmCard } from "../../settings/agents/AgentsPage";
import { getHost } from "../../sessions/host";
import { getSessions } from "../../sessions/sessions";
import { whyText, type CustomPreview } from "../../sessions/custom";
import { getStore } from "../../state/store";
import { t } from "../../i18n";
import { draftBot, draftsAllowed, parseDrafts, type DraftBlock } from "./agentDraft";

/** The chips for reply `text` in chat `chatKey`; nothing outside a bot's main chat or a Hermes folder chat. */
export function AgentChips({ chatKey, text }: { chatKey: string; text: string }) {
  const blocks = useMemo(() => (draftsAllowed(chatKey) && text.includes("omher-agent") ? parseDrafts(text) : []), [chatKey, text]);
  if (blocks.length === 0) return null;
  return (
    <div className="agent-chips" data-testid="agent-chips">
      {blocks.map((b, i) => (
        <AgentChip key={i} chatKey={chatKey} block={b} />
      ))}
    </div>
  );
}

function AgentChip({ chatKey, block }: { chatKey: string; block: DraftBlock }) {
  const [card, setCard] = useState<CustomPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [added, setAdded] = useState(false);
  const refusal = block.why ? whyText(`why:${block.why}`) : err;

  /** The chip: the shell checks the draft again and resolves the command; nothing is written. */
  const preview = async () => {
    const d = block.draft;
    if (!d || block.why) return;
    setBusy(true);
    try {
      const p = await getHost().customBotPreview(d.name, d.program, d.args, d.install);
      const bot = draftBot(chatKey);
      setCard({ ...p, by: getStore().getState().bots.find((b) => b.name === bot)?.display_name || bot });
      setErr("");
    } catch (e) {
      setErr(whyText(e));
    } finally {
      setBusy(false);
    }
  };
  /** The card's Add: the one call that writes. */
  const add = async () => {
    if (!card) return;
    setBusy(true);
    try {
      await getHost().customConfirm(card.entry);
      setCard(null);
      setAdded(true);
      await getSessions().loadAgents();
    } catch (e) {
      setCard(null);
      setErr(whyText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        type="button"
        className="agent-chip"
        disabled={busy || added || !!refusal}
        title={refusal || t("ag.chipTip")}
        onClick={() => void preview()}
        data-testid="agent-chip"
        data-why={block.why ?? undefined}
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        <span className="agent-chip-t">{added ? t("ag.added") : t("ag.add")}</span>
        {block.draft?.name && <span className="agent-chip-k">{block.draft.name}</span>}
      </button>
      {card && createPortal(<AgentConfirmCard card={card} busy={busy} onCancel={() => setCard(null)} onAdd={() => void add()} />, document.body)}
    </>
  );
}
