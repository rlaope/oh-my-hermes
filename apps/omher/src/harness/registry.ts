// ONE registry of the harnesses omher can show at work: Hermes itself, and the agent CLIs Hermes hands work to
// (Claude Code, Codex… through ACP, or an OMH fanout export). Each row names its official mark file in
// src/assets/agents (read only through ./assets). Adding a harness = one row here + one asset file.
//
// `harnessOf(facts)` decides WHO is working, in this order:
//   1. an explicit kind or executor / fanout owner (`claude-code` → claude, `codex`, `omp`…); a named kind or
//      executor no row knows → `generic` (kind `hermes` falls through to 3);
//   2. the ACP command's basename (`claude-agent-acp` → claude, `codex-acp` → codex, `gemini --acp` → gemini…);
//   3. otherwise a plain Hermes child: the harness is `hermes`, and the model's maker (Claude, OpenAI, xAI, Z.ai…)
//      is a second, smaller fact (`modelMark`). A Hermes child that merely runs a Claude model is never shown as
//      Claude Code.
// Nothing known at all → `generic` (a neutral mark, never a wrong company's logo).
import { markFor } from "../ui/ModelIcon";

export type HarnessId =
  | "hermes"
  | "claude"
  | "codex"
  | "gemini"
  | "opencode"
  | "kimi"
  | "qwen"
  | "copilot"
  | "cline"
  | "goose"
  | "cursor"
  | "amp"
  | "kilo"
  | "junie"
  | "windsurf"
  | "trae"
  | "roo"
  | "grok"
  | "pi"
  | "omp"
  | "omo"
  | "dsh"
  | "omh"
  | "generic";

export interface Harness {
  id: HarnessId;
  label: string;
  /** Its official mark: a file name in src/assets/agents ("" = the neutral mark). */
  mark: string;
  /** A character mark the vendor ships besides the logo (drawn where a face goes), when there is one. */
  character?: string;
  /** Other names an executor, owner or ACP command uses for it (lower case, without `-acp`). */
  aliases?: string[];
}

export const HARNESSES: readonly Harness[] = [
  { id: "hermes", label: "Hermes", mark: "hermes-agent.png", aliases: ["hermes-agent", "hermes"] },
  { id: "claude", label: "Claude Code", mark: "claudecode-color.svg", aliases: ["claude-code", "claudecode", "claude-agent", "claude-code-acp", "claude-agent-acp"] },
  { id: "codex", label: "Codex", mark: "openai.svg", aliases: ["openai-codex", "codex-cli"] },
  { id: "gemini", label: "Gemini CLI", mark: "geminicli-color.svg", aliases: ["gemini-cli", "geminicli"] },
  { id: "opencode", label: "OpenCode", mark: "opencode.svg", aliases: ["open-code"] },
  { id: "kimi", label: "Kimi Code", mark: "kimi-code.png", aliases: ["kimi-code", "kimi-cli"] },
  { id: "qwen", label: "Qwen Code", mark: "qwen-color.svg", aliases: ["qwen-code"] },
  { id: "copilot", label: "GitHub Copilot", mark: "githubcopilot.svg", aliases: ["github-copilot", "githubcopilot", "copilot-cli"] },
  { id: "cline", label: "Cline", mark: "cline.svg" },
  { id: "goose", label: "Goose", mark: "goose.svg" },
  { id: "cursor", label: "Cursor", mark: "cursor.svg", aliases: ["cursor-agent"] },
  { id: "amp", label: "Amp", mark: "amp-color.svg" },
  { id: "kilo", label: "Kilo Code", mark: "kilocode.svg", aliases: ["kilocode", "kilo-code"] },
  { id: "junie", label: "Junie", mark: "junie-color.svg" },
  { id: "windsurf", label: "Windsurf", mark: "windsurf.svg" },
  { id: "trae", label: "TRAE", mark: "trae-color.svg" },
  { id: "roo", label: "Roo Code", mark: "roocode.svg", aliases: ["roocode", "roo-code"] },
  { id: "grok", label: "Grok", mark: "grok.svg", character: "grokbot.svg", aliases: ["grok-cli"] },
  { id: "pi", label: "pi", mark: "pi.svg" },
  { id: "omp", label: "oh-my-pi", mark: "omp.svg", aliases: ["oh-my-pi"] },
  { id: "omo", label: "OmO", mark: "omo.svg", aliases: ["oh-my-openagent"] },
  { id: "dsh", label: "DSH", mark: "dsh.svg", aliases: ["deepseek-harness"] },
  { id: "omh", label: "oh-my-hermes", mark: "omh.png", aliases: ["oh-my-hermes"] },
  { id: "generic", label: "Agent", mark: "" },
];

const BY_ID = new Map<string, Harness>(HARNESSES.map((h) => [h.id, h]));
const BY_NAME = new Map<string, HarnessId>();
for (const h of HARNESSES) {
  if (h.id === "generic") continue;
  BY_NAME.set(h.id, h.id);
  for (const a of h.aliases ?? []) BY_NAME.set(a, h.id);
}

export function harness(id: string | null | undefined): Harness {
  return BY_ID.get(id ?? "") ?? BY_ID.get("generic")!;
}

/** What a node, a subagent or a session row knows about who ran it. */
export interface HarnessFacts {
  /** The agent CLI the work was handed to (a fanout unit's `owner`, a node's `executor`, a CLI run's agent). */
  executor?: string | null;
  /** The ACP command a Hermes child ran over (`claude-agent-acp`, `/usr/local/bin/codex-acp`, `gemini --acp`). */
  acpCommand?: string | null;
  /** The provider / model the child ran on (Hermes' own subagents). */
  provider?: string | null;
  model?: string | null;
  /** The bridge's own verdict for a session it read (`runs.node_session` kind). */
  kind?: string | null;
}

export interface HarnessIdentity {
  harness: HarnessId;
  /** The model maker's mark id (ModelIcon's), a second smaller fact; null when unknown. */
  modelMark: string | null;
  /** Which fact decided the harness. */
  by: "executor" | "acp" | "model" | "none";
}

/** A name as an executor or a command spells it, to a harness id; null when no row knows it. */
export function harnessByName(name: string | null | undefined): HarnessId | null {
  let s = (name ?? "").trim().toLowerCase();
  if (!s) return null;
  // a command line: its first word's basename
  s = s.split(/\s+/)[0].split(/[\\/]/).pop() ?? "";
  s = s.replace(/\.(exe|cmd|js|mjs|sh)$/, "");
  const direct = BY_NAME.get(s);
  if (direct) return direct;
  const bare = s.replace(/[-_]acp$/, "").replace(/^acp[-_]/, "");
  return BY_NAME.get(bare) ?? null;
}

export function harnessOf(facts: HarnessFacts): HarnessIdentity {
  const modelMark = facts.model || facts.provider ? markFor(facts.model ?? undefined, facts.provider ?? undefined) : null;
  const kind = (facts.kind ?? "").trim();
  const k = harnessByName(kind);
  if (k && k !== "hermes") return { harness: k, modelMark, by: "executor" };
  // a named kind no row knows is an unknown agent, like an unknown executor: neutral, never Hermes by its model
  if (kind && !k) return { harness: "generic", modelMark, by: "executor" };
  // an executor that is named decides, even when no row knows it: an unknown agent CLI is neutral, never Hermes on
  // whatever model it reported
  if ((facts.executor ?? "").trim()) return { harness: harnessByName(facts.executor) ?? "generic", modelMark, by: "executor" };
  if (facts.acpCommand) {
    const acp = harnessByName(facts.acpCommand);
    return { harness: acp ?? "generic", modelMark, by: "acp" };
  }
  if (k === "hermes" || facts.model || facts.provider) return { harness: "hermes", modelMark, by: "model" };
  return { harness: "generic", modelMark, by: "none" };
}
