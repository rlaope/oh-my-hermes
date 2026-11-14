// Add-a-bot popover from the sidebar `+`. "Connect a Hermes profile" lists every profile the bridge sees
// with its status; Connect attaches that profile's gateway (one read: models.options) and re-reads
// bots.list. Nothing is copied or created on disk. "Create a new bot" is not in v0.1.
import { useEffect, useState } from "react";
import "./addbot.css";
import type { SlotProps } from "../features";
import type { Bot } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { Avatar, Popover, Spinner } from "../ui";
import { connectProfile, refreshBots } from "./bots";
import { t } from "../i18n";
import { statusText } from "../settings/Settings.slot";
import { SshIcon } from "../peers/SshMarker";
import { isRemote } from "../peers/peerKey";

export const slot = "addBot";


export default function AddBot({ onClose, onSsh }: SlotProps["addBot"]) {
  const s = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});
  const local = s.bots.filter((b) => !isRemote(b));

  useEffect(() => {
    void refreshBots(getStore()).catch(() => undefined);
  }, []);

  const connect = async (b: Bot) => {
    setBusy(b.name);
    setFailed((f) => ({ ...f, [b.name]: "" }));
    try {
      const after = await connectProfile(getStore(), b.name);
      if (after?.status === "offline") setFailed((f) => ({ ...f, [b.name]: t("ab.couldNotStart") }));
    } catch (e) {
      const msg = typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);
      setFailed((f) => ({ ...f, [b.name]: msg }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Popover open onClose={onClose} align="left" width={272} label={t("ab.label")} className="ab-pop">
      <div data-testid="addbot">
        <div className="ab-h">{t("ab.title")}</div>
        <p className="ab-sub">{t("ab.sub")}</p>
        <div className="ab-list" data-testid="addbot-list">
          {local.length === 0 && <div className="ab-empty">{t("ab.none")}</div>}
          {local.map((b) => {
            const err = failed[b.name];
            return (
              <div key={b.name} className="ab-row" data-testid={`addbot-${b.name}`}>
                <Avatar bot={b.name} size={22} />
                <span className="ab-m">
                  <span className="ab-n">{b.display_name}</span>
                  <span className="ab-s" title={err || undefined}>
                    <i className={`ab-dot ${b.status}`} aria-hidden="true" />
                    {err ? t("ab.failed") : statusText(b.status)}
                    <span className="ab-p"> · {b.name}</span>
                  </span>
                </span>
                {b.status !== "online" &&
                  (busy === b.name ? (
                    <Spinner size={12} label={t("ab.connecting")} />
                  ) : (
                    <button
                      type="button"
                      className="ab-btn"
                      onClick={() => void connect(b)}
                      disabled={busy !== null || b.status === "starting"}
                    >
                      {t("ab.connect")}
                    </button>
                  ))}
              </div>
            );
          })}
        </div>
        <div className="ab-sep" />
        {/* a Hermes on another computer: the same confirm card a bot's draft opens */}
        <button type="button" className="ab-new ab-ssh" onClick={() => (onClose(), onSsh?.())} data-testid="addbot-ssh">
          <SshIcon size={12} />
          <span className="ab-m">
            <span className="ab-n">{t("ab.ssh")}</span>
            <span className="ab-s">{t("ab.sshSub")}</span>
          </span>
        </button>
        <button type="button" className="ab-new" disabled title={t("ab.later")} data-testid="addbot-create">
          {t("ab.create")}
          <span className="ab-soon">{t("set.soon")}</span>
        </button>
      </div>
    </Popover>
  );
}
