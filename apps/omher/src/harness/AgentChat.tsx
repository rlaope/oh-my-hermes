// A Hermes subagent's, or a Claude Code / Codex session's, work shown as a CHAT between agents, read-only, with our
// own chat's parts: what the parent said (the prompt, any later steer) is a right bubble like the person's own,
// labelled with the parent's mark and name, because from the child's view the parent is its user; the child's
// words are left bubbles with its harness mark as the face (a Hermes child also wears its model's mark); its tool
// calls are our step rows between the bubbles, in order, each opening to its full input and result; its own children
// are our subagent rows, a click opens their chat in place (breadcrumb Kami › child › grandchild). The last left
// bubble is its answer; the parent's acceptance is not part of the child's session and never shows. No composer, no
// edit, no resend. Polls every 3 s while the session runs.
import { useEffect, useRef, useState } from "react";
import { Bubble } from "../chat/parts/Bubble";
import { StepRow } from "../chat/activity/Activity.slot";
import { SubagentLine } from "../chat/activity/Subagents";
import { Avatar, ChevronRight, Spinner } from "../ui";
import { t } from "../i18n";
import { modelName } from "../runs/format";
import { nodeSession, type NodeSessionTarget } from "./client";
import { HarnessFace, HarnessMark } from "./HarnessMark";
import { harness, harnessOf } from "./registry";
import { chatPieces, type NodeSession, type NodeSessionResult } from "./session";
import "./harness.css";

const POLL_MS = 3000;

interface Crumb {
  label: string;
  target: NodeSessionTarget;
  /** The face facts of the agent this crumb is (its harness, its model). */
  facts?: { kind?: string; executor?: string; model?: string; provider?: string };
}

function useNodeSession(bot: string, target: NodeSessionTarget, running: boolean, read: typeof nodeSession) {
  const [res, setRes] = useState<NodeSessionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(target);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setRes(null);
    setError(null);
    const load = () =>
      read(bot, target).then(
        (r) => {
          if (!live) return;
          setRes(r);
          const still = running || r.session?.state === "running";
          if (still) timer = setTimeout(load, POLL_MS);
        },
        (e) => live && setError(String((e as { message?: string })?.message ?? e)),
      );
    void load();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot, key, running, read]);
  return { res, error };
}

export function AgentChat({
  bot,
  botName,
  target,
  title,
  facts,
  running = false,
  full = false,
  onFull,
  read = nodeSession,
}: {
  bot: string;
  /** The parent's name on its right bubbles (the bot's display name). */
  botName?: string;
  target: NodeSessionTarget;
  /** The first crumb after the bot: the node's or the subagent's title. */
  title: string;
  /** What the node already says about who ran it (before the session is read). */
  facts?: Crumb["facts"];
  running?: boolean;
  /** Drawn across the whole view ("Open as chat"); `onFull` toggles it. */
  full?: boolean;
  onFull?: () => void;
  read?: typeof nodeSession;
}) {
  const [trail, setTrail] = useState<Crumb[]>([{ label: title, target, facts }]);
  const rootKey = JSON.stringify(target);
  useEffect(() => setTrail([{ label: title, target, facts }]), [rootKey, title]); // eslint-disable-line react-hooks/exhaustive-deps
  const cur = trail[trail.length - 1];
  const { res, error } = useNodeSession(bot, cur.target, trail.length === 1 && running, read);
  const s = res?.session ?? null;
  const parentName = trail.length === 1 ? (s?.parent || botName || bot) : trail[trail.length - 2].label;
  const parentFacts = trail.length === 1 ? null : trail[trail.length - 2].facts ?? null;
  const childFacts = { kind: s?.kind ?? cur.facts?.kind, executor: cur.facts?.executor, model: s?.model || cur.facts?.model, provider: s?.provider || cur.facts?.provider };
  const who = harnessOf(childFacts);
  const scroller = useRef<HTMLDivElement>(null);
  return (
    <div className={`ac${full ? " full" : ""}`} data-testid="agent-chat" data-kind={s?.kind ?? ""} data-harness={who.harness}>
      <div className="ac-head">
        <nav className="ac-crumbs" aria-label={t("harness.trail")} data-testid="agent-chat-trail">
          <span className="ac-crumb root">
            <Avatar bot={bot} size={14} />
            {botName || bot}
          </span>
          {trail.map((c, i) => (
            <span key={i} className="ac-crumb-w">
              <ChevronRight size={9} />
              {i < trail.length - 1 ? (
                <button type="button" className="ac-crumb" onClick={() => setTrail(trail.slice(0, i + 1))} data-testid="agent-chat-crumb">
                  {c.label}
                </button>
              ) : (
                <span className="ac-crumb cur" data-testid="agent-chat-crumb-current">
                  {c.label}
                </span>
              )}
            </span>
          ))}
        </nav>
        <span className="ac-who" data-testid="agent-chat-who">
          <HarnessMark id={who.harness} size={12} />
          {harness(who.harness).label}
          {childFacts.model ? ` · ${modelName(childFacts.model)}` : ""}
        </span>
        {onFull && (
          <button type="button" className="ac-full" onClick={onFull} data-testid="agent-chat-full">
            {full ? t("harness.closeChat") : t("harness.openChat")}
          </button>
        )}
      </div>
      <div className="ac-body" ref={scroller} data-testid="agent-chat-body" data-bubbles="open">
        {!res && !error && (
          <div className="ac-none">
            <Spinner size={10} label={t("harness.loading")} /> {t("harness.loading")}
          </div>
        )}
        {error && <div className="ac-none bad" data-testid="agent-chat-error">{t("harness.error", { error })}</div>}
        {res && !s && (
          <div className="ac-none" data-testid="agent-chat-none">
            {res.why === "no_cli_session" ? t("harness.noCli", { agent: harness(harnessOf({ executor: res.executor }).harness).label }) : t("harness.none")}
          </div>
        )}
        {s && (
          <ChatBody
            s={s}
            bot={bot}
            parentName={parentName}
            parentFacts={parentFacts}
            childFacts={childFacts}
            onChild={(c) =>
              setTrail([...trail, { label: c.label, target: { ref: c.ref }, facts: { kind: c.kind, model: c.model, provider: c.provider } }])
            }
          />
        )}
      </div>
    </div>
  );
}

function ChatBody({
  s,
  bot,
  parentName,
  parentFacts,
  childFacts,
  onChild,
}: {
  s: NodeSession;
  bot: string;
  parentName: string;
  parentFacts: Crumb["facts"] | null;
  childFacts: NonNullable<Crumb["facts"]>;
  onChild: (c: { ref: string; label: string; kind: string; model?: string; provider?: string }) => void;
}) {
  const pieces = chatPieces(s);
  const running = s.state === "running";
  const now = Date.now();
  // the parent's small mark beside its name: the bot's picture at the top, else the parent agent's harness mark
  const from = (
    <>
      {parentFacts ? <HarnessFace facts={parentFacts} size={12} /> : <Avatar bot={bot} size={12} />}
      <span data-testid="bubble-from-name">{parentName}</span>
    </>
  );
  const face = <HarnessFace facts={childFacts} size={28} />;
  let lastWasBot = false;
  return (
    <div className="ac-tl" data-testid="agent-chat-timeline">
      {pieces.map((p) => {
        if (p.kind === "user") {
          lastWasBot = false;
          return <Bubble key={p.key} item={{ kind: "user", text: p.text }} from={from} />;
        }
        if (p.kind === "assistant") {
          const first = !lastWasBot;
          lastWasBot = true;
          return (
            <div key={p.key} data-testid={p.last ? "agent-chat-answer" : "agent-chat-said"}>
              <Bubble item={{ kind: "assistant", text: p.text }} bot={bot} face={first} faceEl={face} />
            </div>
          );
        }
        lastWasBot = false;
        if (p.kind === "steps")
          return (
            <div key={p.key} className="act ac-steps" data-testid="agent-chat-steps">
              <div className="act-det">
                {p.steps.map((st) => (
                  <StepRow key={st.id} step={st} live={false} now={now} io={{ input: st.input, result: st.result }} />
                ))}
              </div>
            </div>
          );
        const label = p.sub.goal || t("sub.untitled", { n: p.sub.index + 1 });
        const open = () => onChild({ ref: p.ref, label, kind: p.childKind, model: p.sub.model, provider: p.provider });
        return (
          // the same row our chat's subagent card shows; a click anywhere on it opens the child's own chat here
          <div
            key={p.key}
            role="button"
            tabIndex={0}
            className="ac-child sa-card"
            data-testid="agent-chat-child"
            data-ref={p.ref}
            onClickCapture={(e) => {
              e.preventDefault();
              e.stopPropagation();
              open();
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                open();
              }
            }}
            title={t("harness.openChild", { name: label })}
          >
            <SubagentLine sub={p.sub} now={now} live={running} />
          </div>
        );
      })}
    </div>
  );
}
