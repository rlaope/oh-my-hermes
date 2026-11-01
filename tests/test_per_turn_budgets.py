"""Contracts for the per-request budgets in `budget_metrics()`.

Three OMH surfaces can reach the model on every request or turn: the skill
index lines, the registered tool schemas (eagerly only when Hermes's
tool_search is off), and the fenced `pre_llm_call` context.
Each budget here is only as good as its producer, so every producer is pinned
to what it claims to measure -- and shown to move when the thing it measures
moves -- rather than only to the number it returns today.
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import hashlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.commands.main import build_parser
from omh.install.installer import RECONCILE_CONTEXT_COST_NOTE, _context_cost_warning
from omh.maintenance import per_turn_context
from omh.maintenance.advisory import check_installed_skill_context_weight
from omh.maintenance.drift import budget_metrics, derive_ceiling, limits
from omh.maintenance.release import (
    AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT,
    FULL_PROFILE_SKILL_BODY_HEADROOM_PERCENT,
    FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS,
    FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
    FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
)
from omh.plugin_bundle.omh.awareness import awareness_primer_context
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh import turn_budget
from omh.plugin_bundle.omh.skill_shortlist import skill_candidate_line, skill_candidates_for_turn
from omh.plugin_bundle.omh.tools import BUILTIN_TOOL_NAMES
from omh.plugin_bundle.omh.tools.todo_tool import OMH_TODO_SCHEMA
from omh.skills import skill_index, structure_lint
from omh.skills.catalog import builtin_definitions, installable_skill_names
from omh.skills.context_cost import skill_context_cost_markdown, skill_context_cost_payload
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.validation import skill_structure_lint_payload

PER_REQUEST_BUDGETS = (
    "skill_index_chars",
    "skill_index_line_max_chars",
    "plugin_tool_schema_chars",
    "pre_llm_call_context_chars_max",
    "pre_llm_call_context_fallback_chars_max",
)


class PerRequestBudgetRegistryTests(unittest.TestCase):
    def test_the_per_request_budgets_lead_the_registry(self) -> None:
        names = [metric.name for metric in budget_metrics()]
        self.assertEqual(tuple(names[: len(PER_REQUEST_BUDGETS)]), PER_REQUEST_BUDGETS)

    def test_each_per_request_budget_holds_on_the_tree(self) -> None:
        # Zero-slack ratchets: no headroom step and no reviewed exception
        # (policy in src/maintenance/release.py beside the body ceiling).
        ledger = limits()
        for metric in budget_metrics():
            if metric.name in PER_REQUEST_BUDGETS:
                with self.subTest(metric=metric.name):
                    limit = ledger[metric.name]
                    self.assertEqual(limit.kind, "ratchet")
                    self.assertIsNone(limit.step)
                    self.assertEqual(limit.measured, limit.value)
                    self.assertEqual(metric.reviewed_exception, 0)
                    # Zero-slack means the ratchet sits exactly at its producer
                    # reading; `<=` would also pass a budget wired to the wrong
                    # constant, since `measured == value` holds for every ratchet.
                    self.assertEqual(metric.live(), limit.value)

    def test_the_body_total_is_labelled_as_install_footprint(self) -> None:
        body = next(metric for metric in budget_metrics() if metric.name == "full_profile_skill_body_chars")
        self.assertIn("Install footprint", body.describe)
        self.assertIn("loaded on demand", body.describe)

    def test_repeated_body_ceiling_is_the_documented_headroom_policy(self) -> None:
        # Derived, never picked: the producer-measured figure plus the shared
        # headroom percentage, rounded up to the step (src/maintenance/release.py).
        repeated = next(
            metric for metric in budget_metrics() if metric.name == "full_profile_skill_body_repeated_chars"
        )
        self.assertEqual(repeated.limit, FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT)
        self.assertEqual(repeated.reviewed_exception, 0)
        limit = limits()["full_profile_skill_body_repeated_chars"]
        self.assertEqual(limit.kind, "ceiling")
        self.assertEqual(limit.measured, FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS)
        self.assertEqual(limit.step, FULL_PROFILE_SKILL_BODY_REPEATED_CEILING_STEP_CHARS)
        self.assertEqual(
            FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT,
            derive_ceiling(limit.measured, FULL_PROFILE_SKILL_BODY_HEADROOM_PERCENT, limit.step),
        )

    def test_repeated_body_measurement_is_the_producer_floor(self) -> None:
        # The measurement is a floor as well as the base of the ceiling: a
        # change that moves repeated text into references reads below it and
        # must lower it (and re-derive the ceiling) in the same commit, so the
        # freed slack is never left to be spent later without review; and a
        # measurement inflated above what the producer reads fails here too.
        repeated = next(
            metric for metric in budget_metrics() if metric.name == "full_profile_skill_body_repeated_chars"
        )
        full = next(
            profile for profile in skill_context_cost_payload()["profiles"] if profile["profile"] == "full"
        )
        live = repeated.live()
        self.assertEqual(live, full["repeated"]["bytes"])
        self.assertGreaterEqual(
            live,
            FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS,
            "repeated bytes fell below the recorded measurement: set "
            "FULL_PROFILE_SKILL_BODY_REPEATED_MEASURED_CHARS to the producer value and re-derive the ceiling",
        )
        self.assertLessEqual(live, repeated.limit)

    def test_repeated_body_bytes_move_when_a_body_repeats_another(self) -> None:
        # A body that copies another skill's sections verbatim adds every copied
        # byte to the repeated figure and to the footprint alike; the ratchet
        # must see it, not only the footprint.
        from omh.skills import context_cost

        templates = context_cost.builtin_skill_templates()
        source = templates[0]
        clone = dataclasses.replace(source, name=f"{source.name}-clone")
        metrics = {metric.name: metric for metric in budget_metrics()}
        before = {
            name: metrics[name].live()
            for name in ("full_profile_skill_body_chars", "full_profile_skill_body_repeated_chars")
        }
        with mock.patch.object(context_cost, "builtin_skill_templates", return_value=[*templates, clone]):
            after = {name: metrics[name].live() for name in before}
        for name in before:
            with self.subTest(metric=name):
                self.assertEqual(after[name] - before[name], len(source.content))

    def test_one_more_ordinary_lane_member_fits_every_body_budget(self) -> None:
        # The point of both body ceilings: a new skill that joins an existing
        # lane needs no raise. Render a copy of every ordinary catalog member
        # (no artifact contracts, no progressive disclosure) through the
        # catalog render path under a new name, make its skill-specific
        # sections unique -- a real new skill writes its own -- and keep the
        # rail sections the renderer stamps byte-identical across skills. The
        # largest such member must still fit under both ceilings; when it
        # stops fitting, re-measure and re-derive before the next skill.
        from omh.skills import context_cost
        from omh.skills.render import workflow_skill_from_definition

        templates = context_cost.builtin_skill_templates()
        slices = context_cost._section_slices({template.name for template in templates}, templates)
        copies: dict[tuple[str, str], int] = {}
        for section in slices:
            copies[(section.heading, section.body)] = copies.get((section.heading, section.body), 0) + 1
        names = {template.name for template in templates}
        members = [
            definition
            for definition in builtin_definitions()
            if definition.name in names
            and not definition.artifact_contracts
            and not definition.progressive_disclosure
        ]
        self.assertGreater(len(members), 50)
        metrics = {metric.name: metric for metric in budget_metrics()}
        body_budgets = ("full_profile_skill_body_chars", "full_profile_skill_body_repeated_chars")
        before = {name: metrics[name].live() for name in body_budgets}
        worst: dict[str, tuple[int, str]] = {name: (0, "") for name in body_budgets}
        for definition in members:
            name = f"{definition.name}-lane-mate"
            rendered = workflow_skill_from_definition(dataclasses.replace(definition, name=name), name)
            content = "".join(
                body if copies.get((heading, body), 0) >= 2 else f"{body}<!-- {name} -->\n"
                for heading, body in context_cost._split_sections(rendered.content)
            )
            added = dataclasses.replace(rendered, content=content)
            with mock.patch.object(context_cost, "builtin_skill_templates", return_value=[*templates, added]):
                for budget in body_budgets:
                    delta = metrics[budget].live() - before[budget]
                    if delta > worst[budget][0]:
                        worst[budget] = (delta, definition.name)
        # The copy carries the rail sections, so it must move the repeated figure.
        self.assertGreater(worst["full_profile_skill_body_repeated_chars"][0], 0)
        for budget in body_budgets:
            delta, member = worst[budget]
            with self.subTest(budget=budget, member=member, delta=delta):
                self.assertLessEqual(before[budget] + delta, metrics[budget].limit)


class SkillIndexRenderingTests(unittest.TestCase):
    def test_description_rule_matches_hermes(self) -> None:
        # At the limit the text is untouched; one past it is cut to 57 + "...".
        self.assertEqual(skill_index.hermes_index_description("x" * 60), "x" * 60)
        self.assertEqual(skill_index.hermes_index_description("x" * 61), "x" * 57 + "...")
        # Surrounding whitespace, then surrounding quote characters, are stripped first.
        self.assertEqual(skill_index.hermes_index_description('  "quoted"  '), "quoted")

    def test_one_line_per_installable_skill_under_sorted_category_headers(self) -> None:
        lines = skill_index.full_profile_skill_index_lines()
        skill_lines = [line for line in lines if line.startswith("    - ")]
        headers = [line for line in lines if not line.startswith("    - ")]
        self.assertEqual(len(skill_lines), len(installable_skill_names()))
        self.assertEqual(headers, sorted(headers))
        for header in headers:
            self.assertRegex(header, r"^  [a-z0-9/_-]+:$")
        for line in skill_lines:
            self.assertRegex(line, r"^    - [a-z0-9-]+: \[omh\] .+$")
            self.assertLessEqual(len(line.split(": ", 1)[1]), skill_index.SKILL_PROMPT_DESC_LIMIT)

    def test_totals_are_derived_from_the_rendered_lines(self) -> None:
        lines = skill_index.full_profile_skill_index_lines()
        self.assertEqual(skill_index.skill_index_chars(), len("\n".join(lines)))
        self.assertEqual(
            skill_index.skill_index_line_max_chars(),
            max(len(line) for line in lines if line.startswith("    - ")),
        )


    def test_no_packaged_skill_ships_a_category_description(self) -> None:
        # Hermes renders a category `DESCRIPTION.md` from an external dir into
        # the index header; the producer renders bare headers, which is only
        # right while OMH ships none.
        shipped = [ref.relative_path for ref in builtin_skill_reference_templates()]
        self.assertEqual([path for path in shipped if Path(path).name == "DESCRIPTION.md"], [])
        repo_skills = Path(__file__).resolve().parents[1] / "skills"
        self.assertEqual(sorted(repo_skills.rglob("DESCRIPTION.md")), [])


def _hermes_source(relative: str) -> Path | None:
    """A file of an importable Hermes checkout, located without importing Hermes.

    The checkout root is found through Hermes's `agent` package, the one
    top-level name with no OMH-side twin: this repository has its own
    top-level `tools/`, so `find_spec("tools")` would answer with OMH's.
    """
    package = importlib.util.find_spec("agent")
    locations = list(package.submodule_search_locations or []) if package else []
    for location in locations:
        candidate = Path(location).parent / relative
        if (Path(location) / "skill_utils.py").is_file() and candidate.is_file():
            return candidate
    return None


class UpstreamDescriptionLimitPinTests(unittest.TestCase):
    """`SKILL_PROMPT_DESC_LIMIT` is copied from Hermes; this is where the copy is checked.

    OMH does not import Hermes, so the comparison reads the upstream source
    text. It runs wherever a Hermes checkout is importable (a Hermes venv, or
    a PYTHONPATH that includes one) and is skipped, saying so, elsewhere --
    including CI, which installs no Hermes.
    """

    def test_copied_limit_matches_the_upstream_line(self) -> None:
        # Locate the top-level `agent` package without importing it (a
        # submodule lookup would execute Hermes's package `__init__`).
        upstream = _hermes_source("agent/skill_utils.py")
        if upstream is None:
            self.skipTest("no Hermes checkout is importable; agent/skill_utils.py cannot be compared")
        source = upstream.read_text(encoding="utf-8")
        match = re.search(r"^SKILL_PROMPT_DESC_LIMIT = (\d+)$", source, re.MULTILINE)
        self.assertIsNotNone(match, f"{upstream} no longer defines SKILL_PROMPT_DESC_LIMIT")
        assert match is not None
        self.assertEqual(int(match.group(1)), skill_index.SKILL_PROMPT_DESC_LIMIT)
        self.assertIn('desc[:SKILL_PROMPT_DESC_LIMIT - 3] + "..."', source)


def _module_literals(tree: ast.Module) -> dict[str, object]:
    """Module-level names whose value is a plain literal, in source order."""
    names: dict[str, object] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                names[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
    return names


def _eval_toolset_expr(node: ast.AST, names: dict[str, object]) -> set[str]:
    """Evaluate a module-level toolset expression without importing Hermes.

    Hermes moved `_DIRECT_SURFACE_TOOLSETS` from a literal `frozenset({...})`
    to `CLIENT_SURFACE_TOOLSETS | TOOLSET_SESSION_PLATFORMS.keys()`.  The
    invariant is the resulting set, not the spelling, so resolve names, literal
    sets/dicts, `|` unions and `.keys()` calls over literal module constants.
    """
    if isinstance(node, ast.Name):
        value = names.get(node.id)
        if isinstance(value, (set, frozenset, list, tuple)):
            return set(value)
        if isinstance(value, dict):
            return set(value)
        raise TypeError(f"{node.id} is not a literal collection at module level")
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return {ast.literal_eval(element) for element in node.elts}
    if isinstance(node, ast.Dict):
        return {ast.literal_eval(key) for key in node.keys}
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
        and len(node.args) == 1
    ):
        return _eval_toolset_expr(node.args[0], names)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _eval_toolset_expr(node.left, names) | _eval_toolset_expr(node.right, names)
    if (
        isinstance(node, ast.Call)
        and not node.args
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "keys"
    ):
        return _eval_toolset_expr(node.func.value, names)
    if isinstance(node, ast.Attribute):
        value = names.get(node.attr)
        if isinstance(value, (set, frozenset, list, tuple, dict)):
            return set(value)
    raise TypeError(ast.dump(node))


def _session_platform_toolsets(toolsets_source: Path) -> set[str]:
    """Keys of `TOOLSETS` whose spec declares `platforms` (the session-gated set)."""
    tree = ast.parse(toolsets_source.read_text(encoding="utf-8"))
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "TOOLSETS" for target in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            continue
        names: set[str] = set()
        for key, value in zip(node.value.keys, node.value.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            declares = (
                isinstance(value, ast.Dict)
                and any(isinstance(item, ast.Constant) and item.value == "platforms" for item in value.keys)
            ) or (
                isinstance(value, ast.Call)
                and any(keyword.arg == "platforms" for keyword in value.keywords)
            )
            if declares:
                names.add(key.value)
        return names
    raise AssertionError(f"{toolsets_source} no longer defines TOOLSETS as a mapping")


def _resolve_module_names(tree: ast.Module) -> dict[str, object]:
    """Literal module names plus reducible `frozenset({...})`/union assignments."""
    names = _module_literals(tree)
    for _ in range(len(tree.body)):
        progressed = False
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            try:
                value = _eval_toolset_expr(node.value, names)
            except (TypeError, ValueError):
                continue
            if names.get(node.targets[0].id) != value:
                names[node.targets[0].id] = value
                progressed = True
        if not progressed:
            break
    return names


def _imported_literal_names(source: Path, tree: ast.Module) -> dict[str, object]:
    """Literal constants of `from <module> import <name>` for sibling Hermes modules."""
    names: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for candidate in (source.parent / f"{node.module}.py", source.parent.parent / f"{node.module}.py"):
            if candidate.is_file():
                break
        else:
            continue
        imported = _resolve_module_names(ast.parse(candidate.read_text(encoding="utf-8")))
        for alias in node.names:
            original = alias.name
            if original in imported:
                names[alias.asname or original] = imported[original]
            elif original == "TOOLSET_SESSION_PLATFORMS":
                names[alias.asname or original] = _session_platform_toolsets(candidate)
    return names


def _direct_surface_toolsets(source: Path) -> set[str]:
    """The resolved `_DIRECT_SURFACE_TOOLSETS` of a Hermes `tools/tool_search.py`."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assignments = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_DIRECT_SURFACE_TOOLSETS" for target in node.targets)
    ]
    if not assignments:
        raise AssertionError(f"{source} no longer defines _DIRECT_SURFACE_TOOLSETS")
    names = {**_imported_literal_names(source, tree), **_resolve_module_names(tree)}
    return _eval_toolset_expr(assignments[-1].value, names)


def _tool_search_default_enabled(source: Path) -> str:
    """`DEFAULT_CONFIG["tools"]["tool_search"]["enabled"]`, read from the AST.

    The surrounding defaults mapping is not a pure literal, so walk mappings
    for the `tool_search` block instead of parsing one indentation spelling.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "tool_search" and isinstance(value, ast.Dict)):
                continue
            for inner_key, inner_value in zip(value.keys, value.values):
                if (
                    isinstance(inner_key, ast.Constant)
                    and inner_key.value == "enabled"
                    and isinstance(inner_value, ast.Constant)
                    and isinstance(inner_value.value, str)
                ):
                    return inner_value.value
    raise AssertionError(f"{source} no longer defines a tool_search.enabled default")


class UpstreamToolDeferralPinTests(unittest.TestCase):
    """`plugin_tool_schema_chars` is labelled an eager ceiling because Hermes defers plugin tools.

    Under Hermes's default `tools.tool_search.enabled: auto` every non-core
    tool outside `_DIRECT_SURFACE_TOOLSETS` is deferrable, which puts the
    `omh` toolset behind the bridge.  The invariant is the resolved set, so it
    is read with `ast` instead of one regex spelling; the actual deferral of a
    registered `omh` tool is observed end to end by
    `tools/check_hermes_compatibility.py` in the Hermes compatibility workflow.
    """

    def test_the_omh_toolset_is_deferrable_by_default_upstream(self) -> None:
        tool_search = _hermes_source("tools/tool_search.py")
        defaults = _hermes_source("hermes_cli/config_defaults.py")
        if tool_search is None or defaults is None:
            self.skipTest("no Hermes checkout is importable; tools/tool_search.py cannot be compared")
        direct = _direct_surface_toolsets(tool_search)
        self.assertIsInstance(direct, set)
        self.assertNotIn("omh", direct)
        self.assertTrue(direct, "the resolved direct-surface set is empty; the expression was not understood")
        source = tool_search.read_text(encoding="utf-8")
        # The rule's wording has changed between Hermes versions; its name has not.
        self.assertIn("def is_deferrable_tool_name(", source)
        self.assertIn(_tool_search_default_enabled(defaults), {"auto", "on"})

    def test_the_budget_is_described_as_an_eager_ceiling(self) -> None:
        metric = next(m for m in budget_metrics() if m.name == "plugin_tool_schema_chars")
        self.assertIn("Eager ceiling", metric.describe)
        self.assertIn("tool_search", metric.describe)
        self.assertNotRegex(metric.describe, r"^Per request")


class CorrectedContextCostWordingTests(unittest.TestCase):
    """Every surface that used to call a skill body per-turn or always loaded."""

    STALE = ("always-loaded", "always loaded", "per-turn context weight")

    def assertCorrected(self, text: str, *expected: str) -> None:
        lowered = text.lower()
        for stale in self.STALE:
            self.assertNotIn(stale, lowered)
        for phrase in expected:
            self.assertIn(phrase, text)

    @staticmethod
    def _subparser(parser: argparse.ArgumentParser, name: str) -> tuple[argparse._SubParsersAction, argparse.ArgumentParser]:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction) and name in action.choices:
                return action, action.choices[name]
        raise AssertionError(f"no subcommand {name}")

    def test_reconcile_note(self) -> None:
        self.assertCorrected(RECONCILE_CONTEXT_COST_NOTE, "index line", "each time its body loads")

    def test_full_profile_warning(self) -> None:
        self.assertCorrected(_context_cost_warning(core_count=1, full_count=2)["message"], "index line", "body loads")

    def test_setup_core_help(self) -> None:
        _action, setup = self._subparser(build_parser(), "setup")
        (core,) = [action for action in setup._actions if "--core" in action.option_strings]
        self.assertCorrected(str(core.help), "index line", "per body load")

    def test_skill_context_cost_help(self) -> None:
        _action, docs = self._subparser(build_parser(), "docs")
        action, _parser = self._subparser(docs, "skill-context-cost")
        (choice,) = [item for item in action._choices_actions if item.dest == "skill-context-cost"]
        self.assertCorrected(str(choice.help), "per skill view")

    def test_skill_context_cost_payload_and_report(self) -> None:
        self.assertCorrected(str(skill_context_cost_payload()["description"]), "index line")
        self.assertCorrected(skill_context_cost_markdown(), "- Skill body total (install footprint")

    def test_structure_lint_ceiling_message(self) -> None:
        (definition,) = [d for d in builtin_definitions() if d.name == "plan"]
        with mock.patch.object(structure_lint, "STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING", 0):
            message = structure_lint._lint_context_budget(definition)
        self.assertCorrected(message, "SKILL.md body (per load)")

    def test_doctor_advisory_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            entry = check_installed_skill_context_weight(hermes_home=home, skills_dirs=[])
        self.assertCorrected(entry.remediation, "index line")


class IndexOpeningLintTests(unittest.TestCase):
    RULE = "SKILL_INDEX_OPENING_DISTINCT"

    def _with_descriptions(self, **descriptions: str) -> list:
        definitions = list(builtin_definitions())
        for index, definition in enumerate(definitions):
            if definition.name in descriptions:
                definitions[index] = dataclasses.replace(definition, description=descriptions[definition.name])
        return definitions

    def _rule_details(self, payload: dict[str, object]) -> list[str]:
        violations = payload["violations"]
        assert isinstance(violations, list)
        return [str(item["detail"]) for item in violations if item["rule"] == self.RULE]

    def test_opening_is_the_first_three_visible_words_after_the_prefix(self) -> None:
        self.assertEqual(skill_index.index_opening("[omh] Hermes Code Review workflow: bug-first"), "hermes code review")

    def test_the_opening_words_are_the_same_with_and_without_the_description_prefix(self) -> None:
        # An installed body keeps the prefix until its next update; the lint
        # must read the same opening words from either.
        for text in ("Hermes Code Review workflow: bug-first", "Review, a pull request."):
            with self.subTest(text=text):
                self.assertEqual(skill_index.index_opening(f"[omh] {text}"), skill_index.index_opening(text))
        self.assertEqual(skill_index.index_opening("Hermes Code Review workflow: bug-first"), "hermes code review")

    def test_the_prefix_costs_six_characters_of_the_visible_window(self) -> None:
        # The window is 57 characters either way; the prefix sits inside it.
        self.assertEqual(skill_index.index_opening("[omh] " + "a" * 60 + " b c"), "a" * 51)
        self.assertEqual(skill_index.index_opening("a" * 60 + " b c"), "a" * 57)

    def test_openings_that_differ_by_the_third_word_do_not_collide(self) -> None:
        pairs = [("one", "[omh] Hermes frontend workflow: x"), ("two", "[omh] Hermes frontend refactor: y")]
        self.assertEqual(skill_index.index_opening_collisions(pairs), {})

    def test_punctuation_around_a_word_does_not_separate_openings(self) -> None:
        self.assertEqual(skill_index.index_opening("[omh] Review, a pull request."), "review a pull")
        self.assertEqual(skill_index.index_opening("[omh] Review: a -- pull request"), "review a pull")
        pairs = [("one", "[omh] Review, a pull request."), ("two", "[omh] Review a pull request for plan fit.")]
        self.assertEqual(skill_index.index_opening_collisions(pairs), {"review a pull": frozenset({"one", "two"})})

    def test_a_hyphenated_word_stays_one_word(self) -> None:
        self.assertEqual(skill_index.index_opening("[omh] Code-review lane for diffs"), "code-review lane for")

    def test_the_same_skill_twice_is_not_a_collision(self) -> None:
        pairs = [("one", "[omh] Same three words here"), ("one", "[omh] Same three words here")]
        self.assertEqual(skill_index.index_opening_collisions(pairs), {})

    def test_the_tree_carries_exactly_the_reviewed_groups(self) -> None:
        payload = skill_structure_lint_payload()
        self.assertEqual(self._rule_details(payload), [])
        self.assertIn(self.RULE, payload["rules"])
        for opening, (skills, reason) in skill_index.REVIEWED_SHARED_INDEX_OPENINGS.items():
            with self.subTest(opening=opening):
                self.assertGreaterEqual(len(skills), 2)
                self.assertLessEqual(skills, set(installable_skill_names()))
                self.assertGreater(len(reason), 60, "a reason is not a label")

    def test_the_installed_files_agree_with_the_reviewed_groups(self) -> None:
        # The lint renders descriptions from catalog definitions; Hermes reads
        # them from the installed SKILL.md files. Both views must see the same
        # shared openings, or the lint is guarding a surface nobody ships.
        from_files = skill_index.index_opening_collisions(skill_index.full_profile_index_descriptions())
        reviewed = {opening: skills for opening, (skills, _reason) in skill_index.REVIEWED_SHARED_INDEX_OPENINGS.items()}
        self.assertEqual(from_files, reviewed)

    def test_a_new_shared_opening_fails_alone(self) -> None:
        payload = skill_structure_lint_payload(
            definitions=self._with_descriptions(
                **{
                    "code-review": "Quokka lemur tapir code review lane.",
                    "plan": "Quokka lemur tapir planning lane.",
                }
            )
        )
        details = self._rule_details(payload)
        self.assertEqual(len(details), 1, details)
        self.assertIn("['code-review', 'plan']", details[0])
        self.assertIn("'quokka lemur tapir'", details[0])
        violations = payload["violations"]
        assert isinstance(violations, list)
        self.assertEqual({item["rule"] for item in violations}, {self.RULE})

    # The tree carries no reviewed group, so these two record one of their own.
    _SYNTHETIC_REASON = "A synthetic reviewed group for this test, long enough to read as a reason and not a label."

    def test_a_reviewed_group_gaining_a_member_fails(self) -> None:
        reviewed = {"quokka lemur tapir": (frozenset({"plan", "ralplan"}), self._SYNTHETIC_REASON)}
        with mock.patch.object(skill_index, "REVIEWED_SHARED_INDEX_OPENINGS", reviewed):
            payload = skill_structure_lint_payload(
                definitions=self._with_descriptions(
                    **{
                        "plan": "Quokka lemur tapir planning lane.",
                        "ralplan": "Quokka lemur tapir consensus lane.",
                        "code-review": "Quokka lemur tapir review lane.",
                    }
                )
            )
        details = self._rule_details(payload)
        self.assertEqual(len(details), 1, details)
        self.assertIn("'code-review'", details[0])

    def test_a_stale_record_fails_on_the_full_catalog(self) -> None:
        reviewed = {"quokka lemur tapir": (frozenset({"plan", "code-review"}), self._SYNTHETIC_REASON)}
        with mock.patch.object(skill_index, "REVIEWED_SHARED_INDEX_OPENINGS", reviewed):
            payload = skill_structure_lint_payload()
        details = self._rule_details(payload)
        self.assertEqual(len(details), 1, details)
        self.assertIn("update or delete the record", details[0])

    def test_a_supplied_subset_never_reports_a_record_stale(self) -> None:
        subset = [definition for definition in builtin_definitions() if definition.name == "skill-health"]
        self.assertEqual(self._rule_details(skill_structure_lint_payload(definitions=subset)), [])

    def test_a_retired_definition_contributes_no_index_line(self) -> None:
        retired = sorted({d.name for d in builtin_definitions()} - set(installable_skill_names()))
        self.assertTrue(retired, "fixture needs a non-installable catalog definition")
        payload = skill_structure_lint_payload(
            definitions=self._with_descriptions(
                **{retired[0]: "Quokka lemur tapir retired.", "plan": "Quokka lemur tapir planning."}
            )
        )
        self.assertEqual(self._rule_details(payload), [])


class PluginToolSchemaProducerTests(unittest.TestCase):
    def test_the_recording_context_sees_every_registered_tool(self) -> None:
        self.assertEqual(sorted(per_turn_context.registered_tool_schemas()), sorted(BUILTIN_TOOL_NAMES))

    def test_the_total_is_the_sum_of_the_per_tool_sizes(self) -> None:
        by_tool = per_turn_context.plugin_tool_schema_chars_by_tool()
        self.assertEqual(per_turn_context.plugin_tool_schema_chars(), sum(by_tool.values()))

    def test_parked_dag_schema_growth_is_bounded_without_spending_legacy_content(self) -> None:
        # The approved preflight schema was also 2479 JSON characters. Remove
        # only parked additions, retaining preflight's marker refusal and
        # one-shot cap wording; pin its intact schema, not just its size, so
        # removing an existing safeguard cannot finance parked growth.
        schema = per_turn_context.registered_tool_schemas()["omh_dag"]
        legacy = copy.deepcopy(schema)
        parked_note = (
            "A still-running wait may settle parked with "
            "handle and wake_at (future UTC ISO-8601 or epoch, within 24h); ready reoffers it then, at most three parks. "
        )
        self.assertEqual(legacy["description"].count(parked_note), 1)
        legacy["description"] = legacy["description"].replace(parked_note, "", 1)
        properties = legacy["parameters"]["properties"]
        self.assertEqual(properties.pop("handle")["maxLength"], 120)
        self.assertEqual(properties.pop("wake_at")["type"], ["string", "number"])
        self.assertEqual(properties["outcome"]["enum"].count("parked"), 1)
        properties["outcome"]["enum"].remove("parked")
        # The node `category` enum is the routable vocabulary, which grew by
        # the six routing-recipe categories on 2026-10-28 (+75, funded by its
        # own PLUGIN_TOOL_SCHEMA_CHAR_LIMIT entry). Strip exactly those so the
        # approved schema below is still compared intact.
        category_enum = properties["nodes"]["items"]["properties"]["category"]["enum"]
        recipe = ["google-search", "x-search", "review", "swarm", "forensics", "synthesize"]
        self.assertEqual(category_enum[-len(recipe):], recipe)
        del category_enum[-len(recipe):]
        # The node `role` field (+85, its own PLUGIN_TOOL_SCHEMA_CHAR_LIMIT entry) is stripped the same way, from
        # this and from the live schema below, so it can spend neither the approved schema nor the parked cap.

        def without_role(target: dict) -> int:
            before = len(json.dumps(target, sort_keys=True, ensure_ascii=False))
            role = target["parameters"]["properties"]["nodes"]["items"]["properties"].pop("role")
            self.assertEqual(role, {"type": "string", "enum": ["build", "baseline", "verify", "review"]})
            self.assertEqual(target["description"].count("write_scope, role)"), 1)
            target["description"] = target["description"].replace("write_scope, role)", "write_scope)", 1)
            return before - len(json.dumps(target, sort_keys=True, ensure_ascii=False))

        self.assertEqual(without_role(legacy), 85)
        encoded = json.dumps(legacy, sort_keys=True, ensure_ascii=False)
        self.assertEqual(len(encoded), 2479)
        self.assertEqual(
            hashlib.sha256(encoded.encode()).hexdigest(),
            "39be91ffc4db311ad1222cd4f57ded619ceb643063fdaa7bb2f0605fe654d3c5",
        )
        # The parked cap is measured against the live schema without the six
        # category values, so category growth cannot spend the parked cap.
        live = copy.deepcopy(schema)
        del live["parameters"]["properties"]["nodes"]["items"]["properties"]["category"]["enum"][-len(recipe):]
        self.assertEqual(without_role(live), 85)
        delta = len(json.dumps(live, sort_keys=True, ensure_ascii=False)) - len(encoded)
        self.assertEqual(
            per_turn_context.plugin_tool_schema_chars_by_tool()["omh_dag"] - len(encoded) - delta, 75 + 85
        )
        self.assertGreater(delta, 0)
        self.assertLessEqual(delta, 429)  # Measured feature cap, not general headroom.

    def test_a_longer_schema_description_moves_the_total(self) -> None:
        before = per_turn_context.plugin_tool_schema_chars()
        grown = str(OMH_TODO_SCHEMA["description"]) + " padding"
        with mock.patch.dict(OMH_TODO_SCHEMA, {"description": grown}):
            after = per_turn_context.plugin_tool_schema_chars()
        self.assertEqual(after - before, len(" padding"))


class PreLlmCallScenarioTests(unittest.TestCase):
    def test_the_scenario_set_is_fixed_and_named(self) -> None:
        scenarios = per_turn_context.pre_llm_call_context_scenario_chars()
        self.assertEqual(
            sorted(scenarios),
            sorted(
                [
                    "first_turn_without_section",
                    "route_hint",
                    "skill_candidates",
                    "role_marker",
                    "active_workflow",
                    "running_work_board",
                    "done_unverified_plan",
                    "held_native_write",
                    "all_surfaces",
                    "all_surfaces_without_section",
                ]
            ),
        )
        for name, chars in scenarios.items():
            with self.subTest(scenario=name):
                self.assertGreater(chars, 0, f"{name} injected nothing, so it measures nothing")

    def test_the_held_write_scenario_measures_the_held_write_line(self) -> None:
        # The scenario is only worth its name if the line is in what it
        # measures: without the pending fact the same turn is exactly the
        # line and its join shorter.
        from omh.plugin_bundle.omh import native_todo

        with_line = per_turn_context.pre_llm_call_context_scenario_chars()["held_native_write"]
        with mock.patch.object(native_todo, "_note_held_write", lambda *args, **kwargs: None):
            without_line = per_turn_context.pre_llm_call_context_scenario_chars()["held_native_write"]
        line = native_todo.HELD_NATIVE_WRITE_NOTE.format(kind="accepted plan")
        self.assertEqual(with_line - without_line, len(line) + len("\n\n"))

    def test_parts_add_so_all_surfaces_is_the_maximum(self) -> None:
        scenarios = per_turn_context.pre_llm_call_context_scenario_chars()
        self.assertEqual(per_turn_context.pre_llm_call_context_chars_max(), scenarios["all_surfaces"])
        for name in ("route_hint", "role_marker", "active_workflow", "running_work_board"):
            with self.subTest(scenario=name):
                self.assertLess(scenarios[name], scenarios["all_surfaces"])

    def test_the_fallback_maximum_is_all_surfaces_with_the_primer(self) -> None:
        scenarios = per_turn_context.pre_llm_call_context_scenario_chars()
        self.assertEqual(
            per_turn_context.pre_llm_call_context_fallback_chars_max(), scenarios["all_surfaces_without_section"]
        )
        # The fallback differs from the section host by exactly the primer and
        # its join, so the fallback limit gates the primer's own growth there.
        self.assertEqual(
            scenarios["all_surfaces_without_section"] - scenarios["all_surfaces"],
            len(awareness_primer_context()) + len("\n\n"),
        )

    def test_a_larger_primer_moves_the_fallback_maximum(self) -> None:
        before = per_turn_context.pre_llm_call_context_fallback_chars_max()
        with mock.patch.object(turn_budget, "awareness_primer_context", return_value="p" * 2000):
            after = per_turn_context.pre_llm_call_context_fallback_chars_max()
        self.assertEqual(after - before, 2000 - len(awareness_primer_context()))

    def test_two_runs_measure_the_same(self) -> None:
        self.assertEqual(
            per_turn_context.pre_llm_call_context_scenario_chars(),
            per_turn_context.pre_llm_call_context_scenario_chars(),
        )

    def test_the_primer_limit_still_binds_the_primer_alone(self) -> None:
        self.assertLessEqual(len(awareness_primer_context()), AWARENESS_PRIMER_CONTEXT_CHAR_LIMIT)
        # The first-turn scenario is the primer inside the fence, plus the
        # request's skill candidate line when it has one, and nothing else.
        first_turn = per_turn_context.pre_llm_call_context_scenario_chars()["first_turn_without_section"]
        fence_overhead = len(llm_hooks.fence_omh_context(["x"])) - 1
        line = skill_candidate_line(skill_candidates_for_turn(per_turn_context._PLAIN_REQUEST))
        line_chars = len("\n\n" + line) if line else 0
        self.assertEqual(first_turn, len(awareness_primer_context()) + fence_overhead + line_chars)

    def test_a_larger_injected_part_moves_the_measurement(self) -> None:
        before = per_turn_context.pre_llm_call_context_scenario_chars()["first_turn_without_section"]
        with mock.patch.object(turn_budget, "awareness_primer_context", return_value="p" * 2000):
            after = per_turn_context.pre_llm_call_context_scenario_chars()["first_turn_without_section"]
        self.assertEqual(after - before, 2000 - len(awareness_primer_context()))

    def test_the_primer_is_absent_from_every_section_scenario(self) -> None:
        # The section scenarios are the default host; a primer that grows must
        # not move them, or the primer is still riding the per-turn context.
        before = per_turn_context.pre_llm_call_context_scenario_chars()
        with mock.patch.object(turn_budget, "awareness_primer_context", return_value="p" * 2000):
            after = per_turn_context.pre_llm_call_context_scenario_chars()
        for name in before:
            if name.endswith("_without_section"):
                continue
            with self.subTest(scenario=name):
                self.assertEqual(after[name], before[name])


if __name__ == "__main__":
    unittest.main()
