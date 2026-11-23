// "Hand to <bot>": the small card a TERMINALS row's menu and a Worktrees row's menu open. It shows the first message
// (src/handover/message.ts) before anything is sent, takes an optional goal line, and on Open thread starts a thread
// under the picked bot through the same store action as "Start in thread" (thread.create, then chat.send). Nothing
// is moved, closed or typed into a terminal. Git facts come only from the bot's Worktrees list and one panel.diff of
// a worktree in it (BOUNDARY.md rule 10). Cancel, Escape or a press outside sends nothing.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Bot, Worktree, WorktreeDiff } from "../lib/protocol";
import { getStore, useStore } from "../state/store";
import { loadTrees } from "../elsewhere/trees";
import { BotChip } from "../pages/kit";
import { t } from "../i18n";
import { composing } from "../lib/ime";
import { Spinner } from "../ui";
import { GOAL_CHARS, handoverMessage, handoverTitle, worktreeOf } from "./message";
import "./handover.css";

/** What is handed: a TERMINALS session's folder (git facts looked up in the picked bot's worktrees), or a row of a
 *  bot's Worktrees tab (read as that bot). */
export type HandoverFrom = { kind: "terminal"; folder: string } | { kind: "worktree"; bot: string; worktree: Worktree };

/** The bots a folder can be handed to: this computer's, not offline (as the Tasks page's bot chip). */
export const handBots = (bots: Bot[]) => bots.filter((b) => !b.host && b.status !== "offline");

/** The menu item: "Hand to <bot>…" with one bot to hand to, else "Hand to a bot…" (the card has the picker). */
export function handLabel(): string {
  const bots = handBots(getStore().getSnapshot().bots);
  return bots.length === 1 ? t("hand.menuOne", { bot: bots[0].display_name }) : t("hand.menu");
}

const W = 380;

/** `gone`: the bridge no longer finds that worktree (removed since the list was read): nothing can be sent. */
type Facts = { key: string; worktree: Worktree | null; diff: WorktreeDiff | null; gone: boolean };

export function HandoverCard({ at, from, onClose }: { at: { x: number; y: number }; from: HandoverFrom; onClose: () => void }) {
  const s = useStore();
  const local = handBots(s.bots);
  // a Worktrees row goes to its own bot unless another is picked (when that bot is of this computer and online)
  const [pick, setPick] = useState<string | null>(from.kind === "worktree" ? from.bot : null);
  const to = local.find((b) => b.name === pick) ?? local.find((b) => b.name === s.selectedBot) ?? local[0];
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [facts, setFacts] = useState<Facts | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(at.y);
  const folder = from.kind === "terminal" ? from.folder : from.worktree.path;
  // a Worktrees row is read as the bot whose tab shows it; a terminal's folder as the bot it goes to. With no bot to
  // send to, nothing is read.
  const reader = !to ? "" : from.kind === "worktree" ? from.bot : to.name;
  const key = `${reader}\n${folder}`;
  useEffect(() => {
    if (!reader) return;
    let live = true;
    void (async () => {
      let worktree: Worktree | null = null;
      if (from.kind === "worktree") worktree = from.worktree;
      else worktree = worktreeOf(folder, (await loadTrees(reader).catch(() => ({ worktrees: [] }))).worktrees);
      let gone = false;
      const diff = !worktree
        ? null
        : await getStore()
            .actions.panelDiff(reader, worktree.path)
            .catch((e: { code?: string }) => {
              gone = e?.code === "not_found";
              return null;
            });
      if (live) setFacts({ key, worktree, diff, gone });
    })();
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  // once, when the card opens: the goal field takes the keyboard, a press outside closes it, and closing gives the
  // keyboard back to where it was
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLInputElement>("input")?.focus();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close.current();
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
      if (back && document.contains(back)) back.focus();
    };
  }, []);
  const ready = facts?.key === key ? facts : null;
  const text = ready ? handoverMessage({ folder, worktree: ready.worktree, diff: ready.diff, goal }) : "";
  useLayoutEffect(() => {
    const h = ref.current?.offsetHeight ?? 0;
    setTop(Math.max(6, Math.min(at.y, window.innerHeight - h - 6)));
  }, [at.y, text]);
  const send = async () => {
    if (!to || !ready || ready.gone || busy) return;
    setBusy(true);
    const made = await s.startTaskThread(to.name, handoverTitle({ folder, worktree: ready.worktree }), text);
    setBusy(false);
    if (made) onClose();
  };
  const left = Math.max(6, Math.min(at.x, window.innerWidth - W - 6));
  return createPortal(
    <div
      ref={ref}
      className="ho-card"
      role="dialog"
      aria-label={to ? t("hand.title", { bot: to.display_name }) : t("hand.menu")}
      style={{ left, top, width: W }}
      data-testid="handover"
      // a portal's events still bubble to the React parent (a TERMINALS row drags to split or reorder on a press and
      // opens its menu on a right click; the panel maximises on a double click): none of that from inside the card
      onPointerDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        // Escape with the bot list open closes only the list (its own listener); the next one closes the card
        if (e.key === "Escape" && !ref.current?.querySelector('[aria-expanded="true"]')) {
          e.preventDefault();
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div className="ho-head">
        {local.length > 1 ? (
          <>
            <span>{t("hand.to")}</span>
            <BotChip bots={local} bot={to} onPick={setPick} testId="handover-bot" />
          </>
        ) : (
          <b>{to ? t("hand.title", { bot: to.display_name }) : t("hand.noBot")}</b>
        )}
      </div>
      <label className="ho-goal">
        <span>{t("hand.goal")}</span>
        <input
          type="text"
          value={goal}
          maxLength={GOAL_CHARS}
          placeholder={t("hand.goalHint")}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !composing(e)) {
              e.preventDefault();
              void send();
            }
          }}
          data-testid="handover-goal"
        />
      </label>
      <div className="ho-sub">{t("hand.preview")}</div>
      {!to ? (
        <div className="ho-prev ho-wait">{t("hand.noBot")}</div>
      ) : ready?.gone ? (
        <div className="ho-prev ho-wait ho-gone" data-testid="handover-gone">
          {t("hand.gone")}
        </div>
      ) : ready ? (
        <pre className="ho-prev" data-testid="handover-preview">
          {text}
        </pre>
      ) : (
        <div className="ho-prev ho-wait">
          <Spinner size={12} label={t("hand.reading")} />
        </div>
      )}
      <p className="ho-note">{t("hand.note")}</p>
      <div className="ho-b">
        <button type="button" onClick={onClose} data-testid="handover-cancel">
          {t("hand.cancel")}
        </button>
        <button type="button" className="primary" disabled={!to || !ready || ready.gone || busy} onClick={() => void send()} data-testid="handover-send">
          {t("hand.send")}
        </button>
      </div>
    </div>,
    document.body,
  );
}
