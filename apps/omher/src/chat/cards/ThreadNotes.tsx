// Under a bot's main-chat answer: what its ```omher-thread``` / ```omher-thread-route``` blocks became.
// - ThreadLinkLine: "→ thread: <title>", one per thread the bot opened (or a message the person sent there); a click
//   opens the thread.
// - ThreadRouteCard: "Send this to <title>?" [Send there] [Keep here]. Nothing moves until Send there; Keep here only
//   closes the card. Once answered it collapses to one gray line.
import "./cards.css";
import { useState } from "react";
import { useStore, type ThreadLinkItem, type ThreadRouteItem } from "../../state/store";
import { t } from "../../i18n";

export function ThreadLinkLine({ item }: { item: ThreadLinkItem }) {
  const s = useStore();
  return (
    <button
      type="button"
      className="line card-line th-link"
      data-testid="thread-link"
      data-thread={item.thread}
      onClick={() => void s.openThread(item.bot, item.thread)}
      title={t("thread.linkOpen", { title: item.title })}
    >
      <span className="line-ic" aria-hidden="true">
        →
      </span>
      <span className="line-t">
        {t("thread.link")} <span className="th-link-t">{item.title}</span>
      </span>
    </button>
  );
}

export function ThreadRouteCard({ item }: { item: ThreadRouteItem }) {
  const s = useStore();
  const [busy, setBusy] = useState(false);
  if (item.done) {
    return (
      <div className="line card-line" data-testid="thread-route-done">
        <span className="line-ic">{item.done === "sent" ? "→" : "·"}</span>
        <span className="line-t">{item.done === "sent" ? t("thread.routeSent", { title: item.title }) : t("thread.routeKept")}</span>
      </div>
    );
  }
  const answer = async (choice: "send" | "keep") => {
    if (busy) return;
    setBusy(true);
    await s.answerRoute(item.bot, item.id, choice);
    setBusy(false);
  };
  return (
    <div className="card th-route" role="group" aria-label={t("thread.routeAsk", { title: item.title })} data-testid="thread-route" data-thread={item.thread}>
      <div className="card-title">{t("thread.routeAsk", { title: item.title })}</div>
      <div className="th-route-text" title={item.text}>
        {item.text}
      </div>
      <div className="card-acts">
        <button type="button" className="card-btn soft" disabled={busy} onClick={() => void answer("send")} data-testid="thread-route-send">
          {t("thread.routeSend")}
        </button>
        <button type="button" className="card-btn soft" disabled={busy} onClick={() => void answer("keep")} data-testid="thread-route-keep">
          {t("thread.routeKeep")}
        </button>
        {item.error && <span className="card-err">{t("card.notSent", { error: item.error })}</span>}
      </div>
    </div>
  );
}
