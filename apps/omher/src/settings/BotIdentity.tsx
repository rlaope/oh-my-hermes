// Bot identity editing: picture and display name, plus the read-only "what this bot has done" facts.
// Used by the bot page in Settings. Only presentation changes: the Hermes profile id never moves.
import { useEffect, useRef, useState } from "react";
import type { Bot, BotInfo } from "../lib/protocol";
import { useStore } from "../state/store";
import { Avatar, Spinner } from "../ui";
import { shortTime } from "../app/time";

const SIDE = 256;
const KINDS = ["image/png", "image/jpeg", "image/webp"];

/** Center-crop to a square and scale to 256px PNG, so any photo fits Hermes' 2 MB cap and reads round. */
export async function squarePicture(file: Blob): Promise<string> {
  if (!KINDS.includes(file.type)) throw new Error("Use a PNG, JPEG or WebP picture");
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = () => rej(new Error("Could not read that picture"));
      i.src = url;
    });
    const side = Math.min(img.naturalWidth, img.naturalHeight);
    const c = document.createElement("canvas");
    c.width = c.height = SIDE;
    const ctx = c.getContext("2d");
    if (!ctx) throw new Error("Could not read that picture");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, SIDE, SIDE);
    return c.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

const msg = (e: unknown) =>
  typeof e === "object" && e && "message" in e ? String((e as { message: unknown }).message) : String(e);

/** Picture editing state shared by the big avatar (click or drop) and the inline "Change picture" link. */
export function usePictureEditor(bot: Bot) {
  const s = useStore();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const apply = async (file: Blob | null | undefined) => {
    if (!file) return;
    setErr("");
    setBusy(true);
    try {
      await s.setAvatar(bot.name, await squarePicture(file));
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(false);
    }
  };
  const reset = async () => {
    setErr("");
    setBusy(true);
    try {
      await s.setAvatar(bot.name, null);
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(false);
    }
  };
  const pick = () => input.current?.click();
  const fileInput = (
    <input
      ref={input}
      type="file"
      accept={KINDS.join(",")}
      hidden
      data-testid="avatar-file"
      onChange={(e) => {
        void apply(e.target.files?.[0]);
        e.target.value = "";
      }}
    />
  );
  return { busy, err, apply, reset, pick, fileInput, own: bot.avatar_rev != null };
}

/** The bot's picture, 64px: click or drop a picture on it; a camera shows on hover. */
export function AvatarEditor({ bot, ed }: { bot: Bot; ed: ReturnType<typeof usePictureEditor> }) {
  const [over, setOver] = useState(false);
  const { busy, apply, pick } = ed;
  return (
    <div className="be-av-wrap">
      <button
        type="button"
        className={`be-av${over ? " over" : ""}`}
        onClick={pick}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          void apply(e.dataTransfer.files?.[0]);
        }}
        disabled={busy}
        title="Change picture"
        aria-label={`Change ${bot.display_name}'s picture`}
        data-testid="avatar-edit"
      >
        <Avatar bot={bot.name} size={64} />
        <span className="be-av-cover" aria-hidden="true">
          {busy ? <Spinner size={14} label="Saving picture" /> : <CameraIcon />}
        </span>
      </button>
      {ed.fileInput}
    </div>
  );
}

/** Inline picture actions next to Open chat, plus the error line when a picture was refused. */
export function PictureActions({ ed }: { ed: ReturnType<typeof usePictureEditor> }) {
  return (
    <>
      <button type="button" className="be-link" onClick={ed.pick} disabled={ed.busy} data-testid="avatar-change">
        Change picture
      </button>
      {ed.own && (
        <button type="button" className="be-link" onClick={() => void ed.reset()} disabled={ed.busy} data-testid="avatar-reset">
          Use default face
        </button>
      )}
      {ed.err && (
        <span className="be-err" role="alert" data-testid="avatar-error">
          {ed.err}
        </span>
      )}
    </>
  );
}

/** The bot's name, shown big; the pencil turns it into a field (Enter saves, Escape cancels). */
export function NameEditor({ bot }: { bot: Bot }) {
  const s = useStore();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(bot.display_name);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setValue(bot.display_name);
  }, [bot.display_name, editing]);
  useEffect(() => {
    if (editing) field.current?.select();
  }, [editing]);

  const save = async () => {
    const next = value.trim();
    if (next === bot.display_name) {
      setEditing(false);
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await s.renameBot(bot.name, next);
      setEditing(false);
    } catch (e) {
      setErr(msg(e));
    } finally {
      setBusy(false);
    }
  };

  if (!editing)
    return (
      <div className="be-name">
        <b data-testid="bot-name">{bot.display_name}</b>
        <button type="button" className="be-pen" onClick={() => setEditing(true)} aria-label="Rename" title="Rename" data-testid="rename">
          <PenIcon />
        </button>
      </div>
    );
  return (
    <div className="be-name-edit">
      <input
        ref={field}
        value={value}
        maxLength={64}
        placeholder={bot.name}
        aria-label="Bot name"
        data-testid="rename-input"
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
          if (e.key === "Escape") {
            setEditing(false);
            setErr("");
          }
        }}
      />
      <button type="button" className="st-btn" onClick={() => void save()} disabled={busy} data-testid="rename-save">
        {busy ? "Saving…" : "Save"}
      </button>
      <button type="button" className="be-link quiet" onClick={() => setEditing(false)} disabled={busy}>
        Cancel
      </button>
      <div className="be-hint">
        {err ? (
          <span className="be-err" role="alert">
            {err}
          </span>
        ) : (
          <>
            Only the name apps show changes. The profile stays <code>{bot.name}</code>; leave it empty to use that.
          </>
        )}
      </div>
    </div>
  );
}

const SOURCE: Record<string, string> = { slack: "Slack", discord: "Discord", cron: "Cron", telegram: "Telegram" };
export const placeName = (src: string) => SOURCE[src] ?? src.charAt(0).toUpperCase() + src.slice(1);

export function sinceLabel(ts: number | null): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Read-only facts for the bot page: where it works (sessions per place), skills, routines, since when. */
export function useBotInfo(bot: Bot): BotInfo | null | undefined {
  const s = useStore();
  const [info, setInfo] = useState<BotInfo | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    setInfo(undefined);
    s.botInfo(bot.name).then(
      (r) => live && setInfo(r),
      () => live && setInfo(null),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.name]);
  return info;
}

export function BotFacts({ info }: { info: BotInfo | null | undefined }) {
  if (info === undefined)
    return (
      <div className="be-facts" data-testid="bot-facts">
        <Spinner size={12} label="Loading" />
      </div>
    );
  if (info === null) return <div className="be-facts muted">Could not read this profile.</div>;
  const places = Object.entries(info.places);
  const total = places.reduce((a, [, n]) => a + n, 0);
  return (
    <div className="be-facts" data-testid="bot-facts">
      <div className="be-stats">
        <Stat n={total} label={total === 1 ? "session elsewhere" : "sessions elsewhere"} />
        <Stat n={info.skills} label={info.skills === 1 ? "skill" : "skills"} />
        <Stat n={info.routines} label={info.routines === 1 ? "routine" : "routines"} />
        <Stat text={info.last_active ? shortTime(info.last_active) : "—"} label="last active" />
      </div>
      {places.length > 0 && (
        <div className="be-places" data-testid="bot-places">
          {places.map(([src, n]) => (
            <span key={src} className="be-place">
              <i className={`src-sq src-${src}`} />
              {placeName(src)}
              <b>{n}</b>
            </span>
          ))}
          {info.first_active && <span className="be-since">since {sinceLabel(info.first_active)}</span>}
        </div>
      )}
    </div>
  );
}

function Stat({ n, text, label }: { n?: number; text?: string; label: string }) {
  return (
    <div className="be-stat">
      <b>{text ?? (n ?? 0).toLocaleString("en-US")}</b>
      <span>{label}</span>
    </div>
  );
}

function CameraIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M2.5 5.2h2.2l1.1-1.7h4.4l1.1 1.7h2.2v7.3h-11z" strokeLinejoin="round" />
      <circle cx="8" cy="8.7" r="2.3" />
    </svg>
  );
}

function PenIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
      <path d="M8.2 1.8l2 2-6.4 6.4-2.5.5.5-2.5z" strokeLinejoin="round" />
    </svg>
  );
}
