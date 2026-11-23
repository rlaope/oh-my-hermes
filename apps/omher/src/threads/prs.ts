// The pull requests a thread produced (BOUNDARY rule 40): the bridge finds the full PR links in the bot's own answers
// of a thread and asks the person's own `gh` for each one's state and checks (`thread.prs`); this file decides when
// to ask, keeps the answers, and says which thread waits on failing checks. It only shows: it never changes a
// thread's run state and never starts, steers or stops anything.
//
// When a thread is read (never on a tight loop):
//   - when the person opens it, after a turn of it ends, and on the card's Refresh (which asks GitHub again);
//   - when its sidebar row comes into view, unless it was read in the last 5 minutes;
//   - on a 60 s tick, again every 5 minutes at the soonest, while its row is in view or it is in Needs you, only
//     while a PR it named is open, a draft, or not known. The tick runs while omher's window is hidden too (rule 36
//     keeps the app running), so a PR that starts failing can still notify. After a failed read (the bridge refused,
//     or gh could say nothing about any of its PRs) the wait doubles each time, up to an hour; an answer the bridge
//     held back for its per-minute cap (`limited`) is no failure and is asked again a minute later.
//   - at most two reads at a time; a thread already waiting or being read is not asked twice.
// A bot on another computer (an SSH peer) is never asked: thread reads stay on this computer (rule 31), so its
// threads show the number from the transcript with no state.
//
// Notifications (`mayRing`): at most one per failing head commit of a PR, and never two for the same PR within 6
// hours (a PR whose head GitHub did not give: the 6 hours alone), kept across restarts in this computer's storage
// (`omher.prNotified`: the newest 200 head keys and 200 PR times). Seen while the person looks at that thread, it is
// counted as told. No Dock count.
import type { PrState } from "../lib/runs";

export type PrChecks = "passing" | "failing" | "running" | "none";
const STATES: readonly PrState[] = ["open", "merged", "closed", "draft", "unknown"];
const CHECKS: readonly PrChecks[] = ["passing", "failing", "running", "none"];

export interface PrRef {
  number: number;
  repo: string;
  url: string;
}

export interface ThreadPr extends PrRef {
  state: PrState;
  checks: PrChecks;
  /** The head commit's id (40 hex), when GitHub gave one. Never shown; it only keys the one notification. */
  head?: string;
  /** Not asked: the bridge's per-minute cap was reached. No state, but not a failure either. */
  limited?: boolean;
}

/** The bridge's THREAD_PR_URL, the same strictness: https only, the host exactly github.com, nothing glued before it,
 *  a number of 1-7 digits with no leading zero, and no further path segment. */
const LINK = /(?<![A-Za-z0-9.@/-])https:\/\/github\.com\/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\/([A-Za-z0-9_.-]{1,100})\/pull\/([1-9][0-9]{0,6})(?![A-Za-z0-9_/])/g;

/** At most this many PRs per thread (the bridge reads the same three). */
export const THREAD_PRS_MAX = 3;
/** Background re-read of a visible row, and the soonest a row coming back into view is read again. */
export const PR_REREAD_MS = 5 * 60_000;
/** The longest wait after failed reads. */
export const PR_BACKOFF_MAX_MS = 60 * 60_000;
/** Reads in flight at once. */
export const PR_READS_AT_ONCE = 2;
/** How often the visible rows are looked over, and the wait after an answer held back by the bridge's cap. */
export const PR_TICK_MS = 60_000;
/** The least time between two notifications for the same PR. */
export const PR_RING_GAP_MS = 6 * 3600_000;

export const prKey = (p: Pick<PrRef, "repo" | "number">) => `${p.repo}#${p.number}`;

/** Every valid PR link in `text`, in order. */
export function prLinksIn(text: string): PrRef[] {
  const out: PrRef[] = [];
  for (const m of text.matchAll(LINK)) {
    if (m[2] === "." || m[2] === "..") continue;
    const repo = `${m[1]}/${m[2]}`;
    const number = Number(m[3]);
    out.push({ number, repo, url: `https://github.com/${repo}/pull/${number}` });
  }
  return out;
}

type Said = { kind: string; id?: string; text?: string };

const named = new WeakMap<readonly Said[], (PrRef & { at: string })[]>();

/** The newest PRs the bot named in `items` (its answers only, never the person's words), newest first, each once,
 *  with the id of the answer that last named each. Kept per `items` array (the store makes a new one on a change). */
export function namedPrs(items: readonly Said[], max = THREAD_PRS_MAX): (PrRef & { at: string })[] {
  if (max === THREAD_PRS_MAX) {
    const hit = named.get(items);
    if (hit) return hit;
  }
  const seen = new Map<string, PrRef & { at: string }>();
  for (const it of items) {
    if (it.kind !== "assistant" || typeof it.text !== "string" || !it.id) continue;
    for (const ref of prLinksIn(it.text)) {
      const k = prKey(ref);
      seen.delete(k);
      seen.set(k, { ...ref, at: it.id });
    }
  }
  const out = [...seen.values()].reverse().slice(0, max);
  if (max === THREAD_PRS_MAX) named.set(items, out);
  return out;
}

/** The bridge's answer as this page trusts it: a known state and checks word, the canonical URL for that repo and
 *  number, a 40-hex head; anything else dropped. The bridge already checked; this keeps what reaches the UI closed. */
export function cleanPrs(raw: unknown): ThreadPr[] {
  if (!Array.isArray(raw)) return [];
  const out: ThreadPr[] = [];
  for (const r of raw.slice(0, THREAD_PRS_MAX)) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    const [ref] = typeof o.url === "string" ? prLinksIn(` ${o.url} `) : [];
    if (!ref || ref.url !== o.url || ref.repo !== o.repo || ref.number !== o.number) continue;
    const state = STATES.includes(o.state as PrState) ? (o.state as PrState) : "unknown";
    const checks = CHECKS.includes(o.checks as PrChecks) ? (o.checks as PrChecks) : "none";
    const head = typeof o.head === "string" && /^[0-9a-f]{40}$/.test(o.head) ? o.head : undefined;
    const limited = state === "unknown" && o.limited === true;
    out.push({ ...ref, state, checks, ...(head ? { head } : {}), ...(limited ? { limited } : {}) });
  }
  return out;
}

/** `refs` with what the bridge said about each (same repo and number); one it has not read shows no state. */
export function withState<R extends PrRef>(refs: readonly R[], read: readonly ThreadPr[] | null | undefined): (R & ThreadPr)[] {
  const by = new Map((read ?? []).map((p) => [prKey(p), p]));
  return refs.map((r) => {
    const got = by.get(prKey(r));
    return {
      ...r,
      state: got?.state ?? "unknown",
      checks: got?.checks ?? "none",
      ...(got?.head ? { head: got.head } : {}),
      ...(got?.limited ? { limited: true } : {}),
    };
  });
}

/** The newest PR that is open (not a draft) with failing checks: the thread's Needs reason; null when none. */
export const failingPr = <P extends ThreadPr>(prs: readonly P[]): P | null => prs.find((p) => p.state === "open" && p.checks === "failing") ?? null;

/** A failing head: the PR and its head commit (`?` when GitHub gave none). */
export const failKey = (p: ThreadPr) => `${prKey(p)}@${p.head ?? "?"}`;

/** What has rung: the failing heads (newest last) and when each PR last rang (ms). */
export interface Told {
  heads: string[];
  prs: Record<string, number>;
}
const TOLD_MAX = 200;

/** Whether failing `p` rings now, and the record after it. Once per failing head (a head seen counts even when the
 *  6 hours keep it quiet, so it never rings later); never twice for the same PR within PR_RING_GAP_MS; a PR with no
 *  head: the 6 hours alone. Pure. */
export function mayRing(t: Told, p: ThreadPr, now: number): { ring: boolean; told: Told } {
  const head = p.head ? failKey(p) : null;
  if (head && t.heads.includes(head)) return { ring: false, told: t };
  const heads = head ? [...t.heads, head].slice(-TOLD_MAX) : t.heads;
  const last = t.prs[prKey(p)];
  if (last !== undefined && now - last < PR_RING_GAP_MS) return { ring: false, told: heads === t.heads ? t : { heads, prs: t.prs } };
  const prs = Object.fromEntries(
    Object.entries({ ...t.prs, [prKey(p)]: now })
      .sort((a, b) => a[1] - b[1])
      .slice(-TOLD_MAX),
  );
  return { ring: true, told: { heads, prs } };
}

/** Worth asking again in the background: a PR that may still change (open, draft) or whose state is not known. */
export const mayChange = (prs: readonly ThreadPr[]) => prs.some((p) => p.state === "open" || p.state === "draft" || p.state === "unknown");

/** The wait before the next background read after `failures` failed reads in a row. */
export const nextDelay = (failures: number) => Math.min(PR_REREAD_MS * 2 ** Math.max(0, failures), PR_BACKOFF_MAX_MS);

export interface PrEntry {
  /** null until the first answer */
  prs: ThreadPr[] | null;
  /** ms of the last answer (or failure) */
  at: number;
  failures: number;
  /** some PR was held back by the bridge's cap: asked again on the next tick */
  limited?: boolean;
}

/** A failed read: the bridge refused, or gh could say nothing about any of the thread's PRs (an answer held back by
 *  the cap is not one; one PR gh cannot read beside others it can is not one either). */
export const readFailed = (prs: readonly ThreadPr[]) => prs.length > 0 && prs.every((p) => p.state === "unknown" && !p.limited);

export interface FailingThread {
  bot: string;
  thread: string;
  pr: ThreadPr;
}

export interface ThreadPrDeps {
  read(bot: string, thread: string, fresh: boolean): Promise<{ prs: unknown[] }>;
  /** A bot on another computer: never read. */
  remote(bot: string): boolean;
  now(): number;
  /** Ring for this failing PR, unless the person looks at that thread (the caller decides). */
  notify(f: FailingThread): void;
  told: { get(): Told; set(t: Told): void };
}

export type ReadWhy = "open" | "view" | "turn" | "refresh" | "tick";

export function createThreadPrs(deps: ThreadPrDeps) {
  const entries = new Map<string, PrEntry & { bot: string; thread: string }>();
  const visible = new Map<string, { bot: string; thread: string; n: number }>();
  const queue: { bot: string; thread: string; fresh: boolean }[] = [];
  const busy = new Set<string>();
  const fns = new Set<() => void>();
  let failing: FailingThread[] = [];
  let ver = 0;
  const keyOf = (bot: string, thread: string) => `${bot}\n${thread}`;

  const changed = () => {
    const next: FailingThread[] = [];
    for (const e of entries.values()) {
      const pr = e.prs ? failingPr(e.prs) : null;
      if (pr) next.push({ bot: e.bot, thread: e.thread, pr });
    }
    const same =
      next.length === failing.length &&
      next.every((f, i) => f.bot === failing[i].bot && f.thread === failing[i].thread && failKey(f.pr) === failKey(failing[i].pr));
    if (!same) failing = next;
    ver += 1;
    for (const f of [...fns]) f();
  };

  const pump = () => {
    while (busy.size < PR_READS_AT_ONCE) {
      // one read per thread at a time: a thread already being read waits its turn in the queue
      const i = queue.findIndex((j) => !busy.has(keyOf(j.bot, j.thread)));
      if (i < 0) return;
      const job = queue.splice(i, 1)[0];
      const k = keyOf(job.bot, job.thread);
      busy.add(k);
      void deps
        .read(job.bot, job.thread, job.fresh)
        .then(
          (r) => {
            const prs = cleanPrs(r?.prs);
            const old = entries.get(k);
            const limited = prs.some((p) => p.limited);
            entries.set(k, { bot: job.bot, thread: job.thread, prs, at: deps.now(), failures: readFailed(prs) ? (old?.failures ?? 0) + 1 : 0, limited });
            for (const p of prs) {
              if (p.state !== "open" || p.checks !== "failing") continue;
              const { ring, told } = mayRing(deps.told.get(), p, deps.now());
              deps.told.set(told);
              if (ring) deps.notify({ bot: job.bot, thread: job.thread, pr: p });
            }
          },
          () => {
            const old = entries.get(k);
            entries.set(k, { bot: job.bot, thread: job.thread, prs: old?.prs ?? null, at: deps.now(), failures: (old?.failures ?? 0) + 1 });
          },
        )
        .finally(() => {
          busy.delete(k);
          changed();
          pump();
        });
    }
  };

  /** Ask for `thread`'s PRs, for the reason given (see the top of this file for which reasons ask when). */
  const read = (bot: string, thread: string, why: ReadWhy) => {
    if (deps.remote(bot)) return;
    const k = keyOf(bot, thread);
    const e = entries.get(k);
    const age = e ? deps.now() - e.at : Infinity;
    if (why === "view" && age < PR_REREAD_MS) return;
    if (why === "tick" && (!e?.prs || !mayChange(e.prs) || age < (e.limited ? PR_TICK_MS : nextDelay(e.failures)))) return;
    const fresh = why === "refresh";
    const waiting = queue.find((j) => keyOf(j.bot, j.thread) === k);
    if (waiting) {
      waiting.fresh ||= fresh;
      return;
    }
    // a read already under way answers a view, a tick or an open; a turn's end or a Refresh asks once more after it
    if (busy.has(k) && why !== "turn" && !fresh) return;
    queue.push({ bot, thread, fresh });
    pump();
  };

  let timer: ReturnType<typeof setInterval> | null = null;
  /** The rows in view, and the threads in Needs you wherever their row is (so one leaves when its PR is merged). */
  const tick = () => {
    const due = new Map([...visible].map(([k, v]) => [k, v]));
    for (const f of failing) due.set(keyOf(f.bot, f.thread), { bot: f.bot, thread: f.thread, n: 1 });
    for (const v of due.values()) read(v.bot, v.thread, "tick");
  };

  return {
    get: (bot: string, thread: string): PrEntry | undefined => entries.get(keyOf(bot, thread)),
    read,
    /** A thread row in view: read now (unless read lately) and keep it on the background tick until it leaves. */
    show(bot: string, thread: string): () => void {
      const k = keyOf(bot, thread);
      const v = visible.get(k);
      if (v) v.n += 1;
      else visible.set(k, { bot, thread, n: 1 });
      read(bot, thread, "view");
      if (!timer && typeof setInterval !== "undefined") timer = setInterval(tick, PR_TICK_MS);
      return () => {
        const cur = visible.get(k);
        if (cur && --cur.n <= 0) visible.delete(k);
      };
    },
    tick,
    /** A thread was removed: forget it. */
    forget(bot: string, thread: string) {
      entries.delete(keyOf(bot, thread));
      changed();
    },
    /** Threads whose newest open PR has failing checks, for Needs you. Same array until it changes. */
    failing: () => failing,
    /** Moves on with every answer (for a view that shows any thread's PRs). */
    version: () => ver,
    busy: (bot: string, thread: string) => busy.has(keyOf(bot, thread)) || queue.some((j) => keyOf(j.bot, j.thread) === keyOf(bot, thread)),
    subscribe(f: () => void) {
      fns.add(f);
      return () => {
        fns.delete(f);
      };
    },
    stop() {
      if (timer) clearInterval(timer);
      timer = null;
    },
  };
}

export type ThreadPrs = ReturnType<typeof createThreadPrs>;

/** What has rung, kept in this computer's storage for the app (`omher.prNotified`). */
const TOLD_KEY = "omher.prNotified";
export function storedTold(): ThreadPrDeps["told"] {
  let t: Told = { heads: [], prs: {} };
  try {
    const raw = typeof localStorage !== "undefined" ? JSON.parse(localStorage.getItem(TOLD_KEY) ?? "null") : null;
    if (raw && Array.isArray(raw.heads) && raw.prs && typeof raw.prs === "object") {
      const prs = Object.entries(raw.prs as Record<string, unknown>).filter((e): e is [string, number] => typeof e[1] === "number");
      t = { heads: (raw.heads as unknown[]).filter((k): k is string => typeof k === "string").slice(-TOLD_MAX), prs: Object.fromEntries(prs.slice(-TOLD_MAX)) };
    }
  } catch {
    t = { heads: [], prs: {} };
  }
  return {
    get: () => t,
    set(next) {
      if (next === t) return;
      t = next;
      try {
        localStorage.setItem(TOLD_KEY, JSON.stringify(t));
      } catch {
        /* no storage: told for this run only */
      }
    },
  };
}
