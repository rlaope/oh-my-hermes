# Channel watch collector (Slack / Discord, read-only)

`scripts/channel_watch.py` is executable **companion data**, not an OMH
command. Catalog, install, update, routing and doctor only materialize/read its
bytes; OMH core never imports or runs it. A Hermes cron job runs it as the
job's pre-run script, before the judging step. It is the one scoped network
integration described in `AGENTS.md` under "Channel watch collector".

It is stdlib only (Python >= 3.10), so it runs on Hermes' own interpreter, and
read-only: it sends only GET requests and never posts, edits, reacts or joins.

## Install (one watch)

Hermes runs a job script only from inside `<profile>/scripts/` (a symlink that
points outside is refused) and passes no arguments, so each watch gets its own
copy of the file, named after the watch. For a watch called `<watch>` on
profile `<profile>` (for example `~/.hermes/profiles/kami`):

```sh
install -d -m 700 "<profile>/scripts" "<profile>/channel_watch"
install -m 600 "<skill_dir>/toolkit/scripts/channel_watch.py" "<profile>/scripts/channel_watch_<watch>.py"
install -m 600 my-watch.json "<profile>/channel_watch/<watch>.json"
```

`<skill_dir>/toolkit/` is this directory as the skill installed it; in a
checkout it is `src/skills/channel_watch_toolkit/`. Then create the cron job
with `script: "channel_watch_<watch>.py"` (the file name only), e.g. every 5
minutes, delivering to the bot's Bot Chat. Removing a watch: delete the job,
`scripts/channel_watch_<watch>.py`, `channel_watch/<watch>.json` and
`channel_watch/<watch>.state/`.

Try it by hand without cron: `HERMES_HOME=<profile> python3 <profile>/scripts/channel_watch_<watch>.py`,
or `python3 scripts/channel_watch.py --config path/to/watch.json`.

## Config: `<profile>/channel_watch/<watch>.json`

See `examples/watch.json`.

| key | meaning |
|---|---|
| `name` | the watch name, `[a-z0-9][a-z0-9_-]*`; must equal `<watch>` in the script's file name |
| `platform` | `slack` or `discord` |
| `channels` | list of channel ids, or `{"id", "name", "guild_id"}` objects (`name` is shown in output, `guild_id` builds Discord permalinks) |
| `keywords` | optional; when set, only posts containing one of them (case-insensitive) are shown |
| `daily_wake_cap` | optional, default 24: at most this many runs a day print posts (wake the model); after that the run prints `{"wakeAgent": false}` and leaves the cursor so the posts wait for the next day |
| `slack_workspace_url` | optional, e.g. `https://acme.slack.com`, for Slack permalinks |
| `guild_id` | optional default `guild_id` for Discord channels |
| `api_base` | tests only: overrides the API base and is refused unless the host is loopback (`127.0.0.1`, `::1`, `localhost`) |
| `mode` | optional; `brief` (Slack only) makes it a briefing for one person, see below; any other value is a config error |

### Brief mode (`"mode": "brief"`)

omher installs one of these per bot that has Slack connected, as
`scripts/channel_watch_omher-brief.py` with `channel_watch/omher-brief.json`.

| key | meaning |
|---|---|
| `owner` | the Slack user id of the person the bot briefs |
| `owner_name` | how the brief names them |
| `max_per_day` | optional, default 6 briefs a day; at most that plus 2 runs a day wake the model |
| `channels` | optional; left out, the bot's own channels (`users.conversations`) are used |

It keeps only channels the owner is a member of (`conversations.members`,
once a day, at most 40), the last 48 h of their posts (`posts.json`), the
owner's post times for 14 days (`owner_hours.json`), author names
(`users.info`, `users.json`) and a 3-day wake ledger (`ledger.json`). A thread
is re-read (`conversations.replies`, at most 20 a run) only when its latest
reply moved. The first run reads 6 h back. It wakes the model for one reason:
`mention` (someone else called the owner 20+ min ago, within 6 h, and they
have not answered in that thread), `followup` (a thread one of this job's
briefs from the last 3 days linked got 2+ posts by people since, 3 h apart per
thread), `back` (the owner posted within 30 min after 4+ h quiet, and 5+ posts
came in meanwhile) or `discovery` (6 h since the last discovery/back, an
active hour of the owner's, 5+ new posts, 2 h after the last brief); events
are 30 min apart. The briefs already sent are this job's own Hermes run
records (`cron/output/<job id>/*.md`, newest 40, each non-`[SILENT]` `##
Response`). Output: a header line, `OWNER`, `REASON`, `TRIGGER - ...` and
`RECENT_BRIEF - ...` lines, then `## #<channel>` groups of `- ` post lines
(replies `- ↳ `) since the last brief, at most 12 h and 150 lines; otherwise
`{"wakeAgent": false}`.

Cursors: one file per channel, `<profile>/channel_watch/<watch>.state/cursor-<channel>.json`,
plus `wakes.json` for the daily cap. The first run records "now" and reports
nothing, so a new watch does not dump channel history.

## Token

`SLACK_BOT_TOKEN` (Slack, needs `channels:history`/`groups:history` and the bot
in the channel) or `DISCORD_BOT_TOKEN` (Discord, needs View Channel + Read
Message History, and the Message Content intent for text). Hermes strips these
from a cron script's environment, so the script reads that one key name from
`$HERMES_HOME/.env` when it is not in the environment. It reads no other key,
and never prints, logs or stores the token.

## Output and exit codes

- Posts to judge: a header line, then one line per post, oldest first:
  `- <ISO-8601 UTC> <channel> @<author>: <text, one line, <=500 chars> <permalink>`.
  More than 50: the newest 50, then `... and N more`. The cursor moves to the
  newest post read.
- Skipped: the bot's own posts, join/leave and other system messages, and any
  post starting with this watch's alert text (`Watch · <name>`,
  `Cronjob Response: <name>`, `[Cronjob "<name>" output`), so an alert that
  lands in a watched channel is never re-reported.
- Nothing to judge (no new posts, all filtered, wake cap reached, or a
  transient failure): last stdout line exactly `{"wakeAgent": false}`.

| exit | meaning | stdout |
|---|---|---|
| 0 | ran; posts printed or `{"wakeAgent": false}`. A 429, 5xx or network error is a stderr note and the cursor stays | |
| 2 | no token; no request was sent | `channel-watch: error reason=no_token key=<KEY> watch=<name>` |
| 3 | config missing or invalid | `channel-watch: error reason=config detail=...` |
| 4 | a channel is not readable (`not_in_channel`, `channel_not_found`, Discord 403/404, other API refusal) | `channel-watch: unreadable reason=<reason> platform=<p> channel=<id> watch=<name> exit=4` |
| 5 | token not accepted (`invalid_auth`, `token_revoked`, HTTP 401) | same line, `exit=5` |
| 6 | token lacks a scope (`missing_scope`) | same line, `exit=6` |

Every failing channel gets one such line, and its cursor stays. When at least
one channel was read, the run exits 0 and the readable channels' posts print
as usual next to those lines; only when every channel fails (or the token is
rejected, `channel=*`) does the highest code win. A token with a space or
control character is rejected before any request: `reason=bad_token`, exit 5,
the token never echoed.

Post text Hermes' cron scanner would block (the prompt-injection directive
patterns it checks, mirrored in `INSTRUCTION_LIKE` in the script) is printed as
`[text withheld: looks like instructions]`, so one such post cannot block the
run that judges the others.
