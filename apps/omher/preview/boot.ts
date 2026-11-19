// The omher.app preview: runs before any app module. Nothing may leave the page, so storage goes to
// sessionStorage, notifications, sounds and the Tauri paths stay off, and the bridge is an in-page host
// (preview/host.ts) behind a stand-in WebSocket.
import { FakeSocket } from "./host";

const w = window as unknown as Record<string, unknown>;
// The preview is always in English, whatever the site's language switch (?lang=, omh.lang) or the browser says. Its
// story (chat, threads, terminals) is staged in English, so a translated app UI around it showed Korean labels next
// to English messages. The app would otherwise take the browser's language on a first run.
export const siteLang = (): string => "en";
// The app keeps its look, pins and recent folders in localStorage; the preview keeps them for this tab only.
try {
  const ss = window.sessionStorage;
  Object.defineProperty(window, "localStorage", { configurable: true, get: () => ss });
  if (!ss.getItem("omher.theme")) ss.setItem("omher.theme", "dark");
  ss.setItem("omher.notify", "off");
  // The staged terminals draw box frames (Codex's header, Claude Code's welcome box): at the app's default 1.2 line
  // height the frame's │ sides break between rows. Line height 1 joins them.
  if (!ss.getItem("omher.term")) ss.setItem("omher.term", JSON.stringify({ lineHeight: 1 }));
  ss.setItem("omher.sounds", "off");
  ss.setItem("omher.lang", siteLang());
  // From 0.2.10 the sidebar lists only the roster (one bot on a first run); the story plays on all four.
  if (!ss.getItem("omher.roster")) ss.setItem("omher.roster", JSON.stringify(["kami", "friren", "juno-bot", "pip"]));
  // Tasks opens on the staged repository (the page keeps its own choice in omher.tasks)
  if (!ss.getItem("omher.tasks"))
    ss.setItem("omher.tasks", JSON.stringify({ source: "github", repo: { github: "acme/web-app", gitlab: "" }, kind: "issues", filter: "open", bar: true, recent: { github: ["acme/web-app"], gitlab: [] }, folders: { "github:acme/web-app": "/Users/you/code/web-app" } }));
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
// TERMINALS (0.2.12): the staged folder's git branch on its header.
w.__omherBranches = { "/Users/you/code/web-app": "feature/search-filters" };
// Tasks (0.2.12): the in-page task host's staged GitHub issues and pull requests for acme/web-app (the desktop app
// asks the person's own `gh`; here nothing is asked). The page opens on that repository.
const H = 3600;
const now = Date.now() / 1000;
const lbl = (name: string, color: string) => ({ name, color });
const issue = (number: number, title: string, labels: { name: string; color: string }[], author: string, ago: number, f: { assignee?: boolean; mine?: boolean; mentions?: boolean } = {}) => ({
  number, title, state: "open", url: "", labels, author, created: now - ago * 3, updated: now - ago, checks: null, ...f,
});
const pr = (number: number, title: string, labels: { name: string; color: string }[], author: string, ago: number, checks: { passed: number; failed: number; pending: number; total: number }, state = "open", f: { assignee?: boolean; mine?: boolean; mentions?: boolean } = {}) => ({
  number, title, state, url: "", labels, author, created: now - ago * 4, updated: now - ago, checks, ...f,
});
const BUG = lbl("bug", "d73a4a"), DOCS = lbl("docs", "0075ca"), FEAT = lbl("enhancement", "a2eeef"), SEARCH = lbl("search", "7057ff"), GOOD = lbl("good first issue", "7057ff"), PERF = lbl("performance", "fbca04");
w.__omherTasks = {
  status: { github: { installed: true, signed_in: true }, gitlab: { installed: true, signed_in: true } },
  remotes: { "/Users/you/code/web-app": { source: "github", repo: "acme/web-app" } },
  items: {
    "github:acme/web-app:issues": [
      issue(142, "Search results flicker when a filter is removed", [BUG, SEARCH], "mina", 0.6 * H, { assignee: true }),
      issue(139, "Dark mode: code blocks keep a light background", [BUG, DOCS], "sam", 3 * H, { mentions: true }),
      issue(137, "Remember the last used search filters", [FEAT, SEARCH], "you", 7 * H, { mine: true }),
      issue(134, "Docs sidebar is slow with 400+ pages", [PERF, DOCS], "lee", 26 * H, { assignee: true }),
      issue(131, "Add a copy button to code blocks", [FEAT, GOOD], "jules", 50 * H),
      issue(128, "Broken link to the API reference on the home page", [DOCS, GOOD], "sam", 75 * H, { mine: true }),
      issue(122, "Keyboard shortcut for search does not work in Firefox", [BUG], "ari", 6 * 24 * H),
    ],
    "github:acme/web-app:prs": [
      pr(146, "Docs dark mode", [DOCS, FEAT], "kami", 0.2 * H, { passed: 11, failed: 0, pending: 2, total: 13 }, "open", { mentions: true }),
      pr(145, "Search: wait for the index refresh in tests", [SEARCH], "kami", 0.8 * H, { passed: 13, failed: 0, pending: 0, total: 13 }, "open", { assignee: true }),
      pr(143, "Rate limits per API key", [FEAT], "you", 5 * H, { passed: 12, failed: 1, pending: 0, total: 13 }, "open", { mine: true }),
      pr(140, "Release notes for 2.4", [DOCS], "juno-bot", 9 * H, { passed: 0, failed: 0, pending: 0, total: 0 }, "draft"),
      pr(138, "Faster docs sidebar", [PERF], "lee", 30 * H, { passed: 13, failed: 0, pending: 0, total: 13 }),
    ],
  },
  details: {
    "github:acme/web-app:issues:142": {
      body: "When you remove the last filter chip the results list clears for a moment and then fills again.\n\n**Steps**\n1. Search for `token`\n2. Add the `api` filter, then remove it\n\nExpected: the list stays put while it refreshes.",
      comments: [
        { author: "sam", body: "Same on mobile. It looks like the list re-mounts.", created: now - 0.4 * H },
        { author: "kami", body: "The result list is keyed on the filter set, so it re-mounts. I can take this one.", created: now - 0.2 * H },
      ],
    },
    "github:acme/web-app:prs:146": {
      body: "Adds a dark theme to the docs site: 12 token pairs in `theme.css`, a toggle in the header that follows the system theme, and a dark code theme with the same contrast.\n\nEvery token pair passes WCAG AA.",
      checks: [
        { name: "build", state: "passed", url: "" },
        { name: "unit tests", state: "passed", url: "" },
        { name: "contrast check", state: "passed", url: "" },
        { name: "e2e (chromium)", state: "pending", url: "" },
        { name: "e2e (webkit)", state: "pending", url: "" },
      ],
    },
  },
};
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
