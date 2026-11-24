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

**What the gate is.** It is a guardrail. It stops a cooperating agent's
mistakes and the common spellings of a forbidden action, and it refuses what
it cannot parse. It is **not** a sandbox against an agent that deliberately
evades it from a shell, for example by unsetting `HERMES_SESSION_ID` and
driving a terminal to flip the grant, or by writing its own forge client.
Hermes' approval policy and the forge's own branch protection are the
controls for that. Turn on branch protection for the default branch of every
repository a granted bot can reach: require a pull request and a review, and
refuse force pushes, with a ruleset nothing bypasses (GitHub Actions
included). Also bound what a workflow on a bot branch can reach: set the
default `GITHUB_TOKEN` permissions to read-only and put deploy and other
secrets behind environments with required reviewers (see the list below). The
gate refuses the obvious self-grant spellings, but that list is not complete.

**What changes when this ships.** In a cron job (a PR watch included), a
webhook or `api_server` run, a `hermes chat -q` run or a delegated child:

- A command that pushes a branch or opens a PR is refused with a hand-off
  until the person runs `omh capability-policy pr-delivery on` for that
  profile.
- Merges, force pushes and pushes to the default branch are refused with or
  without the grant.

## The commands

```sh
omh capability-policy pr-delivery show [--json]
omh capability-policy pr-delivery on [--branch-prefix bot/] [--json]
omh capability-policy pr-delivery off [--json]
```

The grant is per Hermes profile. Select the profile with `omh --hermes-home
<profile home>` (and `--omh-home` when that profile has its own OMH home).
`on` and `off` refuse to run inside a Hermes session. They detect it from
`HERMES_SESSION_ID`, which Hermes sets for every command its terminal tool
runs, and from the other markers Hermes puts in its children's environment
(every `HERMES_SESSION_*`, `HERMES_UI_SESSION_ID`, `HERMES_CRON_SESSION`,
`HERMES_AGENT`, `HERMES_EXEC_ASK`, `HERMES_SINGLE_QUERY_SESSION`). `on` also
asks for a typed yes on a terminal a person can see: `/dev/tty` on POSIX,
and on Windows the console, only when its window is visible. This stops a
cooperating agent and an agent without a terminal. It does not stop a bot
that spells the command past the tool hook, unsets every marker and spawns
its own pseudo-terminal (the terminal tool's `pty=true` makes the pty the
child's controlling terminal, and `process submit "y"` answers it) or answers a hidden
console: that bot can type the yes itself. That is the same class as the
other residuals below, which the gate does not claim to stop. `omh doctor`
lists every profile in the OMH home whose grant is on.

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

OMH's `pre_tool_call` hook (`src/plugin_bundle/omh/pr_delivery_gate.py`) reads
`terminal` commands, `process` stdin writes, `execute_code`, file writes and
MCP tool names. Commands go through its own shell-aware lexer, in which `#` is
an ordinary character, as it is to bash inside a word. It unwraps `env`,
`sudo`, `timeout` and similar wrappers, reads into `sh -c`, `eval`,
`submodule foreach`, `rebase -x` and `bisect run`, and then applies an explicit
option table for `git push`, `git config`, `git remote`, `gh pr`, `gh api`,
`gh auth` and the repository-level `gh` groups. A `gh` flag given twice is
read as gh reads it: the last value wins.

A session counts as unattended when it is one of these:

- a programmatic platform (`webhook`, `msgraph_webhook`, `api_server`);
- a cron turn (Hermes builds every cron agent with `platform="cron"`, and OMH
  records the platform `pre_llm_call` passes);
- a delegated child (`platform="subagent"`, or reported by `subagent_start`);
- a single-query `hermes chat -q` process.

| Command class | Attended chat | Unattended | Delegated child |
| --- | --- | --- | --- |
| push to `origin` `HEAD:refs/heads/<prefix>...` with a named destination | Hermes approvals | allowed with the grant on, refused with a hand-off while it is off | refused, because a child does not carry the grant |
| `gh pr create --head <prefix>...` as the only command in the line, without `--repo`, `--label` or `--body-file`, at most one per run (one Hermes session id: one webhook delivery, one cron run, one `chat -q` process, one chat session), counted from the opened-PR record | Hermes approvals | same as above | refused |
| `gh pr comment <URL>` on a recorded own PR, body not a bot command | Hermes approvals | same as above | refused |
| merge or merge trigger (`gh pr merge`, a `gh api` write to a merge endpoint, a comment line starting with `/`, `@name ...` or `bors`) | Hermes approvals | refused | refused |
| force push or ref deletion (`-f`, `--force`, `--force-with-lease`, `+ref`, `--delete`, `:ref`, `--mirror`, `--prune`) | Hermes approvals | refused | refused |
| push outside the prefix or to a remote other than `origin` (`HEAD:main`, `main`, tags, `--all`, a URL) | Hermes approvals | refused | refused |
| push options (`-o`), another PR or the repository (`gh pr edit/close/review/...`, a comment on an unrecorded PR, `gh pr create --repo/--label`, `gh repo/secret/label/release ...`, any `gh api` write, an MCP tool whose name says merge, push, delete or pull_request) | Hermes approvals | refused | refused |
| destination not named (`git push`, `git push origin HEAD`, `git push origin bot/x`, `gh pr create` without `--head`, `gh pr comment 12` without `--repo`) | Hermes approvals | refused | refused |
| unclassifiable (see below) | Hermes approvals | refused (fails closed) | refused |

Unclassifiable covers:

- an unbalanced quote, a backquote, `env -S`, or a heredoc in a multi-line
  command that names git or gh;
- a `$` word, or a quoted or escaped command word, beside a forge verb;
- `-c`, `--config-env` or `--exec-path` on git, and a `GIT_*`, `GH_*`,
  `GITHUB_*`, `PATH`, `HOME` or `XDG_CONFIG_HOME` assignment or export;
- `--upload-pack`, `--receive-pack`, `--exec`, `--extcmd`, `ext::` or `fd::`;
- a write to any `git config` key but `user.name` and `user.email`, and any
  `git remote` change;
- a git subcommand or alias the table does not know, and `difftool`;
- `gh auth` other than a plain `status` (`gh auth token` prints a
  credential), a named forge token variable (`GH_TOKEN`, `GITHUB_TOKEN`),
  gh's `hosts.yml` or git's `.git-credentials`, and an unknown `gh` group;
- a comment (`#` word), and command or process substitution (`$(...)`,
  backquotes, `<(...)`) in a command that names git or gh;
- a function or alias named git or gh;
- git or gh beside a forge verb under another program;
- `execute_code` naming them, a `process` write that is not a whole line,
  and a file-tool write to a file git or gh reads as configuration or runs
  as a hook (anything under `.git/` in any letter case, `.gitconfig`,
  `~/.config/git/config`, `.gitmodules`, gh's `config.yml` and `hosts.yml`);
- an operator run joined to its neighbours (`;(`, `&&(`), and a
  backslash-newline inside a word, which are read the way bash reads them.

In an attended chat nothing changes. The person is there, and Hermes' own
approvals apply.

Why a bare branch name counts as "not named": `remote.<name>.push` can remap
`git push origin bot/x` to another branch. At the moment the shell runs, the
hook cannot see which branch is checked out, so a push must say
`HEAD:refs/heads/<prefix><topic>`.

What Hermes itself flags (measured against the installed Hermes'
`tools/approval_detection.py`): a force push. It flags no plain `git push`,
including one to the default branch, and no `gh` verb, including `gh pr
merge`. Outside OMH's gate, nothing else stops those in an unattended run.

A raise inside OMH's hook fails closed: Hermes turns a `pre_tool_call`
exception into a block (`hermes_cli/plugins_dispatch.py`). A runtime-binding
fault before the gate runs (an unreadable profile config) returns an allow
for every gate, this one included; that window is the pre-existing one
`tool_hooks.py` states.

## What this gate is, and is not

It holds a cooperating model against its own mistakes and against naive
injected instructions, such as a webhook payload telling the bot to merge. It
is **not** a boundary against a model that sets out to evade it. These reach
the forge without passing the gate:

- a script file run by an interpreter (`bash deliver.sh`, `python x.py`), and
  `base64 -d | sh`;
- the persistent shell (Hermes' `terminal.persistent_shell` defaults to on): a
  function, alias or PATH shim defined under a name the gate does not read;
- an HTTP client with a token (`curl`, `wget`, `httpie`, a Python request),
  for which `gh auth token` is refused but any token already in the
  environment or a file is not;
- an MCP or other forge tool whose name does not say merge, push, delete,
  fork, comment, review, close, label or a pull-request write. The gate reads
  only the tool's name, never its arguments, so it cannot judge a comment
  body sent through one;
- a write to `~/.ssh/config` by a program this gate does not name: a
  `ProxyCommand` or `Match exec` there runs a command during an otherwise
  covered push over ssh. A file-tool write to it, and `cp`, `mv`, `ln` or a
  redirection naming it, are refused in an unattended run;
- a workflow file under `.github/workflows/` committed on a bot branch: it
  runs on the forge with the repository's token, and whatever secrets the
  repository exposes to such runs, as soon as the branch is pushed or the PR
  opens. The gate does not look inside a push for this. The bot pushes with
  the person's own login to a branch of the same repository, so GitHub's
  approval setting for workflow runs (which covers fork pull requests from
  outside or first-time contributors) does not apply, and a same-repository
  `pull_request` run receives the repository's secrets. Bound it on the forge:
  set the default `GITHUB_TOKEN` permissions to read-only; put deploy and
  other secrets behind environments with required reviewers; protect the
  default branch with a ruleset nothing bypasses, GitHub Actions included;
  where the plan offers push rulesets, block changes to `.github/workflows/**`
  on bot branches. A CODEOWNERS entry for `.github/workflows/` gates the merge,
  not the run;
- a local-path or `insteadOf` remote set up before the grant applied, and a
  `cd` into another checkout before `git push origin ...` (`git -C`,
  `--git-dir` and `--work-tree` on a push are refused);
- a symlink or junction made before the grant applied, or by a program this
  gate does not name. A file-tool write is checked both as written and with
  every link resolved (`g -> .git` then `g/hooks/pre-push` is refused), and
  `ln`, `mklink`, `New-Item -ItemType Junction`, `cp`, `mv` and similar
  naming `.git` or a git config are refused in an unattended run. The
  command side is lexical: a link made through a glob or a variable
  (`ln -s .gi? g`, `L=.git; ln -s $L g`), or by any program not named here,
  and then written through by a shell redirect (`echo x > g/hooks/pre-push`)
  is not seen. Plain reads of a protected path are allowed by `cat`,
  `head`, `tail`, `ls`, `stat`, `wc`, `grep`/`egrep`/`fgrep` and the read
  forms of `git config` (`--get`, `--get-all`, `--get-regexp`, `--list`),
  and only when their segment assigns no variable and the line names no
  pager or reader variable (`LESS*`, `PAGER`, `GIT_PAGER`, `MANPAGER`,
  `MORE`, `GREP_*`, `LS_*`). The allowance is an exception to the
  protected-path refusal alone: every other check still runs on the
  reader. Pagers, `find`, `tree`, `rg`, `sed`, `awk`, `xargs` and `sort`
  keep the refusal (`LESSOPEN='|…' less` runs a command, `tree -o` writes,
  `rg --pre` runs a program). Writes, links, copies onto a protected path
  and redirects into it are refused;
- the grant file and the opened-PR record written by arbitrary code under
  another spelling (the file tools and command lines that name the store are
  refused);
- on Windows, the grant file's mode bits, which mean nothing there.

## Windows

Nothing of this has run on Windows; the following is what the code does
there, held by tests that run on every platform through fakes.

- `on` asks for its yes on the console (`CONIN$` and `CONOUT$`), the Windows
  equivalent of `/dev/tty`, and only when that console has a visible window.
  Hermes spawns every terminal child with `CREATE_NO_WINDOW`, which gives it
  a hidden console: `CONIN$` would open there with nobody at it, so a hidden
  or missing console is a refusal ("turning the grant on needs a yes typed at
  your own terminal"), never a wait and never a crash. A classic console
  window (conhost: `cmd.exe` or Windows PowerShell started from the Start
  menu) is expected to work. Under Windows Terminal (ConPTY),
  `GetConsoleWindow` may return a pseudo-window that reports as invisible,
  so `on` may refuse there; run it from a classic console window instead.
  None of this has run on Windows.
- The grant file's owner and mode are not checked: POSIX mode bits mean
  nothing there, so the grant reads as recorded. On POSIX the check only
  excludes other users and group or world writes. The threat the grant
  guards against is the user's own bot, which runs as the same account, so
  neither mode bits nor an ACL tell the two apart. When the OMH home is under
  `%USERPROFILE%`, the default profile ACL (the user, SYSTEM, Administrators)
  already excludes other users. A shared or relocated OMH home (`OMH_HOME`
  outside the profile, or one home for several accounts) does not: give it
  an ACL of its own.
- The file-write guard folds Windows spellings to the file the system opens:
  backslashes, drive letters, letter case, trailing dots and spaces
  (`.git.`), NTFS stream suffixes (`.git::$INDEX_ALLOCATION`), the 8.3 short
  names (`GIT~1`, `GITCON~1`, `GITMOD~1` and their kin), and gh's
  `GitHub CLI\config.yml` and `hosts.yml` under AppData.
- Commands are read with a POSIX shell lexer, which is right on Windows
  too: Hermes runs the terminal through Git Bash there. `git.exe`, `gh.exe`
  and PowerShell's `& git ...` are read as git and gh. In an unattended run
  these are refused as unparseable when the command names git or gh:
  - a command word written as a Windows path (`C:\Program Files\Git\cmd\git.exe`,
    quoted or not); a backslash inside an argument is read as Git Bash
    reads it and is not refused, so `git log --format='%h\t%s'` passes;
  - a command word holding cmd.exe's `^` or `%VAR%`, or a PowerShell
    backtick; `%` in a branch name, push destination or `--head` is refused
    too, while `%` elsewhere (a `--format` string) is literal under Git Bash;
  - any `powershell`, `pwsh` or `cmd` invocation (any path, any `.exe`) that
    is not a plain script file (`-File x.ps1`, `pwsh x.ps1`, `cmd /c
    x.bat`): `-EncodedCommand` and every prefix PowerShell accepts for it,
    `-Command`, stdin, `cmd /c <command>`, `/k`;
  - `$env:GH_REPO = ...`, `Set-Item Env:...`, `set` or `setx` of a forge
    variable, `cmd /c ...`, `powershell -Command ...`, `Start-Process git ...`.
- The gate reads POSIX shell syntax, because Hermes' local backend runs the
  terminal through Git Bash on Windows. Forms that work only inside a
  PowerShell shell (`&('g'+'it') push`, `& (gcm gh) pr merge`, `Set-Alias`,
  `function git`, `[Environment]::SetEnvironmentVariable`) are not read; from
  Git Bash every way into PowerShell is refused, as above.

## Residuals, stated

- Only `git` and `gh` are recognized as forge CLIs.
- Two profiles that grant the same prefix can each push to the other's bot
  branches. `omh doctor` warns when that is the case; give each bot its own
  prefix.
- `gh issue create|comment|close|edit|reopen` are outside this gate (owner
  call, 2026-11-24). `gh run rerun|cancel|delete` and `gh issue
  delete|transfer|develop` are refused in an unattended run.
- The merge-trigger refusals (a comment or PR title or body line that
  starts with `/`, `!`, `@name <word>` or `bors`, or names merge, automerge,
  squash or rebase; and any `--label`, `--milestone` or `--project` on PR
  creation) are a best-effort
  list. A merge bot that reads other words or labels is not covered.
- A commit message or command argument that reads as a forge command, or
  holds a `$`, can be refused in an unattended session. This is the
  fail-closed direction.
