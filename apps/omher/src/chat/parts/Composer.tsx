import { useLayoutEffect, useRef, useState } from "react";
import type { Bot } from "../../lib/protocol";
import { ArrowUp, StopIcon } from "../../ui";

const MAX_H = 200;

/** Autosizing textarea. Enter sends, Shift+Enter breaks the line, `/` shows a skill hint, Stop interrupts. */
export function Composer({
  bot,
  running,
  asking = false,
  offline,
  onSend,
  onStop,
  offlineText,
}: {
  bot: Bot;
  running: boolean;
  /** An approval or question card of this bot is waiting above: the placeholder points at it. */
  asking?: boolean;
  offline: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
  /** Placeholder while `offline` (default: "<bot> is offline"). */
  offlineText?: string;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const has = text.trim().length > 0;

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_H)}px`;
    el.style.overflowY = el.scrollHeight > MAX_H ? "auto" : "hidden";
  }, [text]);

  useLayoutEffect(() => {
    ref.current?.focus();
  }, [bot.name]);

  const send = () => {
    if (!has || offline) return;
    onSend(text);
    setText("");
  };

  const slash = /^\/[\w-]*$/.test(text);
  const showStop = running && !has;

  return (
    <div className="cw">
      {slash && (
        <div className="hint" role="note" data-testid="skill-hint">
          <span className="hint-k">/skill</span> Type a skill name, e.g. <code>/plan</code> — {bot.display_name} loads it
          for this message
        </div>
      )}
      <div className={`composer${has ? " has" : ""}`}>
        <textarea
          ref={ref}
          rows={1}
          value={text}
          disabled={offline}
          placeholder={
            offline
              ? (offlineText ?? `${bot.display_name} is offline`)
              : asking
                ? "Answer above, or type to reply"
                : `Message ${bot.display_name}`
          }
          aria-label={`Message ${bot.display_name}`}
          data-testid="composer"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
              e.preventDefault();
              send();
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
            disabled={!has || offline}
            onClick={send}
            data-testid="send"
          >
            <ArrowUp />
          </button>
        )}
      </div>
    </div>
  );
}
