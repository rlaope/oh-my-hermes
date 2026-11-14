// Add-a-bot popover from the sidebar `+`. It lists the Hermes profiles on this computer that are not in the sidebar
// yet (the roster, store.ts), each with one Add: the bot joins the list, its chat opens and its gateway is attached
// (addToList in bots.ts). Nothing is copied, created or deleted on disk.
import { useEffect } from "react";
import "./addbot.css";
import type { SlotProps } from "../features";
import { getStore, selectUnlisted, useStore } from "../state/store";
import { Avatar, Popover } from "../ui";
import { addToList, refreshBots } from "./bots";
import { t, tx } from "../i18n";
import { SshIcon, SshMarker } from "../peers/SshMarker";

/** Hermes' own command for a new profile (a new bot); omher never runs it. */
const NEW_PROFILE = "hermes profile create <name>";

export const slot = "addBot";

export default function AddBot({ onClose, onSsh }: SlotProps["addBot"]) {
  const s = useStore();
  const others = selectUnlisted(s);

  useEffect(() => {
    void refreshBots(getStore()).catch(() => undefined);
  }, []);

  return (
    <Popover open onClose={onClose} align="left" width={272} label={t("ab.label")} className="ab-pop">
      <div data-testid="addbot">
        <div className="ab-h">{t("ab.label")}</div>
        <div className="ab-list" data-testid="addbot-list">
          {others.length === 0 && (
            <div className="ab-empty" data-testid="addbot-empty">
              <span>{s.bots.length ? t("ab.allHere") : t("ab.none")}</span>
              <span className="ab-hint">{tx("ab.newHint", { cmd: <code>{NEW_PROFILE}</code> })}</span>
            </div>
          )}
          {others.map((b) => (
            <div key={b.name} className="ab-row" data-testid={`addbot-${b.name}`}>
              <Avatar bot={b.name} size={22} />
              <span className="ab-m">
                <span className="ab-n">
                  {b.display_name}
                  {b.host && <SshMarker bot={b} testId={`addbot-ssh-${b.name}`} />}
                </span>
                <span className="ab-s">{b.model || b.name}</span>
              </span>
              <button
                type="button"
                className="ab-btn"
                aria-label={t("ab.addOf", { name: b.display_name })}
                onClick={() => {
                  onClose();
                  void addToList(getStore(), b.name);
                }}
              >
                {t("ab.add")}
              </button>
            </div>
          ))}
        </div>
        <div className="ab-sep" />
        {/* a Hermes on another computer: the same confirm card a bot's draft opens (the sidebar holds it) */}
        <button type="button" className="ab-ssh" onClick={() => (onClose(), onSsh?.())} data-testid="addbot-ssh">
          <SshIcon size={13} />
          <span className="ab-m">
            <span className="ab-n">{t("ab.ssh")}</span>
            <span className="ab-s">{t("ab.sshSub")}</span>
          </span>
        </button>
      </div>
    </Popover>
  );
}
