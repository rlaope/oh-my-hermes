from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import build_unit_prompt  # noqa: E402
from omh.coding.model_routing import EXECUTOR_MODEL_OPTIONS, MODEL_ROLES  # noqa: E402
from _cli_harness import run_cli  # noqa: E402
from omh.coding.unit_prompt_protocol import (  # noqa: E402
    FAILURE_KIND_PROTOCOL,
    GOAL_ECHO_PROTOCOL,
    HIGH_EFFORT_CALIBRATIONS,
    HIGH_EFFORT_TIER,
    MAIN_AGENT_COMPOSITION_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS,
    PROMPT_CACHE_COMPOSITION_PROTOCOL,
    REVIEW_ROLE_PROTOCOL,
    STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE,
    TOOL_BATCHING_PROTOCOL,
    UNIT_PROMPT_MAX_BYTES,
    UNIT_RESULT_RETURN_PROTOCOL,
    VERIFICATION_STOP_PROTOCOL,
    calibration_for_route,
    completion_criteria_for_unit,
    composition_calibration_for_model,
    shared_unit_preamble_lines,
)
from omh.coding.unit_prompt_assembly import assemble_unit_prompt  # noqa: E402

_GOAL = "build the virtual dashboard feature across subagents"


def _assembled(unit: dict):
    return assemble_unit_prompt(unit, _GOAL, route=unit["handoff"]["model_route"])


def _contract_unit(units: list[dict], unit_id: str) -> dict:
    contract = build_fanout_contract(_GOAL, units)
    return {unit["unit_id"]: unit for unit in contract["units"]}[unit_id]


class ProtocolContentTests(unittest.TestCase):
    def test_prompt_carries_echo_criteria_and_stop_protocol(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "impl", "title": "Impl", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "impl",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn(GOAL_ECHO_PROTOCOL, prompt)
        self.assertIn("Done means, and only means:", prompt)
        self.assertIn(VERIFICATION_STOP_PROTOCOL, prompt)
        self.assertIn(FAILURE_KIND_PROTOCOL, prompt)
        # Verification stays mandatory: the discipline bounds it, never skips it.
        self.assertIn("verification is never skipped", prompt)
        # A policy denial is a boundary, and "blocked" needs a named persistent
        # condition — neither may be relitigated by a rewrite.
        self.assertIn("policy denial is a boundary, not a bug", prompt)
        self.assertIn("remaining work is not blocked", prompt)
        # Every unit prompt instructs the parse-then-validate structured return.
        self.assertIn(UNIT_RESULT_RETURN_PROTOCOL, prompt)
        # Code exploration is bounded the same way verification is: capped,
        # escalate-on-need, stop-on-found.
        self.assertIn(STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE, prompt)
        self.assertIn("Commit your work; do not merge or push other branches.", prompt)

    def test_the_brief_outranks_repository_workflow_rules(self) -> None:
        # "Stop if they conflict with your brief" made a delegated agent halt
        # whenever the caller's instruction (no branch, no commit) met an
        # AGENTS.md convention (branch first), declining the task before any
        # edit. The brief now outranks repository workflow rules; only a
        # brief that contradicts itself is stopped on.
        self.assertIn("brief outranks repo workflow rules", GOAL_ECHO_PROTOCOL)
        self.assertIn("only a self-contradiction", GOAL_ECHO_PROTOCOL)
        self.assertNotIn("If they conflict with your brief", GOAL_ECHO_PROTOCOL)

    def test_structural_search_discipline_rides_the_shared_invariant_preamble(self) -> None:
        self.assertIn(STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE, shared_unit_preamble_lines(_GOAL))

    def test_tool_batching_rides_every_unit_section_and_stays_out_of_the_frozen_head(self) -> None:
        # Independent work batches, dependent work serializes, and shell output
        # carries no separator noise into the bounded capture (Codex Desktop
        # prompt review, 2026-09-11 — adopted as executor-neutral discipline).
        # It is a unit-section line on purpose: the shared head is frozen at
        # its measured small-model budget, and a batching rule is the first a
        # weak lane may drop, so it never displaces a stop rule there.
        self.assertNotIn(TOOL_BATCHING_PROTOCOL, shared_unit_preamble_lines(_GOAL))
        for role in MODEL_ROLES:
            unit = _contract_unit(
                [{"unit_id": "u", "title": "U", "owner": "codex", "file_scope": ["src/"], "role": role}],
                "u",
            )
            unit_zone = [block.text for block in _assembled(unit).blocks if block.zone == "unit"]
            self.assertIn(TOOL_BATCHING_PROTOCOL, unit_zone, role)
        self.assertIn("independent reads and searches together", TOOL_BATCHING_PROTOCOL)
        self.assertIn("sequential", TOOL_BATCHING_PROTOCOL)
        self.assertIn("separator commands", TOOL_BATCHING_PROTOCOL)
        # Nothing in the batching rule pushes the unit to keep working.
        for push in ("keep going", "to completion", "persist"):
            self.assertNotIn(push, TOOL_BATCHING_PROTOCOL)

    def test_structured_return_names_the_shape_and_the_parse_rule(self) -> None:
        """The report must end in a fenced fanout_unit_result/v1 JSON object so
        collection is parse-then-validate, never prose-scraping."""
        self.assertIn("```json", UNIT_RESULT_RETURN_PROTOCOL)
        self.assertIn("fanout_unit_result/v1", UNIT_RESULT_RETURN_PROTOCOL)
        for field in (
            "schema_version",
            "unit_id",
            "run_id",
            "fanout_id",
            "base_sha",
            "head_sha",
            "process_status",
            "changed_paths",
            "checks",
            "findings",
        ):
            self.assertIn(field, UNIT_RESULT_RETURN_PROTOCOL, field)
        self.assertIn("parses", UNIT_RESULT_RETURN_PROTOCOL)
        self.assertIn("validates", UNIT_RESULT_RETURN_PROTOCOL)
        self.assertIn("never scraped", UNIT_RESULT_RETURN_PROTOCOL)

    def test_integration_checks_become_numbered_criteria(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "impl", "title": "Impl", "owner": "codex", "file_scope": ["src/core/"]},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "impl",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertNotIn("Before finishing:", prompt)
        criteria = completion_criteria_for_unit(unit)
        self.assertGreaterEqual(len(criteria), 3)
        for index, criterion in enumerate(criteria, start=1):
            self.assertIn(f"{index}. {criterion}", prompt)
        # Boundary confinement and committed work are always declared criteria.
        self.assertTrue(any("src/core/" in criterion for criterion in criteria))
        self.assertTrue(any("committed" in criterion for criterion in criteria))

    def test_review_role_gets_criterion_bound_review_protocol(self) -> None:
        review = _contract_unit(
            [
                {"unit_id": "review", "title": "Review", "owner": "codex", "file_scope": ["src/r/"], "role": "review"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "review",
        )
        self.assertIn(REVIEW_ROLE_PROTOCOL, build_unit_prompt(review, _GOAL))
        aux = _contract_unit(
            [
                {"unit_id": "review", "title": "Review", "owner": "codex", "file_scope": ["src/r/"], "role": "review"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "aux",
        )
        self.assertNotIn(REVIEW_ROLE_PROTOCOL, build_unit_prompt(aux, _GOAL))


class SharedPreambleCacheTests(unittest.TestCase):
    def test_sibling_prompts_share_byte_identical_preamble(self) -> None:
        """Provider prompt caches match prefixes by exact bytes, so every
        sibling prompt of one fanout must lead with the same shared bytes."""
        import os.path

        units = [
            {"unit_id": "impl", "title": "Impl", "owner": "codex", "file_scope": ["src/core/"]},
            {"unit_id": "aux", "title": "Aux docs", "owner": "claude-code", "file_scope": ["docs/"]},
        ]
        impl = _contract_unit(units, "impl")
        aux = _contract_unit(units, "aux")
        preamble = "\n".join(shared_unit_preamble_lines(_GOAL))
        prompt_a = build_unit_prompt(impl, _GOAL)
        prompt_b = build_unit_prompt(aux, _GOAL)
        self.assertTrue(prompt_a.startswith(preamble))
        self.assertTrue(prompt_b.startswith(preamble))
        self.assertGreaterEqual(len(os.path.commonprefix([prompt_a, prompt_b])), len(preamble))

    def test_shared_preamble_has_no_volatile_bytes(self) -> None:
        """The shared head depends only on the goal text — never on the unit
        or the clock — or one changed byte forfeits every sibling's cache."""
        lines = shared_unit_preamble_lines(_GOAL)
        preamble = "\n".join(lines)
        # Given unique machine-consumed unit identities (not common prose substrings).
        units = [
            {"unit_id": "volatile-alpha-identity", "title": "volatile-alpha-identity",
             "owner": "codex", "file_scope": ["src/alpha/"]},
            {"unit_id": "volatile-beta-identity", "title": "volatile-beta-identity",
             "owner": "claude-code", "file_scope": ["docs/beta/"]},
        ]
        # When sibling prompts are built, then only their suffix carries each identity.
        for spec in units:
            unit_id = str(spec["unit_id"])
            unit = _contract_unit(units, unit_id)
            prompt = build_unit_prompt(unit, _GOAL)
            self.assertTrue(prompt.startswith(preamble))
            self.assertIn(unit_id, prompt[len(preamble):])
            self.assertNotIn(unit_id, preamble)
        self.assertEqual(lines, shared_unit_preamble_lines(_GOAL))
        import omh.coding.unit_prompt_protocol as module

        self.assertNotIn("datetime", dir(module))

    def test_prompt_cache_protocol_names_the_rule_and_the_families(self) -> None:
        self.assertIn("byte-identical", PROMPT_CACHE_COMPOSITION_PROTOCOL)
        self.assertIn("stagger", PROMPT_CACHE_COMPOSITION_PROTOCOL)
        for family_mechanism in ("Anthropic", "OpenAI", "Gemini", "DeepSeek"):
            self.assertIn(family_mechanism, PROMPT_CACHE_COMPOSITION_PROTOCOL)

    def test_composition_guide_carries_prompt_cache_protocol(self) -> None:
        status, stdout, _stderr = run_cli(["coding", "composition-guide", "--json"])
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(
            payload["delegation_protocol"]["prompt_cache"], PROMPT_CACHE_COMPOSITION_PROTOCOL
        )
        status, stdout, _stderr = run_cli(
            ["coding", "composition-guide", "--model", "claude-fable-5"], output_json=False
        )
        self.assertEqual(status, 0)
        self.assertIn("Prompt-cache discipline", stdout)
        status, stdout, _stderr = run_cli(["coding", "composition-guide"], output_json=False)
        self.assertEqual(status, 0)
        self.assertIn("Prompt-cache discipline (every family):", stdout)


class CalibrationSelectionTests(unittest.TestCase):
    def test_dotted_qwen_cli_contract_reaches_both_calibration_tables(self) -> None:
        from omh.coding.model_contracts import model_contract_projection

        cases = {
            "qwen/qwen3.8-max-0902": "qwen",
            "qwen/qwen3.8-flash": "qwen",
            "qwen3.8-max-0902": "qwen",
            "qwen3.8-flash": "qwen",
            "qwen/qwen3x-flash": "generic",
            "qwen/qwen3": "generic",
        }
        for model, calibration_key in cases.items():
            with self.subTest(model=model):
                units = [
                    {"unit_id": "target", "title": "Parser fix", "owner": "hermes",
                     "file_scope": ["src/"], "role": "implementation",
                     "model": model, "reasoning_effort": "xhigh"},
                    {"unit_id": "docs", "title": "Docs", "owner": "hermes",
                     "file_scope": ["docs/"]},
                ]
                status, stdout, stderr = run_cli(
                    ["coding", "fanout", "prepare", "--goal", _GOAL, "--units", "-"],
                    stdin_text=json.dumps(units),
                )
                self.assertEqual((status, stderr), (0, ""))
                unit = next(u for u in json.loads(stdout)["units"] if u["unit_id"] == "target")
                route = unit["handoff"]["model_route"]
                self.assertEqual(route["selected_model"], model)
                self.assertEqual(route["selected_reasoning_effort"], "xhigh")
                self.assertEqual(route["model_family"], "unknown" if calibration_key == "generic" else "qwen")
                self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS[calibration_key])
                # Compare shipped copies, not pinned prompt wording. This is the
                # renderer dispatch consumes; coding delegate is not this surface.
                prompt = build_unit_prompt(unit, _GOAL)
                self.assertIn(HIGH_EFFORT_CALIBRATIONS[calibration_key], prompt)
                other_key = "qwen" if calibration_key == "generic" else "generic"
                self.assertNotIn(HIGH_EFFORT_CALIBRATIONS[other_key], prompt)
                status, stdout, stderr = run_cli(
                    ["coding", "composition-guide", "--model", model, "--json"]
                )
                self.assertEqual((status, stderr), (0, ""))
                self.assertEqual(json.loads(stdout)["calibration"], MAIN_AGENT_COMPOSITION_CALIBRATIONS[calibration_key])
                self.assertIsNone(model_contract_projection(model))

    def test_high_effort_codex_brain_gets_gpt_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "codex", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        # The codex brain chain head is GPT-6.1 Sol at `high` (2026-10-01),
        # whose exact-model override replaces the `gpt` family block.
        self.assertIn(MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"], prompt)
        self.assertNotIn(HIGH_EFFORT_CALIBRATIONS["gpt"], prompt)

    def test_high_effort_claude_brain_gets_claude_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "claude-code", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "codex", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn(HIGH_EFFORT_CALIBRATIONS["claude"], prompt)

    def test_low_or_absent_effort_gets_no_calibration(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "docs", "title": "Docs", "owner": "codex", "file_scope": ["docs/a/"], "role": "docs"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/b/"]},
            ],
            "docs",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        for block in HIGH_EFFORT_CALIBRATIONS.values():
            self.assertNotIn(block, prompt)

    def test_unknown_family_high_effort_falls_back_to_generic(self) -> None:
        route = {"selected_reasoning_effort": "xhigh", "model_family": "unknown"}
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["generic"])
        route = {"selected_reasoning_effort": "xhigh", "model_family": "mistral"}
        self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS["mistral"])

    def test_vendor_prefixed_models_get_design_family_composition(self) -> None:
        cases = {
            "digitalocean/openai-gpt-5.6-sol": "gpt",
            "digitalocean/anthropic-claude-opus-5": "claude",
        }
        for model_id, family in cases.items():
            self.assertEqual(
                composition_calibration_for_model(model_id),
                MAIN_AGENT_COMPOSITION_CALIBRATIONS[family],
            )

    def test_each_declared_family_gets_its_own_block(self) -> None:
        # gemini/grok/kimi/glm/qwen/deepseek ride provider-surfaced routes; each family's
        # counter-text is distinct data, selected by the recorded model_family.
        for family in ("gpt", "claude", "gemini", "grok", "kimi", "glm", "qwen", "deepseek"):
            route = {"selected_reasoning_effort": "high", "model_family": family}
            self.assertEqual(calibration_for_route(route), HIGH_EFFORT_CALIBRATIONS[family], family)

    def test_target_family_calibrations_preserve_documented_agent_behavior(self) -> None:
        self.assertIn("non-thinking", HIGH_EFFORT_CALIBRATIONS["qwen"])
        self.assertNotIn("<think>", HIGH_EFFORT_CALIBRATIONS["qwen"])
        self.assertIn("model version", HIGH_EFFORT_CALIBRATIONS["deepseek"])
        # DeepSeek's own harness ships the exact-string editor contract the
        # family is post-trained on (deepseek-harness, 2026-08-13). Its
        # priced-prefix fact generalized into the universal prompt-cache
        # protocol, which the composition guide prints beside every composer
        # block, so the family entry no longer repeats it.
        self.assertIn("exact literal strings", HIGH_EFFORT_CALIBRATIONS["deepseek"])
        # Measured 2026-11-17 on og deepseek-v4.1-flash-eco (live-model-tools,
        # 6 templates x 3 seeds x 5 reps): 90/90 with this sentence against
        # 76/90 without it; the search templates wrote a bare list or a
        # wrapper key of their own instead of the task's `locations` object.
        self.assertIn("not a bare list and not a wrapper key", HIGH_EFFORT_CALIBRATIONS["deepseek"])
        self.assertIn("byte-identical", PROMPT_CACHE_COMPOSITION_PROTOCOL)
        self.assertIn("interleaved", HIGH_EFFORT_CALIBRATIONS["glm"])

    def test_claude_subagent_block_drops_the_removed_push_sentence(self) -> None:
        # MODEL-ONBOARDING §2: no calibration sentence may push the model to
        # keep working. The removed sentence was measured on 2026-09-23 (og /
        # anthropic/claude-fable-5-1 at xhigh, 18/30 either way, cost within
        # same-text drift); the evidence sentence beside it is kept.
        block = HIGH_EFFORT_CALIBRATIONS["claude"]
        for clause in (
            "No one is watching",
            "proceed on every reversible action",
            "do that work now",
        ):
            self.assertNotIn(clause, block)
        self.assertIn(
            "Every progress claim points at a tool result from this run — a failed "
            "check is reported with its output, a skipped step as skipped.",
            block,
        )

    def test_claude_composer_block_drops_the_removed_push_clauses(self) -> None:
        # Pins the two clauses removed on 2026-09-23 by their wording; it does
        # not judge whether new wording pushes. Deletion-only and unmeasured:
        # the live benchmark has no fanout and never reaches this block (#1836).
        block = MAIN_AGENT_COMPOSITION_CALIBRATIONS["claude"]
        for clause in (
            "keep working while delegated units run",
            "run it before closing",
        ):
            self.assertNotIn(clause, block.lower())
        self.assertIn("state them once, completely, and freeze", block)
        self.assertIn("keep in line anything that finishes in a handful of tool calls.", block)

    def test_no_route_means_no_calibration(self) -> None:
        self.assertEqual(calibration_for_route(None), "")

    def test_generic_fallback_exists_and_no_family_lacks_discipline(self) -> None:
        # Executor neutrality: the generic block is mandatory so an unknown
        # family never gets weaker discipline than a known one, and every
        # declared block carries the same core stop rule.
        self.assertIn("generic", HIGH_EFFORT_CALIBRATIONS)
        for family, block in HIGH_EFFORT_CALIBRATIONS.items():
            self.assertTrue(block.startswith("High-effort calibration:"), family)


class CompositionCalibrationTests(unittest.TestCase):
    def test_composer_families_mirror_subagent_families(self) -> None:
        """No family gets subagent discipline without composer discipline:
        the two calibration tables share one key set, generic included."""
        self.assertEqual(
            set(MAIN_AGENT_COMPOSITION_CALIBRATIONS), set(HIGH_EFFORT_CALIBRATIONS)
        )
        for family, block in MAIN_AGENT_COMPOSITION_CALIBRATIONS.items():
            self.assertTrue(block.startswith("Composition calibration:"), family)

    def test_selection_follows_the_composers_own_model(self) -> None:
        # The user's own examples: fable5 -> claude family, sol -> gpt,
        # gemini -> gemini, kimi -> kimi, qwen -> qwen; provider prefixes welcome.
        cases = {
            "claude-fable-5": "claude",
            "gpt-5.6-sol": "gpt",
            "gemini-3.1-pro": "gemini",
            "kimi-k3": "kimi",
            "opencode/glm-5": "glm",
            "grok-code-fast-1": "grok",
            "qwen-max-2024-11-26": "qwen",
        }
        for model_id, family in cases.items():
            self.assertEqual(
                composition_calibration_for_model(model_id),
                MAIN_AGENT_COMPOSITION_CALIBRATIONS[family],
                model_id,
            )
        self.assertEqual(
            composition_calibration_for_model("mystery-model-9"),
            MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"],
        )
        self.assertEqual(
            composition_calibration_for_model(""),
            MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"],
        )

    def test_cache_rule_rides_the_guide_beside_every_composer_block(self) -> None:
        # A composer block reaches a model only through `composition-guide`,
        # and both output forms carry PROMPT_CACHE_COMPOSITION_PROTOCOL next
        # to it, so no block restates the shared-preamble cache rule.
        models = ("glm-5.3", "deepseek-v4-pro", "deepseek-flash", "kimi-k3", "claude-fable-5-1")
        for model in models:
            with self.subTest(model=model):
                status, stdout, _stderr = run_cli(
                    ["coding", "composition-guide", "--model", model], output_json=False
                )
                self.assertEqual(status, 0)
                self.assertIn(composition_calibration_for_model(model), stdout)
                self.assertIn(PROMPT_CACHE_COMPOSITION_PROTOCOL, stdout)
                status, stdout, _stderr = run_cli(["coding", "composition-guide", "--model", model, "--json"])
                self.assertEqual(status, 0)
                payload = json.loads(stdout)
                self.assertEqual(payload["delegation_protocol"]["prompt_cache"], PROMPT_CACHE_COMPOSITION_PROTOCOL)

    def test_cli_guide_plain_default_and_json(self) -> None:
        status, stdout, _stderr = run_cli(
            ["coding", "composition-guide", "--model", "claude-fable-5"], output_json=False
        )
        self.assertEqual(status, 0)
        self.assertIn("claude family", stdout)
        self.assertIn("Composition calibration:", stdout)
        status, stdout, _stderr = run_cli(["coding", "composition-guide", "--json"])
        self.assertEqual(status, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "composition_guide/v1")
        self.assertEqual(set(payload["calibrations"]), set(MAIN_AGENT_COMPOSITION_CALIBRATIONS))


class DomainSkillBundleTests(unittest.TestCase):
    def test_declared_work_domain_bundles_the_matching_skill(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "ops", "title": "Fix CI", "owner": "codex", "file_scope": ["ci/"], "role": "implementation", "domain": "devops"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "ops",
        )
        prompt = build_unit_prompt(unit, _GOAL)
        self.assertIn("OMH skill bundle (devops)", prompt)
        self.assertIn("omh-build-failure-triage", prompt)

    def test_no_domain_or_unknown_domain_means_no_bundle(self) -> None:
        from omh.coding.unit_prompt_protocol import DOMAIN_SKILL_GUIDANCE, domain_skill_guidance_line

        self.assertEqual(domain_skill_guidance_line({"unit_id": "x"}), "")
        self.assertEqual(domain_skill_guidance_line({"domain": "gardening"}), "")
        self.assertEqual(
            set(DOMAIN_SKILL_GUIDANCE), {"devops", "app_development", "research", "x_platform_data"}
        )


class PromptBudgetPolicyTests(unittest.TestCase):
    def test_worst_case_prompt_stays_under_budget(self) -> None:
        """Unit prompts become subprocess argv; the ceiling is policy-gated
        here rather than trimmed at runtime. Exercises every profile x role
        combination plus, per calibration family, a requested model that
        selects that family's block (requested models pass through
        unvalidated, so every declared block is reachable on any profile)."""
        wide_scope = [f"src/area{i}/" for i in range(12)]
        requested_models = [""] + [f"{family}-x" for family in HIGH_EFFORT_CALIBRATIONS]
        worst = 0
        for profile in EXECUTOR_MODEL_OPTIONS:
            for role in MODEL_ROLES:
                for requested_model in requested_models:
                    target: dict[str, object] = {
                        "unit_id": "target",
                        "title": "A deliberately verbose unit title for budget measurement",
                        "owner": profile,
                        "file_scope": ["src/target/"],
                        "role": role,
                        "reasoning_effort": "max",
                        "domain": "x_platform_data",
                    }
                    if requested_model:
                        target["model"] = requested_model
                    units = [
                        target,
                        {"unit_id": "sibling", "title": "Sibling", "owner": profile, "file_scope": wide_scope},
                    ]
                    unit = _contract_unit(units, "target")
                    prompt = build_unit_prompt(unit, _GOAL * 3)
                    worst = max(worst, len(prompt.encode("utf-8")))
        self.assertLess(worst, UNIT_PROMPT_MAX_BYTES, f"worst-case unit prompt {worst}B")

    def test_protocol_lines_are_deterministic(self) -> None:
        unit = _contract_unit(
            [
                {"unit_id": "brain", "title": "Brain", "owner": "codex", "file_scope": ["src/d/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"]},
            ],
            "brain",
        )
        self.assertEqual(_assembled(unit), _assembled(unit))
        self.assertEqual(build_unit_prompt(unit, _GOAL), build_unit_prompt(unit, _GOAL))

    def test_high_effort_tier_vocabulary(self) -> None:
        self.assertEqual(HIGH_EFFORT_TIER, frozenset({"high", "xhigh", "max"}))


class ModelOptiDocTests(unittest.TestCase):
    """MODEL_OPTI.md is the human-readable map of the calibration surface.

    The doc promises a section (with trait/injected/why/source) for every
    calibrated family and names the recognized-but-uncalibrated families as
    tracked gaps — so a table change without a doc change fails here.
    """

    def _doc(self) -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "MODEL_OPTI.md").read_text(
            encoding="utf-8"
        )

    def test_every_calibrated_family_has_a_documented_section(self) -> None:
        doc = self._doc()
        for family in HIGH_EFFORT_CALIBRATIONS:
            self.assertIn(f"### `{family}`", doc, family)
        self.assertIn("HIGH_EFFORT_CALIBRATIONS", doc)
        self.assertIn("MAIN_AGENT_COMPOSITION_CALIBRATIONS", doc)
        self.assertIn("UNIT_PROMPT_MAX_BYTES", doc)

    def test_recognized_design_families_are_calibrated(self) -> None:
        for family in ("mistral", "llama", "codestral", "solar", "gpt", "claude"):
            self.assertIn(family, HIGH_EFFORT_CALIBRATIONS)
        for vendor in ("openai", "anthropic"):
            self.assertNotIn(vendor, HIGH_EFFORT_CALIBRATIONS)


if __name__ == "__main__":
    unittest.main()
