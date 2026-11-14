// A bot's agent draft: a fenced ```omher-agent block in its reply holding one JSON object
// `{"name": "...", "program": "...", "args": ["acp"], "install": "..."}` (unknown keys ignored). The block still
// renders as a code block; each one also gets an "Add agent" chip under the reply (AgentChip.tsx) that opens
// Settings › Agents' own confirm card, filled from the draft and checked again by the shell. Nothing is written until
// that card's Add. Drafts are read only from bot replies in a bot's main chat and in Hermes folder chats, never from
// tool output, Slack/Discord mirrors (elsewhere lines) or a CLI agent's session chat.
import { botRefusal, mockCheck, type CustomWhy } from "../../sessions/custom";

/** One draft as the bot wrote it: the fields the confirm card takes, nothing else. */
export interface AgentDraft {
  name: string;
  program: string;
  args: string[];
  install: string;
}

/** A draft block found in a reply: the draft, or why it cannot be one (`ag.why.<code>`; `json`: not one JSON object). */
export type DraftBlock = { draft: AgentDraft; why: null } | { draft: AgentDraft | null; why: CustomWhy };

/** A ```omher-agent fence (or ~~~), from its opening line to its closing one. */
const FENCE = /^ {0,3}(`{3,}|~{3,})[ \t]*omher-agent[ \t]*\r?\n([\s\S]*?)\r?\n {0,3}\1[ \t]*$/gm;

/** Each ```omher-agent block of `text`, in order, checked as the shell will check it again. */
export function parseDrafts(text: string): DraftBlock[] {
  return [...text.matchAll(FENCE)].map((m) => parseOne(m[2]));
}

function parseOne(body: string): DraftBlock {
  let v: unknown;
  try {
    v = JSON.parse(body);
  } catch {
    return { draft: null, why: "json" };
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return { draft: null, why: "json" };
  const o = v as Record<string, unknown>;
  const install = o.install ?? "";
  const args = o.args ?? [];
  if (typeof o.name !== "string" || typeof o.program !== "string" || typeof install !== "string" || !Array.isArray(args) || !args.every((a) => typeof a === "string"))
    return { draft: null, why: "shape" };
  const draft: AgentDraft = { name: o.name.trim(), program: o.program.trim(), args: args as string[], install: install.trim() };
  // stricter than the form first (a shell or interpreter, OpenCode, Kilo Code, a built-in's program), then the form's
  // own checks (whether an absolute path is a program here is the shell's to say)
  const why = botRefusal(draft.program) ?? mockCheck({ id: "draft", label: draft.name, program: draft.program, args: draft.args, install: draft.install }, () => true);
  return why ? { draft, why } : { draft, why: null };
}

/** Chats whose bot replies may carry drafts: a bot's main chat (its profile name) and a Hermes folder chat (`fold:`);
 *  never a CLI agent's session chat (`agent:`). */
export const draftsAllowed = (chatKey: string): boolean => chatKey.startsWith("fold:") || !chatKey.includes(":");

/** The bot a chat belongs to (its main chat, or the bot a folder chat runs on), for the card's "Proposed by" line. */
export const draftBot = (chatKey: string): string => (chatKey.startsWith("fold:") ? chatKey.slice(5).split(":")[0] : chatKey);
