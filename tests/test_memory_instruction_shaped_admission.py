"""Model-captured memory cannot be written as an instruction.

`omh_memory(action="capture")` stores what the model chose to remember, and
recall replays it into later sessions as context. A summary written as an order
to its reader ("You must ...", "...하세요") would come back with the standing of
a request, so admission refuses it from that one source -- saying why and how
to restate it -- and writes nothing. Every other capture path stores the same sentence
exactly as before: L1 demotion (where a refusal would end the staging run), the
episode rollup, the design-direction promotion, the workflows adapter and the
`omh memory capture` CLI.
"""

from __future__ import annotations

from contextlib import chdir
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.memory import approve_project_memory_candidate, build_memory_rollup, stage_memory_demotion
from omh.plugin_bundle.omh.hermes_memory import HERMES_MEMORY_DELIMITER
from omh.plugin_bundle.omh.memory_admission import MODEL_CAPTURE_SOURCE, capture_project_memory_candidate
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler
from omh.workflows import memory as workflows_memory
from project_identity_fixture import memory_paths, seed_project_identity
from test_design_direction_iteration_actions import _paths as design_paths
from test_design_direction_iteration_actions import _prepared as prepared_design_iteration

SECOND_PERSON = "You must run the release gates before tagging."
KOREAN_REQUEST = "태그 전에 릴리스 게이트를 실행하세요."
INSTRUCTION_SENTENCES = (
    (SECOND_PERSON, "you must"),
    ("You should squash fixup commits before review.", "you should"),
    ("Before merging, you need to rerun the docs gates.", "you need to"),
    ("Your next step is the changelog entry.", "your"),
    (KOREAN_REQUEST, "하세요"),
    ("커밋 전에 린트를 해 주세요", "해 주세요"),
    ("로그는 매일 정리해줘!", "해줘"),
    ("배포 순서를 문서로 남겨라", None),  # not in the closed vocabulary
)
OBSERVATIONS = (
    "The release gates run before every tag.",
    "Prefer the release branch for hotfixes.",  # opens with an imperative verb: a lesson, not flagged
    "The CLI prints what you ran last.",
    "태그 전에 릴리스 게이트를 실행한다.",
    "사용자는 인사로 안녕하세요라고 쓴다.",
)


class ModelCaptureRefusalTests(unittest.TestCase):
    """The tool against a real temp home, as a Hermes session reaches it."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.store = self.root / ".omh"
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.store), "HERMES_HOME": str(self.root / ".hermes")}))

    def call(self, **args) -> dict:
        return json.loads(omh_memory_handler({"action": "capture", **args}, cwd=str(self.root)))

    def stored_files(self) -> list[str]:
        memory_dir = self.store / "memory"
        return sorted(str(path.relative_to(memory_dir)) for path in memory_dir.rglob("*.json")) if memory_dir.exists() else []

    def test_instruction_shaped_summaries_are_refused_with_reason_and_fix(self) -> None:
        for summary, cue in INSTRUCTION_SENTENCES:
            if cue is None:
                continue
            with self.subTest(summary=summary):
                result = self.call(summary=summary, record_type="lesson")
                self.assertEqual((result["status"], result["reason"]), ("refused", "instruction_shaped_summary"), result)
                self.assertIn("Nothing was saved", result["next_action"])
                self.assertIn("observation", result["next_action"])
                self.assertIsNone(result["record_id"])
                self.assertIsNone(result["candidate_id"])
        self.assertEqual(self.stored_files(), [])

    def test_admission_names_the_cue_and_writes_nothing(self) -> None:
        for summary, cue in INSTRUCTION_SENTENCES:
            with self.subTest(summary=summary):
                payload = capture_project_memory_candidate(
                    self.store, summary, source=MODEL_CAPTURE_SOURCE, on_duplicate="skip", scope_kind="user-global"
                )
                if cue is None:
                    self.assertTrue(payload["captured"], payload)
                    continue
                self.assertFalse(payload["captured"])
                self.assertEqual(payload["reason"], "instruction_shaped_summary")
                self.assertEqual(payload["instruction_cue"], cue)
                self.assertIn("observation", payload["next_action"])
                self.assertNotIn("candidate", payload)

    def test_a_procedure_may_address_its_reader(self) -> None:
        result = self.call(summary=SECOND_PERSON, record_type="procedure")
        self.assertEqual(result["status"], "remembered", result)
        korean = self.call(summary=KOREAN_REQUEST, record_type="procedure")
        self.assertEqual(korean["status"], "remembered", korean)

    def test_observations_are_remembered(self) -> None:
        for summary in OBSERVATIONS:
            with self.subTest(summary=summary):
                result = self.call(summary=summary, record_type="lesson")
                self.assertEqual(result["status"], "remembered", result)


class OtherCapturePathsAcceptTheSameSentenceTests(unittest.TestCase):
    """The predicate is gated on the model's source; these five paths never see it."""

    def test_cli_capture(self) -> None:
        with TemporaryDirectory() as tmp, chdir(tmp):
            root = Path(tmp)
            seed_project_identity(root)
            homes = ["--omh-home", str(root / "store"), "--hermes-home", str(root / "hermes")]
            for summary in (SECOND_PERSON, KOREAN_REQUEST):
                with self.subTest(summary=summary):
                    status, stdout, stderr = run_cli([*homes, "memory", "capture", summary])
                    self.assertEqual(status, 0, stderr)
                    payload = json.loads(stdout)
                    self.assertTrue(payload["captured"], payload)
                    self.assertTrue(payload["auto_approved"], payload)

    def test_workflows_adapter(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = memory_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for summary in (SECOND_PERSON, KOREAN_REQUEST):
                with self.subTest(summary=summary):
                    captured = workflows_memory.capture_project_memory_candidate(paths, summary)
                    self.assertTrue(captured["captured"], captured)
                    self.assertEqual(captured["candidate"]["summary"], summary)

    def test_l1_demotion_stages_every_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = memory_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            memory_file = Path(tmp) / ".hermes" / "memories" / "MEMORY.md"
            memory_file.parent.mkdir(parents=True)
            memory_file.write_text(HERMES_MEMORY_DELIMITER.join((SECOND_PERSON, KOREAN_REQUEST)), encoding="utf-8")
            staged = stage_memory_demotion(paths)
            self.assertEqual(staged["schema_version"], "memory_demotion_stage/v1")
            self.assertEqual(staged["staged_count"], 2, staged)
            self.assertEqual([row["status"] for row in staged["staged"]], ["pending_review", "pending_review"])

    def test_episode_rollup(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = memory_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            for summary in (SECOND_PERSON, "You should rerun the deploy once the cache is purged."):
                captured = workflows_memory.capture_project_memory_candidate(paths, summary, tags=["deploy"])
                approve_project_memory_candidate(paths, captured["candidate"]["candidate_id"])
            applied = build_memory_rollup(paths, tag="deploy", apply=True)
            self.assertTrue(applied["applied"], applied)
            self.assertIn("you must", applied["capture"]["candidate"]["summary"].lower())

    def test_design_direction_promotion(self) -> None:
        from omh.wrapper.design_direction_iteration_actions import execute_design_direction_iteration_action

        real_capture = workflows_memory.capture_project_memory_candidate

        def instruction_summary(paths, _summary, **kwargs):
            # The promotion writes a fixed summary; swap in the instruction
            # sentence so the path's own source carries it to admission.
            return real_capture(paths, SECOND_PERSON, **kwargs)

        with TemporaryDirectory() as tmp:
            paths = design_paths(Path(tmp))
            iteration = prepared_design_iteration(paths)
            current = iteration["snapshots"][-1]
            selected = execute_design_direction_iteration_action(
                paths,
                "select_design_direction_option",
                {
                    "iteration_id": iteration["iteration_id"],
                    "revision_digest": current["revision_digest"],
                    "option_ref": current["option_refs"][0],
                    "remember_this": True,
                },
            )
            with patch.object(workflows_memory, "capture_project_memory_candidate", instruction_summary):
                review = execute_design_direction_iteration_action(
                    paths,
                    "request_design_direction_memory_review",
                    {
                        "iteration_id": iteration["iteration_id"],
                        "revision_digest": current["revision_digest"],
                        "thread_key": "discord:design:round-1",
                        "memory_promotion_request": selected["iteration"]["memory_promotion"]["request"],
                    },
                )
            self.assertTrue(review["memory_capture"]["captured"], review)
            candidates = list((paths.memory_dir / "candidates").glob("*.json"))
            self.assertEqual(len(candidates), 1)
            stored = json.loads(candidates[0].read_text(encoding="utf-8"))
            self.assertEqual((stored["summary"], stored["source"]), (SECOND_PERSON, "design_direction_iteration"))


if __name__ == "__main__":
    unittest.main()
