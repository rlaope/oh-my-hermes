from __future__ import annotations

from .. import runtime_paths

import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePath
import re
import shlex
import subprocess
import sys
import tempfile
from typing import Any, NamedTuple

from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, observe_plugin_tool_call

OMH_EVIDENCE_SCHEMA = {
    "name": "omh_gather_evidence",
    "description": (
        "Run bounded allowlisted local verification probes and return structured evidence. "
        "This is explicit verification evidence only, not executor dispatch or coding execution."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Commands to run. Each command must match an allowlisted token prefix.",
            },
            "project_root": {
                "type": "string",
                "description": "Root that bounds workdir: the host working directory (default) or inside it.",
            },
            "workdir": {
                "type": "string",
                "description": "Working directory for commands. Must stay inside project_root.",
            },
            "timeout": {
                "type": "integer",
                "description": "Per-command timeout in seconds. Default 60, capped at 180.",
            },
            "truncate": {
                "type": "integer",
                "description": "Maximum output characters per command. Keeps the tail. Default 4000, capped at 20000.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
        "required": ["commands"],
    },
}

SCHEMA_VERSION = "omh_evidence_probe/v1"
_MAX_COMMANDS = 8
_MAX_TIMEOUT_SECONDS = 180
_MAX_TRUNCATE_CHARS = 20_000
_DEFAULT_TIMEOUT_SECONDS = 60
_DEFAULT_TRUNCATE_CHARS = 4_000
_SHELL_METACHAR_RE = re.compile(r"[\n\r;&|`$<>(){}]")
# After a `-m unittest` prefix only these options may follow, plus, when the
# prefix names no test itself, a selection of test*.py modules inside workdir
# (`_unittest_selection_rejection`). Never `discover`, a start/top-level
# directory, or a module from outside workdir: a probe imports only the code
# default discovery from workdir could reach.
_UNITTEST_FLAGS = frozenset({
    "-v", "--verbose", "-q", "--quiet", "-f", "--failfast",
    "-b", "--buffer", "-c", "--catch", "--locals",
})
_UNITTEST_VALUE_FLAGS = frozenset({"-k"})
_UNITTEST_DOTTED_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# The runner's own summary line; the last one in the output is the runner's.
_UNITTEST_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)
# Python 3.12+ unittest and pytest both exit 5 when no test ran.
_NO_TESTS_RAN_EXIT_CODE = 5
# `git diff` options that write a file, run a configured external program, or
# read paths outside the repository. Every other argument that is not an option
# must name a path inside workdir: with two paths and one of them outside the
# repository, git switches to `--no-index` on its own and prints both files.
# That bounds filesystem paths only; a `:/` pathspec or `<rev>:<path>` still
# reaches the whole repository, which may extend above project_root.
_GIT_DIFF_REFUSED = ("--output", "--ext-diff", "--textconv", "--no-index")


class _OptionGrammar(NamedTuple):
    """The argparse options that may follow a prefix whose program opens paths.

    Anything not listed is refused, argparse abbreviations included. The value
    of a `paths` option names a path the program opens, and so does every
    positional argument when `operands` is set (at least one is then
    required); each must stay inside workdir. `refused` only adds the reason.
    """

    flags: frozenset[str] = frozenset()
    values: frozenset[str] = frozenset()
    paths: frozenset[str] = frozenset()
    refused: tuple[tuple[str, str], ...] = ()
    operands: bool = False


# The same options on Python 3.11 through 3.14. With no path compileall
# compiles every directory on sys.path, so a path is required.
_COMPILEALL_GRAMMAR = _OptionGrammar(
    flags=frozenset({"-l", "-f", "-q", "--hardlink-dupes"}),
    values=frozenset({"-r", "-x", "-o", "-j", "--workers", "--invalidation-mode"}),
    paths=frozenset({"-e"}),
    refused=(
        ("-i", "reads more paths from a file or stdin"),
        ("-b", "writes .pyc beside the sources, outside the private pycache"),
        ("-d", "rewrites the source path recorded in the bytecode"),
        ("-s", "rewrites the source path recorded in the bytecode"),
        ("-p", "rewrites the source path recorded in the bytecode"),
    ),
    operands=True,
)
# The omh prefixes with an option that opens a path or writes a file. The
# other shipped omh prefixes have no such option, and argparse refuses one they
# do not define.
_OMH_GRAMMARS = (
    (("omh", "doctor"), _OptionGrammar(
        flags=frozenset({"--json"}),
        values=frozenset({"--language"}),
        refused=(("--profile-isolation", "reads two profile homes named by the caller"),),
    )),
    (("omh", "docs", "workflows"), _OptionGrammar(
        flags=frozenset({"--check"}),
        paths=frozenset({"--output"}),
    )),
    (("omh", "release", "evidence-bundle"), _OptionGrammar(
        # A bare `--verify` reads the canonical bundle; a PATH after it is a
        # positional here, so it is refused.
        flags=frozenset({"--json", "--verify"}),
        values=frozenset({"--version", "--omh-command", "--archive-digest", "--artifact-digest"}),
        paths=frozenset({"--repo-root", "--artifact", "--notes-file"}),
        refused=(("--write", "writes the bundle into the OMH home"),),
    )),
)
_DEFAULT_ALLOWLIST = (
    "omh --help",
    "omh doctor",
    "omh probe",
    "omh harness validate",
    "omh docs workflows --check",
    "omh release checklist",
    "omh release product-readiness",
    "omh release evidence-bundle",
    "python -m unittest",
    "python3 -m unittest",
    "python -m compileall",
    "python3 -m compileall",
    # No `uv run` prefix: `uv run` syncs and builds the project environment
    # (resolving indexes, running build backends) before the named command
    # starts, which is code execution and network access this probe cannot
    # bound by argv.
    "git diff --check",
    # Read-only prefix for the tests-first red-commit tamper probe
    # (`git diff <red-commit>.. -- <test paths>`), named by
    # `ulw-work/references/tdd-red-green.md`. Kept alongside the narrower
    # "git diff --check" entry for config compatibility.
    "git diff",
)


def omh_evidence_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_gather_evidence", args, kwargs)
    commands = args.get("commands", [])
    if not isinstance(commands, list) or not commands:
        return _json(_with_observation({"error": "commands must be a non-empty list"}, observation))
    if len(commands) > _MAX_COMMANDS:
        return _json(_with_observation({"error": f"too many commands: {len(commands)} > {_MAX_COMMANDS}"}, observation))

    try:
        project_root = _project_root(args, kwargs)
        if isinstance(project_root, dict):
            return _json(_with_observation(project_root, observation))
        workdir = _workdir(args, project_root)
    except runtime_paths.RuntimeBindingError as exc:
        return _json(_with_observation({"error": str(exc)}, observation))
    if not project_root.is_dir():
        return _json(
            _with_observation(
                {"error": "project_root must be an existing directory", "project_root": str(project_root)},
                observation,
            )
        )
    if isinstance(workdir, dict):
        return _json(_with_observation(workdir, observation))

    timeout = min(_positive_int(args.get("timeout"), _DEFAULT_TIMEOUT_SECONDS), _MAX_TIMEOUT_SECONDS)
    truncate = min(_positive_int(args.get("truncate"), _DEFAULT_TRUNCATE_CHARS), _MAX_TRUNCATE_CHARS)
    allowlist = _allowlist()
    parsed: list[tuple[str, list[str]]] = []
    rejected = []
    for command in commands:
        command_text = str(command or "").strip()
        if not command_text:
            rejected.append({"command": command_text, "reason": "empty command"})
            continue
        if _SHELL_METACHAR_RE.search(command_text):
            rejected.append({"command": command_text, "reason": "shell metacharacters are not allowed"})
            continue
        try:
            tokens = shlex.split(command_text)
        except ValueError as exc:
            rejected.append({"command": command_text, "reason": f"parse failed: {exc}"})
            continue
        reason = _allowlist_rejection(tokens, allowlist, workdir)
        if reason is not None:
            rejected.append({"command": command_text, "reason": reason})
            continue
        parsed.append((command_text, _limit_compileall_symlinks(tokens)))

    results = [_rejected_result(item["command"], item["reason"]) for item in rejected]
    try:
        for command_text, tokens in parsed:
            results.append(_run_command(command_text, tokens, workdir=workdir, timeout=timeout, truncate=truncate))
    except runtime_paths.RuntimeBindingError:
        return _json(_with_observation({"error": "OMH evidence runtime home binding is unavailable"}, observation))

    passed_count = sum(1 for result in results if result.get("passed"))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "workdir": str(workdir),
        "allowlist": list(allowlist),
        "results": results,
        "all_pass": bool(results) and passed_count == len(results),
        "summary": f"{passed_count}/{len(results)} passed",
        "privacy": "command_output_truncated",
        "claim_boundary": (
            "This is explicit local verification evidence only. It is not executor dispatch, "
            "implementation, review, CI, merge, or Hermes runtime-load evidence."
        ),
    }
    return _json(_with_observation(payload, observation))


def _with_observation(payload: dict[str, Any], observation: dict[str, Any] | None) -> dict[str, Any]:
    return attach_public_observation(payload, observation)


def _project_root(args: dict, kwargs: dict) -> Path | dict[str, str]:
    """The requested root, bounded to the host's working directory.

    The model chooses `project_root`, so without this bound an allowlisted
    test runner would execute whatever test code sits in any directory on the
    machine. Both sides are resolved, so a symlink cannot step outside.
    """
    host_cwd = runtime_paths.runtime_cwd()
    value = args.get("project_root") or kwargs.get("project_root") or host_cwd
    if value is None or host_cwd is None:
        raise runtime_paths.RuntimeBindingError("OMH evidence requires a logical project root")
    project_root = runtime_paths.expand_input_path(value).resolve()
    bound = Path(host_cwd).resolve()
    if not project_root.is_relative_to(bound):
        return {"error": "project_root must be the host working directory or inside it",
                "project_root": str(project_root), "host_cwd": str(bound)}
    return project_root


def _workdir(args: dict, project_root: Path) -> Path | dict[str, str]:
    value = str(args.get("workdir") or project_root)
    workdir = runtime_paths.expand_input_path(value).resolve()
    try:
        workdir.relative_to(project_root)
    except ValueError:
        return {"error": "workdir must stay within project_root", "workdir": str(workdir), "project_root": str(project_root)}
    if not workdir.is_dir():
        return {"error": "workdir must be an existing directory", "workdir": str(workdir)}
    return workdir


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _allowlist() -> tuple[str, ...]:
    configured = _read_config_allowlist(Path(__file__).resolve().parents[1] / "config.yaml")
    return tuple(configured or _DEFAULT_ALLOWLIST)


def _read_config_allowlist(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    values: list[str] = []
    in_evidence = False
    in_allowlist = False
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            in_evidence = stripped == "evidence:"
            in_allowlist = False
            continue
        if in_evidence and indent == 2:
            in_allowlist = stripped == "allowlist_prefixes:"
            continue
        if in_evidence and in_allowlist and indent >= 4 and stripped.startswith("- "):
            values.append(_unquote(stripped[2:].strip()))
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _allowlist_rejection(tokens: list[str], allowlist: tuple[str, ...], workdir: Path) -> str | None:
    """None when some allowlist entry admits `tokens`, else the reason to refuse."""
    reason = "command not in allowlist"
    for prefix in allowlist:
        prefix_tokens = prefix.split()
        if not prefix_tokens or tokens[: len(prefix_tokens)] != prefix_tokens:
            continue
        refused = _suffix_rejection(prefix_tokens, tokens[len(prefix_tokens):], workdir)
        if refused is None:
            return None
        reason = refused
    return reason


def _suffix_rejection(prefix_tokens: list[str], suffix: list[str], workdir: Path) -> str | None:
    """Bound the free suffix after a prefix whose program would run it as code
    or open a path it names outside workdir."""
    if _has_pair(prefix_tokens, "-m", "unittest"):
        # An operator entry that already names a test keeps exactly that test.
        selection_allowed = prefix_tokens[-2:] == ["-m", "unittest"]
        index = 0
        while index < len(suffix):
            token = suffix[index]
            if token in _UNITTEST_VALUE_FLAGS and index + 1 < len(suffix):
                index += 2
                continue
            if token not in _UNITTEST_FLAGS:
                # Any other option fails the selection's name grammar.
                refused = _unittest_selection_rejection(token, workdir) if selection_allowed else ""
                if refused is not None:
                    return f"unittest argument not allowed: {token[:80]}" + (f" ({refused})" if refused else "")
            index += 1
    if _has_pair(prefix_tokens, "-m", "compileall"):
        return _grammar_rejection("compileall", _COMPILEALL_GRAMMAR, suffix, workdir)
    for command, grammar in _OMH_GRAMMARS:
        if tuple(prefix_tokens[: len(command)]) == command:
            return _grammar_rejection(" ".join(command), grammar, suffix, workdir)
    if " ".join(prefix_tokens[:2]) == "git diff":
        options_end = False
        for token in suffix:
            if not options_end and token.startswith("-") and token != "-":
                if token == "--":
                    options_end = True
                elif token.split("=", 1)[0] in _GIT_DIFF_REFUSED:
                    return f"git diff option not allowed: {token[:80]}"
                elif not token.startswith("--") and "O" in token:
                    # `-O<file>` reads an order file, also inside a cluster such as `-pO<file>`.
                    return "git diff option not allowed: -O (reads an order file)"
                continue
            refused = _path_rejection("git diff", token, workdir)
            if refused is not None:
                return refused
    return None


def _unittest_selection_rejection(token: str, workdir: Path) -> str | None:
    """None when `token` selects tests that default discovery from workdir runs.

    Two forms, read the way `python -m unittest` reads them: a relative `.py`
    path (`tests/test_x.py`, which unittest turns into `tests.test_x`), or a
    dotted name (`tests.test_x`, `tests.test_x.Case.test_y`). The leading parts
    must be regular packages inside workdir (a directory with `__init__.py`,
    the only kind discovery descends into) and the module a `test*.py` file
    inside workdir, the discovery pattern; what follows it is checked by
    `_unittest_attribute_rejection`. So the selection runs only code bare
    `-m unittest` from workdir would run anyway: a standard-library name, a
    symlink out of workdir, or a module discovery would not run is refused,
    and so is `discover` in every form.
    """
    if token.lower() == "discover":
        return "discover is not allowed"
    if token.lower().endswith(".py"):
        refused = _path_rejection("unittest", token, workdir)
        if refused is not None:
            return refused
        parts = list(PurePath(token[:-3]).parts)
        if not parts or not all(_UNITTEST_DOTTED_NAME_RE.fullmatch(part) and "." not in part for part in parts):
            return "not a test file path"
    elif _UNITTEST_DOTTED_NAME_RE.fullmatch(token):
        parts = token.split(".")
    else:
        return "not a dotted test name"
    # A standard-library package the interpreter may already hold would be
    # imported in place of the workdir one. (`sys.stdlib_module_names` leaves
    # out CPython's own `test` package, which a workdir `test/` shadows.)
    if parts[0] in sys.stdlib_module_names:
        return "names a standard-library module"
    base = workdir
    for index, part in enumerate(parts):
        package, module = base / part, base / f"{part}.py"
        if package.is_dir() and (package / "__init__.py").is_file():
            found = package
        elif module.is_file():
            found = module
        else:
            break
        if not all(Path(os.path.realpath(path)).is_relative_to(workdir)
                   for path in (found, found / "__init__.py") if path.exists()):
            return "resolves outside workdir"
        if found is module:
            if not part.startswith("test"):
                return "names no test*.py module inside workdir"
            return _unittest_attribute_rejection(module, parts[index + 1:])
        base = found
    return "names no test*.py module inside workdir"


def _unittest_attribute_rejection(module: Path, attributes: list[str]) -> str | None:
    """None when `attributes` name what discovery would run in `module`.

    unittest calls any callable a dotted name reaches that is not a TestCase,
    so `tests.test_x.helper` would run a helper and `tests.test_x.os.<f>` a
    function of a module the test imported. Allowed: nothing, a class defined
    at the top of the test file, or such a class and a `test*` method, which
    is the shape discovery itself runs.
    """
    if not attributes:
        return None
    try:
        tree = ast.parse(module.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return "test module cannot be read"
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    if attributes[0] not in classes:
        return "names no class defined in the test module"
    if len(attributes) > 2:
        return "names more than a test class and method"
    if len(attributes) == 2 and not attributes[1].startswith("test"):
        return "names a method that is not test*"
    return None


def _grammar_rejection(program: str, grammar: _OptionGrammar, suffix: list[str], workdir: Path) -> str | None:
    """None when every token of `suffix` fits `grammar`, read the way argparse reads it."""
    refused = dict(grammar.refused)
    operand_count = 0
    options_end = False
    index = 0
    while index < len(suffix):
        token = suffix[index]
        index += 1
        if options_end or token == "-" or not token.startswith("-"):
            if not grammar.operands:
                return f"{program} argument not allowed"
            reason = _path_rejection(program, token, workdir)
            if reason is not None:
                return reason
            operand_count += 1
            continue
        if token == "--":
            options_end = True
            continue
        if token.startswith("--"):
            option, equals, inline = token.partition("=")
            pieces = [(option, inline if equals else None)]
        elif "=" in token:
            # argparse drops the `=` from `-e=DIR` and `-fe=DIR` alike; the
            # token is refused rather than mirrored.
            return f"{program} option not allowed: {token[:2]} with '='"
        else:
            pieces = _short_option_cluster(token, grammar.flags)
        for option, inline in pieces:
            if option in refused:
                return f"{program} option not allowed: {option} ({refused[option]})"
            if option in grammar.flags and inline is None:
                continue
            if option not in grammar.values and option not in grammar.paths:
                return f"{program} option not allowed: {option[:80]}"
            value = inline
            if value is None:
                if index == len(suffix):
                    return f"{program} option needs a value: {option}"
                value = suffix[index]
                index += 1
            if option in grammar.paths:
                reason = _path_rejection(program, value, workdir)
                if reason is not None:
                    return reason
    if grammar.operands and not operand_count:
        return f"{program} needs a path inside workdir"
    return None


def _short_option_cluster(token: str, flags: frozenset[str]) -> list[tuple[str, str | None]]:
    """Split `-fqr5` as argparse does: flags chain, the next option takes the rest as its value."""
    pieces: list[tuple[str, str | None]] = []
    rest = token[1:]
    while rest:
        option, rest = "-" + rest[0], rest[1:]
        if option in flags:
            pieces.append((option, None))
            continue
        pieces.append((option, rest or None))
        break
    return pieces


def _path_rejection(program: str, value: str, workdir: Path) -> str | None:
    """Why `value`, read relative to workdir, could name a path outside it.

    The reason never repeats the value or what it resolves to, so a symlink
    that leads out of workdir does not tell the caller where it leads.
    """
    path = PurePath(value)
    if not value:
        return f"{program} path not allowed: empty"
    if path.anchor or value.startswith("~"):
        return f"{program} path not allowed: absolute or home-relative"
    if ".." in path.parts:
        return f"{program} path not allowed: '..' component"
    try:
        resolved = Path(os.path.realpath(workdir / path))
    except (OSError, ValueError):
        return f"{program} path not allowed: cannot be resolved"
    if not resolved.is_relative_to(workdir):
        return f"{program} path not allowed: resolves outside workdir"
    return None


def _limit_compileall_symlinks(tokens: list[str]) -> list[str]:
    """Add `-e .` after `-m compileall`, so a symlink found below a path
    argument that leads out of workdir is skipped instead of compiled. A
    caller's own `-e DIR` comes later on the command line and wins; it is
    bounded to workdir like every path."""
    for index in range(len(tokens) - 1):
        if tokens[index : index + 2] == ["-m", "compileall"]:
            return [*tokens[: index + 2], "-e", ".", *tokens[index + 2 :]]
    return tokens


def _has_pair(tokens: list[str], first: str, second: str) -> bool:
    return any(tokens[index : index + 2] == [first, second] for index in range(len(tokens) - 1))


def run_verification_command(tokens: list[str], *, workdir: Path, timeout: int) -> dict[str, object]:
    """Run one already-approved argv and say what happened, without judging it.

    The runner only: no allowlist, no metacharacter check, no pass/fail
    verdict. The two callers approve a command differently -- this tool by the
    allowlist below, `omh_team` by the person's plan approval plus its own
    command policy (`omh.workflows.team.validate_team_command`), and for its
    own fixed read-only git reads of a helper's branch by the literal argv in
    `tools/team_tool.py` -- and each needs to tell a command that ran and
    exited non-zero apart from one that never ran, which a bare
    `passed: False` cannot. So the outcome is ``exited`` (with
    ``exit_code``), ``not_found`` or ``timeout``.

    ``shell=False``, no stdin, the minimal child environment, and a private
    pycache are the same for both callers. A `-m compileall` run also gets
    ``PYTHONSAFEPATH`` (honoured from Python 3.11), so a ``compileall.py`` in
    workdir cannot stand in for the stdlib module; `-m unittest` keeps the
    working directory on ``sys.path`` because it imports test modules by name.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="omh-evidence-pycache-") as pycache_dir:
            env = _minimal_child_environment(pycache_dir)
            if _has_pair(tokens, "-m", "compileall"):
                env["PYTHONSAFEPATH"] = "1"
            proc = subprocess.run(
                tokens,
                cwd=str(workdir),
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
    except FileNotFoundError:
        return {"outcome": "not_found", "exit_code": None, "output": ""}
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "exit_code": None, "output": ""}
    return {"outcome": "exited", "exit_code": proc.returncode, "output": (proc.stdout or "") + (proc.stderr or "")}


def _run_command(command_text: str, tokens: list[str], *, workdir: Path, timeout: int, truncate: int) -> dict[str, object]:
    run = run_verification_command(tokens, workdir=workdir, timeout=timeout)
    if run["outcome"] == "not_found":
        return _rejected_result(command_text, f"command not found: {tokens[0] if tokens else command_text}")
    if run["outcome"] == "timeout":
        return _rejected_result(command_text, f"timeout after {timeout}s")
    output = str(run["output"])
    truncated = len(output) > truncate
    no_tests_ran = _no_tests_ran(tokens, run["exit_code"], output)
    result = {
        "command": command_text,
        "exit_code": run["exit_code"],
        "output_tail": output[-truncate:] if truncated else output,
        "truncated": truncated,
        "passed": run["exit_code"] == 0 and not no_tests_ran,
        "evidence_type": "observed_local_command",
    }
    if no_tests_ran:
        result["reason"] = "no tests ran"
    return result


def _no_tests_ran(tokens: list[str], exit_code: object, output: str) -> bool:
    """True when a test runner exited without running a test, which proves nothing.

    Python before 3.12 prints `Ran 0 tests` and exits 0 when unittest finds no
    test; 3.12+ and pytest exit 5 instead. Read from the whole output, before
    truncation, and from the runner's own (last) summary line.
    """
    if _has_pair(tokens, "-m", "unittest"):
        if exit_code == _NO_TESTS_RAN_EXIT_CODE:
            return True
        counts = _UNITTEST_RAN_RE.findall(output)
        return exit_code == 0 and bool(counts) and int(counts[-1]) == 0
    if _has_pair(tokens, "-m", "pytest") or (tokens[:1] == ["pytest"]):
        return exit_code == _NO_TESTS_RAN_EXIT_CODE
    return False


def _minimal_child_environment(pycache_dir: str) -> dict[str, str]:
    """Return only non-secret process basics for allowlisted evidence probes."""

    return {
        "HOME": str(Path.home()),
        "OMH_HOME": str(runtime_paths.default_omh_home()),
        "HERMES_HOME": str(runtime_paths.default_hermes_home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": pycache_dir,
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
    }


def _rejected_result(command: str, reason: str) -> dict[str, object]:
    return {
        "command": command,
        "exit_code": -1,
        "output_tail": reason,
        "truncated": False,
        "passed": False,
        "evidence_type": "rejected",
    }


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
