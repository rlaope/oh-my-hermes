"""User-authored tool-call rules, enforced at the ``pre_tool_call`` seam.

The idea is borrowed from stream-rule systems in other harnesses (rules sit
dormant until the model goes off-script, then intervene once), scaled to the
one intervention point the Hermes plugin host actually supports. Host
contract, read from the installed Hermes implementation
(``hermes_cli/plugins.py``, ``_get_pre_tool_call_directive_details`` /
``_dispatch_pre_tool_call_hooks``): a ``pre_tool_call`` hook may return
``{"action": "block", "message": ...}``, ``block`` "vetoes the tool call
outright (the message becomes the tool result the model sees)", and the host
passes ``tool_name``, ``args``, ``task_id``, ``session_id``, and turn
identifiers to the hook. OMH cannot abort a stream mid-token — that is
host-owned — but it can deterministically refuse one tool call and hand the
model the rule text, which produces the same course-correction loop at
tool-call granularity. Rules match in file order and the first match wins.

Rules are user-authored local configuration at
``$OMH_HOME/rules/toolcall-rules.json``; the file's presence is the opt-in.
Everything here is fail-open: a missing, malformed, or oversized rules file
and any single invalid rule degrade to "no intervention", never to a broken
hook. Matching is plain regex over the tool name and the JSON-serialized
tool arguments — no model call, no network, no clever parsing.

A blocked call is prevented, not judged: the block is instruction to the
model, not evidence that the rule's concern applied, and it is never
execution, verification, review, CI, or merge evidence.
"""

from __future__ import annotations

from . import runtime_paths

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# `re._parser` is the stdlib regex AST walker (formerly `sre_parse`); linters
# use the same surface. It exists so the validator can refuse
# catastrophic-backtracking patterns instead of certifying them.
from re import _parser as _re_parser  # type: ignore[attr-defined]

TOOLCALL_RULES_SCHEMA_VERSION: Final = "omh_toolcall_rules/v1"
TOOLCALL_RULES_FILE: Final = "toolcall-rules.json"
RULE_REPEAT_MODES: Final = ("once", "always")

MAX_RULES: Final = 64
MAX_RULE_NAME_CHARS: Final = 64
MAX_PATTERN_CHARS: Final = 512
MAX_MESSAGE_CHARS: Final = 1000
MAX_TOOL_SCOPE_ITEMS: Final = 16
MAX_RULES_FILE_BYTES: Final = 262_144
# Serialized-args match window. Bounding it keeps one pathological tool call
# (a giant write_file body) from turning every rule check into a slow scan.
MAX_MATCH_TEXT_CHARS: Final = 20_000

_BLOCK_SUFFIX: Final = (
    "This tool call was blocked by a user-defined OMH rule before execution. "
    "Adjust the approach to satisfy the rule instead of retrying the same "
    "call. A blocked call did not run."
)


@dataclass(frozen=True)
class ToolcallRule:
    name: str
    pattern: re.Pattern[str]
    message: str
    tools: tuple[str, ...]  # empty = every tool
    repeat: str  # "once" | "always"


# Parsed-rules cache keyed by rules-file path; entries are (mtime_ns, size,
# rules). A hook runs on every tool call, so the file is re-parsed only when
# it visibly changed.
_cache_lock = threading.Lock()
_rules_cache: dict[str, tuple[int, int, tuple[ToolcallRule, ...]]] = {}

# Sessions that already consumed a repeat="once" rule: {(session_id, rule name)}.
# In-process state is the point — one intervention per rule per session within
# this host process, and a host restart naturally re-arms the rules.
_fired_lock = threading.Lock()
_fired: set[tuple[Path, Path, str, str]] = set()
_MAX_FIRED_ENTRIES: Final = 1024
_MAX_CACHED_RULE_FILES: Final = 8


def toolcall_rules_path(omh_home: str = "") -> Path:
    # Same home resolution as session_hooks.py: an explicit kwarg wins, then
    # $OMH_HOME, then ~/.omh — so the documented rules path is the read path.
    resolved = omh_home or runtime_paths.default_omh_home()
    return Path(resolved).expanduser() / "rules" / TOOLCALL_RULES_FILE


def load_toolcall_rules(path: Path) -> tuple[ToolcallRule, ...]:
    """Parse the rules file, skipping every invalid entry. Fail-open."""
    try:
        stat = path.stat()
    except OSError:
        return ()
    if stat.st_size > MAX_RULES_FILE_BYTES:
        return ()
    key = str(path)
    with _cache_lock:
        cached = _rules_cache.get(key)
        if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    rules = _parse_rules(raw)
    with _cache_lock:
        if len(_rules_cache) >= _MAX_CACHED_RULE_FILES and key not in _rules_cache:
            _rules_cache.pop(next(iter(_rules_cache)))
        _rules_cache[key] = (stat.st_mtime_ns, stat.st_size, rules)
    return rules


def validate_toolcall_rules_document(raw: object) -> tuple[list[str], int]:
    """Return (errors, accepted_count) for a rules document.

    The hook itself never reports these errors — it fails open — so this is
    the surface `omh ops toolcall-rules-validate` uses to make a silently
    skipped rule visible to the person who wrote it.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return (["rules document must be a JSON object"], 0)
    if raw.get("schema_version") != TOOLCALL_RULES_SCHEMA_VERSION:
        # The loader refuses the whole document on a wrong schema_version, so
        # reporting any rule as accepted would certify a file the hook will
        # never read.
        return ([f"schema_version must be {TOOLCALL_RULES_SCHEMA_VERSION}; no rule is loaded"], 0)
    entries = raw.get("rules")
    if not isinstance(entries, list):
        errors.append("rules must be a list")
        return (errors, 0)
    if len(entries) > MAX_RULES:
        errors.append(f"at most {MAX_RULES} rules are read; extra entries are ignored")
    accepted = 0
    seen_names: set[str] = set()
    for index, entry in enumerate(entries[:MAX_RULES]):
        entry_errors = _entry_errors(entry, seen_names)
        if entry_errors:
            errors.extend(f"rules[{index}]: {error}" for error in entry_errors)
        else:
            assert isinstance(entry, dict)
            seen_names.add(str(entry["name"]).strip())
            accepted += 1
    return (errors, accepted)


def toolcall_rule_directive(
    *,
    tool_name: object,
    tool_input: object,
    session_id: str = "",
    omh_home: str = "",
) -> dict[str, str] | None:
    """The block directive for this call, or ``None`` to let it proceed."""
    name = str(tool_name or "").strip()
    if not name:
        return None
    try:
        path = toolcall_rules_path(omh_home)
    except (OSError, RuntimeError):
        # Path.home()/expanduser can raise when no home resolves; a rules
        # fault must never break the tool hook.
        return None
    rules = load_toolcall_rules(path)
    if not rules:
        return None
    match_text = _match_text(name, tool_input)
    for rule in rules:
        if rule.tools and name not in rule.tools:
            continue
        if rule.pattern.search(match_text) is None:
            continue
        if rule.repeat == "once" and not _claim_fire(path, session_id, rule.name):
            continue
        return {
            "action": "block",
            "message": f"[OMH Rule] {rule.name}: {rule.message}\n{_BLOCK_SUFFIX}",
        }
    return None


def _parse_rules(raw: object) -> tuple[ToolcallRule, ...]:
    if not isinstance(raw, dict) or raw.get("schema_version") != TOOLCALL_RULES_SCHEMA_VERSION:
        return ()
    entries = raw.get("rules")
    if not isinstance(entries, list):
        return ()
    rules: list[ToolcallRule] = []
    seen_names: set[str] = set()
    for entry in entries[:MAX_RULES]:
        if _entry_errors(entry, seen_names):
            continue
        assert isinstance(entry, dict)
        name = str(entry["name"]).strip()
        try:
            pattern = re.compile(str(entry["pattern"]))
        except re.error:
            continue
        seen_names.add(name)
        tools_value = entry.get("tools", [])
        tools = tuple(str(tool).strip() for tool in tools_value) if isinstance(tools_value, list) else ()
        rules.append(
            ToolcallRule(
                name=name,
                pattern=pattern,
                message=str(entry["message"]).strip(),
                tools=tools,
                repeat=str(entry.get("repeat", "once")),
            )
        )
    return tuple(rules)


def _entry_errors(entry: object, seen_names: set[str]) -> list[str]:
    if not isinstance(entry, dict):
        return ["rule must be an object"]
    errors: list[str] = []
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_RULE_NAME_CHARS:
        errors.append("name must be a nonempty string of at most " f"{MAX_RULE_NAME_CHARS} characters")
    elif name.strip() in seen_names:
        errors.append(f"duplicate rule name: {name.strip()!r}")
    pattern = entry.get("pattern")
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN_CHARS:
        errors.append(f"pattern must be a nonempty regex string of at most {MAX_PATTERN_CHARS} characters")
    else:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"pattern does not compile: {exc}")
        else:
            if _has_nested_unbounded_repeat(pattern):
                errors.append(
                    "pattern nests an unbounded repeat inside another repeat "
                    "(catastrophic-backtracking shape); rewrite it without "
                    "nested + or * quantifiers"
                )
    message = entry.get("message")
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > MAX_MESSAGE_CHARS:
        errors.append(f"message must be a nonempty string of at most {MAX_MESSAGE_CHARS} characters")
    tools = entry.get("tools", [])
    if not isinstance(tools, list) or len(tools) > MAX_TOOL_SCOPE_ITEMS or not all(
        isinstance(tool, str) and tool.strip() and len(tool) <= MAX_RULE_NAME_CHARS for tool in tools
    ):
        errors.append(
            f"tools must be a list of at most {MAX_TOOL_SCOPE_ITEMS} nonempty tool names "
            f"of at most {MAX_RULE_NAME_CHARS} characters each"
        )
    repeat = entry.get("repeat", "once")
    if repeat not in RULE_REPEAT_MODES:
        errors.append(f"repeat must be one of {', '.join(RULE_REPEAT_MODES)}")
    return errors


def _match_text(tool_name: str, tool_input: object) -> str:
    if isinstance(tool_input, str):
        args_text = tool_input
    else:
        try:
            args_text = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            args_text = str(tool_input)
    return f"{tool_name}\n{args_text}"[:MAX_MATCH_TEXT_CHARS]


def _claim_fire(path: Path, session_id: str, rule_name: str) -> bool:
    key = (runtime_paths.default_hermes_home(), path.resolve(), str(session_id or ""), rule_name)
    with _fired_lock:
        if key in _fired:
            return False
        if len(_fired) >= _MAX_FIRED_ENTRIES:
            _fired.pop()
        _fired.add(key)
    return True


def _has_nested_unbounded_repeat(pattern: str) -> bool:
    """True when an unbounded repeat wraps a subpattern containing a repeat.

    The classic catastrophic-backtracking shapes — ``(a+)+``, ``(a*)*``,
    ``(?:x+y*)+`` — all parse to MAX_REPEAT nodes with another repeat in
    their body. Walking the parsed AST refuses the shape itself instead of
    trying to predict runtime, so the validator and the loader agree.
    """
    try:
        parsed = _re_parser.parse(pattern)
    except (re.error, ValueError, RecursionError, OverflowError):
        # re.compile upstream already rejected anything unparseable; an AST
        # walk failure here must not turn into a hook fault.
        return False
    return _subpattern_has_nested_repeat(parsed, inside_repeat=False)


def _subpattern_has_nested_repeat(nodes, *, inside_repeat: bool) -> bool:
    for opcode, value in nodes:
        opcode_name = str(opcode)
        if opcode_name in ("MAX_REPEAT", "MIN_REPEAT"):
            _minimum, maximum, body = value
            unbounded = maximum is None or maximum >= _re_parser.MAXREPEAT
            if inside_repeat and unbounded:
                return True
            if _subpattern_has_nested_repeat(body, inside_repeat=inside_repeat or unbounded):
                return True
        elif opcode_name == "SUBPATTERN":
            body = value[3]
            if _subpattern_has_nested_repeat(body, inside_repeat=inside_repeat):
                return True
        elif opcode_name == "BRANCH":
            for branch in value[1]:
                if _subpattern_has_nested_repeat(branch, inside_repeat=inside_repeat):
                    return True
    return False


def _reset_state() -> None:
    """Test seam: forget parsed files and fired rules."""
    with _cache_lock:
        _rules_cache.clear()
    with _fired_lock:
        _fired.clear()
