"""Contracts for `plan_variant/v1` (issue #827).

Three acceptance criteria, three classes, and one guard class for the failure
the whole record family exists to prevent: a variant being read as the plan it
forked. The accepted plan is the artifact a prepared handoff points at by
digest, so anything that rewrites it, or that lets a what-if answer to
"which plan is next" masquerade as that artifact, is the regression here.
"""

from __future__ import annotations

import ast
import json
import socket
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths  # noqa: E402
from omh.workflows.hermes_planning import (  # noqa: E402
    build_hermes_plan_payload,
    read_hermes_plan_artifact,
    update_hermes_plan_status,
    write_hermes_plan,
)
from omh.workflows.plan_variants import (  # noqa: E402
    PLAN_VARIANT_CLAIM_BOUNDARY,
    PLAN_VARIANT_DELTA_DIMENSIONS,
    PLAN_VARIANT_HANDOFF_BOUNDARY,
    PLAN_VARIANT_KEYS,
    PLAN_VARIANT_NOT_OBSERVED,
    PLAN_VARIANT_REF_KINDS,
    PLAN_VARIANT_SCHEMA_VERSION,
    build_plan_variant,
    build_plan_variant_delta,
    build_plan_variant_ref,
    normalize_plan_variant_dimension,
    normalize_plan_variant_ref_kind,
    render_plan_variant_text,
    validate_plan_variant,
    write_plan_variant,
)

T0 = "2026-08-09T00:00:00Z"
T1 = "2026-08-10T12:34:56Z"
TASK = "implement a coding delegation flow with tests"

OWNER_DELTA = {
    "dimension": "coding_owner",
    "label": "selected executor",
    "parent_value": "codex",
    "variant_value": "claude-code",
}
SCOPE_DELTA = {
    "dimension": "scope",
    "label": "docs",
    "parent_value": "ship docs in the same PR",
    "variant_value": "defer docs to a follow-up",
}


def _accepted_plan(tmp: str, *, task: str = TASK) -> dict[str, Any]:
    """Write a real plan through the real lifecycle, then accept it."""
    paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
    artifact = write_hermes_plan(paths, build_hermes_plan_payload(task))
    update_hermes_plan_status(paths, artifact["path"], status="accepted", allow_scaffold=True)
    return read_hermes_plan_artifact(artifact["path"])


def _variant(parent: dict[str, Any], **overrides: Any) -> dict[str, object]:
    arguments: dict[str, Any] = {
        "parent_artifact": parent,
        "name": "claude-code owner",
        "deltas": [OWNER_DELTA],
        "created_at": T0,
    }
    arguments.update(overrides)
    return build_plan_variant(**arguments)


class OriginalPlanRemainsUnchangedTests(unittest.TestCase):
    """AC1: forking a plan never touches the plan it forked."""

    def test_building_and_recording_a_variant_leaves_the_parent_byte_identical(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)
            plan_path = Path(str(parent["path"]))
            before = plan_path.read_bytes()

            variant = _variant(parent, deltas=[OWNER_DELTA, SCOPE_DELTA])
            record = write_plan_variant(resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes"), variant)

            self.assertEqual(plan_path.read_bytes(), before)
            # The digest the variant carries still describes the file on disk,
            # which is the only reason a parent reference means anything.
            self.assertEqual(
                variant["parent_plan_sha256"],
                read_hermes_plan_artifact(plan_path)["sha256"],
            )
            self.assertTrue(Path(str(record["path"])).exists())

    def test_the_variant_is_written_outside_the_plans_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            parent = _accepted_plan(tmp)
            plans_dir = Path(str(parent["path"])).parent
            before = sorted(path.name for path in plans_dir.iterdir())

            record = write_plan_variant(paths, _variant(parent))

            # A variant landing in `plans/` would be picked up by anything that
            # scans the plan store, which is exactly the confusion AC1 forbids.
            self.assertEqual(sorted(path.name for path in plans_dir.iterdir()), before)
            self.assertEqual(Path(str(record["path"])).parent.name, "plan-variants")

    def test_recording_the_same_fork_twice_rewrites_one_file(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            parent = _accepted_plan(tmp)

            first = write_plan_variant(paths, _variant(parent, created_at=T0))
            second = write_plan_variant(paths, _variant(parent, created_at=T1))

            self.assertEqual(first["path"], second["path"])
            variants_dir = Path(str(first["path"])).parent
            self.assertEqual(len(list(variants_dir.glob("*.json"))), 1)


class ChangedInputsAndInheritedRefsTests(unittest.TestCase):
    """AC2: every variant lists changed inputs and inherited references."""

    def test_every_delta_is_listed_as_a_changed_input(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp), deltas=[OWNER_DELTA, SCOPE_DELTA])

            self.assertEqual(variant["delta_count"], 2)
            self.assertEqual(
                variant["changed_inputs"],
                [
                    "coding_owner | selected executor: codex -> claude-code",
                    "scope | docs: ship docs in the same PR -> defer docs to a follow-up",
                ],
            )
            self.assertEqual(validate_plan_variant(variant), [])

    def test_the_accepted_parent_is_always_an_inherited_reference(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)
            variant = _variant(parent)

            inherited = variant["inherited_refs"]
            self.assertEqual(variant["inherited_ref_count"], 1)
            self.assertEqual(inherited[0]["kind"], "plan_artifact")
            self.assertEqual(inherited[0]["ref"], parent["path"])
            self.assertTrue(inherited[0]["reviewed"])

    def test_an_unreviewed_reference_is_held_for_reevaluation_not_inherited(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(
                _accepted_plan(tmp),
                refs=[
                    build_plan_variant_ref(kind="context_pack", ref="pack.json", reviewed=True),
                    build_plan_variant_ref(kind="source", ref="https://example.invalid/spec"),
                ],
            )

            # "Copy only reviewed metadata and re-evaluate unsafe context" is a
            # partition, not a warning field: an unreviewed ref never appears in
            # the list a downstream reader treats as carried over.
            self.assertEqual([ref["kind"] for ref in variant["inherited_refs"]], ["plan_artifact", "context_pack"])
            self.assertEqual([ref["ref"] for ref in variant["refs_requiring_reevaluation"]], ["https://example.invalid/spec"])
            self.assertEqual(validate_plan_variant(variant), [])

    def test_validation_refuses_an_unreviewed_reference_moved_into_inherited(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp))
            variant["inherited_refs"] = [
                *variant["inherited_refs"],
                build_plan_variant_ref(kind="source", ref="https://example.invalid/spec"),
            ]
            variant["inherited_ref_count"] = 2

            self.assertIn(
                "inherited_refs[1]: only reviewed references may be inherited",
                validate_plan_variant(variant),
            )

    def test_a_fork_with_nothing_changed_is_not_a_variant(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)
            with self.assertRaises(ValueError) as raised:
                _variant(parent, deltas=[])
            self.assertIn("at least one delta", str(raised.exception))

            self.assertIn(
                "deltas[0]: parent_value and variant_value must differ",
                validate_plan_variant(
                    {
                        **_variant(parent),
                        "deltas": [build_plan_variant_delta(dimension="scope", label="x", parent_value="a", variant_value="a")],
                    }
                ),
            )

    def test_the_plain_text_rendering_shows_the_differences_and_the_open_question(self) -> None:
        with TemporaryDirectory() as tmp:
            text = render_plan_variant_text(
                _variant(
                    _accepted_plan(tmp),
                    deltas=[OWNER_DELTA, SCOPE_DELTA],
                    refs=[build_plan_variant_ref(kind="source", ref="https://example.invalid/spec")],
                )
            )

            self.assertIn("Changed inputs:", text)
            self.assertIn("coding_owner | selected executor: codex -> claude-code", text)
            self.assertIn("Inherited references:", text)
            self.assertIn("Re-evaluate before any handoff:", text)
            self.assertIn("Which plan should become the next handoff", text)
            self.assertIn("prepared_not_observed", text)


class NoReplayToolNetworkOrDispatchTests(unittest.TestCase):
    """AC3: creating a variant is a pure local metadata operation."""

    def test_the_module_imports_nothing_that_could_replay_spawn_or_connect(self) -> None:
        source = Path(__file__).resolve().parents[1] / "src" / "workflows" / "plan_variants.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add("." * node.level + (node.module or ""))

        # An exact set, not a denylist: the next import that could reach a
        # process, a socket, or the plan lifecycle has to change this line.
        self.assertEqual(
            imported,
            {"__future__", "hashlib", "typing", "..system.local_store", "..system.paths"},
        )

    def test_building_a_variant_runs_with_sockets_and_subprocesses_disabled(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)

            def refuse(*args: object, **kwargs: object) -> None:
                raise AssertionError("plan variant creation reached the network or a subprocess")

            with (
                mock.patch.object(socket, "socket", refuse),
                mock.patch.object(subprocess, "run", refuse),
                mock.patch.object(subprocess, "Popen", refuse),
            ):
                variant = _variant(parent, deltas=[OWNER_DELTA, SCOPE_DELTA])

            self.assertEqual(validate_plan_variant(variant), [])

    def test_building_a_variant_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)
            store = Path(tmp) / ".omh"
            before = sorted(str(path) for path in store.rglob("*"))

            _variant(parent, deltas=[OWNER_DELTA, SCOPE_DELTA])

            # Recording is a separate call. Building one is what Hermes does to
            # answer a what-if in chat, and it must leave the store alone.
            self.assertEqual(sorted(str(path) for path in store.rglob("*")), before)

    def test_the_record_names_every_class_it_is_not_evidence_for(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp))

            self.assertEqual(variant["not_evidence_until_observed"], list(PLAN_VARIANT_NOT_OBSERVED))
            for boundary in ("plan_replay", "tool_execution", "network_call", "coding_dispatch"):
                self.assertIn(boundary, PLAN_VARIANT_NOT_OBSERVED)


class AVariantIsNotThePlanTests(unittest.TestCase):
    """The guard: nothing may read a variant as the accepted plan."""

    def test_a_variant_carries_no_status_and_cannot_be_given_one(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp))

            self.assertNotIn("status", variant)
            self.assertEqual(tuple(sorted(variant)), tuple(sorted(PLAN_VARIANT_KEYS)))
            self.assertIn(
                "plan_variant has unexpected keys: status",
                validate_plan_variant({**variant, "status": "accepted"}),
            )

    def test_a_variant_never_wears_the_plan_schema_version(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp))

            self.assertEqual(variant["schema_version"], PLAN_VARIANT_SCHEMA_VERSION)
            self.assertNotEqual(variant["schema_version"], variant["parent_plan_schema_version"])
            self.assertIn(
                f"schema_version must be {PLAN_VARIANT_SCHEMA_VERSION}",
                validate_plan_variant({**variant, "schema_version": "hermes_plan/v1"}),
            )

    def test_the_claim_boundary_denies_the_plan_and_every_evidence_class(self) -> None:
        self.assertIn("not the accepted plan", PLAN_VARIANT_CLAIM_BOUNDARY)
        self.assertIn("not plan acceptance", PLAN_VARIANT_CLAIM_BOUNDARY)
        for word in ("replay", "dispatch", "execution", "verification", "review", "CI", "merge"):
            self.assertIn(word, PLAN_VARIANT_CLAIM_BOUNDARY)

    def test_the_next_handoff_question_stays_open_and_changes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)
            handoff = _variant(parent)["next_handoff"]

            self.assertEqual(handoff["decision"], "undecided")
            self.assertTrue(handoff["requires_user_choice"])
            self.assertEqual([item["kind"] for item in handoff["candidates"]], ["parent_plan", "variant"])
            self.assertEqual(handoff["candidates"][0]["digest"], parent["sha256"])
            self.assertEqual(handoff["boundary"], PLAN_VARIANT_HANDOFF_BOUNDARY)

    def test_only_an_accepted_hermes_plan_can_be_forked(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            draft = read_hermes_plan_artifact(
                write_hermes_plan(paths, build_hermes_plan_payload(TASK))["path"]
            )
            with self.assertRaises(ValueError) as raised:
                _variant(draft)
            self.assertIn("accepted parent plan", str(raised.exception))

            foreign = Path(tmp) / "not-a-plan.md"
            foreign.write_text("---\nschema_version: other/v1\nstatus: accepted\n---\n# Nope\n", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                _variant(read_hermes_plan_artifact(foreign))
            self.assertIn("hermes_plan/v1 parent artifact", str(raised.exception))

    def test_a_parent_without_a_digest_cannot_be_forked(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = {**_accepted_plan(tmp), "sha256": "not-a-digest"}
            with self.assertRaises(ValueError) as raised:
                _variant(parent)
            self.assertIn("parent plan sha256", str(raised.exception))

    def test_siblings_stay_non_interchangeable_across_parents_and_deltas(self) -> None:
        with TemporaryDirectory() as tmp:
            first = _accepted_plan(tmp)
            second = _accepted_plan(tmp, task="refactor the router with tests")

            same_delta_other_parent = _variant(second)
            other_delta_same_parent = _variant(first, deltas=[SCOPE_DELTA])
            baseline = _variant(first)

            self.assertNotEqual(baseline["variant_id"], same_delta_other_parent["variant_id"])
            self.assertNotEqual(baseline["variant_id"], other_delta_same_parent["variant_id"])

    def test_identity_is_reproducible_and_carries_no_clock(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = _accepted_plan(tmp)

            early = _variant(parent, created_at=T0)
            late = _variant(parent, created_at=T1)

            # A timestamp inside the digest would make two forks of the same
            # plan look like two different alternatives.
            self.assertEqual(early["variant_id"], late["variant_id"])
            self.assertEqual(early["variant_digest"], late["variant_digest"])
            self.assertNotEqual(early["created_at"], late["created_at"])


class VocabularyAndValidationTests(unittest.TestCase):
    def test_unknown_vocabulary_falls_back_instead_of_inventing_a_dimension(self) -> None:
        self.assertEqual(normalize_plan_variant_dimension("Coding Owner"), "coding_owner")
        self.assertEqual(normalize_plan_variant_dimension("acceptance-criteria"), "acceptance_criteria")
        self.assertEqual(normalize_plan_variant_dimension("vibes"), "other")
        self.assertEqual(normalize_plan_variant_ref_kind("Context Pack"), "context_pack")
        self.assertEqual(normalize_plan_variant_ref_kind("carrier pigeon"), "unknown")
        self.assertIn("other", PLAN_VARIANT_DELTA_DIMENSIONS)
        self.assertIn("unknown", PLAN_VARIANT_REF_KINDS)

    def test_a_missing_key_and_a_tampered_constant_are_both_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            variant = _variant(_accepted_plan(tmp))
            stripped = {key: value for key, value in variant.items() if key != "prepared_state"}

            self.assertIn("plan_variant is missing keys: prepared_state", validate_plan_variant(stripped))
            self.assertIn(
                "claim_boundary must deny that a variant is the accepted plan or evidence",
                validate_plan_variant({**variant, "claim_boundary": "anything goes"}),
            )
            self.assertIn(
                "next_handoff must offer the parent plan and the variant",
                validate_plan_variant({**variant, "next_handoff": {**variant["next_handoff"], "candidates": []}}),
            )

    def test_a_write_of_an_invalid_variant_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            variant = {**_variant(_accepted_plan(tmp)), "prepared_state": "observed"}

            with self.assertRaises(ValueError):
                write_plan_variant(paths, variant)
            self.assertFalse((Path(tmp) / ".omh" / "plan-variants").exists())


class PlanVariantCliTests(unittest.TestCase):
    def _accepted_plan_path(self, tmp: str) -> tuple[list[str], str]:
        base = ["--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes")]
        parent = _accepted_plan(tmp)
        return base, str(parent["path"])

    def test_the_cli_summarizes_by_default_and_emits_the_payload_on_request(self) -> None:
        with TemporaryDirectory() as tmp:
            base, plan_path = self._accepted_plan_path(tmp)
            arguments = base + [
                "hermes",
                "plan-variant",
                plan_path,
                "--name",
                "claude-code owner",
                "--delta",
                "coding_owner:selected executor:codex:claude-code",
                "--reevaluate",
                "source:https://example.invalid/spec",
            ]

            status, text, stderr = run_cli(arguments, output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            self.assertTrue(text.startswith("Plan variant: claude-code owner"))
            self.assertIn("coding_owner | selected executor: codex -> claude-code", text)
            self.assertIn("Re-evaluate before any handoff:", text)

            status, stdout, stderr = run_cli(arguments + ["--json"], output_json=False)
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "hermes_plan_variant_view/v1")
            self.assertEqual(validate_plan_variant(payload["variant"]), [])
            self.assertNotIn("artifact", payload)

    def test_the_cli_records_the_variant_and_leaves_the_plan_untouched(self) -> None:
        with TemporaryDirectory() as tmp:
            base, plan_path = self._accepted_plan_path(tmp)
            before = Path(plan_path).read_bytes()

            status, stdout, stderr = run_cli(
                base
                + [
                    "hermes",
                    "plan-variant",
                    plan_path,
                    "--name",
                    "defer docs",
                    "--delta",
                    "scope:docs:ship docs in the same PR:defer docs to a follow-up",
                    "--record",
                    "--json",
                ]
            )

            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            recorded = Path(payload["artifact"]["path"])
            self.assertEqual(recorded.parent.resolve(), (Path(tmp) / ".omh" / "plan-variants").resolve())
            self.assertTrue(recorded.exists())
            self.assertEqual(Path(plan_path).read_bytes(), before)

    def test_the_cli_refuses_a_draft_plan_and_a_malformed_delta(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes")]
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            draft = str(write_hermes_plan(paths, build_hermes_plan_payload(TASK))["path"])

            status, _, stderr = run_cli(
                base + ["hermes", "plan-variant", draft, "--name", "x", "--delta", "scope:docs:a:b"]
            )
            self.assertEqual(status, 2)
            self.assertIn("accepted parent plan", stderr)

            update_hermes_plan_status(paths, draft, status="accepted", allow_scaffold=True)
            status, _, stderr = run_cli(
                base + ["hermes", "plan-variant", draft, "--name", "x", "--delta", "scope:docs"]
            )
            self.assertEqual(status, 2)
            self.assertIn("--delta must contain exactly 4 colon-separated fields", stderr)


if __name__ == "__main__":
    unittest.main()
