import { useEffect, useState } from "react";
import blob from "../assets/avatars/face-blob.svg";
import ghost from "../assets/avatars/face-ghost.svg";
import mochi from "../assets/avatars/face-mochi.svg";
import star from "../assets/avatars/face-star.svg";
import { getStore, useStore } from "../state/store";

/** The four built-in faces (blob, ghost, mochi, star). Known bots keep a fixed one; others get one by name. */
const KNOWN: Record<string, string> = { kami: blob, friren: ghost, default: mochi, hermes: mochi };
const POOL = [blob, ghost, mochi, star];

export function avatarFor(bot: string): string {
  const k = KNOWN[bot.toLowerCase()];
  if (k) return k;
  let h = 0;
  for (const ch of bot) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return POOL[h % POOL.length];
}

// The bot's own picture (Hermes keeps it in the profile as assets/avatar.*), fetched once per revision
// and shared by every <Avatar> of that bot.
const cache = new Map<string, Promise<string | null>>();
const ready = new Map<string, string | null>();

function pictureOf(bot: string, rev: number): Promise<string | null> {
  const key = `${bot}:${rev}`;
  let p = cache.get(key);
  if (!p) {
    p = getStore()
      .actions.avatarOf(bot)
      .then((r) => r.data)
      .catch(() => null)
      .then((d) => {
        ready.set(key, d);
        return d;
      });
    cache.set(key, p);
  }
  return p;
}

/** The picture to show for a bot: its own when it has one, else its built-in face. */
export function useAvatarSrc(bot: string): string {
  return useAvatar(bot).src;
}

function useAvatar(bot: string): { src: string; own: boolean } {
  const s = useStore();
  const rev = s.bots.find((b) => b.name === bot)?.avatar_rev ?? null;
  const [own, setOwn] = useState<string | null>(rev === null ? null : ready.get(`${bot}:${rev}`) ?? null);
  useEffect(() => {
    if (rev === null) {
      setOwn(null);
      return;
    }
    let live = true;
    setOwn(ready.get(`${bot}:${rev}`) ?? null);
    void pictureOf(bot, rev).then((d) => {
      if (live) setOwn(d);
    });
    return () => {
      live = false;
    };
  }, [bot, rev]);
  return own ? { src: own, own: true } : { src: avatarFor(bot), own: false };
}

export function Avatar({ bot, size = 32, className }: { bot: string; size?: number; className?: string }) {
  const { src, own } = useAvatar(bot);
  return (
    <img
      className={`ui-av${className ? ` ${className}` : ""}`}
      src={src}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      alt=""
      draggable={false}
      data-own={own ? "1" : undefined}
    />
  );
}
