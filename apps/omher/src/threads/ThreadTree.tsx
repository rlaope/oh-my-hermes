// A bot's threads, nested under its row in the sidebar the way Discord nests threads under a channel: indented,
// joined to the bot by a thin line that drops from the avatar column with a rounded elbow into each row (the last
// row gets the elbow only). Two levels only: bot > thread. One line per thread: state glyph, title, time; hover
// shows x, which asks first (ConfirmRemove) and then stops and archives the thread in Hermes.
import { useState } from "react";
import { selectAsks, useStore, type AppState } from "../state/store";
import { shortTime } from "../app/time";
import { t } from "../i18n";
import { StatusGlyph } from "./StatusGlyph";
import { threadStatus, type ThreadStatus } from "./status";
import { threadKey, THREADS_SHOWN, type ThreadRow } from "./types";
import { ConfirmRemove } from "./ConfirmRemove";
import "./threads.css";

/** A thread's state from what the store holds: its chat (turn, last turn, open asks) and the bridge's list row. */
export function rowStatus(state: AppState, bot: string, row: ThreadRow): ThreadStatus {
  const key = threadKey(bot, row.thread);
  const chat = state.chats[key];
  const asks = selectAsks(state).filter((a) => a.bot === key).length;
  return threadStatus({
    running: chat ? !!chat.turn : row.running,
    asks: chat ? asks : row.needs ? 1 : 0,
    lastOutcome: chat?.lastTurn?.outcome ?? null,
  });
}

export function ThreadTree({ bot, id }: { bot: string; id: string }) {
  const s = useStore();
  const rows = s.threads[bot] ?? [];
  const [all, setAll] = useState(false);
  const [asking, setAsking] = useState<{ thread: string; at: DOMRect } | null>(null);
  if (!rows.length) return null;
  const openThread = s.ui.view === "chat" && s.selectedBot === bot ? s.ui.thread : null;
  // the open thread stays in view even when it is past the first five
  const shown = all || rows.length <= THREADS_SHOWN ? rows : rows.filter((r, i) => i < THREADS_SHOWN || r.thread === openThread);
  const hidden = rows.length - shown.length;
  const name = s.bots.find((b) => b.name === bot)?.display_name ?? bot;
  return (
    <ul className="th-tree" role="group" id={id} aria-label={t("thread.list", { name })} data-testid={`threads-${bot}`}>
      {shown.map((r, i) => {
        const st = rowStatus(s, bot, r);
        const title = r.title || t("thread.untitled");
        const last = i === shown.length - 1 && hidden === 0;
        const ts = r.last ?? r.started_at;
        return (
          <li
            key={r.thread}
            role="treeitem"
            aria-level={2}
            aria-selected={openThread === r.thread}
            className={`th-row${last ? " th-last" : ""}${openThread === r.thread ? " on" : ""}`}
            data-state={st}
            data-thread={r.thread}
            data-testid={`thread-row-${r.thread}`}
          >
            <span className="th-branch" aria-hidden="true" />
            <button type="button" className="th-open" onClick={() => void s.openThread(bot, r.thread)} title={title} data-testid="thread-open">
              <StatusGlyph status={st} />
              <span className="th-title">{title}</span>
              {ts > 0 && <span className="th-time">{shortTime(ts)}</span>}
            </button>
            <span className="th-harness" />
            <button
              type="button"
              className="th-x"
              aria-label={t("thread.remove", { title })}
              title={t("thread.remove", { title })}
              data-testid="thread-x"
              onClick={(e) => setAsking({ thread: r.thread, at: e.currentTarget.getBoundingClientRect() })}
            >
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                <path d="M2.5 2.5 7.5 7.5M7.5 2.5 2.5 7.5" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              </svg>
            </button>
            {asking?.thread === r.thread && (
              <ConfirmRemove
                at={asking.at}
                running={st === "running" || st === "needs_you"}
                onCancel={() => setAsking(null)}
                onConfirm={async () => {
                  try {
                    await s.removeThread(bot, r.thread);
                  } catch (e) {
                    s.systemNote(t("thread.removeFailed", { error: e instanceof Error ? e.message : String((e as { message?: string })?.message ?? e) }), bot);
                  }
                  setAsking(null);
                }}
              />
            )}
          </li>
        );
      })}
      {(hidden > 0 || (all && rows.length > THREADS_SHOWN)) && (
        <li role="none" className="th-row th-more th-last">
          <span className="th-branch" aria-hidden="true" />
          <button type="button" className="th-open" onClick={() => setAll((v) => !v)} aria-expanded={all} data-testid="thread-more">
            <span className="th-title">{all ? t("thread.less") : t("thread.more", { n: hidden })}</span>
          </button>
        </li>
      )}
    </ul>
  );
}
