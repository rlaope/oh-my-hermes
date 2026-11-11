// The mark of a provider (Nous Portal, OpenRouter, Anthropic, claude-proxy, og …) or of a model vendor
// ("google", "moonshotai", "z-ai"). Own marks first, then the ModelIcon family mark, then a quiet monogram,
// never a different company's mark taken from the provider's first model.
import { MODEL_MARKS, type ModelMark } from "../../ui/modelMarks";
import { markFor } from "../../ui";
import { EXTRA_MARKS } from "./marks";

const OWN: [RegExp, string][] = [
  [/nous/i, "nous"],
  [/openrouter/i, "openrouter"],
  [/ollama/i, "ollama"],
  [/anthropic/i, "anthropic"],
  [/minimax/i, "minimax"],
  [/nvidia/i, "nvidia"],
  [/tencent/i, "tencent"],
  [/stepfun/i, "stepfun"],
  [/xiaomi/i, "xiaomi"],
  [/upstage/i, "upstage"],
  [/sakana/i, "sakana"],
];

/** The mark id for a provider or vendor name, or null when none is known. */
export function markIdFor(...names: string[]): string | null {
  const s = names.filter(Boolean).join(" ");
  if (!s) return null;
  for (const [re, id] of OWN) if (re.test(s)) return id;
  return markFor(s, s);
}

const markById = (id: string | null): ModelMark | null => (id ? EXTRA_MARKS[id] ?? MODEL_MARKS[id] ?? null : null);

export function ProviderMark({ names, size = 14 }: { names: string[]; size?: number }) {
  const id = markIdFor(...names);
  const mark = markById(id);
  if (!mark) {
    const letter = (names.find(Boolean) ?? "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 1).toUpperCase() || "?";
    return (
      <span className="pv-mono" data-mark="none" aria-hidden="true" style={{ width: size, height: size, fontSize: size * 0.62 }}>
        {letter}
      </span>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox={mark.viewBox}
      fill="currentColor"
      fillRule="evenodd"
      aria-hidden="true"
      className="pv-ic"
      data-mark={id!}
      // static, generated markup from modelMarks.ts / marks.ts (no user input)
      dangerouslySetInnerHTML={{ __html: mark.body }}
    />
  );
}
