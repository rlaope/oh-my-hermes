// How long a CLI login has left, from the time its status gives (`loginExpiresAt` of `claude auth status --json`):
// "Login: 12 days left", "Login: 5 h left" under a day, "Login: expired" past it. Within three days the row shows it
// in the theme's danger colour. An unknown or unreadable time shows nothing.
import { t } from "../../i18n";

const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;
/** At or under this long left, the line turns red. */
export const LOGIN_SOON_MS = 3 * DAY;

export type LoginLeft = { text: string; soon: boolean };

export function loginLeft(expiresAt: string | null | undefined, nowMs: number): LoginLeft | null {
  if (!expiresAt) return null;
  const at = Date.parse(expiresAt);
  if (!Number.isFinite(at)) return null;
  const left = at - nowMs;
  if (left <= 0) return { text: t("acc.loginExpired"), soon: true };
  const soon = left <= LOGIN_SOON_MS;
  if (left < DAY) return { text: t("acc.loginHours", { n: Math.max(1, Math.floor(left / HOUR)) }), soon };
  const days = Math.floor(left / DAY);
  return { text: days === 1 ? t("acc.loginDay") : t("acc.loginDays", { n: days }), soon };
}
