// What a link points at, read from the URL alone: no request, no login, no page fetch. `classifyLink` turns
// a URL into the service it belongs to (GitHub, Slack, Google Docs, YouTube, ...), what kind of thing it is
// (a pull request, a thread, a video, ...), and a short label for the chip that stands in for the bare URL.
// A host must BE the service's domain or one of its subdomains: `github.com.evil.io` is a plain web link.
// Anything not recognised is `service: "web"` with its domain as the label, so a lookalike shows where it goes.
// Service names stay as written; the kind words around them follow the current language.
import { t as tr, type Key } from "../../i18n";

/** "Slack channel" in the current language. */
const k = (svc: string, kind: Key) => tr("lk.svcKind", { svc, kind: tr(kind) });

export type LinkService =
  | "github"
  | "slack"
  | "discord"
  | "googledocs"
  | "googlesheets"
  | "googleslides"
  | "googleforms"
  | "googledrive"
  | "googlecalendar"
  | "googlemeet"
  | "gmail"
  | "googlemaps"
  | "google"
  | "x"
  | "linkedin"
  | "youtube"
  | "notion"
  | "linear"
  | "figma"
  | "npm"
  | "web";

export interface LinkInfo {
  service: LinkService;
  /** pr, issue, commit, repo, release, run, file, gist, compare, discussion, message, thread, channel, video ... */
  kind: string;
  /** The chip text. Slack and Discord carry a fallback here; the chip swaps in the channel name when known. */
  label: string;
  /** Parsed ids the chip may use: owner, repo, number, sha, channel, thread, ts, video, t, ... */
  meta: Record<string, string>;
}

const web = (host: string, path: string): LinkInfo => {
  const p = path === "/" ? "" : path.replace(/\/$/, "");
  const label = host + (p.length > 28 ? p.slice(0, 27) + "…" : p);
  return { service: "web", kind: "web", label, meta: { host } };
};

/** `host` is `domain` or one of its subdomains (label boundary, so `xgithub.com` and `github.com.evil.io` are not). */
function on(host: string, domain: string): boolean {
  return host === domain || host.endsWith("." + domain);
}

const seg = (path: string) =>
  path
    .split("/")
    .filter(Boolean)
    .map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    });

/** "83", "83s", "1m23s", "1h2m3s" -> seconds; null when it is not a time. */
export function parseT(t: string | null): number | null {
  if (!t) return null;
  if (/^\d+s?$/.test(t)) return parseInt(t, 10);
  const m = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(t);
  if (!m || !(m[1] || m[2] || m[3])) return null;
  return (+(m[1] ?? 0)) * 3600 + (+(m[2] ?? 0)) * 60 + +(m[3] ?? 0);
}

/** 83 -> "1:23", 3723 -> "1:02:03". */
export function clock(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

// First path segments on github.com that are pages of GitHub itself, not an owner.
const GH_RESERVED = new Set([
  "about", "account", "apps", "codespaces", "collections", "contact", "customer-stories", "dashboard", "enterprise",
  "events", "explore", "features", "issues", "login", "marketplace", "new", "notifications", "orgs", "organizations",
  "pricing", "pulls", "search", "security", "sessions", "settings", "signup", "site", "sponsors", "team", "topics",
  "trending", "users",
]);

function github(u: URL, p: string[]): LinkInfo {
  const host = u.hostname;
  const meta: Record<string, string> = {};
  if (host === "gist.github.com") {
    const [user, id] = p;
    if (user) meta.user = user;
    if (id) meta.id = id;
    return { service: "github", kind: "gist", label: user && id ? `gist · ${user}` : "GitHub Gist", meta };
  }
  if (!p.length || GH_RESERVED.has(p[0].toLowerCase())) return { service: "github", kind: "page", label: "GitHub", meta };
  const [owner, repo, kind, ...rest] = p;
  meta.owner = owner;
  if (!repo) return { service: "github", kind: "user", label: `@${owner}`, meta };
  meta.repo = repo;
  const full = `${owner}/${repo}`;
  const num = (s: string | undefined) => (s && /^\d+$/.test(s) ? s : null);
  switch (kind) {
    case "pull": {
      const n = num(rest[0]);
      if (!n) break;
      meta.number = n;
      return { service: "github", kind: "pr", label: `${full}#${n}`, meta };
    }
    case "issues": {
      const n = num(rest[0]);
      if (!n) break;
      meta.number = n;
      return { service: "github", kind: "issue", label: `#${n}`, meta };
    }
    case "discussions": {
      const n = num(rest[0]);
      if (!n) break;
      meta.number = n;
      return { service: "github", kind: "discussion", label: `${full} ${tr("lk.k.discussion")} #${n}`, meta };
    }
    case "commit": {
      if (!rest[0] || !/^[0-9a-f]{7,40}$/i.test(rest[0])) break;
      meta.sha = rest[0];
      return { service: "github", kind: "commit", label: `${full}@${rest[0].slice(0, 7)}`, meta };
    }
    case "releases": {
      if (rest[0] === "tag" && rest[1]) {
        meta.tag = rest.slice(1).join("/");
        return { service: "github", kind: "release", label: `${full} ${meta.tag}`, meta };
      }
      return { service: "github", kind: "releases", label: `${full} ${tr("lk.k.releases")}`, meta };
    }
    case "actions": {
      const n = rest[0] === "runs" ? num(rest[1]) : null;
      if (n) {
        meta.run = n;
        return { service: "github", kind: "run", label: tr("lk.ciRun"), meta };
      }
      return { service: "github", kind: "actions", label: `${full} actions`, meta };
    }
    case "blob":
    case "tree": {
      if (rest.length < 2) break;
      meta.ref = rest[0];
      meta.path = rest.slice(1).join("/");
      const name = rest[rest.length - 1];
      const line = /^L(\d+)(?:C\d+)?(?:-L(\d+))?/.exec(u.hash.slice(1));
      if (line) meta.line = line[1];
      const label = kind === "tree" ? `${name}/` : line ? `${name}:${line[1]}${line[2] ? `-${line[2]}` : ""}` : name;
      return { service: "github", kind: kind === "tree" ? "folder" : "file", label, meta };
    }
    case "compare": {
      const range = rest.join("/");
      if (!range) break;
      meta.range = range;
      return { service: "github", kind: "compare", label: tr("lk.compare", { range }), meta };
    }
  }
  return { service: "github", kind: "repo", label: full, meta };
}

function slack(u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  const host = u.hostname;
  const team = host.endsWith(".slack.com") && host !== "app.slack.com" ? host.slice(0, -".slack.com".length) : "";
  if (team) meta.workspace = team;
  // slack.com/app_redirect?channel=C…&team=T…
  if (p[0] === "app_redirect") {
    const ch = u.searchParams.get("channel");
    if (ch) {
      meta.channel = ch;
      return { service: "slack", kind: "channel", label: k("Slack", "lk.k.channel"), meta };
    }
  }
  // app.slack.com/client/T…/C…[/thread/C…-ts]
  if (p[0] === "client" && p[2]) {
    meta.channel = p[2];
    const th = p[3] === "thread" && p[4] ? /-(\d+\.\d+)$/.exec(p[4]) : null;
    if (th) {
      meta.thread = th[1];
      return { service: "slack", kind: "thread", label: `Slack · ${tr("lk.k.thread")}`, meta };
    }
    return { service: "slack", kind: "channel", label: k("Slack", "lk.k.channel"), meta };
  }
  // <team>.slack.com/archives/C…[/p1794195216893139][?thread_ts=…]
  if (p[0] === "archives" && p[1]) {
    meta.channel = p[1];
    const ts = p[2] && /^p(\d{10})(\d{6})$/.exec(p[2]);
    if (ts) meta.ts = `${ts[1]}.${ts[2]}`;
    const thread = u.searchParams.get("thread_ts");
    if (thread) {
      meta.thread = thread;
      return { service: "slack", kind: "thread", label: `Slack · ${tr("lk.k.thread")}`, meta };
    }
    if (ts) return { service: "slack", kind: "message", label: k("Slack", "lk.k.message"), meta };
    return { service: "slack", kind: "channel", label: k("Slack", "lk.k.channel"), meta };
  }
  if (team) return { service: "slack", kind: "workspace", label: `Slack · ${team}`, meta };
  return { service: "slack", kind: "page", label: "Slack", meta };
}

function discord(u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  if (u.hostname === "discord.gg" || u.hostname.endsWith(".discord.gg")) {
    if (p[0]) meta.invite = p[0];
    return { service: "discord", kind: "invite", label: p[0] ? `${k("Discord", "lk.k.invite")} · ${p[0]}` : "Discord", meta };
  }
  if ((p[0] === "invite" || p[0] === "invites") && p[1]) {
    meta.invite = p[1];
    return { service: "discord", kind: "invite", label: `${k("Discord", "lk.k.invite")} · ${p[1]}`, meta };
  }
  if (p[0] === "channels" && p[1]) {
    meta.guild = p[1];
    if (p[2]) {
      meta.channel = p[2];
      if (p[3]) {
        meta.message = p[3];
        return { service: "discord", kind: "message", label: k("Discord", "lk.k.message"), meta };
      }
      return { service: "discord", kind: "channel", label: k("Discord", "lk.k.channel"), meta };
    }
    return { service: "discord", kind: "server", label: p[1] === "@me" ? k("Discord", "lk.k.dms") : k("Discord", "lk.k.server"), meta };
  }
  return { service: "discord", kind: "page", label: "Discord", meta };
}

const GOOGLE_EDITORS: Record<string, [LinkService, string]> = {
  document: ["googledocs", "Google Docs"],
  spreadsheets: ["googlesheets", "Google Sheets"],
  presentation: ["googleslides", "Google Slides"],
  forms: ["googleforms", "Google Forms"],
};

/** Drop a leading `/u/<n>/` account switch (Docs, Drive, Gmail, Calendar). */
const dropAccount = (p: string[]) => (p[0] === "u" && /^\d+$/.test(p[1] ?? "") ? p.slice(2) : p);

function google(u: URL, p0: string[]): LinkInfo | null {
  const host = u.hostname;
  const meta: Record<string, string> = {};
  if (host === "docs.google.com") {
    const p = dropAccount(p0);
    const ed = GOOGLE_EDITORS[p[0]];
    if (ed) {
      const at = p.indexOf("d");
      if (at >= 0 && p[at + 1]) meta.id = p[at + 1] === "e" && p[at + 2] ? p[at + 2] : p[at + 1];
      return { service: ed[0], kind: p[0], label: ed[1], meta };
    }
    return { service: "googledrive", kind: "page", label: "Google Docs", meta };
  }
  if (host === "forms.gle") return { service: "googleforms", kind: "forms", label: "Google Forms", meta };
  if (host === "drive.google.com") {
    const p = dropAccount(p0);
    if (p[0] === "file" && p[1] === "d" && p[2]) {
      meta.id = p[2];
      return { service: "googledrive", kind: "file", label: k("Drive", "lk.k.file"), meta };
    }
    const fi = p.indexOf("folders");
    if (fi >= 0 && p[fi + 1]) {
      meta.id = p[fi + 1];
      return { service: "googledrive", kind: "folder", label: k("Drive", "lk.k.folder"), meta };
    }
    const id = u.searchParams.get("id");
    if (id) meta.id = id;
    return { service: "googledrive", kind: id ? "file" : "page", label: id ? k("Drive", "lk.k.file") : "Google Drive", meta };
  }
  if (host === "calendar.google.com") {
    const eid = u.searchParams.get("eid");
    const p = dropAccount(p0.slice(p0[0] === "calendar" ? 1 : 0));
    if (eid || p.includes("eventedit") || p[0] === "event") {
      if (eid) meta.eid = eid;
      return { service: "googlecalendar", kind: "event", label: tr("lk.calEvent"), meta };
    }
    return { service: "googlecalendar", kind: "page", label: "Google Calendar", meta };
  }
  if (host === "meet.google.com") {
    const code = p0[0] && /^[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(p0[0]) ? p0[0] : "";
    if (code) meta.code = code;
    return { service: "googlemeet", kind: code ? "meeting" : "page", label: code ? `Meet · ${code}` : "Google Meet", meta };
  }
  if (host === "mail.google.com") {
    const id = /\/([A-Za-z0-9]{16,})$/.exec(u.hash)?.[1];
    if (id) meta.thread = id;
    return { service: "gmail", kind: id ? "thread" : "page", label: id ? k("Gmail", "lk.k.thread") : "Gmail", meta };
  }
  if (host === "maps.app.goo.gl" || (host === "goo.gl" && p0[0] === "maps")) {
    return { service: "googlemaps", kind: "place", label: "Google Maps", meta };
  }
  const isGoogle = /^(?:www\.)?google\.(?:com|[a-z]{2}|co\.[a-z]{2}|com\.[a-z]{2})$/.test(host);
  if (isGoogle || host === "maps.google.com") {
    if (host === "maps.google.com" || p0[0] === "maps") {
      const pi = p0.indexOf("place");
      const name = pi >= 0 && p0[pi + 1] ? p0[pi + 1].replace(/\+/g, " ") : "";
      if (name) meta.place = name;
      return { service: "googlemaps", kind: name ? "place" : "map", label: name ? `Maps · ${name}` : "Google Maps", meta };
    }
    const q = p0[0] === "search" ? u.searchParams.get("q") : null;
    if (q) {
      meta.q = q;
      return { service: "google", kind: "search", label: `Google · ${q}`, meta };
    }
    return { service: "google", kind: "page", label: "Google", meta };
  }
  return null;
}

const X_RESERVED = new Set(["home", "explore", "search", "i", "settings", "notifications", "messages", "hashtag", "compose", "intent", "share", "login", "signup", "tos", "privacy"]);

function x(_u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  if (p[0] === "i" && p[1] === "web" && p[2] === "status" && p[3]) {
    meta.post = p[3];
    return { service: "x", kind: "post", label: k("X", "lk.k.post"), meta };
  }
  if (!p[0] || X_RESERVED.has(p[0].toLowerCase()) || !/^\w{1,15}$/.test(p[0])) return { service: "x", kind: "page", label: "X", meta };
  meta.user = p[0];
  if (p[1] === "status" && p[2] && /^\d+$/.test(p[2])) {
    meta.post = p[2];
    return { service: "x", kind: "post", label: `@${p[0]} · ${tr("lk.k.post")}`, meta };
  }
  return { service: "x", kind: "profile", label: `@${p[0]}`, meta };
}

function linkedin(u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  if (u.hostname === "lnkd.in") return { service: "linkedin", kind: "short", label: "LinkedIn", meta };
  if ((p[0] === "in" || p[0] === "pub") && p[1]) {
    meta.profile = p[1];
    return { service: "linkedin", kind: "profile", label: `in/${p[1]}`, meta };
  }
  if ((p[0] === "company" || p[0] === "school" || p[0] === "showcase") && p[1]) {
    meta.company = p[1];
    return { service: "linkedin", kind: "company", label: `LinkedIn · ${p[1]}`, meta };
  }
  if (p[0] === "jobs" && p[1] === "view" && p[2]) {
    meta.job = p[2].replace(/^.*-(\d+)$/, "$1");
    return { service: "linkedin", kind: "job", label: k("LinkedIn", "lk.k.job"), meta };
  }
  if (p[0] === "posts" || (p[0] === "feed" && p[1] === "update") || p[0] === "pulse") {
    return { service: "linkedin", kind: "post", label: k("LinkedIn", "lk.k.post"), meta };
  }
  return { service: "linkedin", kind: "page", label: "LinkedIn", meta };
}

function youtube(u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  const t = parseT(u.searchParams.get("t") ?? u.searchParams.get("start"));
  const at = t !== null && t > 0 ? ` · ${clock(t)}` : "";
  if (t !== null && t > 0) meta.t = String(t);
  let video = "";
  if (u.hostname === "youtu.be") video = p[0] ?? "";
  else if (p[0] === "watch") video = u.searchParams.get("v") ?? "";
  else if ((p[0] === "embed" || p[0] === "live" || p[0] === "v") && p[1]) video = p[1];
  if (video && /^[\w-]{6,20}$/.test(video)) {
    meta.video = video;
    return { service: "youtube", kind: "video", label: `YouTube · ${tr("lk.k.video")}${at}`, meta };
  }
  if (p[0] === "shorts" && p[1]) {
    meta.video = p[1];
    return { service: "youtube", kind: "short", label: `YouTube · ${tr("lk.k.short")}`, meta };
  }
  const list = u.searchParams.get("list");
  if (p[0] === "playlist" && list) {
    meta.list = list;
    return { service: "youtube", kind: "playlist", label: `YouTube · ${tr("lk.k.playlist")}`, meta };
  }
  if (p[0]?.startsWith("@")) {
    meta.handle = p[0];
    return { service: "youtube", kind: "channel", label: p[0], meta };
  }
  if ((p[0] === "c" || p[0] === "user") && p[1]) {
    meta.handle = p[1];
    return { service: "youtube", kind: "channel", label: `YouTube · ${p[1]}`, meta };
  }
  if (p[0] === "channel" && p[1]) {
    meta.channel = p[1];
    return { service: "youtube", kind: "channel", label: k("YouTube", "lk.k.channel"), meta };
  }
  return { service: "youtube", kind: "page", label: "YouTube", meta };
}

/** "Release-Notes-0f1e…" -> "Release Notes" (Notion and Figma put a readable name in the path). */
const titleOf = (slug: string) =>
  slug
    .replace(/-?[0-9a-f]{32}$/i, "")
    .replace(/[-_+]+/g, " ")
    .trim();

function notion(_u: URL, p: string[]): LinkInfo {
  const last = p[p.length - 1] ?? "";
  const id = /([0-9a-f]{32})$/i.exec(last)?.[1];
  const name = titleOf(last);
  const meta: Record<string, string> = id ? { id } : {};
  return { service: "notion", kind: id ? "page" : "site", label: name && id ? `Notion · ${name}` : "Notion", meta };
}

function linear(_u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  if (p[0]) meta.team = p[0];
  if (p[1] === "issue" && p[2] && /^[A-Z][A-Z0-9]*-\d+$/i.test(p[2])) {
    meta.issue = p[2].toUpperCase();
    return { service: "linear", kind: "issue", label: meta.issue, meta };
  }
  if (p[1] === "project" && p[2]) return { service: "linear", kind: "project", label: k("Linear", "lk.k.project"), meta };
  return { service: "linear", kind: "page", label: "Linear", meta };
}

function figma(_u: URL, p: string[]): LinkInfo {
  const meta: Record<string, string> = {};
  if (["file", "design", "proto", "board", "slides"].includes(p[0]) && p[1]) {
    meta.key = p[1];
    const name = p[2] ? titleOf(p[2]) : "";
    return { service: "figma", kind: p[0], label: name ? `Figma · ${name}` : k("Figma", "lk.k.file"), meta };
  }
  return { service: "figma", kind: "page", label: "Figma", meta };
}

function npm(_u: URL, p: string[]): LinkInfo {
  if (p[0] === "package" && p[1]) {
    const name = p[1].startsWith("@") && p[2] ? `${p[1]}/${p[2]}` : p[1];
    return { service: "npm", kind: "package", label: `npm · ${name}`, meta: { package: name } };
  }
  return { service: "npm", kind: "page", label: "npm", meta: {} };
}

/** The service, kind and chip label of `url`; null for anything that is not an http(s) URL. */
export function classifyLink(url: string): LinkInfo | null {
  let u: URL;
  try {
    u = new URL(url.trim());
  } catch {
    return null;
  }
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  if (u.username || u.password) return web(u.hostname, u.pathname); // user@host tricks stay plain
  const host = u.hostname.toLowerCase().replace(/\.$/, "");
  const bare = host.replace(/^(?:www|m|mobile)\./, "");
  const p = seg(u.pathname);
  if (bare === "github.com" || host === "gist.github.com") return github(u, p);
  if (on(host, "slack.com")) return slack(u, p);
  if (["discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"].includes(bare) || bare === "discord.gg") return discord(u, p);
  if (on(host, "google.com") || on(host, "goo.gl") || host === "forms.gle" || /^(?:www\.)?google\.[a-z.]+$/.test(host)) {
    const g = google(u, p);
    if (g) return g;
  }
  if (bare === "x.com" || bare === "twitter.com") return x(u, p);
  if (on(host, "linkedin.com") || host === "lnkd.in") return linkedin(u, p);
  if (bare === "youtube.com" || host === "music.youtube.com" || host === "youtu.be" || bare === "youtube-nocookie.com") return youtube(u, p);
  if (bare === "notion.so" || on(host, "notion.site")) return notion(u, p);
  if (bare === "linear.app") return linear(u, p);
  if (bare === "figma.com") return figma(u, p);
  if (bare === "npmjs.com") return npm(u, p);
  return web(host.replace(/^www\./, ""), u.pathname);
}

/** The http(s) URLs in a piece of plain text, with where each sits (trailing punctuation left out). */
export function findUrls(text: string): { url: string; start: number; end: number }[] {
  const out: { url: string; start: number; end: number }[] = [];
  const re = /https?:\/\/[^\s<>"'`]+/g;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    let url = m[0];
    // keep a closing bracket that has its opening one in the URL (wiki-style links), drop sentence punctuation
    while (/[.,;:!?)\]}>…]$/.test(url)) {
      const ch = url[url.length - 1];
      if ((ch === ")" && (url.match(/\(/g)?.length ?? 0) >= (url.match(/\)/g)?.length ?? 0)) || (ch === "]" && url.includes("["))) break;
      url = url.slice(0, -1);
    }
    out.push({ url, start: m.index, end: m.index + url.length });
  }
  return out;
}

/** Every http(s) link in a markdown text (bare, autolinked or `[text](url)`), first seen first, each once. */
export function linksIn(markdown: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  const add = (u: string) => {
    if (!seen.has(u)) {
      seen.add(u);
      out.push(u);
    }
  };
  // fenced and inline code are not links
  const text = markdown.replace(/```[\s\S]*?```/g, " ").replace(/`[^`\n]*`/g, " ");
  for (const { url } of findUrls(text)) add(url);
  return out;
}
