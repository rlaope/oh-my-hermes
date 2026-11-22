"""User-declared fanout executors, read only from the operator's OMH home.

A person who prefers another headless coding CLI declares it once:

    schema_version = 1

    [executors.my-agent]
    label = "My Agent"
    argv = ["my-agent", "run", "--", "{prompt}"]

and `omh coding fanout dispatch --owner my-agent` hands a unit to it with the
same lane guarantees the built-in owners get. This module is the whole trust
boundary for that file: it reads one path under the resolved OMH home, holds
the file to a closed schema, and reports a bad entry with a closed reason
instead of raising into a dispatch.

Rules this module exists to enforce (design: `ext-harness-specs/design.md`
§1-§3):

* **One location, never discovered.** `<omh_home>/routing/executors.toml`,
  next to `dispatch-models.json`. Nothing here walks the repository, its
  parents or the cwd, so a checked-in file can never become an executor.
* **Data, not a command string.** Every vector is a list of literal argv
  tokens with placeholders occupying a whole element: exactly one of
  `{prompt}`/`{prompt_file}` in `argv`, one matching placeholder per optional
  fragment. A shell string (`sh -c "..."`) is refused, and so is any
  interpreter or launcher as the program, because the value omh would hand a
  process must not be a language in which a caller's prompt becomes code.
* **A bad entry never costs the good ones.** Parsing a contract, listing it or
  reading its status spawns and probes nothing; an unreadable, oversized,
  malformed or wrongly-versioned file yields an empty registry plus a
  diagnostic, and one invalid entry is omitted while its valid siblings load.
* **Identity is a plain id.** `[a-z][a-z0-9-]{1,31}`, no case folding and no
  aliases; a user id may not shadow a built-in owner, a preset name or a
  reserved word.

`definition_sha256` digests the *effective behavioral* fields (argv, fragments,
insert, session policy, preset id, remote adapter policy). It deliberately
excludes `label`, the preset's display-only source URL, `validated` and the
digest itself, so renaming a lane or re-reading a vendor page does not look
like a different executor, while any change dispatch could act on does.

Writers (`add_executor_preset`, `remove_user_executor`) take the private
routing-dir lock, re-read the file, refuse an invalid one rather than rewriting
it lossily, and make one atomic mode-0600 replacement. Successful mutations may
reformat the TOML and discard comments: this file is the operator's config, not
an authored document.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Mapping

from ..plugin_bundle.omh.pi_family_names import (
    LEGACY_RUNTIME_PROFILE_ID,
    PI_DISTRIBUTION_HOST,
    PI_FORK_HOST,
)
from ..plugin_bundle.omh.run_records import EXECUTOR_PROGRESS_PROFILES
from ..system.local_store import atomic_write_text, file_lock
from .executor_presets import PRESETS, get_preset, preset_ids
from .executors import EXECUTOR_PROFILES


if TYPE_CHECKING:
    from ..system.paths import OmhPaths


USER_EXECUTOR_LAUNCH_SUPPORTED: Final = os.name == "posix"
USER_EXECUTOR_PLATFORM_UNSUPPORTED: Final = "user_executor_platform_unsupported"

EXECUTORS_CONFIG_SCHEMA_VERSION: Final[int] = 1
# Bounded read: a registry is a short list of argv vectors, so 256 KiB is
# already far past any honest file, and a larger one is refused unread.
USER_EXECUTORS_MAX_BYTES: Final[int] = 256 * 1024
MAX_VECTOR_TOKENS: Final[int] = 64
MAX_TOKEN_BYTES: Final[int] = 4096
MAX_LABEL_CHARS: Final[int] = 80

PROMPT_PLACEHOLDER: Final[str] = "{prompt}"
PROMPT_FILE_PLACEHOLDER: Final[str] = "{prompt_file}"
MODEL_PLACEHOLDER: Final[str] = "{model}"
EFFORT_PLACEHOLDER: Final[str] = "{effort}"
SESSION_FILE_PLACEHOLDER: Final[str] = "{session_file}"
SESSION_ID_PLACEHOLDER: Final[str] = "{session_id}"

_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9-]{1,31}", re.ASCII)
_VERSION_SUBCOMMAND_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_VERSION_QUERIES: Final[frozenset[str]] = frozenset({"--version", "-V", "version"})

_ROOT_KEYS: Final[frozenset[str]] = frozenset({"schema_version", "executors"})
_ENTRY_SCALAR_KEYS: Final[tuple[str, ...]] = (
    "label",
    "argv",
    "model",
    "effort",
    "insert",
    "version",
    "preset",
    "remote_pr",
)
_SESSION_KEY: Final[str] = "session"
_SESSION_KEYS: Final[frozenset[str]] = frozenset({"export", "resume"})
_PRESET_ENTRY_KEYS: Final[frozenset[str]] = frozenset({"preset", "remote_pr"})

# Programs that are a shell, an OS launcher or a language evaluator rather than
# the coding CLI the person installed. `argv[0]` must be a bare PATH program
# name, so a refusal here is about the *shape* of the declaration: omh never
# inspects or sandboxes what the binary does once it is launched.
_REFUSED_PROGRAMS: Final[frozenset[str]] = frozenset(
    {
        "ash",
        "bash",
        "busybox",
        "bun",
        "cmd",
        "command",
        "csh",
        "dash",
        "deno",
        "doas",
        "env",
        "eval",
        "exec",
        "expect",
        "fish",
        "java",
        "ksh",
        "lua",
        "luajit",
        "make",
        "mksh",
        "nohup",
        "node",
        "nodejs",
        "osascript",
        "perl",
        "php",
        "powershell",
        "powershell_ise",
        "pwsh",
        "python",
        "python2",
        "python3",
        "ruby",
        "script",
        "setsid",
        "sh",
        "sudo",
        "tcsh",
        "time",
        "toybox",
        "xargs",
        "zsh",
    }
)
# A Windows batch/script target is a command string in a file, even when the
# token has no path separator: PATHEXT would resolve it to a launcher. Refused
# on every platform so a declaration cannot become spawnable elsewhere.
_REFUSED_SUFFIXES: Final[tuple[str, ...]] = (
    ".bash",
    ".bat",
    ".cmd",
    ".com",
    ".js",
    ".pl",
    ".ps1",
    ".py",
    ".rb",
    ".sh",
    ".vbs",
    ".wsf",
    ".zsh",
)

# Built-in owners, the reserved control words and the ids that already mean
# something else in a stored progress record. A configured id lands in the same
# owner namespace a fanout contract carries, so it must not collide with any of
# them: `maestro` is an internal label, `choose`/`unassigned` are sentinels, and
# the pi-family hosts are both PATH-program names and progress aliases.
#
# `_PROGRESS_ALIASES` mirrors the alias table in
# `executor_progress.normalize_executor_profile`: each of those spellings is
# already read back as one of the shipped lanes, so a configured executor named
# the same would silently change what an existing record means.
_PROGRESS_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "claude",
        "claude-code",
        "claude-code-cli",
        "hermes-local",
        "opencode",
        "pi",
    }
)
RESERVED_OWNER_IDS: Final[frozenset[str]] = frozenset(
    {
        *EXECUTOR_PROFILES,
        *EXECUTOR_PROGRESS_PROFILES,
        *preset_ids(),
        *_PROGRESS_ALIASES,
        "choose",
        "unassigned",
        "maestro",
        LEGACY_RUNTIME_PROFILE_ID,
        PI_DISTRIBUTION_HOST,
        PI_FORK_HOST,
    }
)

_READ_CHUNK: Final[int] = 64 * 1024

# Internal problem shorthand: (field, closed reason). `ConfigIssue` adds the id.
_Problem = tuple[str, str]


class ExecutorConfigError(ValueError):
    """A requested mutation or render cannot be honored.

    `reason` is a closed token (`unknown_preset`, `already_exists`,
    `invalid_file`, `prompt_file_required`, ...) safe to put in user-facing CLI
    output: it never carries command arguments, a prompt, a secret or TOML
    source.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ConfigIssue:
    """One rejected entry or file-level problem, with a closed reason."""

    executor_id: str | None
    field: str
    reason: str


@dataclass(frozen=True)
class ExecutorSpec:
    """One validated executor: either a custom entry or an expanded preset."""

    id: str
    label: str
    argv: tuple[str, ...]
    model: tuple[str, ...]
    effort: tuple[str, ...]
    insert: int
    version: tuple[str, ...]
    export: tuple[str, ...]
    resume: tuple[str, ...]
    preset_id: str | None
    remote_adapter: str | None
    remote_pr: bool
    definition_sha256: str
    validated: bool


@dataclass(frozen=True)
class ExecutorRegistry:
    """Valid entries plus every rejection, from one read of one home."""

    entries: Mapping[str, ExecutorSpec]
    issues: tuple[ConfigIssue, ...]


def user_executors_path(omh_home: Path) -> Path:
    """`<omh_home>/routing/executors.toml`; sibling of dispatch model prefs."""
    return Path(omh_home) / "routing" / "executors.toml"


def operator_executor_home(
    omh_home: str | Path | None = None,
    hermes_home: str | Path | None = None,
    *,
    scope: str | None = None,
    paths: OmhPaths | None = None,
) -> Path:
    """The OMH home whose `routing/executors.toml` an invocation may use.

    `--scope project` moves *artifacts* into the checkout, not this registry: a
    repo-owned `executors.toml` would let a clone choose the argv OMH spawns,
    so a project-scoped invocation still reads and writes the operator's own
    home. A store the operator named (`--omh-home`) is the store the operator
    meant, and still wins under either scope.
    """
    # Imported here: the resolver lives in `system.paths`, which imports the
    # coding package this module belongs to, and this keeps that order free.
    from ..system.paths import resolve_paths

    if paths is not None:
        if paths.omh_home_named:
            return paths.omh_home
        # A paths-only caller cannot distinguish an explicit project-local
        # Hermes home from the implicit sibling of the project artifact store.
        # In that ambiguous pair prefer the operator, never checkout config.
        # CLI commands have the original flags and do not need this fallback.
        implicit_pair = (paths.omh_home.name == ".omh" and
                         paths.hermes_home == paths.omh_home.with_name(".hermes"))
        hermes_home = None if implicit_pair else paths.hermes_home
    if omh_home is None and str(scope or "user").strip().lower() == "project":
        return Path(resolve_paths(None, hermes_home).omh_home)
    return Path(resolve_paths(omh_home, hermes_home, scope=scope).omh_home)


def valid_executor_id(value: object) -> bool:
    """Exact `[a-z][a-z0-9-]{1,31}` grammar only -- no normalization."""
    return isinstance(value, str) and _ID_PATTERN.fullmatch(value) is not None


# --------------------------------------------------------------------------
# Value-level checks
# --------------------------------------------------------------------------


def _has_control(value: str) -> bool:
    return any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)


def _token_problem(token: object) -> str | None:
    if not isinstance(token, str):
        return "non_string_token"
    if token == "":
        return "empty_token"
    if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
        return "token_too_long"
    if _has_control(token):
        return "control_character"
    return None


def _parse_vector(
    value: object,
    field: str,
    placeholders: tuple[str, ...],
    *,
    required: bool = False,
) -> tuple[tuple[str, ...] | None, list[_Problem]]:
    """Hold one argv vector to the closed rules; None means "absent or bad".

    `placeholders` is empty for the version probe, where no substitution is
    allowed at all. Otherwise exactly one token must equal exactly one of the
    placeholders and no other token may carry a brace, which is what keeps a
    placeholder to a whole argv element instead of a segment of one.

    An empty list on an optional fragment is the same statement as omitting the
    key (no tokens to splice), so it reads as absent; the same list in `argv` or
    in the version probe is a declared-but-empty vector and is refused.
    """
    if value is None:
        if required:
            return None, [(field, "missing")]
        return None, []
    if not isinstance(value, (list, tuple)):
        return None, [(field, "invalid_vector")]
    tokens = list(value)
    if not tokens and not required:
        return None, []
    if not 1 <= len(tokens) <= MAX_VECTOR_TOKENS:
        return None, [(field, "vector_length")]
    for token in tokens:
        reason = _token_problem(token)
        if reason is not None:
            return None, [(field, reason)]
    braced = [token for token in tokens if "{" in token or "}" in token]
    if not placeholders:
        if braced:
            return None, [(field, "placeholder_not_allowed")]
        return tuple(tokens), []
    if sum(1 for token in braced if token in placeholders) != 1:
        return None, [(field, "placeholder_count")]
    if len(braced) != 1:
        return None, [(field, "stray_braces")]
    return tuple(tokens), []


def _insert_problem(value: object, argv_length: int) -> str | None:
    # bool is an int in Python; `insert = true` is a different declaration.
    if isinstance(value, bool) or not isinstance(value, int):
        return "invalid_insert"
    if not 1 <= value <= argv_length:
        return "insert_out_of_range"
    return None


def _program_problem(token: str) -> str | None:
    if "/" in token or "\\" in token or token in {".", ".."}:
        return "program_path"
    if token.startswith("-"):
        return "invalid_program"
    lowered = token.lower()
    if lowered.endswith(_REFUSED_SUFFIXES):
        return "shell_program"
    stem = lowered[:-4] if lowered.endswith(".exe") else lowered
    if stem in _REFUSED_PROGRAMS:
        return "shell_program"
    return None


def _version_problem(version: tuple[str, ...], program: str) -> str | None:
    """A version probe is a version query, not a second workload."""
    if version[0] != program:
        return "version_program"
    if len(version) < 2:
        return "version_probe"
    if version[-1] not in _VERSION_QUERIES:
        return "version_probe"
    for token in version[1:-1]:
        if not _VERSION_SUBCOMMAND_PATTERN.fullmatch(token):
            return "version_probe"
    return None


def declares_cloud(arguments: Sequence[str]) -> bool:
    """Check arguments *after* the program, or an insertion fragment on its own."""
    return (bool(arguments) and arguments[0] == "cloud") or any(
        arg == "--cloud" or arg.startswith("--cloud=") for arg in arguments
    )


def _definition_digest(
    *,
    executor_id: str,
    argv: tuple[str, ...],
    model: tuple[str, ...],
    effort: tuple[str, ...],
    insert: int,
    version: tuple[str, ...],
    export: tuple[str, ...],
    resume: tuple[str, ...],
    preset_id: str | None,
    remote_adapter: str | None,
    remote_pr: bool,
) -> str:
    payload = {
        "adapter": remote_adapter,
        "argv": list(argv),
        "effort": list(effort),
        "export": list(export),
        "id": executor_id,
        "insert": insert,
        "model": list(model),
        "preset": preset_id,
        "remote_pr": remote_pr,
        "resume": list(resume),
        "version": list(version),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _build_spec(
    executor_id: str,
    *,
    label: object,
    argv: object,
    model: object,
    effort: object,
    insert: object,
    version: object,
    export: object,
    resume: object,
    preset_id: str | None,
    remote_adapter: str | None,
    remote_pr: bool,
) -> tuple[ExecutorSpec | None, tuple[_Problem, ...]]:
    """Validate expanded data (custom or preset) through one rule set."""
    problems: list[_Problem] = []

    # An absent label defaults to the id; anything that is not a short, single
    # line of printable text is refused rather than trimmed into something the
    # operator did not write.
    if label is None:
        label_text = executor_id
    elif isinstance(label, str):
        label_text = label
    else:
        label_text = ""
    if not label_text.strip():
        problems.append(("label", "invalid_label"))
    elif len(label_text) > MAX_LABEL_CHARS or _has_control(label_text):
        problems.append(("label", "invalid_label"))

    argv_tokens, found = _parse_vector(
        argv, "argv", (PROMPT_PLACEHOLDER, PROMPT_FILE_PLACEHOLDER), required=True
    )
    problems.extend(found)
    model_tokens, found = _parse_vector(model, "model", (MODEL_PLACEHOLDER,))
    problems.extend(found)
    effort_tokens, found = _parse_vector(effort, "effort", (EFFORT_PLACEHOLDER,))
    problems.extend(found)
    export_tokens, found = _parse_vector(export, "session.export", (SESSION_FILE_PLACEHOLDER,))
    problems.extend(found)
    resume_tokens, found = _parse_vector(resume, "session.resume", (SESSION_ID_PLACEHOLDER,))
    problems.extend(found)

    # Every parsed fragment is part of the argv a dispatch renders, so the
    # cloud switch is refused wherever it is spelled -- not only in `argv`.
    for field, fragment in (
        ("model", model_tokens),
        ("effort", effort_tokens),
        ("session.export", export_tokens),
        ("session.resume", resume_tokens),
    ):
        if fragment is not None and declares_cloud(fragment):
            problems.append((field, "cloud_refused"))

    version_tokens: tuple[str, ...] | None = None
    if argv_tokens is not None:
        version_value = version
        if version_value is None:
            version_value = [argv_tokens[0], "--version"]
        version_tokens, found = _parse_vector(version_value, "version", (), required=True)
        problems.extend(found)
        if version_tokens is not None and declares_cloud(version_tokens[1:]):
            # Checked before the probe grammar, so the refusal names the real
            # problem instead of calling `--cloud` a malformed version query.
            problems.append(("version", "cloud_refused"))
            version_tokens = None
        if version_tokens is not None:
            reason = _version_problem(version_tokens, argv_tokens[0])
            if reason is not None:
                problems.append(("version", reason))
        reason = _insert_problem(1 if insert is None else insert, len(argv_tokens))
        if reason is not None:
            problems.append(("insert", reason))
        if argv_tokens[0] in (PROMPT_PLACEHOLDER, PROMPT_FILE_PLACEHOLDER):
            # A placeholder in the program slot would make the "executable" a
            # prompt: the argv would have no program at all.
            problems.append(("argv", "program_placeholder"))
        reason = _program_problem(argv_tokens[0])
        if reason is not None:
            problems.append(("argv", reason))
        if declares_cloud(argv_tokens[1:]):
            problems.append(("argv", "cloud_refused"))

    if problems or argv_tokens is None or version_tokens is None:
        return None, tuple(problems or [("argv", "missing")])

    # Validated above; the fallback only keeps the value typed without an
    # `assert`, which `python -O` would drop.
    insert_value = 1
    if isinstance(insert, int) and not isinstance(insert, bool):
        insert_value = insert
    digest = _definition_digest(
        executor_id=executor_id,
        argv=argv_tokens,
        model=model_tokens or (),
        effort=effort_tokens or (),
        insert=insert_value,
        version=version_tokens,
        export=export_tokens or (),
        resume=resume_tokens or (),
        preset_id=preset_id,
        remote_adapter=remote_adapter,
        remote_pr=remote_pr,
    )
    return (
        ExecutorSpec(
            id=executor_id,
            label=label_text,
            argv=argv_tokens,
            model=model_tokens or (),
            effort=effort_tokens or (),
            insert=insert_value,
            version=version_tokens,
            export=export_tokens or (),
            resume=resume_tokens or (),
            preset_id=preset_id,
            remote_adapter=remote_adapter,
            remote_pr=remote_pr,
            definition_sha256=digest,
            # Documentation and a fake process prove neither account access nor
            # a committed run: only a live dispatch receipt may claim more.
            validated=False,
        ),
        (),
    )


def _preset_entry(
    executor_id: str, raw: Mapping[str, Any]
) -> tuple[ExecutorSpec | None, tuple[ConfigIssue, ...]]:
    issues: list[ConfigIssue] = []

    def add(field: str, reason: str) -> None:
        issues.append(ConfigIssue(executor_id, field, reason))

    for key in sorted(raw):
        if key not in _PRESET_ENTRY_KEYS:
            add(key, "unknown_key")
    preset_name = raw.get("preset")
    preset = get_preset(preset_name) if isinstance(preset_name, str) else None
    if preset is None:
        add("preset", "unknown_preset")
        return None, tuple(issues)
    if preset.id != executor_id:
        add("preset", "preset_id_mismatch")
    remote_pr_value = raw.get("remote_pr", False)
    if not isinstance(remote_pr_value, bool):
        add("remote_pr", "invalid_argument")
        remote_pr_value = False
    elif remote_pr_value and preset.remote_adapter is None:
        add("remote_pr", "remote_pr_unsupported")
        remote_pr_value = False

    spec, problems = _build_spec(
        executor_id,
        label=preset.label,
        argv=list(preset.argv),
        model=list(preset.model),
        effort=list(preset.effort),
        insert=preset.insert,
        version=list(preset.version),
        export=list(preset.export),
        resume=list(preset.resume),
        preset_id=preset.id,
        remote_adapter=preset.remote_adapter,
        remote_pr=remote_pr_value,
    )
    issues.extend(ConfigIssue(executor_id, field, reason) for field, reason in problems)
    if spec is None or issues:
        return None, tuple(issues)
    return spec, ()


def _custom_entry(
    executor_id: str, raw: Mapping[str, Any]
) -> tuple[ExecutorSpec | None, tuple[ConfigIssue, ...]]:
    issues: list[ConfigIssue] = []

    def add(field: str, reason: str) -> None:
        issues.append(ConfigIssue(executor_id, field, reason))

    allowed = set(_ENTRY_SCALAR_KEYS) | {_SESSION_KEY}
    for key in sorted(raw):
        if key not in allowed:
            add(key, "unknown_key")
    if executor_id in RESERVED_OWNER_IDS:
        add("id", "shadowed_id")

    export_value: object = None
    resume_value: object = None
    session = raw.get(_SESSION_KEY)
    if session is not None:
        if not isinstance(session, dict):
            add("session", "invalid_argument")
        else:
            for key in sorted(session):
                if key not in _SESSION_KEYS:
                    add(f"session.{key}", "unknown_key")
            export_value = session.get("export")
            resume_value = session.get("resume")
            if export_value is None or (
                isinstance(export_value, (list, tuple)) and not export_value
            ):
                add("session.export", "missing")

    remote_pr_value = raw.get("remote_pr", False)
    if not isinstance(remote_pr_value, bool):
        add("remote_pr", "invalid_argument")
        remote_pr_value = False
    elif remote_pr_value:
        # No custom id owns a cloud adapter: the remote lane is a shipped
        # builder paired with its preset, never a user-supplied argv.
        add("remote_pr", "remote_pr_unsupported")
        remote_pr_value = False

    spec, problems = _build_spec(
        executor_id,
        label=raw.get("label"),
        argv=raw.get("argv"),
        model=raw.get("model"),
        effort=raw.get("effort"),
        insert=raw.get("insert"),
        version=raw.get("version"),
        export=export_value,
        resume=resume_value,
        preset_id=None,
        remote_adapter=None,
        remote_pr=remote_pr_value,
    )
    issues.extend(ConfigIssue(executor_id, field, reason) for field, reason in problems)
    if spec is None or issues:
        return None, tuple(issues)
    return spec, ()


def validate_executor_entry(
    executor_id: str, raw: object
) -> tuple[ExecutorSpec | None, tuple[ConfigIssue, ...]]:
    """Validate one `[executors.<id>]` table; exactly a spec or nonempty issues."""
    if not valid_executor_id(executor_id):
        return None, (ConfigIssue(executor_id if isinstance(executor_id, str) else None, "id", "invalid_id"),)
    if not isinstance(raw, Mapping):
        return None, (ConfigIssue(executor_id, "entry", "not_a_table"),)
    if "preset" in raw:
        return _preset_entry(executor_id, raw)
    return _custom_entry(executor_id, raw)


# --------------------------------------------------------------------------
# Reading the file
# --------------------------------------------------------------------------


def _escapes_home(path: Path, home: Path) -> bool:
    home_real = Path(os.path.realpath(home))
    path_real = Path(os.path.realpath(path))
    try:
        path_real.relative_to(home_real)
    except ValueError:
        return True
    return False


def _read_bounded(fd: int) -> bytes:
    chunks: list[bytes] = []
    remaining = USER_EXECUTORS_MAX_BYTES + 1
    while remaining > 0:
        chunk = os.read(fd, min(_READ_CHUNK, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_document(
    path: Path, home: Path, problems: list[_Problem]
) -> dict[str, Any] | None:
    """Read and parse the file; None means "absent" or "refused" (see problems).

    No probe, no spawn and no write happens here. Refusals are the trust
    boundary: an absolute home is required, the path may not resolve outside
    it, and the file itself may not be a symlink (a link inside the home still
    lets another tree's file become the registry).
    """
    if _escapes_home(path, home):
        problems.append(("path", "path_escape"))
        return None
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode):
            problems.append(("path", "symlink_refused"))
            return None
        if not stat.S_ISREG(before.st_mode):
            problems.append(("path", "not_regular_file"))
            return None
        # Non-blocking, so a writer-less FIFO at the path returns immediately
        # instead of hanging list/dispatch in open(2); `O_NOFOLLOW` keeps the
        # final component from being a link. `fstat` decides what it is before
        # a single byte is read: only a regular file is a registry.
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
    except FileNotFoundError:
        return None
    except OSError:
        problems.append(("path", "unreadable"))
        return None
    try:
        info = os.fstat(fd)
        # Without O_NOFOLLOW, only read the regular file identified by lstat.
        if not stat.S_ISREG(info.st_mode) or not os.path.samestat(before, info):
            problems.append(("path", "not_regular_file"))
            return None
        if info.st_size > USER_EXECUTORS_MAX_BYTES:
            problems.append(("path", "too_large"))
            return None
        raw = _read_bounded(fd)
    finally:
        os.close(fd)
    if len(raw) > USER_EXECUTORS_MAX_BYTES:
        problems.append(("path", "too_large"))
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(("path", "undecodable"))
        return None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        problems.append(("path", "malformed_toml"))
        return None


def _root_problems(document: object) -> list[_Problem]:
    """Closed root: one schema version and one `[executors]` table, nothing else."""
    if not isinstance(document, dict):
        return [("root", "malformed_document")]
    problems: list[_Problem] = []
    if set(document) - _ROOT_KEYS:
        problems.append(("root", "unknown_root_key"))
    version = document.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        problems.append(("schema_version", "unsupported_schema"))
    elif version != EXECUTORS_CONFIG_SCHEMA_VERSION:
        problems.append(("schema_version", "unsupported_schema"))
    executors = document.get("executors")
    if executors is not None and not isinstance(executors, dict):
        problems.append(("executors", "invalid_table"))
    return problems


def _empty_registry(problems: list[_Problem]) -> ExecutorRegistry:
    return ExecutorRegistry(
        entries=MappingProxyType({}),
        issues=tuple(ConfigIssue(None, field, reason) for field, reason in problems),
    )


def load_user_executors(omh_home: Path) -> ExecutorRegistry:
    """Load one home's registry. Never raises; never spawns or probes.

    A missing file is an empty registry with no issues (that is the ordinary
    "nobody declared an executor yet" state). A refused file is an empty
    registry with a file-level issue. A refused entry is omitted while its
    valid siblings still load, so one typo cannot take a wave down.
    """
    home = Path(omh_home)
    if not home.is_absolute():
        return _empty_registry([("omh_home", "relative_home")])
    problems: list[_Problem] = []
    document = _read_document(user_executors_path(home), home, problems)
    if problems:
        return _empty_registry(problems)
    if document is None:
        return _empty_registry([])
    root = _root_problems(document)
    if root:
        return _empty_registry(root)

    entries: dict[str, ExecutorSpec] = {}
    issues: list[ConfigIssue] = []
    executors = document.get("executors") or {}
    for raw_id in sorted(executors):
        spec, entry_issues = validate_executor_entry(raw_id, executors[raw_id])
        if spec is None:
            issues.extend(entry_issues)
        else:
            entries[raw_id] = spec
    return ExecutorRegistry(entries=MappingProxyType(entries), issues=tuple(issues))


def fanout_owner_ids(registry: ExecutorRegistry) -> tuple[str, ...]:
    """Built-in owners first, then configured ids sorted (stable for display)."""
    return (*EXECUTOR_PROFILES, *sorted(registry.entries))


# --------------------------------------------------------------------------
# Writing the file
# --------------------------------------------------------------------------


def _trusted_path(omh_home: Path) -> Path:
    home = Path(omh_home)
    if not home.is_absolute():
        raise ExecutorConfigError("relative_home")
    path = user_executors_path(home)
    if _escapes_home(path, home):
        raise ExecutorConfigError("path_escape")
    if path.is_symlink():
        raise ExecutorConfigError("symlink_refused")
    return path


def _read_for_write(path: Path, home: Path) -> dict[str, dict[str, Any]]:
    """The current entries, or a typed refusal -- never a lossy rewrite.

    A file this module would not load in full is refused as a whole: rewriting
    it from a partial parse is how unrelated entries, nested tables and a
    person's own values get dropped.
    """
    problems: list[_Problem] = []
    document = _read_document(path, home, problems)
    if problems:
        raise ExecutorConfigError("invalid_file")
    if document is None:
        return {}
    if _root_problems(document):
        raise ExecutorConfigError("invalid_file")
    executors = dict(document.get("executors") or {})
    for raw_id, raw_entry in executors.items():
        spec, _issues = validate_executor_entry(raw_id, raw_entry)
        if spec is None:
            raise ExecutorConfigError("invalid_file")
    return executors


def _format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        # JSON's string escaping is a TOML basic string for every character the
        # closed schema admits (no NUL/control characters reach here), and the
        # whole document is round-tripped through `tomllib` before it lands.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    raise ExecutorConfigError("unrepresentable_value")


def _serialize_document(document: Mapping[str, Any]) -> str:
    """Deterministic TOML for this closed schema (may reformat, never lose)."""
    lines = [f"schema_version = {EXECUTORS_CONFIG_SCHEMA_VERSION}", ""]
    executors = document.get("executors") or {}
    for executor_id in sorted(executors):
        entry = executors[executor_id]
        if not isinstance(entry, dict):
            raise ExecutorConfigError("unrepresentable_value")
        lines.append(f"[executors.{executor_id}]")
        for key in _ENTRY_SCALAR_KEYS:
            if key in entry:
                lines.append(f"{key} = {_format_scalar(entry[key])}")
        if set(entry) - set(_ENTRY_SCALAR_KEYS) - {_SESSION_KEY}:
            raise ExecutorConfigError("unrepresentable_value")
        session = entry.get(_SESSION_KEY)
        if session is not None:
            if not isinstance(session, dict) or set(session) - _SESSION_KEYS:
                raise ExecutorConfigError("unrepresentable_value")
            lines.append("")
            lines.append(f"[executors.{executor_id}.session]")
            for key in ("export", "resume"):
                if key in session:
                    lines.append(f"{key} = {_format_scalar(session[key])}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _document_for_write(executors: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {"schema_version": EXECUTORS_CONFIG_SCHEMA_VERSION}
    if executors:
        document["executors"] = {
            executor_id: dict(entry) for executor_id, entry in sorted(executors.items())
        }
    return document


def _replace_executors(path: Path, executors: Mapping[str, Mapping[str, Any]]) -> None:
    document = _document_for_write(executors)
    text = _serialize_document(document)
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ExecutorConfigError("serializer_mismatch") from error
    if parsed != document:
        raise ExecutorConfigError("serializer_mismatch")
    # One atomic mode-0600 replacement; the routing dir is created private.
    atomic_write_text(path, text, private=True)


def _is_preset_reference(entry: object, preset_id: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("preset") != preset_id:
        return False
    return set(entry) <= {"preset", "remote_pr"}


def add_executor_preset(
    omh_home: Path, preset_id: str, *, force: bool = False
) -> ExecutorSpec:
    """Opt in to one shipped preset by writing a reference, never a vendor install.

    `force` re-writes an existing same-id preset reference (and only that):
    it cannot overwrite a custom entry, a different preset or a file this
    module refuses to read.
    """
    preset = get_preset(preset_id) if isinstance(preset_id, str) else None
    if preset is None:
        raise ExecutorConfigError("unknown_preset")
    spec, issues = validate_executor_entry(preset.id, {"preset": preset.id})
    if spec is None:
        raise ExecutorConfigError("invalid_preset_definition")
    home = Path(omh_home)
    path = _trusted_path(home)
    reference: dict[str, Any] = {"preset": preset.id}
    with file_lock(path, private=True):
        executors = _read_for_write(path, home)
        existing = executors.get(preset.id)
        if existing is not None:
            if not _is_preset_reference(existing, preset.id):
                raise ExecutorConfigError("conflict")
            if not force:
                raise ExecutorConfigError("already_exists")
            if existing == reference:
                # A no-op must not rewrite the file.
                return spec
        executors[preset.id] = reference
        _replace_executors(path, executors)
    return spec


def remove_user_executor(omh_home: Path, executor_id: str) -> None:
    """Remove any configured entry (custom or preset). Missing id is a refusal."""
    if not valid_executor_id(executor_id):
        raise ExecutorConfigError("invalid_id")
    home = Path(omh_home)
    path = _trusted_path(home)
    with file_lock(path, private=True):
        executors = _read_for_write(path, home)
        if executor_id not in executors:
            raise ExecutorConfigError("not_found")
        del executors[executor_id]
        _replace_executors(path, executors)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _expand(vector: tuple[str, ...], placeholder: str, value: str) -> list[str]:
    """One vector with its placeholder element replaced by one literal value.

    The value stays a single argv element whatever it contains: a prompt with
    newlines, shell metacharacters, braces or a leading dash is message text,
    never a second flag and never a shell word.
    """
    return [value if token == placeholder else token for token in vector]


def render_user_argv(
    spec: ExecutorSpec,
    *,
    prompt: str,
    prompt_file: Path | None = None,
    model: str = "",
    effort: str = "",
    session_file: Path | None = None,
    session_id: str | None = None,
) -> list[str]:
    """The exact argv for one attempt. Pure: no PATH lookup, probe or write.

    Fragments the caller does not supply are left out (an empty model/effort,
    no session file). A fragment the caller *does* supply that the spec has no
    vector for is a typed refusal rather than a silent drop: reporting a model
    as applied when nothing carried it is a worse lie than failing.
    """
    if not isinstance(prompt, str):
        raise ExecutorConfigError("invalid_prompt")
    argv = list(spec.argv)
    prompt_index: int | None = None
    for index, token in enumerate(argv):
        if token in (PROMPT_PLACEHOLDER, PROMPT_FILE_PLACEHOLDER):
            prompt_index = index
            break
    if prompt_index is None:
        raise ExecutorConfigError("missing_prompt_placeholder")
    if argv[prompt_index] == PROMPT_FILE_PLACEHOLDER:
        if prompt_file is None:
            raise ExecutorConfigError("prompt_file_required")
        if not Path(prompt_file).is_file():
            raise ExecutorConfigError("prompt_file_unavailable")
        argv[prompt_index] = str(prompt_file)
    else:
        argv[prompt_index] = prompt

    if model and not spec.model:
        raise ExecutorConfigError("model_unsupported")
    if effort and not spec.effort:
        raise ExecutorConfigError("effort_unsupported")
    if session_file is not None and not spec.export:
        raise ExecutorConfigError("session_export_unsupported")
    if session_id is not None and not spec.resume:
        raise ExecutorConfigError("session_resume_unsupported")

    inserted: list[str] = []
    if model:
        inserted.extend(_expand(spec.model, MODEL_PLACEHOLDER, model))
    if effort:
        inserted.extend(_expand(spec.effort, EFFORT_PLACEHOLDER, effort))
    if session_file is not None:
        inserted.extend(_expand(spec.export, SESSION_FILE_PLACEHOLDER, str(session_file)))
    if session_id is not None:
        if not session_id:
            raise ExecutorConfigError("invalid_session_id")
        inserted.extend(_expand(spec.resume, SESSION_ID_PLACEHOLDER, session_id))

    index = min(spec.insert, len(argv))
    argv[index:index] = inserted
    return argv


# `PRESETS` is re-exported for callers that already hold a registry and want the
# shipped rows beside it without importing the presets module themselves.
__all__ = [
    "ConfigIssue",
    "ExecutorConfigError",
    "ExecutorRegistry",
    "ExecutorSpec",
    "PRESETS",
    "RESERVED_OWNER_IDS",
    "USER_EXECUTORS_MAX_BYTES",
    "add_executor_preset",
    "fanout_owner_ids",
    "load_user_executors",
    "declares_cloud",
    "operator_executor_home",
    "preset_ids",
    "remove_user_executor",
    "render_user_argv",
    "user_executors_path",
    "valid_executor_id",
    "validate_executor_entry",
]
