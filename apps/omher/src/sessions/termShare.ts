// Bots and TERMINALS sessions. While a TERMINALS session is listed, omher keeps a small status file for it that a bot
// holding its link can read (`~/.omher/terminals/<link id>.json`, written by the shell, src-tauri/src/term_share.rs):
// its title, CLI, folder, state, start time and last printed line. A bot asks to type into the session by putting a
// request in the session's inbox (the OMH tool `omh_omher_terminal`). The shell checks every inbox file (the user's
// own owner-only plain file, 16 KB at most, never a link) and hands the page the request; the page shows it as a card
// on the session ("<bot> wants to type into <title>"), with Deny, Allow once and Allow for this session. Only Allow
// types it (the prompt, then Enter; a bracketed paste when the program asked for one). "Allow for this session" lets
// later requests to that session type without a card until it is closed or omher restarts. Nothing else types a
// bot's prompt.
import { useSyncExternalStore } from "react";
import { getStore } from "../state/store";
import { isTerminalRec, termFallbackName, type SessionRec } from "./agents";
import { getSessions } from "./sessions";
import { termActs } from "./termActivity";
import { findTermLinks, isLinkId } from "./termLink";
import { pickTitle } from "./titles";
import { termLinkState } from "../chat/parts/TermLinkChip";
import { t } from "../i18n";

/** What the shell writes for one session (term_share.rs `Status`). */
export interface ShareStatus {
  title: string;
  agent: string;
  cwd: string;
  state: "working" | "waiting" | "done" | "ended";
  /** ms since the epoch */
  started: number;
  lastLine: string;
}

/** A bot's request as the shell hands it over (term_share.rs `Request`). `link`: the session's link id. */
export interface ShareRequest {
  id: string;
  link: string;
  prompt: string;
  from: string;
  session: string;
}

/** A request waiting on the person: the session it is for and a key of its own. */
export interface PendingRequest extends ShareRequest {
  key: string;
  sessionId: string;
}

export interface ShareHost {
  write(link: string, status: ShareStatus): Promise<void>;
  remove(link: string): Promise<void>;
  prune(keep: string[]): Promise<void>;
  take(links: string[]): Promise<ShareRequest[]>;
}

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

class TauriShare implements ShareHost {
  private async invoke<T>(cmd: string, args: Record<string, unknown>): Promise<T> {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>(cmd, args);
  }
  write(link: string, status: ShareStatus) {
    return this.invoke<void>("term_share_write", { link, status });
  }
  remove(link: string) {
    return this.invoke<void>("term_share_remove", { link });
  }
  prune(keep: string[]) {
    return this.invoke<void>("term_share_prune", { keep });
  }
  take(links: string[]) {
    return this.invoke<ShareRequest[]>("term_share_take", { links });
  }
}

type MockShareGlobals = {
  /** e2e: the status files the mock shell keeps, by link id */
  __omherShareFiles?: Record<string, ShareStatus>;
  /** e2e: requests waiting in the mock inboxes (as the OMH tool writes them; `link` is the id) */
  __omherMockInbox?: ShareRequest[];
};

/** The mock shell: status files in memory; requests a test puts in `__omherMockInbox` are taken as the shell would
 *  (control characters out, a newline kept). */
export class MockShare implements ShareHost {
  constructor(private g: MockShareGlobals = globalThis as MockShareGlobals) {}
  async write(link: string, status: ShareStatus) {
    (this.g.__omherShareFiles ??= {})[link] = status;
  }
  async remove(link: string) {
    if (this.g.__omherShareFiles) delete this.g.__omherShareFiles[link];
  }
  async prune(keep: string[]) {
    const f = this.g.__omherShareFiles ?? {};
    for (const k of Object.keys(f)) if (!keep.includes(k)) delete f[k];
  }
  async take(links: string[]) {
    const all = this.g.__omherMockInbox ?? [];
    const mine = all.filter((r) => links.includes(r.link));
    this.g.__omherMockInbox = all.filter((r) => !links.includes(r.link));
    return mine.map((r) => ({ ...r, prompt: cleanPrompt(String(r.prompt ?? "")) })).filter((r) => r.prompt.trim());
  }
}

/** Control characters out (C0, DEL, C1); a newline stays. The shell does the same; the page does it again before it
 *  types anything. */
export function cleanPrompt(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\r\n/g, "\n").replace(/[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/g, "");
}

/** What a session's status file says now (null: no file for it, a draft or a chat session). Pure apart from the
 *  clock. */
export function statusOf(rec: SessionRec, agents: Parameters<typeof termFallbackName>[1], unseen: Parameters<typeof termLinkState>[2], now: number): ShareStatus | null {
  if (!rec.linkId || !isTerminalRec(agents, rec)) return null;
  const act = termActs.get(rec.id);
  return {
    title: pickTitle(rec, termFallbackName(rec, agents)).title,
    agent: rec.fgAgent ?? rec.agent,
    cwd: act.cwd ?? rec.cwd,
    state: termLinkState(rec, act, unseen, now),
    started: rec.startedAt,
    lastLine: act.lastLine || act.oscTitle || "",
  };
}

// ---- the store ------------------------------------------------------------------------------------------------

export function createTermShare(host: ShareHost, sessions: () => ReturnType<typeof getSessions>) {
  /** what was last written, by link id (JSON) */
  const written = new Map<string, string>();
  let pending: PendingRequest[] = [];
  /** sessions the person allowed for the rest of their life ("Allow for this session") */
  const granted = new Set<string>();
  const subs = new Set<() => void>();
  let seq = 0;
  const emit = () => {
    for (const fn of [...subs]) fn();
  };

  /** Type an allowed prompt into session `id`. The only way a bot's prompt reaches a terminal. */
  const type = (r: PendingRequest) => void sessions().typeAllowed(r.sessionId, cleanPrompt(r.prompt));

  /** Write what changed, remove the files of sessions that are gone. */
  const publish = async (now = Date.now()) => {
    const st = sessions().getState();
    const seen = new Set<string>();
    for (const rec of st.list) {
      const s = statusOf(rec, st.agents, st.unseen[rec.id], now);
      if (!s) continue;
      seen.add(rec.linkId!);
      const json = JSON.stringify(s);
      if (written.get(rec.linkId!) === json) continue;
      written.set(rec.linkId!, json);
      await host.write(rec.linkId!, s).catch(() => written.delete(rec.linkId!));
    }
    for (const link of [...written.keys()]) {
      if (seen.has(link)) continue;
      written.delete(link);
      await host.remove(link).catch(() => undefined);
    }
    // a request or grant for a session that is gone goes with it
    const ids = new Set(st.list.map((r) => r.id));
    for (const g of [...granted]) if (!ids.has(g)) granted.delete(g);
    const keep = pending.filter((p) => ids.has(p.sessionId));
    if (keep.length !== pending.length) {
      pending = keep;
      emit();
    }
  };

  /** Requests the shell took from the inboxes: typed at once for a session the person allowed, else a card. */
  const arrive = (reqs: ShareRequest[]) => {
    let added = false;
    for (const r of reqs) {
      if (!isLinkId(r.link)) continue;
      const rec = sessions().byLink(r.link);
      if (!rec || !isTerminalRec(sessions().getState().agents, rec)) continue;
      const p: PendingRequest = { ...r, prompt: cleanPrompt(r.prompt), key: `rq${++seq}`, sessionId: rec.id };
      if (!p.prompt.trim()) continue;
      if (granted.has(rec.id)) {
        type(p);
        continue;
      }
      pending = [...pending, p];
      added = true;
    }
    if (added) emit();
  };

  const poll = async () => {
    const links = [...written.keys()];
    if (!links.length) return;
    const got = await host.take(links).catch(() => [] as ShareRequest[]);
    if (got.length) arrive(got);
  };

  /** The person's answer to request `key`. */
  const answer = (key: string, choice: "deny" | "once" | "session") => {
    const r = pending.find((p) => p.key === key);
    if (!r) return;
    pending = pending.filter((p) => p.key !== key);
    if (choice === "session") granted.add(r.sessionId);
    if (choice !== "deny") type(r);
    emit();
  };

  return {
    publish,
    poll,
    arrive,
    answer,
    prune: (keep: string[]) => host.prune(keep),
    pending: () => pending,
    granted: (id: string) => granted.has(id),
    subscribe(fn: () => void) {
      subs.add(fn);
      return () => void subs.delete(fn);
    },
  };
}

export type TermShare = ReturnType<typeof createTermShare>;

let share: TermShare | null = null;
export function getTermShare(): TermShare {
  if (!share) {
    share = createTermShare(inTauri() ? new TauriShare() : new MockShare(), getSessions);
    if (typeof window !== "undefined" && !inTauri()) (window as unknown as { __omherShare?: TermShare }).__omherShare = share;
  }
  return share;
}

/** How often omher looks in the inboxes and rewrites changed status files. */
export const SHARE_POLL_MS = 1500;

let started = false;
/** Once per page load: after the session list came back, remove the files of sessions that are gone, then keep the
 *  status files current and look in the inboxes. */
export function startTermShare(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  const s = getTermShare();
  void getStore().resumed.then(async () => {
    const keep = getSessions()
      .getState()
      .list.map((r) => r.linkId)
      .filter((x): x is string => !!x);
    await s.prune(keep).catch(() => undefined);
    let busy = false;
    const tick = async () => {
      if (busy) return;
      busy = true;
      try {
        await s.publish();
        await s.poll();
      } finally {
        busy = false;
      }
    };
    void tick();
    getSessions().subscribe(() => void tick());
    setInterval(() => void tick(), SHARE_POLL_MS);
  });
}

const NONE: PendingRequest[] = [];

/** The requests waiting on the person (all sessions, oldest first). */
export function usePendingRequests(): PendingRequest[] {
  const s = getTermShare();
  return useSyncExternalStore(s.subscribe, s.pending, () => NONE);
}

/** `text` with each omher terminal link as that session's title (or "Terminal not on this computer"), for one-line
 *  previews that draw no chip. */
export function termLinkText(text: string): string {
  const found = findTermLinks(text);
  if (!found.length) return text;
  const ss = getSessions();
  const st = ss.getState();
  let out = "";
  let at = 0;
  for (const f of found) {
    const rec = ss.byLink(f.id);
    out += text.slice(at, f.start) + (rec && rec.status !== "draft" ? pickTitle(rec, termFallbackName(rec, st.agents)).title : t("tlink.gone"));
    at = f.end;
  }
  return out + text.slice(at);
}
