# Monitor scripts (Gmail, Calendar, Notion, Linear, Jira, Obsidian, Sentry)

The three scripts in `scripts/` are executable **companion data**, not OMH
commands. Catalog, install, update, routing and doctor only materialize their
bytes; OMH core never imports or runs them. A Hermes cron job runs one as the
job's `--monitor-script`, before the agent on every tick. The recipes that use
them, with the job to create and the prompt for each, are in
`references/monitor-recipes.md`
(`skill_view(name='omh-automation-blueprint', file_path='references/monitor-recipes.md')`).

| script | kinds | reads with | writes |
| --- | --- | --- | --- |
| `api_watch.py` | `notion`, `linear`, `jira`, `sentry` | HTTPS to the platform's own API host, credential from one environment name | nothing |
| `google_watch.py` | `gmail`, `calendar` | Hermes' google-workspace skill CLI (`google_api.py`), with the profile's Google sign-in | nothing |
| `vault_watch.py` | `obsidian` | file names, sizes and modification times under one vault folder | nothing |

All three are stdlib only (Python >= 3.10), so they run on Hermes' own
interpreter, and they write nothing: their only output is stdout and stderr.
The google-workspace CLI that `google_watch.py` runs rewrites
`<profile>/google_token.json` when it refreshes the sign-in, as it does when
the agent uses it. Do not set `--interpreter` on a `google_watch` job: that CLI
would run on the other Python, which may lack the Google libraries.

`omh update` refreshes this folder, never the copies in `<profile>/scripts/`:
after an update, copy each installed script again.

## Install (one watch)

Hermes runs a monitor script only from inside `<profile>/scripts/` (a symlink
that points outside is refused) and passes no arguments, so each watch gets its
own copy of the script, named after the watch. For a watch called `<watch>` on
profile `<profile>` (the bot's `HERMES_HOME`):

```sh
install -d -m 700 "<profile>/scripts" "<profile>/monitors"
install -m 600 "<skill_dir>/toolkit/monitors/scripts/api_watch.py" "<profile>/scripts/api_watch_<watch>.py"
install -m 600 my-watch.json "<profile>/monitors/<watch>.json"
```

`<skill_dir>/toolkit/monitors/` is this directory as the skill installed it;
in a checkout it is `src/skills/monitor_watch_toolkit/`. The config's `name`
must equal `<watch>`. Try a config by hand without cron:
`HERMES_HOME=<profile> python3 scripts/api_watch.py --config path/to/watch.json`.

## Config: `<profile>/monitors/<watch>.json`

Every config has `name` (`[a-z0-9][a-z0-9_-]{0,63}`) and `kind`. One example
per kind is in `examples/`.

| kind | keys |
| --- | --- |
| `gmail` | `query` (a Gmail search, at most 300 characters), `limit` (1-50, default 10) |
| `calendar` | `calendar` (default `primary`), `lead_minutes` (1-240, default 15) |
| `notion` | `pages` (at most 10 page ids), `databases` (at most 5 database ids), `rows` (1-100 newest-edited rows per database, default 20); at least one id |
| `linear` | `limit` (1-100, default 50) |
| `jira` | `site` (the `<site>` of `<site>.atlassian.net`), `jql` (default `assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC`), `limit` (1-100, default 50) |
| `sentry` | `org` (slug), `region` (`us` for sentry.io, `de` for de.sentry.io), `project_ids` (numeric, optional), `query` (default `is:unresolved`), `limit` (1-100, default 10) |
| `obsidian` | `vault` (optional; else `OBSIDIAN_VAULT_PATH`, else `~/Documents/Obsidian Vault`), `folder` (relative to the vault, default the whole vault), `extensions` (default `[".md"]`), `recent` (0-50 newest names shown, default 10), `use_mtime` (default true; false hashes names and sizes only, for a vault a sync tool touches, and shows no `recent` lines) |

`api_base` (`api_watch.py` only) is for tests: it replaces the API host and is
refused unless it is `http://` on a loopback address.

## Credentials

| kind | environment name | sent to |
| --- | --- | --- |
| `notion` | `NOTION_API_KEY` (an internal integration token, the page or database shared with it) | `api.notion.com` |
| `linear` | `LINEAR_API_KEY` (a personal API key) | `api.linear.app` |
| `jira` | `JIRA_EMAIL` and `JIRA_API_TOKEN` (an Atlassian API token) | `<site>.atlassian.net` |
| `sentry` | `SENTRY_AUTH_TOKEN` (a token with `event:read`) | `sentry.io` or `de.sentry.io` |
| `gmail`, `calendar` | none: Hermes' google-workspace skill signs in (`<profile>/google_token.json`) | Google, by that skill |
| `obsidian` | none | nothing; local reads |

`api_watch.py` reads the credential only from the environment, by that one
name; it never reads a file for it, and never prints, logs or stores it. Put
the key in the profile's `.env`: these names are not Hermes-managed
credentials, so Hermes keeps them in a cron script's environment. Each host is
fixed in the script (Jira's is `<site>.atlassian.net` with the site validated),
so a config cannot send the credential anywhere else. Redirects are refused,
each read has a 15 s timeout and a whole reply 30 s, and replies are capped at 1 MiB.
`google_watch.py` holds no credential: it checks that `google_token.json`
exists and runs the skill's CLI, which reads it.

## Output

The first line is `monitor: <kind> watch=<name>`. The rest is ids and the
platform's own timestamps, sorted, so the bytes change only when the watched
thing does. No message subject, sender, snippet, event title, issue title or
note content is printed; the woken agent reads those with its own tools.

| kind | lines |
| --- | --- |
| `gmail` | `matched=<n>`, then `message <id>` for the newest matching messages |
| `calendar` | `event <id> start=<start>` for every timed event starting after now and within `lead_minutes`, plus the latest one already started (24 h back), or `event none` |
| `notion` | `page <id> edited=<last_edited_time>` (or `archived`), `database <id> row <id> edited=<last_edited_time>` (or `database <id> rows=0`) |
| `linear`, `jira` | `issue <key>` per open assigned issue (or `issues=0`), `limit_reached=yes` when the list was cut |
| `sentry` | `issue <id> short=<short id> first_seen=<time>` for the newest issues the query selects (or `issues=0`) |
| `obsidian` | `folder=<folder> files=<n> digest=<16 hex>` (plus `unreadable=<n>`, `limit_reached=yes`), then `recent <time> <vault-relative name>` |

## Failure and exit codes

| exit | stdout | stderr | what Hermes does |
| --- | --- | --- | --- |
| 0 | the digest | | hash compared: unchanged suppresses the agent, changed wakes it |
| 0 | `error reason=<reason>` (plus `key=<NAME>` for a credential) | a config error's detail | the line changes once, the agent wakes once to report it, and the next ticks are unchanged until it is fixed |
| 1 | nothing | `monitor: <kind> watch=<name> unreachable reason=<reason>` | a failed monitor source: no change, no agent run, the stored hash kept; an alert on the first failed tick, repeats of the same failure held back for `cron.failure_repeat_alert_hours` (6 by default) |

Exit 0 error reasons: `config`, `no_token`, `bad_token`, `token_rejected`
(HTTP 401), `forbidden` (403), `not_found` (404), `request_rejected` (another
4xx, such as invalid JQL), `skill_missing` (no google-workspace skill in the
profile), `not_signed_in` (no `google_token.json`), `sign_in_expired`,
`vault_missing`, `folder_missing`, `folder_unreadable`.

Exit 1 reasons: `network` (a refused or dropped connection, or a timeout),
`platform_busy` (HTTP 429, or a Linear rate limit), `server_error` (5xx),
`redirect_refused`, `reply_too_large`, `bad_response` (a reply it cannot read,
or a non-empty list in which no item has a readable id), `cli_failed` (the
google-workspace CLI failed or hung for another reason). None of them uses the
words Hermes reads as a model provider's failure (rate limit, timed out,
quota), so Hermes' alert names the script, not the model.
