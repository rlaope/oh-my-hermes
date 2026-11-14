// Settings › Remote machines: each computer omher reaches over SSH, its host and link state, Retry for a failed
// link and Remove (asks once). Adding one is the same card as the sidebar's Connect over SSH.
import { useState } from "react";
import { t } from "../i18n";
import { AttachCard } from "./AttachCard";
import { linkText, SshIcon } from "./SshMarker";
import { removePeer, retryPeer, usePeers } from "./links";
import "./peers.css";

export function RemoteMachines() {
  const peers = usePeers();
  const [asking, setAsking] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");
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
              {p.state === "failed" && p.kind === "auth" && <code className="peer-cmd sm">ssh-copy-id {p.host}</code>}
            </div>
            <div className="st-v peer-acts">
              {asking === p.id ? (
                <>
                  <span className="peer-ask">{t("peer.removeAsk", { label: p.label })}</span>
                  <button type="button" className="st-btn" onClick={() => setAsking(null)} data-testid={`remote-keep-${p.id}`}>
                    {t("update.cancel")}
                  </button>
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
      </div>
      {err && <p className="peer-warn" role="alert">{err}</p>}
      {adding && <AttachCard seed={{}} onClose={() => setAdding(false)} />}
    </div>
  );
}
