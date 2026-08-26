from __future__ import annotations

import json
import unittest

from omh.version import __version__ as omh_version
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _platform_support import requires_posix_permissions


class HudCliTests(unittest.TestCase):
    def test_hud_projects_active_subagents_without_duplicate_host_fields(self) -> None:
        status = {
            "runtime_state_present": True,
            "runs": [
                {
                    "run_id": "run-hud",
                    "workflow": "ULW model routing review",
                    "phase": "executing",
                    "observation_status": "execution_observed",
                    "execution_observed": True,
                }
            ],
            "active_executors": [
                {
                    "binding_id": "binding-running-1",
                    "target_type": "subagent",
                    "target_id": "explore",
                    "executor_profile": "hermes",
                    "routed_model": "gpt-5.6-sol",
                    "routed_reasoning_effort": "xhigh",
                    "tokens_total": 18_200,
                    "elapsed_seconds": 23,
                    "category": "deep",
                    "fallback_count": 2,
                    "turn_count": 3,
                    "tool_count": 14,
                    "cost_usd": 0.1346,
                    "tokens_per_second": 45,
                    "latest_event": {
                        "event_type": "repo_exploration",
                        "summary": "Inspecting the routing implementation.",
                        "observed_at": "2026-08-13T11:00:00Z",
                    },
                },
                {
                    "binding_id": "binding-running-2",
                    "target_type": "subagent",
                    "target_id": "librarian",
                    "executor_profile": "hermes",
                    "routed_model": "kimi-k3",
                    "tokens_total": 4_300,
                    "latest_event": {
                        "event_type": "tests_started",
                        "summary": "Running focused routing tests.",
                        "observed_at": "2026-08-13T11:01:00Z",
                    },
                },
                {
                    "binding_id": "binding-blocked",
                    "target_type": "subagent",
                    "target_id": "architect",
                    "executor_profile": "hermes",
                    "routed_model": "claude-opus-5",
                    "latest_event": {
                        "event_type": "executor_blocked",
                        "summary": "Waiting for the Windows CI result.",
                        "observed_at": "2026-08-13T11:02:00Z",
                    },
                },
            ],
            "stale_executors": [],
            "latest_progress_events": [
                {
                    "binding_id": "binding-completed",
                    "event_type": "executor_completed",
                    "summary": "Verified the Windows CI integrity fix.",
                    "observed_at": "2026-08-13T11:03:00Z",
                }
            ],
        }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = json.loads(
                run_cli(
                    [
                        "--omh-home",
                        str(root / ".omh"),
                        "--hermes-home",
                        str(root / ".hermes"),
                        "hud",
                        "--json",
                    ],
                    output_json=False,
                )[1]
            )
            # The CLI call proves the public surface still works, while the
            # injected status below isolates the deterministic projection seam.
            from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

            payload = read_omh_hud(
                root / ".omh",
                root / ".hermes",
                status=status,
            )

        self.assertEqual(payload["subagents"]["status"], "observed")
        self.assertTrue(payload["active"])
        self.assertEqual(payload["subagents"]["active"], 3)
        self.assertEqual(payload["subagents"]["running"], 2)
        self.assertEqual(payload["subagents"]["blocked"], 1)
        self.assertEqual(payload["subagents"]["completed"], 1)
        self.assertEqual(payload["subagents"]["stale"], 0)
        self.assertEqual(
            payload["subagents"]["latest_action"],
            "Verified the Windows CI integrity fix.",
        )
        self.assertEqual(
            payload["subagents"]["rows"],
            [
                {
                    "state": "running",
                    "task_id": "explore",
                    "role": "explore",
                    "action": "Inspecting the routing implementation.",
                    "model": "gpt-5.6-sol",
                    "effort": "xhigh",
                    "tokens": 18_200,
                    "elapsed_seconds": 23,
                    "observed_at": "2026-08-13T11:00:00Z",
                    "category": "deep",
                    "fallback_count": 2,
                    "turn_count": 3,
                    "tool_count": 14,
                    "cost_usd": 0.1346,
                    "tokens_per_second": 45,
                },
                {
                    "state": "running",
                    "task_id": "libraria",
                    "role": "librarian",
                    "action": "Running focused routing tests.",
                    "model": "kimi-k3",
                    "effort": "",
                    "tokens": 4_300,
                    "elapsed_seconds": None,
                    "observed_at": "2026-08-13T11:01:00Z",
                    "category": "",
                    "fallback_count": None,
                    "turn_count": None,
                    "tool_count": None,
                    "cost_usd": None,
                    "tokens_per_second": None,
                },
                {
                    "state": "blocked",
                    "task_id": "architec",
                    "role": "architect",
                    "action": "Waiting for the Windows CI result.",
                    "model": "claude-opus-5",
                    "effort": "",
                    "tokens": None,
                    "elapsed_seconds": None,
                    "observed_at": "2026-08-13T11:02:00Z",
                    "category": "",
                    "fallback_count": None,
                    "turn_count": None,
                    "tool_count": None,
                    "cost_usd": None,
                    "tokens_per_second": None,
                },
            ],
        )
        self.assertEqual(payload["maestro"], {"status": "idle", "rows": []})
        widget_text = "\n".join(payload["display"]["widget_lines"])
        self.assertIn("[OMH]", widget_text)
        self.assertIn("ULW model routing review", widget_text)
        self.assertIn("active", widget_text)
        self.assertIn("agents 3", widget_text)
        self.assertIn("run 2", widget_text)
        self.assertIn("block 1", widget_text)
        self.assertIn("done 1", widget_text)
        for duplicate in ("cwd", "branch", "context", "cost", "provider", "model:"):
            self.assertNotIn(duplicate, widget_text.casefold())

    def test_hud_replaces_internal_runtime_labels_with_friendly_status(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import _hud_widget_lines

        lines = _hud_widget_lines(
            {
                "runtime": {"workflow": "fanout-unit", "phase": "runtime"},
                "subagents": {"active": 0, "running": 0, "blocked": 0, "completed": 0},
            }
        )

        self.assertIn("[OMH] Parallel work ready", lines[0])
        self.assertIn("ready  •  agents 0  •  run 0  •  block 0  •  done 0", lines[0])
        self.assertNotIn("fanout-unit", lines[0])
        self.assertNotIn(" runtime ", lines[0])

    def test_hud_fails_closed_for_unsafe_runtime_state(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "INJECTED_RUNTIME_SENTINEL"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            runtime_dir = omh_home / "runtime"
            runtime_dir.mkdir(parents=True)
            external = root / "outside.json"
            cases = {
                "absent": None,
                "malformed": '{"version": "INJECTED_RUNTIME_SENTINEL"',
                "oversized": json.dumps(
                    {
                        "version": sentinel,
                        "padding": "x" * 300_000,
                    }
                ),
                "symlinked": external,
            }
            external.write_text(json.dumps({"version": sentinel}), encoding="utf-8")

            for name, fixture in cases.items():
                with self.subTest(name=name):
                    state_path = runtime_dir / "state.json"
                    state_path.unlink(missing_ok=True)
                    if isinstance(fixture, Path):
                        state_path.symlink_to(fixture)
                    elif isinstance(fixture, str):
                        state_path.write_text(fixture, encoding="utf-8")

                    payload = read_omh_hud(
                        omh_home,
                        root / ".hermes",
                        package_version="1.0.5",
                    )
                    rendered = json.dumps(payload)

                    self.assertEqual(payload["runtime"]["workflow"], "idle")
                    self.assertFalse(payload["active"])
                    self.assertEqual(payload["subagents"]["status"], "idle")
                    self.assertNotIn(sentinel, rendered)
                    self.assertLessEqual(len(rendered), 16_384)

    def test_hud_reads_the_checked_descriptor_when_the_path_is_replaced(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import _read_hud_json

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            external = root / "external.json"
            state_path.write_text('{"version": "safe"}', encoding="utf-8")
            external.write_text('{"version": "secret"}', encoding="utf-8")
            from omh.plugin_bundle.omh import runtime_reader

            original_open = runtime_reader.os.open
            swapped = False
            replacement_blocked = False

            def open_then_replace(path: str | bytes | Path, *args: object, **kwargs: object) -> int:
                nonlocal replacement_blocked, swapped
                descriptor = original_open(path, *args, **kwargs)
                if Path(path) == state_path:
                    try:
                        state_path.unlink()
                        state_path.symlink_to(external)
                        swapped = True
                    except OSError:
                        replacement_blocked = True
                return descriptor

            with patch.object(runtime_reader.os, "open", open_then_replace):
                payload = _read_hud_json(state_path)

            self.assertTrue(swapped or replacement_blocked)
            self.assertEqual(payload, {"version": "safe"})

    def test_run_target_binding_projects_the_profile_as_role_not_the_run_id(self) -> None:
        # A run's target_id is its timestamped artifact id; showing it as the
        # "role" put a 40-char identifier where a human-readable owner belongs.
        from omh.plugin_bundle.omh.runtime_reader import _hud_executor_role

        run_row = {
            "target_type": "run",
            "target_id": "20260815T172724312406Z-ultrawork-goal-execution-1c8041",
            "executor_profile": "claude_code",
        }
        self.assertEqual(_hud_executor_role(run_row), "claude_code")
        wrapper_row = {
            "target_type": "wrapper_session",
            "target_id": "ws-3fa2b1c9d0e4f56a78b9c0d1",
            "executor_profile": "claude_code",
        }
        self.assertEqual(_hud_executor_role(wrapper_row), "claude_code")
        subagent_row = {
            "target_type": "subagent",
            "target_id": "explore",
            "executor_profile": "hermes",
        }
        self.assertEqual(_hud_executor_role(subagent_row), "explore")

    def test_role_catalog_detection_falls_back_when_directory_open_is_unsupported(self) -> None:
        from omh.plugin_bundle.omh import runtime_reader

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            references = root / "plugins" / "omh" / "references"
            references.mkdir(parents=True)
            (references / "role-planner.md").write_text("# Planner\n", encoding="utf-8")
            original_open = runtime_reader.os.open

            def reject_directory_open(path: str | bytes | Path, *args: object, **kwargs: object) -> int:
                if Path(path) == references:
                    raise PermissionError("directory descriptors unsupported")
                return original_open(path, *args, **kwargs)

            with patch.object(runtime_reader.os, "supports_dir_fd", set()), patch.object(
                runtime_reader.os,
                "open",
                reject_directory_open,
            ):
                self.assertTrue(runtime_reader._hud_has_role_catalog(references, root=root))

    def test_terminal_result_lookup_rejects_traversal_target_ids(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import (
            _target_has_terminal_result,
            _valid_progress_binding,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime"
            (runtime_dir / "runs").mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            (outside / "delegation.json").write_text(
                json.dumps({"observed": True, "result": "completed"}),
                encoding="utf-8",
            )

            self.assertFalse(
                _target_has_terminal_result(
                    runtime_dir,
                    "run",
                    "../../outside",
                )
            )
            self.assertFalse(
                _valid_progress_binding(
                    {
                        "schema_version": "omh_executor_progress_binding/v1",
                        "target_type": "run",
                        "target_id": "../../outside",
                    },
                    "run",
                )
            )

    def test_hud_rejects_symlinked_run_directories(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "EXTERNAL_SECRET_SENTINEL"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = root / ".omh" / "runtime" / "runs"
            runs.mkdir(parents=True)
            external = root / "external-run"
            external.mkdir()
            (external / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "external",
                        "skill": sentinel,
                        "phase": "executing",
                    }
                ),
                encoding="utf-8",
            )
            (runs / "999").symlink_to(external, target_is_directory=True)

            payload = read_omh_hud(root / ".omh", root / ".hermes")
            rendered = json.dumps(payload)

            self.assertEqual(payload["runtime"]["workflow"], "idle")
            self.assertNotIn(sentinel, rendered)

    def test_hud_rejects_symlinked_runtime_and_plugin_ancestors(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "EXTERNAL_HUD_SECRET"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            external_runtime = root / "external-runtime"
            external_plugin = root / "external-plugin"
            external_achievements = root / "external-achievements"
            external_runtime.mkdir()
            external_plugin.mkdir()
            external_achievements.mkdir()
            (external_runtime / "state.json").write_text(
                json.dumps({"version": sentinel}),
                encoding="utf-8",
            )
            (external_plugin / "plugin.yaml").write_text(
                f"version: {sentinel}\n",
                encoding="utf-8",
            )
            (external_achievements / "state.json").write_text(
                json.dumps({"unlocked": [sentinel]}),
                encoding="utf-8",
            )
            omh_home.mkdir()
            (omh_home / "runtime").symlink_to(external_runtime, target_is_directory=True)
            (hermes_home / "plugins").mkdir(parents=True)
            (hermes_home / "plugins" / "omh").symlink_to(external_plugin, target_is_directory=True)
            (hermes_home / "plugins" / "hermes-achievements").symlink_to(
                external_achievements,
                target_is_directory=True,
            )

            payload = read_omh_hud(omh_home, hermes_home, package_version="1.0.5")

            self.assertNotIn(sentinel, json.dumps(payload))
            self.assertFalse(payload["active"])

    def test_plugin_capabilities_reject_symlinked_files_and_role_catalog(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import (
            TOOL_FILE_STEMS,
            _plugin_capabilities,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            plugin_dir = hermes_home / "plugins" / "omh"
            tools_dir = plugin_dir / "tools"
            references_dir = plugin_dir / "references"
            external = root / "external.py"
            tools_dir.mkdir(parents=True)
            references_dir.mkdir()
            external.write_text("# external\n", encoding="utf-8")
            (plugin_dir / "plugin.yaml").write_text("name: omh\n", encoding="utf-8")
            (plugin_dir / "__init__.py").symlink_to(external)
            (references_dir / "role-coding.md").symlink_to(external)
            for stem in set(TOOL_FILE_STEMS.values()):
                (tools_dir / f"{stem}.py").symlink_to(external)

            capabilities = _plugin_capabilities(plugin_dir, {}, root=hermes_home)

            self.assertFalse(capabilities["files"]["init_py"])
            self.assertFalse(capabilities["files"]["role_catalog"])
            for stem in set(TOOL_FILE_STEMS.values()):
                self.assertFalse(capabilities["files"][stem])

    def test_hud_rejects_symlinked_run_auxiliary_metadata(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "AUXILIARY_METADATA_SECRET"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".omh" / "runtime" / "runs" / "999"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "999", "skill": "safe workflow", "phase": "executing"}),
                encoding="utf-8",
            )
            external = root / "coding.json"
            external.write_text(
                json.dumps({"recommended_workflow": sentinel}),
                encoding="utf-8",
            )
            (run_dir / "coding_delegation.json").symlink_to(external)

            payload = read_omh_hud(root / ".omh", root / ".hermes")
            rendered = json.dumps(payload)

            self.assertEqual(payload["runtime"]["workflow"], "safe workflow")
            self.assertNotIn(sentinel, rendered)

    def test_hud_rejects_symlinked_executor_progress_directory(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "INTERMEDIATE_SYMLINK_SECRET"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".omh" / "runtime" / "runs" / "999"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "999", "skill": "safe", "phase": "executing"}),
                encoding="utf-8",
            )
            external = root / "external-progress"
            external.mkdir()
            binding = {
                "schema_version": "omh_executor_progress_binding/v1",
                "binding_id": "run:999:codex",
                "instance_id": "run:999:codex:instance",
                "target": {"type": "run", "id": "999"},
                "target_type": "run",
                "target_id": "999",
                "executor": "codex",
                "executor_profile": "codex",
                "correlation_root": "run:999",
                "state": "active",
                "created_at": "2099-01-01T00:00:00Z",
                "updated_at": "2099-01-01T00:00:00Z",
                "last_observed_at": "2099-01-01T00:00:00Z",
                "freshness_seconds": 900,
                "expiry_seconds": 86400,
                "report_count": 0,
                "last_reported_event_type": "",
                "evidence_refs": [],
                "privacy": "metadata_only",
                "claim_boundary": (
                    "Executor progress is metadata-only observed activity. It is not result, verification, "
                    "review, CI, merge-readiness, or merge evidence."
                ),
            }
            (external / "binding.json").write_text(json.dumps(binding), encoding="utf-8")
            (external / "events.jsonl").write_text(
                json.dumps(
                    {
                        **binding,
                        "schema_version": "omh_executor_progress_event/v1",
                        "event_type": "progress_observed",
                        "status": "running",
                        "summary": sentinel,
                        "observed_at": "2099-01-01T00:00:00Z",
                        "severity": "info",
                        "signal": {},
                        "transition_fingerprint": "a" * 64,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "executor_progress").symlink_to(external, target_is_directory=True)

            payload = read_omh_hud(root / ".omh", root / ".hermes")
            rendered = json.dumps(payload)

            self.assertEqual(payload["subagents"]["active"], 0)
            self.assertNotIn(sentinel, rendered)

    def test_hud_separates_maestro_owned_run_from_subagents(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        status = {
            "runtime_state_present": True,
            "runs": [
                {
                    "run_id": "run-maestro",
                    "workflow": "coding execution",
                    "phase": "executing",
                    "executor_target": "maestro",
                }
            ],
            "active_executors": [
                {
                    "target_type": "run",
                    "target_id": "run-maestro",
                    "executor_profile": "codex",
                    "routed_model": "gpt-5.6-sol",
                    "routed_reasoning_effort": "xhigh",
                    "tokens_total": 42_100,
                    "cache_hit_percentage": 0,
                    "context_percentage": 41.5,
                    "latest_event": {
                        "event_type": "progress_observed",
                        "status": "running",
                        "summary": "Implementing the coding handoff.",
                    },
                },
                {
                    "target_type": "run",
                    "target_id": "run-subagent",
                    "executor_profile": "hermes_local",
                    "latest_event": {
                        "event_type": "repo_exploration",
                        "status": "running",
                        "summary": "Exploring the repository.",
                    },
                },
            ],
            "stale_executors": [],
            "latest_progress_events": [],
        }

        payload = read_omh_hud(status=status)

        self.assertEqual(payload["maestro"]["status"], "observed")
        self.assertEqual(payload["maestro"]["rows"][0]["role"], "codex")
        self.assertEqual(payload["maestro"]["rows"][0]["model"], "gpt-5.6-sol")
        self.assertEqual(payload["maestro"]["rows"][0]["cache_hit_percentage"], 0)
        self.assertEqual(payload["maestro"]["rows"][0]["context_percentage"], 41.5)
        self.assertEqual(len(payload["subagents"]["rows"]), 1)

    def test_hud_bounds_workflow_within_allowed_file_size(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "BOUNDARY_WORKFLOW_SENTINEL"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / ".omh" / "runtime" / "runs" / "999"
            run_dir.mkdir(parents=True)
            workflow = sentinel + ("x" * 240_000)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "999", "skill": workflow, "phase": "executing"}),
                encoding="utf-8",
            )

            payload = read_omh_hud(root / ".omh", root / ".hermes")
            rendered = json.dumps(payload)

            self.assertLessEqual(len(payload["runtime"]["workflow"]), 120)
            self.assertLessEqual(len(rendered), 16_384)
            self.assertNotIn("x" * 121, rendered)

    def test_hud_bounds_run_and_jsonl_reads_before_projection(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        sentinel = "OVERSIZED_HUD_SENTINEL"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            runtime = omh_home / "runtime"
            run_dir = runtime / "runs" / "999"
            progress_dir = run_dir / "executor_progress"
            progress_dir.mkdir(parents=True)
            state_path = runtime / "state.json"
            state_path.write_text(
                json.dumps({"version": sentinel, "padding": "x" * 300_000}),
                encoding="utf-8",
            )
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "999",
                        "skill": sentinel + ("y" * 300_000),
                        "phase": "executing",
                    }
                ),
                encoding="utf-8",
            )
            (progress_dir / "events.jsonl").write_text(
                (json.dumps({"summary": sentinel, "padding": "z" * 300_000}) + "\n") * 5,
                encoding="utf-8",
            )
            original_read_text = Path.read_text

            def guarded_read_text(path: Path, *args, **kwargs) -> str:
                if path in {state_path, run_dir / "run.json", progress_dir / "events.jsonl"}:
                    raise AssertionError(f"oversized metadata was read: {path}")
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", guarded_read_text):
                payload = read_omh_hud(omh_home, root / ".hermes")
            rendered = json.dumps(payload)

            self.assertLessEqual(len(rendered), 16_384)
            self.assertNotIn(sentinel, rendered)

    def test_status_alias_returns_hud_payload_for_operator_smoke_checks(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "status", "--json"],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_hud/v1")
            self.assertEqual(payload["plugin"]["status"], "missing")

    def test_hud_prints_compact_line_without_runtime_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(
                ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "hud"],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            self.assertIn(f"[omh] v{omh_version}", stdout)
            self.assertIn("plugin:not-installed", stdout)
            # No run and no recorded coding-agent preference: the segment is
            # executor-neutral, not an idle agent named "ask". See
            # docs/INSTALLATION.md "Status model: no-run, prepared-handoff,
            # observed-run".
            self.assertIn("coding-agent:not-selected", stdout)
            self.assertNotIn("coding-agent:idle(ask)", stdout)
            self.assertNotIn("tokens:unobserved", stdout)
            self.assertNotIn("executor:", stdout)
            self.assertNotIn("handoff:", stdout)

    def test_hud_shows_recorded_executor_preference_without_a_run(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(
                run_cli(
                    [
                        "--omh-home",
                        str(omh_home),
                        "--hermes-home",
                        str(hermes_home),
                        "setup",
                        "--default-executor",
                        "codex",
                    ]
                )[0],
                0,
            )

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hud", "--json"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["runtime"]["latest_run_id"], "")
            # A real, explicitly recorded preference is a legitimate reason to
            # name the executor even with no run yet; it is distinct from the
            # neutral "not-selected" no-preference state.
            self.assertIn("coding-agent:idle(codex)", payload["display"]["line"])
            self.assertNotIn("coding-agent:not-selected", payload["display"]["line"])

    def test_hud_reports_setup_plugin_target_and_prepared_runtime_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "setup"])[0], 0)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "coding",
                    "delegate",
                    "--record",
                    "--executor",
                    "codex",
                    "implement safe status feature in src/omh/runtime/status.py without overclaiming",
                ]
            )
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            run_id = json.loads(stdout)["runtime"]["run"]["run_id"]

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "hud",
                    "--json",
                    "--preset",
                    "full",
                    "--tokens-remaining",
                    "1200",
                    "--token-budget",
                    "4000",
                ]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["schema_version"], "omh_hud/v1")
            self.assertEqual(payload["version"], omh_version)
            self.assertEqual(payload["plugin"]["status"], "ready")
            self.assertNotIn("skills", payload)
            self.assertEqual(payload["target_topology"]["mode"], "single_agent_target")
            self.assertEqual(payload["runtime"]["latest_run_id"], run_id)
            self.assertEqual(payload["runtime"]["evidence_state"], "prepared_not_observed")
            self.assertEqual(payload["tokens"]["status"], "observed_from_host_metadata")
            self.assertEqual(payload["tokens"]["values"]["tokens_remaining"], 1200)
            self.assertEqual(payload["tokens"]["values"]["token_budget"], 4000)
            self.assertEqual(payload["tokens"]["summary"], "30%")
            self.assertNotIn("tokens:", payload["display"]["line"])
            self.assertIn("plugin:ready", payload["display"]["line"])
            self.assertIn("coding-agent:prepared(codex)", payload["display"]["line"])
            self.assertNotIn("plan:prepared", payload["display"]["line"])
            self.assertNotRegex(payload["display"]["line"], r"#[0-9a-f]{6}")
            self.assertNotIn("skills:", payload["display"]["line"])
            self.assertNotIn("executor:", payload["display"]["line"])
            self.assertNotIn("handoff:", payload["display"]["line"])
            self.assertIn("evidence:prepared", payload["display"]["line"])
            self.assertNotIn("evidence:prepared_not_observed", payload["display"]["line"])
            self.assertIn("Prepared handoffs are not execution", payload["evidence_boundary"])

    def test_hud_does_not_treat_non_coding_runtime_as_busy_coding_agent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            run_dir = omh_home / "runtime" / "runs" / "20260630T000000Z-loop"
            run_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260630T000000Z-loop",
                        "skill": "loop",
                        "phase": "runtime",
                        "observation_status": "unknown",
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "delegation.json").write_text(
                json.dumps({"observed": True, "result": "completed"}),
                encoding="utf-8",
            )

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "hud",
                    "--json",
                    "--preset",
                    "full",
                ],
                output_json=False,
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["runtime"]["workflow"], "loop")
            self.assertEqual(payload["runtime"]["evidence_state"], "execution_observed")
            # A non-coding runtime run (loop) never recorded a coding
            # executor_target, and no preference is configured, so the
            # coding-agent segment stays executor-neutral rather than
            # reporting a busy or idle coding agent.
            self.assertIn("coding-agent:not-selected", payload["display"]["line"])
            self.assertIn("evidence:executed", payload["display"]["line"])
            self.assertNotIn("coding-agent:idle(ask)", payload["display"]["line"])
            self.assertNotIn("coding-agent:runtime(ask)", payload["display"]["line"])

    def test_hud_marks_older_plugin_bundle_as_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            plugin_dir = hermes_home / "plugins" / "omh"
            tools_dir = plugin_dir / "tools"
            tools_dir.mkdir(parents=True)
            (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
            (plugin_dir / "plugin.yaml").write_text(
                "\n".join(
                    [
                        "name: omh",
                        'version: "0.9.0"',
                        "provides_tools:",
                        "  - omh_status",
                        "provides_hooks:",
                        "  - pre_llm_call",
                    ]
                ),
                encoding="utf-8",
            )
            (tools_dir / "status_tool.py").write_text("OMH_STATUS_SCHEMA = {}\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hud", "--json"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["plugin"]["status"], "stale")
            self.assertTrue(payload["plugin"]["stale"])
            self.assertFalse(payload["plugin"]["capabilities"]["tools"]["omh_hud"])
            self.assertTrue(payload["plugin"]["capabilities"]["tools"]["omh_status"])
            self.assertIn("plugin:update-needed", payload["display"]["line"])

    def test_hud_marks_legacy_complete_plugin_without_capabilities_tool_as_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"
            plugin_dir = hermes_home / "plugins" / "omh"
            tools_dir = plugin_dir / "tools"
            refs_dir = plugin_dir / "references"
            tools_dir.mkdir(parents=True)
            refs_dir.mkdir()
            (plugin_dir / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
            (plugin_dir / "plugin.yaml").write_text(
                "\n".join(
                    [
                        "name: omh",
                        'version: "0.9.0"',
                        "provides_tools:",
                        "  - omh_gather_evidence",
                        "  - omh_hud",
                        "  - omh_role",
                        "  - omh_status",
                        "provides_hooks:",
                        "  - on_session_end",
                        "  - pre_llm_call",
                        "  - pre_tool_call",
                    ]
                ),
                encoding="utf-8",
            )
            for stem in ("evidence_tool", "hud_tool", "role_tool", "status_tool"):
                (tools_dir / f"{stem}.py").write_text("SCHEMA = {}\n", encoding="utf-8")
            (refs_dir / "role-planner.md").write_text("# Planner\n", encoding="utf-8")

            status, stdout, stderr = run_cli(
                ["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "hud", "--json"]
            )

            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)
            payload = json.loads(stdout)
            self.assertEqual(payload["plugin"]["status"], "stale")
            self.assertFalse(payload["plugin"]["capabilities"]["tools"]["omh_capabilities"])
            self.assertTrue(payload["plugin"]["capabilities"]["tools"]["omh_status"])
            self.assertIn("plugin:update-needed", payload["display"]["line"])

    def test_hud_plugin_tool_tolerates_untrusted_limit_argument(self) -> None:
        from omh.plugin_bundle.omh.tools.hud_tool import omh_hud_handler

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = json.loads(
                omh_hud_handler(
                    {
                        "omh_home": str(root / ".omh"),
                        "hermes_home": str(root / ".hermes"),
                        "limit": "not-a-number",
                    }
                )
            )

            self.assertEqual(payload["schema_version"], "omh_hud/v1")
            self.assertEqual(payload["runtime"]["recent_run_count"], 0)


class TodoHudTests(unittest.TestCase):
    def _write_todo(self, omh_home: Path, record: dict) -> Path:
        runtime_dir = omh_home / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        path = runtime_dir / "todo.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def _record(self, **overrides: object) -> dict:
        from datetime import datetime, timezone

        record = {
            "schema_version": "omh_todo/v1",
            "title": "Foundation",
            "source": "cli",
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "items": [
                {"text": "Restore RED baseline", "state": "done"},
                {"text": "Inspect routing fixtures", "state": "active"},
                {"text": "Update count assertions", "state": "pending"},
                {"text": "Run byte gates", "state": "pending"},
            ],
        }
        record.update(overrides)
        return record

    def test_hud_projects_established_todo_with_collapse_and_lines(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_todo(root / ".omh", self._record())
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            todo = payload["todo"]
            self.assertEqual(todo["status"], "established")
            self.assertEqual(
                todo["counts"],
                {"total": 4, "done": 1, "active": 1, "pending": 2, "phases": 0},
            )
            self.assertEqual(
                [item["text"] for item in todo["display_items"]],
                ["Restore RED baseline", "Inspect routing fixtures", "Update count assertions"],
            )
            self.assertEqual(todo["more_count"], 1)
            self.assertEqual(
                payload["display"]["todo_lines"],
                [
                    "Todo · Foundation   1/4",
                    "[✓] Restore RED baseline",
                    "[•] Inspect routing fixtures",
                    "[ ] Update count assertions   +1 more",
                ],
            )
            self.assertIn("Todo items are plan declarations", payload["evidence_boundary"])

    def test_hud_indents_multiple_tasks_beneath_their_phase_header(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                {"text": "Edit source", "state": "active", "phase": "Implementation"},
                {"text": "Run tests", "state": "pending", "phase": "Implementation"},
            ]
            self._write_todo(root / ".omh", self._record(items=items))

            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(
                payload["display"]["todo_lines"],
                [
                    "Todo · Foundation   0/2",
                    "Implementation",
                    "  [•] Edit source",
                    "  [ ] Run tests",
                ],
            )

    def test_hud_inherits_phase_for_unphased_nested_tasks(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                {"text": "Verify", "state": "active", "phase": "Verification"},
                {"text": "Usability", "state": "pending", "depth": 1},
            ]
            self._write_todo(root / ".omh", self._record(items=items))

            focused = read_omh_hud(root / ".omh", root / ".hermes")
            full = read_omh_hud(root / ".omh", root / ".hermes", preset="full")

            expected_lines = [
                "Todo · Foundation   0/2",
                "Verification",
                "  [•] Verify",
                "    [ ] Usability",
            ]
            self.assertEqual(
                [item["text"] for item in focused["todo"]["display_items"]],
                ["Verify", "Usability"],
            )
            self.assertEqual(focused["display"]["todo_lines"], expected_lines)
            self.assertEqual(full["display"]["todo_lines"], expected_lines)

    def test_hud_keeps_unphased_root_tasks_outside_neighboring_phases(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        phase_item = {"text": "Phase task", "state": "pending", "phase": "Implementation"}
        root_item = {"text": "Standalone", "state": "active"}
        scenarios = (
            ([phase_item, root_item], ["Implementation", "  [ ] Phase task", "[•] Standalone"]),
            ([root_item, phase_item], ["[•] Standalone", "Implementation", "  [ ] Phase task"]),
        )

        for items, full_rows in scenarios:
            with self.subTest(items=items), TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._write_todo(root / ".omh", self._record(items=items))

                focused = read_omh_hud(root / ".omh", root / ".hermes")
                full = read_omh_hud(root / ".omh", root / ".hermes", preset="full")

                self.assertEqual(focused["todo"].get("display_phase", ""), "")
                self.assertEqual(
                    focused["display"]["todo_lines"],
                    ["Todo · Foundation   0/2", "[•] Standalone   +1 more"],
                )
                self.assertEqual(
                    full["display"]["todo_lines"],
                    ["Todo · Foundation   0/2", *full_rows],
                )

    def test_hud_full_keeps_consecutive_root_tasks_under_their_phase(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                {"text": "First phased", "state": "active", "phase": "Implementation"},
                {"text": "Second phased", "state": "pending", "phase": "Implementation"},
                {"text": "Standalone", "state": "pending"},
            ]
            self._write_todo(root / ".omh", self._record(items=items))

            payload = read_omh_hud(root / ".omh", root / ".hermes", preset="full")

            self.assertEqual(
                payload["display"]["todo_lines"],
                [
                    "Todo · Foundation   0/3",
                    "Implementation",
                    "  [•] First phased",
                    "  [ ] Second phased",
                    "[ ] Standalone",
                ],
            )

    def test_hud_todo_lines_respect_minimal_and_full_presets(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_todo(root / ".omh", self._record())
            minimal = read_omh_hud(root / ".omh", root / ".hermes", preset="minimal")
            full = read_omh_hud(root / ".omh", root / ".hermes", preset="full")

            self.assertEqual(minimal["display"]["todo_lines"], ["Todo · Foundation   1/4"])
            self.assertEqual(len(full["display"]["todo_lines"]), 5)
            self.assertNotIn("more", full["display"]["todo_lines"][-1])

    def test_hud_collapses_all_done_todo_to_single_header_line(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [{"text": "Restore RED baseline", "state": "done"}, {"text": "Run byte gates", "state": "done"}]
            self._write_todo(root / ".omh", self._record(items=items))
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(payload["todo"]["status"], "all_done")
            self.assertEqual(payload["todo"]["display_items"], [])
            self.assertEqual(payload["display"]["todo_lines"], ["Todo · Foundation ✓ 2/2"])

    def test_hud_retires_a_finished_plan_after_its_linger_window(self) -> None:
        # A finished plan is a receipt, not ambient chrome: it lingers briefly
        # for the session that finished it, then leaves. Without this, a plan
        # completed in one session greeted every NEW session as a "Plan 3/3"
        # panel for a full day (observed on a fresh boot the morning after).
        from datetime import datetime, timedelta, timezone

        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            done_items = [{"text": "Ship", "state": "done"}]
            old_stamp = (
                (datetime.now(timezone.utc) - timedelta(minutes=20))
                .isoformat()
                .replace("+00:00", "Z")
            )
            self._write_todo(root / ".omh", self._record(items=done_items, updated_at=old_stamp))
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(payload["todo"]["status"], "absent")
            self.assertEqual(payload["display"]["todo_lines"], [])

    def test_hud_hides_stale_and_unparseable_todo_updates(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for updated_at in ("2020-01-01T00:00:00Z", "not-a-timestamp"):
                self._write_todo(root / ".omh", self._record(updated_at=updated_at))
                payload = read_omh_hud(root / ".omh", root / ".hermes")

                self.assertEqual(payload["todo"]["status"], "stale")
                self.assertEqual(payload["display"]["todo_lines"], [])

    def test_hud_ignores_invalid_todo_schema_and_malformed_items(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_records = [
                self._record(schema_version="omh_todo/v0"),
                self._record(items=[]),
                self._record(items=[{"text": "", "state": "done"}, {"text": "x", "state": "later"}, "raw"]),
            ]
            for record in invalid_records:
                self._write_todo(root / ".omh", record)
                payload = read_omh_hud(root / ".omh", root / ".hermes")

                self.assertEqual(payload["todo"]["status"], "absent")
                self.assertEqual(payload["display"]["todo_lines"], [])

    def test_hud_rejects_symlinked_todo_file(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside-todo.json"
            outside.write_text(json.dumps(self._record()), encoding="utf-8")
            runtime_dir = root / ".omh" / "runtime"
            runtime_dir.mkdir(parents=True)
            (runtime_dir / "todo.json").symlink_to(outside)
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(payload["todo"]["status"], "absent")

    def test_todo_plugin_tool_set_show_clear_round_trip(self) -> None:
        import os

        from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler

        with TemporaryDirectory() as tmp:
            home = str(Path(tmp) / ".omh")
            with patch.dict(os.environ, {"OMH_HOME": home}):
                written = json.loads(
                    omh_todo_handler(
                        {
                            "action": "set",
                            "title": "Foundation",
                            "items": [{"text": "Inspect routing fixtures", "state": "active"}],
                        }
                    )
                )
                self.assertEqual(written["status"], "written")
                self.assertEqual(written["todo"]["status"], "established")

            shown = json.loads(omh_todo_handler({"action": "show", "omh_home": home}))
            self.assertEqual(shown["status"], "read")
            self.assertEqual(shown["todo"]["counts"]["total"], 1)

            with patch.dict(os.environ, {"OMH_HOME": home}):
                cleared = json.loads(omh_todo_handler({"action": "clear"}))
                self.assertEqual(cleared["status"], "cleared")
                self.assertEqual(cleared["todo"]["status"], "absent")

    def test_todo_plugin_tool_rejects_omh_home_override_for_mutations(self) -> None:
        from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "victim"
            for action, extra in (("set", {"items": [{"text": "x"}]}), ("clear", {})):
                payload = json.loads(
                    omh_todo_handler({"action": action, "omh_home": str(target), **extra})
                )

                self.assertEqual(payload["status"], "invalid_todo")
                self.assertIn("configured OMH home", payload["error"])
            self.assertFalse(target.exists())

    def test_todo_plugin_tool_reports_invalid_items_without_writing(self) -> None:
        import os

        from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler

        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            with patch.dict(os.environ, {"OMH_HOME": str(home)}):
                payload = json.loads(
                    omh_todo_handler({"action": "set", "items": [{"text": "x", "state": "later"}]})
                )

            self.assertEqual(payload["status"], "invalid_todo")
            self.assertEqual(payload["todo"]["status"], "absent")
            self.assertFalse((home / "runtime" / "todo.json").exists())

    def test_todo_more_count_ignores_hidden_done_items(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [{"text": f"done {n}", "state": "done"} for n in range(4)]
            items.append({"text": "current", "state": "active"})
            self._write_todo(root / ".omh", self._record(items=items))
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(payload["todo"]["more_count"], 0)
            self.assertEqual(
                payload["display"]["todo_lines"],
                ["Todo · Foundation   4/5", "[✓] done 3", "[•] current"],
            )

    def test_todo_plugin_tool_reports_invalid_action_and_already_absent(self) -> None:
        import os

        from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler

        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"OMH_HOME": str(Path(tmp) / ".omh")}):
                invalid = json.loads(omh_todo_handler({"action": "purge"}))
                absent = json.loads(omh_todo_handler({"action": "clear"}))

            self.assertEqual(invalid["status"], "invalid_action")
            self.assertTrue(invalid["error"])
            self.assertEqual(absent["status"], "already_absent")

    def test_todo_store_rejects_item_cap_and_symlinked_home(self) -> None:
        from omh.plugin_bundle.omh.todo_store import (
            MAX_TODO_ITEMS,
            TodoStoreError,
            TodoValidationError,
            build_todo_record,
            write_todo,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = build_todo_record("t", [{"text": "x"}], source="cli")

            with self.assertRaises(TodoValidationError):
                build_todo_record("t", [{"text": "x"}] * (MAX_TODO_ITEMS + 1), source="cli")

            outside = root / "outside"
            outside.mkdir()
            linked_home = root / ".omh"
            linked_home.mkdir()
            (linked_home / "runtime").symlink_to(outside)
            with self.assertRaises(TodoStoreError):
                write_todo(linked_home, record)

    @requires_posix_permissions
    def test_todo_store_reports_unwritable_home_as_store_error(self) -> None:
        from omh.plugin_bundle.omh.todo_store import TodoStoreError, build_todo_record, write_todo

        with TemporaryDirectory() as tmp:
            sealed_home = Path(tmp) / "sealed"
            sealed_home.mkdir(mode=0o500)
            try:
                with self.assertRaises(TodoStoreError):
                    write_todo(sealed_home, build_todo_record("t", [{"text": "x"}], source="cli"))
            finally:
                sealed_home.chmod(0o700)

    def test_todo_surfaces_strip_control_characters_on_write_and_read(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud
        from omh.plugin_bundle.omh.todo_store import build_todo_record

        record = build_todo_record(
            "A\x1b[2J\x1b[1;1Hpwned",
            [{"text": "ok\x1b]0;hijack\x07 \r\n done", "state": "active"}],
            source="cli",
        )
        self.assertEqual(record["title"], "A[2J[1;1Hpwned")
        self.assertEqual(record["items"][0]["text"], "ok]0;hijack  done")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_todo(
                root / ".omh",
                self._record(
                    title="B\x1bad",
                    items=[{"text": "line\r\nsplit", "state": "active"}],
                ),
            )
            payload = read_omh_hud(root / ".omh", root / ".hermes")

            self.assertEqual(payload["todo"]["title"], "Bad")
            self.assertEqual(payload["todo"]["items"], [{"text": "linesplit", "state": "active"}])
            self.assertEqual(len(payload["display"]["todo_lines"]), 2)


class ActivityRowOrderTests(unittest.TestCase):
    """Merged activity rows: running first, settled newest-first, capped at 8.

    Display-priority ordering adopted from OMO's DAG status widget — a late
    failure must never be pushed off screen by older completed rows, and
    running lanes keep dispatch order.
    """

    def _rows(self, *specs: tuple[str, str, str]) -> list[dict[str, str]]:
        return [
            {"task_id": task_id, "state": state, "observed_at": observed_at}
            for task_id, state, observed_at in specs
        ]

    def test_running_rows_lead_and_keep_dispatch_order(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import _ordered_activity_rows

        rows = self._rows(
            ("done-old", "done", "2026-08-26T10:00:00Z"),
            ("run-b", "running", "2026-08-26T10:01:00Z"),
            ("blocked-new", "blocked", "2026-08-26T10:05:00Z"),
            ("run-a", "running", "2026-08-26T10:02:00Z"),
            ("done-new", "done", "2026-08-26T10:04:00Z"),
            ("failed-old", "failed", "2026-08-26T10:03:00Z"),
        )
        ordered = [row["task_id"] for row in _ordered_activity_rows(rows)]
        self.assertEqual(
            ordered,
            ["run-b", "run-a", "blocked-new", "failed-old", "done-new", "done-old"],
        )

    def test_rows_without_a_state_count_as_running(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import _ordered_activity_rows

        rows = [{"task_id": "bare"}] + self._rows(("done", "done", "2026-08-26T10:00:00Z"))
        self.assertEqual(
            [row["task_id"] for row in _ordered_activity_rows(rows)],
            ["bare", "done"],
        )

    def test_merged_rows_cap_at_eight_dropping_oldest_settled_first(self) -> None:
        from omh.plugin_bundle.omh.runtime_reader import (
            ACTIVITY_ROW_LIMIT,
            _ordered_activity_rows,
        )

        self.assertEqual(ACTIVITY_ROW_LIMIT, 8)
        rows = self._rows(
            *[(f"run-{index}", "running", f"2026-08-26T10:0{index}:00Z") for index in range(6)],
            ("done-new", "done", "2026-08-26T10:09:00Z"),
            ("done-mid", "done", "2026-08-26T10:08:00Z"),
            ("done-old", "done", "2026-08-26T10:07:00Z"),
        )
        ordered = [row["task_id"] for row in _ordered_activity_rows(rows)]
        # The helper orders without dropping; the call site slices at the
        # limit and discloses the count, so the capped view keeps all six
        # running rows, fills the remainder with the newest settled rows, and
        # the oldest settled row is the one that falls off.
        self.assertEqual(len(ordered), 9)
        capped = ordered[:ACTIVITY_ROW_LIMIT]
        self.assertEqual(capped[:6], [f"run-{index}" for index in range(6)])
        self.assertEqual(capped[6:], ["done-new", "done-mid"])

    def test_row_limit_matches_the_native_reader_bound(self) -> None:
        # The comment on ACTIVITY_ROW_LIMIT claims parity with the native
        # reader's own per-source bound; make the claim enforceable.
        from omh.plugin_bundle.omh.hermes_delegation import _ROW_LIMIT
        from omh.plugin_bundle.omh.runtime_reader import ACTIVITY_ROW_LIMIT

        self.assertEqual(ACTIVITY_ROW_LIMIT, _ROW_LIMIT)


if __name__ == "__main__":
    unittest.main()
