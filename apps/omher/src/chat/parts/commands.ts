// The `/` menu of a SESSIONS chat: the commands and skills the agent itself reported (`session.commands`, one shape
// for every adapter: Claude Code's initialize, Codex's skills/list, the rpc agents' get_commands, ACP agents), and
// how the composer narrows them as the person types. Lists run to several hundred entries: the menu shows at most
// MENU_MAX rows and says how many more match.

export interface AgentCommand {
  name: string;
  description: string;
  /** what it takes after its name (`<file>`), "" for nothing */
  hint: string;
  kind: "command" | "skill";
  /** what the person types before the name */
  prefix: "/" | "$";
}

/** Commands from a `session.commands` event, cleaned: names kept once (the first wins), odd entries dropped. */
export function parseCommands(raw: unknown): AgentCommand[] {
  const out: AgentCommand[] = [];
  const seen = new Set<string>();
  for (const c of Array.isArray(raw) ? raw : []) {
    if (!c || typeof c !== "object") continue;
    const o = c as Record<string, unknown>;
    const name = typeof o.name === "string" ? o.name.trim() : "";
    const prefix = o.prefix === "$" ? "$" : "/";
    if (!name || /\s/.test(name) || seen.has(prefix + name)) continue;
    seen.add(prefix + name);
    out.push({
      name,
      description: typeof o.description === "string" ? o.description : "",
      hint: typeof o.hint === "string" ? o.hint : "",
      kind: o.kind === "skill" ? "skill" : "command",
      prefix,
    });
  }
  return out;
}

/** Rows the `/` menu shows at most; typing narrows the list. */
export const MENU_MAX = 50;

/** What the person is typing for the menu: `/` or `$` at the very start of the box and the word after it, or null. */
export function commandQuery(text: string): { prefix: "/" | "$"; query: string } | null {
  const m = /^([/$])([\w:.-]*)$/.exec(text);
  return m ? { prefix: m[1] as "/" | "$", query: m[2] } : null;
}

/** Commands for a query: names that start with it first, then names that contain it, then a description that does;
 *  `/` lists every entry (skills typed with `$` too, shown with their own prefix), `$` only `$` entries. */
export function matchCommands(list: readonly AgentCommand[], prefix: "/" | "$", query: string, max = MENU_MAX): { shown: AgentCommand[]; total: number } {
  const q = query.toLowerCase();
  const pool = prefix === "$" ? list.filter((c) => c.prefix === "$") : list;
  const starts: AgentCommand[] = [];
  const has: AgentCommand[] = [];
  const said: AgentCommand[] = [];
  for (const c of pool) {
    const n = c.name.toLowerCase();
    if (n.startsWith(q)) starts.push(c);
    else if (n.includes(q)) has.push(c);
    else if (q && c.description.toLowerCase().includes(q)) said.push(c);
  }
  const all = [...starts, ...has, ...said];
  return { shown: all.slice(0, max), total: all.length };
}

/** The box's text after a pick: the command with its prefix and a space, ready for its argument. */
export const pickText = (c: AgentCommand) => `${c.prefix}${c.name} `;
