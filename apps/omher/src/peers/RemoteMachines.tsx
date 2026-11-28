// Settings › Remote machines: each computer omher reaches over SSH, its host and link state, Retry for a failed
// link and Remove (asks once). Adding one is the same card as the sidebar's Connect over SSH.
// Under the host, a line with when the link last came up and, while it waits to reconnect, when the next try is;
// History opens the link's last few events (connected, dropped and why, retrying in N s, stopped), newest first, as
// the shell keeps them in memory.
import { useState } from "react";
import { t } from "../i18n";
import { busyFor } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { AttachCard } from "./AttachCard";
import { linkText, SshIcon } from "./SshMarker";
import { removePeer, retryPeer, usePeers } from "./links";
import type { LinkEvent, PeerStatus } from "./host";
import { useServerMode } from "../app/remote";
import "./peers.css";

/** "now" under 10 s, else "3m ago". */
function ago(at: number, now: number): string {
  const ms = Math.max(0, now - at);
  return ms < 10_000 ? t("time.nowShort") : t("peer.ago", { t: busyFor(ms) });
}

function eventText(e: LinkEvent): string {
  if (e.what === "retrying") return t("peer.ev.retrying", { n: e.wait ?? 0 });
  return t(`peer.ev.${e.what}` as const);
}

/** When a link that is down was last connected: its last drop after it came up (`dropped` in its history). When
 *  the history (8 events) no longer holds the drop, the oldest event kept after it came up, the nearest time known;
 *  with no history after it, when it came up. */
function lastConnected(p: PeerStatus & { connected_at: number }): number {
  const after = (p.events ?? []).filter((e) => e.at >= p.connected_at && e.what !== "connected");
  const drop = after.filter((e) => e.what === "dropped").at(-1);
  return drop?.at ?? after[0]?.at ?? p.connected_at;
}

/** The row's detail line: the next try while reconnecting, then how long it has been up, or how long ago it was last
 *  connected (from its drop, not from when it came up). */
export function linkLine(p: PeerStatus, now: number): string {
  const bits: string[] = [];
  if (p.state === "reconnecting" && p.retry_at) bits.push(t("peer.nextTry", { t: busyFor(Math.max(0, p.retry_at - now)) }));
  if (p.connected_at) {
    const up = p.state === "connected";
    const since = busyFor(Math.max(0, now - (up ? p.connected_at : lastConnected({ ...p, connected_at: p.connected_at }))));
    bits.push(up ? t("peer.upFor", { t: since }) : t("peer.lastUp", { t: since }));
  }
  return bits.join(" · ");
}

export function RemoteMachines() {
  const peers = usePeers();
  const [asking, setAsking] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  // a countdown ticks each second; "up for" and "ago" every ten
  const now = useNow(peers.some((p) => !!p.connected_at || !!p.events?.length), peers.some((p) => p.state === "reconnecting" && !!p.retry_at) ? 1000 : 10_000);
  // on a server (rule 47) other computers are that server's to reach: no peer link starts from here
  const remote = useServerMode().mode === "remote";
  return (
    <div className="peer-set" data-testid="remote-machines">
      <div className="st-gh">{t("peer.machines")}</div>
      <div className="st-grp">
        {peers.length === 0 && (
          <div className="st-row">
            <div className="st-k">
              <b>{t("peer.noMachines")}</b>
              <span>{t("peer.noMachinesHint")}</span>
            </div>
          </div>
        )}
        {peers.map((p) => (
          <div className="st-row peer-row" key={p.id} data-testid={`remote-${p.id}`} data-state={p.state}>
            <div className="st-k">
              <b className="st-kt">
                <SshIcon size={12} />
                {p.label}
              </b>
              <span className="peer-row-h">
                <code>{p.host}{p.port ? `:${p.port}` : ""}</code>
                <i className={`peer-dot ${p.state}`} aria-hidden="true" />
                {linkText(p) || t("peer.connected")}
              </span>
              {(linkLine(p, now) || !!p.events?.length) && (
                <span className="peer-row-l" data-testid={`remote-line-${p.id}`}>
                  {linkLine(p, now)}
                  {!!p.events?.length && (
                    <button
                      type="button"
                      className="peer-hist-b"
                      aria-expanded={open === p.id}
                      onClick={() => setOpen(open === p.id ? null : p.id)}
                      data-testid={`remote-history-${p.id}`}
                    >
                      {t("peer.history")} ({p.events.length})
                    </button>
                  )}
                </span>
              )}
              {open === p.id && !!p.events?.length && (
                <ol className="peer-hist" data-testid={`remote-events-${p.id}`}>
                  {[...p.events].reverse().map((e, i) => (
                    <li key={`${e.at}-${i}`} data-what={e.what}>
                      <span className="peer-hist-t">{ago(e.at, now)}</span>
                      <span className="peer-hist-w">{eventText(e)}</span>
                      {e.reason && <span className="peer-line">{e.reason}</span>}
                    </li>
                  ))}
                </ol>
              )}
              {p.state === "failed" && p.kind === "auth" && <code className="peer-cmd sm">ssh-copy-id {p.host}</code>}
            </div>
            <div className="st-v peer-acts">
              {asking === p.id ? (
                <>
                  <span className="peer-ask">{t("peer.removeAsk", { label: p.label })}</span>
                  <button
                    type="button"
                    className="st-btn peer-danger"
                    onClick={() => {
                      setAsking(null);
                      void removePeer(p.id).catch((e) => setErr(String((e as { message?: string })?.message ?? e)));
                    }}
                    data-testid={`remote-remove-yes-${p.id}`}
                  >
                    {t("peer.remove")}
                  </button>
                  <button type="button" className="st-btn" onClick={() => setAsking(null)} data-testid={`remote-keep-${p.id}`}>
                    {t("update.cancel")}
                  </button>
                </>
              ) : (
                <>
                  {p.state === "failed" && (
                    <button type="button" className="st-btn" onClick={() => void retryPeer(p.id)} data-testid={`remote-retry-${p.id}`}>
                      {t("peer.retry")}
                    </button>
                  )}
                  <button type="button" className="st-btn" onClick={() => setAsking(p.id)} data-testid={`remote-remove-${p.id}`}>
                    {t("peer.remove")}
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
        {remote ? (
          <div className="st-row" data-testid="remote-add-off">
            <div className="st-k">
              <span>{t("remote.noPeers")}</span>
            </div>
          </div>
        ) : (
          <div className="st-row">
            <div className="st-k">
              <b>{t("peer.add")}</b>
              <span>{t("peer.addHint")}</span>
            </div>
            <div className="st-v">
              <button type="button" className="st-btn" onClick={() => setAdding(true)} data-testid="remote-add">
                {t("peer.title")}
              </button>
            </div>
          </div>
        )}
      </div>
      {err && <p className="peer-warn" role="alert">{err}</p>}
      {adding && !remote && <AttachCard seed={{}} onClose={() => setAdding(false)} />}
    </div>
  );
}
