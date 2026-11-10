"""The assembled fanout unit prompt, path by path.

`tests/fixtures/unit_prompt_golden_digests.json` holds the sha256 and byte
size of the exact prompt every dispatch path sends for a matrix of units. It
was captured from the string-mutating composer that `_dispatch_unit` used
before the prompt became a value, so a refactor of the assembly proves itself
byte-identical against it. An intentional prompt-text change moves digests;
regenerate with `_render_golden_fixture()` (see `GoldenDigestTests`) and check
that the cases named in the failure are the ones you meant to change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_repair import (  # noqa: E402
    _FAILURE_KINDS,
    _MAX_REPAIR_CHECKS,
    _MAX_REPAIR_COMMAND_CHARS,
    MAX_REPAIR_ATTEMPTS,
)
from omh.coding.executor_skill_discovery import ROLE_SEQUENCE_RECIPES  # noqa: E402
from omh.coding.unit_prompt_assembly import BLOCK_NAMES, AssembledPrompt, assemble_unit_prompt  # noqa: E402
from omh.coding.unit_prompt_protocol import (  # noqa: E402
    DOMAIN_SKILL_GUIDANCE,
    HIGH_EFFORT_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS,
    UNIT_PROMPT_APPEND_MAX_BYTES,
    UNIT_PROMPT_MAX_BYTES,
)

GOLDEN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "unit_prompt_golden_digests.json"

GOAL = "Ship the bounded exporter flag across the dashboard units"

OWNERS = ("codex", "claude-code")
ROLES = ("implementation", "review")
EFFORTS = ("low", "high", "max")
# (selected_model, recorded model_family). kimi-k3 has no exact-model override,
# so it is the family-only case; the rest are every exact override plus the
# `-pro` projection of 6.1 Sol and the claude family's shipped head.
MODELS = (
    ("kimi-k3", "kimi"),
    ("gpt-6-astra", "gpt"),
    ("gpt-6.1-sol", "gpt"),
    ("gpt-6.1-sol-pro", "gpt"),
    ("deepseek-v4.1-flash", "deepseek"),
    ("claude-sonnet-5-5", "claude"),
    ("claude-fable-5-2", "claude"),
)
# The live variants `_dispatch_unit` can produce, plus the two it never pairs
# (repair without a sidecar contract, and repair with a parent decision) so a
# composer that only handled the live pairs could not pass by accident.
VARIANTS = (
    "bare",
    "sidecar",
    "sidecar+discovery",
    "sidecar+repair",
    "sidecar+parent",
    "sidecar+repair+retry",
    "sidecar+parent+retry",
    "repair",
    "sidecar+repair+parent",
)

DISCOVERIES = {
    "claude-code": {
        "schema_version": "executor_skill_discovery/v1",
        "executor_profile": "claude-code",
        "skills": [
            {"name": "omc-plan", "invocation": "/omc-plan", "role": "brain", "role_score": 5, "source": "claude_user_skills"},
            {"name": "ultrawork", "invocation": "/ultrawork", "role": "implementation", "role_score": 3, "source": "claude_user_skills"},
            {"name": "code-reviewer", "invocation": "/code-reviewer", "role": "review", "role_score": 4, "source": "claude_user_skills"},
        ],
    },
    "codex": {
        "schema_version": "executor_skill_discovery/v1",
        "executor_profile": "codex",
        "skills": [
            {"name": "review-pr", "invocation": "$review-pr", "role": "review", "role_score": 4, "source": "codex_skills"},
            {"name": "implement", "invocation": "$implement", "role": "implementation", "role_score": 3, "source": "codex_skills"},
        ],
    },
}

SIDECAR_PATH = "/tmp/omh-fanout-intake-golden/11111111-1111-4111-8111-111111111111.json"
RETRY_SIDECAR_PATH = "/tmp/omh-fanout-intake-golden/22222222-2222-4222-8222-222222222222.json"
REPAIR = {
    "attempt": 1,
    "max_repair_attempts": 3,
    "failing_checks": [
        {"command": "python -m unittest tests/test_exporter.py", "exit_code": 1, "failure_kind": "exit_nonzero"},
    ],
}
PARENT_DECISION = {
    "answer": {"decision_id": "decision-d1", "answer": "json"},
    "goal_attempt_id": "attempt-0001",
}


def golden_unit(owner: str, role: str, effort: str, model: str, family: str) -> dict[str, object]:
    """A hand-built contract unit, so the goldens never move with chain data."""
    unit: dict[str, object] = {
        "unit_id": "exporter",
        "run_ref": "fanout-0123456789ab-exporter",
        "title": "Add the bounded exporter flag",
        "boundary": {"file_scope": ["src/exporter/", "tests/test_exporter.py"], "do_not_touch": ["docs/"]},
        "branch_suggestion": "agent/exporter",
        "integration_checks": ["python -m unittest tests/test_exporter.py passes"],
        "handoff": {
            "executor_target": owner,
            "model_route": {
                "role": role,
                "selected_model": model,
                "selected_reasoning_effort": effort,
                "model_family": family,
            },
        },
    }
    if role == "review":
        unit["domain"] = "research"
    if owner == "codex" and role == "implementation":
        unit["input_budget"] = {
            "chars": 24000,
            "tokens": 6000,
            "source_ranges": [
                {"source": "src/exporter/core.py", "span": "lines 1-200", "offset": 0, "limit": 200, "end_line": 200, "estimated_chars": 8000},
            ],
        }
    return unit


def golden_cases():
    """Yield (case_id, path, unit, variant) for every golden case."""
    for owner in OWNERS:
        for role in ROLES:
            for effort in EFFORTS:
                for model, family in MODELS:
                    unit = golden_unit(owner, role, effort, model, family)
                    stem = f"{owner}|{role}|{effort}|{model}"
                    for variant in VARIANTS:
                        yield f"dispatch|{stem}|{variant}", "dispatch", unit, variant
                    yield f"recovery|{stem}", "recovery", unit, ""


def _sidecar_contract(unit: dict[str, object]) -> dict[str, str]:
    return {
        "path": SIDECAR_PATH,
        "unit_id": str(unit["unit_id"]),
        "run_id": str(unit["run_ref"]),
        "fanout_id": "fanout-0123456789ab",
        "base_sha": "a" * 40,
    }


def assemble(path: str, unit: dict[str, object], variant: str, *, binding_path: str = SIDECAR_PATH) -> AssembledPrompt:
    """The prompt the named path sends, through the one assembler."""
    route = unit["handoff"]["model_route"]  # type: ignore[index]
    if path == "recovery":
        return assemble_unit_prompt(unit, GOAL, route=route)
    flags = set(variant.split("+"))
    owner = str(unit["handoff"]["executor_target"])  # type: ignore[index]
    if "retry" in flags:
        binding_path = RETRY_SIDECAR_PATH
    return assemble_unit_prompt(
        unit,
        GOAL,
        route=route,
        binding={**_sidecar_contract(unit), "path": binding_path} if "sidecar" in flags else None,
        discovery=DISCOVERIES[owner] if "discovery" in flags else None,
        repair=REPAIR if "repair" in flags else None,
        parent_decision=PARENT_DECISION if "parent" in flags else None,  # type: ignore[arg-type]
    )


def compose(path: str, unit: dict[str, object], variant: str) -> str:
    return assemble(path, unit, variant).text


def _render_golden_fixture() -> dict[str, object]:
    cases = {}
    for case_id, path, unit, variant in golden_cases():
        data = compose(path, unit, variant).encode("utf-8")
        cases[case_id] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return {"schema_version": "omh_unit_prompt_golden/v1", "goal": GOAL, "cases": cases}


class GoldenDigestTests(unittest.TestCase):
    def test_every_path_reproduces_its_golden_bytes(self) -> None:
        expected = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        actual = _render_golden_fixture()
        self.assertEqual(sorted(actual["cases"]), sorted(expected["cases"]))
        moved = sorted(case for case, row in actual["cases"].items() if row != expected["cases"][case])
        self.assertEqual(moved, [], f"{len(moved)} golden prompts moved, first: {moved[:5]}")


_HEAD = (
    "head.goal",
    "head.goal_echo",
    "head.verification_stop",
    "head.failure_kind",
    "head.unit_result_return",
    "head.parent_clarification",
    "head.structural_search_discipline",
)
_FRAME = ("unit.title", "unit.scope", "unit.do_not_touch", "unit.branch")
_CRITERIA = ("unit.criteria", "unit.commit_criterion", "unit.tool_batching")


class BlockNameGoldenTests(unittest.TestCase):
    """What each path sends, as a readable list rather than a digest."""

    GOLDEN_NAMES = {
        "recovery|claude-code|review|max|claude-fable-5-2": (
            *_HEAD, *_FRAME, *_CRITERIA, "unit.review_role", "unit.calibration[claude]",
            "unit.domain_bundle", "tail.commit",
        ),
        "dispatch|codex|implementation|low|kimi-k3|bare": (
            *_HEAD, *_FRAME, "unit.input_budget", *_CRITERIA, "tail.commit",
        ),
        "dispatch|claude-code|implementation|high|gpt-6.1-sol-pro|sidecar+discovery": (
            *_HEAD, *_FRAME, *_CRITERIA, "unit.calibration[gpt-6.1-sol]", "unit.skills",
            "tail.unit_result_contract", "tail.commit",
        ),
        "dispatch|codex|review|max|deepseek-v4.1-flash|sidecar+repair+retry": (
            *_HEAD, *_FRAME, *_CRITERIA, "unit.review_role", "unit.calibration[deepseek-v4.1-flash]",
            "unit.domain_bundle", "tail.unit_result_contract", "tail.commit", "append.repair",
        ),
        "dispatch|claude-code|review|high|gpt-6-astra|sidecar+parent": (
            *_HEAD, *_FRAME, *_CRITERIA, "unit.review_role", "unit.calibration[gpt-6-astra]",
            "unit.domain_bundle", "tail.unit_result_contract", "tail.commit", "append.parent_decision",
        ),
    }

    def test_each_path_sends_its_golden_block_list(self) -> None:
        cases = {case[0]: case for case in golden_cases()}
        for case_id, expected in self.GOLDEN_NAMES.items():
            _case, path, unit, variant = cases[case_id]
            with self.subTest(case=case_id):
                self.assertEqual(assemble(path, unit, variant).names(), expected)

    def test_every_name_is_in_the_vocabulary_and_zones_keep_their_order(self) -> None:
        order = ("shared_head", "unit", "tail", "append")
        for case_id, path, unit, variant in golden_cases():
            assembled = assemble(path, unit, variant)
            with self.subTest(case=case_id):
                self.assertTrue({block.base_name for block in assembled.blocks} <= BLOCK_NAMES)
                zones = [order.index(block.zone) for block in assembled.blocks]
                self.assertEqual(zones, sorted(zones))
                self.assertEqual(assembled.size_bytes, len(assembled.text.encode("utf-8")))
                self.assertEqual(assembled.digest(), hashlib.sha256(assembled.text.encode("utf-8")).hexdigest())

    def test_the_tail_contract_never_rides_without_the_head_failure_kind(self) -> None:
        # The sidecar contract states the process_declined literals and leaves
        # the definition to head.failure_kind; every receiver of the one must
        # receive the other.
        for case_id, path, unit, variant in golden_cases():
            names = assemble(path, unit, variant).names()
            if "tail.unit_result_contract" in names:
                self.assertIn("head.failure_kind", names, case_id)

    def test_a_sidecar_prompt_cannot_omit_the_head_failure_kind(self) -> None:
        unit = golden_unit("codex", "implementation", "high", "gpt-6-astra", "gpt")
        omit = frozenset({"head.failure_kind"})
        with self.assertRaisesRegex(ValueError, "must carry head.failure_kind"):
            assemble_unit_prompt(unit, GOAL, route=None, binding=_WORST_BINDING, omit=omit)
        # Without the contract the block is still a benchmark lane's to drop.
        self.assertNotIn("head.failure_kind", assemble_unit_prompt(unit, GOAL, route=None, omit=omit).names())

    def test_unknown_omitted_block_names_raise(self) -> None:
        unit = golden_unit("codex", "implementation", "high", "gpt-6-astra", "gpt")
        with self.assertRaisesRegex(ValueError, "unknown unit prompt blocks: head.nope"):
            assemble_unit_prompt(unit, GOAL, route=None, omit=frozenset({"head.nope"}))
        lean = assemble_unit_prompt(unit, GOAL, route=unit["handoff"]["model_route"],  # type: ignore[index]
                                    omit=frozenset({"unit.calibration", "head.parent_clarification"}))
        self.assertFalse([name for name in lean.names() if name.startswith(("unit.calibration", "head.parent"))])


def _worst_case_unit(model: str, family: str) -> dict[str, object]:
    """Every OMH-bounded unit input at its largest; operator text representative.

    Goal, title, scope, and checks are the operator's and unbounded, so they
    take the representative sizes the older budget test used. The role is
    review (it adds a block) and the domain is the one with the longest bundle.
    """
    domain = max(DOMAIN_SKILL_GUIDANCE, key=lambda name: len("".join(DOMAIN_SKILL_GUIDANCE[name])))
    return {
        "unit_id": "target",
        "run_ref": "fanout-0123456789ab-target",
        "title": "A deliberately verbose unit title for budget measurement",
        "boundary": {"file_scope": ["src/target/"], "do_not_touch": [f"src/area{i}/" for i in range(12)]},
        "branch_suggestion": "agent/target",
        "integration_checks": ["python -m unittest tests/test_target.py passes"],
        "domain": domain,
        "handoff": {
            "executor_target": "claude-code",
            "model_route": {
                "role": "review",
                "selected_model": model,
                "selected_reasoning_effort": "max",
                "model_family": family,
            },
        },
    }


def _worst_case_routes():
    """One route per calibration key: every family block and every override."""
    for family in HIGH_EFFORT_CALIBRATIONS:
        yield family, f"{family}-unlisted-model", family
    for model in MODEL_HIGH_EFFORT_CALIBRATIONS:
        yield model, model, ""


_WORST_BINDING = {
    # A macOS TemporaryDirectory intake root, the longest the platforms produce.
    "path": "/private/var/folders/zz/zyxvpxvq6csfxvn_n0000000000000/T/omh-fanout-intake-k2j4h5g6/"
    "ffffffff-ffff-4fff-8fff-ffffffffffff.json",
    "unit_id": "target",
    "run_id": "fanout-0123456789ab-target",
    "fanout_id": "fanout-0123456789ab",
    "base_sha": "f" * 64,
}
# One skill per recipe role, with long invocation names, so every recipe step
# of every role resolves.
_WORST_DISCOVERY = {
    "skills": [
        {"name": role, "invocation": f"/{'p' * 40}:{role}-{'s' * 40}", "role": role, "role_score": 9,
         "source": "claude_plugin_skills"}
        for role in sorted({step for recipe in ROLE_SEQUENCE_RECIPES.values() for step in recipe})
    ],
}
# The repair brief at fanout_repair's own caps. `"` is the printable ASCII
# character JSON doubles, so this is the brief's printable-ASCII maximum.
_WORST_REPAIR = {
    "attempt": MAX_REPAIR_ATTEMPTS,
    "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
    "failing_checks": [
        {"command": '"' * _MAX_REPAIR_COMMAND_CHARS, "exit_code": 4294967295,
         "failure_kind": max(_FAILURE_KINDS, key=len)}
        for _ in range(_MAX_REPAIR_CHECKS)
    ],
}
_WORST_PARENT_DECISION = {
    "answer": {
        "schema_version": "fanout_clarification_answer/v1",
        "decision_id": "d" * 64,
        "attempt_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        "round": 3,
        "answer": "a" * 300,
        "source": "root_session_cli",
        "observed_at": "2026-10-04T00:00:00.000000+00:00",
    },
    "goal_attempt_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
}


class PromptCeilingTests(unittest.TestCase):
    """The assembled prompt against its ceilings, at its worst live shape.

    `test_unit_prompt_protocol` keeps the older contract-shaped budget test;
    this one adds what it could not express: the sidecar contract every live
    dispatch carries, exact-model overrides, skill discovery, and the
    redispatch sections.
    """

    def test_dispatch_prompt_stays_under_the_ceiling_for_every_calibration_key(self) -> None:
        sizes = {}
        for key, model, family in _worst_case_routes():
            unit = _worst_case_unit(model, family)
            assembled = assemble_unit_prompt(
                unit, GOAL * 3, route=unit["handoff"]["model_route"],  # type: ignore[index]
                binding=_WORST_BINDING, discovery=_WORST_DISCOVERY,
            )
            self.assertIn(f"unit.calibration[{key}]", assembled.names())
            sizes[key] = assembled.size_bytes
        worst = max(sizes, key=sizes.__getitem__)
        self.assertEqual(len(sizes), len(HIGH_EFFORT_CALIBRATIONS) + len(MODEL_HIGH_EFFORT_CALIBRATIONS))
        self.assertLessEqual(
            sizes[worst], UNIT_PROMPT_MAX_BYTES, f"worst dispatch prompt {sizes[worst]} B ({worst})"
        )

    def test_each_redispatch_section_stays_under_its_derived_ceiling(self) -> None:
        unit = _worst_case_unit("claude-fable-5-2", "claude")
        route = unit["handoff"]["model_route"]  # type: ignore[index]
        base = assemble_unit_prompt(unit, GOAL * 3, route=route, binding=_WORST_BINDING, discovery=_WORST_DISCOVERY)
        for name, extra in (
            ("append.repair", {"repair": _WORST_REPAIR}),
            ("append.parent_decision", {"parent_decision": _WORST_PARENT_DECISION}),
        ):
            assembled = assemble_unit_prompt(
                unit, GOAL * 3, route=route, binding=_WORST_BINDING, discovery=_WORST_DISCOVERY, **extra,
            )
            added = assembled.size_bytes - base.size_bytes
            with self.subTest(section=name):
                self.assertEqual(assembled.names()[-1], name)
                self.assertLessEqual(added, UNIT_PROMPT_APPEND_MAX_BYTES, f"{name} adds {added} B")
        # Non-ASCII command text at the caps: the brief is UTF-8 (no `\uXXXX`
        # expansion) and each command is cut to the cap in UTF-8 bytes, so no
        # character set can outgrow the `"` brief measured above.
        for label, char in (("latin", "é"), ("cjk", "한"), ("emoji", "🙂"), ("mixed", 'é"')):
            command = (char * _MAX_REPAIR_COMMAND_CHARS)[:_MAX_REPAIR_COMMAND_CHARS]
            repair = dict(_WORST_REPAIR)
            repair["failing_checks"] = [
                {"command": command, "exit_code": 4294967295, "failure_kind": max(_FAILURE_KINDS, key=len)}
            ] * _MAX_REPAIR_CHECKS
            assembled = assemble_unit_prompt(
                unit, GOAL * 3, route=route, binding=_WORST_BINDING, discovery=_WORST_DISCOVERY, repair=repair,
            )
            added = assembled.size_bytes - base.size_bytes
            with self.subTest(command_text=label):
                self.assertLessEqual(added, UNIT_PROMPT_APPEND_MAX_BYTES, f"{label} repair adds {added} B")
                self.assertNotIn("\\u", assembled.blocks[-1].text)

    def test_a_brief_command_is_cut_to_the_cap_in_utf8_bytes(self) -> None:
        from omh.coding.fanout_repair import journal_repair_checks

        ascii_command = "a" * _MAX_REPAIR_COMMAND_CHARS
        self.assertEqual(journal_repair_checks([{"command": ascii_command}])[0]["command"], ascii_command)
        for char in ("é", "한", "🙂"):
            with self.subTest(char=char):
                cut = journal_repair_checks([{"command": char * _MAX_REPAIR_COMMAND_CHARS}])[0]["command"]
                self.assertLessEqual(len(cut.encode("utf-8")), _MAX_REPAIR_COMMAND_CHARS)
                self.assertEqual(cut, char * len(cut))
                self.assertGreater(len(cut), 0)


_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n")

# Sentences allowed to repeat inside one assembled prompt, each with its reason.
# Empty: no repeat is intentional today.
REPEATED_SENTENCE_ALLOWLIST: dict[str, str] = {}


def repeated_sentences(text: str) -> list[str]:
    """Sentences (whitespace-normalized, casefolded, 4+ words) that occur twice."""
    seen: dict[str, int] = {}
    for raw in _SENTENCE_BOUNDARY.split(text):
        sentence = " ".join(raw.split()).casefold()
        if len(sentence.split()) >= 4:
            seen[sentence] = seen.get(sentence, 0) + 1
    return sorted(sentence for sentence, count in seen.items() if count > 1 and sentence not in REPEATED_SENTENCE_ALLOWLIST)


class RepeatedSentenceTests(unittest.TestCase):
    def test_no_sentence_repeats_inside_one_assembled_prompt(self) -> None:
        prompts = [(case_id, compose(path, unit, variant)) for case_id, path, unit, variant in golden_cases()]
        for key, model, family in _worst_case_routes():
            unit = _worst_case_unit(model, family)
            prompts.append((f"worst|{key}", assemble_unit_prompt(
                unit, GOAL, route=unit["handoff"]["model_route"],  # type: ignore[index]
                binding=_WORST_BINDING, discovery=_WORST_DISCOVERY, parent_decision=_WORST_PARENT_DECISION,  # type: ignore[arg-type]
            ).text))
        for case_id, text in prompts:
            self.assertEqual(repeated_sentences(text), [], case_id)

    def test_the_check_sees_a_planted_repeat(self) -> None:
        text = "Run the full suite once. Then stop.\nRun   the full suite ONCE."
        self.assertEqual(repeated_sentences(text), ["run the full suite once."])


if __name__ == "__main__":
    unittest.main()
