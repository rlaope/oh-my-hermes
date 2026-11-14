// The "Connect over SSH" chips under a bot reply that holds `omher-peer` drafts (draft.ts): one compact chip per
// draft. A click opens the same confirm card as the sidebar's Connect over SSH (AttachCard), filled from the draft,
// with one more quiet line naming the bot that proposed it. Only that card's Connect writes. A draft that fails its
// check shows its chip disabled, the reason in the tooltip and on the chip.
import { useMemo, useState } from "react";
import { t } from "../i18n";
import { getStore } from "../state/store";
import { AttachCard } from "./AttachCard";
import { parsePeerDrafts, peerDraftsAllowed, type PeerDraftBlock } from "./draft";
import { SshIcon } from "./SshMarker";
import "./peers.css";

/** The chips for reply `text` in chat `chatKey`; nothing outside a bot's main chat. */
export function PeerChips({ chatKey, text }: { chatKey: string; text: string }) {
  const blocks = useMemo(() => (peerDraftsAllowed(chatKey) && text.includes("omher-peer") ? parsePeerDrafts(text) : []), [chatKey, text]);
  if (blocks.length === 0) return null;
  return (
    <div className="peer-chips" data-testid="peer-chips">
      {blocks.map((b, i) => (
        <PeerChip key={i} chatKey={chatKey} block={b} />
      ))}
    </div>
  );
}

function PeerChip({ chatKey, block }: { chatKey: string; block: PeerDraftBlock }) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(false);
  const why = block.why ? t(`peer.why.${block.why}` as const) : "";
  const by = getStore().getState().bots.find((b) => b.name === chatKey)?.display_name || chatKey;
  return (
    <>
      <button
        type="button"
        className="peer-chip"
        disabled={!!why || done}
        title={why || t("peer.chipTip", { host: block.draft?.host ?? "" })}
        onClick={() => setOpen(true)}
        data-testid="peer-chip"
        data-why={block.why ?? undefined}
      >
        <SshIcon />
        <span className="peer-chip-t">{done ? t("peer.chipDone") : t("peer.chip")}</span>
        {block.draft?.label && <span className="peer-chip-k">{block.draft.label}</span>}
        {why && <span className="peer-chip-why">{why}</span>}
      </button>
      {open && block.draft && !why && (
        <AttachCard seed={{ ...block.draft, by }} onClose={() => setOpen(false)} onDone={() => setDone(true)} />
      )}
    </>
  );
}
