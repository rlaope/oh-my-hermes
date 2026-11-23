# PR watch monitor and webhook event guard

Two scripts that bound a bot working on GitHub pull requests. Both are
executable **companion data**, not OMH commands: catalog, install, update,
routing and doctor only materialize or read their bytes, and OMH core never
imports or runs them. The person's Hermes runs them, from a copy the person
(or their bot, on their request) installed into `<profile>/scripts/`. They are
the scoped exception described in `AGENTS.md` under "PR watch monitor and
event guard".

Both are stdlib only (Python >= 3.10), so they run on Hermes' own interpreter,
and deterministic: the same input and state give the same output bytes.

| script | Hermes hook | reads | writes |
|---|---|---|---|
| `scripts/pr_watch.py` | `hermes cron create --monitor-script` | one `gh pr view` per tick | its own state file |
| `scripts/pr_event_guard.py` | `hermes webhook subscribe --script` | the payload on stdin | its own window file |

`<skill_dir>/toolkit/` is this directory as the skill installed it; in a
checkout it is `src/skills/pr_watch_toolkit/`. `<profile>` is the Hermes home
of the bot's profile (for example `~/.hermes/profiles/kami`, or `~/.hermes`).

## PR watch: `scripts/pr_watch.py`

A wait on one open pull request, without a model polling loop. Hermes runs the
monitor script before the agent on every tick and hashes its exact stdout:
unchanged output suppresses the agent run, changed output wakes it with a diff.
The script prints only the PR's settled state, so the agent wakes when checks
finish (pass or fail), a merge conflict appears, a review is submitted, or the
PR is merged or closed.

Install one watch per PR, named `<watch>` (`[a-z0-9][a-z0-9_-]*`, for example
`widgets-pr-42`):

```sh
install -d -m 700 "<profile>/scripts" "<profile>/pr_watch"
install -m 600 "<skill_dir>/toolkit/scripts/pr_watch.py" "<profile>/scripts/pr_watch_<watch>.py"
install -m 600 my-watch.json "<profile>/pr_watch/<watch>.json"
```

Config `<profile>/pr_watch/<watch>.json` (see `examples/pr-watch.json`):

| key | meaning |
|---|---|
| `name` | the watch name; must equal `<watch>` in the script's file name |
| `repo` | `owner/name` |
| `pr` | the pull request number |
| `deadline` | UTC time `YYYY-MM-DDTHH:MM:SSZ`; default recipe: two hours after the watch starts. From then on the script reads nothing and prints `next=stop_watch reason=deadline` |
| `fix_round_cap` | optional, default 2, at most 2: fix rounds on a failed check before the fix is a person's |

Then the job, every 5 minutes for 24 ticks (two hours, the same bound as the
deadline):

```sh
hermes -p <profile> cron create "every 5m" "<the PR watch prompt>" \
  --name pr-watch-<watch> --monitor-script pr_watch_<watch>.py --repeat 24 \
  --skill omh-github-event-ops --deliver <target>
```

Removing a watch: remove the job, then delete `scripts/pr_watch_<watch>.py`,
`pr_watch/<watch>.json` and `pr_watch/<watch>.state.json`.

Try it by hand: `python3 scripts/pr_watch.py --config path/to/pr-watch.json`.

### Output

```text
pr-watch: <watch> <owner>/<repo>#<pr>
state=open head=<sha12> conflict=no
checks=fail passed=5 failed=2 pending=0
reviews=1 decision=none
fix_rounds_used=1 fix_round_cap=2 first_failed_head=<sha12>
next=fix_round round=2
```

| `next` | when |
|---|---|
| `wait reason=checks_running` | a check is still queued or running; only the header and this line print, so a push during the run keeps the same bytes |
| `fix_round round=<n>` | checks settled with a failure and fewer than `fix_round_cap` rounds are used |
| `hand_to_person reason=fix_round_cap` | checks failed again after the last allowed round |
| `hand_to_person reason=fix_rounds_unreadable` | checks failed and the first failed head is no longer in the PR's commit list (history rewritten) |
| `hand_to_person reason=merge_conflict` | GitHub reports the PR as conflicting |
| `hand_to_person reason=changes_requested` | checks settled green or absent and the review decision is changes requested |
| `report reason=approved`, `reason=checks_pass`, `reason=checks_none` | nothing to fix |
| `stop_watch reason=merged`, `closed`, `deadline` | the watch is over |

Check names, titles and comment text never print: only counts and fixed words.

### Fix rounds, counted from evidence

The first head the monitor sees with checks settled as failed is kept in
`pr_watch/<watch>.state.json` and never replaced. `fix_rounds_used` is the
number of commits the PR's own commit list (`gh pr view --json commits`) holds
after that head. A round pushed as two commits counts as two, which stops the
bot earlier, never later. When that head is gone from the list, the count is
unreadable and failed checks hand the fix to a person.

### Read-only toward the forge

One `gh pr view <pr> --repo <owner>/<repo> --json
state,headRefOid,mergeable,reviewDecision,latestReviews,statusCheckRollup,commits`
per tick, as a fixed argv with no shell, the repository and number validated
before they reach it, stdin closed, a 30 s timeout and output capped at 8 MiB.
It uses the gh CLI's own sign-in (`gh auth status`) and never reads or prints a
token.

| exit | meaning |
|---|---|
| 0 | state printed |
| 3 | config missing or invalid |
| 4 | `gh` not found, failed or timed out |
| 5 | `gh` output unreadable |
| 6 | state file not writable |

On a nonzero exit Hermes reports the monitor source as failed for that tick
and keeps the last output's hash, so a failed read never wakes the agent as a
change.

## Event guard: `scripts/pr_event_guard.py`

A webhook route's filter. Hermes passes the route payload as JSON on stdin;
empty stdout, `[SILENT]`, or a nonzero exit ignores the webhook. The guard
decides from the payload and its config alone (no network, no forge call, no
process):

- **Own-PR guard.** The event is dropped when its sender is one of
  `own_logins`, when the pull request (or the commented issue) was opened by
  one of them, when a head branch it names starts with one of
  `own_branch_prefixes`, or when a comment or review body contains
  `own_comment_marker`.
- **Burst cap.** At most `max_events` accepted events per `window_minutes`
  start a run (default 5 per 15 minutes). A further event inside the window is
  dropped, not queued; dropped events do not count toward the window.

Install one guard per route, named `<route>`:

```sh
install -d -m 700 "<profile>/scripts" "<profile>/pr_event_guard"
install -m 600 "<skill_dir>/toolkit/scripts/pr_event_guard.py" "<profile>/scripts/pr_event_guard_<route>.py"
install -m 600 my-guard.json "<profile>/pr_event_guard/<route>.json"
hermes -p <profile> webhook subscribe <route> --signature github \
  --events pull_request,pull_request_review,issue_comment,check_run \
  --skills omh-github-event-ops --script pr_event_guard_<route>.py
```

Config `<profile>/pr_event_guard/<route>.json` (see `examples/pr-event-guard.json`):

| key | meaning |
|---|---|
| `name` | the route name; must equal `<route>` in the script's file name |
| `own_logins` | GitHub logins only the bot's runs use (a GitHub App such as `my-bot[bot]`, or a machine user). Naming the person's own login drops the person's events too |
| `own_branch_prefixes` | head branch prefixes the bot's runs open PRs from, such as `bot/` |
| `own_comment_marker` | optional, 8 to 200 characters the bot puts in every comment and review it writes, such as `<!-- bot-run -->` |
| `max_events` | optional, default 5 (1 to 100) |
| `window_minutes` | optional, default 15 (1 to 1440) |

At least one of `own_logins` and `own_branch_prefixes` is required. A comment
event carries no head branch, so with only a branch prefix a person's comment
on the bot's PR passes the guard; the run's own re-read of the PR
(`headRefName`) is where the skill's own-PR rule catches it.

Output: a dropped event prints `[SILENT]` and one `pr-event-guard: drop
reason=<own_sender|own_pr_author|own_branch|own_marker|burst_cap ...>` line on
stderr (Hermes logs it). An accepted event prints one `pr-event-guard: pass
window_count=<n> max_events=<m> window_minutes=<w>` line, which Hermes attaches
to the payload as `script_output`. Payload text is never printed.

| exit | meaning |
|---|---|
| 0 | decided: pass, or `[SILENT]` drop |
| 3 | config missing or invalid (every event is dropped) |
| 4 | stdin is not one JSON object (dropped) |
| 5 | the window file could not be locked, read or written (dropped) |

The window lives in `<profile>/pr_event_guard/<route>.state.json` (accepted
event times, at most `max_events`), guarded by a lock file beside it.

## Platforms

Both scripts use only `pathlib`, `json`, `os.replace` and, for the monitor,
`subprocess` with a list argv, so nothing in them is POSIX-only. They are
tested on macOS and Linux; on Windows they are tested in-process only
(the monitor's real `gh` spawn is not exercised there).
