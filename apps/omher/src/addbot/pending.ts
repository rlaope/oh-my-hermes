// A bot template the person chose for a new bot that could not apply it yet (it had no oh-my-hermes skills before
// `omh apply --profile <name>` or the next `omh update`). Kept in this computer's storage for the app (`omher.pendingTemplates`, bot -> template id) so the
// bot's page can offer Apply template later; a convenience only, an empty or unreadable store offers nothing.
import { getStore } from "../state/store";
import { withBridge } from "./bots";
import { APPLY_SKILL, applyMessage } from "./templates";

export const PENDING_KEY = "omher.pendingTemplates";
const TEMPLATE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

function read(): Record<string, string> {
  try {
    const raw = JSON.parse(localStorage.getItem(PENDING_KEY) ?? "{}");
    if (!raw || typeof raw !== "object") return {};
    return Object.fromEntries(Object.entries(raw).filter(([, v]) => typeof v === "string" && TEMPLATE_ID.test(v))) as Record<string, string>;
  } catch {
    return {};
  }
}

function write(all: Record<string, string>): void {
  try {
    localStorage.setItem(PENDING_KEY, JSON.stringify(all));
  } catch {
    /* storage refused: the page simply offers nothing later */
  }
}

export function pendingTemplate(bot: string): string | null {
  return read()[bot] ?? null;
}

export function setPendingTemplate(bot: string, template: string): void {
  write({ ...read(), [bot]: template });
}

export function clearPendingTemplate(bot: string): void {
  const all = read();
  delete all[bot];
  write(all);
}

/** Whether the bot's own skill folders hold the template skill (rule 19's read, `skills.list`). */
export async function hasApplySkill(bot: string): Promise<boolean> {
  const { skills } = await withBridge((b) => b.request("skills.list", { bot }));
  return skills.some((s) => s.name === APPLY_SKILL);
}

/**
 * Send the one apply message to `bot`'s main chat, only once the bot has the template skill. Returns false (and sends
 * nothing) while it does not; the template then stays pending for the bot's page.
 */
export async function applyTemplate(bot: string, template: string): Promise<boolean> {
  if (!(await hasApplySkill(bot).catch(() => false))) {
    setPendingTemplate(bot, template);
    return false;
  }
  const store = getStore();
  const text = applyMessage(template);
  let failed = false;
  try {
    await store.actions.sendTo(bot, text);
    // `send` keeps a failed send in the chat with its error rather than throwing
    const items = store.getState().chats[bot]?.items ?? [];
    const mine = [...items].reverse().find((i) => i.kind === "user" && i.text === text);
    failed = !!mine && "error" in mine && !!mine.error;
  } catch {
    failed = true;
  }
  if (failed) {
    // it did not go out: it stays pending, and the page offers Apply template again
    setPendingTemplate(bot, template);
    return false;
  }
  clearPendingTemplate(bot);
  return true;
}
