"""Completion-integrity refusals: a gate that refuses fake completion.

`assess_quality_evidence` reports whether evidence is consistent, and
`build_goal_completion_gate` reports whether required criteria carry evidence.
Neither one reads the *claim* itself. A goal can therefore satisfy every
structural requirement while the work it claims is unfinished ("TODO: wire the
retry path"), the tests it claims are skipped, and the evidence it names is the
string "TBD".

This module closes that hole as a pure classifier over a completion claim:
changed file content, declared evidence entries, and the completion summary in.
Structured refusals out. It runs no command, reads no file, and upgrades
nothing -- a refusal is a verdict about the claim as supplied, and the caller
decides what a refusal blocks.

Two design rules keep the refusals reviewable rather than clever:

* Every rule is a word list or a small predicate over normalized tokens. There
  is no pattern soup and no rule that only its author can re-derive.
* Markers are scoped to changed *code* content, never to prose. A `TODO` in a
  Markdown file or under `docs/` is documentation; a report *about* TODO
  markers must not refuse itself. Only code files are scanned, and inside them
  only comment bodies, so a marker word inside a string literal or a variable
  name is not a placeholder note.

A marker that names a tracked follow-up -- an issue number or a URL on the same
line -- is a linked reason, not a placeholder, and passes. That is the
difference between "someone will do this, tracked here" and "this is not done
and nothing records that".

A ninth rule reads a diff rather than post-change content: `guard_deletion_
without_adversarial_regression` fires when a changed file's `diff` entry
*removes* a validation/refusal/sanitization/permission/allowlist line, or a
test function whose name carries negative-case vocabulary ("refuses",
"rejects", "denies", "blocks", "invalid"), and the same idiom does not
reappear as an *added* line anywhere in the supplied diffs. A guard that moves
elsewhere in the same change (the identical line reappears added) is not a
deletion. The refusal is waived for the whole claim, not line by line, the
moment any diff adds a negative-case-named test or an evidence entry names
"adversarial"/"regression" -- a boundary that loses its guard without a
regression proving it still refuses is the exact hole this rule closes.

Attribution: the placeholder evidence values and the negative-case naming
vocabulary follow oh-my-openagent (omo), which is published under the
Sustainable Use License 1.0. It is a link-only source, recorded in the note on
code-level borrowings in `docs/SKILL-SOURCES.md`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

COMPLETION_INTEGRITY_SCHEMA_VERSION: Final = "omh_completion_integrity/v1"

GUARD_DELETION_CATEGORY: Final = "guard_deletion_without_adversarial_regression"

REFUSAL_CATEGORIES: Final = (
    "unfinished_work_marker",
    "skipped_test_without_linked_reason",
    "stub_implementation",
    "empty_evidence",
    "self_referential_evidence",
    "prepared_evidence_claimed_as_observed",
    "unnamed_verification_command",
    "unproven_claim_word",
    GUARD_DELETION_CATEGORY,
)

CLAIM_BOUNDARY: Final = (
    "Completion-integrity refusals classify the supplied claim text, changed content, and "
    "evidence entries only; passing this classifier is not observed execution evidence."
)

# Only these suffixes are read as code. Everything else -- Markdown, reST,
# plain text, JSON fixtures -- is prose or data, where a marker word is a
# legitimate subject rather than an unfinished-work note.
_CODE_SUFFIXES: Final = (
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js", ".jsx",
    ".kt", ".m", ".mm", ".php", ".py", ".rb", ".rs", ".scala", ".sh", ".sql",
    ".swift", ".ts", ".tsx", ".zsh",
)

# A code file living under a documentation tree is still documentation: an
# example snippet or a doctest fixture is prose about code, not shipped code.
_PROSE_PATH_PARTS: Final = ("docs", "doc", "examples", "fixtures")

# Comment leads. SQL's `--` is deliberately absent: it collides with every
# long CLI flag a code line can carry (`--group`, `--check`), and truncating a
# line there would read the flag name as comment prose.
_COMMENT_LEADS: Final = ("<!--", "/*", "//", "#")

_UNFINISHED_MARKER_WORDS: Final = ("todo", "fixme", "xxx", "hack", "wip", "tbd")

# Test-suppression markers across the runners OMH's executors actually meet.
# Matched as literal substrings because each one is already a distinctive,
# unambiguous token -- `test.skip` never appears by accident.
_SKIP_MARKERS: Final = (
    "test.skip(", "test.only(", "it.only(", "it.skip(", "describe.only(",
    "describe.skip(", "xit(", "xdescribe(", "@unittest.skip", "@pytest.mark.skip",
    "self.skiptest(", "t.skip(",
)

# Stub bodies: a function that declares it does nothing.
_STUB_MARKERS: Final = (
    "raise notimplementederror", "throw new notimplementederror",
    "todo!(", "unimplemented!(", "panic(\"not implemented",
)

# Words that turn a no-op body (`pass`, `...`, `return None`) into a declared
# stub rather than a deliberate empty implementation.
_STUB_COMMENT_WORDS: Final = ("stub", "placeholder", "unimplemented", "not implemented")
_NO_OP_BODIES: Final = ("pass", "...", "return none", "return", "{}", "return null")

# An abstract method raises exactly like a stub does, so the decorator is what
# separates "this class delegates the body to subclasses" from "nobody wrote
# this yet". A raise within this many lines of an abstract decorator is read as
# the former.
_ABSTRACT_DECORATORS: Final = ("@abstractmethod", "@abc.abstractmethod", "@overload")
_ABSTRACT_LOOKBACK_LINES: Final = 5

# omo's placeholder set, matched against the whole normalized evidence value so
# an evidence entry that merely mentions the word "todo" is untouched.
_PLACEHOLDER_EVIDENCE_VALUES: Final = (
    "placeholder", "todo", "tbd", "n/a", "na", "none", "nil", "stub", "-", "?", "pending",
)

# Assertions that describe a feeling about the work instead of a check that
# ran. Matched as phrases inside the normalized evidence value.
_SELF_REFERENTIAL_PHRASES: Final = (
    "works as expected", "worked as expected", "as expected", "should pass",
    "should work", "should be fine", "looks good", "looks fine", "seems fine",
    "seems correct", "obviously correct", "no issues found", "nothing to report",
    "trust me", "it works", "manually verified", "verified manually",
)

# Words that assert the claim is proven, as opposed to describing what changed.
# Status words like "done" or "complete" are deliberately absent: they state a
# position in the workflow, not that a check was run.
_CLAIM_WORDS: Final = (
    "verified", "passing", "passed", "fixed", "green", "confirmed", "proven",
)

# Phrases that specifically claim a suite ran.
_VERIFICATION_CLAIM_PHRASES: Final = (
    "tests pass", "tests passing", "tests passed", "test suite passes",
    "all tests pass", "suite is green", "suite passes", "build passes",
    "lint passes", "ci is green", "checks pass",
)

# Command-runner tokens. An evidence entry naming one of these names a command
# a reader can re-run; an entry naming none is a description of a command.
_COMMAND_TOKENS: Final = (
    "pytest", "unittest", "nose", "tox", "jest", "vitest", "mocha", "npm",
    "pnpm", "yarn", "bun", "cargo", "gradle", "mvn", "make", "ruff", "mypy",
    "eslint", "tsc", "uv", "python", "python3", "go", "dotnet", "phpunit",
    "rspec", "swift", "ctest", "bazel", "compileall", "omh",
)

# Evidence prefixes OMH already uses for a recorded observation. These are
# observed-class references even when they name no command, because the
# reference resolves to a stored record rather than to a sentence.
_OBSERVED_REFERENCE_PREFIXES: Final = ("observed:", "run:", "runtime:", ".omh/", "omh://")

_PREPARED_NOT_OBSERVED: Final = "prepared_not_observed"

# House vocabulary for a trust-boundary guard: a removed line carrying one of
# these tokens is read as a validation/refusal/sanitization/permission/
# allowlist check, whether it is a `raise`, a `return`/`refuse` verdict, or an
# allowlist assignment (OMH's own `DAEMON_ENV_ALLOWLIST`-style identifiers
# tokenize to exactly this word).
_GUARD_VOCABULARY_WORDS: Final = frozenset((
    "raise", "refuse", "refuses", "refused", "refusal",
    "deny", "denies", "denied", "validate", "validates", "validated", "validation",
    "sanitize", "sanitizes", "sanitized", "sanitise", "sanitises", "sanitised",
    "permission", "allowlist", "forbid", "forbids", "forbidden",
    "disallow", "disallows", "disallowed", "guard", "reject", "rejects", "rejected",
))

# omo's `ULW_LOOP_SUCCESS_CRITERION_USER_MODELS` negative-case naming
# convention, matched against a test definition's name or description.
_NEGATIVE_CASE_VOCABULARY_WORDS: Final = frozenset((
    "refuse", "refuses", "refused", "refusal",
    "reject", "rejects", "rejected", "rejection",
    "deny", "denies", "denied", "denial",
    "block", "blocks", "blocked",
    "invalid", "invalidates", "invalidated",
))

# The criterion classes a claim can name in its evidence to prove a guard
# deletion is covered, mirroring `ULW_LOOP_SUCCESS_CRITERION_USER_MODELS`.
_REGRESSION_CRITERION_WORDS: Final = frozenset(("adversarial", "regression"))

_MAX_EXCERPT_CHARS: Final = 160


def classify_completion_integrity(
    *,
    summary: str = "",
    changed_files: Sequence[Mapping[str, object]] = (),
    evidence: Sequence[object] = (),
) -> dict[str, object]:
    """Return every completion-integrity refusal the supplied claim earns.

    `changed_files` entries carry `path` and optional `content`; an entry with
    no content contributes its path only, because a path alone cannot prove
    anything about what the file now holds. `evidence` entries are either a
    plain reference string or a mapping with `reference` and an optional
    `status`, which is how the goal ledger's `evidence_refs` and the richer
    quality-evidence observations both fit without a conversion step.
    """
    refusals: list[dict[str, str]] = []
    for entry in changed_files:
        refusals.extend(_changed_file_refusals(entry))
    normalized_evidence = [_normalized_evidence(entry) for entry in evidence]
    for index, (reference, status) in enumerate(normalized_evidence):
        refusals.extend(_evidence_refusals(index, reference, status))
    refusals.extend(_claim_binding_refusals(summary, normalized_evidence))
    refusals.extend(_guard_deletion_refusals(changed_files, normalized_evidence))
    return {
        "schema_version": COMPLETION_INTEGRITY_SCHEMA_VERSION,
        "refused": bool(refusals),
        "refusals": refusals,
        "categories": sorted({item["category"] for item in refusals}),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _changed_file_refusals(entry: Mapping[str, object]) -> list[dict[str, str]]:
    if not isinstance(entry, Mapping):
        return []
    path = entry.get("path")
    content = entry.get("content")
    if not isinstance(path, str) or not path.strip():
        return []
    if not isinstance(content, str) or not content.strip():
        return []
    if not _is_scanned_code_path(path):
        return []
    lines = content.splitlines()
    refusals: list[dict[str, str]] = []
    for index, line in enumerate(lines):
        refusal = _line_refusal(path, line, abstract_guarded=_is_abstract_guarded(lines, index))
        if refusal is not None:
            refusals.append(refusal)
    return refusals


def _is_abstract_guarded(lines: Sequence[str], index: int) -> bool:
    window = lines[max(0, index - _ABSTRACT_LOOKBACK_LINES) : index]
    return any(
        decorator in line.lower() for line in window for decorator in _ABSTRACT_DECORATORS
    )


def _line_refusal(path: str, line: str, *, abstract_guarded: bool) -> dict[str, str] | None:
    """The first refusal one code line earns, or None.

    Rules are tried in a fixed order so the same line always reports the same
    category, and one line reports at most once: a stub body annotated `# TODO`
    is one unfinished thing, not two.

    A stub marker is refused even when the line links an issue -- a tracked
    stub is still an unwritten body -- while a skip marker or a placeholder
    note that links one passes, because there the link is the whole difference
    between a tracked follow-up and a silently dropped obligation.
    """
    lowered = line.lower()
    if not abstract_guarded:
        for marker in _STUB_MARKERS:
            if marker in lowered:
                return _refusal(
                    "stub_implementation",
                    path,
                    line,
                    "Implement the branch or record it as a blocker; a declared stub cannot be "
                    "part of a completion claim.",
                )
    if _has_linked_reason(line):
        return None
    for marker in _SKIP_MARKERS:
        if marker in lowered:
            return _refusal(
                "skipped_test_without_linked_reason",
                path,
                line,
                f"Remove `{marker.rstrip('(')}` or name the tracked reason on the same line "
                "(an issue number like #123, or a URL); a suppressed test is not a passing test.",
            )
    comment = _comment_body(line)
    if comment is not None:
        comment_tokens = _tokens(comment)
        code_before = _code_before_comment(line)
        if code_before in _NO_OP_BODIES and any(
            word in comment.lower() for word in _STUB_COMMENT_WORDS
        ):
            return _refusal(
                "stub_implementation",
                path,
                line,
                "Implement the body or record it as a blocker; a no-op annotated as a stub "
                "cannot be part of a completion claim.",
            )
        for word in _UNFINISHED_MARKER_WORDS:
            if word in comment_tokens:
                return _refusal(
                    "unfinished_work_marker",
                    path,
                    line,
                    f"Resolve the `{word.upper()}` note or link it to a tracked issue "
                    "(#123 or a URL) on the same line; an unlinked placeholder note is "
                    "unfinished work, not a completed change.",
                )
    return None


def _guard_deletion_refusals(
    changed_files: Sequence[Mapping[str, object]], normalized_evidence: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Refusals for a guard deleted with no adversarial/regression case behind it.

    Each `changed_files` entry may carry an optional `diff` -- unified-diff
    text for that path, `-`/`+`/context-prefixed lines -- alongside `content`.
    Entries with no `diff` contribute nothing here; `content`-only entries are
    already covered by `_changed_file_refusals`.
    """
    parsed: list[tuple[str, list[str], list[str]]] = []
    for entry in changed_files:
        if not isinstance(entry, Mapping):
            continue
        path = entry.get("path")
        diff = entry.get("diff")
        if not isinstance(path, str) or not path.strip():
            continue
        if not isinstance(diff, str) or not diff.strip():
            continue
        if not _is_scanned_code_path(path):
            continue
        removed, added = _diff_removed_and_added(diff)
        parsed.append((path, removed, added))
    if not parsed:
        return []

    added_normalized: set[str] = set()
    added_negative_test = False
    for _, _, added in parsed:
        for line in added:
            added_normalized.add(_normalized_text(line))
            test_name = _test_definition_name(line)
            if test_name and _tokens(test_name) & _NEGATIVE_CASE_VOCABULARY_WORDS:
                added_negative_test = True

    candidates: list[dict[str, str]] = []
    for path, removed, _ in parsed:
        for line in removed:
            if not line.strip():
                continue
            if _normalized_text(line) in added_normalized:
                continue  # the identical line reappears added: moved, not deleted
            test_name = _test_definition_name(line)
            if test_name and _tokens(test_name) & _NEGATIVE_CASE_VOCABULARY_WORDS:
                candidates.append(
                    _refusal(
                        GUARD_DELETION_CATEGORY,
                        path,
                        line,
                        "Restore the deleted negative-case test or add a named adversarial/"
                        "regression test proving the boundary still refuses what it should; a "
                        "deleted negative case with no replacement earns no completion claim.",
                    )
                )
                continue
            if _tokens(line) & _GUARD_VOCABULARY_WORDS:
                candidates.append(
                    _refusal(
                        GUARD_DELETION_CATEGORY,
                        path,
                        line,
                        "Add a named adversarial/regression test proving the boundary still "
                        "refuses what it should, or restore the guard; a removed validation/"
                        "refusal/sanitization/permission/allowlist check with no adversarial "
                        "regression behind it earns no completion claim.",
                    )
                )

    if not candidates or added_negative_test:
        return []
    if any(_tokens(reference) & _REGRESSION_CRITERION_WORDS for reference, _ in normalized_evidence):
        return []
    return candidates


def _diff_removed_and_added(diff_text: str) -> tuple[list[str], list[str]]:
    """`(-, +)` line bodies from unified-diff text, headers and hunks skipped."""
    removed: list[str] = []
    added: list[str] = []
    for raw_line in diff_text.splitlines():
        if raw_line.startswith(("---", "+++", "@@")):
            continue
        if raw_line.startswith("-"):
            removed.append(raw_line[1:])
        elif raw_line.startswith("+"):
            added.append(raw_line[1:])
    return removed, added


def _test_definition_name(line: str) -> str | None:
    """The test name/description a line declares, or None.

    Covers Python's `def test_x(...)` / `async def test_x(...)` and the
    JS/TS `it("...", ...)` / `test("...", ...)` description-string idiom.
    """
    stripped = line.strip()
    for prefix in ("def ", "async def "):
        if stripped.startswith(prefix):
            name = stripped[len(prefix):].split("(", 1)[0].strip()
            return name if name.lower().startswith("test") else None
    for caller in ("it(", "test(", "it.each(", "test.each("):
        if stripped.startswith(caller):
            after = stripped[len(caller):].lstrip()
            if after[:1] in ("\"", "'", "`"):
                quote = after[0]
                end = after.find(quote, 1)
                if end != -1:
                    return after[1:end]
    return None


def _evidence_refusals(index: int, reference: str, status: str) -> list[dict[str, str]]:
    label = f"evidence[{index}]"
    normalized = _normalized_text(reference)
    if not normalized or normalized in _PLACEHOLDER_EVIDENCE_VALUES:
        return [
            _refusal(
                "empty_evidence",
                label,
                reference,
                "Replace the placeholder with the command that ran and where its output is "
                "recorded; a completion claim cannot check out on an empty evidence field.",
            )
        ]
    for phrase in _SELF_REFERENTIAL_PHRASES:
        if phrase in normalized:
            return [
                _refusal(
                    "self_referential_evidence",
                    label,
                    reference,
                    f"Replace \"{phrase}\" with the command that ran and its observed result; "
                    "an assertion about the work is not evidence of the work.",
                )
            ]
    if _PREPARED_NOT_OBSERVED in normalized or status == _PREPARED_NOT_OBSERVED:
        if _claims_execution(normalized):
            return [
                _refusal(
                    "prepared_evidence_claimed_as_observed",
                    label,
                    reference,
                    "Split the prepared plan from the observed run: keep the prepared entry "
                    "labelled prepared_not_observed and add a separate entry for the command "
                    "that actually ran.",
                )
            ]
    if _claims_verification(normalized) and not _names_a_command(normalized):
        return [
            _refusal(
                "unnamed_verification_command",
                label,
                reference,
                "Name the command that produced this result (for example "
                "`PYTHONPATH=tests uv run python -m unittest discover -s tests`); a claim that "
                "tests pass without a named command cannot be re-run.",
            )
        ]
    return []


def _claim_binding_refusals(
    summary: str, evidence: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Claim words in the summary require one observed, command-naming entry."""
    if not isinstance(summary, str) or not summary.strip():
        return []
    tokens = _tokens(summary)
    claimed = [word for word in _CLAIM_WORDS if word in tokens]
    if not claimed:
        return []
    if any(_is_observed_class(reference, status) for reference, status in evidence):
        return []
    return [
        _refusal(
            "unproven_claim_word",
            "summary",
            summary,
            f"Either drop the word \"{claimed[0]}\" from the summary or add one evidence entry "
            "naming the command that proves it; a proof word with no observed command-naming "
            "evidence is an unproven claim.",
        )
    ]


def _is_observed_class(reference: str, status: str) -> bool:
    """True when an evidence entry resolves to something a reader can check."""
    normalized = _normalized_text(reference)
    if not normalized:
        return False
    if status == _PREPARED_NOT_OBSERVED or _PREPARED_NOT_OBSERVED in normalized:
        return False
    if any(normalized.startswith(prefix) for prefix in _OBSERVED_REFERENCE_PREFIXES):
        return True
    return _names_a_command(normalized)


def _normalized_evidence(entry: object) -> tuple[str, str]:
    """One evidence entry as `(reference, status)`.

    A bare string is a reference with no declared status, which is exactly how
    the goal ledger stores `evidence_refs`.
    """
    if isinstance(entry, str):
        return entry, ""
    if isinstance(entry, Mapping):
        reference = entry.get("reference")
        if not isinstance(reference, str):
            reference = entry.get("summary")
        status = entry.get("status")
        return (
            reference if isinstance(reference, str) else "",
            status.strip().lower() if isinstance(status, str) else "",
        )
    return "", ""


def _is_scanned_code_path(path: str) -> bool:
    parts = tuple(part for part in path.replace("\\", "/").split("/") if part not in ("", "."))
    if not parts:
        return False
    if any(part.lower() in _PROSE_PATH_PARTS for part in parts[:-1]):
        return False
    basename = parts[-1].lower()
    return any(basename.endswith(suffix) for suffix in _CODE_SUFFIXES)


def _comment_body(line: str) -> str | None:
    """The comment text on a code line, or None when the line carries none.

    A line whose stripped form starts with `*` is a block-comment continuation.
    Only the first comment lead is honoured, so a lead appearing later inside
    the comment text does not restart the scan.
    """
    stripped = line.strip()
    if stripped.startswith("*") and not stripped.startswith("*/"):
        return stripped[1:]
    positions = [(line.find(lead), lead) for lead in _COMMENT_LEADS if lead in line]
    if not positions:
        return None
    index, lead = min(positions)
    return line[index + len(lead):]


def _code_before_comment(line: str) -> str:
    positions = [line.find(lead) for lead in _COMMENT_LEADS if lead in line]
    if not positions:
        return line.strip().lower()
    return line[: min(positions)].strip().lower().rstrip(":;")


def _has_linked_reason(line: str) -> bool:
    """True when the line names a tracked follow-up: an issue number or a URL."""
    lowered = line.lower()
    if "http://" in lowered or "https://" in lowered:
        return True
    for index, char in enumerate(line):
        if char == "#" and index + 1 < len(line) and line[index + 1].isdigit():
            return True
    return False


def _claims_execution(normalized: str) -> bool:
    return any(
        word in _tokens(normalized) for word in ("ran", "executed", "observed", "green", "passed")
    ) or _claims_verification(normalized)


def _claims_verification(normalized: str) -> bool:
    return any(phrase in normalized for phrase in _VERIFICATION_CLAIM_PHRASES)


def _names_a_command(normalized: str) -> bool:
    return any(token in _tokens(normalized) for token in _COMMAND_TOKENS)


def _tokens(value: str) -> frozenset[str]:
    """Lowercased alphanumeric tokens, so marker words match whole words only."""
    collected: list[str] = []
    current: list[str] = []
    for char in value.lower():
        if char.isalnum():
            current.append(char)
        elif current:
            collected.append("".join(current))
            current = []
    if current:
        collected.append("".join(current))
    return frozenset(collected)


def _normalized_text(value: str) -> str:
    return " ".join(value.lower().split()) if isinstance(value, str) else ""


def _refusal(category: str, path: str, excerpt: str, remedy: str) -> dict[str, str]:
    return {
        "category": category,
        "path": path,
        "excerpt": _excerpt(excerpt),
        "remedy": remedy,
    }


def _excerpt(value: str) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= _MAX_EXCERPT_CHARS:
        return collapsed
    return collapsed[: _MAX_EXCERPT_CHARS - 1] + "…"
