// A bot's threads, nested under its row in the sidebar: each one a chat you open, not a subtask (tidy, 2026-11-16).
// A rounded card per thread (fill on hover, the open chat's fill when selected, a › on hover), a chat bubble with the
// state as a small badge on its corner (spinner, amber dot, check, x; idle has none), two lines: title and the time of
// its last activity / who said the last thing ("Kami: …", "You: …"), what it is doing now, or the question it asks.
// A thin rail from the bot's avatar with a short rounded elbow into each card keeps the hierarchy (owner, 2026-11-15).
// Two levels only: bot > thread. Hover shows x, which asks first (ConfirmRemove), then stops and archives the thread.
// No "+ New thread" line under the cards (owner, 2026-11-19: a line that is always there under the bot is too much;
// it reversed 2026-11-18). A new thread opens from the bot row's + on hover, its right-click menu, or ./thread.
import { useRef, useState } from "react";
import { askText, selectAsks, useStore, type AppState } from "../state/store";
import { busyFor, shortTime } from "../app/time";
import { useNow } from "../elsewhere/useNow";
import { plain } from "../sidebar/BotRow";
import { t } from "../i18n";
import { StatusGlyph } from "./StatusGlyph";
import { threadStatus, type ThreadStatus } from "./status";
import { threadKey, THREADS_SHOWN, type ThreadRow } from "./types";
import { ConfirmRemove } from "./ConfirmRemove";
import { HarnessStack } from "../harness/HarnessMark";
import type { HarnessFacts } from "../harness/registry";
import { subagentEnded, type Chat } from "../state/store";
import { PrMark, prMarkText, shownPrs, useRowsInView, useThreadPrs } from "./ThreadPrs";
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

/** Who works in a thread now: its subagents still out (in the running turn, or ones that outlived the last turn),
 *  as harness facts (a CLI's own name, else a Hermes child on its model). Empty when nobody is out. */
export function threadHarness(chat: Chat | undefined): HarnessFacts[] {
  if (!chat) return [];
  const turns = [chat.turn, chat.lastTurn].filter((t): t is NonNullable<typeof t> => !!t);
  const facts: HarnessFacts[] = [];
  for (const t of turns)
    for (const f of t.fanouts ?? [])
      for (const sub of f.subs) if (!subagentEnded(sub)) facts.push({ executor: sub.agent ?? null, model: sub.model ?? "hermes" });
  return facts;
}

/** A thread's second line and the time of its last activity, from what the store holds (no new reads): the question
 *  it asks, what it is doing now, else who said the last thing and what, else the bridge's preview of it. */
export function rowPreview(state: AppState, bot: string, row: ThreadRow, nowMs: number): { text: string; kind: "ask" | "live" | "said" | "none"; ts: number } {
  const key = threadKey(bot, row.thread);
  const chat = state.chats[key];
  const name = state.bots.find((b) => b.name === bot)?.display_name ?? bot;
  const items = chat?.items ?? [];
  let said: (typeof items)[number] | undefined;
  for (let i = items.length - 1; i >= 0 && !said; i -= 1) if (items[i]!.kind === "assistant" || items[i]!.kind === "user") said = items[i];
  const ts = Math.max(row.last ?? 0, row.started_at ?? 0, said?.ts ?? 0);
  const asks = selectAsks(state).filter((a) => a.bot === key);
  // plain text on every kind: an ask names its command in backticks ("Allow `pnpm build:docs`?")
  if (asks.length) return { text: plain(askText(asks[asks.length - 1]!.item)), kind: "ask", ts };
  if (chat?.turn) return { text: t("thread.working", { name, time: busyFor(nowMs - chat.turn.startedAt) }), kind: "live", ts };
  if (said && (said.kind === "assistant" || said.kind === "user")) {
    const text = plain(said.text);
    if (text) return { text: t("thread.said", { name: said.kind === "user" ? t("thread.you") : name, text }), kind: "said", ts };
  }
  const preview = row.preview ? plain(row.preview) : "";
  if (preview) return { text: t("thread.said", { name: t("thread.you"), text: preview }), kind: "said", ts };
  return { text: t("thread.empty"), kind: "none", ts };
}

/** The rows a bot's tree shows: the first THREADS_SHOWN (every one after "Show N more"), and the open thread wherever
 *  it is. */
export function shownThreads(rows: ThreadRow[], openThread: string | null, all: boolean): ThreadRow[] {
  return all || rows.length <= THREADS_SHOWN ? rows : rows.filter((r, i) => i < THREADS_SHOWN || r.thread === openThread);
}

/** The thread of `bot` open in the chat, if any. */
const openThreadOf = (state: AppState, bot: string) => (state.ui.view === "chat" && state.selectedBot === bot ? state.ui.thread : null);

/** Unread answers in the threads of `bot` that its tree does not show (past "Show N more"). Its bot row and the
 *  "Show N more" line count them, so every answer in the Dock or taskbar count has a row that shows it. */
export function hiddenThreadUnread(state: AppState, bot: string, all: boolean): number {
  const rows = state.threads[bot] ?? [];
  const shown = new Set(shownThreads(rows, openThreadOf(state, bot), all).map((r) => r.thread));
  return rows.reduce((n, r) => (shown.has(r.thread) ? n : n + (state.unread[threadKey(bot, r.thread)] ?? 0)), 0);
}

/** A speech bubble, the thread's own mark. */
function Bubble() {
  return (
    <svg className="th-bub" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3.2 2.5h9.6a1.7 1.7 0 0 1 1.7 1.7v5.6a1.7 1.7 0 0 1-1.7 1.7H7.4L4.5 13.8v-2.3H3.2a1.7 1.7 0 0 1-1.7-1.7V4.2a1.7 1.7 0 0 1 1.7-1.7Z" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinejoin="round" />
    </svg>
  );
}

/** A bot's threads (nothing when it has none). `all`: "Show N more" was pressed (the sidebar holds it, so the bot
 *  row knows which threads are out of view). */
export function ThreadTree({ bot, id, all, onAll }: { bot: string; id: string; all: boolean; onAll: (all: boolean) => void }) {
  const s = useStore();
  const rows = s.threads[bot] ?? [];
  const [asking, setAsking] = useState<{ thread: string; at: DOMRect } | null>(null);
  // a working thread's "· 2m" moves on (read before any return: the tree stays mounted from 0 threads to 1)
  const nowMs = useNow(rows.some((r) => !!s.chats[threadKey(bot, r.thread)]?.turn), 10_000);
  const name = s.bots.find((b) => b.name === bot)?.display_name ?? bot;
  const remote = !!s.bots.find((b) => b.name === bot)?.host;
  const openThread = openThreadOf(s, bot);
  // the open thread stays in view even when it is past the first five
  const shown = shownThreads(rows, openThread, all);
  // the pull request each thread produced (rule 40): rows in view are read, and their mark follows the answers
  const tree = useRef<HTMLUListElement>(null);
  const prs = useThreadPrs();
  useRowsInView(tree, bot, shown.map((r) => r.thread).join("\n"));
  if (!rows.length) return null;
  const hidden = rows.length - shown.length;
  const more = hidden > 0 || (all && rows.length > THREADS_SHOWN);
  const hiddenUnread = hiddenThreadUnread(s, bot, all);
  return (
    <ul ref={tree} className="th-tree" role="group" id={id} aria-label={t("thread.list", { name })} data-testid={`threads-${bot}`}>
      {shown.map((r, i) => {
        const st = rowStatus(s, bot, r);
        const title = r.title || t("thread.untitled");
        const last = i === shown.length - 1 && !more;
        const pv = rowPreview(s, bot, r, nowMs);
        const ts = pv.ts;
        const pr = shownPrs(s.chats[threadKey(bot, r.thread)]?.items, prs.get(bot, r.thread))[0];
        // answers the person has not read (the Dock or taskbar counts them): a count as the bot row shows one; an open
        // question takes its place, as on the bot row (the amber mark says it)
        const unread = st === "needs_you" ? 0 : (s.unread[threadKey(bot, r.thread)] ?? 0);
        const label = pr ? `${t("thread.linkOpen", { title })} · ${prMarkText(pr)}` : t("thread.linkOpen", { title });
        return (
          <li
            key={r.thread}
            role="treeitem"
            aria-level={2}
            aria-selected={openThread === r.thread}
            className={`th-row${last ? " th-last" : ""}${openThread === r.thread ? " on" : ""}${unread > 0 ? " unread" : ""}`}
            data-state={st}
            data-thread={r.thread}
            data-testid={`thread-row-${r.thread}`}
          >
            <span className="th-branch" aria-hidden="true" />
            <button
              type="button"
              className="th-open"
              onClick={() => void s.openThread(bot, r.thread)}
              aria-label={unread > 0 ? `${label} · ${t("thread.unread", { n: unread })}` : label}
              title={title}
              data-testid="thread-open"
            >
              <span className="th-ic" data-testid="thread-icon">
                <Bubble />
                <StatusGlyph status={st} />
              </span>
              <span className="th-title">{title}</span>
              {/* who works in it: ONE mark, in the time's place while it shows (the first harness out; the tooltip names
                  them all, the thread's chat shows each), so the title keeps its room at the sidebar's default width */}
              <span className="th-harness">
                <HarnessStack items={threadHarness(s.chats[threadKey(bot, r.thread)])} size={12} max={1} more={false} />
              </span>
              {ts > 0 && (
                <span className="th-time" data-testid="thread-time">
                  {shortTime(ts, nowMs)}
                </span>
              )}
              <span className={`th-sub th-sub-${pv.kind}`} data-testid="thread-sub">
                {pv.text}
              </span>
              {pr && <PrMark pr={pr} remote={remote} />}
              {unread > 0 && (
                <span className="badge th-unread" data-testid="thread-unread" aria-hidden="true">
                  {unread}
                </span>
              )}
              <span className="th-go" aria-hidden="true" data-testid="thread-go">
                <svg width="10" height="10" viewBox="0 0 10 10">
                  <path d="M3.8 2.2 6.6 5 3.8 7.8" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </button>
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
      {more && (
        <li role="none" className="th-row th-more th-last">
          <span className="th-branch" aria-hidden="true" />
          <button
            type="button"
            className="th-open"
            onClick={() => onAll(!all)}
            aria-expanded={all}
            aria-label={hiddenUnread > 0 ? `${t("thread.more", { n: hidden })} · ${t("thread.unread", { n: hiddenUnread })}` : undefined}
            data-testid="thread-more"
          >
            <span className="th-title">{all ? t("thread.less") : t("thread.more", { n: hidden })}</span>
            {hiddenUnread > 0 && (
              <span className="badge th-unread th-more-unread" data-testid="thread-more-unread" aria-hidden="true">
                {hiddenUnread}
              </span>
            )}
          </button>
        </li>
      )}
    </ul>
  );
}
