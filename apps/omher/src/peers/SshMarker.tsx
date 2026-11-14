// The SSH marker for a bot on another computer: a small terminal glyph and `SSH · <label>`, the host in its tooltip,
// and (when the link is not up) the link's state in words. The same marker sits on the sidebar row, the chat header,
// Settings' bot cards and the bot's own page; a bot on this computer shows nothing.
import type { Bot } from "../lib/protocol";
import { t } from "../i18n";
import { usePeer } from "./links";
import { failKey, type PeerStatus } from "./host";
import "./peers.css";

export const SshIcon = ({ size = 11 }: { size?: number }) => (
  <svg className="ssh-ic" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="1.75" y="2.75" width="12.5" height="10.5" rx="2" />
    <path d="M4.5 6.25 6.5 8l-2 1.75M8.25 10h3" />
  </svg>
);

/** The link's state in words: "" while connected; `short` is the marker's few words, the long one the sentence. */
export function linkText(st: PeerStatus | undefined, short = false): string {
  if (!st || st.state === "connected") return "";
  if (st.state === "connecting") return t("peer.connecting");
  if (st.state === "reconnecting") return t("peer.reconnecting");
  if (st.state === "failed") return short ? t(st.kind === "auth" ? "peer.short.auth" : "peer.short.failed") : t(failKey(st.kind), { host: st.host });
  return "";
}

/** `SSH · Mac mini`, tooltip `sionic@10.1.145.204`; `full` adds the link state after it. */
export function SshMarker({ bot, full = false, testId }: { bot: Pick<Bot, "host">; full?: boolean; testId?: string }) {
  const h = bot.host;
  const st = usePeer(h?.peer);
  if (!h) return null;
  const state = st?.state ?? "connected";
  const words = linkText(st, true);
  const tip = [t("peer.tip", { host: h.host }), linkText(st), st?.reason].filter(Boolean).join("\n");
  return (
    <span className={`ssh-mark ${state}`} title={tip} data-testid={testId ?? "ssh-mark"} data-state={state}>
      <SshIcon />
      <span className="ssh-k">SSH</span>
      <span className="ssh-sep">{" · "}</span>
      <span className="ssh-l">{h.label}</span>
      {full && words && <span className="ssh-st">{words}</span>}
    </span>
  );
}
