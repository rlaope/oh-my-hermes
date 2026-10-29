"""Which commands in an approval's shell line would destroy something, for the slot to show first.

Hermes flags a command line by the first of its dangerous patterns that
matches and names only that one (`detect_dangerous_command`), so a line that
chains a recursive delete with a forced worktree removal and a remote branch
delete reads as "recursive delete" alone. The approval slot shows each command
of the line on its own row and names the risks Hermes did not.

Two small, explicit steps, no shell parser:

- `split_commands` cuts the line at the top-level `&&`, `||`, `;` and line
  breaks, skipping over single quotes, double quotes and backslash escapes.
  A pipe stays inside its command. A comment (`#` starting a word) runs to the
  end of its line, and a here-document (`<<EOF`) stays with the command that
  opened it through its closing line; neither is read for what it runs.
- A command is risky only when a program it runs (its first word after any
  `NAME=value` assignments, the first word of a pipe stage, or the word after
  `sudo`, `env` or `xargs` and their options) matches a row of `RISKS`, or
  when it runs a download or decoded text as a script: a pipe stage running
  a shell after one that downloads or decodes (`curl … | sh`, `base64 -d |
  sh`), or a shell, `eval`, `source` or `.` handed a substitution that
  downloads (`bash <(curl …)`, `eval "$(curl …)"`, `sh -c "$(curl …)"`).
  Words are read quote-aware, so text inside quotes, or an argument to `echo`
  or `grep`, never matches.

`RISKS` is far narrower than Hermes' own table, so what it does not find is
not safe. `Segment.foldable` is a closed allowlist instead: a command may
fold out of sight only when every program it runs reads and changes nothing
(`FOLDABLE`, `GIT_FOLDABLE`, `GH_READ_ONLY`), it writes no file, and nothing
in it runs more than its words say (a substitution, a background job, a
here-document, an open quote, a function or alias the line defines, an
assignment in front of a program, git's `-c`) or reads as a risk inside
quotes (Hermes' patterns are not quote-aware). Everything else is listed,
and so is a command that decides what a listed one after it acts on: a
directory change or a variable assignment (`_sets_state`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache

# Words that run the program after them; their options that take a value consume the next word (`timeout` also
# takes its duration).
_RUNNERS = {"sudo": frozenset("ugCDhprtUT"), "env": frozenset("uCS"), "xargs": frozenset("InPLsdEa"),
            "timeout": frozenset("sk"), "command": frozenset()}
# Shell words that come before the command they introduce (`if c; then curl x | sh; fi`).
_KEYWORDS = frozenset(("if", "then", "elif", "else", "do", "while", "until", "time", "!", "{", "("))
# How deep a shell's `-c` script or a substitution inside one is read for what it runs.
_DEPTH = 3
# Options git itself takes before the subcommand that consume the next word.
_GIT_VALUE_OPTIONS = frozenset(("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"))
# The programs a command may run and still fold out of sight: they read, print or move the shell, and change
# nothing. git folds only on `_git_folds`, gh only on `GH_READ_ONLY`.
FOLDABLE = frozenset(("cd", "pushd", "popd", "echo", "printf", "ls", "pwd", "true", ":", "wc", "grep", "head"))
# The `FOLDABLE` programs that move the shell, so a later command acts somewhere else; they fold only with nothing
# listed after them (`_sets_state`).
_MOVES = frozenset(("cd", "pushd", "popd"))
# The programs that download, and the shells that run what is piped into them (hermes-agent bf0203a794
# tools/approval_detection.py:157-158 `_SHELL_NAMES`).
_FETCHERS = frozenset(("curl", "wget"))
_SHELLS = frozenset(("bash", "sh", "zsh", "ksh", "dash"))
# The builtins that run the text they are given in the current shell.
_SOURCES = frozenset(("eval", "source", "."))
GH_READ_ONLY = frozenset((
    ("pr", "view"), ("pr", "list"), ("pr", "checks"), ("pr", "status"), ("pr", "diff"), ("issue", "view"),
    ("issue", "list"), ("run", "view"), ("run", "list"), ("run", "watch"), ("repo", "view"), ("auth", "status"),
))
# The git subcommands that may fold. They read, except `worktree prune`, which only drops git's records of worktrees
# whose directory is already gone (the owner's line runs it, and Hermes flags none of them).
GIT_FOLDABLE = frozenset(("status", "log", "diff", "show", "rev-parse", "worktree list", "worktree prune", "branch",
                          "remote"))
# `git branch` options that only list; with `--list` or `-l` its other words are patterns.
_GIT_BRANCH_LISTS = frozenset(("--list", "-l", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose",
                               "--show-current", "--no-color"))
# git options before the subcommand that make it run a program of their choosing.
_GIT_RUNS = ("-c", "--config-env", "--exec-path")
# Text that runs something the words do not show: a command substitution, a subshell or a process substitution.
_OPAQUE_TEXT = ("(", "`")
# What a word is cut at when looking for `rm` anywhere, inside quotes too.
_WORD_BREAKS = "'\"`;&|(){}<>=!"


@dataclass(frozen=True)
class Segment:
    """One command of the line: its text as written, the first word it runs, and the risks found in it."""

    text: str
    head: str
    risks: tuple[str, ...]
    foldable: bool = True  # may fold out of sight: it changes nothing (`_foldable`)
    sets_state: bool = False  # would fold, but moves the shell or assigns before a listed command (`_sets_state`)


def _word_start(text: str, index: int) -> bool:
    return index == 0 or text[index - 1].isspace() or text[index - 1] in ";&|()<>"


def _heredoc(command: str, index: int) -> tuple[str, int, bool, bool]:
    """The here-document `<<` at `index` opens: its delimiter with the quotes taken off, the index past it, whether
    its closing line may be indented with tabs (`<<-`), and whether the delimiter is quoted (`'EOF'`, `"EOF"`,
    `\\EOF`), which keeps the body from running its substitutions. No delimiter for a `<<` that opens none
    (`1<<2`)."""
    end = index + 2
    tabs = command.startswith("-", end)
    end += tabs
    while end < len(command) and command[end] in " \t":
        end += 1
    start, word, quote = end, [], ""
    while end < len(command):
        char = command[end]
        if quote:
            quote = "" if char == quote else quote
            if quote:
                word.append(char)
        elif char in "'\"":
            quote = char
        elif char.isspace() or char in ";&|<>()":
            break
        elif char != "\\":
            word.append(char)
        end += 1
    opens = start < len(command) and (command[start] in "'\"\\_" or command[start].isalpha())
    quoted = any(char in "'\"\\" for char in command[start:end])
    return ("".join(word) if opens else ""), end, tabs, quoted


@lru_cache(maxsize=8)
def _parentheses(text: str) -> dict[int, int]:
    """Each `(` of `text` mapped to the `)` that closes it, every parenthesis counted as written; one that never
    closes has none. Read once per text, so a line of thousands of `((` stays linear."""
    closes: dict[int, int] = {}
    opened: list[int] = []
    for index, char in enumerate(text):
        if char == "(":
            opened.append(index)
        elif char == ")" and opened:
            closes[opened.pop()] = index
    return closes


def _arithmetic_end(text: str, index: int) -> int | None:
    """The index past the `))` that closes the arithmetic `$((` or `((` at `index` (a `<<` inside is a shift, not a
    here-document), or None when what opens there is read as commands instead: a `$((` that never closes, or a `((`
    whose two parentheses do not close together or that holds a `;`, `&&`, `||` or a line break at its own level,
    as `((cd a; rm -rf b); ls)` is two subshells."""
    closes = _parentheses(text)
    first = text.index("((", index)
    outer, inner = closes.get(first), closes.get(first + 1)
    if outer is None:
        return None
    if text.startswith("$", index):
        return outer + 1
    if inner is None or outer != inner + 1:
        return None
    position = first + 2
    while position < inner:
        if text[position] == "(" and position in closes:
            position = closes[position] + 1  # a nested pair is not this level
        elif text[position] in ";\n" or text.startswith(("&&", "||"), position):
            return None
        else:
            position += 1
    return outer + 1


def _arithmetic(text: str, index: int) -> bool:
    """Whether an arithmetic expansion (`$((`) or command (`((` starting a word) opens at `index`."""
    return text.startswith("$((", index) or (text.startswith("((", index) and _word_start(text, index))


def _body_substitutions(body: str) -> list[str]:
    """The command substitutions (`$(…)`, `` `…` ``) in the here-document `body` of an unquoted delimiter, which the
    shell runs as it reads the body; a backslash escapes the next character."""
    found: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == "\\":
            index += 2
        elif body.startswith("$((", index) and (end := _arithmetic_end(body, index)) is not None:
            index = end
        elif body.startswith("$(", index):
            end = _closing(body, index + 2)
            found.append(body[index : end + 1])
            index = end + 1
        elif body[index] == "`":
            end = body.find("`", index + 1)
            end = len(body) if end < 0 else end
            found.append(body[index : end + 1])
            index = end + 1
        else:
            index += 1
    return found


def _heredoc_end(command: str, index: int, pending: list[tuple[str, bool]]) -> int:
    """Where the bodies of the `pending` here-documents end, from the line break at `index`: the line break after the
    last one's closing line, or the end of `command` when a body is never closed."""
    end = index
    for delimiter, tabs in pending:
        while end < len(command):
            start = end + 1
            end = command.find("\n", start)
            end = len(command) if end < 0 else end
            line = command[start:end]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                break
    return end


def _scan(command: str) -> list[tuple[str, str, bool]]:
    """Each top-level command of `command`: its text as written, the text read for what it runs (its comments and
    here-document bodies left out), each stripped, and whether its quotes close (an unclosed one swallows every command
    after it); a command with nothing to read (a comment line) is dropped."""
    parts: list[tuple[list[str], list[str]]] = []
    written: list[str] = []
    read: list[str] = []
    opener, opener_read = written, read  # the command a pending here-document's body belongs to
    pending: list[tuple[str, bool, bool]] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\" and index + 1 < len(command):
            written.append(command[index : index + 2])
            read.append(command[index : index + 2])
            index += 2
            continue
        elif quote == '"':
            quote = "" if char == '"' else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and _word_start(command, index):
            end = command.find("\n", index)
            end = len(command) if end < 0 else end
            written.append(command[index:end])
            index = end
            continue
        elif _arithmetic(command, index) and (end := _arithmetic_end(command, index)) is not None:
            written.append(command[index:end])
            read.append(command[index:end])
            index = end
            continue
        elif command.startswith("<<<", index):  # a here-string, not a here-document
            written.append("<<<")
            read.append("<<<")
            index += 3
            continue
        elif command.startswith("<<", index):
            delimiter, end, tabs, quoted = _heredoc(command, index)
            if delimiter:
                pending.append((delimiter, tabs, quoted))
                opener, opener_read = written, read
                written.append(command[index:end])
                read.append(command[index:end])
                index = end
                continue
        elif char == "\n" and pending:
            end = _heredoc_end(command, index, [(delimiter, tabs) for delimiter, tabs, _ in pending])
            opener.append(command[index:end])
            if not all(quoted for _, _, quoted in pending):  # an unquoted delimiter's body runs its substitutions
                opener_read.extend(" " + text for text in _body_substitutions(command[index:end]))
            pending = []
            index = end
            continue
        if not quote and (command.startswith(("&&", "||"), index) or char in ";\n"):
            parts.append((written, read))
            written, read = [], []
            index += 1 if char in ";\n" else 2
            continue
        written.append(char)
        read.append(char)
        index += 1
    parts.append((written, read))
    return [("".join(text).strip(), "".join(words).strip(), not quote or number < len(parts) - 1)
            for number, (text, words) in enumerate(parts) if "".join(words).strip()]


def split_commands(command: str) -> list[str]:
    """`command` cut at its top-level `&&`, `||`, `;` and line breaks (`_scan`), each part as written, stripped."""
    return [text for text, _, _ in _scan(command)]


def _stages(segment: str) -> list[list[str]]:
    """`segment`'s pipe stages, each as its words with the quotes taken off (a quoted text is one word), a comment
    (`#` starting a word, to the end of its line) left out."""
    stages: list[list[str]] = [[]]
    word: list[str] = []
    started = False  # a word is open, so `""` is still a word
    quote = ""
    index = 0
    while index < len(segment):
        char = segment[index]
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                word.append(char)
        elif char == "\\" and index + 1 < len(segment):
            word.append(segment[index + 1])
            started = True
            index += 2
            continue
        elif quote == '"':
            if char == '"':
                quote = ""
            else:
                word.append(char)
        elif char in "'\"":
            quote, started = char, True
        elif char == "#" and not started:
            end = segment.find("\n", index)
            index = len(segment) if end < 0 else end
            continue
        elif char.isspace() or char == "|":
            if started or word:
                stages[-1].append("".join(word))
            word, started = [], False
            if char == "|":
                stages.append([])
        else:
            word.append(char)
            started = True
        index += 1
    if started or word:
        stages[-1].append("".join(word))
    return [stage for stage in stages if stage]


def _is_assignment(word: str) -> bool:
    name, equals, _ = word.partition("=")
    return bool(equals) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def _program(words: list[str]) -> list[str]:
    """`words` from the program they run: past shell keywords (`then`, `do`, `!`), `NAME=value` assignments, and a
    runner (`_RUNNERS`, by its name or its path) with its options."""
    index = 0
    while index < len(words):
        word = words[index]
        if _is_assignment(word) or word in _KEYWORDS:
            index += 1
            continue
        runner = word.rsplit("/", 1)[-1]
        valued = _RUNNERS.get(runner)
        if valued is None:
            return words[index:]
        index += 1
        while index < len(words) and (words[index].startswith("-") or (runner == "env" and _is_assignment(words[index]))):
            option = words[index]
            index += 2 if len(option) == 2 and option[1] in valued else 1
        index += runner == "timeout"
    return []


def _options(args: list[str]) -> tuple[set[str], set[str], list[str]]:
    """`args` before a `--`: the long options (without a `=value`), the letters of the short ones, and the rest."""
    longs: set[str] = set()
    shorts: set[str] = set()
    rest: list[str] = []
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("--"):
            longs.add(arg.partition("=")[0])
        elif arg.startswith("-") and len(arg) > 1:
            shorts.update(arg[1:])
        else:
            rest.append(arg)
    return longs, shorts, rest


def _given(longs: set[str], *names: str) -> bool:
    """Whether `longs` hold one of `names` or a prefix of it: git and GNU tools take `--ha` for `--hard`."""
    return any(len(given) > 2 and name.startswith(given) for given in longs for name in names)


def _rm(args: list[str]) -> list[str]:
    longs, shorts, rest = _options(args)
    if _given(longs, "--recursive") or shorts & {"r", "R"}:
        return ["recursive delete"]
    operands = rest + (args[args.index("--") + 1 :] if "--" in args else [])
    return ["deletes in root path"] if any(path.startswith("/") for path in operands) else []


def _chmod(args: list[str]) -> list[str]:
    """Whether the mode lets others write: an octal mode whose last digit has the write bit (`777`, `666`), or a
    symbolic clause for `o` or `a` that adds or sets `w` (`o+w`, `a+rwx`)."""
    _, _, rest = _options(args)
    operands = rest + (args[args.index("--") + 1 :] if "--" in args else [])
    mode = operands[0] if operands else ""
    if mode and all(digit in "01234567" for digit in mode):
        # A sticky shared directory (`1777`, as /tmp is) lets others write but not delete what is not theirs; Hermes'
        # pattern does not match it either.
        sticky = len(mode) == 4 and mode[0] in "1357"
        return ["makes files world-writable"] if mode[-1] in "2367" and not sticky else []
    for clause in mode.split(","):
        who, op, perms = clause.partition("+") if "+" in clause else clause.partition("=")
        if op and "w" in perms and set(who) & {"o", "a"}:
            return ["makes files world-writable"]
    return []


def _find(args: list[str]) -> list[str]:
    """`find` deletes what it matches with `-delete`, or with `rm` run by `-exec`, `-execdir`, `-ok` or `-okdir`
    (tools/approval_detection.py:358, :367). The words of a program `-exec` runs, up to its `;` or `+`, are that
    program's: `find . -exec echo -delete ;` deletes nothing."""
    index = 0
    while index < len(args):
        if args[index] in ("-exec", "-execdir", "-ok", "-okdir"):
            if args[index + 1 : index + 2] and args[index + 1].rsplit("/", 1)[-1] == "rm":
                return ["recursive delete"]
            index += 1
            while index < len(args) and args[index] not in (";", "+"):
                index += 1
        elif args[index] == "-delete":
            return ["recursive delete"]
        index += 1
    return []


def _git(args: list[str]) -> list[str]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in _GIT_VALUE_OPTIONS else 1
    if index >= len(args):
        return []
    sub, longs, shorts, rest = args[index], *_options(args[index + 1 :])
    found: list[str] = []
    if sub == "push":
        if _given(longs, "--delete") or "d" in shorts or any(ref.startswith(":") and len(ref) > 1 for ref in rest[1:]):
            found.append("deletes a remote branch")
        if _given(longs, "--force", "--force-with-lease") or "f" in shorts or any(ref.startswith("+") for ref in rest[1:]):
            found.append("force-pushes")
    elif sub == "branch":
        deletes, forced = _given(longs, "--delete") or "d" in shorts, _given(longs, "--force") or "f" in shorts
        if "D" in shorts or (deletes and forced):
            found.append("deletes local branches")
    elif sub == "worktree":
        if rest[:1] == ["remove"] and (_given(longs, "--force") or "f" in shorts):
            found.append("force-removes a worktree")
    elif sub == "reset":
        if _given(longs, "--hard"):
            found.append("hard reset")
    elif sub == "clean":
        if _given(longs, "--force") or "f" in shorts:
            found.append("deletes untracked files")
    return found


# The closed table: a program's name, and what reads its arguments for the risks it names.
RISKS: dict[str, Callable[[list[str]], list[str]]] = {"rm": _rm, "git": _git, "chmod": _chmod, "find": _find}
# A download run as a script (`_runs_download`, or a pipe from `_FETCHERS` into `_SHELLS`), and decoded text piped
# into a shell (`_decodes`).
REMOTE_SCRIPT = "runs a downloaded script"
DECODED_SCRIPT = "runs decoded text as a script"
# Hermes' own descriptions of the same risks where its wording differs from OMH's (tools/approval_detection.py,
# hermes-agent bf0203a794), so a risk Hermes already named is not named again in other words.
HERMES_NAMES = {
    "deletes in root path": ("delete in root path",),
    # Hermes says "delete in root path" for any `rm` with an operand from `/`, recursive or not (its first pattern).
    "recursive delete": (
        "delete in root path",
        "recursive delete (long flag)",
        "recursive delete (flags after operands)",
        "recursive delete of root filesystem",
        "recursive delete of system directory",
        "recursive delete of home directory",
        "xargs with rm",
        "find -exec/-execdir rm",
        "find -delete",
    ),
    "force-pushes": (
        "git force push (rewrites remote history)",
        "git force push short flag (rewrites remote history)",
    ),
    "deletes local branches": (
        "git branch force delete",
        "git branch force delete (long flags)",
        "git branch force delete (long flags, force-first)",
    ),
    "hard reset": ("git reset --hard (destroys uncommitted changes)",),
    "deletes untracked files": ("git clean with force (deletes untracked files)",),
    # tools/approval_detection.py:287-288 (`chmod` with 777, 666, o+w or a+w).
    "makes files world-writable": (
        "world/other-writable permissions",
        "recursive world/other-writable (long flag)",
    ),
    # :313 (`curl` or `wget` piped to a shell), :314 (a shell reading `<(curl …)`), :316 (`eval`, `source` or `.`
    # given `$(curl …)`); a shell's `-c` is Hermes' structural "shell command via -c/-lc flag" (:1013-1016), which
    # names every `-c`, so it is not taken as naming this.
    REMOTE_SCRIPT: (
        "pipe remote content to shell",
        "execute remote script via process substitution",
        "execute remote content via command substitution",
    ),
    # :332-338: base64/base32/base16 `-d`, `xxd -r`, `echo | tr` and `openssl` decoding, piped to a shell.
    DECODED_SCRIPT: (
        "pipe decoded content to shell (possible command obfuscation)",
        "pipe xxd-decoded content to shell (possible command obfuscation)",
        "pipe tr-transformed output to shell (possible command obfuscation)",
        "pipe openssl-decoded content to shell (possible command obfuscation)",
    ),
}


def _decodes(program: str, args: list[str], previous: str) -> bool:
    """Whether a pipe stage running `program` with `args`, after one running `previous`, decodes what it reads into
    text a shell after it would run (tools/approval_detection.py:332-338)."""
    if program in ("base64", "base32", "base16"):
        return any(arg.partition("=")[0] == "--decode" or (arg[:1] == "-" and arg[1:2] != "-" and set(arg[1:]) & set("dD"))
                   for arg in args)
    if program == "xxd":
        return bool({"-r", "-revert", "-rp", "-pr"} & set(args))
    if program == "openssl":
        return bool({"base64", "enc"} & set(args)) and bool({"-d", "-D"} & set(args))
    return program == "tr" and previous == "echo"


def _closing(text: str, index: int) -> int:
    """The index of the `)` that closes the `(` before `index`, or the end of `text` when none does. A parenthesis
    inside quotes, a backtick span or a here-document body (`_heredoc`, `_heredoc_end`) is text, not one that
    closes: a commit message's `a)` must not end its `$(cat <<'EOF' …`."""
    closers = [")"]  # what ends each context open at `index`: `)`, a double quote, or a backtick
    pending: list[tuple[str, bool]] = []
    while index < len(text):
        char = text[index]
        inside = closers[-1]
        if char == "\\":
            index += 2
            continue
        arithmetic = inside != "`" and _arithmetic(text, index) and (inside == ")" or text.startswith("$((", index))
        if arithmetic and (end := _arithmetic_end(text, index)) is not None:
            index = end
            continue
        if inside != ")":  # in a double quote only `$(` and a backtick open; in a backtick span nothing does
            if char == inside:
                closers.pop()
            elif inside == '"' and text.startswith("$(", index):
                closers.append(")")
                index += 1
            elif inside == '"' and char == "`":
                closers.append(char)
            index += 1
            continue
        if char == "'":
            end = text.find("'", index + 1)
            index = len(text) if end < 0 else end + 1
            continue
        if text.startswith("<<<", index):  # a here-string, not a here-document
            index += 3
            continue
        if text.startswith("<<", index):
            delimiter, end, tabs, _ = _heredoc(text, index)
            if delimiter:
                pending.append((delimiter, tabs))
                index = end
                continue
        if char == "\n" and pending:
            index = _heredoc_end(text, index, pending)
            pending = []
            continue
        if char in "\"`(":
            closers.append(")" if char == "(" else char)
        elif char == ")":
            closers.pop()
            if not closers:
                return index
        index += 1
    return len(text)


def _substitutions(segment: str) -> tuple[str, list[tuple[str, str]]]:
    """`segment` with each substitution replaced by its number between NULs, and each one's opener and body: a
    command substitution (`$(…)`, `` `…` ``) outside single quotes, a process substitution (`<(…)`) outside any
    quotes."""
    masked: list[str] = []
    found: list[tuple[str, str]] = []
    quote = ""
    index = 0
    while index < len(segment):
        char = segment[index]
        opener = ""
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\" and index + 1 < len(segment):
            masked.append(segment[index : index + 2])
            index += 2
            continue
        elif char == '"' and quote in ("", '"'):
            quote = "" if quote else char
        elif char == "'" and not quote:
            quote = char
        elif segment.startswith("$(", index) and not segment.startswith("$((", index):
            opener = "$("
        elif char == "`":
            opener = "`"
        elif segment.startswith("<(", index) and not quote:
            opener = "<("
        if not opener:
            masked.append(char)
            index += 1
            continue
        start = index + len(opener)
        end = segment.find("`", start) if opener == "`" else _closing(segment, start)
        end = len(segment) if end < 0 else end
        masked.append(f"\x00{len(found)}\x00")
        found.append((opener, segment[start:end]))
        index = end + 1
    return "".join(masked), found


def _fetches(text: str) -> bool:
    """Whether a pipe stage of `text` runs `curl` or `wget`."""
    return any(words and words[0].rsplit("/", 1)[-1] in _FETCHERS for words in map(_program, _stages(text)))


def _runs_text(word: str) -> bool:
    """Whether a shell's option `word` makes it run the next word as its script (`-c`, `-lc`)."""
    return word[:1] == "-" and word[1:2] != "-" and "c" in word


def _shell_operand(args: list[str]) -> tuple[bool, int]:
    """Whether a shell's options in `args` include `-c`, and the index of its first operand (`len(args)` when it has
    none): the script it runs, from `-c` or a file. Options start with `-` or `+` (`+x`) and end at the first
    operand, so `bash run.sh -c x` passes `-c` to `run.sh`; `-o`, `+o`, `-O`, `+O`, `--rcfile` and `--init-file`
    take a value, and a `<` redirect is no operand."""
    runs = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "<":
            index += 1
        elif arg in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            index += 2
        elif arg[:1] in ("-", "+") and arg not in ("-", "+"):
            runs = runs or _runs_text(arg)
            index += 1
        else:
            break
    return runs, index


def _shell_script(args: list[str]) -> str | None:
    """The script a shell with `args` runs from its `-c` (`_shell_operand`), or None when it has none."""
    runs, index = _shell_operand(args)
    return args[index] if runs and index < len(args) else None


def _runs_download(stages: list[list[str]], substituted: list[tuple[str, str]]) -> bool:
    """Whether the pipe `stages` (substitutions masked, `_substitutions`) hand a download to what runs it as a
    script: a shell, `eval`, `source` or `.` reading a process substitution that downloads (`bash <(curl …)`, :314),
    `eval`, `source` or `.` given a command substitution that does (`eval "$(curl …)"`, :316), or a shell given one
    as the script its `-c` runs (`sh -c "$(curl …)"`), or reading one as its input (`bash -s -- a < <(curl …)`). A
    shell's later operands are its script's arguments."""
    fetching = {str(number) for number, (_, body) in enumerate(substituted) if _fetches(body)}
    if not fetching:
        return False
    for stage in stages:
        words = _program(stage)
        program = words[0].rsplit("/", 1)[-1] if words else ""
        if program in _SOURCES:
            read = words[1:]
        elif program in _SHELLS:
            runs, index = _shell_operand(words[1:])
            read = words[1 + index : 2 + index]
            stdin = [after for before, after in zip(words, words[1:]) if before == "<"]
            if any(substituted[int(number)][0] == "<(" for word in stdin for number in word.split("\x00")[1::2]
                   if number in fetching):
                return True
        else:
            continue
        for word in read:
            for number in word.split("\x00")[1::2]:
                if number in fetching and (substituted[int(number)][0] == "<(" or program in _SOURCES or runs):
                    return True
    return False


def segment_risks(segment: str, depth: int = 0) -> tuple[str, ...]:
    """The risks of the programs `segment` runs, in table order within each, once each; a shell a download or decoded
    text is piped into, or a download handed to what runs it (`_runs_download`), is `REMOTE_SCRIPT` or
    `DECODED_SCRIPT`. A shell's `-c` script and each substitution's commands are read the same way, `_DEPTH` deep."""
    masked, substituted = _substitutions(segment)
    stages = _stages(masked)
    found: list[str] = []
    inner = [body for _, body in substituted]
    fetched = decoded = False
    previous = ""
    for stage in stages:
        words = _program(stage)
        program = words[0].rsplit("/", 1)[-1] if words else ""
        check = RISKS.get(program)
        risks = check(words[1:]) if check else []
        if program in _SHELLS:
            risks += [REMOTE_SCRIPT] * fetched + [DECODED_SCRIPT] * decoded
            script = _shell_script(words[1:])
            inner += [script] if script else []
        found.extend(risk for risk in risks if risk not in found)
        fetched = fetched or program in _FETCHERS
        decoded = decoded or _decodes(program, words[1:], previous)
        previous = program
    if REMOTE_SCRIPT not in found and _runs_download(stages, substituted):
        found.append(REMOTE_SCRIPT)
    for text in inner if depth < _DEPTH else ():
        for _, read, _ in _scan(text):
            found.extend(risk for risk in segment_risks(read, depth + 1) if risk not in found)
    return tuple(found)


def _head(segment: str) -> str:
    """The first program `segment` runs, or `NAME=` for a command that only assigns."""
    stages = _stages(segment)
    words = stages[0] if stages else []
    program = next((word for word in words if not _is_assignment(word)), "")
    if program:
        return program
    return words[0].partition("=")[0] + "=" if words else segment.split(maxsplit=1)[0]


def _git_folds(args: list[str]) -> bool:
    """Whether `git` with `args` may fold: a `GIT_FOLDABLE` subcommand that writes no file (`--output`) and runs no
    program of an option's choosing (`-c`, `--config-env`, `--exec-path`, `--ext-diff`), and no risk found."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index].partition("=")[0] in _GIT_RUNS:
            return False
        index += 2 if args[index] in _GIT_VALUE_OPTIONS else 1
    sub, rest = (args[index], args[index + 1 :]) if index < len(args) else ("", [])
    if sub == "worktree":
        sub = " ".join(["worktree", *rest[:1]])
    elif sub == "branch":
        listing = "--list" in rest or "-l" in rest
        if not all(arg in _GIT_BRANCH_LISTS or (listing and not arg.startswith("-")) for arg in rest):
            return False
    elif sub == "remote" and not set(rest) <= {"-v", "--verbose"}:
        return False
    if any(arg.startswith(("--output", "--ext-diff")) for arg in rest):
        return False
    return sub in GIT_FOLDABLE and not _git(args)


def _program_folds(stage: list[str]) -> bool:
    """Whether the pipe stage `stage` only assigns, or runs a program that changes nothing (`FOLDABLE`, `_git_folds`,
    read-only gh) with no assignment in front of it (`LD_PRELOAD=…`, `PAGER=…` choose what it runs)."""
    if all(_is_assignment(word) for word in stage):
        return True
    if _is_assignment(stage[0]):
        return False
    program = stage[0].rsplit("/", 1)[-1]
    if program == "git":
        return _git_folds(stage[1:])
    if program == "gh":
        return tuple(stage[1:3]) in GH_READ_ONLY and not {"--show-token", "-t"} & set(stage)
    return program in FOLDABLE


def _writes(stage: list[str]) -> bool:
    """Whether `stage` redirects output into a file (`> f`, `>> f`, `>& f`); a descriptor (`2>&1`, `>&2`, `>&-`) and
    `/dev/null` are none."""
    for index, word in enumerate(stage):
        if ">" in word:
            target = word.rpartition(">")[2]
            descriptor = target.startswith("&")
            target = target.removeprefix("&") or (stage[index + 1] if index + 1 < len(stage) else "")
            if not ((descriptor and (target.isdigit() or target == "-")) or target == "/dev/null"):
                return True
    return False


def _foldable(read: str) -> bool:
    """Whether the command `read` may fold out of sight: every stage's program changes nothing (`_program_folds`), no
    stage writes a file, nothing runs more than the words say (a substitution, a background job, a here-document),
    and no quoted text reads as a risk or names `rm`, since Hermes' patterns match inside quotes."""
    if any(text in read for text in _OPAQUE_TEXT) or "<<" in read:
        return False
    for index, char in enumerate(read):
        if char == "&" and read[index - 1 : index] not in ("&", ">", "<", "|") and read[index + 1 : index + 2] not in ("&", ">"):
            return False  # a background job: `a & b` runs two commands
    spaced = read
    for char in _WORD_BREAKS:
        spaced = spaced.replace(char, " ")
    if any(word.rsplit("/", 1)[-1] == "rm" for word in spaced.split()):
        return False
    stages = _stages(read)
    if any(segment_risks(word) for stage in stages for word in stage if any(char.isspace() for char in word)):
        return False
    return all(_program_folds(stage) and not _writes(stage) for stage in stages)


def _sets_state(read: str) -> bool:
    """Whether the command `read` decides what a later command acts on: it moves the shell (`_MOVES`) or sets a
    variable (`T=/`, `printf -v T /`, `${T:=/}`)."""
    start = read.find("${")
    while start >= 0:  # `${NAME=…}` or `${NAME:=…}` assigns NAME when it is unset
        end = start + 2
        while end < len(read) and (read[end].isalnum() or read[end] == "_"):
            end += 1
        if end > start + 2 and read.startswith(("=", ":="), end):
            return True
        start = read.find("${", end)
    for stage in _stages(read):
        program = stage[0].rsplit("/", 1)[-1]
        if program in _MOVES or all(_is_assignment(word) for word in stage):
            return True
        if program == "printf" and any(word.startswith("-v") for word in stage[1:]):
            return True
    return False


def _defined(scanned: list[tuple[str, str, bool]]) -> set[str]:
    """The names the line defines as a function (`f() {`, `function f`) or an alias (`alias f=…`)."""
    names: set[str] = set()
    for _, read, _ in scanned:
        if "()" in read and read.partition("()")[0].split():
            names.add(read.partition("()")[0].split()[-1])
        for stage in _stages(read):
            if stage[0] == "function" and len(stage) > 1:
                names.add(stage[1])
            if stage[0] == "alias":
                names.update(word.partition("=")[0] for word in stage[1:])
    return names


def segments(command: str) -> list[Segment]:
    """Each command of `command` (`split_commands`) with its first program, its risks and whether it may fold (a call
    to a function or alias the line defines never does, nor a directory change or an assignment with a command
    listed after it: `cd ~` and `T=/` decide what `rm -rf "$T"/*` deletes)."""
    scanned = _scan(command)
    defined = _defined(scanned)
    found = [Segment(text, _head(read), segment_risks(read),
                     closed and _foldable(read) and not {word for stage in _stages(read) for word in stage} & defined)
             for text, read, closed in scanned]
    listed = False  # a command after this one is listed
    for index in range(len(found) - 1, -1, -1):
        if listed and found[index].foldable and _sets_state(scanned[index][1]):
            found[index] = replace(found[index], foldable=False, sets_state=True)
        listed = listed or not found[index].foldable
    return found


def _wordings(risk: str) -> set[str]:
    """The ways `risk` is named, OMH's and Hermes', ignoring case."""
    return {risk.casefold(), *(name.casefold() for name in HERMES_NAMES.get(risk, ()))}


def names_a_found_risk(found: list[Segment], description: str) -> bool:
    """Whether Hermes' `description` names a risk found in `found`, so the command it flagged is drawn as risky."""
    named = description.strip().casefold()
    return any(named in _wordings(risk) for segment in found for risk in segment.risks)


def unnamed_risks(found: list[Segment], description: str) -> list[str]:
    """The risks in `found`, once each in order, without the one Hermes named (`description`, ignoring case)."""
    named = description.strip().casefold()
    risks: list[str] = []
    for segment in found:
        for risk in segment.risks:
            if risk not in risks and named not in _wordings(risk):
                risks.append(risk)
    return risks
