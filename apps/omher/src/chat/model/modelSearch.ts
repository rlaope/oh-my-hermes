// Search and vendor categories for the model picker. A model's vendor is the company behind it, taken
// from the same rules as its mark (ModelIcon.markFor); models without a known company fall under "Other".
import type { ModelProvider } from "../../lib/protocol";
import { markFor } from "../../ui/ModelIcon";
import { modelName } from "../../runs/format";

export interface Vendor {
  id: string;
  label: string;
  /** Extra words a search for this vendor should find (company names, slugs). */
  aliases: string;
}

/** Chip order. `id` is the mark id from ModelIcon, except "other". */
export const VENDORS: Vendor[] = [
  { id: "claude", label: "Claude", aliases: "anthropic" },
  { id: "openai", label: "OpenAI", aliases: "gpt chatgpt" },
  { id: "gemini", label: "Gemini", aliases: "google" },
  { id: "deepseek", label: "DeepSeek", aliases: "" },
  { id: "grok", label: "Grok", aliases: "xai x-ai" },
  { id: "kimi", label: "Kimi", aliases: "moonshot" },
  { id: "zhipu", label: "GLM", aliases: "zhipu z-ai" },
  { id: "qwen", label: "Qwen", aliases: "alibaba" },
  { id: "mistral", label: "Mistral", aliases: "" },
  { id: "meta", label: "Llama", aliases: "meta" },
  { id: "other", label: "Other", aliases: "" },
];
const KNOWN = new Set(VENDORS.map((v) => v.id));

/** The vendor chip a model belongs to. Provider-only marks (OpenRouter, Ollama) count as "other". */
export function vendorOf(model: string, provider?: string): string {
  const mark = markFor(model, provider);
  return mark && KNOWN.has(mark) ? mark : "other";
}

export interface ModelRow {
  model: string;
  /** What the row shows: the model's name as people say it (`modelName`), the provider's own id when two of the
   *  provider's models would read the same ("GLM-5.3" for both glm-5.3 and glm-5.3-flash), so no two rows look alike. */
  label: string;
  provider: ModelProvider;
  vendor: string;
}

/** Every model, flat, in provider order, with its vendor and its label. */
export function modelRows(providers: ModelProvider[]): ModelRow[] {
  return providers.flatMap((p) => {
    const names = p.models.map(modelName);
    return p.models.map((model, i) => ({
      model,
      label: names.indexOf(names[i]) === names.lastIndexOf(names[i]) ? names[i] : model,
      provider: p,
      vendor: vendorOf(model, `${p.slug} ${p.name}`),
    }));
  });
}

/** Is `row` the model the chat runs? Same provider, and the same id, or the same name where one side is a display
 *  name ("Opus 5.5" from the chat against "anthropic/claude-opus-5.5" in the catalog). An id that two of the
 *  provider's models share a name with matches only itself. */
export function isCurrent(row: ModelRow, model: string, provider: string): boolean {
  if (row.provider.slug !== provider || !model) return false;
  if (row.model === model) return true;
  if (row.provider.models.includes(model)) return false;
  return row.label === modelName(model);
}

/** Vendors that have at least one model, in chip order. */
export function vendorsPresent(rows: ModelRow[]): Vendor[] {
  const have = new Set(rows.map((r) => r.vendor));
  return VENDORS.filter((v) => have.has(v.id));
}

const compact = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

/**
 * Does `query` find this model? Case-insensitive; every word of the query must appear in the model id, its label,
 * the provider (slug or name) or the vendor, either as typed or with separators dropped on both sides
 * ("opus55" finds "claude-opus-5-5"). An empty query matches everything.
 */
export function matchesModel(query: string, row: ModelRow): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const vendor = VENDORS.find((v) => v.id === row.vendor);
  const fields = [row.model, row.label, row.provider.slug, row.provider.name, vendor?.label ?? "", vendor?.aliases ?? ""];
  const plain = fields.join(" ").toLowerCase();
  const tight = fields.map(compact);
  return words.every((w) => {
    if (plain.includes(w)) return true;
    const cw = compact(w);
    return cw.length > 0 && tight.some((f) => f.includes(cw));
  });
}

/** Rows that pass both the vendor chip (`"all"` = any) and the search. */
export function filterRows(rows: ModelRow[], query: string, vendor: string): ModelRow[] {
  return rows.filter((r) => (vendor === "all" || r.vendor === vendor) && matchesModel(query, r));
}
