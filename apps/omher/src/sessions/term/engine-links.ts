// Links in a SESSIONS terminal's output. An http or https address is underlined on hover and opens in the default
// browser on Cmd+click (macOS) or Ctrl+click (Windows, Linux). A plain click does nothing here, so it still selects
// text and a program's own mouse handling is left alone. It opens through the app's one opener (`openExternal`, the
// Tauri `open_external` command: docs/OMHER-BOUNDARY.md rule 22) and only for an address that passes the same rule:
// http or https, no user name or password. Nothing is fetched.
import type { Terminal } from "@xterm/xterm";
import type { WebLinksAddon } from "@xterm/addon-web-links";
import { openExternal } from "../../lib/openExternal";
import { t } from "../../i18n";

/** The add-on's chunk loads with the first terminal (with xterm), never with the app. */
let linksLoad: Promise<typeof WebLinksAddon> | null = null;
const loadLinks = () =>
  (linksLoad ??= import("@xterm/addon-web-links").then(
    (m) => m.WebLinksAddon,
    (e) => {
      linksLoad = null;
      throw e;
    },
  ));

export const isMacPlatform = () => typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** The address to open for a piece of terminal text, or null when the rule says no: only http and https, no user
 *  name or password (`https://good.com@evil.com` style addresses), a host present. */
export function webLinkTarget(text: string): string | null {
  let u: URL;
  try {
    u = new URL(text.trim());
  } catch {
    return null;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  if (u.username || u.password || !u.hostname) return null;
  return u.href;
}

/** Cmd on macOS, Ctrl elsewhere, and no other modifier held. */
export function linkModifier(e: { metaKey: boolean; ctrlKey: boolean; altKey: boolean; shiftKey: boolean }, mac: boolean): boolean {
  if (e.altKey || e.shiftKey) return false;
  return mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
}

/** The click on a link: open it when the modifier is held and the address passes the rule, else nothing. */
export function activateLink(event: MouseEvent, text: string, open: (url: string) => Promise<void> = openExternal, mac = isMacPlatform()): boolean {
  if (!linkModifier(event, mac)) return false;
  const url = webLinkTarget(text);
  if (!url) return false;
  void open(url).catch(() => undefined);
  return true;
}

/** Links for one terminal; returns what undoes it. */
export function attachLinks(term: Terminal): () => void {
  let gone = false;
  let addon: WebLinksAddon | null = null;
  let tip: HTMLElement | null = null;
  const hide = () => {
    tip?.remove();
    tip = null;
  };
  // the hover hint names the key to hold (xterm's own underline and pointer say it is a link)
  const show = (e: MouseEvent) => {
    const host = term.element;
    if (!host) return;
    hide();
    const r = host.getBoundingClientRect();
    const el = document.createElement("div");
    el.className = "xterm-hover term-linktip";
    el.setAttribute("role", "tooltip");
    el.textContent = t("term.linkHint", { key: isMacPlatform() ? "⌘" : "Ctrl" });
    el.style.left = `${Math.max(0, e.clientX - r.left + 6)}px`;
    el.style.top = `${Math.max(0, e.clientY - r.top - 30)}px`;
    host.appendChild(el);
    tip = el;
  };
  void loadLinks().then(
    (Ctor) => {
      if (gone) return;
      addon = new Ctor((e, uri) => void activateLink(e, uri), { hover: (e) => show(e), leave: hide });
      try {
        term.loadAddon(addon);
      } catch {
        addon = null; // no links, the terminal still works
      }
    },
    () => undefined, // the chunk would not load: no links
  );
  return () => {
    gone = true;
    hide();
    try {
      addon?.dispose();
    } catch {
      /* already gone with the terminal */
    }
    addon = null;
  };
}
