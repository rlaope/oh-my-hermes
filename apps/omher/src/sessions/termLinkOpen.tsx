// An omher terminal link opened from outside omher (the OS hands `omher://terminal/<id>` to the desktop app; the shell
// checks its shape and sends the bare id, term_link.rs): open that TERMINALS session, or say the terminal is not on
// this computer. Links that arrived before the page listened are taken once at start. In the browser build (mock
// host) `window.__omherOpenTermLink(url)` stands in for the OS.
import { useEffect, useState } from "react";
import { getStore } from "../state/store";
import { t } from "../i18n";
import { getSessions } from "./sessions";
import { isLinkId, parseTermLink } from "./termLink";

const inTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Gone = () => void;
const goneListeners = new Set<Gone>();

/** Open the session holding link id `id`; false (and the "not on this computer" note) when none does. */
export function openTermLinkId(id: string): boolean {
  const r = isLinkId(id) ? getSessions().byLink(id) : null;
  if (!r || r.status === "draft") {
    for (const f of [...goneListeners]) f();
    return false;
  }
  getStore().actions.openSession(r.id);
  return true;
}

let started = false;

/** Once per page load: take the links waiting in the shell, then follow new ones. */
export function startTermLinks(): void {
  if (started || typeof window === "undefined") return;
  started = true;
  if (!inTauri()) {
    (window as unknown as { __omherOpenTermLink?: (url: string) => boolean }).__omherOpenTermLink = (url) => {
      const id = parseTermLink(url);
      return id ? openTermLinkId(id) : false;
    };
    return;
  }
  void Promise.all([import("@tauri-apps/api/event"), import("@tauri-apps/api/core")])
    .then(async ([{ listen }, { invoke }]) => {
      await listen<string>("term-link", (e) => void openTermLinkId(String(e.payload)));
      const waiting = await invoke<string[]>("term_link_take");
      for (const id of waiting) openTermLinkId(id);
    })
    .catch(() => undefined);
}

/** "Terminal not on this computer" for a moment after a link to a session omher does not have was opened. */
export function TermLinkGone() {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const on = () => {
      setShown(true);
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => setShown(false), 4000);
    };
    goneListeners.add(on);
    return () => {
      goneListeners.delete(on);
      if (timer) clearTimeout(timer);
    };
  }, []);
  if (!shown) return null;
  return (
    <div className="tlink-gone" role="status" data-testid="term-link-gone">
      {t("tlink.gone")}
    </div>
  );
}
