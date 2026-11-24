"""What an unattended run may publish to a forge, held at `pre_tool_call`.

Owner-approved, 2026-11-23; `docs/PR-DELIVERY-GRANT.md` states the matrix for
people. Rows are session kinds; columns are what a command does on the forge.

* **Attended** (a person can answer a prompt): this gate has no opinion. The
  person is there and Hermes' own approvals apply.
* **Unattended** -- a programmatic platform (`webhook`, `msgraph_webhook`,
  `api_server`), a cron turn (Hermes builds every cron agent with
  `platform="cron"`, which `pre_llm_call` passes and `session_attendance`
  records), a delegated child (`platform="subagent"`, or `subagent_start`), or
  a single-query `hermes chat -q` process:
  - grant-covered: a push to the literal remote `origin` whose every
    destination is spelled `<src>:refs/heads/<prefix>...` with no force;
    `gh pr create --head <prefix>...` as a command of its own, without
    `--repo` or `--label`, at most one per session; `gh pr comment <URL>`
    (or `<n> --repo <owner>/<name>`) on a PR this profile's gate recorded as
    opened, with a body that is no bot command. Allowed with the grant on;
    refused with a hand-off message while it is off, and always in a
    delegated child, which does not carry the grant.
  - always refused, whatever the grant says: force pushes and remote ref
    deletion, a push anywhere but `origin`'s prefixed branches, merges and
    merge triggers, any other PR or repository write, push options.
  - refused as unqualified: a push or PR that does not name its destination.
    The hook cannot know which branch is checked out when the shell runs, and
    `remote.<name>.push` can remap a bare branch name.
  - refused as unclassified (fail closed): anything the tables below do not
    know, and every form that carries a command or configuration into git or
    gh (`-c`, `GIT_*`/`GH_*`/`PATH` assignments, `--upload-pack`, `ext::`,
    `rebase -x`, a `$` word, a function or alias named git or gh).

Everywhere, attended or not: a command that would turn the grant on or off,
or that names its store, is refused.

What this is, stated plainly: a gate that holds a cooperating model against
its own mistakes and against naive injected instructions. It is not a boundary
against a model that sets out to evade it -- a script file, a persistent-shell
function defined under another name, an HTTP client with a token, or an MCP
tool this gate does not name all reach the forge without passing here. The
residuals are listed in `docs/PR-DELIVERY-GRANT.md`.

The lexer is this module's own: shell-aware `shlex` with `#` NOT a comment
character (bash does not end a word at `a#b`, and over-reading a real comment
is the fail-closed direction). Only `git` and `gh` are recognized forge CLIs.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
from collections.abc import Mapping
from typing import Final

from . import pr_delivery
from .consistency_trigger import _edit_targets
from .tools.lsp_nav_tool import _workspace_root
from .hooks.nudge_budget import session_is_delegated
from .hooks.session_attendance import SINGLE_QUERY_SESSION_ENV, UNATTENDED_APPROVAL_PLATFORMS, session_platform

TERMINAL_TOOL: Final = "terminal"
CODE_TOOL: Final = "execute_code"
PROCESS_TOOL: Final = "process"
FILE_TOOLS: Final = frozenset({"write_file", "patch"})

# Command classes.
LOCAL: Final = "local"
PUSH_BOT_BRANCH: Final = "push_bot_branch"
OPEN_PR: Final = "open_pr"
COMMENT_OWN_PR: Final = "comment_own_pr"
FORCE_PUSH: Final = "force_push_or_ref_delete"
PUSH_OUTSIDE: Final = "push_outside_bot_branches"
FORGE_MERGE: Final = "merge"
OTHER_PR_OR_REPO: Final = "other_pr_or_repository_write"
UNQUALIFIED: Final = "destination_not_named"
UNCLASSIFIED: Final = "unclassified"
NOT_GOVERNED: Final = "not_governed_by_this_gate"

GRANT_COVERED: Final = frozenset({PUSH_BOT_BRANCH, OPEN_PR, COMMENT_OWN_PR})
# Most severe first: a command's class is its worst segment's.
_SEVERITY: Final = (
    FORCE_PUSH, FORGE_MERGE, PUSH_OUTSIDE, OTHER_PR_OR_REPO, UNCLASSIFIED, UNQUALIFIED,
    OPEN_PR, COMMENT_OWN_PR, PUSH_BOT_BRANCH, NOT_GOVERNED, LOCAL,
)
_DESCRIPTIONS: Final[Mapping[str, str]] = {
    FORCE_PUSH: "a force push or a remote branch deletion",
    FORGE_MERGE: "a merge, or a command that asks a bot to merge",
    PUSH_OUTSIDE: "a push to anything but a branch under the bot's prefix on origin",
    OTHER_PR_OR_REPO: "a change to a pull request this bot did not open, or to the repository itself",
    UNQUALIFIED: "a push or pull-request command that does not name its destination",
    UNCLASSIFIED: "a command whose forge effect OMH cannot read",
    PUSH_BOT_BRANCH: "a push of the bot's work branch",
    OPEN_PR: "opening a pull request",
    COMMENT_OWN_PR: "a comment on the bot's own pull request",
}

# Session kinds where nobody answers: the host's programmatic platforms, cron,
# and a delegated child's own platform.
UNATTENDED_PLATFORMS: Final = UNATTENDED_APPROVAL_PLATFORMS | frozenset({"cron", "subagent"})
_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})

_MAX_DEPTH: Final = 3
_SEPARATORS: Final = frozenset({"&&", "||", "|", "|&", ";", ";;", ";&", ";;&", "&", "(", ")"})
_REDIRECT: Final = re.compile(r"^&?[<>]+[&|]?$")
_OPERATOR_RUN: Final = re.compile(r"^[();<>|&]+$")
_SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
# Transparent wrappers: the command after them is the command. Each maps to
# the options that take a separate value.
_WRAPPERS: Final[Mapping[str, frozenset[str]]] = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir"}),
    "command": frozenset(),
    "builtin": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "sudo": frozenset({"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-D", "-U", "-r", "-t"}),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
}
_WRAPPER_POSITIONALS: Final[Mapping[str, int]] = {"timeout": 1}
_UNREADABLE_WRAPPER_OPTIONS: Final = frozenset({"-S", "--split-string"})
_ASSIGNMENT: Final = re.compile(r"^([A-Za-z_][A-Za-z_0-9]*)\+?=")
# Variables that redirect or reprogram git or gh: their `-c`, `--repo` and
# `--exec-path` in another spelling.
# Plus the variables git, gh or a pager they start read as a program to run
# (git(1) ENVIRONMENT and git-var(1): EDITOR, VISUAL, PAGER, SSH_ASKPASS, the
# GIT_* family incl. GIT_EDITOR, GIT_SEQUENCE_EDITOR, GIT_ASKPASS, GIT_SSH,
# GIT_SSH_COMMAND, GIT_PAGER, GIT_EXTERNAL_DIFF, GIT_PROXY_COMMAND; gh's
# environment help: GH_EDITOR, GH_BROWSER, GH_PAGER, BROWSER; less(1):
# LESS, LESSOPEN, LESSCLOSE, LESSKEY*; man(1): MANPAGER).
_ENV_NAMES: Final = (r"GIT_\w*|GH_\w*|GITHUB_\w*|PATH|HOME|XDG_CONFIG_HOME|EDITOR|VISUAL|PAGER|MANPAGER|LESS\w*|"
                     r"SSH_ASKPASS|BROWSER")
_FORGE_ENV: Final = re.compile(rf"^(?:{_ENV_NAMES})$", re.IGNORECASE)
_DECLARERS: Final = frozenset({"export", "declare", "typeset", "readonly", "local", "set", "setx"})
# Marks in a command word that a shell resolves before it runs it: POSIX
# expansion and quoting, cmd.exe's `^` escape and `%VAR%`, PowerShell's backtick.
_HIDING_MARKS: Final = "$\\'\"^%`"
# PowerShell's environment assignment (`$env:GH_REPO = ...`), the twin of `GH_REPO=...`.
_POWERSHELL_ENV: Final = re.compile(rf"^\$?env:(?:{_ENV_NAMES})\b", re.IGNORECASE)
_WINDOWS_EXECUTABLE: Final = re.compile(r"\.(?:exe|cmd|bat|com)$", re.IGNORECASE)
# A backslash before a letter or digit: a Windows path, which the POSIX lexer
# would read as escapes (`C:\Program Files\Git\cmd\git.exe` loses every one).
_WINDOWS_PATH_BACKSLASH: Final = re.compile(r"\\[A-Za-z0-9]")
_DEFINERS: Final = frozenset({"alias", "function", "unalias", "unset", "hash"})

# A pattern rather than a ("git", ...) literal: INVARIANT 3 reads such a tuple as a git argv.
_FORGE_CLI: Final = re.compile(r"^(?:git|gh)$")
_FORGE_WORD: Final = re.compile(r"\b(?:git|gh)\b", re.IGNORECASE)
_FORGE_VERB: Final = re.compile(
    r"\b(?:push|merge|pr|api|repo|release|secret|variable|label|workflow|ruleset|send-pack|config|remote)\b",
    re.IGNORECASE,
)
_EXEC_CARRIERS: Final = ("--upload-pack", "--receive-pack", "--exec", "--extcmd", "--open-files-in-pager")
_EXEC_URL: Final = re.compile(r"(?:^|[:=])(?:ext|fd)::", re.IGNORECASE)

# git ------------------------------------------------------------------------
_GIT_GLOBAL_VALUE: Final = frozenset({"-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--list-cmds"})
_GIT_GLOBAL_BOOL: Final = frozenset({
    "-p", "--paginate", "-P", "--no-pager", "--bare", "--no-replace-objects", "--literal-pathspecs",
    "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-optional-locks", "--no-advice",
    "--html-path", "--man-path", "--info-path", "--version", "--help", "-h",
})
# Subcommands that change nothing on a remote and run nothing they are handed.
# `push`, `config`, `remote`, `rebase`, `bisect`, `submodule` are read on their
# own; any name not here (an alias, `lfs`, `send-email`, `difftool`) is unclassified.
_GIT_LOCAL: Final = frozenset({
    "add", "am", "annotate", "apply", "archive", "blame", "branch", "bundle", "cat-file", "check-attr",
    "check-ignore", "check-mailmap", "check-ref-format", "checkout", "cherry", "cherry-pick", "clean",
    "clone", "column", "commit", "commit-graph", "commit-tree", "count-objects", "describe",
    "diff", "diff-files", "diff-index", "diff-tree", "fetch", "for-each-ref", "format-patch",
    "fsck", "gc", "grep", "hash-object", "help", "init", "interpret-trailers", "log", "ls-files",
    "ls-remote", "ls-tree", "maintenance", "merge", "merge-base", "merge-file", "mktag",
    "mktree", "mv", "name-rev", "notes", "pack-refs", "prune", "pull", "range-diff", "read-tree", "reflog",
    "repack", "replace", "request-pull", "rerere", "reset", "restore", "rev-list", "rev-parse",
    "revert", "rm", "shortlog", "show", "show-branch", "show-ref", "sparse-checkout", "stash", "status",
    "stripspace", "switch", "symbolic-ref", "tag", "unpack-file", "update-index", "update-ref", "var",
    "verify-commit", "verify-pack", "verify-tag", "version", "whatchanged", "worktree", "write-tree",
})
_GIT_CONFIG_READS: Final = frozenset({"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "get",
                                      "list"})
_GIT_CONFIG_SAFE_KEYS: Final = frozenset({"user.name", "user.email"})
_GIT_REMOTE_READS: Final = frozenset({"", "-v", "--verbose", "show", "get-url"})
_PUSH_LONG_BOOL: Final = frozenset({
    "--set-upstream", "--quiet", "--verbose", "--progress", "--no-progress", "--no-verify", "--verify",
    "--atomic", "--no-atomic", "--porcelain", "--thin", "--no-thin", "--ipv4", "--ipv6", "--no-signed",
    "--no-force-with-lease", "--no-recurse-submodules", "--no-follow-tags",
})
_PUSH_LONG_OPTIONAL_VALUE: Final = frozenset({"--signed", "--recurse-submodules"})
_FORCE_LONG: Final = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune"})
_WIDE_LONG: Final = frozenset({"--all", "--branches", "--tags", "--follow-tags"})
_NOT_LITERAL: Final = re.compile(r"[$`*?\[\\~^%\s'\"]|\.\.|@\{")
_PUSH_REMOTE: Final = "origin"

# gh -------------------------------------------------------------------------
_GH_READ_ONLY_GROUPS: Final = frozenset({"--version", "version", "status", "search"})
_GH_READ_VERBS: Final = frozenset({"view", "list", "status", "checks", "diff", "checkout", "get", "check",
                                   "download", "clone", "watch", "set-default"})
_GH_PR_MUTATIONS: Final = frozenset({"edit", "close", "reopen", "ready", "review", "lock", "unlock",
                                     "update-branch", "revert"})
_GH_REPO_GROUPS: Final = frozenset({"repo", "secret", "variable", "label", "workflow", "release", "ruleset",
                                    "cache", "deploy-key"})
_GH_NOT_GOVERNED_GROUPS: Final = frozenset({"issue", "run"})
# Owner call (2026-11-24): these verbs of the otherwise ungoverned groups are
# never run unattended. `issue develop` creates a branch on the forge.
_GH_GOVERNED_VERBS: Final[Mapping[str, frozenset[str]]] = {
    "run": frozenset({"rerun", "cancel", "delete"}),
    "issue": frozenset({"delete", "transfer", "develop"}),
}


def _aliases(*pairs: tuple[str, str]) -> dict[str, str]:
    """Each spelling of a gh flag mapped to one canonical name, so the last value wins as in gh."""
    table: dict[str, str] = {}
    for short, long in pairs:
        table[short] = long
        table[long] = long
    return table


_GH_PR_CREATE_VALUE: Final = _aliases(
    ("-t", "--title"), ("-b", "--body"), ("-F", "--body-file"), ("-B", "--base"), ("-H", "--head"),
    ("-a", "--assignee"), ("-l", "--label"), ("-m", "--milestone"), ("-p", "--project"), ("-r", "--reviewer"),
    ("-T", "--template"), ("-R", "--repo"), ("--recover", "--recover"),
)
_GH_PR_CREATE_BOOL: Final = _aliases(
    ("-d", "--draft"), ("-f", "--fill"), ("--fill-first", "--fill-first"), ("--fill-verbose", "--fill-verbose"),
    ("--no-maintainer-edit", "--no-maintainer-edit"), ("--dry-run", "--dry-run"),
)
_GH_PR_COMMENT_VALUE: Final = _aliases(("-b", "--body"), ("-F", "--body-file"), ("-R", "--repo"))
_GH_PR_COMMENT_BOOL: Final = _aliases(("--edit-last", "--edit-last"), ("--create-if-none", "--create-if-none"),
                                      ("--yes", "--yes"))
_GH_API_VALUE: Final = _aliases(
    ("-X", "--method"), ("-f", "--raw-field"), ("-F", "--field"), ("-H", "--header"), ("--input", "--input"),
    ("-q", "--jq"), ("-t", "--template"), ("--cache", "--cache"), ("-p", "--preview"), ("--hostname", "--hostname"),
)
_GH_API_BOOL: Final = _aliases(("-i", "--include"), ("--paginate", "--paginate"), ("--silent", "--silent"),
                               ("--verbose", "--verbose"), ("--slurp", "--slurp"))
_GH_API_BODY: Final = frozenset({"--raw-field", "--field", "--input"})
_MERGE_ENDPOINT: Final = re.compile(r"(?:^|/)(?:merge|merges|auto-merge)(?:$|[/?])", re.IGNORECASE)
# A comment line that is a command to a bot (`/merge`, `@bot merge`, `bors r+`).
_BOT_COMMAND_LINE: Final = re.compile(r"^\W*(?:[/!]|@\S+\s+\S|bors\b)|\b(?:merge|automerge|squash|rebase)\b",
                               re.IGNORECASE)
_PR_NUMBER: Final = re.compile(r"^#?([1-9][0-9]{0,9})$")
_REPO_NAME: Final = re.compile(r"^(?:([A-Za-z0-9.-]+)/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
_DEFAULT_HOST: Final = "github.com"

# MCP tools that write to a forge, by the verbs in their names.
_MCP_FORGE_WRITE: Final = re.compile(
    r"merge|push|delete|fork|create_pull_request|update_pull_request|create_or_update_file|create_branch|"
    r"comment|update_issue|review|close|reopen|label|"
    r"create_ref|update_ref|"
    r"create_repository|update_repository", re.IGNORECASE)

# An HTTP client writing to a forge API without gh: the cheap, common shape only.
_HTTP_CLIENTS: Final = frozenset({"curl", "wget", "http", "https", "xh"})
# Shells that take a command in a form this gate cannot read (`-EncodedCommand`).
_WINDOWS_SHELLS: Final = frozenset({"powershell", "pwsh", "cmd"})
_POWERSHELL_PLAIN_OPTIONS: Final = frozenset({"-noprofile", "-nologo", "-noninteractive", "-nop", "-noni"})
_POWERSHELL_VALUE_OPTIONS: Final = frozenset({"-executionpolicy", "-ep", "-ex"})
_SCRIPT_SUFFIX: Final = re.compile(r"\.(?:ps1|bat|cmd)$", re.IGNORECASE)
# Programs that make links (`ln -s .git g`, `mklink /J g .git`, PowerShell `New-Item -ItemType Junction`).
_LINKERS: Final = frozenset({"ln", "mklink", "new-item", "ni", "cp", "mv", "install", "rsync", "tar", "unzip"})
# Programs that only read the files they name.
# `tree` (`-o` writes) and `rg` (`--pre` runs a program) are not on it.
# Programs that cannot run a command or write a file from their arguments or
# environment. Pagers, `find`, `tree`, `rg`, `sed`, `awk`, `xargs`, `sort` and
# anything with an output-file or preprocessor option are not on it.
_READERS: Final = frozenset({"cat", "head", "tail", "ls", "stat", "wc", "grep", "egrep", "fgrep"})
# A variable that makes a reader (or a pager it starts) run something, anywhere on the line.
_READER_ENV: Final = re.compile(r"\b(?:LESS\w*|PAGER|GIT_PAGER|MANPAGER|MORE|GREP_\w*|LS_\w*)\b")
_FORGE_API_HOST: Final = re.compile(r"api\.github\.com|/api/v3/|/api/graphql", re.IGNORECASE)
_WRITE_METHOD: Final = re.compile(r"\b(?:PUT|POST|PATCH|DELETE)\b|--data|(?:^|\s)-d\b|--json|--form", re.IGNORECASE)

# A forge credential named or read: a token variable, gh's host file, git's credential store.
_CREDENTIAL: Final = re.compile(
    r"\b(?:GH_TOKEN|GITHUB_TOKEN|GH_ENTERPRISE_TOKEN|GITHUB_ENTERPRISE_TOKEN)\b|gh/hosts\.yml|\.git-credentials",
    re.IGNORECASE)

# Files git or gh read as configuration (global, XDG, submodules, gh's own).
_FORGE_CONFIG_FILES: Final = frozenset({".gitconfig", ".gitmodules", ".git-credentials", ".gitattributes"})
_FORGE_CONFIG_SUFFIXES: Final = ("git/config", "git/attributes", "gh/config.yml", "gh/hosts.yml",
                                  "github cli/config.yml", "github cli/hosts.yml", "etc/gitconfig",
                                  "git/credentials", ".ssh/config")
# An 8.3 short name of a protected entry: `GIT~1` (.git), `GITCON~1` (.gitconfig),
# `GITMOD~1` (.gitmodules), `GIT-CR~1`, `GITATT~1`, `GITHUB~1` (gh's `GitHub CLI`).
_SHORT_GIT: Final = re.compile(r"^\.?git[^~/]{0,4}~[0-9]+$")
# A store path split to dodge a token match (`'runtime/pr_' + 'delivery'`), or written whole.
_STORE_PATH: Final = re.compile(r"runtime/+pr_(?:delivery|['\"])", re.IGNORECASE)

# The grant's command and store, as tokens.
_GRANT_GROUP: Final = "capability-policy"
_GRANT_COMMAND: Final = "pr-delivery"
_STORE_GLOB: Final = frozenset("*?[{")
_STORE_DIR: Final = pr_delivery.STORE_DIRNAME

_BLOCK_SUFFIX: Final = "A blocked call did not run."


class _Context:
    """What one classification reads besides the command: the grant's prefix and the bot's PRs."""

    def __init__(self, prefix: str, opened: frozenset[tuple[str, int]]) -> None:
        self.prefix = prefix
        self.opened = opened
        self.pr_head = ""
        self.pr_creates = 0
        self.segments = 0
        self.line = ""


def nobody_can_answer(session_id: object) -> bool:
    """This gate's own unattended predicate: wider than the ask rules', because cron is held here."""
    if session_is_delegated(session_id):
        return True
    if str(os.environ.get(SINGLE_QUERY_SESSION_ENV, "") or "").strip().lower() in _TRUTHY:
        return True
    return session_platform(session_id) in UNATTENDED_PLATFORMS


def _delegated(session_id: object) -> bool:
    return session_is_delegated(session_id) or session_platform(session_id) == "subagent"


def _tokens(command: str) -> list[str]:
    """Shell-aware tokens, `#` included as an ordinary character; `[]` when it will not tokenize."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return []


def _segments(tokens: list[str]) -> list[list[str]]:
    """Command segments, with redirections and their targets removed."""
    segments: list[list[str]] = [[]]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token in _SEPARATORS or (_OPERATOR_RUN.match(token) and not _REDIRECT.match(token)):
            # `punctuation_chars` joins a run of operators into one token
            # (`;(`, `&&(`, `);`): every such run ends a command.
            segments.append([])
            continue
        if _REDIRECT.match(token):
            if segments[-1] and segments[-1][-1].isdigit():
                segments[-1].pop()
            index += 1  # the redirection's target
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def _worst(classes: list[str]) -> str:
    return min(classes, key=_SEVERITY.index) if classes else LOCAL


def classify_command(command: object, *, prefix: str, opened: frozenset[tuple[str, int]] = frozenset()) -> str:
    """The forge class of one command line. Pure; reads no file."""
    context = _Context(prefix, opened)
    result = _classify(command, context, 0)
    if result == OPEN_PR and (context.pr_creates != 1 or context.segments != 1):
        # One PR, as a command of its own: nothing else in the line can print
        # into its output, and a loop cannot open many.
        return UNCLASSIFIED
    return result


def _classify(command: object, context: _Context, depth: int) -> str:
    if not isinstance(command, str) or not command.strip():
        return LOCAL
    if depth > _MAX_DEPTH:
        return UNCLASSIFIED
    command = _join_continuations(command)
    mentions_forge = _FORGE_WORD.search(command.replace("\\", "/")) is not None
    if mentions_forge and _command_word_is_a_windows_path(command):
        return UNCLASSIFIED  # the program run is named by a Windows path, which the POSIX lexer would misread
    if _CREDENTIAL.search(command):
        return UNCLASSIFIED  # printing a forge credential takes the next step outside this gate
    if mentions_forge and ("`" in command or "$(" in command or "<(" in command or ">(" in command):
        return UNCLASSIFIED
    lines = command.splitlines()
    if len(lines) > 1 and "<<" in command and mentions_forge:
        # A heredoc's body is lines too, and its extent is not tracked here.
        return UNCLASSIFIED
    whole = _tokens(command)
    if not whole:
        return UNCLASSIFIED if mentions_forge else LOCAL
    if mentions_forge and any(token.startswith("#") for token in whole):
        return UNCLASSIFIED  # a comment: what bash drops and what this reads must not differ
    if _defines_forge_function(whole):
        return UNCLASSIFIED
    for index, token in enumerate(whole[:-1]):
        # A here-string or redirection hands its target to the program as input.
        if _REDIRECT.match(token) and (_FORGE_WORD.search(whole[index + 1]) or _configures_forge(whole[index + 1])):
            return UNCLASSIFIED
    segments = _segments(whole)
    if depth == 0:
        context.segments = len(segments) if len(lines) <= 1 else len(segments) + len(lines)
        context.line = command
    classes = [_classify_segment(segment, context, depth) for segment in segments]
    # The per-line pass catches a push on its own line, which `shlex` reads as
    # more arguments of the line before; a line that does not tokenize alone
    # is inside a quoted string the whole pass already read.
    if len(lines) > 1:
        for line in lines:
            classes.extend(_classify_segment(segment, context, depth) for segment in _segments(_tokens(line)))
    return _worst(classes)


def _command_word_is_a_windows_path(command: str) -> bool:
    """Whether some segment's command word, as written, holds a backslash before a letter or digit.

    Only the command word names what runs, so only it is read raw. A
    backslash inside an argument (`--format='%h\\t%s'`, `-m 'fix\\nbody'`) is
    read by Git Bash exactly as the POSIX lexer reads it, and is not refused.
    """
    lexer = shlex.shlex(command, posix=False, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        raw = list(lexer)
    except ValueError:
        return True
    segments: list[list[str]] = [[]]
    for token in raw:
        if token in _SEPARATORS or (_OPERATOR_RUN.match(token) and not _REDIRECT.match(token)):
            segments.append([])
        else:
            segments[-1].append(token)
    return any(_WINDOWS_PATH_BACKSLASH.search(word) for word in map(_raw_command_word, segments) if word)


def _raw_command_word(segment: list[str]) -> str:
    """The token that names what runs, found past assignments and wrappers with `_unwrap`'s option table."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if _ASSIGNMENT.match(token):
            index += 1
            continue
        name = _basename(token.strip("'\"")).lower()
        if name not in _WRAPPERS:
            return token
        index += 1
        while index < len(segment) and segment[index].startswith("-") and segment[index] != "-":
            option = segment[index].split("=", 1)[0]
            index += 2 if option in _WRAPPERS[name] and "=" not in segment[index] else 1
        index += _WRAPPER_POSITIONALS.get(name, 0)
    return ""


def _runs_only_a_script(name: str, args: list[str]) -> bool:
    """`powershell -NoProfile -File x.ps1 ...`, `pwsh x.ps1`, `cmd /c x.bat`: a script file and nothing else."""
    if name == "cmd":
        return len(args) >= 2 and args[0].lower() == "/c" and bool(_SCRIPT_SUFFIX.search(args[1]))
    index = 0
    while index < len(args):
        option = args[index].lower()
        if option in _POWERSHELL_PLAIN_OPTIONS:
            index += 1
        elif option in _POWERSHELL_VALUE_OPTIONS:
            index += 2
        elif option in ("-file", "-f"):
            return index + 1 < len(args) and bool(_SCRIPT_SUFFIX.search(args[index + 1]))
        else:
            return not option.startswith("-") and bool(_SCRIPT_SUFFIX.search(args[index]))
    return False


def _plain_read(name: str, assignments: list[str], line: str) -> bool:
    """A reader on `_READERS` with no assignment in its segment and no reader variable on the line.

    It earns exactly one exception: a protected path it names is neither the
    protected-path refusal's business nor a forge word for the fallback.
    Every other check runs on it as on any program.
    """
    return name in _READERS and not assignments and not _READER_ENV.search(line)


def _names_forge_config(word: str) -> bool:
    """A command argument naming `.git` itself, a path under it, or a git or gh config file."""
    value = word.split("=", 1)[-1] if word.startswith("-") else word
    return bool(value) and _configures_forge(value)


def _join_continuations(command: str) -> str:
    """Remove backslash-newlines, as bash does before it reads a word (`g\\<newline>it` is `git`)."""
    return command.replace("\\\r\n", "").replace("\\\n", "")


def _defines_forge_function(tokens: list[str]) -> bool:
    """`git() {...}` or `gh ()`: every later git command in a persistent shell would be that function."""
    for index, token in enumerate(tokens[:-1]):
        if _FORGE_CLI.match(_basename(token).lower()) and tokens[index + 1].startswith("("):
            return True
    return False


def _basename(token: str) -> str:
    """The program a command word names: its last path part, without a Windows `.exe`/`.cmd`/`.bat`/`.com`."""
    name = token.replace("\\", "/").rsplit("/", 1)[-1]
    return _WINDOWS_EXECUTABLE.sub("", name)


def _split_assignments(words: list[str]) -> tuple[list[str], list[str]]:
    names: list[str] = []
    index = 0
    while index < len(words):
        match = _ASSIGNMENT.match(words[index])
        if match is None:
            break
        names.append(match.group(1))
        index += 1
    return names, words[index:]


def _unwrap(segment: list[str]) -> tuple[list[str], list[str]] | None:
    """(assignment names, the segment from its real command on), or None when a wrapper hides it."""
    names, words = _split_assignments(segment)
    while words and _basename(words[0]) in _WRAPPERS:
        name = _basename(words[0])
        value_options = _WRAPPERS[name]
        index = 1
        while index < len(words) and words[index].startswith("-") and words[index] != "-":
            option = words[index].split("=", 1)[0]
            if option in _UNREADABLE_WRAPPER_OPTIONS:
                return None
            index += 2 if option in value_options and "=" not in words[index] else 1
        index += _WRAPPER_POSITIONALS.get(name, 0)
        more, words = _split_assignments(words[index:])
        names.extend(more)
    return names, words


def _shell_payload(words: list[str]) -> str | None:
    """The command string of `sh -c '<string>'`, or None when the shell takes no `-c`."""
    index = 1
    has_c = False
    while index < len(words) and words[index].startswith("-"):
        if not words[index].startswith("--") and "c" in words[index][1:]:
            has_c = True
        index += 1
    if has_c and index < len(words):
        return words[index]
    return None


def _nested(words: list[str], context: _Context, depth: int) -> str:
    """A command handed on as words: read both as the shell re-joins them and as argv."""
    return _worst([_classify(" ".join(words), context, depth + 1), _classify(shlex.join(words), context, depth + 1)])


def _classify_segment(segment: list[str], context: _Context, depth: int) -> str:
    text = " ".join(segment)
    forge_text = _FORGE_WORD.search(text) is not None
    unwrapped = _unwrap(segment)
    if unwrapped is None:
        return UNCLASSIFIED if forge_text else LOCAL
    names, words = unwrapped
    if any(_FORGE_ENV.match(name) for name in names) or any(_POWERSHELL_ENV.match(word) for word in segment):
        return UNCLASSIFIED
    if not words:
        return LOCAL
    head = words[0]
    name = _basename(head).lower()
    if name == "setx" and len(words) > 1 and _FORGE_ENV.match(words[1]):
        return UNCLASSIFIED  # cmd.exe's `setx NAME value`, with no `=`
    if name in _DECLARERS:
        declared = [_ASSIGNMENT.match(word) for word in words[1:]]
        if any(match is not None and _FORGE_ENV.match(match.group(1)) for match in declared):
            return UNCLASSIFIED
    if name in _DEFINERS and forge_text:
        return UNCLASSIFIED
    if any(mark in head for mark in _HIDING_MARKS) and _FORGE_VERB.search(text):
        return UNCLASSIFIED
    if _FORGE_CLI.match(name):
        carried = (any("$" in word or _EXEC_URL.search(word) for word in words[1:])
                   or any(word.split("=", 1)[0] in _EXEC_CARRIERS for word in words[1:]))
        if carried:
            return UNCLASSIFIED
        return _classify_git(words[1:], context, depth) if name == "git" else _classify_gh(words[1:], context)
    if name in _WINDOWS_SHELLS:
        # Decided by the executable, never by the flag spelling: PowerShell
        # accepts any unambiguous prefix of `-EncodedCommand`, and cmd runs
        # `/c`, `/k` and `/r`. Only a plain script file stays a script residual.
        return LOCAL if _runs_only_a_script(name, words[1:]) and not forge_text else UNCLASSIFIED
    if name in _LINKERS and any(_names_forge_config(word) for word in words[1:]):
        return UNCLASSIFIED  # a link to `.git` or a git config lets a later plain write land there
    reader = _plain_read(name, names, context.line)
    if not reader and any(_names_forge_config(word) for word in words[1:]) and not _FORGE_CLI.match(name):
        return UNCLASSIFIED  # a shell write into `.git/` or a git or gh config file
    if name in _SHELLS:
        payload = _shell_payload(words)
        if payload is not None:
            return UNCLASSIFIED if "$" in payload else _classify(payload, context, depth + 1)
        if not any(not word.startswith("-") for word in words[1:]) or "-s" in words[1:]:
            return UNCLASSIFIED  # a shell reading its commands from stdin: a pipe or a redirection this gate cannot read
    elif name == "eval":
        return UNCLASSIFIED if any("$" in word for word in words[1:]) else _nested(words[1:], context, depth)
    if name in _HTTP_CLIENTS and _FORGE_API_HOST.search(text) and _WRITE_METHOD.search(text):
        return OTHER_PR_OR_REPO  # a forge API write that skips gh
    if reader:
        # The one exception: protected paths a plain reader names are not forge words. The rest of
        # its text is judged by the fallback exactly as for any other program.
        text = " ".join(word for word in words if not _names_forge_config(word))
        forge_text = _FORGE_WORD.search(text) is not None
    if forge_text and _FORGE_VERB.search(text):
        return UNCLASSIFIED
    return LOCAL


def _classify_git(args: list[str], context: _Context, depth: int) -> str:
    index = 0
    relocated = False
    while index < len(args) and args[index].startswith("-"):
        option, has_value, _value = args[index].partition("=")
        if option in _GIT_GLOBAL_VALUE:
            relocated = relocated or option in ("-C", "--git-dir", "--work-tree")
            if not has_value:
                index += 1
        elif option not in _GIT_GLOBAL_BOOL:
            # `-c`, `--config-env`, `--exec-path` and anything unknown can
            # reprogram what the subcommand runs or where it pushes.
            return UNCLASSIFIED
        index += 1
    if index >= len(args):
        return LOCAL
    subcommand, rest = args[index], args[index + 1:]
    if subcommand == "push":
        # Another checkout's `origin` is another repository: push from the work tree itself.
        return UNCLASSIFIED if relocated else _classify_push(rest, context)
    if subcommand == "config":
        return _classify_git_config(rest)
    if subcommand == "remote":
        return LOCAL if (rest[0] if rest else "") in _GIT_REMOTE_READS else UNCLASSIFIED
    if subcommand == "submodule" and "foreach" in rest:
        return _nested(rest[rest.index("foreach") + 1:], context, depth)
    if subcommand == "bisect" and rest[:1] == ["run"]:
        return _nested(rest[1:], context, depth)
    if subcommand == "rebase":
        return _classify_rebase(rest, context, depth)
    if subcommand == "grep" and any(word.startswith("-O") for word in rest):
        return UNCLASSIFIED
    if subcommand == "clone" and any(word.startswith("-u") for word in rest):
        return UNCLASSIFIED
    return LOCAL if subcommand in _GIT_LOCAL else UNCLASSIFIED


def _classify_git_config(rest: list[str]) -> str:
    if any(word in _GIT_CONFIG_READS for word in rest):
        return LOCAL
    keys = [word for word in rest if not word.startswith("-") and word != "set"]
    if keys and keys[0].lower() in _GIT_CONFIG_SAFE_KEYS:
        return LOCAL
    # A write to any other key can run a program or redirect a remote
    # (`core.sshCommand`, `core.hooksPath`, `url.*.pushInsteadOf`, `alias.*`).
    return UNCLASSIFIED


def _classify_rebase(rest: list[str], context: _Context, depth: int) -> str:
    classes = [LOCAL]
    for position, token in enumerate(rest):
        if token in ("-x", "--exec"):
            nested = rest[position + 1] if position + 1 < len(rest) else ""
            classes.append(_classify(nested, context, depth + 1) if nested else UNCLASSIFIED)
        elif token.startswith("--exec="):
            classes.append(_classify(token.split("=", 1)[1], context, depth + 1))
        elif token.startswith("-x") and len(token) > 2:
            classes.append(_classify(token[2:], context, depth + 1))
    return _worst(classes)


def _classify_push(args: list[str], context: _Context) -> str:
    positionals: list[str] = []
    repository = ""
    wide = False
    dry_run = False
    index = 0
    options_ended = False
    while index < len(args):
        token = args[index]
        index += 1
        if options_ended or not token.startswith("-") or token == "-":
            positionals.append(token)
            continue
        if token == "--":
            options_ended = True
            continue
        if token.startswith("--"):
            option, has_value, value = token.partition("=")
            if option in _FORCE_LONG:
                return FORCE_PUSH
            if option == "--push-option":
                return OTHER_PR_OR_REPO  # a push option can open or merge a request on the forge
            if option in _WIDE_LONG:
                wide = True
            elif option == "--dry-run":
                if has_value:
                    return UNCLASSIFIED
                dry_run = True
            elif option == "--repo":
                if not has_value:
                    value = args[index] if index < len(args) else ""
                    index += 1
                repository = value
            elif option in _PUSH_LONG_OPTIONAL_VALUE:
                if option == "--recurse-submodules" and value not in ("check", "no"):
                    wide = True
            elif option not in _PUSH_LONG_BOOL:
                return UNCLASSIFIED
            continue
        for letter in token[1:]:
            if letter in "fd":
                return FORCE_PUSH
            if letter == "o":
                return OTHER_PR_OR_REPO
            if letter == "n":
                dry_run = True
            elif letter not in "uqv46":
                return UNCLASSIFIED
    if dry_run:
        return LOCAL
    if wide:
        return PUSH_OUTSIDE
    if not repository and positionals:
        repository, positionals = positionals[0], positionals[1:]
    if not repository or not positionals:
        return UNQUALIFIED
    refspecs = [_classify_refspec(spec, context.prefix) for spec in positionals]
    if repository != _PUSH_REMOTE:
        refspecs.append(PUSH_OUTSIDE)
    return _worst(refspecs)


def _classify_refspec(spec: str, prefix: str) -> str:
    if spec.startswith("+"):
        return FORCE_PUSH
    source, colon, destination = spec.partition(":")
    if not colon:
        if source in ("HEAD", "@") or _NOT_LITERAL.search(source):
            return UNQUALIFIED
        # A bare name may be remapped by `remote.<name>.push`, so even a name
        # under the prefix is not a named destination.
        return UNQUALIFIED if _under_prefix(source, prefix) else PUSH_OUTSIDE
    if not source:
        return FORCE_PUSH if destination else PUSH_OUTSIDE  # `:dst` deletes; `:` pushes every matching branch
    if not destination or _NOT_LITERAL.search(destination) or ":" in destination:
        return PUSH_OUTSIDE if "*" in destination else UNQUALIFIED
    return PUSH_BOT_BRANCH if _under_prefix(destination, prefix) else PUSH_OUTSIDE


def _under_prefix(ref: str, prefix: str) -> bool:
    if ref.startswith("refs/"):
        if not ref.startswith("refs/heads/"):
            return False
        ref = ref[len("refs/heads/"):]
    return ref.startswith(prefix) and len(ref) > len(prefix) and not _NOT_LITERAL.search(ref)


def _options(args: list[str], value_options: Mapping[str, str], bool_options: Mapping[str, str]):
    """(options by canonical name, last value wins as in gh; positionals; known)."""
    options: dict[str, str] = {}
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        index += 1
        if not token.startswith("-") or token == "-":
            positionals.append(token)
            continue
        option, has_value, value = token.partition("=")
        if option in value_options:
            if not has_value:
                # pflag hands the next argument to a value flag even when it starts with "-".
                value = args[index] if index < len(args) else ""
                index += 1
            options[value_options[option]] = value
        elif option in bool_options and not has_value:
            options[bool_options[option]] = ""
        else:
            return options, positionals, False
    return options, positionals, True


def _first_verb(args: list[str]) -> tuple[str, list[str]]:
    """A gh group's verb, skipping a leading `-R <repo>`; and the arguments around it."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in ("-R", "--repo") else 1
    if index >= len(args):
        return "", args
    return args[index], args[:index] + args[index + 1:]


def _classify_gh(args: list[str], context: _Context) -> str:
    if not args or args in (["--help"], ["-h"], ["help"]) or args[0] in _GH_READ_ONLY_GROUPS:
        return LOCAL
    group, rest = args[0], args[1:]
    if rest in (["--help"], ["-h"]):
        return LOCAL
    if group == "auth":
        # A token or a widened scope takes the next step outside this gate.
        return LOCAL if rest == ["status"] else UNCLASSIFIED
    if group == "api":
        return _classify_gh_api(rest)
    verb, verb_args = _first_verb(rest)
    if verb_args in (["--help"], ["-h"]):
        return LOCAL
    if group == "pr":
        return _classify_gh_pr(verb, verb_args, context)
    if group == "repo" and verb == "set-default":
        # It picks the repository every later gh command acts on, like `--repo`.
        return LOCAL if verb_args in (["--view"], ["-v"]) else UNCLASSIFIED
    if group in _GH_REPO_GROUPS:
        return LOCAL if not verb or verb in _GH_READ_VERBS else OTHER_PR_OR_REPO
    if group in _GH_NOT_GOVERNED_GROUPS:
        if not verb or verb in _GH_READ_VERBS:
            return LOCAL
        return OTHER_PR_OR_REPO if verb in _GH_GOVERNED_VERBS.get(group, ()) else NOT_GOVERNED
    if group == "config" and verb in ("get", "list"):
        return LOCAL
    return UNCLASSIFIED


def _classify_gh_pr(verb: str, args: list[str], context: _Context) -> str:
    if not verb or verb in _GH_READ_VERBS:
        return LOCAL
    if verb == "merge":
        return FORGE_MERGE
    if verb in _GH_PR_MUTATIONS:
        return OTHER_PR_OR_REPO
    if verb == "create":
        options, positionals, known = _options(args, _GH_PR_CREATE_VALUE, _GH_PR_CREATE_BOOL)
        if not known or positionals or "--body-file" in options:
            return UNCLASSIFIED  # a body file is read off disk into a public PR
        if "--dry-run" in options:
            return LOCAL
        if options.keys() & {"--repo", "--label", "--milestone", "--project"}:
            # Another repository; a label, milestone or project can be an auto-merge rule's condition.
            return OTHER_PR_OR_REPO
        if _asks_a_bot(options.get("--title", "") + "\n" + options.get("--body", "")):
            return FORGE_MERGE
        head = options.get("--head", "")
        if not head:
            return UNQUALIFIED
        if ":" in head:
            return OTHER_PR_OR_REPO
        if not _under_prefix(head, context.prefix):
            return PUSH_OUTSIDE
        context.pr_head = head
        context.pr_creates += 1
        return OPEN_PR
    if verb == "comment":
        options, positionals, known = _options(args, _GH_PR_COMMENT_VALUE, _GH_PR_COMMENT_BOOL)
        if not known or len(positionals) > 1 or "--body-file" in options:
            return UNCLASSIFIED
        if _asks_a_bot(options.get("--body", "")):
            return FORGE_MERGE
        pr = _selected_pr(positionals[0] if positionals else "", options.get("--repo", ""))
        if pr is None:
            return UNQUALIFIED
        return COMMENT_OWN_PR if pr in context.opened else OTHER_PR_OR_REPO
    return UNCLASSIFIED


def _asks_a_bot(text: str) -> bool:
    """Best effort: a line that reads as a command to a merge bot, or names merging at all."""
    return any(_BOT_COMMAND_LINE.search(line) for line in text.splitlines())


def _selected_pr(selector: str, repository: str) -> tuple[str, int] | None:
    """(`host/owner/name`, number) a `gh pr comment` names unambiguously, else None."""
    by_url = pr_delivery.parse_pr_url(selector)
    if by_url is not None:
        return None if repository else by_url
    number = _PR_NUMBER.match(selector)
    repo = _REPO_NAME.match(repository)
    if number is None or repo is None:
        return None
    host, owner, name = repo.groups()
    return f"{host or _DEFAULT_HOST}/{owner}/{name}".lower(), int(number.group(1))


def _classify_gh_api(args: list[str]) -> str:
    options, positionals, known = _options(args, _GH_API_VALUE, _GH_API_BOOL)
    if not known or len(positionals) != 1:
        return UNCLASSIFIED
    endpoint = positionals[0].split("?", 1)[0]
    if endpoint.strip("/").lower() == "graphql":
        return LOCAL if not options.keys() & (_GH_API_BODY | {"--method"}) else OTHER_PR_OR_REPO
    method = options.get("--method", "").upper() or ("POST" if _GH_API_BODY & options.keys() else "GET")
    if method == "GET":
        return LOCAL
    return FORGE_MERGE if _MERGE_ENDPOINT.search(endpoint) else OTHER_PR_OR_REPO


# Directives -------------------------------------------------------------------


def _text_arg(tool_input: object, key: str) -> str:
    value = tool_input.get(key) if isinstance(tool_input, Mapping) else None
    return value if isinstance(value, str) else ""


def _process_data(tool_input: object) -> str | None:
    """The stdin a `process` call sends to a background process, else None.

    `write` and `submit` send it; any other action that carries `data` is
    read the same way rather than trusted to ignore it.
    """
    data = _text_arg(tool_input, "data")
    if _text_arg(tool_input, "action") in ("write", "submit") or data:
        return data
    return None


def _names_store(token: str) -> bool:
    lowered = token.lower()
    if "pr_delivery/" in lowered or lowered.endswith("/pr_delivery") or _STORE_PATH.search(lowered):
        return True
    # A glob that the shell would expand to the store's directory (`pr_deliver?/`, `pr_*`).
    return any(any(mark in part for mark in _STORE_GLOB) and fnmatch.fnmatchcase(_STORE_DIR, part)
               for part in lowered.split("/"))


def _names_grant_change(command: str, depth: int = 0) -> bool:
    """Whether a command line would change the grant or touch its store."""
    command = _join_continuations(command)
    folded = command.replace("\\", "/").lower()
    if "pr_delivery/" in folded or _STORE_PATH.search(folded):
        return True  # a store path in any spelling, a Windows one included, which the lexer would unescape
    tokens = _tokens(command)
    if not tokens:
        lowered = command.lower()
        return _GRANT_COMMAND in lowered or "pr_delivery" in lowered
    if any(_names_store(token) for token in tokens):  # redirection targets included
        return True
    for segment in _segments(tokens):
        lowered = [token.lower() for token in segment]
        if _GRANT_GROUP in lowered and (_GRANT_COMMAND in lowered or any("$" in t or "`" in t for t in lowered)):
            return True
        if depth < _MAX_DEPTH and any(" " in token and _names_grant_change(token, depth + 1) for token in segment):
            return True
    return "`" in command and _GRANT_GROUP in command.lower()


def grant_change_directive(*, tool_name: object, tool_input: object) -> dict[str, str] | None:
    """Refuse, in every session, a tool call that would turn the grant on or off."""
    tool = str(tool_name or "")
    if tool == TERMINAL_TOOL:
        named = _names_grant_change(_text_arg(tool_input, "command"))
    elif tool == PROCESS_TOOL:
        data = _process_data(tool_input)
        named = data is not None and _names_grant_change(data)
    elif tool == CODE_TOOL:
        code = _text_arg(tool_input, "code").lower()
        named = _STORE_PATH.search(code.replace("\\", "/")) is not None or "pr_delivery/" in code or _GRANT_GROUP in code
    else:
        return None
    if not named:
        return None
    return {
        "action": "block",
        "message": (
            "[OMH PR delivery] Only the person turns the PR delivery grant on or off, at their own terminal; "
            f"a bot never does. Tell them the exact command: `{pr_delivery.TURN_ON_COMMAND}` or "
            f"`{pr_delivery.TURN_OFF_COMMAND}`. Read the grant's state with the omh_status tool "
            f"(`pr_delivery_grant`). {_BLOCK_SUFFIX}"
        ),
    }


def _resolved(target: str, task_id: object) -> str:
    """The real path a file tool would write: relative to the session's workspace, every link followed."""
    base = _workspace_root(task_id) or os.getcwd()
    try:
        return os.path.realpath(os.path.join(base, os.path.expanduser(target)))
    except (OSError, ValueError):
        return target


def _tool_class(tool: str, tool_input: object, prefix: str, opened: frozenset[tuple[str, int]],
                task_id: object = None) -> str:
    if tool == TERMINAL_TOOL:
        return classify_command(_text_arg(tool_input, "command"), prefix=prefix, opened=opened)
    if tool == PROCESS_TOOL:
        data = _process_data(tool_input)
        if data is None:
            return LOCAL
        if data.rstrip("\r\n").endswith("\\"):
            return UNCLASSIFIED  # a line continuation joins this send with the next one
        if _text_arg(tool_input, "action") != "submit" and data and not data.endswith("\n"):
            # A partial line is joined with the next write by the program
            # reading it, so no single write can be judged.
            return UNCLASSIFIED
        return classify_command(data, prefix=prefix, opened=opened)
    if tool == CODE_TOOL:
        code = _text_arg(tool_input, "code")
        return UNCLASSIFIED if _FORGE_WORD.search(code) and _FORGE_VERB.search(code) else LOCAL
    if tool in FILE_TOOLS:
        # A file under `.git/` (a hook, the config) runs on the next git command. Read both as
        # written and resolved: a symlinked or junctioned parent (`g -> .git`) must not hide it.
        targets = _edit_targets(tool, dict(tool_input) if isinstance(tool_input, Mapping) else {})
        return UNCLASSIFIED if any(_configures_forge(target) or _configures_forge(_resolved(target, task_id))
                                   for target in targets) else LOCAL
    lowered = tool.lower()
    if (lowered.startswith("mcp") or "github" in lowered or "gitlab" in lowered) and _MCP_FORGE_WRITE.search(tool):
        return OTHER_PR_OR_REPO
    return LOCAL


def _configures_forge(target: str) -> bool:
    """A file that git or gh reads as configuration or runs as a hook.

    Case-folded (APFS and NTFS ignore case), with Windows spellings folded to
    the name the file system opens: backslashes, a drive letter, trailing dots
    and spaces (`.git.` is `.git`), an NTFS stream suffix (`.git::$DATA`), and
    the 8.3 short name `GIT~1`.
    """
    lowered = target.replace("\\", "/").casefold()
    parts = [_windows_part(part) for part in lowered.split("/")]
    if any(part == ".git" or _SHORT_GIT.match(part) for part in parts) or parts[-1] in _FORGE_CONFIG_FILES:
        return True
    return "/".join(parts).endswith(_FORGE_CONFIG_SUFFIXES)


def _windows_part(part: str) -> str:
    if len(part) == 2 and part.endswith(":"):
        return part  # a drive letter
    return part.split(":", 1)[0].rstrip(". ")


def delivery_directive(
    *, tool_name: object, tool_input: object, session_id: str, omh_home: str, hermes_home: str,
    task_id: object = None,
) -> dict[str, str] | None:
    """The block for a forge command an unattended session may not run, else None."""
    tool = str(tool_name or "")
    if not nobody_can_answer(session_id):
        return None
    grant = pr_delivery.read_grant(omh_home, hermes_home)
    prefix = pr_delivery.branch_prefix(grant)
    opened = pr_delivery.opened_prs(omh_home, hermes_home) if tool in (TERMINAL_TOOL, PROCESS_TOOL) else frozenset()
    forge_class = _tool_class(tool, tool_input, prefix, opened, task_id)
    if forge_class in (LOCAL, NOT_GOVERNED):
        return None
    delegated = _delegated(session_id)
    if forge_class in GRANT_COVERED and grant.get("state") == "on" and not delegated:
        if forge_class != OPEN_PR or pr_delivery.opened_count(omh_home, hermes_home, session_id) < 1:
            return None
        return {"action": "block", "message": _refusal(forge_class, grant, prefix, delegated, capped=True)}
    return {"action": "block", "message": _refusal(forge_class, grant, prefix, delegated)}


def _refusal(forge_class: str, grant: Mapping[str, object], prefix: str, delegated: bool, capped: bool = False) -> str:
    what = _DESCRIPTIONS.get(forge_class, "this command")
    lead = f"[OMH PR delivery] Nobody can answer a confirmation in this session, so OMH did not run {what}."
    if capped:
        detail = ("This run already opened a pull request; a second one is a person's decision. Report the first "
                  "PR and hand any further one to a person's turn.")
    elif forge_class in GRANT_COVERED and delegated:
        detail = ("A delegated child does not carry the PR delivery grant: return the prepared branch and "
                  "commits to the parent session, which pushes and opens the pull request.")
    elif forge_class in GRANT_COVERED:
        detail = ("This profile's PR delivery grant is off, so hand the push and the pull request to a person's "
                  f"turn with the prepared branch, commits and PR text. Only the person can turn the grant on, at "
                  f"their own terminal: `{pr_delivery.TURN_ON_COMMAND}`.")
    elif forge_class == UNQUALIFIED:
        detail = ("Name the destination explicitly: `git push origin HEAD:refs/heads/"
                  f"{prefix}<topic>`, `gh pr create --head {prefix}<topic>`, `gh pr comment <PR URL>`. The hook "
                  "cannot see which branch is checked out when the shell runs, so it does not guess.")
    elif forge_class == UNCLASSIFIED:
        detail = ("OMH cannot read what this command publishes. Run git and gh as plain commands of their own, "
                  "without a shell wrapper, eval, variable, alias, script, `-c` or GIT_/GH_ setting, and run "
                  "`gh pr create` alone; or hand the step to a person's turn.")
    else:
        detail = ("That is never run without a person, whatever the PR delivery grant says "
                  f"(state: {grant.get('state', 'off')}). Hand it to a person's turn with the evidence.")
    return f"{lead} {detail} {_BLOCK_SUFFIX}"


def observe_opened_pr(
    *, tool_name: object, tool_input: object, result: object, session_id: str, omh_home: str, hermes_home: str
) -> bool:
    """Record the PR a grant-allowed `gh pr create` printed. True when a record was written.

    Only a command that classifies as exactly one `gh pr create` and nothing
    else, so no other program in the line can print a URL into its output;
    only a zero exit; only a URL on the output's last line, which is where
    `gh pr create` prints it.
    """
    if str(tool_name or "") != TERMINAL_TOOL:
        return False
    grant = pr_delivery.read_grant(omh_home, hermes_home)
    if grant.get("state") != "on":
        return False
    command = _text_arg(tool_input, "command")
    if classify_command(command, prefix=pr_delivery.branch_prefix(grant)) != OPEN_PR:
        return False
    context = _Context(pr_delivery.branch_prefix(grant), frozenset())
    _ = _classify(command, context, 0)
    url = _last_output_line(result)
    if not url:
        return False
    return pr_delivery.append_opened_pr(omh_home, hermes_home, url=url, head_branch=context.pr_head,
                                        session_id=session_id)


def _last_output_line(result: object) -> str:
    if not isinstance(result, str) or not result:
        return ""
    try:
        parsed = json.loads(result)
    except ValueError:
        return ""
    if not isinstance(parsed, dict) or parsed.get("exit_code") != 0:
        return ""
    output = parsed.get("output")
    if not isinstance(output, str):
        return ""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    return lines[-1] if lines and pr_delivery.parse_pr_url(lines[-1]) is not None else ""
