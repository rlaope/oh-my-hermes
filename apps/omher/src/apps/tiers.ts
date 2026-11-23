// The Apps page's groups and names: which of Hermes' MCP catalog entries and integration skills are surfaced first
// (the tiers of the platform list), each one's display name and mark, and what a card offers for each state. Pure
// data and functions, so the page and its tests read the same thing.
import type { AppRow, AppSkill } from "../lib/protocol";

export type Tier = "work" | "ops" | "more";
export const TIERS: readonly Tier[] = ["work", "ops", "more"];

/** Tier 1: shipped by Hermes and surfaced first (catalog entries and bundled skills). */
const WORK = new Set([
  "notion", "linear", "atlassian", "figma", "sentry", "gitlab", "todoist", "asana", "clickup",
  "google-workspace", "obsidian", "apple-notes", "apple-reminders", "microsoft-office", "teams-meeting-pipeline",
  "himalaya", "email-inbox-triage", "meeting-action-items", "agentmail", "siyuan", "box",
]);
/** Tier 2: in the catalog, ops and data. */
const OPS = new Set([
  "datadog", "grafana", "betterstack", "vercel", "netlify", "cloudflare", "railway", "supabase", "neon",
  "prisma-postgres", "motherduck", "circleci", "buildkite", "semgrep", "amplitude", "mixpanel", "airtable", "dropbox",
  "miro", "intercom", "fireflies", "monday", "stripe", "postman", "context7", "deepwiki",
]);

export function tierOf(name: string): Tier {
  return WORK.has(name) ? "work" : OPS.has(name) ? "ops" : "more";
}

/** Product names as their makers write them; any other entry's own name, capitalised, with spaces for `-` and `_`. */
const TITLES: Record<string, string> = {
  atlassian: "Jira and Confluence",
  betterstack: "Better Stack",
  circleci: "CircleCI",
  clickup: "ClickUp",
  context7: "Context7",
  deepwiki: "DeepWiki",
  gitlab: "GitLab",
  "google-workspace": "Google Workspace",
  "hugging_face": "Hugging Face",
  "apple-notes": "Apple Notes",
  "apple-reminders": "Apple Reminders",
  "microsoft-office": "Microsoft Office",
  "microsoft-learn": "Microsoft Learn",
  "teams-meeting-pipeline": "Microsoft Teams meetings",
  himalaya: "Email (IMAP/SMTP)",
  "email-inbox-triage": "Inbox triage",
  "meeting-action-items": "Meeting action items",
  agentmail: "AgentMail",
  siyuan: "SiYuan",
  motherduck: "MotherDuck",
  "prisma-postgres": "Prisma Postgres",
  "n8n-official": "n8n",
  paypal: "PayPal",
  "wordpress-com": "WordPress.com",
  "aws-knowledge": "AWS Knowledge",
  "twilio-docs": "Twilio Docs",
  "twelve-data": "Twelve Data",
  "comfy-cloud": "Comfy Cloud",
  "unreal-engine": "Unreal Engine",
  alltrails: "AllTrails",
};

export function titleOf(name: string): string {
  if (TITLES[name]) return TITLES[name];
  const words = name.replace(/[-_]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

/** The service mark a card draws (brandIcons.tsx); anything else draws the globe. */
const MARKS: Record<string, string> = {
  notion: "notion",
  linear: "linear",
  figma: "figma",
  "google-workspace": "google",
  himalaya: "gmail",
};
export const markOf = (name: string): string => MARKS[name] ?? name;

/** What a catalog entry's card offers: Connect, Sign in (again) and Remove, each only where it means something. A state
 *  omher could not read offers nothing, and neither does an install only a terminal can answer (the card shows its
 *  command). */
export function actionsOf(app: Pick<AppRow, "auth" | "state" | "terminal" | "device">): ("install" | "login" | "remove")[] {
  // a device-code sign-in shows its code only in a terminal: the card shows `hermes mcp login` instead of Sign in
  const login = app.auth === "oauth" && !app.device ? (["login"] as const) : [];
  switch (app.state) {
    case "available":
      // a value Hermes can only ask in a terminal: Connect would always fail, so the card shows the command instead
      return app.terminal ? [] : ["install"];
    case "needs_signin":
      return [...login, "remove"];
    case "installed":
      return [...login, "remove"];
    case "disabled":
      return ["remove"];
    default:
      return [];
  }
}

export type Card =
  | { kind: "mcp"; tier: Tier; app: AppRow }
  | { kind: "skill"; tier: Tier; skill: AppSkill };

/** The page's sections in order (work, ops, more), each card sorted with what the bot already has first, then by
 *  name; `query` keeps the cards whose name, title or description has it. Empty sections are left out. */
export function sections(apps: AppRow[], skills: AppSkill[], query = ""): { tier: Tier; cards: Card[] }[] {
  const q = query.trim().toLowerCase();
  const hit = (name: string, desc: string) =>
    !q || name.toLowerCase().includes(q) || titleOf(name).toLowerCase().includes(q) || desc.toLowerCase().includes(q);
  const cards: Card[] = [
    ...apps.filter((a) => hit(a.name, a.description)).map((app): Card => ({ kind: "mcp", tier: tierOf(app.name), app })),
    ...skills.filter((s) => hit(s.name, s.description)).map((skill): Card => ({ kind: "skill", tier: tierOf(skill.name), skill })),
  ];
  const nameOf = (c: Card) => (c.kind === "mcp" ? c.app.name : c.skill.name);
  const has = (c: Card) => (c.kind === "mcp" ? c.app.state !== "available" : c.skill.state !== "available");
  return TIERS.map((tier) => ({
    tier,
    cards: cards
      .filter((c) => c.tier === tier)
      .sort((a, b) => Number(has(b)) - Number(has(a)) || titleOf(nameOf(a)).localeCompare(titleOf(nameOf(b)))),
  })).filter((s) => s.cards.length > 0);
}
