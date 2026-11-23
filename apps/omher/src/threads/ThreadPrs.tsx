// A thread's pull requests on screen (rule 40; the logic is prs.ts): the compact mark on its sidebar row, the card
// under the answer that named each one, and the app's one reader of `thread.prs`. A card opens the PR's page only on
// the person's click, through the app's one external opener (rule 22). Everything GitHub said is shown as a fixed
// word from this app's own dictionary; the repository and number come from the validated link, as plain text.
import { useEffect, useSyncExternalStore, type RefObject } from "react";
import { getStore, notifyEnabled, type ChatItem } from "../state/store";
import { showNote, windowWatched } from "../lib/notify";
import { openExternal } from "../lib/openExternal";
import { PrIcon } from "../ui/PrIcon";
import { t } from "../i18n";
import { createThreadPrs, namedPrs, storedTold, withState, type PrEntry, type ThreadPr, type ThreadPrs } from "./prs";

let single: ThreadPrs | null = null;

/** The app's one reader: `thread.prs` through the store, a bot on another computer never asked, the notification
 *  for a failing head unless the person looks at that thread. */
export function getThreadPrs(): ThreadPrs {
  if (single) return single;
  const store = getStore();
  const prs = createThreadPrs({
    read: (bot, thread, fresh) => store.actions.threadPrs(bot, thread, fresh),
    remote: (bot) => !!store.getState().bots.find((b) => b.name === bot)?.host,
    now: () => Date.now(),
    told: storedTold(),
    notify({ bot, thread, pr }) {
      const st = store.getState();
      if (!notifyEnabled()) return;
      // a thread removed while its read was under way never rings
      if (!(st.threads[bot] ?? []).some((r) => r.thread === thread)) return;
      if (windowWatched() && st.ui.view === "chat" && st.selectedBot === bot && st.ui.thread === thread) return;
      const row = (st.threads[bot] ?? []).find((r) => r.thread === thread);
      const title = row?.title || t("thread.untitled");
      void showNote(
        { title: t("note.prFailing", { thread: title, n: pr.number }), body: pr.repo, bot, tag: `${bot}:${thread}:pr` },
        () => void store.actions.openThread(bot, thread),
        true,
      );
    },
  });
  store.actions.onBridgeEvent((ev) => {
    // the bot may have just named a pull request in this thread
    if (ev.event === "turn.end" && ev.session && (store.getState().threads[ev.bot] ?? []).some((r) => r.thread === ev.session))
      prs.read(ev.bot, ev.session, "turn");
    const removed = ev as unknown as { event: string; bot: string; thread?: string };
    if (removed.event === "thread.removed" && removed.thread) prs.forget(removed.bot, removed.thread);
  });
  single = prs;
  return prs;
}

/** Re-renders on any answer; returns the reader. */
export function useThreadPrs(): ThreadPrs {
  const p = getThreadPrs();
  useSyncExternalStore(p.subscribe, p.version, p.version);
  return p;
}

/** What a thread shows: the PRs its loaded transcript names (newest first) with the bridge's word on each, else, for a
 *  thread not read yet, the bridge's own list. A bot on another computer: the transcript's numbers, no state. */
export function shownPrs(items: readonly ChatItem[] | undefined, entry: PrEntry | undefined): ThreadPr[] {
  const named = items ? namedPrs(items as readonly { kind: string; id?: string; text?: string }[]) : [];
  if (named.length) return withState(named, entry?.prs);
  return entry?.prs ?? [];
}

/** "#12 · Open · Checks failing", "#12" while the state is not known. Checks only for an open PR or a draft. */
export function prMarkText(pr: ThreadPr): string {
  if (pr.state === "unknown") return `#${pr.number}`;
  const live = pr.state === "open" || pr.state === "draft";
  return [`#${pr.number}`, t(`pr.${pr.state}`), live && pr.checks !== "none" ? t(`pr.checks.${pr.checks}`) : ""].filter(Boolean).join(" · ");
}

/** Why a PR shows no state: a bot on another computer, the bridge's per-minute cap (asked again shortly), or gh. */
const unknownWhy = (pr: ThreadPr, remote: boolean) => t(remote ? "pr.remote" : pr.limited ? "pr.limited" : "pr.unknown");

/** The checks' mark: a check, an x, or a dot while they run. */
function ChecksMark({ checks }: { checks: ThreadPr["checks"] }) {
  if (checks === "none") return null;
  return (
    <svg className="pr-ck" data-checks={checks} width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
      {checks === "passing" && <path d="M2 5.2 4.1 7.3 8 2.9" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />}
      {checks === "failing" && <path d="M2.6 2.6 7.4 7.4M7.4 2.6 2.6 7.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />}
      {checks === "running" && <circle cx="5" cy="5" r="2.6" fill="currentColor" />}
    </svg>
  );
}

/** The sidebar row's mark: the newest PR's state mark, its number and its checks. */
export function PrMark({ pr, remote }: { pr: ThreadPr; remote: boolean }) {
  const live = pr.state === "open" || pr.state === "draft";
  return (
    <span
      className="th-pr"
      data-testid="thread-pr"
      data-state={pr.state}
      data-checks={live ? pr.checks : "none"}
      title={pr.state === "unknown" ? `${prMarkText(pr)} · ${unknownWhy(pr, remote)}` : prMarkText(pr)}
    >
      <PrIcon state={pr.state} size={11} />
      <span className="th-pr-n">#{pr.number}</span>
      {live && <ChecksMark checks={pr.checks} />}
    </span>
  );
}

/** Under the answer that named it: the PR's repository, number, state and checks; a click opens its page in the
 *  browser, Refresh asks GitHub again. */
export function ThreadPrCard({ pr, remote, busy, onRefresh }: { pr: ThreadPr; remote: boolean; busy: boolean; onRefresh: () => void }) {
  const live = pr.state === "open" || pr.state === "draft";
  const label = `#${pr.number}`;
  return (
    <div className="th-prc" role="group" aria-label={t("pr.card", { pr: label, repo: pr.repo })} data-testid="thread-pr-card" data-state={pr.state} data-checks={live ? pr.checks : "none"}>
      <button type="button" className="th-prc-open" onClick={() => void openExternal(pr.url).catch(() => {})} title={t("pr.onGithub", { pr: label })} data-testid="thread-pr-open">
        <PrIcon state={pr.state} size={14} />
        <span className="th-prc-n">{label}</span>
        <span className="th-prc-repo">{pr.repo}</span>
        {pr.state !== "unknown" && <span className="th-prc-state">{t(`pr.${pr.state}`)}</span>}
        {live && pr.checks !== "none" && (
          <span className="th-prc-checks" data-checks={pr.checks}>
            <ChecksMark checks={pr.checks} />
            {t(`pr.checks.${pr.checks}`)}
          </span>
        )}
        {pr.state === "unknown" && <span className="th-prc-none">{unknownWhy(pr, remote)}</span>}
      </button>
      {!remote && (
        <button type="button" className="th-prc-refresh" onClick={onRefresh} disabled={busy} aria-label={t("pr.refresh", { pr: label })} title={t("pr.refresh", { pr: label })} data-testid="thread-pr-refresh">
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path d="M10 6a4 4 0 1 1-1.2-2.85M10 1.8v2.4H7.6" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}
    </div>
  );
}

/** The thread rows of `bot` inside `ref` that are in view are read (once, then on the slow background tick while
 *  they stay in view); `ids` changes when the rows shown change. */
export function useRowsInView(ref: RefObject<HTMLElement | null>, bot: string, ids: string) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !ids) return;
    const p = getThreadPrs();
    const off = new Map<string, () => void>();
    const rows = [...el.querySelectorAll<HTMLElement>("li[data-thread]")];
    const on = (id: string) => {
      if (!off.has(id)) off.set(id, p.show(bot, id));
    };
    if (typeof IntersectionObserver === "undefined") {
      for (const r of rows) on(r.dataset.thread!);
      return () => off.forEach((f) => f());
    }
    const io = new IntersectionObserver((seen) => {
      for (const e of seen) {
        const id = (e.target as HTMLElement).dataset.thread!;
        if (e.isIntersecting) on(id);
        else {
          off.get(id)?.();
          off.delete(id);
        }
      }
    });
    for (const r of rows) io.observe(r);
    return () => {
      io.disconnect();
      off.forEach((f) => f());
    };
  }, [ref, bot, ids]);
}
