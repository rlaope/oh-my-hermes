import { describe, expect, it } from "vitest";
import { classifyLink, clock, findUrls, linksIn, parseT } from "./linkKinds";

// [url, service, kind, label, meta subset?]
type Case = [string, string, string, string, Record<string, string>?];

const CASES: Case[] = [
  // ---- GitHub
  ["https://github.com/rlaope/oh-my-hermes/pull/2657", "github", "pr", "rlaope/oh-my-hermes#2657", { owner: "rlaope", repo: "oh-my-hermes", number: "2657" }],
  ["https://github.com/rlaope/oh-my-hermes/pull/2657/files?diff=split", "github", "pr", "rlaope/oh-my-hermes#2657"],
  ["https://github.com/rlaope/oh-my-hermes/pull/2657#issuecomment-123", "github", "pr", "rlaope/oh-my-hermes#2657"],
  ["https://www.github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["http://github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://GitHub.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://m.github.com/rlaope/oh-my-hermes/pull/12", "github", "pr", "rlaope/oh-my-hermes#12"],
  ["https://github.com/rlaope/oh-my-hermes/issues/2604", "github", "issue", "#2604", { number: "2604" }],
  ["https://github.com/rlaope/oh-my-hermes/issues", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes/commit/c74e9646a1b2c3d4e5f60718293a4b5c6d7e8f90", "github", "commit", "rlaope/oh-my-hermes@c74e964", { sha: "c74e9646a1b2c3d4e5f60718293a4b5c6d7e8f90" }],
  ["https://github.com/rlaope/oh-my-hermes/commit/c74e964", "github", "commit", "rlaope/oh-my-hermes@c74e964"],
  ["https://github.com/rlaope/oh-my-hermes", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes/", "github", "repo", "rlaope/oh-my-hermes"],
  ["https://github.com/rlaope/oh-my-hermes.git", "github", "repo", "rlaope/oh-my-hermes.git"],
  ["https://github.com/rlaope", "github", "user", "@rlaope"],
  ["https://github.com/rlaope/oh-my-hermes/releases/tag/omher-v0.2.2", "github", "release", "rlaope/oh-my-hermes omher-v0.2.2", { tag: "omher-v0.2.2" }],
  ["https://github.com/rlaope/oh-my-hermes/releases", "github", "releases", "rlaope/oh-my-hermes releases"],
  ["https://github.com/rlaope/oh-my-hermes/actions/runs/42615558060/job/129150631784", "github", "run", "CI run", { run: "42615558060" }],
  ["https://github.com/rlaope/oh-my-hermes/actions/runs/42615558060/job/129150631784/attempts/3/logs", "github", "run", "CI run"],
  ["https://github.com/rlaope/oh-my-hermes/actions", "github", "actions", "rlaope/oh-my-hermes actions"],
  ["https://github.com/rlaope/oh-my-hermes/blob/main/apps/omher/src/lib/runs.ts#L41", "github", "file", "runs.ts:41", { path: "apps/omher/src/lib/runs.ts", line: "41", ref: "main" }],
  ["https://github.com/rlaope/oh-my-hermes/blob/main/apps/omher/src/lib/runs.ts#L41-L58", "github", "file", "runs.ts:41-58"],
  ["https://github.com/rlaope/oh-my-hermes/blob/c74e964/README.md", "github", "file", "README.md"],
  ["https://github.com/rlaope/oh-my-hermes/tree/main/apps/omher", "github", "folder", "omher/"],
  ["https://gist.github.com/rlaope/0f1e2d3c4b5a6978", "github", "gist", "gist · rlaope", { id: "0f1e2d3c4b5a6978" }],
  ["https://github.com/rlaope/oh-my-hermes/compare/main...feat/omher-link-chips", "github", "compare", "compare main...feat/omher-link-chips"],
  ["https://github.com/rlaope/oh-my-hermes/discussions/88", "github", "discussion", "rlaope/oh-my-hermes discussion #88"],
  ["https://github.com/settings/tokens", "github", "page", "GitHub"],
  ["https://github.com/", "github", "page", "GitHub"],
  // ---- Slack
  ["https://example.slack.com/archives/C0000000001/p1700000000000001", "slack", "message", "Slack message", { channel: "C0000000001", ts: "1700000000.000001", workspace: "example" }],
  ["https://example.slack.com/archives/C0000000001/p1700000000000001?thread_ts=1700000000.000001&cid=C0000000001", "slack", "thread", "Slack · thread", { thread: "1700000000.000001" }],
  ["https://example.slack.com/archives/C0000000001", "slack", "channel", "Slack channel", { channel: "C0000000001" }],
  ["https://app.slack.com/client/T0000000001/C0000000001", "slack", "channel", "Slack channel", { channel: "C0000000001" }],
  ["https://app.slack.com/client/T0000000001/C0000000001/thread/C0000000001-1700000000.000001", "slack", "thread", "Slack · thread", { thread: "1700000000.000001" }],
  ["https://slack.com/app_redirect?channel=C0000000001&team=T0000000001", "slack", "channel", "Slack channel", { channel: "C0000000001" }],
  ["https://example.slack.com/", "slack", "workspace", "Slack · example"],
  // ---- Discord
  ["https://discord.com/channels/1100000000000000001/1100000000000000010", "discord", "channel", "Discord channel", { guild: "1100000000000000001", channel: "1100000000000000010" }],
  ["https://discord.com/channels/1100000000000000001/1100000000000000010/1100000000000000030", "discord", "message", "Discord message", { message: "1100000000000000030" }],
  ["https://canary.discord.com/channels/1/2/3", "discord", "message", "Discord message"],
  ["https://ptb.discord.com/channels/1/2", "discord", "channel", "Discord channel"],
  ["https://discordapp.com/channels/1/2", "discord", "channel", "Discord channel"],
  ["https://discord.com/channels/1100000000000000001", "discord", "server", "Discord server"],
  ["https://discord.com/channels/@me/123", "discord", "channel", "Discord channel"],
  ["https://discord.gg/omh", "discord", "invite", "Discord invite · omh", { invite: "omh" }],
  ["https://discord.com/invite/omh", "discord", "invite", "Discord invite · omh"],
  // ---- Google
  ["https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit", "googledocs", "document", "Google Docs", { id: "1AbCdEfGhIjKlMnOpQrStUvWxYz" }],
  ["https://docs.google.com/document/u/1/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit?usp=sharing", "googledocs", "document", "Google Docs", { id: "1AbCdEfGhIjKlMnOpQrStUvWxYz" }],
  ["https://docs.google.com/spreadsheets/d/1ZyX/edit#gid=0", "googlesheets", "spreadsheets", "Google Sheets", { id: "1ZyX" }],
  ["https://docs.google.com/spreadsheets/u/1/d/1ZyX/edit#gid=0", "googlesheets", "spreadsheets", "Google Sheets", { id: "1ZyX" }],
  ["https://docs.google.com/presentation/d/1SlIdEs/edit", "googleslides", "presentation", "Google Slides"],
  ["https://docs.google.com/forms/d/e/1FAIpQL/viewform", "googleforms", "forms", "Google Forms", { id: "1FAIpQL" }],
  ["https://forms.gle/abc123", "googleforms", "forms", "Google Forms"],
  ["https://drive.google.com/file/d/1FiLeId/view?usp=drive_link", "googledrive", "file", "Drive file", { id: "1FiLeId" }],
  ["https://drive.google.com/drive/folders/1FoLdErIdXyZ", "googledrive", "folder", "Drive folder", { id: "1FoLdErIdXyZ" }],
  ["https://drive.google.com/drive/u/1/folders/1FoLdEr", "googledrive", "folder", "Drive folder"],
  ["https://drive.google.com/open?id=1FiLeId", "googledrive", "file", "Drive file"],
  ["https://calendar.google.com/calendar/event?eid=ZXZlbnQxMjM", "googlecalendar", "event", "Calendar event", { eid: "ZXZlbnQxMjM" }],
  ["https://calendar.google.com/calendar/u/0/r/eventedit/abc", "googlecalendar", "event", "Calendar event"],
  ["https://calendar.google.com/calendar/u/0/r", "googlecalendar", "page", "Google Calendar"],
  ["https://meet.google.com/abc-defg-hij", "googlemeet", "meeting", "Meet · abc-defg-hij", { code: "abc-defg-hij" }],
  ["https://meet.google.com/abc-defg-hij?authuser=1", "googlemeet", "meeting", "Meet · abc-defg-hij"],
  ["https://mail.google.com/mail/u/0/#inbox/FMfcgzQXJWDsKmzvNtqgPpLsZ", "gmail", "thread", "Gmail thread"],
  ["https://mail.google.com/mail/u/0/#inbox", "gmail", "page", "Gmail"],
  ["https://www.google.com/maps/place/Gangnam+Station/@37.49,127.02,17z", "googlemaps", "place", "Maps · Gangnam Station"],
  ["https://maps.app.goo.gl/AbCdEf", "googlemaps", "place", "Google Maps"],
  ["https://www.google.com/search?q=hermes+agent", "google", "search", "Google · hermes agent", { q: "hermes agent" }],
  ["https://www.google.co.kr/search?q=omher", "google", "search", "Google · omher"],
  // ---- X / Twitter
  ["https://x.com/NousResearch/status/1854012345678901234", "x", "post", "@NousResearch · post", { user: "NousResearch", post: "1854012345678901234" }],
  ["https://twitter.com/NousResearch/status/1854012345678901234?s=20", "x", "post", "@NousResearch · post"],
  ["https://mobile.twitter.com/NousResearch/status/1854012345678901234", "x", "post", "@NousResearch · post"],
  ["https://x.com/i/web/status/1854012345678901234", "x", "post", "X post"],
  ["https://x.com/NousResearch", "x", "profile", "@NousResearch"],
  ["https://twitter.com/home", "x", "page", "X"],
  // ---- LinkedIn
  ["https://www.linkedin.com/in/demo", "linkedin", "profile", "in/demo", { profile: "demo" }],
  ["https://kr.linkedin.com/in/demo/", "linkedin", "profile", "in/demo"],
  ["https://www.linkedin.com/company/example/", "linkedin", "company", "LinkedIn · example"],
  ["https://www.linkedin.com/jobs/view/4012345678/", "linkedin", "job", "LinkedIn job", { job: "4012345678" }],
  ["https://www.linkedin.com/posts/demo_omher-activity-7260000000000000000-AbCd", "linkedin", "post", "LinkedIn post"],
  ["https://www.linkedin.com/feed/update/urn:li:activity:7260000000000000000/", "linkedin", "post", "LinkedIn post"],
  // ---- YouTube
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "video", "YouTube · video", { video: "dQw4w9WgXcQ" }],
  ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=83s", "youtube", "video", "YouTube · video · 1:23", { t: "83" }],
  ["https://m.youtube.com/watch?v=dQw4w9WgXcQ&feature=share", "youtube", "video", "YouTube · video"],
  ["https://youtu.be/dQw4w9WgXcQ?t=83", "youtube", "video", "YouTube · video · 1:23"],
  ["https://youtu.be/dQw4w9WgXcQ?si=AbCd&t=1h2m3s", "youtube", "video", "YouTube · video · 1:02:03"],
  ["https://www.youtube.com/shorts/AbCdEfGhIjK", "youtube", "short", "YouTube · short"],
  ["https://www.youtube.com/playlist?list=PL1234567890", "youtube", "playlist", "YouTube · playlist", { list: "PL1234567890" }],
  ["https://www.youtube.com/@NousResearch", "youtube", "channel", "@NousResearch"],
  ["https://www.youtube.com/channel/UC1234567890", "youtube", "channel", "YouTube channel"],
  ["https://www.youtube.com/embed/dQw4w9WgXcQ?start=30", "youtube", "video", "YouTube · video · 0:30"],
  ["https://music.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", "video", "YouTube · video"],
  // ---- Notion, Linear, Figma, npm
  ["https://www.notion.so/Release-Notes-0f1e2d3c4b5a69788796a5b4c3d2e1f0", "notion", "page", "Notion · Release Notes"],
  ["https://example.notion.site/Hiring-0f1e2d3c4b5a69788796a5b4c3d2e1f0", "notion", "page", "Notion · Hiring"],
  ["https://linear.app/example/issue/OG-123/retry-budget", "linear", "issue", "OG-123", { issue: "OG-123", team: "example" }],
  ["https://www.figma.com/design/AbC123xYz/omher-chat?node-id=1-2", "figma", "design", "Figma · omher chat", { key: "AbC123xYz" }],
  ["https://www.npmjs.com/package/@tauri-apps/api", "npm", "package", "npm · @tauri-apps/api", { package: "@tauri-apps/api" }],
  ["https://www.npmjs.com/package/vite", "npm", "package", "npm · vite"],
  ["https://calendar.app.google/AbCdEf123", "googlecalendar", "booking", "Calendar booking page", { code: "AbCdEf123" }],
  ["https://calendar.google.com/calendar/appointments/schedules/AcZssZ1abc", "googlecalendar", "booking", "Calendar booking page", { schedule: "AcZssZ1abc" }],
  ["https://www.figma.com/make/AbC123xYz/retry-ui", "figma", "make", "Figma · retry ui", { key: "AbC123xYz" }],
  ["https://www.figma.com/site/AbC123xYz/landing", "figma", "site", "Figma · landing"],
  ["https://www.figma.com/design/AbC123xYz/C%2B%2B-Guide", "figma", "design", "Figma · C++ Guide"],
  ["https://www.notion.so/C%2B%2B-Notes-0f1e2d3c4b5a69788796a5b4c3d2e1f0", "notion", "page", "Notion · C++ Notes"],
  ["https://www.google.com/maps/place/C%2B%2B+Cafe/@37.49,127.02,17z", "googlemaps", "place", "Maps · C++ Cafe"],
  ["https://docs.google.com/constructor", "googledrive", "page", "Google Docs"],
  ["https://docs.google.com/__proto__/d/1", "googledrive", "page", "Google Docs"],
  // ---- Jira (Cloud only: <site>.atlassian.net)
  ["https://acme.atlassian.net/browse/ACME-123", "jira", "issue", "ACME-123", { site: "acme", issue: "ACME-123", project: "ACME" }],
  ["https://acme.atlassian.net/browse/acme-7?focusedCommentId=10001", "jira", "issue", "ACME-7"],
  ["https://acme.atlassian.net:8443/browse/ACME-123", "jira", "issue", "ACME-123"],
  ["https://acme.atlassian.net/browse/OPS", "jira", "project", "Jira project · OPS", { project: "OPS" }],
  ["https://acme.atlassian.net/jira/software/projects/ACME/boards/42", "jira", "board", "Jira board · ACME", { project: "ACME", board: "42" }],
  ["https://acme.atlassian.net/jira/software/c/projects/ACME/boards/42/backlog?selectedIssue=ACME-9", "jira", "issue", "ACME-9", { board: "42" }],
  ["https://acme.atlassian.net/jira/software/projects/ACME/issues/ACME-12", "jira", "issue", "ACME-12"],
  ["https://acme.atlassian.net/jira/servicedesk/projects/HELP/queues/custom/1/HELP-3", "jira", "issue", "HELP-3", { project: "HELP" }],
  ["https://acme.atlassian.net/jira/software/projects/ACME/summary", "jira", "project", "Jira project · ACME"],
  ["https://acme.atlassian.net/projects/ACME/issues/ACME-4", "jira", "issue", "ACME-4"],
  ["https://acme.atlassian.net/jira/your-work", "jira", "page", "Jira"],
  ["https://acme.atlassian.net/browse/12-ACME", "jira", "page", "Jira"],
  ["https://acme.atlassian.net/jira/software/projects/ACME/boards/x?selectedIssue=nope", "jira", "project", "Jira project · ACME"],
  ["https://acme.atlassian.net/", "atlassian", "page", "Atlassian", { site: "acme" }],
  ["https://acme.atlassian.net/compass/component/abc", "atlassian", "page", "Atlassian"],
  ["https://acme.atlassian.net/WIKI/spaces/ENG", "atlassian", "page", "Atlassian"],
  ["https://acme.atlassian.net/jira", "jira", "page", "Jira"],
  // ---- Confluence (<site>.atlassian.net/wiki)
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/123456/Release+Checklist", "confluence", "page", "Confluence · Release Checklist", { site: "acme", space: "ENG", page: "123456" }],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/123456/Q4%20Plan%20%E2%80%94%20Draft", "confluence", "page", "Confluence · Q4 Plan — Draft"],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/123/C%2B%2B+Basics", "confluence", "page", "Confluence · C++ Basics"],
  ["https://acme.atlassian.net/wiki/display/ENG/Q%26A+%2B+Notes", "confluence", "page", "Confluence · Q&A + Notes"],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/123/Rate%2541", "confluence", "page", "Confluence · Rate%41"],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/edit-v2/123456", "confluence", "page", "Confluence page", { page: "123456" }],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/123456", "confluence", "page", "Confluence page"],
  ["https://acme.atlassian.net/wiki/spaces/ENG/overview", "confluence", "space", "Confluence space · ENG", { space: "ENG" }],
  ["https://acme.atlassian.net/wiki/spaces/ENG", "confluence", "space", "Confluence space · ENG"],
  ["https://acme.atlassian.net/wiki/display/ENG/Onboarding+Guide", "confluence", "page", "Confluence · Onboarding Guide", { space: "ENG" }],
  ["https://acme.atlassian.net/wiki/x/AbCd", "confluence", "page", "Confluence page", { short: "AbCd" }],
  ["https://acme.atlassian.net/wiki/spaces/ENG/blog/2026/11/23/123/Notes", "confluence", "page", "Confluence"],
  ["https://acme.atlassian.net/wiki/spaces/ENG/pages/", "confluence", "page", "Confluence"],
  ["https://acme.atlassian.net/wiki/home", "confluence", "page", "Confluence"],
  // ---- Sentry
  ["https://acme.sentry.io/issues/4512345678/", "sentry", "issue", "Sentry issue · 4512345678", { org: "acme", issue: "4512345678" }],
  ["https://sentry.io/organizations/acme/issues/4512345678/events/abc123/", "sentry", "issue", "Sentry issue · 4512345678", { org: "acme" }],
  ["https://us.sentry.io/organizations/acme/issues/77/", "sentry", "issue", "Sentry issue · 77", { org: "acme" }],
  ["https://acme.sentry.io/projects/web-app/", "sentry", "project", "Sentry project · web-app", { project: "web-app" }],
  ["https://sentry.io/organizations/acme/projects/web-app/?project=12", "sentry", "project", "Sentry project · web-app"],
  ["https://acme.sentry.io/releases/web%401.4.2/", "sentry", "release", "Sentry release · web@1.4.2", { release: "web@1.4.2" }],
  ["https://acme.sentry.io/issues/?query=is%3Aunresolved", "sentry", "page", "Sentry"],
  ["https://acme.sentry.io/issues/PROJ-1A/", "sentry", "page", "Sentry"],
  ["https://docs.sentry.io/product/issues/", "sentry", "page", "Sentry"],
  // ---- Asana
  ["https://app.asana.com/0/1205000000000001/1205000000000002", "asana", "task", "Asana task", { project: "1205000000000001", task: "1205000000000002" }],
  ["https://app.asana.com/0/1205000000000001/1205000000000002/f", "asana", "task", "Asana task"],
  ["https://app.asana.com/0/0/1205000000000002", "asana", "task", "Asana task", { task: "1205000000000002" }],
  ["https://app.asana.com/0/1205000000000001/list", "asana", "project", "Asana project", { project: "1205000000000001" }],
  ["https://app.asana.com/0/1205000000000001", "asana", "project", "Asana project"],
  ["https://app.asana.com/1/1100000000000001/project/1205000000000001/task/1205000000000002", "asana", "task", "Asana task", { workspace: "1100000000000001", project: "1205000000000001", task: "1205000000000002" }],
  ["https://app.asana.com/1/1100000000000001/project/1205000000000001/board", "asana", "project", "Asana project"],
  ["https://app.asana.com/1/1100000000000001/task/1205000000000002", "asana", "task", "Asana task"],
  ["https://app.asana.com/0/home/1100000000000001", "asana", "page", "Asana"],
  ["https://app.asana.com/1/1100000000000001/inbox", "asana", "page", "Asana"],
  // ---- Todoist
  ["https://app.todoist.com/app/task/write-release-notes-6Xv2Q9pFg3J8mRcW", "todoist", "task", "Todoist · write release notes", { task: "6Xv2Q9pFg3J8mRcW" }],
  ["https://app.todoist.com/app/task/6Xv2Q9pFg3J8mRcW", "todoist", "task", "Todoist task", { task: "6Xv2Q9pFg3J8mRcW" }],
  ["https://app.todoist.com/app/project/launch-plan-6Xv2Q9pFg3J8mRcX", "todoist", "project", "Todoist · launch plan", { project: "6Xv2Q9pFg3J8mRcX" }],
  ["https://todoist.com/showTask?id=8123456789", "todoist", "task", "Todoist task", { task: "8123456789" }],
  ["https://todoist.com/showProject?id=2203456789", "todoist", "project", "Todoist project"],
  ["https://app.todoist.com/app/today", "todoist", "page", "Todoist"],
  ["https://todoist.com/showTask", "todoist", "page", "Todoist"],
  // ---- ClickUp
  ["https://app.clickup.com/t/86b2x3y4z", "clickup", "task", "ClickUp task", { task: "86b2x3y4z" }],
  ["https://app.clickup.com/t/9012345678/DEV-123", "clickup", "task", "DEV-123", { workspace: "9012345678", task: "DEV-123" }],
  ["https://app.clickup.com/9012345678/v/li/901234567890", "clickup", "list", "ClickUp list", { workspace: "9012345678", list: "901234567890" }],
  ["https://app.clickup.com/9012345678/v/s/90123456", "clickup", "space", "ClickUp space", { space: "90123456" }],
  ["https://app.clickup.com/9012345678/v/f/90123457", "clickup", "folder", "ClickUp folder", { folder: "90123457" }],
  ["https://app.clickup.com/9012345678/v/l/6-901234567890-1", "clickup", "page", "ClickUp"],
  ["https://app.clickup.com/9012345678/home", "clickup", "page", "ClickUp"],
  ["https://app.clickup.com/123/v/constructor/1", "clickup", "page", "ClickUp"],
  ["https://app.clickup.com/123/v/__proto__/1", "clickup", "page", "ClickUp"],
  ["https://app.clickup.com/123/v/toString/1", "clickup", "page", "ClickUp"],
  // ---- GitLab (gitlab.com only)
  ["https://gitlab.com/acme/widgets/-/merge_requests/42", "gitlab", "mr", "acme/widgets!42", { project: "acme/widgets", number: "42" }],
  ["https://gitlab.com/acme/widgets/-/merge_requests/42/diffs?commit_id=0a1b2c3", "gitlab", "mr", "acme/widgets!42"],
  ["https://gitlab.com/acme/platform/billing/api/-/merge_requests/7", "gitlab", "mr", "acme/…/api!7", { project: "acme/platform/billing/api", number: "7" }],
  ["https://gitlab.com/acme/widgets/-/issues/15", "gitlab", "issue", "acme/widgets#15", { number: "15" }],
  ["https://gitlab.com/acme/platform/web/-/issues/3", "gitlab", "issue", "acme/…/web#3", { project: "acme/platform/web" }],
  ["https://gitlab.com/acme/widgets/-/pipelines/1234567890", "gitlab", "pipeline", "GitLab pipeline · 1234567890", { pipeline: "1234567890" }],
  ["https://gitlab.com/acme/widgets/-/commit/0a1b2c3d4e5f60718293a4b5c6d7e8f901234567", "gitlab", "commit", "acme/widgets@0a1b2c3", { sha: "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567" }],
  ["https://www.gitlab.com/acme/widgets/-/issues/15", "gitlab", "issue", "acme/widgets#15"],
  ["https://gitlab.com/acme/widgets/-/merge_requests", "gitlab", "repo", "acme/widgets"],
  ["https://gitlab.com/acme/widgets/-/commit/not-a-sha", "gitlab", "repo", "acme/widgets"],
  ["https://gitlab.com/acme/widgets/-/wikis/home", "gitlab", "repo", "acme/widgets"],
  ["https://gitlab.com/acme/widgets", "gitlab", "page", "acme/widgets", { path: "acme/widgets" }],
  ["https://gitlab.com/explore/projects", "gitlab", "page", "GitLab"],
  ["https://gitlab.com/groups/acme/-/epics/5", "gitlab", "page", "GitLab"],
  ["https://gitlab.com/acme/-/issues/5", "gitlab", "page", "GitLab"],
  ["https://docs.gitlab.com/ee/user/project/merge_requests/", "gitlab", "page", "GitLab"],
  // ---- Obsidian (named, never opened)
  ["obsidian://open?vault=Work%20Notes&file=Projects%2FLaunch%20Plan.md", "obsidian", "note", "Obsidian · Launch Plan", { vault: "Work Notes", file: "Projects/Launch Plan.md" }],
  ["obsidian://open?vault=Work&file=Daily%2F2026-11-23", "obsidian", "note", "Obsidian · 2026-11-23"],
  ["obsidian://open?path=%2FUsers%2Fdemo%2Fvault%2FIdeas.md", "obsidian", "note", "Obsidian · Ideas", { file: "/Users/demo/vault/Ideas.md" }],
  ["obsidian://open?vault=Work", "obsidian", "vault", "Obsidian vault · Work", { vault: "Work" }],
  ["obsidian://search?vault=Work&query=retry%20budget", "obsidian", "search", "Obsidian search · retry budget", { query: "retry budget" }],
  ["obsidian://search?vault=Work", "obsidian", "search", "Obsidian search"],
  ["obsidian://new?vault=Work&name=Standup", "obsidian", "new", "Obsidian new note · Standup"],
  ["obsidian://new?vault=Work&file=Inbox%2FIdea.md", "obsidian", "new", "Obsidian new note · Idea"],
  ["obsidian://vault/Work/Projects/Launch%20Plan", "obsidian", "note", "Obsidian · Launch Plan", { vault: "Work", file: "Projects/Launch Plan" }],
  ["obsidian://vault/Work", "obsidian", "vault", "Obsidian vault · Work"],
  ["OBSIDIAN://Open?vault=Work&file=Ideas", "obsidian", "note", "Obsidian · Ideas"],
  ["obsidian://open", "obsidian", "page", "Obsidian"],
  ["Obsidian://open?vault=Work&file=Ideas", "obsidian", "note", "Obsidian · Ideas"],
  ["obsidian://hook-get-address", "obsidian", "page", "Obsidian"],
  ["obsidian://someone@open?vault=Work&file=Ideas", "obsidian", "page", "Obsidian"],
  // ---- lookalikes and anything else: a plain web link named by its real host
  ["https://github.com.evil.io/rlaope/oh-my-hermes/pull/1", "web", "web", "github.com.evil.io/rlaope/oh-my-hermes/pull/1"],
  ["https://evilgithub.com/rlaope/x/pull/1", "web", "web", "evilgithub.com/rlaope/x/pull/1"],
  ["https://slack.com.attacker.net/archives/C1/p1700000000000001", "web", "web", "slack.com.attacker.net/archives/C1/p1700000000000…"],
  ["https://notslack.com/archives/C1", "web", "web", "notslack.com/archives/C1"],
  ["https://discord.com.evil.io/channels/1/2", "web", "web", "discord.com.evil.io/channels/1/2"],
  ["https://docs.google.com.evil.io/document/d/1", "web", "web", "docs.google.com.evil.io/document/d/1"],
  ["https://youtube.com.example.org/watch?v=dQw4w9WgXcQ", "web", "web", "youtube.com.example.org/watch"],
  ["https://x.com.evil.io/NousResearch", "web", "web", "x.com.evil.io/NousResearch"],
  ["https://github.com@evil.io/rlaope/x/pull/1", "web", "web", "evil.io/rlaope/x/pull/1"],
  ["https://acme.atlassian.net.evil.io/browse/ACME-1", "web", "web", "acme.atlassian.net.evil.io/browse/ACME-1"],
  ["https://atlassian.net/browse/ACME-1", "web", "web", "atlassian.net/browse/ACME-1"],
  ["https://evilatlassian.net/browse/ACME-1", "web", "web", "evilatlassian.net/browse/ACME-1"],
  ["https://acme.atlassian.net:8443@evil.io/browse/ACME-1", "web", "web", "evil.io/browse/ACME-1"],
  ["https://jira.example.com/browse/ACME-1", "web", "web", "jira.example.com/browse/ACME-1"],
  ["https://sentry.io.evil.io/issues/1/", "web", "web", "sentry.io.evil.io/issues/1"],
  ["https://notsentry.io/issues/1", "web", "web", "notsentry.io/issues/1"],
  ["https://app.asana.com.evil.io/0/1/2", "web", "web", "app.asana.com.evil.io/0/1/2"],
  ["https://todoist.com.evil.io/showTask?id=1", "web", "web", "todoist.com.evil.io/showTask"],
  ["https://clickup.com.evil.io/t/86b2x3y4z", "web", "web", "clickup.com.evil.io/t/86b2x3y4z"],
  ["https://gitlab.com.evil.io/acme/widgets/-/issues/1", "web", "web", "gitlab.com.evil.io/acme/widgets/-/issues/1"],
  ["https://evilgitlab.com/acme/widgets", "web", "web", "evilgitlab.com/acme/widgets"],
  ["https://gitlab.example.com/acme/widgets/-/merge_requests/1", "web", "web", "gitlab.example.com/acme/widgets/-/merge_reque…"],
  ["https://gitlab.com@evil.io/acme/widgets/-/issues/1", "web", "web", "evil.io/acme/widgets/-/issues/1"],
  ["https://calendar.app.google.evil.io/AbCdEf123", "web", "web", "calendar.app.google.evil.io/AbCdEf123"],
  ["https://www.example.com/", "web", "web", "example.com"],
  ["https://omher.app/docs/install", "web", "web", "omher.app/docs/install"],
];

describe("classifyLink", () => {
  it("has at least 60 cases", () => expect(CASES.length).toBeGreaterThanOrEqual(60));
  it.each(CASES)("%s", (url, service, kind, label, meta) => {
    const got = classifyLink(url)!;
    expect(got).not.toBeNull();
    expect([got.service, got.kind, got.label]).toEqual([service, kind, label]);
    if (meta) expect(got.meta).toMatchObject(meta);
  });
  it("is null for anything that is not http(s) or obsidian://", () => {
    for (const u of ["javascript:alert(1)", "mailto:a@b.c", "file:///etc/passwd", "slack://channel?id=C1", "notion://www.notion.so/x", "not a url", ""]) {
      expect(classifyLink(u)).toBeNull();
    }
  });
});

describe("labels taken from the URL", () => {
  const BIDI_OR_CONTROL = /[\p{Cc}\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/u;
  it("carry no control or bidi characters", () => {
    const urls = [
      "https://acme.atlassian.net/wiki/spaces/ENG/pages/1/Invoice%E2%80%AEfdp.exe",
      "https://acme.atlassian.net/wiki/spaces/EN%E2%81%A6G",
      "https://app.todoist.com/app/task/pay%00%0Arent-6Xv2Q9pFg3J8mRcW",
      "https://acme.sentry.io/releases/web%E2%80%8F1.0/",
      "obsidian://open?vault=Work&file=a%E2%80%AEb%0D%0Ac.md",
      "obsidian://search?query=%E2%81%A7x%1B%5B31m",
      "https://www.notion.so/Plan%E2%80%AE-0f1e2d3c4b5a69788796a5b4c3d2e1f0",
      "https://www.google.com/search?q=a%E2%80%AEb",
    ];
    for (const u of urls) {
      const got = classifyLink(u)!;
      expect(got.service, u).not.toBe("web");
      expect(BIDI_OR_CONTROL.test(got.label), `${u} -> ${JSON.stringify(got.label)}`).toBe(false);
    }
    expect(classifyLink("https://acme.atlassian.net/wiki/spaces/ENG/pages/1/Invoice%E2%80%AEfdp.exe")!.label).toBe("Confluence · Invoice fdp.exe");
    expect(classifyLink("obsidian://open?vault=Work&file=a%E2%80%AEb%0D%0Ac.md")!.label).toBe("Obsidian · a b c");
  });
  it("are bounded: a long title ends in an ellipsis", () => {
    const long = "Quarterly+Planning+".repeat(12) + "End";
    const urls = [
      `https://acme.atlassian.net/wiki/spaces/ENG/pages/123456/${long}`,
      `https://app.todoist.com/app/task/${"very-long-task-name-".repeat(10)}6Xv2Q9pFg3J8mRcW`,
      `obsidian://open?vault=Work&file=${encodeURIComponent("Notes/" + "a long note name ".repeat(10) + ".md")}`,
      `obsidian://search?query=${"q".repeat(500)}`,
      `https://gitlab.com/${"group/".repeat(30)}project/-/merge_requests/1`,
      `https://www.notion.so/${"Long-Title-".repeat(20)}0f1e2d3c4b5a69788796a5b4c3d2e1f0`,
    ];
    for (const u of urls) {
      const got = classifyLink(u)!;
      expect(got.service, u).not.toBe("web");
      expect([...got.label].length, `${u} -> ${got.label}`).toBeLessThanOrEqual(80);
    }
    const page = classifyLink(urls[0])!.label;
    expect(page.startsWith("Confluence · Quarterly Planning")).toBe(true);
    expect(page.endsWith("…")).toBe(true);
    expect([...page].length).toBe("Confluence · ".length + 48);
  });
  it("survive a malformed percent escape without throwing", () => {
    expect(classifyLink("https://acme.atlassian.net/wiki/spaces/ENG/pages/1/Bad%E0%A4%A")!.label).toBe("Confluence · Bad%E0%A4%A");
    expect(classifyLink("https://app.todoist.com/app/task/fix%ZZ-bug-6Xv2Q9pFg3J8mRcW")!.label).toBe("Todoist · fix%ZZ bug");
    expect(classifyLink("obsidian://vault/Work/Bad%E0%A4%A")!.label).toBe("Obsidian · Bad%E0%A4%A");
    const odd = classifyLink("obsidian://open?vault=Work&file=Bad%E0%A4%A")!;
    expect([odd.service, odd.kind]).toEqual(["obsidian", "note"]);
    expect(odd.label.startsWith("Obsidian · Bad")).toBe(true);
  });
});

describe("times and URL finding", () => {
  it("reads t= forms and prints a clock", () => {
    expect([parseT("83"), parseT("83s"), parseT("1m23s"), parseT("1h2m3s"), parseT("x"), parseT(null)]).toEqual([83, 83, 83, 3723, null, null]);
    expect([clock(83), clock(3723), clock(5)]).toEqual(["1:23", "1:02:03", "0:05"]);
  });
  it("leaves sentence punctuation out of a bare URL and keeps balanced brackets", () => {
    expect(findUrls("see https://x.com/a/status/1. and (https://github.com/o/r).").map((u) => u.url)).toEqual([
      "https://x.com/a/status/1",
      "https://github.com/o/r",
    ]);
    expect(findUrls("https://en.wikipedia.org/wiki/Foo_(bar)").map((u) => u.url)).toEqual(["https://en.wikipedia.org/wiki/Foo_(bar)"]);
  });
  it("lists a handoff's links once, from bare and markdown links, skipping code", () => {
    const md = "PR [#12](https://github.com/o/r/pull/12) and https://github.com/o/r/pull/12 again, `https://in.code/x`\n```\nhttps://in.fence/y\n```\nhttps://meet.google.com/abc-defg-hij";
    expect(linksIn(md)).toEqual(["https://github.com/o/r/pull/12", "https://meet.google.com/abc-defg-hij"]);
  });
  it("trims trailing punctuation in linear time", () => {
    const t0 = performance.now();
    expect(findUrls("https://a" + ")".repeat(50_000))[0].url).toBe("https://a");
    expect(findUrls("obsidian://a" + "(".repeat(25_000) + ")".repeat(25_000))[0].url).toHaveLength("obsidian://a".length + 50_000);
    expect(performance.now() - t0).toBeLessThan(150);
  });
  it("reads the obsidian scheme in any case; http(s) stays lowercase, as the opener takes it", () => {
    expect(findUrls("a OBSIDIAN://open?vault=W b Obsidian://vault/W c").map((u) => u.url)).toEqual(["OBSIDIAN://open?vault=W", "Obsidian://vault/W"]);
    expect(findUrls("HTTPS://github.com/o/r")).toEqual([]);
  });
  it("takes a Sentry org only from a subdomain that names one", () => {
    for (const host of ["www", "docs", "blog", "status"]) expect(classifyLink(`https://${host}.sentry.io/issues/1/`)!.meta.org, host).toBeUndefined();
    expect(classifyLink("https://acme.sentry.io/issues/1/")!.meta.org).toBe("acme");
  });
  it("finds a bare obsidian:// link, sentence punctuation left out, and no other custom scheme", () => {
    const text = "Saved to obsidian://open?vault=Work&file=Ideas. Also slack://channel?id=C1 and notion://x.";
    expect(findUrls(text).map((u) => u.url)).toEqual(["obsidian://open?vault=Work&file=Ideas"]);
    expect(linksIn("see obsidian://vault/Work/Ideas and `obsidian://in.code`")).toEqual(["obsidian://vault/Work/Ideas"]);
  });
});
