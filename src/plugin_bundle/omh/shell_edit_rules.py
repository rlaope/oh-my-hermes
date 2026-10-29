"""Built-in shell-edit rule: refuse a terminal command that edits a source file in place.

A model with `terminal` can change code with `sed -i`, `perl -i`, a
`python -c` that rewrites a file, or a redirect onto an existing file. The
change then never passes through the edit tools, so it is not exact, not
shown as a diff in the tool record, and easy to over-match (a `sed` over every
`*.py` file renames a comment and a method along with the function). This rule
refuses that one call at the ``pre_tool_call`` seam with a block directive
(the message becomes the tool result the model reads) and names the edit tool
to use instead. It is the built-in sibling of the person's own
``toolcall_rules``, which run first.

What is refused, on a ``terminal`` call only, matched on shell segments parsed
with ``shlex`` rather than on raw substrings:

- an in-place editor (`sed -i`, `perl -i`, `ruby -i`, `gawk -i inplace`) whose
  targets are not all shown to be non-source or generated files;
- a `python -c` program, or a `python` reading a heredoc, that writes a file
  and names an existing source file;
- a redirect (`>`, `>>`, `>|`, `&>`) or `tee` onto an existing source file.

Never refused: reads, searches, tests, any `git` command, new files, files
that are not source code (answer JSON, logs, data), and anything under a
generated directory such as `build/`. A command the parser cannot read is let
through: the rule fails open, like the person's own rules.

Setting: env `OMH_SHELL_EDIT_RULES` (on/off) wins over the profile setting
`plugins.entries.omh.settings.shell_edit_rules`; with neither, the rule is
off. The gateway runs this hook in its own process, so the profile setting is
the switch that reaches it; the env value is for a gateway started by hand.
"""

from __future__ import annotations

from . import runtime_paths

import ast
import os
import re
import shlex
from pathlib import Path
from typing import Final

SETTING_NAME: Final = "shell_edit_rules"
ENV_NAME: Final = "OMH_SHELL_EDIT_RULES"
DEFAULT_ENABLED: Final = False

TERMINAL_TOOL: Final = "terminal"

# Code a person edits by hand. Data and prose (json, yaml, toml, md, txt, csv,
# log) are not here: writing them from the shell is ordinary work, and the
# benchmark answer file is JSON.
SOURCE_SUFFIXES: Final = frozenset({
    ".py", ".pyi", ".pyx", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".vue", ".svelte", ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".groovy", ".swift",
    ".m", ".mm", ".c", ".h", ".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx", ".cs", ".fs",
    ".rb", ".php", ".pl", ".pm", ".lua", ".dart", ".ex", ".exs", ".erl", ".hs", ".ml",
    ".clj", ".r", ".jl", ".zig", ".nim", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".sql",
})
# A path with one of these components is build output or an environment, not
# hand-written source: regenerating a file there from the shell is the point.
GENERATED_DIRS: Final = frozenset({
    "build", "dist", "target", "node_modules", ".venv", "venv", "__pycache__", ".tox",
    "site-packages", ".mypy_cache", ".pytest_cache",
})

MAX_COMMAND_CHARS: Final = 20_000
_MAX_NESTING: Final = 2

_CONTROL: Final = frozenset({";", "&&", "||", "|", "&", "|&", ";;", "(", ")", ";&", ";;&"})
_WRITE_REDIRECTS: Final = frozenset({">", ">>", ">|", "&>", "&>>"})
_OTHER_REDIRECTS: Final = frozenset({"<", "<<<", "<>", ">&", "<&", ">>&"})
_KEYWORDS: Final = frozenset({"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "time"})
_SIMPLE_WRAPPERS: Final = frozenset({"command", "builtin", "exec", "nohup", "stdbuf", "caffeinate"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"(?<!<)<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_.-]*)\2")
_PYTHON = re.compile(r"python(\d+(\.\d+)?)?")
_PY_WRITE_MODE = re.compile(r"[wax+]")
_PY_WRITE_TEXT = re.compile(r"\.(write_text|write_bytes)\(|\bopen\([^)]*['\"][rb]*[wax+]")
_ON = ("1", "true", "on", "yes")
_OFF = ("0", "false", "off", "no")

_REFUSAL: Final = (
    "[OMH shell-edit rule] Not run: {what} would change {target} in place from the terminal. "
    "Change existing source files with the `patch` tool (or `write_file` to replace a whole file), "
    "so the edit is exact and shows in the tool record. The terminal is still the place to read, "
    "search, run tests, use git, and write new or generated files; do not route this edit through "
    "another shell command."
)


def shell_edit_rules_enabled(hermes_home: str = "") -> bool:
    """Env `OMH_SHELL_EDIT_RULES` when set to on/off, else the profile setting, else the default."""
    env = os.environ.get(ENV_NAME, "").strip().lower()
    if env in _ON:
        return True
    if env in _OFF:
        return False
    try:
        home = Path(hermes_home) if hermes_home else runtime_paths.default_hermes_home()
        value = runtime_paths.plugin_setting_text((home / "config.yaml").read_text(encoding="utf-8"), SETTING_NAME)
    except (OSError, UnicodeError, ValueError, RuntimeError):
        # `RuntimeBindingError` is a ValueError. A setting OMH cannot read is the default.
        return DEFAULT_ENABLED
    if value is None:
        return DEFAULT_ENABLED
    value = value.strip().lower()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    return DEFAULT_ENABLED


def shell_edit_directive(
    *, tool_name: object, tool_input: object, task_id: object = "", hermes_home: str = "",
) -> dict[str, str] | None:
    """The block directive for a terminal call that edits a source file in place, or None."""
    if str(tool_name or "").strip() != TERMINAL_TOOL or not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND_CHARS:
        return None
    if not shell_edit_rules_enabled(hermes_home):
        return None
    base = _base_dir(task_id, tool_input.get("workdir"))
    found = shell_edit_in_command(command, base)
    if found is None:
        return None
    what, target = found
    return {"action": "block", "message": _REFUSAL.format(what=what, target=target)}


def shell_edit_in_command(command: str, base: Path | None, depth: int = 0) -> tuple[str, str] | None:
    """`(what, target)` for the first in-place source edit the command makes, or None."""
    text, bodies = _split_heredocs(command)
    cwd = base
    for segment in _segments(_tokens(text)):
        words, redirects, heredoc_count = _parse_segment(segment)
        heredoc = bodies.pop(0) if heredoc_count and bodies else None
        for _extra in range(max(heredoc_count - 1, 0)):
            if bodies:
                bodies.pop(0)
        name, args, via = _unwrap(words)
        if name == "cd":
            cwd = _cd(cwd, args)
            continue
        if name == "git":
            continue
        for operator, target in redirects:
            if operator in _WRITE_REDIRECTS and _is_existing_source(target, cwd):
                return (f"`{operator}` redirection", target)
        found = _command_edit(name, args, via, heredoc, cwd, depth)
        if found is not None:
            return found
    return None


def _command_edit(
    name: str, args: list[str], via: str, heredoc: str | None, cwd: Path | None, depth: int,
) -> tuple[str, str] | None:
    if name in ("sed", "gsed"):
        targets = _sed_targets(args)
        return _in_place("`sed -i`", targets, via)
    if name in ("perl", "ruby"):
        targets = _perl_targets(args)
        return _in_place(f"`{name} -i`", targets, via)
    if name in ("awk", "gawk"):
        targets = _awk_targets(args)
        return _in_place("`awk -i inplace`", targets, via)
    if name == "tee":
        for target in (arg for arg in args if not arg.startswith("-")):
            if _is_existing_source(target, cwd):
                return ("`tee`", target)
        return None
    if _PYTHON.fullmatch(name):
        code = _python_code(args, heredoc)
        if code is not None:
            target = _python_write_target(code, cwd)
            if target is not None:
                return ("a `python` program writing a file", target)
        return None
    if name in ("bash", "sh", "zsh") and depth < _MAX_NESTING:
        inner = _option_value(args, "-c")
        if inner is not None:
            return shell_edit_in_command(inner, cwd, depth + 1)
    return None


def _in_place(what: str, targets: list[str] | None, via: str) -> tuple[str, str] | None:
    """In-place editors change files that exist by definition; refuse unless every target is not source."""
    if targets is None:
        return None
    if via or not targets:
        return (what, "files chosen at run time")
    for target in targets:
        if "$" in target or "`" in target or target == "{}":
            return (what, "files chosen at run time")
        if _is_source(target):
            return (what, target)
    return None


def _sed_targets(args: list[str]) -> list[str] | None:
    """File operands of an in-place `sed`, or None when it is not in place."""
    in_place = False
    script_given = False
    operands: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            operands.extend(args[index:])
            break
        if arg.startswith("--"):
            if arg == "--in-place" or arg.startswith("--in-place="):
                in_place = True
            elif arg in ("--expression", "--file"):
                script_given = True
                index += 1
            elif arg.startswith(("--expression=", "--file=")):
                script_given = True
            continue
        if arg.startswith("-") and len(arg) > 1:
            letters = arg[1:]
            for position, letter in enumerate(letters):
                if letter == "i":
                    in_place = True
                    if arg == "-i" and index < len(args) and _looks_like_suffix(args[index]):
                        index += 1  # BSD `sed -i '' ...` / `sed -i .bak ...`
                    break
                if letter in "ef":
                    script_given = True
                    if position == len(letters) - 1:
                        index += 1
                    break
                if letter == "l":
                    if position == len(letters) - 1:
                        index += 1
                    break
            continue
        operands.append(arg)
    if not in_place:
        return None
    return operands if script_given else operands[1:]


def _perl_targets(args: list[str]) -> list[str] | None:
    in_place = False
    script_given = False
    operands: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            operands.extend(args[index:])
            break
        if arg.startswith("-") and len(arg) > 1 and not arg.startswith("--"):
            for position, letter in enumerate(arg[1:]):
                if letter == "i":
                    in_place = True
                    break  # the rest of the cluster is the backup suffix
                if letter in "eE":
                    script_given = True
                    if position == len(arg) - 2:
                        index += 1
                    break
                if letter in "IMmdDxC":
                    break
            continue
        operands.append(arg)
    if not in_place:
        return None
    return operands if script_given else operands[1:]


def _awk_targets(args: list[str]) -> list[str] | None:
    in_place = any(
        (arg in ("-i", "--include") and index + 1 < len(args) and args[index + 1] == "inplace")
        or arg in ("-iinplace", "--include=inplace")
        for index, arg in enumerate(args)
    )
    if not in_place:
        return None
    operands: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in ("-i", "--include", "-f", "-v", "-F"):
            skip = True
            continue
        if arg.startswith("-"):
            continue
        operands.append(arg)
    return operands[1:]


def _looks_like_suffix(arg: str) -> bool:
    return arg == "" or (arg.startswith(".") and "/" not in arg and len(arg) <= 12 and " " not in arg)


def _python_code(args: list[str], heredoc: str | None) -> str | None:
    """The program a python call runs from `-c` or a heredoc on stdin; None for a script or module."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-c":
            return args[index + 1] if index + 1 < len(args) else None
        if arg.startswith("-c") and len(arg) > 2:
            return arg[2:]
        if arg in ("-m",) or (arg.startswith("-m") and len(arg) > 2):
            return None
        if arg in ("-W", "-X"):
            index += 2
            continue
        if arg == "-":
            return heredoc
        if not arg.startswith("-"):
            return None  # a script file
        index += 1
    return heredoc


def _python_write_target(code: str, cwd: Path | None) -> str | None:
    """An existing source file a python program writes, or None.

    The written paths are read from the program when they are literals, or names bound to
    literals (`p = 'x.py'`, `for p in ['a.py', 'b.py']`). A write whose path cannot be read that
    way falls back to the source files the program names at all.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        tree = None
    if tree is None:
        if not _PY_WRITE_TEXT.search(code):
            return None
        return _first_existing_source(re.findall(r"['\"]([^'\"\n]+)['\"]", code), cwd)
    bound = _bound_literals(tree)
    targets, unknown = _ast_write_targets(tree, bound)
    found = _first_existing_source(targets, cwd)
    if found is not None or not unknown:
        return found
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    return _first_existing_source(literals, cwd)


def _first_existing_source(paths: list[str], cwd: Path | None) -> str | None:
    return next((path for path in paths if len(path) < 512 and _is_existing_source(path, cwd)), None)


def _literal_paths(node: ast.AST | None, bound: dict[str, list[str]]) -> list[str] | None:
    """The path strings an expression stands for, or None when it is not that simple."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return bound.get(node.id)
    if isinstance(node, ast.Call) and node.args and _call_name(node) in ("Path", "PurePath", "PosixPath"):
        return _literal_paths(node.args[0], bound)
    if isinstance(node, (ast.List, ast.Tuple)):
        paths: list[str] = []
        for element in node.elts:
            found = _literal_paths(element, bound)
            if found is None:
                return None
            paths.extend(found)
        return paths
    return None


def _bound_literals(tree: ast.AST) -> dict[str, list[str]]:
    bound: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found = _literal_paths(node.value, bound)
            if found is not None:
                bound.setdefault(node.targets[0].id, []).extend(found)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            found = _literal_paths(node.iter, bound)
            if found is not None:
                bound.setdefault(node.target.id, []).extend(found)
    return bound


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _ast_write_targets(tree: ast.AST, bound: dict[str, list[str]]) -> tuple[list[str], bool]:
    """Paths the program writes, and whether some write's path could not be read."""
    targets: list[str] = []
    unknown = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        path_node: ast.AST | None = None
        if name in ("write_text", "write_bytes") and isinstance(node.func, ast.Attribute):
            path_node = node.func.value
        elif name == "open":
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "os":
                unknown = True  # os.open with flags
                continue
            method = isinstance(func, ast.Attribute) and not (
                isinstance(func.value, ast.Name) and func.value.id in ("io", "codecs", "builtins"))
            position = 0 if method else 1
            mode = node.args[position] if len(node.args) > position else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "mode"), None)
            if mode is None:
                continue  # the default mode reads
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and not _PY_WRITE_MODE.search(mode.value):
                continue
            if method:
                path_node = func.value  # Path(...).open("w")
            else:
                path_node = node.args[0] if node.args else next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "file"), None)
        elif name == "input" and any(keyword.arg == "inplace" for keyword in node.keywords):
            path_node = node.args[0] if node.args else None
        else:
            continue
        found = _literal_paths(path_node, bound)
        if found is None:
            unknown = True
        else:
            targets.extend(found)
    return targets, unknown


def _is_source(path: str) -> bool:
    parts = [part for part in re.split(r"[\\/]", path) if part]
    if not parts or any(part in GENERATED_DIRS for part in parts[:-1]):
        return False
    return Path(parts[-1]).suffix.lower() in SOURCE_SUFFIXES


def _is_existing_source(path: str, cwd: Path | None) -> bool:
    if not path or "$" in path or "`" in path or path.startswith(("&", "/dev/")) or not _is_source(path):
        return False
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        if cwd is None:
            return False
        candidate = cwd / candidate
    try:
        return candidate.is_file()
    except OSError:
        return False


def _cd(cwd: Path | None, args: list[str]) -> Path | None:
    target = next((arg for arg in args if not arg.startswith("-")), None)
    if target is None or "$" in target:
        return cwd
    candidate = Path(os.path.expanduser(target))
    if not candidate.is_absolute():
        if cwd is None:
            return None
        candidate = cwd / candidate
    try:
        return candidate if candidate.is_dir() else cwd
    except OSError:
        return cwd


def _base_dir(task_id: object, workdir: object) -> Path | None:
    root = _workspace_root(task_id)
    if isinstance(workdir, str) and workdir.strip():
        path = Path(os.path.expanduser(workdir.strip()))
        if path.is_absolute():
            return path
        return (Path(root) / path) if root else None
    return Path(root) if root else None


def _workspace_root(task_id: object) -> str | None:
    """The session's working directory as Hermes' own file tools resolve it (``TERMINAL_CWD`` fallback)."""
    try:
        from tools.file_tools_paths import _resolve_base_dir

        return str(_resolve_base_dir(str(task_id or "default"), container_paths=False))
    except Exception:  # noqa: BLE001 - classified in tests/test_broad_exception_policy.py
        return os.environ.get("TERMINAL_CWD") or None


def _split_heredocs(command: str) -> tuple[str, list[str]]:
    """The command with heredoc bodies cut out, and the bodies in order of appearance."""
    lines = command.split("\n")
    kept: list[str] = []
    bodies: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        for match in _HEREDOC.finditer(line):
            strip_tabs, delimiter = match.group(1) == "-", match.group(3)
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index].lstrip("\t") if strip_tabs else lines[index]
                index += 1
                if candidate == delimiter:
                    break
                body.append(lines[index - 1])
            bodies.append("\n".join(body))
    joined = "\n".join(kept)
    return joined.replace("\\\n", " "), bodies


def _tokens(text: str) -> list[str]:
    """Shell words and operators; a line that does not close its quotes joins the next one.

    Each parsed chunk ends with a `;`, so a newline separates commands as it does in a shell.
    A tail that never parses is dropped: the rule fails open on what it cannot read.
    """
    tokens: list[str] = []
    pending = ""
    for line in text.split("\n"):
        pending = f"{pending}\n{line}" if pending else line
        lexer = shlex.shlex(pending, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            chunk = list(lexer)
        except ValueError:
            continue
        tokens.extend(chunk)
        tokens.append(";")
        pending = ""
    return tokens


def _segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _CONTROL:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _parse_segment(segment: list[str]) -> tuple[list[str], list[tuple[str, str]], int]:
    """Command words, write redirects as (operator, target), and how many heredocs feed it."""
    words: list[str] = []
    redirects: list[tuple[str, str]] = []
    heredocs = 0
    index = 0
    while index < len(segment):
        token = segment[index]
        index += 1
        if token == "<<":
            heredocs += 1
            index += 1  # the delimiter word
            continue
        if token in _WRITE_REDIRECTS or token in _OTHER_REDIRECTS:
            target = segment[index] if index < len(segment) else ""
            index += 1
            if token in _WRITE_REDIRECTS:
                redirects.append((token, target))
            continue
        if token.isdigit() and index < len(segment) and segment[index] in (_WRITE_REDIRECTS | _OTHER_REDIRECTS):
            continue  # the fd number of `2>` / `1>>`
        words.append(token)
    return words, redirects, heredocs


def _unwrap(words: list[str]) -> tuple[str, list[str], str]:
    """`(command name, its arguments, wrapper that supplies its files)` past assignments and wrappers."""
    index = 0
    via = ""
    while index < len(words):
        word = words[index]
        name = word.rsplit("/", 1)[-1]
        if word in _KEYWORDS or _ASSIGNMENT.match(word):
            index += 1
            continue
        if name in _SIMPLE_WRAPPERS:
            index += 1
            continue
        if name in ("sudo", "env", "nice", "timeout", "xargs", "parallel"):
            if name in ("xargs", "parallel"):
                via = name
            index = _skip_wrapper_options(words, index + 1, name)
            continue
        if name == "uv" and index + 1 < len(words) and words[index + 1] == "run":
            index = _skip_wrapper_options(words, index + 2, "uv")
            continue
        if name == "find":
            exec_at = next((i for i in range(index, len(words)) if words[i] in ("-exec", "-execdir")), None)
            if exec_at is None:
                return name, words[index + 1:], via
            end = next((i for i in range(exec_at + 1, len(words)) if words[i] in (";", "+")), len(words))
            inner = words[exec_at + 1:end]
            if not inner:
                return name, [], via
            names = [words[i + 1] for i in range(index, exec_at) if words[i] in ("-name", "-iname") and i + 1 < exec_at]
            if names and not any(_is_source(pattern) for pattern in names):
                return "find", [], via  # `-exec` over files named as data, not source
            inner_name, inner_args, _ = _unwrap(inner)
            return inner_name, inner_args, "find"
        return name, words[index + 1:], via
    return "", [], via


_WRAPPER_VALUE_OPTIONS: Final = {
    "sudo": frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"}),
    "env": frozenset({"-u", "-C", "-S"}),
    "nice": frozenset({"-n"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "xargs": frozenset({"-I", "-n", "-P", "-L", "-d", "-E", "-s", "-a", "-J", "-R"}),
    "parallel": frozenset({"-j", "-I", "-n"}),
    "uv": frozenset({"--with", "--python", "-p", "--project", "--directory", "--group", "--extra", "--env-file"}),
}


def _skip_wrapper_options(words: list[str], index: int, name: str) -> int:
    takes_value = _WRAPPER_VALUE_OPTIONS.get(name, frozenset())
    while index < len(words):
        word = words[index]
        if word == "--":
            return index + 1
        if word in takes_value:
            index += 2
            continue
        if word.startswith("-") or (name == "env" and _ASSIGNMENT.match(word)):
            index += 1
            continue
        if name == "timeout" and re.fullmatch(r"\d+(\.\d+)?[smhd]?", word):
            index += 1
            continue
        if name == "nice" and re.fullmatch(r"-?\d+", word):
            index += 1
            continue
        return index
    return index


def _option_value(args: list[str], option: str) -> str | None:
    for index, arg in enumerate(args):
        if arg == option and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("-") and not arg.startswith("--") and arg.endswith(option[1:]) and index + 1 < len(args):
            return args[index + 1]  # `bash -lc '...'`
    return None
