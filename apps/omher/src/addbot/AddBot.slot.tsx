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

export const slot = "addBot";

const STATUS: Record<string, string> = { online: "Connected", offline: "Not connected", starting: "Starting…" };

export default function AddBot({ onClose }: SlotProps["addBot"]) {
  const s = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});

  useEffect(() => {
    void refreshBots(getStore()).catch(() => undefined);
  }, []);

  const connect = async (b: Bot) => {
    setBusy(b.name);
    setFailed((f) => ({ ...f, [b.name]: "" }));
    try {
      const after = await connectProfile(getStore(), b.name);
      if (after?.status === "offline") setFailed((f) => ({ ...f, [b.name]: "Hermes could not start it" }));
    } catch (e) {
      const msg = typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);
      setFailed((f) => ({ ...f, [b.name]: msg }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Popover open onClose={onClose} align="left" width={272} label="Add a bot" className="ab-pop">
      <div data-testid="addbot">
        <div className="ab-h">Connect a Hermes profile</div>
        <p className="ab-sub">Each Hermes profile is one bot. Nothing is copied.</p>
        <div className="ab-list" data-testid="addbot-list">
          {s.bots.length === 0 && <div className="ab-empty">No Hermes profiles found</div>}
          {s.bots.map((b) => {
            const err = failed[b.name];
            return (
              <div key={b.name} className="ab-row" data-testid={`addbot-${b.name}`}>
                <Avatar bot={b.name} size={22} />
                <span className="ab-m">
                  <span className="ab-n">{b.display_name}</span>
                  <span className="ab-s" title={err || undefined}>
                    <i className={`ab-dot ${b.status}`} aria-hidden="true" />
                    {err ? "Could not connect" : STATUS[b.status] ?? b.status}
                    <span className="ab-p"> · {b.name}</span>
                  </span>
                </span>
                {b.status !== "online" &&
                  (busy === b.name ? (
                    <Spinner size={12} label="Connecting" />
                  ) : (
                    <button
                      type="button"
                      className="ab-btn"
                      onClick={() => void connect(b)}
                      disabled={busy !== null || b.status === "starting"}
                    >
                      Connect
                    </button>
                  ))}
              </div>
            );
          })}
        </div>
        <div className="ab-sep" />
        <button type="button" className="ab-new" disabled title="Coming in a later version" data-testid="addbot-create">
          Create a new bot<span className="ab-soon">Soon</span>
        </button>
      </div>
    </Popover>
  );
}
