// Add bot › New bot: the name rule and the one message a template sends (BOUNDARY rule 44). The bridge checks the
// name again and runs Hermes' own `hermes -p default profile create <name> --no-alias`; the page only shapes what it
// sends.

/** Hermes' profile id grammar (`hermes_constants.PROFILE_ID_RE`), the one `validate_profile_name` checks. */
export const PROFILE_NAME = /^[a-z0-9][a-z0-9_-]{0,63}$/;
/** Names Hermes keeps for itself (`hermes_cli/profiles.py` `_RESERVED_NAMES`); `default` is the main profile. */
export const PROFILE_RESERVED: readonly string[] = ["hermes", "default", "test", "tmp", "root", "sudo"];
/** OMH's own TUI runtime profile (`TUI_PROFILE`): neither `omh update` nor `omh apply --profile` gives it OMH's skills. */
export const OMH_PROFILES: readonly string[] = ["omh-tui"];
/** OMH's one-profile registration (`omh apply --profile`): the command the page shows, never runs. */
export const skillSyncCmd = (bot: string) => `omh apply --profile ${bot}`;
/** The skill that applies a template, as the `/command` Hermes registers for it. */
export const APPLY_SKILL = "omh-bot-template";
/** A template id as OMH's catalog writes it. */
const TEMPLATE_ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

/** Hermes reads a typed name trimmed and lowercased (`normalize_profile_name`); the page shows that name. */
export function normalizeName(raw: string): string {
  return raw.trim().toLowerCase();
}

export type NameCheck = "ok" | "empty" | "rule" | "reserved" | "omh" | "taken";

/** Whether `name` (already normalized) can be a new bot: Hermes' own rule, then the bots this computer has. */
export function checkName(name: string, taken: Iterable<string>): NameCheck {
  if (!name) return "empty";
  if (!PROFILE_NAME.test(name)) return "rule";
  if (PROFILE_RESERVED.includes(name)) return "reserved";
  if (OMH_PROFILES.includes(name)) return "omh";
  for (const t of taken) if (t === name) return "taken";
  return "ok";
}

/**
 * The one message sent to the new bot's main chat: the skill's own `/command`, so the bot loads it whatever the router
 * picks, and the template id; the skill does the rest with the bot's approvals. Built here from the id alone, never
 * from text the catalog sent. The same text as OMH's `apply_message` (tests/test_omher_boundary.py pins both).
 */
export function applyMessage(templateId: string): string {
  if (!TEMPLATE_ID.test(templateId)) throw new Error(`not a template id: ${templateId}`);
  return `/${APPLY_SKILL} Apply the bot template \`${templateId}\` to this bot.`;
}
