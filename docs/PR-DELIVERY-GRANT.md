# PR Delivery Grant

Audience: operators, meaning the person who owns a Hermes bot profile. Normal
users ask in chat. The commands below are the person's own and are not for an
agent: a bot tells the person the command and never runs it.

A bot that works unattended, in a webhook run, a one-shot run or a scheduled
watch, may fix code and commit. By default it then stops: nobody can answer a
confirmation, so the push and the pull request go to a person's turn. The PR
delivery grant lets one profile's bot finish that delivery itself. This is
owner-approved, 2026-11-23
([`IMPLEMENTATION-BOUNDARIES.md`](IMPLEMENTATION-BOUNDARIES.md)).

## The commands

```sh
omh capability-policy pr-delivery show [--json]
omh capability-policy pr-delivery on [--branch-prefix bot/] [--json]
omh capability-policy pr-delivery off [--json]
```

The grant is per Hermes profile. Select the profile with `omh --hermes-home
<profile home>` (and `--omh-home` when that profile has its own OMH home).
`on` and `off` refuse to run inside a Hermes session, which they detect from
the `HERMES_SESSION_ID` that Hermes sets for every command its terminal tool
runs. `omh doctor` lists every profile in the OMH home whose grant is on.

## What it allows

| Allowed with the grant | Never, grant or no grant |
| --- | --- |
| push a new branch under the grant's branch prefix | merge a pull request, on the forge or by pushing a merge to the default branch |
| open a pull request from that branch | force-push, or delete a remote branch |
| push fix commits to a pull request this bot opened | push to the default branch |
| comment on a pull request this bot opened | act on a pull request this bot did not open, or change repository settings |

`omh` itself runs no forge command. The bot runs `git` and `gh` with your own
login: Hermes, or the coding owner it handed the work to.

## Where it lives

`<omh_home>/runtime/pr_delivery/grant-<digest>.json`, where `<digest>` is
taken from the profile's Hermes home and the file names that home. The schema
is `omh_pr_delivery_grant/v1`, and the file holds `state`, `hermes_home`,
`branch_prefix`, `granted_at`, `turned_off_at` after an `off`, and the fixed
`allowed_actions` and `never_allowed_actions`. The grant reads as off when
the file is missing, unreadable, malformed or larger than 16 KiB, when its
schema is unknown, when it names another profile, when its scope differs from
the fixed one, or when its prefix is invalid. Two profiles that share one OMH
home never share a grant.

The bot reads the grant's state with the `omh_status` tool
(`pr_delivery_grant`). No tool, skill or hook can turn it on. OMH's tool hook
refuses a command line that would change it or that names its store, in every
session. It also refuses a file-tool write into the store.

"A pull request this bot opened" is OMH's record and never the bot's word.
The record is kept in `opened-<digest>.jsonl` beside the grant, schema
`omh_pr_delivery_opened_pr/v1`. One line is written when a `gh pr create`
that the grant allowed, run as a command of its own, exits 0 and prints the
new pull request's URL on its last line.

## Enforcement matrix

OMH's `pre_tool_call` hook (`src/plugin_bundle/omh/pr_delivery_gate.py`)
reads `terminal` commands with the same shell-aware tokenizing that anchors
`git push` elsewhere in the plugin. It unwraps `env`, `sudo`, `timeout` and
similar wrappers and reads into `sh -c` and `eval`. It then uses an explicit
option table for `git push`, `gh pr`, `gh api` and the repository-level `gh`
groups.

| Command class | Attended chat | Programmatic platform (`webhook`, `msgraph_webhook`, `api_server`) or single-query `hermes chat -q` | Delegated child | Cron turn |
| --- | --- | --- | --- | --- |
| push to `refs/heads/<prefix>...` with a named destination | Hermes approvals | allowed with the grant on, refused with a hand-off while it is off | refused, because a child does not carry the grant | not visible to OMH |
| `gh pr create --head <prefix>...`, without `--repo` | Hermes approvals | same as above | refused | not visible |
| push or `gh pr comment <URL>` on a recorded own PR | Hermes approvals | same as above | refused | not visible |
| merge (`gh pr merge`, a `gh api` write to a merge endpoint) | Hermes approvals | refused | refused | not visible |
| force push or ref deletion (`-f`, `--force`, `--force-with-lease`, `+ref`, `--delete`, `:ref`, `--mirror`, `--prune`) | Hermes approvals | refused | refused | Hermes flags it, and `approvals.cron_mode` decides |
| push outside the prefix (`HEAD:main`, `main`, tags, `--all`) | Hermes approvals | refused | refused | not visible |
| another PR or the repository (`gh pr edit/close/review/...`, a comment on an unrecorded PR, `gh pr create --repo`, `gh repo/secret/label/release ...`, any `gh api` write) | Hermes approvals | refused | refused | not visible |
| destination not named (`git push`, `git push origin HEAD`, `git push origin bot/x`, `gh pr create` without `--head`, `gh pr comment 12` without `--repo`) | Hermes approvals | refused | refused | not visible |
| unclassifiable (a backquote, an unbalanced quote, `env -S`, an unknown git subcommand or alias, an unknown `gh` group, git or gh beside a forge verb under another program, `execute_code` naming them) | Hermes approvals | refused (fails closed) | refused | not visible |

In an attended chat nothing changes. The person is there, and Hermes' own
approvals apply.

Why a bare branch name counts as "not named": `remote.<name>.push` can remap
`git push origin bot/x` to another branch. At the moment the shell runs, the
hook cannot see which branch is checked out, so a push must say
`HEAD:refs/heads/<prefix><topic>`.

Why a cron turn is not visible: the cron marker is a Hermes context variable
and never a process variable, and a plugin hook is not passed it
(`src/plugin_bundle/omh/hooks/session_attendance.py`). A PR watch job runs as
a cron turn, so there the bounds are the following. The job's prompt and the
`github-event-ops` skill text state the grant's scope. The PR watch's
two-round fix cap holds. Hermes' own approvals flag a force push and decide it
by `approvals.cron_mode`, which defaults to deny. Hermes flags no plain `git
push` and no `gh` verb (measured against the installed Hermes'
`tools/approval_detection.py`). That includes a push to the default branch
and `gh pr merge`.

## Residuals, stated

- Only `git` and `gh` are recognized as forge CLIs. Another forge's CLI is not
  classified.
- A script file run by an interpreter (`bash deliver.sh`, `python deliver.py`)
  is not read. A command line or `execute_code` that names git or gh beside a
  forge verb is refused.
- The repository a push goes to (the remote's URL) is not checked. Only the
  destination branch is checked.
- The grant file and the opened-PR record are protected against the file
  tools and against command lines that name them. They are not protected
  against arbitrary code that writes them under another spelling.
- A commit message whose body holds a line that reads as a forge command can
  be refused in an unattended session. This is the fail-closed direction.
