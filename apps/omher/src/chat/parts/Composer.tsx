import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../../lib/protocol";
import { useStore, type OutFile, type ReplyChip } from "../../state/store";
import { ArrowUp, CloseIcon, SourceIcon, StopIcon } from "../../ui";
import { AttachButton, Chips, chipsFor, useDropZone, type Chip } from "./Attach";
import "./attach.css";

const MAX_H = 200;

/** Autosizing textarea with a + at its left edge for files (menu, drop on the chat, paste). Enter sends,
 * Shift+Enter breaks the line, `/` shows a skill hint, Stop interrupts. Files go first (`chat.attach`), then
 * the text; if one fails nothing is sent and the chips stay. A "Reply there" chip sits above the text: the
 * next message points the bot at that thread (omher posts nothing). */
export function Composer({
  bot,
  running,
  asking = false,
  offline,
  onSend,
  onSendFiles,
  onStop,
  reply,
  onClearReply,
  offlineText,
}: {
  bot: Bot;
  running: boolean;
  /** An approval or question card of this bot is waiting above: the placeholder points at it. */
  asking?: boolean;
  offline: boolean;
  onSend: (text: string) => void;
  /** Without it (a SESSIONS chat) there is no + and no drop: files go only to a bot's main chat. */
  onSendFiles?: (text: string, files: OutFile[]) => Promise<void>;
  onStop: () => void;
  reply?: ReplyChip | null;
  onClearReply?: () => void;
  /** Placeholder while `offline` (default: "<bot> is offline"). */
  offlineText?: string;
}) {
  const [text, setText] = useState("");
  const [chips, setChips] = useState<Chip[]>([]);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const good = chips.filter((c) => !c.reason);
  const has = text.trim().length > 0 || good.length > 0;

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_H)}px`;
    el.style.overflowY = el.scrollHeight > MAX_H ? "auto" : "hidden";
  }, [text]);

  useLayoutEffect(() => {
    ref.current?.focus();
  }, [bot.name, reply?.session_id]);

  // "Ask in chat" from the Runs drawer: the text lands here for the person to edit and send.
  const draft = useStore().ui.draft;
  useLayoutEffect(() => {
    if (!draft || draft.bot !== bot.name) return;
    setText(draft.text);
    requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(draft.text.length, draft.text.length);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft?.n]);

  const add = useCallback((files: File[]) => {
    setErr(null);
    setChips((cur) => [...cur, ...chipsFor(files, cur.filter((c) => !c.reason).length)]);
    ref.current?.focus();
  }, []);

  const remove = (id: string) =>
    setChips((cur) => {
      const gone = cur.find((c) => c.id === id);
      if (gone?.url) URL.revokeObjectURL(gone.url);
      return cur.filter((c) => c.id !== id);
    });

  // Unsent chips let go of their local copies when the composer goes; sent ones live on in the bubble.
  const latest = useRef(chips);
  latest.current = chips;
  useEffect(() => () => latest.current.forEach((c) => c.url && URL.revokeObjectURL(c.url)), []);

  const overlay = useDropZone(wrap, !offline && !!onSendFiles, add);

  const send = async () => {
    if (!has || offline || sending) return;
    if (!good.length || !onSendFiles) {
      onSend(text);
      setText("");
      return;
    }
    setSending(true);
    setErr(null);
    try {
      await onSendFiles(text, good);
      setText("");
      setChips((cur) => cur.filter((c) => c.reason)); // red chips stay: they were never sent
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const slash = /^\/[\w-]*$/.test(text);
  const showStop = running && !has;

  return (
    <div className="cw" ref={wrap}>
      {overlay}
      {slash && (
        <div className="hint" role="note" data-testid="skill-hint">
          <span className="hint-k">/skill</span> Type a skill name, e.g. <code>/plan</code> — {bot.display_name} loads it
          for this message
        </div>
      )}
      <div className={`composer${has ? " has" : ""}`} data-testid="composer-box">
        <Chips chips={chips} onRemove={remove} />
        {err && (
          <div className="att-err" role="alert" data-testid="attach-error">
            {err}
          </div>
        )}
        {reply && (
          <span className="reply-chip" data-testid="reply-chip" data-session={reply.session_id}>
            <SourceIcon source={reply.source} size={12} />
            <span className="rc-t">
              {reply.place} <span className="rc-k">· {reply.kind}</span>
            </span>
            <button
              type="button"
              className="rc-x"
              aria-label="Remove reply target"
              title="Remove"
              onClick={() => {
                onClearReply?.();
                ref.current?.focus();
              }}
              data-testid="reply-chip-remove"
            >
              <CloseIcon />
            </button>
          </span>
        )}
        <div className="composer-row">
          {onSendFiles && <AttachButton disabled={offline || sending} onFiles={add} onError={setErr} />}
          <textarea
            ref={ref}
            rows={1}
            value={text}
            disabled={offline}
            placeholder={
              offline
                ? (offlineText ?? `${bot.display_name} is offline`)
                : reply
                  ? `Tell ${bot.display_name} what to post there`
                  : asking
                    ? "Answer above, or type to reply"
                    : `Message ${bot.display_name}`
            }
            aria-label={`Message ${bot.display_name}`}
            data-testid="composer"
            onChange={(e) => setText(e.target.value)}
            onPaste={(e) => {
              const files = [...e.clipboardData.files];
              if (!files.length || !onSendFiles) return;
              e.preventDefault();
              add(files);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault();
                void send();
              } else if (e.key === "Backspace" && !text && reply) {
                e.preventDefault();
                onClearReply?.();
              }
            }}
          />
          {showStop ? (
            <button type="button" className="send stop" aria-label="Stop" title="Stop" onClick={onStop} data-testid="stop">
              <StopIcon />
            </button>
          ) : (
            <button
              type="button"
              className="send"
              aria-label="Send"
              title="Send"
              disabled={!has || offline || sending}
              onClick={() => void send()}
              data-testid="send"
            >
              <ArrowUp />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
