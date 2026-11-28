// Pure helpers of a bot's Backup model section (BackupModel.tsx, BOUNDARY rule 55): which models the picker offers as a
// backup and the whole new list `fallback.set` sends. Nothing here reads or writes anything.
import { isCurrent, type ModelRow } from "../chat/model/modelSearch";

/** The bridge's FALLBACK_MAX: backup models a bot gets from omher. */
export const BACKUP_MAX = 4;
/** The bridge's FALLBACK_VALUE: a provider or model id omher can set (letters, digits, `. _ : / @ -`). */
export const BACKUP_VALUE = /^[A-Za-z0-9](?:[A-Za-z0-9._:/@-]{0,126}[A-Za-z0-9])?$/;

export type BackupPair = { provider: string; model: string };

const pair = (e: BackupPair): BackupPair => ({ provider: e.provider, model: e.model });
const same = (a: BackupPair, b: BackupPair) =>
  a.provider.toLowerCase() === b.provider.toLowerCase() && a.model.toLowerCase() === b.model.toLowerCase();

/** What the picker offers as a backup: the bot's own model list (`models.options`), without its main model, a model
 *  already in the list, or an id the bridge would refuse. */
export function backupOptions(rows: ModelRow[], chain: readonly BackupPair[], main: BackupPair): ModelRow[] {
  return rows.filter((r) => {
    const p = { provider: r.provider.slug, model: r.model };
    return (
      BACKUP_VALUE.test(p.provider) &&
      BACKUP_VALUE.test(p.model) &&
      !isCurrent(r, main.model, main.provider) &&
      !same(p, main) &&
      !chain.some((e) => same(e, p))
    );
  });
}

/** The whole list with `add` last, as `fallback.set` takes it (provider and model only). */
export const withBackup = (chain: readonly BackupPair[], add: BackupPair): BackupPair[] => [...chain.map(pair), pair(add)];

/** The whole list without its `i`th entry. */
export const withoutBackup = (chain: readonly BackupPair[], i: number): BackupPair[] => chain.filter((_, j) => j !== i).map(pair);
