// An omher terminal link (`omher://terminal/<id>`) wherever omher draws links: an omher chip. The omher face, then the
// session's CLI mark, its title and a live state dot (working: output flowing; news: it rang unseen, finished or
// waiting; waiting: idle at its prompt; done: ended with 0; ended: ended otherwise, failed, or paused after a restart). A click opens the session. A link
// whose session is not in this computer's TERMINALS reads "Terminal not on this computer" and opens nothing.
import { memo, type MouseEvent } from "react";
import logo from "../../assets/omher-mark.png";
import { t, type Key } from "../../i18n";
import { getStore } from "../../state/store";
import { isNews, termFallbackName, termMarkAgent, type SessionRec, type Unseen } from "../../sessions/agents";
import { flowing, useTermFace } from "../../sessions/termActivity";
import { useSessions } from "../../sessions/sessions";
import { TermRowMark } from "../../sessions/TermRowMark";
import { pickTitle } from "../../sessions/titles";
import { parseTermLink } from "../../sessions/termLink";

/** A session's state as its status file tells bots (termShare.ts): an unseen ring stays `waiting` there. */
export type ShareState = "working" | "waiting" | "done" | "ended";
/** The chip's dot: the file's states, plus `news` for a ring nobody has seen (it may have finished or be waiting). */
export type TermLinkState = ShareState | "news";

/** What a session's status file says of it at `now` (`progress`/`lastOut` from its terminal's activity). Pure. */
export function termLinkState(rec: Pick<SessionRec, "status" | "exitCode" | "paused">, act: { lastOut?: number; progress?: boolean }, unseen: Unseen | undefined, now: number): ShareState {
  if (rec.paused) return "ended";
  if (rec.status === "exited") return rec.exitCode === 0 ? "done" : "ended";
  if (rec.status === "failed" || rec.status === "draft") return "ended";
  // working while its program reports progress, even over a ring nobody saw (that ring is behind it); a bell just
  // after output still reads waiting, as an agent rings when it stops for the person
  if (act.progress) return "working";
  if (unseen === "bell") return "waiting";
  return flowing(act, now) ? "working" : "waiting";
}

/** What the chip's dot says: as the status file, but a running session that rang unseen is news, not waiting. Pure. */
export function termChipState(rec: Pick<SessionRec, "status" | "exitCode" | "paused">, act: { lastOut?: number; progress?: boolean }, unseen: Unseen | undefined, now: number): TermLinkState {
  const st = termLinkState(rec, act, unseen, now);
  return st === "waiting" && isNews(unseen) ? "news" : st;
}

const STATE_KEY: Record<TermLinkState, Key> = { working: "tlink.st.working", news: "tlink.st.news", waiting: "tlink.st.waiting", done: "tlink.st.done", ended: "tlink.st.ended" };

function open(e: MouseEvent<HTMLAnchorElement>, id: string) {
  e.preventDefault();
  if (e.button !== 0) return;
  getStore().actions.openSession(id);
}

const Known = memo(function Known({ url, rec, unseen, label }: { url: string; rec: SessionRec; unseen?: Unseen; label?: string }) {
  const ss = useSessions();
  const live = rec.status === "running" || rec.status === "starting";
  const { act, now } = useTermFace(rec.id, rec.startedAt, live);
  const state = termChipState(rec, act, unseen, now);
  const title = pickTitle(rec, termFallbackName(rec, ss.agents)).title;
  const stateText = t(STATE_KEY[state]);
  return (
    <a
      href={url}
      className="lk lk-term"
      data-testid="term-link-chip"
      data-session={rec.id}
      data-state={state}
      title={`${title} · ${stateText}\n${url}`}
      onClick={(e) => open(e, rec.id)}
    >
      <img src={logo} alt="" className="lk-term-omh" width={12} height={12} />
      <TermRowMark agent={termMarkAgent(rec)} size={12} />
      <span className="lk-t">{label ?? title}</span>
      {/* news takes the accent (links.css colours the other states) */}
      <span className={`lk-term-dot ${state}`} style={state === "news" ? { background: "var(--accent)" } : undefined} role="img" aria-label={stateText} data-testid="term-link-state" />
    </a>
  );
});

/** The chip for terminal link `url` (`children`: a markdown link's own text, shown instead of the title). */
export const TermLinkChip = memo(function TermLinkChip({ url, label }: { url: string; label?: string }) {
  const ss = useSessions();
  const id = parseTermLink(url);
  const rec = id ? ss.list.find((r) => r.linkId === id) : undefined;
  if (rec) return <Known url={url} rec={rec} unseen={ss.unseen[rec.id]} label={label} />;
  return (
    <span className="lk lk-term gone" data-testid="term-link-chip" data-state="gone" title={url}>
      <img src={logo} alt="" className="lk-term-omh" width={12} height={12} />
      <span className="lk-t">{t("tlink.gone")}</span>
    </span>
  );
});
