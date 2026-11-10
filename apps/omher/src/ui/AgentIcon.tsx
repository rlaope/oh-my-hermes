// The mark of an agent or CLI (Claude Code, Codex, Grok, pi, omp, OMH…), a sibling of ModelIcon. The SVG
// files in src/assets/agents are the vendors' marks as published (Lobe Icons, MIT; pi from pi-mono, MIT; omp's
// official mark; the OMH kami mark), imported as text and drawn inline so monochrome marks follow the text
// colour (`currentColor`) on both themes. Unknown ids get a letter mark.
import type { CSSProperties } from "react";
import amp from "../assets/agents/amp-color.svg?raw";
import claudecode from "../assets/agents/claudecode-color.svg?raw";
import cline from "../assets/agents/cline.svg?raw";
import codex from "../assets/agents/codex-color.svg?raw";
import cursor from "../assets/agents/cursor.svg?raw";
import gemini from "../assets/agents/gemini-color.svg?raw";
import geminicli from "../assets/agents/geminicli-color.svg?raw";
import githubcopilot from "../assets/agents/githubcopilot.svg?raw";
import goose from "../assets/agents/goose.svg?raw";
import grok from "../assets/agents/grok.svg?raw";
import grokbot from "../assets/agents/grokbot.svg?raw";
import junie from "../assets/agents/junie-color.svg?raw";
import kilocode from "../assets/agents/kilocode.svg?raw";
import hermesDarkPng from "../assets/agents/hermes-dark.png";
import hermesPng from "../assets/agents/hermes.png";
import omhPng from "../assets/agents/omh.png";
import omp from "../assets/agents/omp.svg?raw";
import openai from "../assets/agents/openai.svg?raw";
import opencode from "../assets/agents/opencode.svg?raw";
import pi from "../assets/agents/pi.svg?raw";
import qwen from "../assets/agents/qwen-color.svg?raw";
import roocode from "../assets/agents/roocode.svg?raw";
import trae from "../assets/agents/trae-color.svg?raw";
import windsurf from "../assets/agents/windsurf.svg?raw";

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

const SVG: [string, string, string][] = [
  ["claude", "Claude Code", claudecode],
  ["codex", "Codex", codex],
  ["openai", "OpenAI", openai],
  ["gemini", "Gemini CLI", geminicli],
  ["gemini-app", "Gemini", gemini],
  ["grok", "Grok", grok],
  ["grokbot", "Grok Bot", grokbot],
  ["pi", "pi", pi],
  ["omp", "omp", omp],
  ["opencode", "opencode", opencode],
  ["cursor", "Cursor", cursor],
  ["amp", "Amp", amp],
  ["cline", "Cline", cline],
  ["copilot", "GitHub Copilot", githubcopilot],
  ["goose", "Goose", goose],
  ["kilo", "Kilo Code", kilocode],
  ["junie", "Junie", junie],
  ["qwen", "Qwen Code", qwen],
  ["windsurf", "Windsurf", windsurf],
  ["trae", "TRAE", trae],
  ["roo", "Roo Code", roocode],
];

const MARKS: Record<string, AgentMark> = Object.fromEntries([
  ...SVG.map(([id, title, raw]) => [id, parse(id, title, raw)] as const),
  ["omh", { kind: "img", id: "omh", title: "OMH", src: omhPng } as AgentMark] as const,
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

/** The mark for an agent id (case-insensitive, aliases allowed); unknown ids get a letter mark. */
export function agentIcon(id: string | null | undefined): AgentMark {
  const key = (id ?? "").trim().toLowerCase();
  const mark = MARKS[ALIASES[key] ?? key];
  if (mark) return mark;
  const name = (id ?? "").trim();
  return { kind: "letter", id: null, title: name || "Unknown", letter: (name.match(/[a-z0-9]/i)?.[0] ?? "?").toUpperCase() };
}

export function AgentIcon({
  id,
  size = 16,
  style,
  className,
}: {
  id: string | null | undefined;
  size?: number;
  style?: CSSProperties;
  className?: string;
}) {
  const mark = agentIcon(id);
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

/** Hermes Agent's own icon, for what a Hermes subagent ran: the app icon of NousResearch/hermes-agent
 *  (`assets/icon-master.svg` on a light theme, `assets/icon-master-dark.svg` on a dark one; MIT, (c) Nous Research),
 *  drawn small from the published files. It is not in the agent list above: Hermes runs every bot, it is not an
 *  agent CLI to pick. */
export function HermesMark({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <span className={`hermes-ic${className ? ` ${className}` : ""}`} data-agent="hermes" role="img" aria-label="Hermes" style={{ width: size, height: size }}>
      <img src={hermesPng} width={size} height={size} alt="" className="on-light" />
      <img src={hermesDarkPng} width={size} height={size} alt="" className="on-dark" />
    </span>
  );
}
