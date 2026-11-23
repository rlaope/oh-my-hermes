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
| `scripts/pr_watch.py` | `hermes cron create --monitor-script` | one `gh pr view` per tick | the PR's own state file |
| `scripts/pr_event_guard.py` | `hermes webhook subscribe --script` | the payload on stdin | its own window file |

`<skill_dir>/toolkit/` is this directory as the skill installed it; in a
checkout it is `src/skills/pr_watch_toolkit/`. `<profile>` is the Hermes home
of the bot's profile (for example `~/.hermes/profiles/kami`, or `~/.hermes`).

## PR watch: `scripts/pr_watch.py`

A wait on one open pull request, without a model polling loop. Hermes runs the
monitor script before the agent on every tick and hashes its exact stdout:
unchanged output suppresses the agent run, changed output wakes it with a diff.
The script prints only the PR's settled state, so the agent wakes when checks
finish (pass or fail), a merge conflict appears, a review is submitted (any
review, a second one by the same person included; one submitted while checks
run is reported once they settle), or the PR is merged or closed.

Install one watch per PR, named `<watch>` (`[a-z0-9][a-z0-9_-]*`, for example
`widgets-pr-42`):

```sh
install -d -m 700 "<profile>/scripts" "<profile>/pr_watch"
install -m 600 "<skill_dir>/toolkit/scripts/pr_watch.py" "<profile>/scripts/pr_watch_<watch>.py"
install -m 600 my-watch.json "<profile>/pr_watch/<watch>.json"
```

On Windows, copy the same files to the same names (there are no mode bits to
set); the scripts themselves use nothing POSIX-only.

Config `<profile>/pr_watch/<watch>.json` (see `examples/pr-watch.json`):

| key | meaning |
|---|---|
| `name` | the watch name; must equal `<watch>` in the script's file name |
| `repo` | `owner/name` |
| `pr` | the pull request number |
| `deadline` | UTC time `YYYY-MM-DDTHH:MM:SSZ`; default recipe: two hours after the watch starts. The watch also ends 24 hours after its first tick, whatever this says; that first tick is kept per watch name, so rewriting the deadline does not restart it, and a later watch on the same PR takes a new name. From then on the script reads nothing and prints `next=stop_watch reason=deadline` |
| `fix_round_cap` | optional, default 2, at most 2: fix rounds on a failed check before the fix is a person's |

Then the job, every 5 minutes for 24 ticks (two hours, the same bound as the
deadline):

```sh
hermes -p <profile> cron create "every 5m" "<the PR watch prompt>" \
  --name pr-watch-<watch> --monitor-script pr_watch_<watch>.py --repeat 24 \
  --skill omh-github-event-ops --deliver <target>
```

Removing a watch: remove the job, then delete `scripts/pr_watch_<watch>.py` and
`pr_watch/<watch>.json`. Keep `pr_watch/state/`: it holds each PR's fix-round
count, and a later watch on the same PR continues from it.

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
| `fix_round round=<n>` | checks settled with a failure and fewer than `fix_round_cap` rounds are used |
| `hand_to_person reason=fix_round_cap` | checks failed again after the last allowed round |
| `hand_to_person reason=fix_rounds_unreadable` | checks failed and the count cannot be read (see below) |
| `hand_to_person reason=merge_conflict` | GitHub reports the PR as conflicting |
| `hand_to_person reason=changes_requested` | the review decision is changes requested, whatever the checks say |
| `report reason=approved`, `reason=checks_pass`, `reason=checks_none` | nothing to fix |
| `stop_watch reason=merged`, `closed`, `deadline` | the watch is over |
| `stop_watch reason=state_unreadable path=<file>` | the PR's state file exists but cannot be parsed; nothing is read from GitHub, the file is not overwritten, and the line names it for a person to check |
| `wait reason=unsettled` | nothing has settled yet in this watch |

**Unsettled is not a change.** While a check is queued or running, while
GitHub reports mergeability as `UNKNOWN` (it recomputes after every push),
while the PR state or head cannot be read, and on the first tick a head shows
no checks at all (CI may not have registered them yet; a second tick with none
settles as `checks_none`), the script
prints this watch's last settled block again, byte for byte. So a push, a CI
run starting, or a mergeability recompute wakes nobody.

Check names, titles and comment text never print: only counts and fixed words.

### Fix rounds, counted from evidence

The count is per pull request and only grows. The PR's state file,
`pr_watch/state/<owner>/<name>/pr-<n>.json`, keeps the first head the monitor
saw with checks settled as failed, every distinct head it observed after that
head, and the highest count it ever printed. Rounds used is the largest of:

- that stored count;
- the number of heads observed after the first failed head (an amend and
  force-push is a new head, so it is a round);
- the number of commits the PR's commit list (`gh pr view --json commits`)
  holds after that head. A round pushed as two commits counts as two.

The commit list is used only when it ends at the current head and holds the
first failed head. Otherwise it is unreadable (history rewritten, a list cut
at GitHub's first 100 commits, a stale list), and failed checks hand the fix to
a person. A new PR opened for the same fix starts a new count; opening one
after the cap is reached is a person's decision.

Every watch on one PR shares that file under one lock file beside it: a tick
reads, changes and writes it only while holding the lock, through a temporary
file of its own and one atomic replace, so watches that tick together (Hermes
runs due jobs in parallel) never corrupt it. A tick that cannot get the lock
within 20 seconds repeats its watch's last block and reads and writes nothing:
no change, no alert. A state file that exists but cannot be read stops the
watch (`next=stop_watch reason=state_unreadable`) instead of guessing.

### Read-only toward the forge

One `gh pr view <pr> --repo <owner>/<repo> --json
state,headRefOid,mergeable,reviewDecision,reviews,statusCheckRollup,commits`
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
| 6 | state file not writable, or not openable while this tick holds the PR's lock (permission denied, a folder in its place) |

On a nonzero exit Hermes reports the monitor source as failed for that tick:
each failed tick is delivered as an alert to the job's `--deliver` target (up
to 24 over a two-hour watch when `gh` is signed out; `gh auth status` names the
fix), and Hermes keeps the last output's hash, so a failed read never wakes the
agent as a change.

## Event guard: `scripts/pr_event_guard.py`

A webhook route's filter. Hermes passes the route payload as JSON on stdin;
empty stdout, `[SILENT]`, or a nonzero exit ignores the webhook. The guard
decides from the payload and its config alone (no network, no forge call, no
process):

- **Own-PR guard.** The event is dropped when its sender is one of
  `own_logins` (or, for a `workflow_run`, its `actor` or `triggering_actor`
  is), when the pull request (or the commented issue) was opened by one of
  them, when a head branch it names starts with one of `own_branch_prefixes`,
  or when a comment or review body contains `own_comment_marker`.
- **Burst cap.** At most `max_events` accepted events per `window_minutes`
  start a run (default 5 per 15 minutes). A further event inside the window is
  dropped, not queued; dropped events do not count toward the window. Hermes
  runs the script before its own redelivery check, so a GitHub redelivery
  spends a slot like any event.
- **Fails closed.** An event without `sender.login` (every GitHub event has
  one) is dropped as `unrecognized_payload`; stdin that is not one JSON object,
  a config error, and a window file that cannot be locked or written exit
  nonzero, which drops the event; a window file that exists but cannot be read
  counts as a full window for one window. A form-encoded delivery, which
  Hermes hands over as `{"payload": "<the JSON event>"}`, is unwrapped first.

Set the GitHub webhook's **Content type: `application/json`**.

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
| `own_branch_prefixes` | head branch prefixes the bot's runs open PRs from, ending in `/` or `-`, such as `bot/` |
| `own_comment_marker` | optional, 8 to 200 characters the bot puts in every comment and review it writes, such as `<!-- bot-run -->` |
| `max_events` | optional, default 5 (1 to 100) |
| `window_minutes` | optional, default 15 (1 to 1440) |

At least one of `own_logins` and `own_branch_prefixes` is required; set both
when you can. What each covers:

- `own_logins` alone covers events the bot sent and PRs it authored. A
  `check_run` or `check_suite` event names no PR author, and its sender is
  usually the CI app, so with logins alone a check event on the bot's PR
  passes. Set `own_branch_prefixes` to cover check events.
- `own_branch_prefixes` alone covers every event that names a head branch. A
  comment event carries no head branch, so a person's comment on the bot's PR
  passes the guard; the run's own re-read of the PR (`headRefName`) is where
  the skill's own-PR rule catches it. A check event on a fork PR lists no PR
  branch either.

Output: a dropped event prints `[SILENT]` and one `pr-event-guard: drop
reason=<own_sender|own_pr_author|own_branch|own_marker|unrecognized_payload|burst_cap ...>`
line on stderr (Hermes logs it). An accepted event prints one `pr-event-guard:
pass window_count=<n> max_events=<m> window_minutes=<w>` line, which Hermes
attaches to the payload as `script_output`. Payload text is never printed.

| exit | meaning |
|---|---|
| 0 | decided: pass, or `[SILENT]` drop |
| 3 | config missing or invalid (every event is dropped) |
| 4 | stdin is not one JSON object (dropped) |
| 5 | the window file could not be locked, read or written (dropped) |

The window lives in `<profile>/pr_event_guard/<route>.state.json` (accepted
event times, at most `max_events`), guarded by a lock file beside it. A clock
moved back does not reopen it: a time from the future counts as now.

## Platforms

Both scripts use only `pathlib`, `json`, `os.replace` and, for the monitor,
`subprocess` with a list argv, so nothing in them is POSIX-only; state files
are created with mode 600 where the platform has mode bits. They are tested on
macOS and Linux; on Windows they are tested in-process and as child processes,
except the monitor's real `gh` spawn.
