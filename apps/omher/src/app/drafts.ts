// Unsent composer text per chat (a bot's name, or a SESSIONS chat's key). The composer reads its chat's draft
// when it mounts and writes every change here; the resume snapshot (resume.ts) saves the map, so a draft
// survives switching chats, a reload, a quit and an update restart.
const MAX_LEN = 20_000;

const drafts = new Map<string, string>();
const fns = new Set<() => void>();

export function getDraft(key: string): string {
  return drafts.get(key) ?? "";
}

export function setDraft(key: string, text: string): void {
  const t = text.length > MAX_LEN ? text.slice(0, MAX_LEN) : text;
  if ((drafts.get(key) ?? "") === t) return;
  if (t) drafts.set(key, t);
  else drafts.delete(key);
  for (const f of [...fns]) f();
}

export function allDrafts(): Record<string, string> {
  return Object.fromEntries(drafts);
}

/** Put saved drafts back (a draft already typed in this page load wins). */
export function loadDrafts(saved: Record<string, string>): void {
  for (const [k, v] of Object.entries(saved)) if (!drafts.has(k) && v) drafts.set(k, v.slice(0, MAX_LEN));
}

export function onDraftChange(fn: () => void): () => void {
  fns.add(fn);
  return () => fns.delete(fn);
}

/** Tests only. */
export function clearDrafts(): void {
  drafts.clear();
}
