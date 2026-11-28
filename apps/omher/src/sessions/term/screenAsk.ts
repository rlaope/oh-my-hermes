// A coding agent stopped on its permission dialog or a choice menu, read off its terminal's screen: Claude Code's
// "Do you want to proceed? ❯ 1. Yes … 4. No" and Codex's "Would you like to run the following command? › 1. Yes,
// proceed (y) …". Pure: the caller hands it the screen's visible lines (top to bottom) and the program in front.
//
// Only a dialog at the bottom of the screen is live: after its last option at most a few lines follow, all of them
// the dialog's own key hints ("Esc to cancel · Tab to amend", "Press enter to confirm or esc to cancel"). One that
// output has pushed up (answered, then more printed) is history. A half-drawn frame (options without the hint line
// under them yet) is not a dialog either, and the debounce below holds a detection until a second read agrees.
// Any other program (a shell printing the same words) never counts.

export type ScreenAskKind = "approve" | "question";

export interface ScreenAsk {
  kind: ScreenAskKind;
  /** one line: "Bash command: touch probe.txt", "Edit notes.md", "$ touch probe.txt" */
  title: string;
  /** the option labels as numbered on screen, without their numbers or key hints */
  options: string[];
  /** the same dialog reads the same key (title and options) */
  key: string;
}

/** The programs whose dialogs are read. */
export const ASK_AGENTS: readonly string[] = ["claude", "codex"];

/** The dialog's options end at most this many lines above the screen's last line with text. */
const TAIL_MAX = 3;
/** How far above the options the title and question are looked for. */
const HEAD_MAX = 16;
const TITLE_MAX = 120;

const OPTION = /^\s*([❯›>])?\s*(\d{1,2})\.\s+(.*\S)\s*$/;
/** a line under the options that is the dialog's key hints */
const HINT = /\b(esc|enter|confirm|cancel|navigate|tab to)\b/i;
/** a dialog's own question line: "Do you want to proceed?", "Would you like to run the following command?" */
const QUESTION_LEAD = /^(do you want|would you like)\b.*\?$/i;
const APPROVE = /^(do you want to (proceed|make this edit|create|run|allow|fetch|delete|overwrite)|would you like to (run|make|apply|allow|grant)|allow |approve )/i;
/** the solid rule above a Claude Code dialog (its dashed ones frame the command inside it) */
const RULE = /^[─━]{8,}$/;

const clip = (s: string) => (s.length > TITLE_MAX ? `${s.slice(0, TITLE_MAX - 1)}…` : s);
/** "Yes, proceed (y)" -> "Yes, proceed"; "No (esc)" -> "No"; "Yes · auto mode handles…" -> "Yes" */
const label = (s: string) => s.replace(/\s+/g, " ").replace(/ · .*$/, "").replace(/\s+\((?:[a-z]|esc|enter|tab)\)$/i, "").trim();

/** The live dialog on this screen, or null. `agent` is the program in front (the row's agent, or the CLI its shell
 *  runs); anything but Claude Code or Codex reads null. */
export function screenAsk(lines: readonly string[], agent: string | null | undefined): ScreenAsk | null {
  if (!agent || !ASK_AGENTS.includes(agent)) return null;
  let last = lines.length - 1;
  while (last >= 0 && !lines[last].trim()) last--;
  if (last < 0) return null;
  // the last option: the lowest numbered line with at most TAIL_MAX hint lines (and blanks) under it
  let end = -1;
  let tail = 0;
  for (let y = last; y >= 0 && tail <= TAIL_MAX; y--) {
    const l = lines[y];
    if (!l.trim()) continue;
    if (OPTION.test(l)) {
      end = y;
      break;
    }
    if (!HINT.test(l)) return null;
    tail++;
  }
  // the key hints must be drawn: options with nothing under them are a frame still being drawn
  if (end < 0 || tail === 0) return null;
  // the options upward: numbered lines, with an option's wrapped lines (indented, no number) between them
  const opts: { n: number; text: string; sel: boolean; y: number }[] = [];
  let more: string[] = [];
  let y = end;
  for (; y >= 0; y--) {
    const l = lines[y];
    const m = OPTION.exec(l);
    if (m) {
      opts.unshift({ n: Number(m[2]), text: [m[3], ...more].join(" "), sel: !!m[1], y });
      more = [];
      if (m[2] === "1") break;
      continue;
    }
    if (!l.trim() || !/^\s{3,}\S/.test(l) || more.length > 2) return null;
    more.unshift(l.trim());
  }
  if (opts.length < 2 || opts[0].n !== 1 || opts.some((o, i) => o.n !== i + 1)) return null;
  if (opts.filter((o) => o.sel).length !== 1) return null;
  // the dialog's block above the options (up to its rule line), and its question: the lowest line in it that asks
  // (Claude Code puts it right above the options, Codex above its reason and command)
  const top = opts[0].y;
  const block: string[] = [];
  for (let k = top - 1; k >= Math.max(0, top - HEAD_MAX); k--) {
    const l = lines[k].trim();
    if (RULE.test(l)) break;
    if (l) block.unshift(l);
  }
  // a known dialog phrase first ("Reason: Allow touch …?" under Codex's question is not the question), else the lowest
  // line ending in "?" (a question menu)
  const lastOf = (ok: (l: string) => boolean) => block.reduce((at, l, i) => (ok(l) ? i : at), -1);
  let qi = lastOf((l) => QUESTION_LEAD.test(l));
  if (qi < 0) qi = lastOf((l) => /\?$/.test(l));
  if (qi < 0) return null;
  const question = block[qi];
  const head = [...block.slice(0, qi), ...block.slice(qi + 1)];
  const options = opts.map((o) => label(o.text));
  const kind: ScreenAskKind = APPROVE.test(question) ? "approve" : "question";
  const title = clip(titleOf(agent, question, head));
  return { kind, title, options, key: `${title}\n${options.join("\n")}` };
}

/** The dialog's one line: what it asks about, in the agent's own words. */
function titleOf(agent: string, question: string, head: string[]): string {
  // "Do you want to make this edit to notes.md?" -> "Edit notes.md"; "Do you want to create notes.md?" -> "Create notes.md"
  const edit = /^do you want to make this edit to (.+)\?$/i.exec(question);
  if (edit) return `Edit ${edit[1]}`;
  const create = /^do you want to create (.+)\?$/i.exec(question);
  if (create) return `Create ${create[1]}`;
  if (agent === "codex") {
    // Codex shows the command it would run as "$ <command>"
    const cmd = head.find((l) => l.startsWith("$ "));
    if (cmd) return cmd;
    return question;
  }
  // Claude Code: the tool's header ("Bash command"), then its description, then the command between dashed rules
  const tool = head.find((l) => /^(bash command|edit file|create file|write file|read file|fetch|web ?fetch|web ?search|mcp|tool use)\b/i.test(l));
  if (tool) {
    const body = head.filter((l) => !/^[╌─]+$/.test(l) && !/^tip:/i.test(l) && l !== tool);
    // the command sits between two dashed rules: the line after the description
    const cmd = body.length > 1 ? body[1] : body[0];
    return cmd ? `${tool}: ${cmd}` : tool;
  }
  // a question menu: its question line, or the line above it when the question is a generic "Do you want to proceed?"
  return question;
}

/** Two reads at least this far apart must agree before a dialog counts. */
export const ASK_CONFIRM_MS = 300;

export interface AskRead {
  /** the dialog now counted, or null */
  live: ScreenAsk | null;
  /** a second read is due in this many ms to confirm a dialog first seen now */
  confirmIn?: number;
  /** true once, on the read that made a new dialog live */
  fresh?: boolean;
}

/** A dialog counts after two consecutive reads at least ASK_CONFIRM_MS apart show the same one (a half-drawn frame
 *  must not flash an ask), and stops counting on the first read that no longer shows it. */
export function createAskDebounce(gapMs = ASK_CONFIRM_MS) {
  let cand: { key: string; at: number } | null = null;
  let live: ScreenAsk | null = null;
  return {
    read(ask: ScreenAsk | null, now: number): AskRead {
      if (!ask) {
        cand = null;
        live = null;
        return { live };
      }
      if (live && live.key === ask.key) {
        live = ask;
        return { live };
      }
      live = null;
      if (cand && cand.key === ask.key) {
        const waited = now - cand.at;
        if (waited >= gapMs) {
          cand = null;
          live = ask;
          return { live, fresh: true };
        }
        return { live, confirmIn: gapMs - waited };
      }
      cand = { key: ask.key, at: now };
      return { live, confirmIn: gapMs };
    },
    reset() {
      cand = null;
      live = null;
    },
  };
}
