import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Bot, Skill } from "../../lib/protocol";
import { useStore, type OutFile, type ReplyChip } from "../../state/store";
import { ArrowUp, CloseIcon, SourceIcon, StopIcon } from "../../ui";
import { AttachButton, Chips, chipsFor, useDropZone, type Chip } from "./Attach";
import "./attach.css";
import { SkillPicker, mirrorText } from "./Skills";
import { findTokens, fragmentAt, matchSkills } from "./skillTokens";
import { getDraft, setDraft } from "../../app/drafts";
import { t, tx } from "../../i18n";
import { composing as imeComposing } from "../../lib/ime";

const MAX_H = 200;

/** Autosizing textarea with a + at its left edge for files (menu, drop on the chat, paste). Enter sends,
 * Shift+Enter breaks the line, `/` shows a skill hint, Stop interrupts. Files go first (`chat.attach`), then
 * the text; if one fails nothing is sent and the chips stay. A "Reply there" chip sits above the text: the
 * next message points the bot at that thread (omher posts nothing). With `skills`, `./` anywhere opens the
 * bot's skills; a picked `./name` is drawn as a gray pill by a mirror layer under the textarea (same font,
 * padding and wrapping, scrolled with it), and goes out hoisted to the front as `/name` (store `send`). */
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
  skills: skillsOn = false,
  tools,
  action,
  foot,
}: {
  bot: Bot;
  running: boolean;
  /** An approval or question card of this bot is waiting above: the placeholder points at it. */
  asking?: boolean;
  offline: boolean;
  onSend: (text: string) => void;
  /** Files with the text (a bot's main chat, a SESSIONS chat agent). Without it there is no +, drop or file paste. */
  onSendFiles?: (text: string, files: OutFile[]) => Promise<void>;
  onStop: () => void;
  reply?: ReplyChip | null;
  onClearReply?: () => void;
  /** Placeholder while `offline` (default: "<bot> is offline"). */
  offlineText?: string;
  /** Offer the bot's skills on `./` (a bot's main chat). */
  skills?: boolean;
  /** Controls in the row before Send (a New session chat's agent picker). */
  tools?: ReactNode;
  /** Stands in for Send (a terminal agent's Start). */
  action?: ReactNode;
  /** A quiet line under the box (a session's folder and account). */
  foot?: ReactNode;
}) {
  // unsent text survives switching chats and restarts (drafts.ts; the composer is keyed by its chat)
  const [text, setText] = useState(() => getDraft(bot.name));
  useEffect(() => setDraft(bot.name, text), [bot.name, text]);
  const [chips, setChips] = useState<Chip[]>([]);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const mirror = useRef<HTMLDivElement>(null);
  const anchor = useRef<HTMLSpanElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const good = chips.filter((c) => !c.reason);
  const has = text.trim().length > 0 || good.length > 0;
  const store = useStore();

  // skills: read once, the first time the text has a `./` in it (the store keeps the list per bot)
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [caret, setCaret] = useState<number | null>(null);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const placeCaret = useRef<number | null>(null);
  const wantSkills = skillsOn && text.includes("./");
  const loadSkills = store.skills;
  useEffect(() => {
    if (!wantSkills || skills) return;
    let live = true;
    void loadSkills(bot.name).then((list) => live && setSkills(list));
    return () => {
      live = false;
    };
  }, [wantSkills, skills, loadSkills, bot.name]);
  const names = useMemo(() => (skills ?? []).map((s) => s.name), [skills]);
  const tokens = useMemo(() => findTokens(text, names), [text, names]);
  const frag = skills && caret !== null ? fragmentAt(text, caret) : null;
  const fragKey = frag ? `${frag.start}:${frag.query}` : null;
  const items = useMemo(() => (frag && skills ? matchSkills(skills, frag.query) : []), [skills, fragKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const picking = !!frag && focused && fragKey !== dismissed;
  const at = Math.min(active, Math.max(items.length - 1, 0));
  useEffect(() => setActive(0), [fragKey]);

  /** The mirror follows the textarea's box and scroll (its width leaves out a scrollbar). */
  const syncMirror = useCallback(() => {
    const el = ref.current;
    const m = mirror.current;
    if (!el || !m) return;
    m.style.width = `${el.clientWidth}px`;
    m.style.height = `${el.clientHeight}px`;
    m.scrollTop = el.scrollTop;
  }, []);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_H)}px`;
    el.style.overflowY = el.scrollHeight > MAX_H ? "auto" : "hidden";
    if (placeCaret.current !== null) {
      el.setSelectionRange(placeCaret.current, placeCaret.current);
      placeCaret.current = null;
    }
    syncMirror();
  }, [text, tokens, syncMirror]);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(syncMirror);
    ro.observe(el);
    return () => ro.disconnect();
  }, [syncMirror]);

  // the picker starts at the `./` being typed, kept inside the composer's width
  useLayoutEffect(() => {
    const p = pop.current;
    const a = anchor.current;
    const w = wrap.current;
    if (!picking || !p || !a || !w) return;
    const x = a.getBoundingClientRect().left - w.getBoundingClientRect().left - 11;
    p.style.left = `${Math.max(0, Math.min(x, w.clientWidth - p.offsetWidth))}px`;
  });
  useEffect(() => {
    if (picking) pop.current?.querySelector(".sk-row.on")?.scrollIntoView({ block: "nearest" });
  }, [picking, at]);

  const trackCaret = (el: HTMLTextAreaElement) => setCaret(el.selectionStart === el.selectionEnd ? el.selectionStart : null);

  /** Put `./name ` where the `./` fragment is (the rest of its word included) and the caret after it. */
  const pick = (s: Skill) => {
    if (!frag || caret === null) return;
    let end = caret;
    while (end < text.length && !/\s/.test(text[end])) end += 1;
    const put = `./${s.name} `;
    const next = text.slice(0, frag.start) + put + text.slice(end).replace(/^ /, "");
    placeCaret.current = frag.start + put.length;
    setCaret(frag.start + put.length);
    setText(next);
  };

  useLayoutEffect(() => {
    ref.current?.focus();
  }, [bot.name, reply?.session_id]);

  // "Ask in chat" from the Runs drawer: the text lands here for the person to edit and send.
  const draft = store.ui.draft;
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
      {picking && <SkillPicker items={items} active={at} onPick={pick} onHover={setActive} popRef={pop} />}
      {slash && (
        <div className="hint" role="note" data-testid="skill-hint">
          <span className="hint-k">/skill</span> {tx("cmp.skillHint", { example: <code>/plan</code>, bot: bot.display_name })}
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
              aria-label={t("cmp.removeReply")}
              title={t("cmp.remove")}
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
          <div className="cm-field">
            <div className="cm-mirror" ref={mirror} aria-hidden="true" data-testid="composer-mirror">
              {tokens.length || picking ? mirrorText(text, tokens, picking && frag ? frag.start : null, anchor) : null}
            </div>
            <textarea
              ref={ref}
              rows={1}
              value={text}
              disabled={offline}
              placeholder={
                offline
                  ? (offlineText ?? t("cmp.offline", { bot: bot.display_name }))
                  : reply
                    ? t("cmp.replyThere", { bot: bot.display_name })
                    : asking
                      ? t("cmp.asking")
                      : t("cmp.message", { bot: bot.display_name })
              }
              aria-label={t("cmp.message", { bot: bot.display_name })}
              data-testid="composer"
              onChange={(e) => {
                setText(e.target.value);
                trackCaret(e.target);
              }}
              onSelect={(e) => trackCaret(e.currentTarget)}
              onScroll={syncMirror}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onPaste={(e) => {
                const files = [...e.clipboardData.files];
                if (!files.length || !onSendFiles) return;
                e.preventDefault();
                add(files);
              }}
              onKeyDown={(e) => {
                const composing = imeComposing(e);
                if (picking && !composing) {
                  const n = items.length;
                  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) {
                    e.preventDefault();
                    setActive((at + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
                    return;
                  }
                  if ((e.key === "Enter" || e.key === "Tab") && !e.shiftKey) {
                    e.preventDefault();
                    if (n) pick(items[at]);
                    else setDismissed(fragKey);
                    return;
                  }
                  if (e.key === "Escape") {
                    e.preventDefault(); // the picker takes Esc, not the running answer
                    setDismissed(fragKey);
                    return;
                  }
                }
                if (e.key === "Enter" && !e.shiftKey && !composing) {
                  e.preventDefault();
                  void send();
                } else if (e.key === "Backspace" && !text && reply) {
                  e.preventDefault();
                  onClearReply?.();
                }
              }}
            />
          </div>
          {tools}
          {action ? (
            action
          ) : showStop ? (
            <button type="button" className="send stop" aria-label={t("cmp.stop")} title={t("cmp.stop")} onClick={onStop} data-testid="stop">
              <StopIcon />
            </button>
          ) : (
            <button
              type="button"
              className="send"
              aria-label={t("cmp.send")}
              title={t("cmp.send")}
              disabled={!has || offline || sending}
              onClick={() => void send()}
              data-testid="send"
            >
              <ArrowUp />
            </button>
          )}
        </div>
      </div>
      {foot}
    </div>
  );
}
