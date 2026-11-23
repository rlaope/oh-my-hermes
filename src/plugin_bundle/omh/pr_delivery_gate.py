"""What an unattended run may publish to a forge, held at `pre_tool_call`.

The matrix (owner-approved, 2026-11-23; `docs/PR-DELIVERY-GRANT.md` states it
for people). Rows are session kinds as `session_attendance` can tell them;
columns are what a `terminal` command does on the forge.

* **Attended** (a person can answer a prompt): this gate has no opinion. The
  person is there and Hermes' own approvals apply.
* **Unattended** (a programmatic platform such as `webhook` or `api_server`,
  or a single-query `hermes chat -q` process):
  - grant-covered: a push whose every destination is spelled
    `<src>:refs/heads/<prefix>...` with no force; `gh pr create --head
    <prefix>...` without `--repo`; `gh pr comment <URL>` (or `<n> --repo
    <owner>/<name>`) on a PR this profile's gate recorded as opened. Allowed
    with the grant on; refused with a hand-off message when it is off.
  - always refused, whatever the grant says: any force push or remote ref
    deletion (`-f`, `--force`, `--force-with-lease`, `+refspec`, `--delete`,
    `:dst`, `--mirror`, `--prune`); a push to anything outside the prefix (the
    default branch, tags, `--all`, `HEAD:main`); a merge (`gh pr merge`, a
    `gh api` write to a merge endpoint); any other `gh pr` mutation, a PR or
    comment on a PR not recorded as the bot's, `gh pr create --repo`, and
    repository-level writes (`gh repo edit`, secrets, labels, releases, any
    `gh api` call that writes).
  - refused as unqualified, whatever the grant says: a push or PR that does
    not name its destination (`git push`, `git push origin HEAD`, `git push
    origin bot/x` -- a bare name can be remapped by `remote.<name>.push` --
    `gh pr create` without `--head`, `gh pr comment 12` without `--repo`). The
    hook cannot know the current branch at the moment the shell runs, so it
    does not guess.
  - refused as unclassified (fail closed): a command it cannot read (an
    unbalanced quote, a backquote, `env -S`), a git subcommand it does not
    know (an alias may be a push), a `gh` group it does not know, and any
    other program whose words name git or gh beside a forge verb (`xargs`,
    `python -c`, a heredoc fed to a shell); an `execute_code` call whose code
    names them too.
* **Delegated child**: unattended, and the grant is NOT inherited: the
  grant-covered columns are refused with a message to return the work to the
  parent session. A child's card names a session nobody started.
* **Cron turn**: indistinguishable from attended at this seam
  (`session_attendance`), so this gate has no opinion there. What bounds it
  instead is the skill text (`_UNATTENDED_GATE` and `github-event-ops`), the
  PR watch's fix-round cap, and Hermes' own `approvals.cron_mode` for the
  commands Hermes flags (a force push; Hermes flags no plain push and no `gh`
  verb).

Everywhere, attended or not: a command that would turn the grant on or off,
or that names its store, is refused. Only the person turns it on, at their
own terminal.

Classification is shell-aware tokenizing, the same `shlex` segments
`remote_wait_nudge` uses to anchor `git push`, then an explicit option table
per command. It is never a substring guess; where the table does not know a
token the answer is "unclassified", which refuses in an unattended session.
Only `git` and `gh` are recognized as forge CLIs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Final

from . import pr_delivery
from .hooks.nudge_budget import session_is_delegated
from .hooks.session_attendance import escalation_can_reach_a_person
from .remote_wait_nudge import _command_lines, _segments, _shell_tokens, _strip_env_assignments

TERMINAL_TOOL: Final = "terminal"
CODE_TOOL: Final = "execute_code"

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
ALWAYS_REFUSED: Final = frozenset({FORCE_PUSH, PUSH_OUTSIDE, FORGE_MERGE, OTHER_PR_OR_REPO, UNQUALIFIED, UNCLASSIFIED})
# Most severe first: a command's class is its worst segment's.
_SEVERITY: Final = (
    FORCE_PUSH, FORGE_MERGE, PUSH_OUTSIDE, OTHER_PR_OR_REPO, UNCLASSIFIED, UNQUALIFIED,
    OPEN_PR, COMMENT_OWN_PR, PUSH_BOT_BRANCH, NOT_GOVERNED, LOCAL,
)
_DESCRIPTIONS: Final[Mapping[str, str]] = {
    FORCE_PUSH: "a force push or a remote branch deletion",
    FORGE_MERGE: "a merge",
    PUSH_OUTSIDE: "a push to a branch outside the bot's branch prefix (the default branch, a tag, or every branch)",
    OTHER_PR_OR_REPO: "a change to a pull request this bot did not open, or to the repository itself",
    UNQUALIFIED: "a push or pull-request command that does not name its destination",
    UNCLASSIFIED: "a command whose forge effect OMH cannot read",
    PUSH_BOT_BRANCH: "a push of the bot's work branch",
    OPEN_PR: "opening a pull request",
    COMMENT_OWN_PR: "a comment on the bot's own pull request",
}

_MAX_DEPTH: Final = 3
_SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
# Transparent wrappers: the command after them is the command. Each maps to
# the options that take a separate value; a wrapper listed in
# `_WRAPPER_POSITIONALS` also takes that many positional arguments first.
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
# `env -S` splits its argument into a new command line: not read here.
_UNREADABLE_WRAPPER_OPTIONS: Final = frozenset({"-S", "--split-string"})

_FORGE_WORD: Final = re.compile(r"\b(?:git|gh)\b")
_FORGE_VERB: Final = re.compile(r"\b(?:push|merge|pr|api|repo|release|secret|variable|label|workflow|ruleset)\b")
_GRANT_STORE_WORD: Final = re.compile(r"pr_delivery")
_GRANT_COMMAND_WORD: Final = "pr-delivery"
_CODE_GRANT_WORD: Final = re.compile(r"pr[-_]delivery")

# git ------------------------------------------------------------------------
_GIT_GLOBAL_VALUE: Final = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--list-cmds"}
)
_GIT_GLOBAL_BOOL: Final = frozenset({
    "-p", "--paginate", "-P", "--no-pager", "--bare", "--no-replace-objects", "--literal-pathspecs",
    "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-optional-locks", "--no-advice",
    "--html-path", "--man-path", "--info-path", "--version", "--help", "-h", "--exec-path",
})
# Subcommands that change nothing on a remote. `push` is classified on its
# own; a few that run a nested command line are read through it; any name
# not here (an alias, `lfs`, `send-email`, `svn`) is unclassified.
_GIT_LOCAL: Final = frozenset({
    "add", "am", "annotate", "apply", "archive", "blame", "branch", "bundle", "cat-file", "check-attr",
    "check-ignore", "check-mailmap", "check-ref-format", "checkout", "cherry", "cherry-pick", "clean",
    "clone", "column", "commit", "commit-graph", "commit-tree", "config", "count-objects", "describe",
    "diff", "diff-files", "diff-index", "diff-tree", "difftool", "fetch", "for-each-ref", "format-patch",
    "fsck", "gc", "grep", "hash-object", "help", "init", "interpret-trailers", "log", "ls-files",
    "ls-remote", "ls-tree", "maintenance", "merge", "merge-base", "merge-file", "mergetool", "mktag",
    "mktree", "mv", "name-rev", "notes", "pack-refs", "prune", "pull", "range-diff", "read-tree", "reflog",
    "remote", "repack", "replace", "request-pull", "rerere", "reset", "restore", "rev-list", "rev-parse",
    "revert", "rm", "shortlog", "show", "show-branch", "show-ref", "sparse-checkout", "stash", "status",
    "stripspace", "switch", "symbolic-ref", "tag", "unpack-file", "update-index", "update-ref", "var",
    "verify-commit", "verify-pack", "verify-tag", "version", "whatchanged", "worktree", "write-tree",
})
_PUSH_LONG_BOOL: Final = frozenset({
    "--set-upstream", "--quiet", "--verbose", "--progress", "--no-progress", "--no-verify", "--verify",
    "--atomic", "--no-atomic", "--porcelain", "--thin", "--no-thin", "--ipv4", "--ipv6", "--no-signed",
    "--no-force-with-lease", "--no-recurse-submodules", "--no-follow-tags",
})
# Long options whose value may come as the next token.
_PUSH_LONG_VALUE: Final = frozenset({"--repo", "--push-option", "--receive-pack", "--exec"})
# Long options whose value may only come after `=`.
_PUSH_LONG_OPTIONAL_VALUE: Final = frozenset({"--signed", "--recurse-submodules"})
_FORCE_LONG: Final = frozenset({"--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune"})
_WIDE_LONG: Final = frozenset({"--all", "--branches", "--tags", "--follow-tags"})
_NOT_LITERAL: Final = re.compile(r"[$`*?\[\\~^\s]|\.\.|@\{")

# gh -------------------------------------------------------------------------
_GH_READ_ONLY_GROUPS: Final = frozenset({"--help", "-h", "--version", "help", "version", "completion", "status",
                                         "search", "browse", "auth"})
_GH_READ_VERBS: Final = frozenset({"view", "list", "status", "checks", "diff", "checkout", "get", "check",
                                   "download", "clone", "watch", "set-default"})
_GH_PR_MUTATIONS: Final = frozenset({"edit", "close", "reopen", "ready", "review", "lock", "unlock",
                                     "update-branch", "revert"})
# Repository-level groups: any verb outside the read verbs writes the repository.
_GH_REPO_GROUPS: Final = frozenset({"repo", "secret", "variable", "label", "workflow", "release", "ruleset",
                                    "cache", "deploy-key"})
# Mutations outside this grant's subject (issues, workflow runs): unchanged by this gate.
_GH_NOT_GOVERNED_GROUPS: Final = frozenset({"issue", "run"})
_GH_PR_CREATE_VALUE: Final = frozenset({"-t", "--title", "-b", "--body", "-F", "--body-file", "-B", "--base", "-H",
                                        "--head", "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p",
                                        "--project", "-r", "--reviewer", "-T", "--template", "-R", "--repo",
                                        "--recover"})
_GH_PR_CREATE_BOOL: Final = frozenset({"-d", "--draft", "-f", "--fill", "--fill-first", "--fill-verbose", "-w",
                                       "--web", "-e", "--editor", "--no-maintainer-edit", "--dry-run"})
_GH_PR_COMMENT_VALUE: Final = frozenset({"-b", "--body", "-F", "--body-file", "-R", "--repo"})
_GH_PR_COMMENT_BOOL: Final = frozenset({"-e", "--editor", "-w", "--web", "--edit-last", "--delete-last",
                                        "--create-if-none", "--yes"})
_GH_API_VALUE: Final = frozenset({"-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header",
                                  "--input", "-q", "--jq", "-t", "--template", "--cache", "-p", "--preview",
                                  "--hostname"})
_GH_API_BOOL: Final = frozenset({"-i", "--include", "--paginate", "--silent", "--verbose", "--slurp"})
_GH_API_BODY: Final = frozenset({"-f", "--raw-field", "-F", "--field", "--input"})
_MERGE_ENDPOINT: Final = re.compile(r"(?:^|/)(?:merge|merges)(?:$|[/?])")
_PR_NUMBER: Final = re.compile(r"^#?([1-9][0-9]{0,9})$")
_REPO_NAME: Final = re.compile(r"^(?:([A-Za-z0-9.-]+)/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
_DEFAULT_HOST: Final = "github.com"

_BLOCK_SUFFIX: Final = "A blocked call did not run."


class _Context:
    """What one classification reads besides the command: the grant's prefix and the bot's PRs."""

    def __init__(self, prefix: str, opened: frozenset[tuple[str, int]]) -> None:
        self.prefix = prefix
        self.opened = opened
        # The head branch of the one `gh pr create` the command holds, for the record.
        self.pr_head = ""


def _worst(classes: list[str]) -> str:
    if not classes:
        return LOCAL
    return min(classes, key=_SEVERITY.index)


def classify_command(command: object, *, prefix: str, opened: frozenset[tuple[str, int]] = frozenset()) -> str:
    """The forge class of one `terminal` command line. Pure; reads no file."""
    return _classify(command, _Context(prefix, opened), 0)


def _classify(command: object, context: _Context, depth: int) -> str:
    if not isinstance(command, str) or not command.strip():
        return LOCAL
    if depth > _MAX_DEPTH:
        return UNCLASSIFIED
    mentions_forge = _FORGE_WORD.search(command) is not None
    if "`" in command and mentions_forge:
        return UNCLASSIFIED
    lines = _command_lines(command)
    whole = _shell_tokens(lines[0])
    if not whole:
        return UNCLASSIFIED if mentions_forge else LOCAL
    classes = [_classify_segment(segment, context, depth) for segment in _segments(whole)]
    # The per-line pass catches a push on its own line, which `shlex` would
    # read as more arguments of the line before; a line that does not
    # tokenize alone is inside a quoted string the whole pass already read.
    for line in lines[1:]:
        classes.extend(_classify_segment(segment, context, depth) for segment in _segments(_shell_tokens(line)))
    return _worst(classes)


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _unwrap(segment: list[str]) -> list[str] | None:
    """The segment from its real command on, or None when a wrapper hides it."""
    words = _strip_env_assignments(segment)
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
        words = _strip_env_assignments(words[index:])
    return words


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


def _classify_segment(segment: list[str], context: _Context, depth: int) -> str:
    words = _unwrap(segment)
    if words is None:
        return UNCLASSIFIED if _FORGE_WORD.search(" ".join(segment)) else LOCAL
    if not words:
        return LOCAL
    name = _basename(words[0])
    if name in _SHELLS:
        payload = _shell_payload(words)
        if payload is not None:
            return _classify(payload, context, depth + 1)
    elif name == "eval":
        return _classify(" ".join(words[1:]), context, depth + 1)
    elif name == "git":
        return _classify_git(words[1:], context, depth)
    elif name == "gh":
        return _classify_gh(words[1:], context)
    text = " ".join(words)
    if _FORGE_WORD.search(text) and _FORGE_VERB.search(text):
        return UNCLASSIFIED
    return LOCAL


def _classify_git(args: list[str], context: _Context, depth: int) -> str:
    index = 0
    configured = False
    while index < len(args) and args[index].startswith("-"):
        option, has_value, value = args[index].partition("=")
        if option in _GIT_GLOBAL_VALUE:
            if not has_value:
                index += 1
                value = args[index] if index < len(args) else ""
            if option in ("-c", "--config-env"):
                configured = True
                if value.lower().startswith("alias."):
                    return UNCLASSIFIED
        elif option not in _GIT_GLOBAL_BOOL:
            return UNCLASSIFIED
        index += 1
    if index >= len(args):
        return LOCAL
    subcommand, rest = args[index], args[index + 1:]
    if subcommand == "push":
        # A `-c` can redirect a push (`url.<base>.insteadOf`, `remote.<name>.push`).
        return UNCLASSIFIED if configured else _classify_push(rest, context)
    if subcommand == "submodule" and "foreach" in rest:
        return _classify(" ".join(rest[rest.index("foreach") + 1:]), context, depth + 1)
    if subcommand == "bisect" and rest[:1] == ["run"]:
        return _classify(" ".join(rest[1:]), context, depth + 1)
    if subcommand == "rebase":
        for position, token in enumerate(rest):
            if token in ("-x", "--exec") and position + 1 < len(rest):
                return _worst([LOCAL, _classify(rest[position + 1], context, depth + 1)])
            if token.startswith("--exec="):
                return _classify(token.split("=", 1)[1], context, depth + 1)
    return LOCAL if subcommand in _GIT_LOCAL else UNCLASSIFIED


def _classify_push(args: list[str], context: _Context) -> str:
    positionals: list[str] = []
    repository_option = False
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
            if option in _WIDE_LONG:
                wide = True
            elif option in ("--dry-run", "--help"):
                dry_run = True
            elif option in _PUSH_LONG_VALUE:
                if not has_value:
                    index += 1
                repository_option = repository_option or option == "--repo"
            elif option in _PUSH_LONG_OPTIONAL_VALUE:
                if option == "--recurse-submodules" and value not in ("check", "no"):
                    wide = True
            elif option not in _PUSH_LONG_BOOL:
                return UNCLASSIFIED
            continue
        cluster = token[1:]
        for position, letter in enumerate(cluster):
            if letter in "fd":
                return FORCE_PUSH
            if letter in "nh":
                dry_run = True
            elif letter == "o":
                if position == len(cluster) - 1:
                    index += 1
                break
            elif letter not in "uqv46":
                return UNCLASSIFIED
    if dry_run:
        return LOCAL
    if wide:
        return PUSH_OUTSIDE
    refspecs = positionals if repository_option else positionals[1:]
    if not refspecs:
        return UNQUALIFIED
    return _worst([_classify_refspec(spec, context.prefix) for spec in refspecs])


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
    if not destination or _NOT_LITERAL.search(destination):
        return PUSH_OUTSIDE if "*" in destination else UNQUALIFIED
    return PUSH_BOT_BRANCH if _under_prefix(destination, prefix) else PUSH_OUTSIDE


def _under_prefix(ref: str, prefix: str) -> bool:
    if ref.startswith("refs/"):
        if not ref.startswith("refs/heads/"):
            return False
        ref = ref[len("refs/heads/"):]
    return ref.startswith(prefix) and len(ref) > len(prefix) and not _NOT_LITERAL.search(ref)


def _options(args: list[str], value_options: frozenset[str], bool_options: frozenset[str]):
    """(options, positionals, known) for a `gh` verb's arguments, by its own option table."""
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
                value = args[index] if index < len(args) else ""
                index += 1
            options[option] = value
        elif option in bool_options and not has_value:
            options[option] = ""
        else:
            return options, positionals, False
    return options, positionals, True


def _first_verb(args: list[str]) -> tuple[str, list[str]]:
    """A gh group's verb, skipping a leading `-R <repo>`; and the arguments after it."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in ("-R", "--repo") else 1
    if index >= len(args):
        return "", []
    return args[index], args[:index] + args[index + 1:]


def _classify_gh(args: list[str], context: _Context) -> str:
    if not args or args[0] in _GH_READ_ONLY_GROUPS:
        return LOCAL
    if "--help" in args or "-h" in args:
        return LOCAL
    group, rest = args[0], args[1:]
    if group == "api":
        return _classify_gh_api(rest)
    verb, verb_args = _first_verb(rest)
    if group == "pr":
        return _classify_gh_pr(verb, verb_args, context)
    if group in _GH_REPO_GROUPS:
        return LOCAL if not verb or verb in _GH_READ_VERBS else OTHER_PR_OR_REPO
    if group in _GH_NOT_GOVERNED_GROUPS:
        return LOCAL if not verb or verb in _GH_READ_VERBS else NOT_GOVERNED
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
        if not known or positionals:
            return UNCLASSIFIED
        if "--dry-run" in options:
            return LOCAL
        if "-R" in options or "--repo" in options:
            return OTHER_PR_OR_REPO
        head = options.get("-H", options.get("--head", ""))
        if not head:
            return UNQUALIFIED
        if ":" in head or not _under_prefix(head, context.prefix):
            return OTHER_PR_OR_REPO if ":" in head else PUSH_OUTSIDE
        context.pr_head = head
        return OPEN_PR
    if verb == "comment":
        options, positionals, known = _options(args, _GH_PR_COMMENT_VALUE, _GH_PR_COMMENT_BOOL)
        if not known or len(positionals) > 1:
            return UNCLASSIFIED
        selector = positionals[0] if positionals else ""
        pr = _selected_pr(selector, options.get("-R", options.get("--repo", "")))
        if pr is None:
            return UNQUALIFIED
        return COMMENT_OWN_PR if pr in context.opened else OTHER_PR_OR_REPO
    return UNCLASSIFIED


def _selected_pr(selector: str, repository: str) -> tuple[str, int] | None:
    """(`host/owner/name`, number) a `gh pr comment` names unambiguously, else None."""
    by_url = pr_delivery.parse_pr_url(selector)
    if by_url is not None:
        return by_url
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
    method = options.get("-X", options.get("--method", "")).upper()
    if not method:
        method = "POST" if _GH_API_BODY.intersection(options) else "GET"
    if method == "GET":
        return LOCAL
    endpoint = positionals[0].split("?", 1)[0]
    return FORGE_MERGE if _MERGE_ENDPOINT.search(endpoint) else OTHER_PR_OR_REPO


# Directives -------------------------------------------------------------------


def _command_of(tool_input: object) -> str:
    if isinstance(tool_input, Mapping):
        value = tool_input.get("command")
        return value if isinstance(value, str) else ""
    return ""


def _code_of(tool_input: object) -> str:
    if isinstance(tool_input, Mapping):
        value = tool_input.get("code")
        return value if isinstance(value, str) else ""
    return ""


def _names_grant_change(command: str) -> bool:
    """Whether a command line turns the grant on or off, or touches its store."""
    if _GRANT_STORE_WORD.search(command):
        return True
    tokens = _shell_tokens(command)
    if not tokens:
        return _GRANT_COMMAND_WORD in command
    for segment in _segments(tokens):
        if _GRANT_COMMAND_WORD in segment:
            after = segment[segment.index(_GRANT_COMMAND_WORD) + 1:]
            if "on" in after or "off" in after:
                return True
        # A token holding a whole command line (`sh -c '...'`, `eval '...'`) is read as one.
        if any(" " in token and _names_grant_change(token) for token in segment):
            return True
    return False


def grant_change_directive(*, tool_name: object, tool_input: object) -> dict[str, str] | None:
    """Refuse, in every session, a tool call that would turn the grant on or off."""
    tool = str(tool_name or "")
    if tool == TERMINAL_TOOL:
        named = _names_grant_change(_command_of(tool_input))
    elif tool == CODE_TOOL:
        named = _CODE_GRANT_WORD.search(_code_of(tool_input)) is not None
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


def delivery_directive(
    *, tool_name: object, tool_input: object, session_id: str, omh_home: str, hermes_home: str
) -> dict[str, str] | None:
    """The block for a forge command an unattended session may not run, else None."""
    tool = str(tool_name or "")
    if tool not in (TERMINAL_TOOL, CODE_TOOL):
        return None
    if escalation_can_reach_a_person(session_id):
        return None
    grant = pr_delivery.read_grant(omh_home, hermes_home)
    prefix = pr_delivery.branch_prefix(grant)
    if tool == CODE_TOOL:
        code = _code_of(tool_input)
        forge_class = UNCLASSIFIED if _FORGE_WORD.search(code) and _FORGE_VERB.search(code) else LOCAL
    else:
        opened = pr_delivery.opened_prs(omh_home, hermes_home)
        forge_class = classify_command(_command_of(tool_input), prefix=prefix, opened=opened)
    if forge_class in (LOCAL, NOT_GOVERNED):
        return None
    delegated = session_is_delegated(session_id)
    if forge_class in GRANT_COVERED and grant.get("state") == "on" and not delegated:
        return None
    return {"action": "block", "message": _refusal(forge_class, grant, prefix, delegated)}


def _refusal(forge_class: str, grant: Mapping[str, object], prefix: str, delegated: bool) -> str:
    what = _DESCRIPTIONS.get(forge_class, "this command")
    lead = f"[OMH PR delivery] Nobody can answer a confirmation in this session, so OMH did not run {what}."
    if forge_class in GRANT_COVERED and delegated:
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
        detail = ("OMH cannot read what this command publishes. Run git and gh as their own commands, without a "
                  "shell wrapper, eval, script or alias, or hand the step to a person's turn.")
    else:
        detail = ("That is never run without a person, whatever the PR delivery grant says "
                  f"(state: {grant.get('state', 'off')}). Hand it to a person's turn with the evidence.")
    return f"{lead} {detail} {_BLOCK_SUFFIX}"


def observe_opened_pr(
    *, tool_name: object, tool_input: object, result: object, session_id: str, omh_home: str, hermes_home: str
) -> bool:
    """Record the PR a grant-allowed `gh pr create` printed. True when a record was written.

    Only a command that is exactly one `gh pr create` segment counts, so no
    other program in the same command line can print a URL into its output;
    only a zero exit; only a URL on the output's last line, which is where
    `gh pr create` prints it.
    """
    if str(tool_name or "") != TERMINAL_TOOL:
        return False
    grant = pr_delivery.read_grant(omh_home, hermes_home)
    if grant.get("state") != "on":
        return False
    command = _command_of(tool_input)
    tokens = _shell_tokens(command)
    segments = _segments(tokens)
    if len(segments) != 1 or len(command.strip().splitlines()) != 1:
        return False
    context = _Context(pr_delivery.branch_prefix(grant), frozenset())
    if _classify_segment(segments[0], context, 0) != OPEN_PR:
        return False
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
