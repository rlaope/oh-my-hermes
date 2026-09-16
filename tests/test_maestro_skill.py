"""Contract tests for the `maestro` (display name `ulw-maestro`) skill.

Pins the surfaces the implementation spec (`.omc/plans/ulw-maestro-spec.md`)
requires: ULW membership agreement across the three coupled tables, the
mechanical display-name derivation, the `ultrawork` Hermes-category carve-out
and install path, trigger disjointness from the named-coding-agent phrase
tables and the retired Codex owner-choice cues, the `HERMES_HARNESS_DEFAULT_WORDING`
substance and both handoff-mode names in the quality bar, executor-neutral
wording (no "default" co-located with a CLI name), and the absence of
Hermes-mixture worker/team vocabulary in maestro's own copy.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.orchestration_vocabulary import HERMES_HARNESS_DEFAULT_WORDING
from omh.routing.executor_cues import NAMED_CODING_AGENT_PHRASES
from omh.routing.ulw_alias import CODEX_OWNER_CHOICE_CUES
from omh.skills.catalog import (
    ULTRAWORK_HERMES_CATEGORY,
    _ULW_ENGINE_ORDER,
    _ULW_ENGINE_PRESENTATIONS,
    builtin_definitions,
    hermes_skill_category,
    omh_skill_install_path,
)
from omh.skills.catalog_types import (
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    ULW_ENGINE_SKILL_NAMES,
    omh_skill_display_name,
)

# Same tokens `tests/test_orchestration_vocabulary.py` forbids in Hermes
# mixture/Maestro vocabulary copy: Maestro hands work to a chosen external
# CLI, never to a "worker" or "team", or the two paths blur back together.
_WORKER_TEAM_TOKENS = {"worker", "workers", "team", "teams"}

# Mirrors `owner_neutrality_findings` in `tests/test_orchestration_vocabulary.py`:
# copy is a defect (`owner_neutrality_lost`) when it co-locates the word
# "default" with a specific external CLI's name, promoting that CLI to the
# implicit default coding owner.
_EXTERNAL_CLI_NAME_MENTIONS = ("codex", "claude code", "claude-code")


def _maestro_definition():
    return next(item for item in builtin_definitions() if item.name == "maestro")


def _owner_neutrality_findings(lines: tuple[str, ...]) -> list[str]:
    findings = []
    for line in lines:
        folded = line.casefold()
        if "default" in folded and any(name in folded for name in _EXTERNAL_CLI_NAME_MENTIONS):
            findings.append(line)
    return findings


class MaestroUlwMembershipTests(unittest.TestCase):
    def test_the_three_coupled_ulw_tables_agree_on_maestro(self) -> None:
        self.assertIn("maestro", ULW_ENGINE_SKILL_NAMES)
        self.assertIn("maestro", _ULW_ENGINE_ORDER)
        self.assertIn("maestro", _ULW_ENGINE_PRESENTATIONS)
        # Import-time gate in catalog.py already enforces set/length equality
        # between _ULW_ENGINE_ORDER and ULW_ENGINE_SKILL_NAMES; re-assert it
        # here as the maestro-specific regression pin rather than relying on
        # the package having imported cleanly.
        self.assertEqual(set(_ULW_ENGINE_ORDER), set(ULW_ENGINE_SKILL_NAMES))
        self.assertEqual(len(_ULW_ENGINE_ORDER), len(ULW_ENGINE_SKILL_NAMES))

    def test_maestro_is_registered_as_a_builtin_skill_definition(self) -> None:
        definition = _maestro_definition()
        self.assertEqual(definition.name, "maestro")


class MaestroDisplayNameAndCategoryTests(unittest.TestCase):
    def test_display_name_is_mechanically_prefixed_with_no_override(self) -> None:
        self.assertNotIn("maestro", OMH_SKILL_DISPLAY_NAME_OVERRIDES)
        self.assertEqual(omh_skill_display_name("maestro"), "ulw-maestro")

    def test_hermes_category_is_the_ultrawork_carve_out(self) -> None:
        self.assertEqual(hermes_skill_category("maestro"), ULTRAWORK_HERMES_CATEGORY)

    def test_install_path_nests_under_ultrawork(self) -> None:
        self.assertEqual(omh_skill_install_path("maestro"), "ultrawork/ulw-maestro")


class MaestroTriggerDisjointnessTests(unittest.TestCase):
    """§5.1: no maestro trigger may contain a bare CLI name or a retired
    owner-choice cue -- those are owner-selection signals, not engine
    signals, and reclaiming them for an engine is the Q9 defect."""

    def test_no_trigger_contains_a_named_coding_agent_phrase(self) -> None:
        definition = _maestro_definition()
        for trigger in definition.triggers:
            folded = trigger.casefold()
            for phrase in NAMED_CODING_AGENT_PHRASES:
                with self.subTest(trigger=trigger, phrase=phrase):
                    self.assertNotIn(phrase.casefold(), folded)

    def test_no_trigger_contains_a_retired_codex_owner_choice_cue(self) -> None:
        definition = _maestro_definition()
        for trigger in definition.triggers:
            folded = trigger.casefold()
            for cue in CODEX_OWNER_CHOICE_CUES:
                with self.subTest(trigger=trigger, cue=cue):
                    self.assertNotIn(cue.casefold(), folded)

    def test_no_trigger_is_the_bare_ambiguous_maestro_token(self) -> None:
        definition = _maestro_definition()
        self.assertNotIn("maestro", definition.triggers)


class MaestroQualityBarContentTests(unittest.TestCase):
    def test_quality_bar_carries_the_hermes_harness_default_wording(self) -> None:
        definition = _maestro_definition()
        combined = " ".join(definition.quality_bar) + " " + definition.why_this_exists
        self.assertIn(HERMES_HARNESS_DEFAULT_WORDING, combined)

    def test_quality_bar_names_both_handoff_modes(self) -> None:
        definition = _maestro_definition()
        combined = " ".join(definition.quality_bar)
        self.assertIn("prompt-only", combined)
        self.assertIn("dispatchable", combined)
        # The schema identifiers must be the real constants, not shorthand:
        # a truncated identifier in the mode-statement rule is exactly the
        # defect review caught, so assert against the source of truth.
        from omh.coding.executors import (
            EXECUTOR_HANDOFF_SCHEMA_VERSION,
            PROMPT_HANDOFF_SCHEMA_VERSION,
            RUNTIME_HANDOFF_SCHEMA_VERSION,
        )
        for schema in (
            PROMPT_HANDOFF_SCHEMA_VERSION,
            EXECUTOR_HANDOFF_SCHEMA_VERSION,
            RUNTIME_HANDOFF_SCHEMA_VERSION,
        ):
            self.assertIn(f"`{schema}`", combined)


class MaestroExecutorNeutralityTests(unittest.TestCase):
    def test_no_quality_bar_or_why_this_exists_line_co_locates_default_with_a_cli_name(self) -> None:
        definition = _maestro_definition()
        # Scan every prose surface the definition ships, not just the quality
        # bar: review found the one violating string living in handoff_policy,
        # the surface the narrower scan missed.
        lines = (
            tuple(definition.quality_bar)
            + tuple(definition.safety_rules)
            + tuple(definition.do_not_use_when)
            + (definition.why_this_exists, definition.handoff_policy)
        )
        findings = _owner_neutrality_findings(lines)
        self.assertEqual(findings, [], f"owner_neutrality_lost findings: {findings}")

    def test_maestro_copy_never_uses_hermes_mixture_worker_team_vocabulary(self) -> None:
        definition = _maestro_definition()
        surfaces = (
            definition.description,
            definition.use_when,
            definition.why_this_exists,
            *definition.quality_bar,
            *definition.safety_rules,
            *definition.do_not_use_when,
        )
        for text in surfaces:
            words = set(text.casefold().replace("-", " ").split())
            overlap = words & _WORKER_TEAM_TOKENS
            with self.subTest(text=text):
                self.assertEqual(overlap, set())


class MaestroHermesOwnerChecklistTests(unittest.TestCase):
    """#1156 review defect, fixed here: `maestro` structurally cannot have
    Hermes as the selected coding owner (safety rule 3, "Never route a
    Hermes-owned lane through this engine", plus the facade's
    `HermesNativeSelectionError`), so its own `final_checklist` must not
    instruct using `hermes_coding_harness/v1` for a Hermes-owned lane. Other
    handoff-gated skills that CAN take Hermes as owner keep the original
    line -- pinned here via `ai-slop-cleaner`.
    """

    def test_maestro_final_checklist_does_not_instruct_hermes_coding_harness_use(self) -> None:
        definition = _maestro_definition()
        checklist = " ".join(definition.final_checklist)
        self.assertNotIn("use `hermes_coding_harness/v1`", checklist)

    def test_maestro_final_checklist_states_the_engine_does_not_apply_for_hermes_owner(self) -> None:
        definition = _maestro_definition()
        checklist = " ".join(definition.final_checklist)
        self.assertIn(
            "When Hermes is the selected coding owner this engine does not apply -- "
            "Hermes-native selection uses the Hermes runtime path, never this engine.",
            checklist,
        )

    def test_maestro_final_checklist_requires_the_observed_run_summary_close(self) -> None:
        """The close is stated where a run decides it is done, not only in the bar.

        `quality_bar` renders under `## Catalog Metadata`; before this, the
        `omh_run_summary` close appeared there and nowhere else in maestro's
        body, so a run that ended without the summary had nothing in the
        document to fail against. `ultrawork` already carried the equivalent
        checklist line, which is what makes the absence here an omission rather
        than a deliberate difference between the two engines.
        """
        definition = _maestro_definition()
        self.assertTrue(
            any("`omh_run_summary`" in item for item in definition.final_checklist),
            "maestro's completion checklist must name the observed run-summary close",
        )
        self.assertTrue(
            any("not_available" in item for item in definition.final_checklist),
            "the not_available fallback belongs with it, or omitting the summary reads as compliant",
        )

    def test_other_handoff_gated_skill_keeps_the_original_hermes_coding_harness_line(self) -> None:
        definitions = {item.name: item for item in builtin_definitions()}
        checklist = " ".join(definitions["ai-slop-cleaner"].final_checklist)
        self.assertIn(
            "When Hermes is the selected coding owner, use `hermes_coding_harness/v1` "
            "to keep builder, verifier, reviewer, docs, and PR lanes separate.",
            checklist,
        )


class MaestroObserveToTerminalStateTests(unittest.TestCase):
    """The dispatch lifecycle does not end at spawn.

    A supervisor that dispatches and then answers each completion with a
    status report leaves results unverified and the plan untouched -- the
    2026-09-11 incident. Two rules close that: observe every unit to a
    terminal state, and act on a finished one in the same turn. Both name a
    real command and real roster fields, so this pins the words AND proves the
    command they name parses.
    """

    def test_the_quality_bar_names_the_polling_command_and_its_interval(self) -> None:
        combined = " ".join(_maestro_definition().quality_bar)
        self.assertIn("omh coding fanout status --fanout-id <fanout-id> --json", combined)
        self.assertIn("60 seconds", combined)

    def test_the_polling_command_the_skill_names_actually_parses(self) -> None:
        # Derived, not asserted from memory: if the verb is ever renamed, the
        # skill body stops describing a command that exists and this fails.
        from omh.commands.main import build_parser

        args = build_parser().parse_args(
            ["coding", "fanout", "status", "--fanout-id", "fanout-0123456789ab", "--json"]
        )

        self.assertEqual(args.fanout_id, "fanout-0123456789ab")
        self.assertTrue(args.json)

    def test_the_quality_bar_names_the_roster_fields_it_tells_the_agent_to_read(self) -> None:
        from omh.coding.fanout_status import FANOUT_UNIT_STATES

        combined = " ".join(_maestro_definition().quality_bar)
        for field in ("lifecycle_state", "last_event_age_seconds", "failure_diagnostic"):
            self.assertIn(f"`{field}`", combined)
        for terminal in ("unit_verification_observed", "integration_ready"):
            self.assertIn(terminal, FANOUT_UNIT_STATES)
            self.assertIn(f"`{terminal}`", combined)

    def test_every_stuck_state_is_named_as_needing_intervention_now(self) -> None:
        from omh.coding.unit_execution_state import UNIT_STUCK_STATES

        combined = " ".join(_maestro_definition().quality_bar)
        for state in sorted(UNIT_STUCK_STATES):
            self.assertIn(f"`{state}`", combined)
        self.assertIn("needs intervention NOW, not more waiting", combined)
        self.assertIn('Never end a turn on "waiting for the worker"', combined)

    def test_the_quality_bar_names_the_rosters_own_stop_condition(self) -> None:
        # Derived from the producer: the supervisor is told to read the stop
        # condition the roster computes, so if those keys are ever renamed the
        # skill stops describing a payload that exists and this fails.
        import inspect

        from omh.coding.fanout_status import project_fanout_status

        produced = inspect.getsource(project_fanout_status)
        combined = " ".join(_maestro_definition().quality_bar)
        for key in ("all_units_terminal", "stuck_units"):
            self.assertIn(f'"{key}"', produced)
            self.assertIn(f"`{key}`", combined)

    def test_the_quality_bar_bounds_the_poll_loop_on_a_unit_with_no_evidence(self) -> None:
        # `all_units_terminal` is false for a unit with neither marker nor
        # summary row, which is the safe direction and also an unbounded wait:
        # without this sentence the poll loop is itself the stall it was added
        # to catch.
        combined = " ".join(_maestro_definition().quality_bar)
        self.assertIn("still `unknown` after about ten minutes", combined)
        self.assertIn("a poll loop with no bound is the stall it was meant to catch", combined)

    def test_the_completion_chain_is_stated_as_one_turns_work(self) -> None:
        combined = " ".join(_maestro_definition().quality_bar)
        self.assertIn(
            "A finished dispatch is an event to act on in the same turn, not a status to report",
            combined,
        )
        self.assertIn("Never announce a continuation that has not actually started", combined)

    def test_the_rendered_skill_body_carries_both_rules(self) -> None:
        # The generated surface is what an agent loads; a rule that exists only
        # in the definition would never reach one.
        from pathlib import Path

        body = (
            Path(__file__).resolve().parents[1] / "skills" / "ulw-maestro" / "SKILL.md"
        ).read_text(encoding="utf-8")

        self.assertIn("omh coding fanout status --fanout-id <fanout-id> --json", body)
        self.assertIn("A finished dispatch is an event to act on in the same turn", body)


if __name__ == "__main__":
    unittest.main()
