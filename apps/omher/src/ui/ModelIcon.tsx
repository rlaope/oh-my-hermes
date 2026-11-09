// The mark of the company behind a model ("Opus 5.5" -> Claude, "gpt-6.1-sol" -> OpenAI,
// "z-ai/glm-5.3" -> GLM), drawn next to the model name. Unknown models fall back to the provider's
// mark (OpenRouter, Ollama) and then to a plain dot.
import type { CSSProperties } from "react";
import { MODEL_MARKS } from "./modelMarks";

const RULES: [RegExp, string][] = [
  [/claude|opus|sonnet|haiku|fable|anthropic/i, "claude"],
  [/\bgpt|(^|[/\s-])o[1-9]\b|openai|codex|chatgpt/i, "openai"],
  [/gemini|gemma|google/i, "gemini"],
  [/deepseek/i, "deepseek"],
  [/grok|x-ai|\bxai\b/i, "grok"],
  [/kimi|moonshot/i, "kimi"],
  [/glm|zhipu|z-ai|\bzai\b/i, "zhipu"],
  [/qwen|qwq|alibaba/i, "qwen"],
  [/mistral|mixtral|codestral|magistral|devstral/i, "mistral"],
  [/llama|\bmeta\b/i, "meta"],
];
const PROVIDERS: [RegExp, string][] = [
  [/openrouter/i, "openrouter"],
  [/ollama/i, "ollama"],
  [/claude|anthropic/i, "claude"],
  [/openai|codex/i, "openai"],
  [/gemini|google/i, "gemini"],
  [/deepseek/i, "deepseek"],
  [/xai|x-ai|grok/i, "grok"],
];

/** Which mark to draw for `model` served by `provider` (a slug or a name). Null = no known mark. */
export function markFor(model: string | undefined, provider?: string): string | null {
  const m = model ?? "";
  for (const [re, mark] of RULES) if (re.test(m)) return mark;
  const p = provider ?? "";
  for (const [re, mark] of PROVIDERS) if (re.test(p)) return mark;
  return null;
}

export function ModelIcon({
  model,
  provider,
  size = 13,
  style,
  className,
}: {
  model?: string;
  provider?: string;
  size?: number;
  style?: CSSProperties;
  className?: string;
}) {
  const id = markFor(model, provider);
  const mark = id ? MODEL_MARKS[id] : null;
  const cls = `model-ic${className ? ` ${className}` : ""}`;
  if (!mark) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={cls} data-mark="none" style={style}>
        <circle cx="12" cy="12" r="5" fill="currentColor" />
      </svg>
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
      className={cls}
      data-mark={id!}
      style={style}
      // static, generated markup from modelMarks.ts (no user input)
      dangerouslySetInnerHTML={{ __html: mark.body }}
    />
  );
}
