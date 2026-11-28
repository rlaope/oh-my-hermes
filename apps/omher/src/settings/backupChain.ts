// Pure helpers of a bot's Backup model section (BackupModel.tsx, BOUNDARY rule 57): which models the picker offers as a
// backup and the whole new list `fallback.set` sends. Nothing here reads or writes anything.
import { isCurrent, type ModelRow } from "../chat/model/modelSearch";

/** The bridge's FALLBACK_MAX: backup models a bot gets from omher. */
export const BACKUP_MAX = 4;
/** The bridge's FALLBACK_VALUE: a provider or model id omher can set (letters, digits, `. _ : / @ -`). */
export const BACKUP_VALUE = /^[A-Za-z0-9](?:[A-Za-z0-9._:/@-]{0,126}[A-Za-z0-9])?$/;

export type BackupPair = { provider: string; model: string };

const pair = (e: BackupPair): BackupPair => ({ provider: e.provider, model: e.model });

/** What the picker offers as a backup: the bot's own model list (`models.options`), without its main model, a model
 *  already in the list, or an id the bridge would refuse. Providers compare as the bridge compares them: through the
 *  ids the bridge gave (`ids` from `fallback.get` for the list's providers and the bot's own, each option's own `id`
 *  from `models.options`), so an alias (`openai` for `openrouter`) is never offered beside the model it names; a
 *  provider without one compares in lowercase. */
export function backupOptions(
  rows: ModelRow[],
  chain: readonly BackupPair[],
  main: BackupPair,
  ids: Readonly<Record<string, string>> = {},
): ModelRow[] {
  const key = (provider: string, model: string, id = ids[provider]) => `${(id || provider).toLowerCase()} ${model.toLowerCase()}`;
  const taken = new Set([key(main.provider, main.model), ...chain.map((e) => key(e.provider, e.model))]);
  return rows.filter(
    (r) =>
      BACKUP_VALUE.test(r.provider.slug) &&
      BACKUP_VALUE.test(r.model) &&
      !isCurrent(r, main.model, main.provider) &&
      !taken.has(key(r.provider.slug, r.model, r.provider.id)),
  );
}

/** The whole list with `add` last, as `fallback.set` takes it (provider and model only). */
export const withBackup = (chain: readonly BackupPair[], add: BackupPair): BackupPair[] => [...chain.map(pair), pair(add)];

/** The whole list without its `i`th entry. */
export const withoutBackup = (chain: readonly BackupPair[], i: number): BackupPair[] => chain.filter((_, j) => j !== i).map(pair);
