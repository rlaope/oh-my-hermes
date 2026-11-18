// The mark of an agent or CLI (Claude Code, Codex, Grok, pi, omp, OMH…), a sibling of ModelIcon. The SVG
// files in src/assets/agents are the vendors' marks as published (Lobe Icons, MIT; pi from pi-mono, MIT; omp's
// official mark; the OMH kami mark), imported as text and drawn inline so monochrome marks follow the text
// colour (`currentColor`) on both themes. Unknown ids get a letter mark.
import type { CSSProperties } from "react";
import { assetRaw, assetUrl } from "../harness/assets";
import { t } from "../i18n";

export type AgentMark =
  | { kind: "svg"; id: string; title: string; viewBox: string; body: string; mono: boolean; evenodd: boolean }
  | { kind: "img"; id: string; title: string; src: string }
  | { kind: "letter"; id: null; title: string; letter: string };

/** Pull viewBox and inner markup out of a published SVG file; ids get a per-mark prefix so two marks never clash. */
function parse(id: string, title: string, raw: string): AgentMark {
  const open = /<svg\b([^>]*)>/.exec(raw);
  if (!open) return { kind: "letter", id: null, title, letter: title[0]?.toUpperCase() ?? "?" };
  const attrs = open[1];
  const body = raw
    .slice(open.index + open[0].length, raw.lastIndexOf("</svg>"))
    .replace(/<title>[\s\S]*?<\/title>/g, "")
    .replace(/\bid="([^"]+)"/g, (_, x) => `id="ag-${id}-${x}"`)
    .replace(/url\(#([^)]+)\)/g, (_, x) => `url(#ag-${id}-${x})`)
    .trim();
  return {
    kind: "svg",
    id,
    title,
    viewBox: /viewBox="([^"]+)"/.exec(attrs)?.[1] ?? "0 0 24 24",
    body,
    mono: /fill="currentColor"/.test(attrs),
    evenodd: /fill-rule="evenodd"/.test(attrs),
  };
}

const SVG: [string, string, string][] = (
  [
  ["claude", "Claude Code", "claudecode-color.svg"],
  // Codex draws the OpenAI (GPT) mark bare: the published codex-color.svg is a white app tile that reads as a
  // blank square at 16px inside a row frame
  ["codex", "Codex", "openai.svg"],
  ["openai", "OpenAI", "openai.svg"],
  ["gemini", "Gemini CLI", "geminicli-color.svg"],
  ["gemini-app", "Gemini", "gemini-color.svg"],
  ["grok", "Grok", "grok.svg"],
  ["grokbot", "Grok Bot", "grokbot.svg"],
  ["pi", "pi", "pi.svg"],
  ["omp", "omp", "omp.svg"],
  ["opencode", "opencode", "opencode.svg"],
  ["cursor", "Cursor", "cursor.svg"],
  ["amp", "Amp", "amp-color.svg"],
  ["cline", "Cline", "cline.svg"],
  ["copilot", "GitHub Copilot", "githubcopilot.svg"],
  ["goose", "Goose", "goose.svg"],
  ["kilo", "Kilo Code", "kilocode.svg"],
  ["junie", "Junie", "junie-color.svg"],
  ["qwen", "Qwen Code", "qwen-color.svg"],
  ["windsurf", "Windsurf", "windsurf.svg"],
  ["trae", "TRAE", "trae-color.svg"],
  ["roo", "Roo Code", "roocode.svg"],
  ] as [string, string, string][]
).map(([id, title, file]) => [id, title, assetRaw(file) ?? ""]);

const MARKS: Record<string, AgentMark> = Object.fromEntries([
  ...SVG.map(([id, title, raw]) => [id, parse(id, title, raw)] as const),
  ["omh", { kind: "img", id: "omh", title: "OMH", src: assetUrl("omh.png") ?? "" } as AgentMark] as const,
]);

/** Every agent id with a mark, in the order the grid shows them (22). */
export const AGENT_IDS: string[] = ["omh", ...SVG.map(([id]) => id)];

/** Other spellings people and files use for the same agent. */
const ALIASES: Record<string, string> = {
  claudecode: "claude",
  "claude-code": "claude",
  chatgpt: "openai",
  geminicli: "gemini",
  "gemini-cli": "gemini",
  "grok-bot": "grokbot",
  githubcopilot: "copilot",
  "github-copilot": "copilot",
  kilocode: "kilo",
  "kilo-code": "kilo",
  roocode: "roo",
  "roo-code": "roo",
  "qwen-code": "qwen",
  "oh-my-hermes": "omh",
  kami: "omh",
};

const byFile = new Map<string, AgentMark>();

/** The mark in `file` (a name in src/assets/agents, no folder), titled `title`; a letter mark when there is no such
 *  file. */
export function fileMark(file: string, title: string): AgentMark {
  const key = `${file}\u0000${title}`;
  const hit = byFile.get(key);
  if (hit) return hit;
  const stem = file.replace(/\.[a-z]+$/i, "");
  const raw = assetRaw(file);
  const src = raw ? undefined : assetUrl(file);
  const mark: AgentMark = raw
    ? parse(stem, title, raw)
    : src
      ? { kind: "img", id: stem, title, src }
      : { kind: "letter", id: null, title, letter: (title.match(/[a-z0-9]/i)?.[0] ?? "?").toUpperCase() };
  byFile.set(key, mark);
  return mark;
}

/** The mark for an agent id (case-insensitive, aliases allowed); unknown ids get a letter mark. */
export function agentIcon(id: string | null | undefined): AgentMark {
  const key = (id ?? "").trim().toLowerCase();
  const mark = MARKS[ALIASES[key] ?? key];
  if (mark) return mark;
  const name = (id ?? "").trim();
  return { kind: "letter", id: null, title: name || t("mark.unknown"), letter: (name.match(/[a-z0-9]/i)?.[0] ?? "?").toUpperCase() };
}

export function AgentIcon({
  id,
  file,
  size = 16,
  style,
  className,
}: {
  id: string | null | undefined;
  /** Draw the mark in this file of src/assets/agents instead ([`fileMark`], titled by `id`). */
  file?: string;
  size?: number;
  style?: CSSProperties;
  className?: string;
}) {
  const mark = file ? fileMark(file, id ?? "") : agentIcon(id);
  const cls = `agent-ic${className ? ` ${className}` : ""}`;
  if (mark.kind === "img") {
    return (
      <img src={mark.src} width={size} height={size} alt="" aria-hidden="true" className={cls}
        data-agent={mark.id} style={{ borderRadius: Math.round(size / 5), ...style }} />
    );
  }
  if (mark.kind === "letter") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={cls} data-agent="letter" style={style}>
        <rect width="24" height="24" rx="5" fill="currentColor" opacity="0.16" />
        <text x="12" y="16.6" textAnchor="middle" fontSize="13" fontWeight="600" fill="currentColor"
          fontFamily="-apple-system, system-ui, sans-serif">
          {mark.letter}
        </text>
      </svg>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox={mark.viewBox}
      fill={mark.mono ? "currentColor" : undefined}
      fillRule={mark.evenodd ? "evenodd" : undefined}
      aria-hidden="true"
      className={cls}
      data-agent={mark.id}
      style={style}
      // static markup from the bundled asset files (no user input)
      dangerouslySetInnerHTML={{ __html: mark.body }}
    />
  );
}
