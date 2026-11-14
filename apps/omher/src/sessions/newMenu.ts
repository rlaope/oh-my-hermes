// Open the SESSIONS + menu from elsewhere (⌘N, the first-run card's "New session"). The menu's header registers here.
const openers = new Set<() => void>();

export function onOpenNewSessionMenu(f: () => void): () => void {
  openers.add(f);
  return () => {
    openers.delete(f);
  };
}

export function openNewSessionMenu(): void {
  for (const f of [...openers]) f();
}
