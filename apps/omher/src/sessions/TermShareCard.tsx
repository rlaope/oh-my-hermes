// The card a bot's request to type into a TERMINALS session shows on that session's terminal: "<bot> wants to type
// into <title>", the prompt as it would be typed, then Deny, Allow once and Allow for this session (the approval
// cards' order, weight and colours). Only Allow types it (termShare.ts). Several requests wait one under another.
// A session that cannot take input now (paused, ended) shows the card on its idle view with Deny and "Resume and
// send" only; a prompt that could not be typed keeps its card with a line saying so.
import { useEffect, useRef } from "react";
import { t } from "../i18n";
import { getSessions, useSessions } from "./sessions";
import { getTermShare, usePendingRequests } from "./termShare";
import "../chat/cards/cards.css";

export function TermShareCards({ sessionId, title }: { sessionId: string; title: string }) {
  const mine = usePendingRequests().filter((r) => r.sessionId === sessionId);
  useSessions(); // a session that starts or ends changes the buttons
  const live = getSessions().canType(sessionId);
  const first = useRef<HTMLDivElement>(null);
  const shown = mine[0]?.key;
  // a new card takes focus on its Deny (the first button), so a key press never allows it by accident
  useEffect(() => {
    if (shown) first.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
  }, [shown]);
  if (!mine.length) return null;
  return (
    <div className="tshare-cards" data-testid="term-share-cards">
      {mine.map((r, i) => (
        <div key={r.key} ref={i === 0 ? first : undefined} className="card tshare-card" role="alertdialog" aria-label={t("tshare.wants", { bot: r.from || "?", title })} data-testid="term-share-card" data-request={r.id}>
          <div className="card-title">{t("tshare.wants", { bot: r.from || "?", title })}</div>
          <pre className="card-cmd" data-testid="term-share-prompt">
            {r.prompt}
          </pre>
          {r.failed && (
            <span className="card-err" role="status" data-testid="term-share-failed">
              {t("tshare.notTyped")}
            </span>
          )}
          <div className="card-acts">
            <button type="button" className="card-btn soft deny" data-choice="deny" disabled={r.busy} onClick={() => void getTermShare().answer(r.key, "deny")}>
              {t("card.deny")}
            </button>
            {live ? (
              <>
                <button type="button" className="card-btn soft once" data-choice="once" onClick={() => void getTermShare().answer(r.key, "once")}>
                  {t("card.allowOnce")}
                </button>
                <button type="button" className="card-btn soft session" data-choice="session" onClick={() => void getTermShare().answer(r.key, "session")}>
                  {t("tshare.thisSession")}
                </button>
              </>
            ) : (
              <button type="button" className="card-btn soft once" data-choice="resume" disabled={r.busy} onClick={() => void getTermShare().answer(r.key, "resume")}>
                {t("tshare.resumeSend")}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
