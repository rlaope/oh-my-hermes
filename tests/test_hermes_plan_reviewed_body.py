from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli

REVIEWED = "## Options\n- A: Redis\n- B: sticky sessions (rejected)\n\n## Success criteria\n| Criterion | Task | Verification |\n| p95 under 200ms | T1 | make bench |\n"


class HermesPlanReviewedBodyTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> tuple[int, dict, str]:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), *args]
        )
        return status, (json.loads(stdout) if stdout.strip().startswith("{") else {}), stderr

    def test_plan_file_replaces_the_canned_sections_with_the_reviewed_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            status, payload, _ = self._run(
                root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions to Redis"
            )
            self.assertEqual(status, 0)
            text = Path(payload["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertIn("plan_body: reviewed", text)
            self.assertIn("## Reviewed Plan", text)
            self.assertIn("sticky sessions (rejected)", text)
            self.assertNotIn("Create a durable Hermes-facing planning artifact.", text)
            self.assertNotIn("say", payload)
            self.assertEqual(payload["artifact"]["plan_body"], "reviewed")

    def test_accepting_a_reviewed_plan_says_nothing_extra(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions")
            _, accepted, _ = self._run(root, "hermes", "plan-accept", payload["artifact"]["path"])
            self.assertEqual(accepted["artifact"]["status"], "accepted")
            self.assertNotIn("say", accepted)
            self.assertIn("p95 under 200ms", Path(payload["artifact"]["path"]).read_text(encoding="utf-8"))

    def test_recording_without_a_body_says_so_and_accept_refuses_the_scaffold(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Move sessions")
            self.assertIn("scaffold only", payload["say"])
            self.assertIn("--allow-scaffold", payload["say"])
            self.assertEqual(payload["artifact"]["plan_body"], "scaffold")
            path = Path(payload["artifact"]["path"])
            before = path.read_text(encoding="utf-8")
            for argv in (("hermes", "plan-accept", str(path)), ("hermes", "plan", "accept", str(path))):
                with self.subTest(argv=argv[:2]):
                    status, accepted, stderr = self._run(root, *argv)
                    self.assertNotEqual(status, 0)
                    self.assertEqual(accepted, {})
                    self.assertIn("only the generated scaffold", stderr)
                    self.assertIn("--plan-file", stderr)
                    self.assertIn("--allow-scaffold", stderr)
                    # Refused before anything is written: the file stays a draft.
                    self.assertEqual(path.read_text(encoding="utf-8"), before)
            from omh.paths import resolve_paths
            from omh.workflows.observation_journal import read_observation_events_result

            events, _ = read_observation_events_result(resolve_paths(root / "omh", root / "hermes"))
            self.assertNotIn("plan_accepted", [event.get("event") for event in events])

    def test_allow_scaffold_accepts_the_scaffold_on_purpose_and_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Move sessions")
            status, accepted, stderr = self._run(root, "hermes", "plan-accept", "--allow-scaffold", payload["artifact"]["path"])
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(accepted["artifact"]["status"], "accepted")
            self.assertFalse(accepted["reviewed_body"])
            self.assertIn("generated scaffold on purpose", accepted["say"])
            self.assertIn("scaffold", accepted["journal_event"]["summary"])

    def test_a_scaffold_record_is_not_ready_for_acceptance_in_the_machine_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = "implement durable observation journal with tests"
            _, scaffold, _ = self._run(root, "hermes", "plan", "--record", task)
            contract = scaffold["wrapper_contract"]
            self.assertEqual(scaffold["plan"]["status"], "draft")
            self.assertEqual(scaffold["plan"]["quality_gate"]["readiness"], "needs_reviewed_body")
            self.assertFalse(scaffold["plan"]["quality_gate"]["coding_handoff_ready"])
            self.assertEqual(contract["quality_gate"]["readiness"], "needs_reviewed_body")
            self.assertEqual(contract["next_action"], "record_reviewed_plan")
            requirement = {"plan_body": "reviewed", "record_with": "--plan-file", "accept_scaffold_with": "--allow-scaffold"}
            self.assertEqual(contract["decision_gate"]["acceptance_requires"], requirement)
            # `available` keeps meaning "after acceptance"; the requirement rides beside it.
            self.assertTrue(contract["coding_delegate"]["available"])
            self.assertEqual(contract["coding_delegate"]["acceptance_requires"], requirement)

            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, reviewed, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), task)
            self.assertEqual(reviewed["plan"]["quality_gate"]["readiness"], "ready_for_acceptance")
            self.assertEqual(reviewed["wrapper_contract"]["next_action"], "prepare_coding_delegation_after_plan_acceptance")
            self.assertNotIn("acceptance_requires", reviewed["wrapper_contract"]["decision_gate"])
            self.assertNotIn("acceptance_requires", reviewed["wrapper_contract"]["coding_delegate"])

            _, unrecorded, _ = self._run(root, "hermes", "plan", task)
            self.assertEqual(unrecorded["plan"]["quality_gate"]["readiness"], "ready_for_acceptance")

            _, blocked, _ = self._run(root, "hermes", "plan", "--record", "help")
            self.assertEqual(blocked["plan"]["quality_gate"]["readiness"], "needs_clarification")
            self.assertEqual(blocked["wrapper_contract"]["next_action"], "ask_clarification")

    def test_the_recorded_scaffold_file_says_what_stdout_says(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = "implement durable observation journal with tests"
            _, scaffold, _ = self._run(root, "hermes", "plan", "--record", task)
            self.assertEqual(scaffold["plan"]["deep_interview"]["after_answer_next_action"], "record_reviewed_plan")
            self.assertEqual(
                scaffold["wrapper_contract"]["deep_interview"]["after_answer_next_action"], "record_reviewed_plan"
            )
            text = Path(scaffold["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertIn("- Readiness: `needs_reviewed_body`", text)
            self.assertIn("- Coding handoff ready: `false`", text)
            self.assertIn("- Next action: `record_reviewed_plan`", text)
            self.assertNotIn("ready_for_acceptance", text)
            self.assertNotIn("accept_or_revise_plan", text)

            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, reviewed, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), task)
            self.assertEqual(reviewed["plan"]["deep_interview"]["after_answer_next_action"], "accept_or_revise_plan")
            reviewed_text = Path(reviewed["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertNotIn("needs_reviewed_body", reviewed_text)

    def test_a_bundle_file_carries_no_plan_readiness_to_disagree_with_stdout(self) -> None:
        # `mark_payload_as_planning_input` runs after the write; that is safe only
        # while the bundle file renders none of the fields it changes.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "bundle.md"
            body.write_text("### Hard Constraints\n- keep p95\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "--input-bundle", "Redis proposal")
            self.assertEqual(payload["plan"]["quality_gate"]["readiness"], "input_not_a_plan")
            text = Path(payload["artifact"]["path"]).read_text(encoding="utf-8")
            for line in ("Readiness:", "Coding handoff ready:", "Next action:"):
                self.assertNotIn(line, text)

    def test_re_accepting_an_accepted_scaffold_is_not_a_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Move sessions")
            path = payload["artifact"]["path"]
            self.assertEqual(self._run(root, "hermes", "plan-accept", "--allow-scaffold", path)[0], 0)
            status, again, stderr = self._run(root, "hermes", "plan-accept", path)
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(again["artifact"]["status"], "accepted")
            self.assertFalse(again["reviewed_body"])
            self.assertIn("accepted earlier", again["say"])

    def test_plan_accept_takes_the_ask_every_time_executor(self) -> None:
        # A setup profile's `choose` default already reaches the context pack,
        # so the flag accepts the same value instead of rejecting it.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions")
            status, accepted, stderr = self._run(
                root, "hermes", "plan-accept", payload["artifact"]["path"], "--write-context-pack", "--executor", "choose"
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(accepted["context_pack"]["context_pack"]["executor_target"], "choose")

    def test_allow_scaffold_changes_nothing_for_a_reviewed_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions")
            status, accepted, _ = self._run(root, "hermes", "plan-accept", "--allow-scaffold", payload["artifact"]["path"])
            self.assertEqual(status, 0)
            self.assertNotIn("say", accepted)
            self.assertNotIn("reviewed_body", accepted)

    def test_bundle_is_recorded_as_input_and_cannot_be_accepted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "bundle.md"
            body.write_text("### Hard Constraints\n- keep p95\n### Open Questions\n- cost?\n", encoding="utf-8")
            status, payload, _ = self._run(
                root, "hermes", "plan", "--record", "--plan-file", str(body), "--input-bundle", "Redis proposal"
            )
            self.assertEqual(status, 0)
            self.assertEqual(payload["artifact"]["schema_version"], "hermes_plan_input/v1")
            path = payload["artifact"]["path"]
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("INPUT TO PLANNING, NOT A PLAN", text)
            self.assertNotIn("Review-gated Hermes plan", text)
            status, _, stderr = run_cli(
                ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "hermes", "plan-accept", path]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("hermes_plan/v1", stderr)

    def test_flags_need_record_and_a_non_empty_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            empty = root / "empty.md"
            empty.write_text("  \n", encoding="utf-8")
            args = ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "hermes", "plan"]
            self.assertNotEqual(run_cli([*args, "--plan-file", str(body), "x y"])[0], 0)
            self.assertNotEqual(run_cli([*args, "--record", "--input-bundle", "x y"])[0], 0)
            status, _, stderr = run_cli([*args, "--record", "--plan-file", str(empty), "x y"])
            self.assertNotEqual(status, 0)
            self.assertIn("empty", stderr)


    def _delegate(self, root: Path, plan_path: str) -> dict:
        status, stdout, _ = run_cli(
            ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"),
             "coding", "delegate", "--executor", "codex", "--from-plan", plan_path]
        )
        self.assertEqual(status, 0)
        return json.loads(stdout)

    def test_paths_in_the_reviewed_body_do_not_deny_the_accepted_handoff(self) -> None:
        rows = [
            "src/session/store.py",
            "bench results go to /tmp/bench.txt",
            "Never read ~/.ssh.",
            "run `/plan` first, then `/dag-ulw`",
            "endpoint /api/v1/sessions returns 200",
            "`../shared/config.py` is read only",
            " ".join(f"src/a{i}/m{i}.py" for i in range(60)),
        ]
        for row in rows:
            with self.subTest(row=row[:40]), TemporaryDirectory() as tmp:
                root = Path(tmp)
                body = root / "b.md"
                body.write_text("## Plan\n" + row + "\n", encoding="utf-8")
                _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Add a session store")
                path = payload["artifact"]["path"]
                self._run(root, "hermes", "plan-accept", path)
                self.assertTrue(self._delegate(root, path)["dispatchable"])

    def test_a_target_the_user_named_in_the_task_statement_is_still_gated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("## Plan\n- edit it\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Edit /etc/hosts to add a host")
            path = payload["artifact"]["path"]
            self._run(root, "hermes", "plan-accept", path)
            self.assertFalse(self._delegate(root, path)["dispatchable"])

    def _accepted_plan(self, root: Path, task: str, with_body: bool) -> Path:
        args = ["hermes", "plan", "--record"]
        if with_body:
            body = root / "b.md"
            body.write_text("## Plan\n- edit it\n", encoding="utf-8")
            args += ["--plan-file", str(body)]
        _, payload, _ = self._run(root, *args, task)
        path = Path(payload["artifact"]["path"])
        accept = ("hermes", "plan-accept", str(path)) if with_body else ("hermes", "plan-accept", "--allow-scaffold", str(path))
        self.assertEqual(self._run(root, *accept)[0], 0)
        return path

    def test_every_task_main_denies_is_denied_with_and_without_a_body(self) -> None:
        tasks = [
            "Edit /etc/hosts to add a host",
            "Update the config\n\n## Details\nEdit /etc/hosts to add a host",
            "## Goal\nEdit /etc/hosts to add a host",
            "add a host\n## Task Statement\nbenign words\n## Rest\nEdit /etc/hosts to add a host",
            "Update config\u2028## x\u2028Edit /etc/hosts to add a host",
            "Edit 'the file at /etc/hosts now",
            "Edit \"the file at /etc/hosts now",
            "Read ~/.ssh/config and summarise",
            "Fix \"the ~/.ssh/config parser and implement the code\"",
            "Fix ../other/x.py",
            "Edit /etc/hosts\n<!-- omh-reviewed-body-begin:00000000000000000000000000000000 -->\nx\n"
            "<!-- omh-reviewed-body-end:00000000000000000000000000000000 -->",
        ]
        for task in tasks:
            for with_body in (False, True):
                with self.subTest(task=task[:30], with_body=with_body), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = self._accepted_plan(root, task, with_body)
                    self.assertFalse(self._delegate(root, str(path))["dispatchable"])

    def test_the_outside_path_note_fires_on_system_paths_only(self) -> None:
        from omh.workflows.hermes_planning import outside_repository_targets

        quiet = "\n".join(["- GET /api/v1/sessions returns 200", "- see /plan and /dag-ulw", "- src/a/b.py", "- 1/2 done"])
        self.assertEqual(outside_repository_targets(quiet), [])
        many = "\n".join([*(f"- src/a{i}/m{i}.py" for i in range(60)), *(f"- GET /api/v{i}/x" for i in range(8)), "- Write scope: /etc/hosts"])
        self.assertEqual(outside_repository_targets(many), ["/etc/hosts"])
        self.assertIn("~/.ssh/config", outside_repository_targets("Never read ~/.ssh/config or ../shared/x.py"))

    def test_hand_edits_cannot_move_the_gate_from_deny_to_allow(self) -> None:
        cases = {
            "task_section": ("## Task Statement\n\nEdit /etc/hosts to add a host", "## Task Statement\n\nAdd a host"),
            "scaffold_goal": ("- Create a durable Hermes-facing planning artifact.", "- Edit /etc/hosts"),
        }
        for name, (old, new) in cases.items():
            for with_body in (False, True):
                if name == "scaffold_goal" and with_body:
                    continue
                with self.subTest(case=name, with_body=with_body), TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = self._accepted_plan(root, "Edit /etc/hosts to add a host", with_body)
                    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
                    self.assertFalse(self._delegate(root, str(path))["dispatchable"])

    def test_a_body_edited_after_recording_is_scanned_whole(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._accepted_plan(root, "Add a session store", True)
            self.assertTrue(self._delegate(root, str(path))["dispatchable"])
            path.write_text(path.read_text(encoding="utf-8").replace("- edit it", "- edit /etc/hosts"), encoding="utf-8")
            self.assertFalse(self._delegate(root, str(path))["dispatchable"])

    def test_a_reviewed_body_naming_an_outside_path_says_so_without_gating(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("## Plan\n- Write scope: /etc/hosts\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Add a session store")
            self.assertIn("/etc/hosts", payload["say"])
            _, accepted, _ = self._run(root, "hermes", "plan-accept", payload["artifact"]["path"])
            self.assertIn("/etc/hosts", accepted["say"])
            self.assertTrue(self._delegate(root, payload["artifact"]["path"])["dispatchable"])

    def test_an_accepted_scaffold_says_so_downstream(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Add a session store")
            path = payload["artifact"]["path"]
            self.assertEqual(self._run(root, "hermes", "plan-accept", "--allow-scaffold", path)[0], 0)
            delegated = self._delegate(root, path)
            self.assertEqual(delegated["plan_artifact"]["plan_body"], "scaffold")
            self.assertIn("plan_body=scaffold", json.dumps(delegated))

    def test_bundle_stdout_is_not_ready_for_acceptance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("### Open Questions\n- cost?\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "--input-bundle", "Redis proposal")
            text = json.dumps(payload)
            self.assertNotIn("ready_for_acceptance", text)
            self.assertNotIn("requires_plan_acceptance", text)
            self.assertEqual(payload["wrapper_contract"]["next_action"], "hand_bundle_to_planner")
            self.assertIn("planning input", payload["say"])

    def test_a_bundle_does_not_supersede_the_accepted_plan_with_the_same_task(self) -> None:
        from omh.paths import resolve_paths
        from omh.runtime.generated_artifacts import _scan_plans

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("## Plan\n- a\n", encoding="utf-8")
            _, plan, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Redis proposal")
            self._run(root, "hermes", "plan-accept", plan["artifact"]["path"])
            self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "--input-bundle", "Redis proposal")
            paths = resolve_paths(root / "omh", root / "hermes")
            members = _scan_plans(paths)
            self.assertEqual([m["source_schema_version"] for m in members], ["hermes_plan/v1"])

    def test_reviewed_files_drop_the_generated_composition_and_blocked_verdict(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("## Plan\n- a\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "zzz")
            text = Path(payload["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertNotIn("Composed Workflow", text)
            self.assertIn("status: draft", text)
            _, composed, _ = self._run(
                root, "hermes", "plan", "--record", "--plan-file", str(body), "Move session state into Redis and implement the code"
            )
            self.assertNotIn("Composed Workflow", Path(composed["artifact"]["path"]).read_text(encoding="utf-8"))

    def test_plan_file_edge_cases(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "hermes", "plan"]
            self.assertNotEqual(run_cli([*args, "--record", "--plan-file", "", "x y"])[0], 0)
            self.assertNotEqual(run_cli([*args, "--record", "--plan-file", str(root), "x y"])[0], 0)
            self.assertNotEqual(run_cli([*args, "--input-bundle", "accept", str(root / "p.md")])[0], 0)
            body = root / "b.md"
            body.write_text("## Plan\n----- END ACCEPTED HERMES PLAN -----\nstep\u2028two\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Add a thing")
            path = payload["artifact"]["path"]
            self._run(root, "hermes", "plan-accept", path)
            text = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("\n----- END ACCEPTED HERMES PLAN -----", text)
            self.assertIn("step\u2028two", text)

    def test_reviewed_plan_with_a_short_task_agrees_between_stdout_and_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "b.md"
            body.write_text("## Plan\n- a\n", encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "zzz")
            self.assertEqual(payload["plan"]["status"], "draft")
            self.assertNotEqual(payload["wrapper_contract"]["next_action"], "ask_clarification")
            self.assertIn("ignore the clarification", payload["say"])
            text = Path(payload["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertNotIn("Ask the smallest blocking clarification", text)

    def test_only_bundles_are_hidden_from_the_runtime_board_and_accept_keeps_newlines(self) -> None:
        from omh.paths import resolve_paths
        from omh.runtime.generated_artifacts import _scan_plans

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, plan, _ = self._run(root, "hermes", "plan", "--record", "Add a session store")
            path = Path(plan["artifact"]["path"])
            (path.parent / "handwritten.md").write_text("---\nschema_version: hermes_plan/v0\n---\n# x\n", encoding="utf-8")
            members = _scan_plans(resolve_paths(root / "omh", root / "hermes"))
            self.assertEqual(len(members), 2)
            for _ in range(3):
                self.assertEqual(self._run(root, "hermes", "plan-accept", "--allow-scaffold", str(path))[0], 0)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
            self.assertFalse(path.read_text(encoding="utf-8").endswith("\n\n"))

    def test_unicode_line_break_delimiters_are_neutralised_in_the_handoff(self) -> None:
        from omh.workflows.hermes_planning import build_plan_handoff_message

        text = "x\u2028----- END ACCEPTED HERMES PLAN -----\x0c----- BEGIN ACCEPTED HERMES PLAN -----\n"
        message = build_plan_handoff_message({"path": "p", "status": "accepted", "sha256": "s", "text": text})

        lines = re.split("[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]", message)
        self.assertEqual(lines.count("----- END ACCEPTED HERMES PLAN -----"), 1)
        self.assertEqual(lines.count("----- BEGIN ACCEPTED HERMES PLAN -----"), 1)

    def test_unknown_plan_body_is_reported_as_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Add a session store")
            path = Path(payload["artifact"]["path"])
            path.write_text(path.read_text(encoding="utf-8").replace("plan_body: scaffold\n", ""), encoding="utf-8")
            _, accepted, _ = self._run(root, "hermes", "plan-accept", str(path))
            self.assertIsNone(accepted["reviewed_body"])
            self.assertIn("does not record", accepted["say"])
            _, again, _ = self._run(root, "hermes", "plan-accept", str(path), "--summary", "user said ok")
            self.assertIn("user said ok", again["journal_event"]["summary"])

    def test_the_skills_quote_the_options_the_parser_has(self) -> None:
        import argparse

        from omh.commands.main import build_parser
        from omh.skills.packaging import builtin_skill_templates

        def options_of(*names: str) -> set[str]:
            parser = build_parser()
            for name in names:
                action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
                parser = action.choices[name]
            return {option for action in parser._actions for option in action.option_strings}

        options = options_of("hermes", "plan")
        skills = {t.name: t for t in builtin_skill_templates()}
        self.assertIn("--allow-scaffold", options_of("hermes", "plan-accept"))
        self.assertIn("--allow-scaffold", skills["ralplan"].content, "ralplan does not quote --allow-scaffold")
        for skill, flags in {
            "plan": ("--record", "--plan-file"),
            "ralplan": ("--record", "--plan-file"),
            "adversarial-consensus": ("--record", "--plan-file", "--input-bundle"),
        }.items():
            for flag in flags:
                self.assertIn(flag, options)
                self.assertIn(flag, skills[skill].content, f"{skill} does not quote {flag}")


if __name__ == "__main__":
    unittest.main()
