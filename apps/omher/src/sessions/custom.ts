// The person's own Agent Client Protocol agents (Settings › Agents) as the UI sees them, and the mock host's stand-in
// for the shell's file (src-tauri/src/custom_agents.rs). The shell owns the real file: it reads and checks it, resolves
// the command the confirm card shows, and writes only after the card's Add. This file holds the shapes it sends, the
// Agents page's model, and, for a browser with no shell (dev, e2e), the same checks over an in-page list.
import { AGENTS, type AgentInfo } from "./agents";
import mockAcpAgents from "./mockAcpAgents.json";
import { t, type Key } from "../i18n";

/** One agent a person added (`CustomAgent` in custom_agents.rs). */
export interface CustomEntry {
  id: string;
  label: string;
  program: string;
  args: string[];
  install: string;
}

/** Why the shell refused an entry (`Why` in custom_agents.rs); the UI shows `ag.why.<code>`. */
export type CustomWhy = "id" | "builtin" | "label" | "program" | "path" | "shim" | "args" | "install" | "opencode" | "kilo" | "dup" | "many" | "shape" | "file" | "interp" | "json";

export const WHYS: readonly CustomWhy[] = ["id", "builtin", "label", "program", "path", "shim", "args", "install", "opencode", "kilo", "dup", "many", "shape", "file", "interp", "json"];

/** An entry of the file that failed its check: skipped, never run, shown so the person can remove it. */
export interface CustomBroken {
  id: string;
  why: CustomWhy;
}

/** Settings › Agents' list: each agent with where its program is now (`path: null` = not found), and the broken ones. */
export interface CustomList {
  agents: AgentInfo[];
  broken: CustomBroken[];
}

/** What the Add agent form holds. `args` is one line, split on spaces by the shell (no shell). */
export interface CustomForm {
  label: string;
  program: string;
  args: string;
  install: string;
}

export const EMPTY_FORM: CustomForm = { label: "", program: "", args: "acp", install: "" };

/** The confirm card: the checked entry, and the exact command omher will run (`null`: not found on the search path).
 *  `by`: the display name of the bot whose reply proposed it (an `omher-agent` draft), shown as one quiet line. */
export interface CustomPreview {
  entry: CustomEntry;
  command: string | null;
  by?: string;
}

/** A refusal the shell sent as `why:<code>`, else null. */
export function whyOf(e: unknown): CustomWhy | null {
  const m = /^why:([a-z]+)$/.exec(e instanceof Error ? e.message : String(e ?? ""));
  return m && (WHYS as readonly string[]).includes(m[1]) ? (m[1] as CustomWhy) : null;
}

/** A refusal in words: the shell's reason translated, else its text as it came. */
export function whyText(e: unknown): string {
  const w = whyOf(e);
  return w ? t(`ag.why.${w}` as Key) : e instanceof Error ? e.message : String(e ?? "");
}

// ---- the Agents page's model -----------------------------------------------------------------

/** Main (Claude Code, Codex, OmO: their own adapters), ACP (the generic agents and OpenCode, on the ACP adapter), or
 *  another built-in. */
export type Tier = "main" | "acp" | "builtin";

export interface BuiltinRow {
  id: string;
  label: string;
  tier: Tier;
  installed: boolean;
}

export interface MineRow {
  id: string;
  label: string;
  /** The command it runs now (the program found, then its arguments), or null when its program is not found. */
  command: string | null;
  program: string;
  args: string[];
}

export interface AgentsPageModel {
  builtins: BuiltinRow[];
  mine: MineRow[];
  broken: CustomBroken[];
}

/** The page's rows: every built-in and generic ACP agent read-only with its tier and whether it is installed (main,
 *  then the other built-ins, then the ACP ones), then the person's own agents and the broken entries. */
export function agentsPageModel(agents: AgentInfo[] | null, custom: CustomList | null): AgentsPageModel {
  const listed = (agents ?? []).filter((a) => !a.acp?.custom);
  const builtins: BuiltinRow[] = listed
    .filter((a) => AGENTS.some((d) => d.id === a.id) || !!a.acp)
    .map((a) => {
      const def = AGENTS.find((d) => d.id === a.id);
      const tier: Tier = def?.main ? "main" : a.acp || a.id === "opencode" ? "acp" : "builtin";
      return { id: a.id, label: a.label, tier, installed: !!a.path };
    });
  const rank: Record<Tier, number> = { main: 0, builtin: 1, acp: 2 };
  builtins.sort((x, y) => rank[x.tier] - rank[y.tier]);
  const mine: MineRow[] = (custom?.agents ?? []).map((a) => ({
    id: a.id,
    label: a.label,
    program: a.acp?.program ?? a.id,
    args: a.acp?.args ?? [],
    command: a.path ? [a.path, ...(a.acp?.args ?? [])].join(" ") : null,
  }));
  return { builtins, mine, broken: custom?.broken ?? [] };
}

/** The command line the confirm card shows: exactly what the shell will run, or the not-found line. */
export function cardCommand(p: CustomPreview): string {
  return p.command ?? t("ag.notFound", { program: p.entry.program });
}

// ---- the mock host's file (a browser has no shell) ---------------------------------------------

const ID = /^[a-z0-9][a-z0-9-]{0,31}$/;
const BARE = /^[A-Za-z0-9._-]{1,64}$/;
const ARG = /^[A-Za-z0-9._=/:-]{1,64}$/;
const ABS = /^\/[A-Za-z0-9._/@+-]+$/;
const LABEL = /^[\p{L}\p{N} ._+-]{1,40}$/u;
const INSTALL = /^[A-Za-z0-9._=/:@+ -]{0,200}$/;

const RESERVED = new Set<string>(["kilo", ...AGENTS.map((a) => a.id), ...mockAcpAgents.map((r) => r.id)]);

/** The shell's check of one entry (custom_agents.rs `check`), for the mock host. `found` says an absolute path is an
 *  executable file. */
export function mockCheck(c: unknown, found: (path: string) => boolean): CustomWhy | null {
  if (!c || typeof c !== "object") return "shape";
  const e = c as Partial<CustomEntry>;
  if (typeof e.id !== "string" || typeof e.label !== "string" || typeof e.program !== "string" || !Array.isArray(e.args)) return "shape";
  if (!ID.test(e.id)) return "id";
  if (RESERVED.has(e.id)) return "builtin";
  if (!LABEL.test(e.label) || e.label.trim() !== e.label) return "label";
  const base = e.program.split("/").pop()!.toLowerCase();
  if (base === "opencode") return "opencode";
  if (base === "kilo" || base === "kilocode") return "kilo";
  if (!(BARE.test(e.program) && /[A-Za-z0-9]/.test(e.program))) {
    if (!ABS.test(e.program) || e.program.split("/").includes("..")) return "program";
    if (!found(e.program)) return "path";
  }
  if (e.args.length > 8 || !e.args.every((a) => typeof a === "string" && ARG.test(a))) return "args";
  if (typeof (e.install ?? "") !== "string" || !INSTALL.test(e.install ?? "") || (e.install ?? "").trim() !== (e.install ?? "")) return "install";
  return null;
}

/** Shells, interpreters and launchers a bot's draft may not name (custom_agents.rs `INTERPRETERS`); a person may
 *  still type one in the form. */
export const INTERPRETERS: readonly string[] = [
  "sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "cmd", "powershell", "pwsh", "python", "python3", "node", "deno", "bun", "ruby", "perl",
  "php", "osascript", "env", "sudo", "doas", "open", "xargs",
];

/** The program's file name without folder or `.exe`, lower-cased (custom_agents.rs `base_name`). */
export function programBase(p: string): string {
  const name = (p.trim().split(/[/\\]/).pop() ?? "").toLowerCase();
  return name.endsWith(".exe") ? name.slice(0, -4) : name;
}

/** What a bot's draft adds to the form's checks (custom_agents.rs `bot_draft`): no shell or interpreter, OpenCode
 *  and Kilo Code by name, and no built-in agent's program. */
export function botRefusal(program: string): CustomWhy | null {
  const base = programBase(program);
  if (INTERPRETERS.includes(base)) return "interp";
  if (base === "opencode") return "opencode";
  if (base === "kilo" || base === "kilocode") return "kilo";
  if (AGENTS.some((a) => a.id === base || a.program === base) || mockAcpAgents.some((r) => r.id === base || r.program === base)) return "builtin";
  return null;
}

/** An id from the name (else the program), free of the built-ins' and of the ids taken (custom_agents.rs `new_id`). */
export function mockNewId(label: string, program: string, taken: string[]): string {
  const slug = (s: string) =>
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 28)
      .replace(/-+$/, "");
  let base = slug(label) || slug(program.split("/").pop() ?? "") || "agent";
  const free = (id: string) => ID.test(id) && !RESERVED.has(id) && !taken.includes(id);
  if (free(base)) return base;
  for (let n = 2; n < 100; n++) if (free(`${base}-${n}`)) return `${base}-${n}`;
  base = `${base}-x`;
  return base;
}
