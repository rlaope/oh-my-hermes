// Turn a provider's flat model list ("anthropic/claude-opus-5.5", "liquid/lfm-3-1.7b:free", "Opus 5.5") into
// vendor groups for the Providers page: one group per `vendor/` prefix in first-seen order, the prefix stripped
// inside the group and a `:free`-style suffix split off as a tag. The current model leads its group, and its
// group leads the list.
import { t } from "../../i18n";

export interface ModelEntry {
  /** the full id as the provider lists it */
  id: string;
  /** the id without the vendor prefix and suffix */
  name: string;
  /** the `:free` / `:beta` suffix without the colon, or "" */
  tag: string;
}

export interface ModelGroup {
  /** the `vendor/` prefix without the slash; "" when the ids carry none */
  vendor: string;
  models: ModelEntry[];
}

export function splitModel(id: string): { vendor: string; entry: ModelEntry } {
  const slash = id.indexOf("/");
  const vendor = slash > 0 ? id.slice(0, slash) : "";
  let name = slash > 0 ? id.slice(slash + 1) : id;
  let tag = "";
  const m = /:([A-Za-z0-9._-]+)$/.exec(name);
  if (m && m.index > 0) {
    tag = m[1];
    name = name.slice(0, m.index);
  }
  return { vendor, entry: { id, name, tag } };
}

export function groupModels(models: string[], current?: string): ModelGroup[] {
  const groups = new Map<string, ModelEntry[]>();
  for (const id of models) {
    const { vendor, entry } = splitModel(id);
    const list = groups.get(vendor);
    if (list) list.push(entry);
    else groups.set(vendor, [entry]);
  }
  const out = [...groups].map(([vendor, list]) => ({ vendor, models: list }));
  if (!current) return out;
  const at = out.findIndex((g) => g.models.some((e) => e.id === current));
  if (at < 0) return out;
  const g = out[at];
  const lead = { vendor: g.vendor, models: [...g.models.filter((e) => e.id === current), ...g.models.filter((e) => e.id !== current)] };
  return [lead, ...out.slice(0, at), ...out.slice(at + 1)];
}

/** Keep the models whose full id contains `q` (case-insensitive); groups left empty are dropped. */
export function filterGroups(groups: ModelGroup[], q: string): ModelGroup[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return groups;
  return groups
    .map((g) => ({ vendor: g.vendor, models: g.models.filter((e) => e.id.toLowerCase().includes(needle)) }))
    .filter((g) => g.models.length > 0);
}

export const countLabel = (n: number) => (n === 0 ? t("pv.noModels") : n === 1 ? t("pv.model1") : t("pv.models", { n }));
