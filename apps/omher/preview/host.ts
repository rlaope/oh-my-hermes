// The preview's bridge: the same ops the Python bridge answers (src/lib/protocol.ts), served inside the page from
// a staged morning (the bots Kami, Friren, Juno and Pip; neutral project names). Nothing here talks to a network,
// a Hermes profile or an agent: `FakeSocket` stands in for the WebSocket the app opens, and every answer comes
// from the data below. Turns are played by the story (story.ts) or by `reply()` when the visitor types.
import docsLight from "./media/docs-light.webp?inline";
import docsDark from "./media/docs-dark.webp?inline";

type Json = Record<string, unknown>;
const MIN = 60;
export const nowS = () => Date.now() / 1000;

// ---- staged data --------------------------------------------------------------------------------------------

export const BOTS = [
  { name: "kami", display_name: "Kami", is_default: false, model: "Opus 5.5", provider: "claude-proxy", description: "team lead", status: "online", running: false },
  { name: "friren", display_name: "Friren", is_default: false, model: "Sonnet 5.5", provider: "claude-proxy", description: "research", status: "online", running: false },
  { name: "juno-bot", display_name: "Juno", is_default: false, model: "gpt-6.1-sol", provider: "openai", description: "releases", status: "online", running: false },
  { name: "pip", display_name: "Pip", is_default: false, model: "Haiku 4.5", provider: "claude-proxy", description: "notes", status: "online", running: false },
];
const REASONING: Record<string, string> = { kami: "high", friren: "medium", "juno-bot": "medium", pip: "low" };

type Row = { id: string; role: "user" | "assistant"; text: string; ts: number };
const seed = (bot: string, rows: [Row["role"], string, number][]): Row[] =>
  rows.map(([role, text, ago], i) => ({ id: `seed-${bot}-${i}`, role, text, ts: nowS() - ago }));

export function kamiSeed(): Row[] {
  return seed("kami", [
    ["user", "Did the search filters land last night?", 15 * 3600],
    ["assistant", "Yes: **PR #121** is merged. Tag and date filters are live on the docs, and 38 search tests pass.", 15 * 3600 - 60],
    ["user", "Morning! What needs me today?", 62 * MIN],
    ["assistant", "Three things today:\n\n1. **Review** the rate-limit PR in api-server (#126).\n2. **Answer** Mina in #design about the docs theme.\n3. **Approve** Juno's deploy once the tests pass.", 61 * MIN],
    ["user", "Review #126 and merge it if it's clean.", 24 * MIN],
    ["assistant", "Reviewed **#126**: fixed two nits, CI is green. Merged into main, and Juno's deploy picks it up.", 21 * MIN],
    ["user", "Can the docs get a dark mode today? Mina keeps asking.", 3 * MIN],
    ["assistant", "Yes. It's color tokens, a theme toggle, code colors and the page styles, then a contrast check, a final check and the PR. Say the word and I'll plan it.", 2.5 * MIN],
  ]);
}

export const history: Record<string, Row[]> = {
  kami: kamiSeed(),
  friren: seed("friren", [
    ["user", "Read the Tauri 2.4 release notes for me.", 50 * MIN],
    ["assistant", "The updater got delta downloads; I'll write it up.", 48 * MIN],
  ]),
  "juno-bot": seed("juno-bot", [
    ["user", "What's in today's api-server release?", 70 * MIN],
    ["assistant", "Three changes: the **rate limits** from #126, a faster `/search` index, and the Go 1.26 bump. No migrations.", 69 * MIN],
    ["user", "Deploy api-server when the tests pass.", 40 * MIN],
    ["assistant", "On it. I'll wait for CI on main and ping you before anything goes out.", 39 * MIN],
    ["assistant", "Tests are green: **214 passed**, 0 failed. Ready to deploy.", 2 * MIN],
  ]),
  pip: seed("pip", [
    ["user", "File today's standup notes.", 3 * 3600],
    ["assistant", "Filed under Notes / Standups.", 160 * MIN],
  ]),
};

type AwaySeed = { id: string; source: string; title: string; place: string | null; url: string | null; target: string | null; reply: string; startedAt: number; lastAt: number; count: number; running?: boolean };
export const away: Record<string, AwaySeed[]> = {
  kami: [],
  friren: [],
  "juno-bot": [
    { id: "slack-releases-juno", source: "slack", title: "release train", place: "#releases", url: "slack://channel?team=T1&id=C3", target: "slack:C03RELEASES:1794200000.000200", reply: "api-server 2.4 is queued behind the tests. I'll post here when it's live.", startedAt: nowS() - 90 * MIN, lastAt: nowS() - 30 * MIN, count: 5 },
    { id: "discord-ops-juno", source: "discord", title: "on-call", place: "#ops", url: "https://discord.com/channels/1/12", target: "discord:900000000000000012", reply: "Staging p95 is back to 84 ms after the cache fix.", startedAt: nowS() - 5 * 3600, lastAt: nowS() - 3 * 3600, count: 9 },
    { id: "cron-juno-nightly", source: "cron", title: "nightly smoke test", place: null, url: null, target: null, reply: "Nightly smoke test passed: 61 of 61.", startedAt: nowS() - 9 * 3600, lastAt: nowS() - 9 * 3600 + 300, count: 2 },
  ],
  pip: [],
};

const ROUTINES: Record<string, Json[]> = {
  kami: [{ id: "cron-digest", name: "Morning digest", schedule: "Daily 09:00", next: 15 * 3600, last: -9 * 3600 }],
  "juno-bot": [
    { id: "cron-deploy-check", name: "Post-deploy health check", schedule: "After each deploy", next: 20 * MIN, last: -22 * 3600 },
    { id: "cron-release-notes", name: "Release notes draft", schedule: "Daily 17:00", next: 8 * 3600, last: -16 * 3600 },
    { id: "cron-dep-audit", name: "Dependency audit", schedule: "Mondays 09:00", next: 6 * 86400, last: -86400 },
  ],
};
const INFO: Record<string, Json> = {
  kami: { places: { slack: 41, discord: 12, cron: 6 }, first: 30 * 86400, skills: 120 },
  friren: { places: { telegram: 6 }, first: 9 * 86400, skills: 14 },
  "juno-bot": { places: { slack: 9, discord: 4 }, first: 5 * 86400, skills: 20 },
  pip: { places: { telegram: 3 }, first: 12 * 86400, skills: 9 },
};
// Automations: every bot's cron jobs (the bridge reads each profile's cron/jobs.json), on the same clock as the
// Schedule tab's routines above. [bot, id, name, cron line, next, last, status, deliver, made (days ago), runs, prompt]
type AutoSeed = [string, string, string, string, number | null, number | null, string | null, string, number, number, string];
const AUTOMATIONS: AutoSeed[] = [
  ["kami", "cron-digest", "Morning digest", "0 9 * * *", 15 * 3600, -9 * 3600, "ok", "bot-chat:kami", 30, 29,
    "Go through yesterday's PRs, issues and team threads and give me what needs me today, five lines at most."],
  ["kami", "cron-pr-sweep", "Open PR sweep", "0 17 * * 1-5", 8 * 3600, -16 * 3600, "ok", "origin", 12, 9,
    "Sort the open PRs in api-server and docs into: needs review, CI broken, ready to merge."],
  ["juno-bot", "cron-deploy-check", "Post-deploy health check", "every 30m", 20 * MIN, -10 * MIN, "ok", "bot-chat:juno-bot", 5, 212,
    "Check api-server's health endpoint and p95 latency; say something only when either is off."],
  ["juno-bot", "cron-release-notes", "Release notes draft", "0 17 * * 1-5", 8 * 3600, -16 * 3600, "ok", "origin", 5, 4,
    "Draft today's release notes for api-server from the merged PRs."],
  ["juno-bot", "cron-dep-audit", "Dependency audit", "0 9 * * 1", 6 * 86400, -86400, "error", "local", 5, 1,
    "Run the dependency audit on api-server and list anything with a known advisory."],
  ["friren", "cron-tauri-watch", "Tauri release watch", "0 8 * * *", 16 * 3600, -8 * 3600, "ok", "bot-chat:friren", 9, 8,
    "Check the Tauri releases page; write up anything new that touches the updater or the bundler."],
  ["pip", "cron-standup", "Standup notes", "30 9 * * 1-5", 17 * 3600, -7 * 3600, "ok", "bot-chat:pip", 12, 9,
    "Collect this morning's standup updates from #team and file them under Notes / Standups."],
];
const ORIGIN: Record<string, { platform: string; place: string }> = {
  "cron-pr-sweep": { platform: "slack", place: "#eng" },
  "cron-release-notes": { platform: "slack", place: "#releases" },
};
const automations = AUTOMATIONS.map(([bot, id, name, schedule, next, last, status, deliver, made, runsN, prompt]) => ({
  bot, id, name, schedule, next, last, status, deliver, made, runs: runsN, prompt, paused: false,
}));
const automationRow = (a: (typeof automations)[number]) => ({
  id: a.id, name: a.name, schedule: a.schedule, bot: a.bot,
  next_run_at: a.paused || a.next === null ? null : nowS() + a.next,
  last_run_at: a.last === null ? null : nowS() + a.last,
  last_status: a.status, enabled: !a.paused, paused: a.paused, prompt: a.prompt, script: null, deliver: a.deliver,
  origin: a.deliver === "origin" ? (ORIGIN[a.id] ?? null) : null, created_at: nowS() - a.made * 86400,
  last_error: a.status === "error" ? "pnpm audit: registry timed out after 60s" : null, repeat: { times: null, completed: a.runs },
});

// Plugins: the curated catalog (a slice of the official and verified entries of Hermes' plugin catalog cache, as
// the bridge's read_catalog returns them), and each bot's installs as `plugins.manage list` rows.
// name, title, category, tier, version, repo, maintainer, platforms, tools, hooks, needs env, description, pin
const CATALOG_ROWS: [string, string, string, string, string, string, string, string[], string[], string[], string[], string, string][] = [
  ["advanced-delegation", "Advanced Delegation", "tools", "official", "1.1.1", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], [], "Two extra delegation modes for `delegate_task`, next to the built-in default.", "13b2c1c9c8204bf333df240b2aacf98c3e6250b7"],
  ["agent-importers", "", "tools", "official", "1.2.1", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], [], "`hermes import-agent`: import an OpenClaw (~/.openclaw, or legacy ~/.clawdbot / ~/.moltbot), Claude Code (~/.claude), Codex CLI (~/.codex), Cursor (~/.cursor), Grok…", "471acd3b4d0d5c12f6f0f6b42db4a2f52a912dba"],
  ["apify", "Apify", "web", "verified", "0.1.5", "apify/apify-hermes-agent-plugin", "apify", [], ["apify_discover", "apify_start", "apify_collect"], [], ["APIFY_API_TOKEN"], "Apify, the largest marketplace of tools for AI: discover, run, and collect results from thousands of ready-to-run Actors, from the comfort of your agent, plus an…", "a3a7af0c0dda9fdac79d67fb0a7a50b7a39cd91d"],
  ["blender", "Blender", "tools", "official", "0.4.1", "NousResearch/hermes-official-plugins", "NousResearch", ["windows", "macos", "linux"], [], [], [], "Official Blender Lab MCP server over stdio, pinned to upstream v1.0.3, with a Blender workflow skill.", "9b11ffeda84b077bea9de52d22733c7a41ca581a"],
  ["camofox", "", "web", "official", "1.1.0", "NousResearch/hermes-official-plugins", "NousResearch", [], ["browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_scroll", "browser_back", "browser_press", "browser_get_images", "browser_vision", "browser_console", "browser_import_cookies"], ["on_session_end", "on_session_finalize"], ["CAMOFOX_URL"], "Camofox browser backend: browse with a self-hosted anti-detection Firefox (Camoufox, C++ fingerprint spoofing) through the camofox-browser REST server.", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["elevenlabs-music", "ElevenLabs Music", "tools", "official", "1.0.0", "NousResearch/hermes-official-plugins", "NousResearch", [], ["elevenlabs_music_compose", "elevenlabs_music_compose_plan", "elevenlabs_music_draft_plan", "elevenlabs_music_upload", "elevenlabs_music_stems", "elevenlabs_music_from_video", "elevenlabs_music_finetunes", "elevenlabs_music_job"], [], ["ELEVENLABS_API_KEY"], "ElevenLabs Music for Hermes: describe a song or paste your lyrics and Hermes writes, generates and sends the track, 3 seconds to 10 minutes, vocals or instrumental.", "1e326ddd28ae261821d7714d106fe114999a0bba"],
  ["elevenlabs-sound-effects", "ElevenLabs Sound Effects", "tools", "official", "1.2.0", "NousResearch/hermes-official-plugins", "NousResearch", [], ["elevenlabs_sound_effect"], [], ["ELEVENLABS_API_KEY"], "ElevenLabs sound effects for Hermes: one tool, elevenlabs_sound_effect, that turns a text description (\"glass shattering on a tile floor\", \"90s hip-hop drum loop…", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["hermes-security", "Security", "tools", "official", "0.1.3", "NousResearch/hermes-official-plugins", "NousResearch", [], ["security_scan_start", "security_scan_get", "security_scan_checkpoint", "security_scan_submit_worker_result", "security_scan_record_validations", "security_scan_record_chains", "security_scan_finalize", "security_scan_cancel", "security_scan_export"], ["on_session_end", "subagent_start", "subagent_stop"], [], "Security review for a local repository.", "8b5b6296bbb900f90e296b4729d2c9a5d1139825"],
  ["homeassistant", "", "platform", "official", "2.0.1", "NousResearch/hermes-official-plugins", "NousResearch", [], ["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"], [], ["HASS_TOKEN"], "Home Assistant gateway platform (state-change events in, persistent notifications and cron notify delivery out) plus the homeassistant toolset (ha_list_entities…", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["langfuse", "", "general", "official", "2.0.0", "NousResearch/hermes-official-plugins", "NousResearch", [], [], ["pre_api_request", "post_api_request", "api_request_error", "pre_llm_call", "post_llm_call", "pre_tool_call", "post_tool_call", "on_session_finalize", "on_session_end", "subagent_start", "subagent_stop"], ["HERMES_LANGFUSE_PUBLIC_KEY", "HERMES_LANGFUSE_SECRET_KEY"], "Langfuse observability for Hermes: one trace per turn, one generation per LLM call (usage and cost from Hermes' own pricing, cache and reasoning tokens included)…", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["mcp-serve", "", "tools", "official", "1.0.0", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], [], "Run Hermes as an MCP server: `hermes mcp-serve` lets any MCP client (Claude Code, Claude Desktop, Cursor, Codex) list and read your messaging conversations, poll…", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["meshy", "Meshy", "tools", "official", "0.5.0", "NousResearch/hermes-official-plugins", "NousResearch", ["windows", "macos", "linux"], [], [], ["MESHY_API_KEY"], "Meshy AI's own MCP server (pinned @meshy-ai/meshy-mcp-server@0.6.5) for text, image and multi-image to 3D, texturing, remeshing, rigging, animation, concept images…", "2937702cb55bf4c56cbaf71f6467479e3eb4f2ba"],
  ["spotify", "", "tools", "official", "2.1.0", "NousResearch/hermes-official-plugins", "NousResearch", [], ["spotify_playback", "spotify_devices", "spotify_queue", "spotify_search", "spotify_playlists", "spotify_albums", "spotify_library"], [], [], "Spotify for Hermes: seven tools (playback, devices, queue, search, playlists, albums, library) over the Spotify Web API, plus `hermes spotify login|status|logout`…", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["tavily-plugin", "Tavily", "web", "verified", "1.0.0", "tavily-ai/tavily-hermes-plugin", "tavily-ai", [], [], [], ["TAVILY_API_KEY"], "Search, extract, map, crawl, and research through Tavily hosted MCP, with Tavily skills.", "ac556341056dc903988f63d627d595e468f1cfa9"],
  ["tinyfish", "TinyFish", "web", "verified", "0.2.5", "tinyfish-io/tinyfish-web-agent-integrations", "tinyfish-io", [], ["tinyfish_agent", "tinyfish_list_profiles", "tinyfish_create_profile", "tinyfish_profile_sign_in", "tinyfish_update_profile", "tinyfish_delete_profile"], ["pre_tool_call", "pre_llm_call", "on_session_finalize"], ["TINYFISH_API_KEY"], "TinyFish: the web, built into Hermes.", "2b29d5c864d08fd9716d6f15c3eafdf487b148d3"],
  ["xchat", "", "platform", "official", "0.1.0", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], ["XCHAT_ACCESS_TOKEN"], "X Chat gateway platform: talk to Hermes in X's end-to-end encrypted DMs.", "e7a218f26db88426ab3e7376f0e000b6e356f5e7"],
  ["cua-spaces", "Cua Spaces", "tools", "verified", "0.4.0", "trycua/hermes-cua-spaces", "trycua", [], [], [], [], "Cua's own plugin: runs Hermes's terminal, file and code tools inside a Cua Space, an isolated Linux, macOS or Windows machine you can watch live, as a terminal…", "82bb8d31517d2d1b8f1ef7f64701558dcac8aea9"],
  ["reka-provider", "Reka", "models", "verified", "1.0.3", "reka-ai/reka-hermes", "reka-ai", [], [], [], ["REKA_API_KEY"], "Reka as a Hermes model provider: Reka's agent-capable models on Reka's OpenAI-compatible API, each with its context window, tool support and image input declared…", "df031f732c9eddf8b39a0fa240b898da4ca2d6ff"],
  ["snyk", "", "tools", "official", "", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], [], "Scan code (SAST), dependencies, container images, IaC and SBOMs with Snyk through its first-party MCP server (pinned snyk@1.1306.0 over npx stdio, CLI analytics…", "abec9e822a23089943dd1d476a104bf746f19f86"],
  ["touchdesigner", "", "tools", "official", "", "NousResearch/hermes-official-plugins", "NousResearch", [], [], [], [], "Drive a live TouchDesigner session through the twozero MCP server (Streamable HTTP on 127.0.0.1:40404), with the touchdesigner-mcp workflow skill bundled.", "abec9e822a23089943dd1d476a104bf746f19f86"],
];
const CATALOG = CATALOG_ROWS.map(([name, title, category, tier, version, repo, maintainer, platforms, tools, hooks, env, description, sha]) => ({
  name, title, category, tier, version, repo: `https://github.com/${repo}`, maintainer, platforms, tools, hooks, requires_env: env, description, sha,
}));
const CATEGORIES = ["automation", "tools", "memory", "voice", "web", "desktop", "models", "platform", "general"];
const TIER_RANK: Record<string, number> = { official: 0, verified: 1, community: 2 };
type PluginRow = { name: string; key: string; title: string; version: string; description: string; source: string; enabled: boolean; tier: string; category: string; catalog_name: string | null; tools: number; hooks: number; update_available: boolean; needs_env: string[] };
const fromCatalog = (name: string, enabled: boolean, extra: Partial<PluginRow> = {}): PluginRow => {
  const c = CATALOG.find((e) => e.name === name)!;
  return { name, key: name, title: c.title, version: c.version, description: c.description, source: "user", enabled, tier: c.tier, category: c.category, catalog_name: name, tools: c.tools.length, hooks: c.hooks.length, update_available: false, needs_env: [], ...extra };
};
const BUILTIN: PluginRow[] = [
  { name: "disk-cleanup", key: "disk-cleanup", title: "", version: "2.0.0", description: "Auto-track and clean up ephemeral files (test scripts, temp outputs, cron logs) created during Hermes sessions.", source: "bundled", enabled: true, tier: "bundled", category: "general", catalog_name: null, tools: 0, hooks: 3, update_available: false, needs_env: [] },
  { name: "fal", key: "image_gen/fal", title: "", version: "1.0.0", description: "FAL.ai image generation backend.", source: "bundled", enabled: true, tier: "bundled", category: "tools", catalog_name: null, tools: 0, hooks: 0, update_available: false, needs_env: [] },
  { name: "browserbase", key: "browser/browserbase", title: "", version: "1.0.0", description: "Browserbase cloud browser backend for the browser tools.", source: "bundled", enabled: false, tier: "bundled", category: "web", catalog_name: null, tools: 0, hooks: 0, update_available: false, needs_env: ["BROWSERBASE_API_KEY"] },
  { name: "google_meet", key: "google_meet", title: "", version: "0.2.0", description: "Join a Google Meet call, transcribe live captions, speak in realtime, and follow up afterwards.", source: "bundled", enabled: false, tier: "bundled", category: "tools", catalog_name: null, tools: 5, hooks: 1, update_available: false, needs_env: [] },
];
const OMH_PLUGIN: PluginRow = { name: "omh", key: "omh", title: "", version: "4.0.7", description: "Oh My Hermes native bridge: runtime status, HUD, role context, bounded evidence probes and a file-backed memory provider.", source: "user", enabled: true, tier: "user", category: "tools", catalog_name: null, tools: 28, hooks: 12, update_available: false, needs_env: [] };
const plugins: Record<string, PluginRow[]> = {
  kami: [OMH_PLUGIN, fromCatalog("hermes-security", true), fromCatalog("tavily-plugin", true, { update_available: true }), fromCatalog("elevenlabs-music", false, { needs_env: ["ELEVENLABS_API_KEY"] }), ...BUILTIN],
  friren: [fromCatalog("tavily-plugin", true), ...BUILTIN],
  "juno-bot": [OMH_PLUGIN, fromCatalog("langfuse", true), ...BUILTIN],
  pip: [...BUILTIN],
};

const SKILLS = [
  { name: "dag-ulw", description: "Plan big work as parts that run in parallel, each checked before it counts." },
  { name: "plan", description: "Break the work into steps and agree on them before doing it." },
  { name: "research", description: "Find sources, read them and answer with citations." },
  { name: "review", description: "Review a diff for correctness, tests and risk, worst first." },
];
const PROVIDERS = [
  { slug: "claude-proxy", name: "Claude (proxy)", models: ["Opus 5.5", "Sonnet 5.5", "Haiku 4.5"] },
  { slug: "openai", name: "OpenAI", models: ["gpt-6.1-sol", "gpt-6.1-sol-mini"] },
  { slug: "openrouter", name: "OpenRouter", models: ["google/gemini-3-pro", "deepseek/deepseek-v4.1", "x-ai/grok-4.7", "qwen/qwen3-coder"] },
];
const models: Record<string, Json> = Object.fromEntries(BOTS.map((b) => [b.name, { model: b.model, provider: b.provider, reasoning: REASONING[b.name] }]));

// Plans: past ones are fixed; the story writes the live one (`setLiveRun`) and its handoff text.
export const runs: { live: Json | null; past: Json[]; handoffs: Record<string, Record<string, string>> } = { live: null, past: [], handoffs: {} };
function pastRun(id: string, title: string, goal: string, ago: number, dur: number, spec: [string, number[], string, string, string, string?][]): Json {
  const t = nowS();
  const nodes = spec.map(([label, deps, model, effort, route, executor], i) => {
    const s0 = t - ago - dur + i * 90, s1 = s0 + 240 + i * 50;
    return { id: `p${i}`, label, deps: deps.map((d) => `p${d}`), layer: 0, state: "done", model, effort, route, ...(executor ? { executor } : {}), started: s0, ended: s1, attempts: [{ n: 1, outcome: "accepted", started: s0, ended: s1 }] };
  });
  return { id, kind: "dag", owner: { type: "bot", id: "kami" }, title, goal, state: "done", started: t - ago - dur, ended: t - ago, updated: t - ago, nodes };
}
runs.past = [
  pastRun("dag:20261109_160200_aa11bb22/search-filters", "Search filters", "Add tag and date filters to docs search.", 17 * 3600, 34 * MIN, [
    ["Filter index", [], "gpt-6.1-sol", "medium", "quick", "codex"],
    ["Filter chips UI", [], "Opus 5.5", "high", "visual-engineering"],
    ["Query parser", [0, 1], "Kimi K3", "high", "deep"],
    ["Search tests", [0, 1], "DeepSeek V4.1", "medium", "quick"],
    ["Review and PR", [2, 3], "Opus 5.5", "high", "review"],
  ]),
  pastRun("dag:20261108_101500_cc33dd44/api-rate-limit", "API rate limits", "Rate-limit the public API per key.", 2 * 86400, 22 * MIN, [
    ["Token bucket", [], "GLM-5.3", "high", "deep"],
    ["Limit headers", [], "gpt-6.1-sol", "medium", "quick", "codex"],
    ["Load test", [0, 1], "DeepSeek V4.1", "high", "review"],
    ["Review and PR", [2], "Opus 5.5", "high", "review"],
  ]),
];
runs.handoffs["dag:20261109_160200_aa11bb22/search-filters"] = {
  p4: "- Merged #121: tag and date filters on docs search\n- 38 search tests pass; p95 query time 41 ms\n- Filter chips keep the URL in sync",
};

const counts = (nodes: Json[]) => ({
  nodes: nodes.length,
  done: nodes.filter((n) => n.state === "done").length,
  running: nodes.filter((n) => n.state === "running").length,
  failed: nodes.filter((n) => n.state === "failed").length,
});
const allRuns = () => [...(runs.live ? [runs.live] : []), ...runs.past];
/** GitHub's state of the PRs the live plan's parts opened (the real bridge asks `gh`; staged here). */
export const PR_REPO = "rlaope/oh-my-hermes";
export const PR_STATES: Record<number, string> = { 2353: "merged", 2352: "merged", 2359: "open", 2360: "draft" };

// ---- media: the before/after the story's last message names ----------------------------------------------------

const MEDIA: Record<string, string> = { "/w/media/docs-light.webp": docsLight, "/w/media/docs-dark.webp": docsDark };

// ---- ops ----------------------------------------------------------------------------------------------------

class OpError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}
const need = (p: Json) => {
  const b = BOTS.find((x) => x.name === p.bot);
  if (!b) throw new OpError("unknown_bot", `no bot named ${String(p.bot)}`);
  return b;
};
const awayRows = (bot: string) =>
  (away[bot] ?? [])
    .map((a) => ({
      id: a.id, source: a.source, label: a.title, title: a.title, started_at: a.startedAt, last_active: a.lastAt,
      message_count: a.count, running: !!a.running, url: a.url, place: a.place, last_reply: a.reply, last_reply_at: a.lastAt, reply_target: a.target,
    }))
    .sort((x, y) => y.last_active - x.last_active);

/** Hooks the story fills in: what a visitor's message or approval sets off. */
export const hooks: {
  send: (bot: string, text: string) => void;
  approve: (bot: string, requestId: string, choice: string) => void;
  clarify: (bot: string, requestId: string) => void;
  interrupt: (bot: string) => void;
  folder: (bot: string, session: string) => void;
} = { send: () => {}, approve: () => {}, clarify: () => {}, interrupt: () => {}, folder: () => {} };

const OPS: Record<string, (p: Json) => unknown> = {
  hello: () => ({ bridge: "mock", version: "preview", hermes: { home: "(preview: staged data)", version: "preview" } }),
  "bots.list": () => ({ bots: BOTS.map((b) => ({ ...b, ...(models[b.name] as object), avatar_rev: null })) }),
  "chat.open": (p) => {
    const b = need(p);
    const m = models[b.name] as Json;
    return { session_id: `main-${b.name}`, messages: history[b.name], running: false, model: m.model, provider: m.provider, reasoning: m.reasoning };
  },
  "chat.send": (p) => {
    const b = need(p);
    const text = String(p.text ?? "").trim();
    if (!text) throw new OpError("bad_request", "missing text");
    if (p.session) {
      setTimeout(() => hooks.folder(b.name, String(p.session)), 0);
      return { input_id: "preview" };
    }
    history[b.name].push({ id: `u-${Math.random().toString(36).slice(2, 9)}`, role: "user", text, ts: nowS() });
    setTimeout(() => hooks.send(b.name, text), 0);
    return { input_id: "preview" };
  },
  "chat.interrupt": (p) => {
    const b = need(p);
    if (p.session) broadcast({ event: "turn.end", bot: b.name, session: String(p.session), outcome: "interrupted" });
    else hooks.interrupt(b.name);
    return {};
  },
  "approval.respond": (p) => (hooks.approve(need(p).name, String(p.request_id), String(p.choice)), {}),
  "clarify.respond": (p) => (hooks.clarify(need(p).name, String(p.request_id)), {}),
  "elsewhere.list": (p) => ({ sessions: awayRows(need(p).name) }),
  "elsewhere.peek": (p) => ({ messages: [], total: (away[need(p).name] ?? []).find((a) => a.id === p.session_id)?.count ?? 0 }),
  "routines.list": (p) => ({
    routines: (ROUTINES[need(p).name] ?? []).map((r) => ({ id: r.id, name: r.name, schedule: r.schedule, next_run_at: nowS() + (r.next as number), last_run_at: nowS() + (r.last as number), last_status: "ok", enabled: true })),
  }),
  "models.options": (p) => ({ providers: PROVIDERS, current: { ...(models[need(p).name] as object) }, reasoning_levels: ["none", "low", "medium", "high", "xhigh"] }),
  "chat.set_model": (p) => {
    const b = need(p);
    const cur = models[b.name];
    models[b.name] = { model: p.model ?? cur.model, provider: p.provider ?? cur.provider, reasoning: p.reasoning ?? cur.reasoning };
    return { ...(models[b.name] as object) };
  },
  "bots.info": (p) => {
    const i = INFO[need(p).name] as { places: Json; first: number; skills: number };
    return { places: { ...i.places }, first_active: nowS() - i.first, last_active: nowS() - 20, skills: i.skills, routines: (ROUTINES[String(p.bot)] ?? []).length };
  },
  "bots.avatar": () => ({ rev: null, data: null }),
  "skills.list": (p) => (need(p), { skills: SKILLS }),
  "panel.terminal": () => ({ runs: [] }),
  "panel.worktrees": () => ({ worktrees: [] }),
  "panel.diff": () => {
    throw new OpError("not_found", "nothing to show in the preview");
  },
  "media.read": (p) => {
    const path = String(p.path ?? "");
    const url = MEDIA[path];
    if (!url) throw new OpError("not_found", "not a file this bot sent");
    const data = url.slice(url.indexOf(",") + 1);
    const out = { path, name: path.split("/").pop(), mime: "image/webp", size: Math.round((data.length * 3) / 4) };
    return p.info === true ? out : { ...out, data_base64: data };
  },
  "runs.list": (p) => ({ runs: need(p).name === "kami" ? allRuns().map(({ nodes, ...r }) => ({ ...r, counts: counts(nodes as Json[]) })) : [] }),
  "runs.get": (p) => {
    const run = allRuns().find((r) => r.id === p.run);
    if (!run) throw new OpError("not_found", "no such plan");
    return { run: structuredClone(run), handoffs: { ...(runs.handoffs[String(run.id)] ?? {}) } };
  },
  "runs.prs": (p) => {
    const run = allRuns().find((r) => r.id === p.run);
    if (!run) throw new OpError("not_found", "no such plan");
    const prs: Record<string, Json> = {};
    for (const n of run.nodes as Json[]) {
      const pr = n.pr as { number: number; repo?: string } | undefined;
      if (pr) prs[String(n.id)] = { ...pr, state: (pr.repo === PR_REPO && PR_STATES[pr.number]) || "unknown" };
    }
    return { prs };
  },
  "automations.list": () => ({ automations: automations.map(automationRow) }),
  "plugins.list": (p) => ({ plugins: structuredClone(plugins[need(p).name] ?? BUILTIN) }),
  "plugins.catalog": (p) => {
    need(p);
    const q = typeof p.query === "string" ? p.query.trim().toLowerCase() : "";
    const category = String(p.category ?? "");
    const hits = CATALOG.filter((e) => (!category || e.category === category) && (!q || `${e.name} ${e.title} ${e.description}`.toLowerCase().includes(q)))
      .sort((a, b) => (TIER_RANK[a.tier] ?? 3) - (TIER_RANK[b.tier] ?? 3) || a.name.localeCompare(b.name))
      .map(({ sha: _sha, ...e }) => e);
    const categories = Object.fromEntries(CATEGORIES.map((c) => [c, CATALOG.filter((e) => e.category === c).length]));
    return { total: CATALOG.length, matched: hits.length, entries: hits, categories, generated_at: new Date(Date.now() - 86400_000).toISOString() };
  },
  "plugins.inspect": (p) => {
    need(p);
    const c = CATALOG.find((e) => e.name === p.catalog_name);
    if (!c) throw new OpError("not_found", `${String(p.catalog_name)} is not in the plugin catalog`);
    const { sha, ...entry } = c;
    return { entry, sha, agent: c.tools.length + c.hooks.length > 0, desktop: c.category === "desktop", warnings: [] };
  },
  "links.places": (p) => (need(p), { places: { slack: { C02DESIGN: "design", C03RELEASES: "releases" }, discord: { "900000000000000009": "releases", "900000000000000012": "ops" } } }),
  "cli.title": () => ({ title: "" }),
  // an oh-my-hermes session: a Hermes chat of the bot in that folder (the story answers its first message)
  "folder.open": (p) => {
    const b = need(p);
    const m = models[b.name] as Json;
    return { session: `fold-${Math.random().toString(36).slice(2, 8)}`, cwd: String(p.cwd ?? ""), model: m.model, provider: m.provider, reasoning: m.reasoning };
  },
  "folder.close": () => ({}),
  "runs.cli": () => ({ runs: [], agents: { claude: "found", codex: "found", pi: "found", omp: "found", grok: "not_installed" } }),
  "usage.read": () => ({
    providers: [
      { id: "claude", plan: "max", state: "ok", source_mtime: nowS() - 60, windows: [{ label: "5 hours", used_percent: 46, resets_at: nowS() + 132 * MIN }, { label: "Weekly", used_percent: 31, resets_at: nowS() + 4 * 86400 }] },
      { id: "codex", plan: "pro", state: "ok", source_mtime: nowS() - 120, windows: [{ label: "5 hours", used_percent: 62, resets_at: nowS() + 107 * MIN }, { label: "Weekly", used_percent: 38, resets_at: nowS() + 5 * 86400 }] },
    ],
  }),
  "accounts.list": () => ({
    groups: ["claude", "codex", "pi", "omp", "grok", "gemini"].map((cli) => ({
      cli, installed: ["claude", "codex", "pi", "omp"].includes(cli), active: "default",
      accounts: [{ id: "default", label: "", email: cli === "claude" ? "you@example.com" : "", state: ["claude", "codex", "pi"].includes(cli) ? "active" : "login", dir: null, usage: null }],
    })),
  }),
};
// Writes the app can ask for: refused with a plain reason (nothing is stored anywhere).
for (const op of [
  "bots.rename", "bots.set_avatar", "chat.attach", "accounts.add", "accounts.set_active", "accounts.label", "accounts.remove", "accounts.discard",
  "automations.add", "automations.pause", "automations.resume", "automations.remove",
  "plugins.install", "plugins.toggle", "plugins.update", "plugins.remove",
])
  OPS[op] = () => {
    throw new OpError("preview", "This is a preview: download omher to do this for real.");
  };

// ---- the stand-in socket --------------------------------------------------------------------------------------

const open = new Set<FakeSocket>();
/** An event to every connected client (the app's store and any short-lived second client). */
export function broadcast(ev: Json): void {
  const data = JSON.stringify(ev);
  for (const s of open) s.onmessage?.({ data } as MessageEvent);
}
export const calls: { op: string; at: number }[] = [];

export class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(public url: string) {
    setTimeout(() => {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      open.add(this);
      this.onopen?.(new Event("open"));
    }, 0);
  }
  send(raw: string): void {
    let msg: Json;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }
    const { id, op, ...params } = msg as { id: string; op: string } & Json;
    calls.push({ op, at: Date.now() });
    let reply: Json;
    try {
      const fn = Object.hasOwn(OPS, op) ? OPS[op] : null;
      if (!fn) throw new OpError("unknown_op", `no such op: ${op}`);
      reply = { id, ok: true, result: fn(params) };
    } catch (e) {
      const err = e as OpError;
      reply = { id, ok: false, error: { code: err.code ?? "internal", message: err.message ?? String(e) } };
    }
    const data = JSON.stringify(reply);
    setTimeout(() => this.readyState === 1 && this.onmessage?.({ data } as MessageEvent), 0);
  }
  close(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    open.delete(this);
    setTimeout(() => this.onclose?.(new CloseEvent("close")), 0);
  }
  addEventListener(): void {}
  removeEventListener(): void {}
}
