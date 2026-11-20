// Open the SESSIONS + menu from elsewhere (⌘N, the first-run card's "New session"). The menu's header registers here.
// Also: the shells this computer offers for a Shell row (the + menu's Shell ▸ list, Settings › Terminal), asked once.
import { useEffect, useState } from "react";
import { getShellHost, type ShellInfo } from "../terminal/host";

const openers = new Set<() => void>();

let shellsAsked: Promise<ShellInfo[]> | null = null;
/** The shells a Shell row may run here (the shell's `shells_available`, default first); [] when it cannot say. */
export function loadShells(): Promise<ShellInfo[]> {
  return (shellsAsked ??= getShellHost()
    .shells()
    .then((l) => (Array.isArray(l) ? l : []))
    .catch(() => {
      shellsAsked = null;
      return [];
    }));
}

/** `loadShells()` for a component: null until it answers. */
export function useShells(): ShellInfo[] | null {
  const [list, setList] = useState<ShellInfo[] | null>(null);
  useEffect(() => {
    let live = true;
    void loadShells().then((l) => live && setList(l));
    return () => {
      live = false;
    };
  }, []);
  return list;
}

export function onOpenNewSessionMenu(f: () => void): () => void {
  openers.add(f);
  return () => {
    openers.delete(f);
  };
}

export function openNewSessionMenu(): void {
  for (const f of [...openers]) f();
}
