import kami from "../assets/avatars/bot-kami.svg";
import friren from "../assets/avatars/bot-friren.svg";
import hermes from "../assets/avatars/bot-hermes.svg";
import fresh from "../assets/avatars/bot-new.svg";

/** The four circle-with-eyes avatars. Known bots get their own; others get one picked by name. */
const KNOWN: Record<string, string> = { kami, friren, default: hermes, hermes };
const POOL = [kami, friren, hermes, fresh];

export function avatarFor(bot: string): string {
  const k = KNOWN[bot.toLowerCase()];
  if (k) return k;
  let h = 0;
  for (const ch of bot) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return POOL[h % POOL.length];
}

export function Avatar({ bot, size = 32, className }: { bot: string; size?: number; className?: string }) {
  return (
    <img
      className={`ui-av${className ? ` ${className}` : ""}`}
      src={avatarFor(bot)}
      width={size}
      height={size}
      style={{ width: size, height: size }}
      alt=""
      draggable={false}
    />
  );
}
