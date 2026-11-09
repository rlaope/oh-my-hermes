// Small display helpers shared by the Runs panel and the full view.
import type { RunNode } from "../lib/runs";

/** "claude-opus-5-5" -> "Opus 5.5"; ids that do not follow that shape stay as they are. */
export function shortModel(model: string): string {
  const m = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(model);
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}`;
  return model;
}

/** A node's model for its meta line: "Opus 5.5 · high", "Codex", "Opus 5.5 (route)". */
export function modelLabel(m: { model: string; source: string }, effort?: string): string {
  const name = m.source === "executor" ? m.model.charAt(0).toUpperCase() + m.model.slice(1) : shortModel(m.model);
  return effort && m.source !== "executor" ? `${name} · ${effort}` : name;
}

/** "Opus 5.5 · high" for a node that ran on a known model, else "". */
export function modelLine(n: Pick<RunNode, "model" | "effort">): string {
  if (!n.model) return "";
  return n.effort ? `${shortModel(n.model)} · ${n.effort}` : shortModel(n.model);
}

/** Markdown to one plain paragraph, for the hover snippet. */
export function plainSnippet(md: string, n = 220): string {
  // the first heading line is the handoff's own title ("t3-doctor handoff"): skip it
  const body = md.replace(/^\s*#[^\n]*\n/, "");
  const text = body
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/^#+\s*/gm, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\*\*|__|[*`>|]/g, "")
    .replace(/^\s*[-+]\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length <= n ? text : text.slice(0, n - 1).replace(/\s+\S*$/, "") + " …";
}

export const STATE_WORD: Record<RunNode["state"], string> = {
  done: "done",
  running: "running",
  failed: "failed",
  blocked: "blocked",
  parked: "parked",
  waiting: "waiting",
  cancelled: "cancelled",
};

/** The dag run's short name ("omher-v02") from its id ("dag:<session>/omher-v02"). */
export const runName = (id: string) => id.split("/").pop() ?? id;

let ctx: CanvasRenderingContext2D | null | undefined;
/** Width of `text` in `font` (a CSS font shorthand). Falls back to 6.2px a character without a canvas. */
export function textWidth(text: string, font: string): number {
  if (ctx === undefined) ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  if (!ctx) return text.length * 6.2;
  ctx.font = font;
  return ctx.measureText(text).width;
}

/** Wrap `text` into at most `lines` lines of `width` px, breaking only between words; when it does not fit, the
 *  last line ends with the last whole word that fits and "…". A single word wider than a line is cut (there is no
 *  other choice). `measure` is injectable for tests. */
export function clampWords(text: string, width: number, lines: number, measure: (s: string) => number): string {
  const words = text.split(/\s+/).filter(Boolean);
  const out: string[] = [];
  let i = 0;
  while (i < words.length && out.length < lines) {
    let line = words[i];
    if (measure(line) > width) {
      // one long token: cut it by characters
      let cut = line;
      while (cut.length > 1 && measure(cut + "…") > width) cut = cut.slice(0, -1);
      if (out.length === lines - 1) return [...out, `${cut}…`].join("\n");
      out.push(line);
      i++;
      continue;
    }
    i++;
    while (i < words.length && measure(`${line} ${words[i]}`) <= width) line += ` ${words[i++]}`;
    out.push(line);
  }
  if (i >= words.length) return out.join("\n");
  // more words left: end the last line with "…" after the last word that still fits with it
  const last = out[lines - 1].split(" ");
  while (last.length > 1 && measure(`${last.join(" ")}…`) > width) last.pop();
  let tail = last.join(" ");
  while (last.length > 1 && /^[+&·–-]$|^(and|or|for|the|of|to|vs|with|a|in)$/i.test(last[last.length - 1])) {
    last.pop(); // never end on a joiner word: "omh update and…" reads better as "omh update…"
    tail = last.join(" ");
  }
  tail = tail.replace(/[\s,;:·+–-]+$/, "");
  while (tail.length > 1 && measure(`${tail}…`) > width) tail = tail.slice(0, -1);
  out[lines - 1] = `${tail}…`;
  return out.join("\n");
}

export const reducedMotion = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
