// The omher.app preview: runs before any app module. Nothing may leave the page, so storage goes to
// sessionStorage, notifications, sounds and the Tauri paths stay off, and the bridge is an in-page host
// (preview/host.ts) behind a stand-in WebSocket.
import { FakeSocket } from "./host";

const w = window as unknown as Record<string, unknown>;
// The preview speaks the site's language: the one picked on omher.app (?lang= or its switch), else English, the
// site's own default; never the browser's, which the app would take on a first run.
export const siteLang = (): string => {
  try {
    const l = (window.parent !== window ? parent.document.documentElement.lang : "").slice(0, 2);
    return ["en", "ko", "ja", "zh"].includes(l) ? l : "en";
  } catch {
    return "en";
  }
};
// The app keeps its look, pins and recent folders in localStorage; the preview keeps them for this tab only.
try {
  const ss = window.sessionStorage;
  Object.defineProperty(window, "localStorage", { configurable: true, get: () => ss });
  if (!ss.getItem("omher.theme")) ss.setItem("omher.theme", "dark");
  ss.setItem("omher.notify", "off");
  ss.setItem("omher.sounds", "off");
  ss.setItem("omher.lang", siteLang());
} catch {
  /* storage blocked: the app falls back to its defaults */
}
// No system notifications and no audio from a web page someone is only looking at.
try {
  Object.defineProperty(window, "Notification", { configurable: true, value: undefined });
} catch {
  /* read-only in this browser */
}
// Stage three installed agents (the chats the story uses, plus oh-my-hermes), keeping More agents and Continue a
// conversation visible when the + menu first opens in the hero-sized window. The other agents, including the six
// added in 0.2.8, show their full install lines under More agents; copying is text only and installs nothing. Chat
// agents answer their first message with the preview note; oh-my-hermes opens a staged folder chat of the current
// bot (host.ts folder.open; the story answers it). A session in the agent's own terminal is held back (guard.ts).
w.__omherMockAgents = ["claude", "codex", "omh"];
// Every BridgeClient the app makes (the store's and the add-bot popover's) talks to the in-page host.
w.WebSocket = FakeSocket;
document.documentElement.dataset.preview = "1";

// Inside omher.app the preview is a window on someone else's page: it must never scroll that page or take its focus.
// - scrollIntoView (the app brings an open plan node or an ask into view) only scrolls panes inside this document;
//   the browser's own version would scroll the visitor's page too.
// - focus() (the app focuses its composer when a chat opens) only happens once the visitor is in the preview, and
//   never scrolls.
if (window.parent !== window) {
  Element.prototype.scrollIntoView = function (this: Element, arg?: boolean | ScrollIntoViewOptions) {
    const block = typeof arg === "object" ? (arg.block ?? "start") : arg === false ? "end" : "start";
    for (let p = this.parentElement; p; p = p.parentElement) {
      if (p.scrollHeight <= p.clientHeight + 1 || !/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowY)) continue;
      const r = this.getBoundingClientRect();
      const pr = p.getBoundingClientRect();
      let d = 0;
      if (block === "start") d = r.top - pr.top;
      else if (block === "end") d = r.bottom - pr.bottom;
      else if (block === "center") d = (r.top + r.bottom) / 2 - (pr.top + pr.bottom) / 2;
      else if (r.top < pr.top) d = r.top - pr.top;
      else if (r.bottom > pr.bottom) d = Math.min(r.bottom - pr.bottom, r.top - pr.top);
      p.scrollTop += d;
    }
  };
  const focus = HTMLElement.prototype.focus;
  HTMLElement.prototype.focus = function (this: HTMLElement, opts?: FocusOptions) {
    if (!document.hasFocus()) return;
    focus.call(this, { ...opts, preventScroll: true });
  };
}
