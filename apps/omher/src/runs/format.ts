// Small display helpers shared by the Runs panel and the full view.
import type { RunNode } from "../lib/runs";
import type { Key } from "../i18n";

/** A model's name as people say it: "claude-opus-5-5" -> "Opus 5.5", "gpt-6.1-sol" -> "GPT-6.1 Sol", "gpt-6-astra"
 *  -> "GPT-6 Astra", "gemini-3-pro" -> "Gemini 3 Pro", "z-ai/glm-5.3-ultrafast" -> "GLM-5.3", "kimi-k3" -> "Kimi K3",
 *  "deepseek-v4.1-flash" -> "DeepSeek V4.1" (a speed tier after GLM, Kimi or DeepSeek is not part of the name). What a provider puts around the id is dropped: a path in front ("anthropic/claude-haiku-5" ->
 *  "Haiku 5"), "us.anthropic." in front, and behind it a context tag ("[1m]"), an effort or revision (":high",
 *  "-v1:0") or a date ("-20261001", "-2026-08-01"). An id of neither shape stays as it is (a display name such
 *  as "Opus 5.5" passes through). */
export function modelName(model: string): string {
  const raw = model.slice(model.lastIndexOf("/") + 1).trim();
  const id = raw
    .replace(/^(?:[a-z]{2}\.)?anthropic\./, "")
    .replace(/\[[^\]]*\]$/, "")
    .replace(/:[^:]*$/, "")
    .replace(/-v\d+$/, "")
    .replace(/-(?:\d{8}|\d{4}-\d{2}-\d{2})$/, "");
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const words = (tail: string) => tail.split("-").filter(Boolean).map((part) => ` ${cap(part)}`).join("");
  const claude = /^claude-([a-z]+)-(\d{1,2})(?:-(\d{1,2}))?((?:-[a-z]+)*)$/.exec(id);
  if (claude) return `${cap(claude[1])} ${claude[2]}${claude[3] ? `.${claude[3]}` : ""}${words(claude[4])}`;
  const gpt = /^gpt-(\d+(?:\.\d+)?)((?:-[a-z][a-z0-9.]*)*)$/i.exec(id);
  if (gpt) return `GPT-${gpt[1]}${words(gpt[2])}`;
  const gemini = /^gemini-(\d+(?:\.\d+)?)((?:-[a-z][a-z0-9.]*)*)$/i.exec(id);
  if (gemini) return `Gemini ${gemini[1]}${words(gemini[2])}`;
  // open models served at several speeds: the tier ("-flash", "-ultrafast") is how it was served, not the model
  const open = id.replace(/(?:-(?:flash|ultrafast|turbo|fast))+$/i, "");
  const glm = /^glm-(\d+(?:\.\d+)?)((?:-[a-z][a-z0-9.]*)*)$/i.exec(open);
  if (glm) return `GLM-${glm[1]}${words(glm[2])}`;
  const kimi = /^kimi-k(\d+(?:\.\d+)?)((?:-[a-z][a-z0-9.]*)*)$/i.exec(open);
  if (kimi) return `Kimi K${kimi[1]}${words(kimi[2])}`;
  const deepseek = /^deepseek-v(\d+(?:\.\d+)?)((?:-[a-z][a-z0-9.]*)*)$/i.exec(open);
  if (deepseek) return `DeepSeek V${deepseek[1]}${words(deepseek[2])}`;
  return raw;
}

export const STATE_WORD: Record<RunNode["state"], Key> = {
  done: "st.done",
  running: "st.running",
  failed: "st.failed",
  blocked: "st.blocked",
  parked: "st.parked",
  waiting: "st.waiting",
  cancelled: "st.cancelled",
};

/** The dag run's short name ("omher-v02") from its id ("dag:<session>/omher-v02"). */
export const runName = (id: string) => id.split("/").pop() ?? id;

export const reducedMotion = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
