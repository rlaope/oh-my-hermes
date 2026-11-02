from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.coding.dispatch_failure_recovery import (  # noqa: E402
    CHOICE_HERMES,
    CHOICE_REPORT,
    CHOICE_RETARGET,
    CHOICE_WAIT,
    COOLDOWN_STATUS_AUTH,
    COOLDOWN_STATUS_LIMIT,
    EXECUTOR_AUTH_FAILURE_SIGNALS_SCHEMA_VERSION,
    FAILURE_KIND_AUTH_SHAPED,
    FAILURE_KIND_BINARY_MISSING,
    DISPATCHER_ASSIGNED_FAILURE_KINDS,
    FAILURE_KIND_CAPABILITY_GATE,
    FAILURE_KIND_CRASH,
    FAILURE_KIND_LIMIT_SHAPED,
    FAILURE_KIND_TIMEOUT,
    FAILURE_KIND_WORKSPACE_BLOCKED,
    FAILURE_KINDS,
    RECOVERABLE_FAILURE_KINDS,
    OnFailureModeError,
    auth_repair_command,
    auth_shaped_label,
    build_repair_card,
    classify_failure_kind,
    clear_auth_failure_signal,
    last_auth_failure_signal,
    parse_on_failure,
    prompt_recovery_choice,
    record_auth_failure_signal,
    recovery_candidates,
    recovery_options,
    retarget_candidates,
    spawn_cooldown,
)
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import (  # noqa: E402
    _hermes_recovery_dispatch,
    dispatch_fanout,
    signal_safe_unit_runner,
)
from omh.coding.fanout_capacity import OwnerLaunchGate  # noqa: E402
from omh.coding.fanout_journal import (  # noqa: E402
    RESUME_RERUN_AWAITING_RETRY,
    build_fanout_run_journal,
    plan_fanout_resume,
)
from omh.system.local_store import atomic_write_json, utc_now  # noqa: E402
from omh.coding.fanout_status import project_fanout_status  # noqa: E402
from omh.commands.coding import _fanout_dispatch_exit_code  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402
from omh.workflows.observation_journal import read_observation_events  # noqa: E402
from _fanout_host_fence import host_cannot_fence_fanout  # noqa: E402

_GOAL = "split the sample feature across agents"
_UNITS = [
    {"unit_id": "core", "title": "Core work", "owner": "codex", "file_scope": ["src/core/"]},
]
_CLI_UNITS = _UNITS + [
    {"unit_id": "docs", "title": "Docs work", "owner": "claude-code", "file_scope": ["docs/"]},
]


def _git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True)


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, sha


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ready(paths, profile, **kwargs):
    return {"status": "ready", "profile": profile}


def _runner(outputs: dict[str, _FakeCompleted]):
    """Route git to the real subprocess; answer each agent CLI from `outputs`."""
    spawned: list[list[str]] = []

    def runner(argv, **kwargs):
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        spawned.append(list(argv))
        return outputs.get(argv[0], _FakeCompleted(0, "done"))

    runner.spawned = spawned
    return runner


class FailureKindClassificationTests(unittest.TestCase):
    def test_closed_enum_covers_every_classifier_answer(self) -> None:
        answers = {
            classify_failure_kind(exit_code=127),
            classify_failure_kind(exit_code=124),
            classify_failure_kind(exit_code=1, auth_label="http_401"),
            classify_failure_kind(exit_code=1, limit_label="rate_limit"),
            classify_failure_kind(exit_code=1),
        }
        # `workspace_blocked` and `capability_gate` are the kinds the classifier
        # can never answer: both are assigned before the spawn, when there is
        # no exit code and no output to classify. Every OTHER member of the
        # enum must still come out of the classifier, or the enum has grown a
        # value nothing sets.
        self.assertEqual(
            DISPATCHER_ASSIGNED_FAILURE_KINDS,
            {FAILURE_KIND_WORKSPACE_BLOCKED, FAILURE_KIND_CAPABILITY_GATE},
        )
        self.assertEqual(answers, set(FAILURE_KINDS) - DISPATCHER_ASSIGNED_FAILURE_KINDS)
        self.assertTrue(DISPATCHER_ASSIGNED_FAILURE_KINDS.isdisjoint(answers))
        self.assertTrue(DISPATCHER_ASSIGNED_FAILURE_KINDS.isdisjoint(RECOVERABLE_FAILURE_KINDS))

    def test_workspace_blocked_is_never_offered_a_recovery_retry(self) -> None:
        # A blocked workspace is the one failure another attempt cannot clear:
        # the objects are still missing, the denial is still a denial, and the
        # case collision is still in the tree.
        self.assertIn(FAILURE_KIND_WORKSPACE_BLOCKED, FAILURE_KINDS)
        self.assertNotIn(FAILURE_KIND_WORKSPACE_BLOCKED, RECOVERABLE_FAILURE_KINDS)

    def test_synthetic_exit_codes_map_before_any_text_match(self) -> None:
        # 127 and 124 are the dispatcher's own observations of the process, so
        # they win even when the tail also carries a provider-shaped message.
        self.assertEqual(
            classify_failure_kind(exit_code=127, limit_label="rate_limit", auth_label="http_401"),
            FAILURE_KIND_BINARY_MISSING,
        )
        self.assertEqual(
            classify_failure_kind(exit_code=124, limit_label="rate_limit", auth_label="http_401"),
            FAILURE_KIND_TIMEOUT,
        )

    def test_auth_wins_over_limit_when_both_shapes_match(self) -> None:
        # The documented precedence: a credential rejection filed as a limit
        # would go into the wait-it-out lane, which can never clear it.
        self.assertEqual(
            classify_failure_kind(exit_code=1, limit_label="rate_limit", auth_label="http_401"),
            FAILURE_KIND_AUTH_SHAPED,
        )

    def test_unclassified_nonzero_exit_is_crash(self) -> None:
        self.assertEqual(classify_failure_kind(exit_code=2), FAILURE_KIND_CRASH)
        self.assertEqual(classify_failure_kind(exit_code=0), "")

    def test_auth_shaped_phrases_are_recognized(self) -> None:
        for text, expected in (
            ("Error: Invalid API key provided", "invalid_api_key"),
            ("your token has expired, please log in again", "token_expired"),
            ("You are not logged in. Please run /login.", "not_logged_in"),
            ("request failed with status 401", "http_401"),
            ("401 Unauthorized", "http_401"),
            ("authentication failed for this account", "authentication_failed"),
            ("the oauth token revoked by the workspace admin", "oauth_revoked"),
        ):
            with self.subTest(text=text):
                self.assertEqual(auth_shaped_label(text, ""), expected)

    def test_unrelated_author_and_401_text_is_not_auth_shaped(self) -> None:
        # The negative controls that keep the patterns multi-word: a bare
        # "auth", "author", or "401" appears constantly in ordinary CLI output.
        for text in (
            "git shortlog: author list for the release notes",
            "unauthorized_reviewers.md mentioned in output",
            "processed value 401 items in the batch",
            "AUTHORS file updated",
            "token budget exceeded for this context window",
            "authorization header forwarded to the proxy",
        ):
            with self.subTest(text=text):
                self.assertEqual(auth_shaped_label(text, ""), "")
                self.assertEqual(auth_shaped_label("", text), "")

    def test_auth_shape_is_matched_case_insensitively_across_both_tails(self) -> None:
        self.assertEqual(auth_shaped_label("", "FATAL: INVALID API KEY"), "invalid_api_key")


class AuthFailureSignalTests(unittest.TestCase):
    def _paths(self, tmp: str) -> OmhPaths:
        root = Path(tmp)
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")

    def test_signal_persists_per_owner_and_reads_back_with_age(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="run-1", unit_id="core", pattern_label="http_401"
            )
            stored = json.loads(paths.executor_auth_failure_signals_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["schema_version"], EXECUTOR_AUTH_FAILURE_SIGNALS_SCHEMA_VERSION)
            self.assertEqual(stored["profiles"]["codex"]["pattern_label"], "http_401")
            signal = last_auth_failure_signal(paths, "codex")
            self.assertFalse(signal["stale"])
            self.assertIsInstance(signal["age_seconds"], int)
            self.assertEqual(last_auth_failure_signal(paths, "claude-code"), {})

    def test_clear_removes_only_the_named_owner(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            record_auth_failure_signal(paths, "codex", run_ref="r", unit_id="u", pattern_label="a")
            record_auth_failure_signal(
                paths, "claude-code", run_ref="r", unit_id="u", pattern_label="b"
            )
            clear_auth_failure_signal(paths, "codex")
            self.assertEqual(last_auth_failure_signal(paths, "codex"), {})
            self.assertEqual(last_auth_failure_signal(paths, "claude-code")["pattern_label"], "b")

    def test_missing_file_reads_as_no_signal_and_clear_is_a_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            self.assertEqual(last_auth_failure_signal(paths, "codex"), {})
            clear_auth_failure_signal(paths, "codex")
            self.assertFalse(paths.executor_auth_failure_signals_path.exists())

    def test_stale_signal_does_not_cool_down_and_fresh_one_does(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="u", pattern_label="http_401"
            )
            cooldown = spawn_cooldown(paths, "codex")
            self.assertIsNotNone(cooldown)
            self.assertEqual(cooldown["status"], COOLDOWN_STATUS_AUTH)
            self.assertEqual(cooldown["failure_kind"], FAILURE_KIND_AUTH_SHAPED)
            atomic_write_json(
                paths.executor_auth_failure_signals_path,
                {
                    "schema_version": EXECUTOR_AUTH_FAILURE_SIGNALS_SCHEMA_VERSION,
                    "profiles": {
                        "codex": {"last_auth_shaped_at": "2020-01-01T00:00:00Z", "pattern_label": "x"}
                    },
                },
                private=True,
            )
            self.assertIsNone(spawn_cooldown(paths, "codex"))

    def test_unaged_record_never_vetoes_a_spawn(self) -> None:
        # A record whose observation time cannot be read cannot be shown to be
        # inside the window, so it ranks but never refuses.
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            atomic_write_json(
                paths.executor_limit_signals_path,
                {"schema_version": "executor_limit_signals/v1", "profiles": {"codex": {"pattern_label": "x"}}},
                private=True,
            )
            self.assertIsNone(spawn_cooldown(paths, "codex"))

    def test_limit_cooldown_is_reported_when_no_auth_signal_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            atomic_write_json(
                paths.executor_limit_signals_path,
                {
                    "schema_version": "executor_limit_signals/v1",
                    "profiles": {"codex": {"last_limit_shaped_at": utc_now(), "pattern_label": "rate_limit"}},
                },
                private=True,
            )
            cooldown = spawn_cooldown(paths, "codex")
            self.assertEqual(cooldown["status"], COOLDOWN_STATUS_LIMIT)
            self.assertEqual(cooldown["failure_kind"], FAILURE_KIND_LIMIT_SHAPED)
            self.assertIsInstance(cooldown["cooldown_remaining_seconds"], int)


class ReadinessSurfaceTests(unittest.TestCase):
    def test_readiness_reports_the_auth_failure_signal_without_persisting_it(self) -> None:
        # The operator whose unit came back `executor_auth_invalid` reads the
        # reason here; advisory markers are recomputed per call, never frozen
        # into the observed-once probe cache.
        from omh.coding.executor_readiness import probe_executor_readiness

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            result = probe_executor_readiness(paths, "codex", dry_run=True)
            self.assertEqual(result["last_auth_failure_signal"]["pattern_label"], "http_401")
            probe_executor_readiness(paths, "codex")
            stored = json.loads(paths.executor_readiness_path.read_text(encoding="utf-8"))
            self.assertNotIn("last_auth_failure_signal", stored["profiles"]["codex"])


class RepairCardTests(unittest.TestCase):
    def test_known_owners_get_their_own_login_command(self) -> None:
        self.assertIn("/login", auth_repair_command("claude-code"))
        self.assertEqual(auth_repair_command("codex"), "codex login")

    def test_unknown_owner_gets_a_neutral_instruction(self) -> None:
        # Executor-neutral: no CLI is the implied default for an owner this
        # repo has not verified a login command for.
        command = auth_repair_command("pi-family-runtime")
        self.assertIn("pi-family-runtime", command)
        self.assertNotIn("codex login", command)
        self.assertNotIn("claude", command)

    def test_auth_card_names_reauth_then_redispatch(self) -> None:
        card = build_repair_card(owner="codex", failure_kind=FAILURE_KIND_AUTH_SHAPED, detail="d")
        self.assertEqual(card["reason_code"], FAILURE_KIND_AUTH_SHAPED)
        self.assertEqual(
            [step["id"] for step in card["repair_steps"]],
            ["reauthenticate_owner", "redispatch_after_repair"],
        )

    def test_limit_card_names_the_wait_and_carries_the_remaining_window(self) -> None:
        card = build_repair_card(
            owner="codex", failure_kind=FAILURE_KIND_LIMIT_SHAPED, detail="d", remaining_seconds=90
        )
        self.assertEqual(card["cooldown_remaining_seconds"], 90)
        self.assertIn("90s", card["repair_steps"][0]["action"])


class OnFailureModeTests(unittest.TestCase):
    def test_named_modes_parse_without_a_target(self) -> None:
        self.assertEqual(parse_on_failure(""), ("report", ""))
        self.assertEqual(parse_on_failure("report"), ("report", ""))
        self.assertEqual(parse_on_failure("hermes"), ("hermes", ""))
        self.assertEqual(parse_on_failure("wait"), ("wait", ""))

    def test_retarget_carries_its_owner_and_validates_it(self) -> None:
        self.assertEqual(
            parse_on_failure("retarget:claude-code", known_owners=("codex", "claude-code")),
            (CHOICE_RETARGET, "claude-code"),
        )
        with self.assertRaises(OnFailureModeError):
            parse_on_failure("retarget:", known_owners=("codex",))
        with self.assertRaises(OnFailureModeError):
            parse_on_failure("retarget:nope", known_owners=("codex",))

    def test_unknown_mode_is_refused_by_name(self) -> None:
        with self.assertRaises(OnFailureModeError) as caught:
            parse_on_failure("switch")
        self.assertIn("switch", str(caught.exception))


class RecoveryOptionTests(unittest.TestCase):
    def test_only_auth_and_limit_failures_are_candidates(self) -> None:
        units = [
            {"unit_id": "a", "owner": "codex", "failure_kind": FAILURE_KIND_AUTH_SHAPED},
            {"unit_id": "b", "owner": "codex", "failure_kind": FAILURE_KIND_LIMIT_SHAPED},
            {"unit_id": "c", "owner": "codex", "failure_kind": FAILURE_KIND_CRASH},
            {"unit_id": "d", "owner": "codex", "failure_kind": FAILURE_KIND_TIMEOUT},
            {"unit_id": "e", "owner": "codex", "failure_kind": FAILURE_KIND_BINARY_MISSING},
            {"unit_id": "f", "owner": "codex"},
        ]
        self.assertEqual([row["unit_id"] for row in recovery_candidates(units)], ["a", "b"])

    def test_the_failed_owner_is_never_offered_as_a_retarget(self) -> None:
        context = {
            "candidates": [
                {"profile": "codex", "label": "Codex", "readiness_status": "ready"},
                {"profile": "claude-code", "label": "Claude Code", "readiness_status": "ready"},
            ]
        }
        rows = retarget_candidates(context, exclude_owner="codex")
        self.assertEqual([row["profile"] for row in rows], ["claude-code"])

    def test_unavailable_options_are_listed_with_their_reason(self) -> None:
        options = recovery_options(
            candidate={"unit_id": "a", "owner": "codex", "failure_kind": FAILURE_KIND_AUTH_SHAPED},
            retargets=[],
            hermes_available=False,
        )
        self.assertEqual([option["choice"] for option in options], [CHOICE_RETARGET, CHOICE_HERMES, CHOICE_WAIT])
        self.assertFalse(options[0]["available"])
        self.assertIn("no other locally-installed coding owner", options[0]["unavailable_reason"])
        self.assertFalse(options[1]["available"])
        self.assertIn("--hermes-model", options[1]["unavailable_reason"])
        self.assertTrue(options[2]["available"])


class RecoveryInterviewPromptTests(unittest.TestCase):
    """The prompt seam is injected, so no test ever needs a real terminal."""

    def _ask(self, answers: list[str], *, retargets, hermes_available=True):
        written: list[str] = []
        candidate = {"unit_id": "core", "owner": "codex", "failure_kind": FAILURE_KIND_LIMIT_SHAPED}
        options = recovery_options(
            candidate=candidate, retargets=retargets, hermes_available=hermes_available
        )
        queue = list(answers)

        def read_line(_prompt: str) -> str:
            if not queue:
                raise EOFError
            return queue.pop(0)

        chosen = prompt_recovery_choice(
            candidate=candidate,
            options=options,
            read_line=read_line,
            write_line=written.append,
        )
        return chosen, written

    def test_choice_one_with_a_single_candidate_selects_that_owner(self) -> None:
        chosen, written = self._ask(["1"], retargets=[{"profile": "claude-code"}])
        self.assertEqual(chosen, {"choice": CHOICE_RETARGET, "target_owner": "claude-code"})
        self.assertTrue(any("core failed on codex" in line for line in written))

    def test_choice_one_with_several_candidates_asks_which_owner(self) -> None:
        chosen, _ = self._ask(
            ["1", "pi-family-runtime"],
            retargets=[{"profile": "claude-code"}, {"profile": "pi-family-runtime"}],
        )
        self.assertEqual(chosen, {"choice": CHOICE_RETARGET, "target_owner": "pi-family-runtime"})

    def test_choice_two_selects_the_hermes_lane(self) -> None:
        chosen, _ = self._ask(["2"], retargets=[{"profile": "claude-code"}])
        self.assertEqual(chosen["choice"], CHOICE_HERMES)

    def test_choice_three_selects_wait(self) -> None:
        chosen, _ = self._ask(["3"], retargets=[])
        self.assertEqual(chosen["choice"], CHOICE_WAIT)

    def test_an_unavailable_option_is_refused_and_re_asked(self) -> None:
        chosen, written = self._ask(["2", "3"], retargets=[], hermes_available=False)
        self.assertEqual(chosen["choice"], CHOICE_WAIT)
        self.assertTrue(any("Option 2 is unavailable" in line for line in written))

    def test_a_closed_input_stream_falls_back_to_report(self) -> None:
        chosen, written = self._ask([], retargets=[])
        self.assertEqual(chosen["choice"], CHOICE_REPORT)
        self.assertTrue(any("No recovery action chosen" in line for line in written))

    def test_junk_answers_are_re_asked_then_give_up_as_report(self) -> None:
        chosen, written = self._ask(["x", "9", "  "], retargets=[])
        self.assertEqual(chosen["choice"], CHOICE_REPORT)
        self.assertEqual(sum(1 for line in written if line == "Answer 1, 2, or 3."), 3)


_AUTH_FAILURE_TEXT = "Error: invalid API key. Run `codex login` and try again."
_LIMIT_FAILURE_TEXT = "Error: you have hit your usage limit. Try again later."


class DispatchFailureRecoveryEngineTests(unittest.TestCase):
    def _setup(self, tmp: str, units=None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, list(units or _UNITS)))
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, runner, **kwargs):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=runner,
            readiness=_ready,
            **kwargs,
        )

    def test_auth_shaped_failure_classifies_persists_and_carries_a_repair_card(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(
                paths, repo, sha, contract, _runner({"codex": _FakeCompleted(1, _AUTH_FAILURE_TEXT)})
            )
            core = summary["units"][0]
            self.assertEqual(core["failure_kind"], FAILURE_KIND_AUTH_SHAPED)
            self.assertTrue(core["auth_shaped"])
            self.assertEqual(core["auth_pattern"], "invalid_api_key")
            self.assertEqual(core["repair_card"]["repair_steps"][0]["command"], "codex login")
            self.assertEqual(last_auth_failure_signal(paths, "codex")["pattern_label"], "invalid_api_key")
            # Auth takes the persisted signal; no limit record is fabricated.
            self.assertFalse(paths.executor_limit_signals_path.exists())

    def test_limit_shaped_failure_keeps_its_existing_flags_and_gains_a_kind(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(
                paths, repo, sha, contract, _runner({"codex": _FakeCompleted(1, _LIMIT_FAILURE_TEXT)})
            )
            core = summary["units"][0]
            self.assertEqual(core["failure_kind"], FAILURE_KIND_LIMIT_SHAPED)
            self.assertTrue(core["limit_shaped"])
            self.assertNotIn("auth_shaped", core)
            self.assertEqual(last_auth_failure_signal(paths, "codex"), {})

    def test_a_missing_binary_and_a_timeout_map_to_their_synthetic_kinds(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def missing(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise FileNotFoundError(argv[0])

            summary = self._dispatch(paths, repo, sha, contract, missing)
            self.assertEqual(summary["units"][0]["failure_kind"], FAILURE_KIND_BINARY_MISSING)

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)

            def slow(argv, **kwargs):
                if argv[0] == "git":
                    return subprocess.run(argv, **kwargs)
                raise subprocess.TimeoutExpired(argv, 1)

            summary = self._dispatch(paths, repo, sha, contract, slow, sleep=lambda _s: None)
            self.assertEqual(summary["units"][0]["failure_kind"], FAILURE_KIND_TIMEOUT)

    def test_a_later_success_clears_the_auth_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            self._dispatch(
                paths,
                repo,
                sha,
                contract,
                _runner({}),
                ignore_limit_signal=True,
            )
            self.assertEqual(last_auth_failure_signal(paths, "codex"), {})

    def test_a_fresh_auth_signal_vetoes_the_spawn_with_a_repair_card(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            runner = _runner({})
            summary = self._dispatch(paths, repo, sha, contract, runner)
            core = summary["units"][0]
            self.assertEqual(core["status"], COOLDOWN_STATUS_AUTH)
            self.assertEqual(core["failure_kind"], FAILURE_KIND_AUTH_SHAPED)
            self.assertIn("--ignore-limit-signal", core["reason"])
            self.assertEqual(core["repair_card"]["reason_code"], FAILURE_KIND_AUTH_SHAPED)
            self.assertEqual(runner.spawned, [])
            # Nothing was created for a unit that never started.
            self.assertFalse((repo.parent / f"{repo.name}-fanout-core").exists())

    def test_a_fresh_limit_signal_vetoes_the_spawn(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            atomic_write_json(
                paths.executor_limit_signals_path,
                {
                    "schema_version": "executor_limit_signals/v1",
                    "profiles": {"codex": {"last_limit_shaped_at": utc_now(), "pattern_label": "rate_limit"}},
                },
                private=True,
            )
            runner = _runner({})
            summary = self._dispatch(paths, repo, sha, contract, runner)
            self.assertEqual(summary["units"][0]["status"], COOLDOWN_STATUS_LIMIT)
            self.assertEqual(runner.spawned, [])

    def test_ignore_limit_signal_overrides_both_cooldowns(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            runner = _runner({})
            summary = self._dispatch(paths, repo, sha, contract, runner, ignore_limit_signal=True)
            self.assertEqual(summary["units"][0]["status"], "completed")
            self.assertEqual(len(runner.spawned), 1)

    def test_a_cooldown_veto_blocks_dependents_and_resumes_as_never_attempted(self) -> None:
        units = [
            {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/core/"]},
            {
                "unit_id": "docs",
                "title": "Docs",
                "owner": "codex",
                "file_scope": ["docs/"],
                "depends_on": ["core"],
            },
        ]
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, units=units)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            summary = self._dispatch(paths, repo, sha, contract, _runner({}))
            by_unit = {entry["unit_id"]: entry for entry in summary["units"]}
            self.assertEqual(by_unit["core"]["status"], COOLDOWN_STATUS_AUTH)
            self.assertEqual(by_unit["docs"]["status"], "blocked_by_dependency")
            journal = build_fanout_run_journal(summary)
            rows = {row["unit_id"]: row for row in journal["units"]}
            self.assertEqual(rows["core"]["terminal_state"], "not_attempted")
            plan = plan_fanout_resume(
                journal, order=["core", "docs"], depends_on={"core": [], "docs": ["core"]}
            )
            self.assertEqual(plan["selected_units"], ["core", "docs"])


class DispatchRecoveryChoiceTests(unittest.TestCase):
    def _setup(self, tmp: str):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, list(_UNITS)))
        return paths, repo, sha, contract

    def _dispatch(self, paths, repo, sha, contract, **kwargs):
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            runner=_runner({"codex": _FakeCompleted(1, _LIMIT_FAILURE_TEXT)}),
            readiness=_ready,
            **kwargs,
        )

    def test_report_mode_records_the_options_and_changes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            lines: list[str] = []
            summary = self._dispatch(paths, repo, sha, contract, write_line=lines.append)
            recovery = summary["failure_recovery"]
            self.assertEqual(recovery["mode"], "report")
            self.assertFalse(recovery["interactive"])
            decision = recovery["decisions"][0]
            self.assertEqual(decision["choice"], CHOICE_REPORT)
            self.assertEqual(decision["failure_kind"], FAILURE_KIND_LIMIT_SHAPED)
            self.assertEqual(len(decision["options"]), 3)
            self.assertIn("repair_card", decision)
            self.assertTrue(any("Recovery options (none taken" in line for line in lines))
            self.assertNotIn("awaiting_retry", summary["units"][0])

    def test_a_clean_run_carries_no_failure_recovery_block(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_runner({}),
                readiness=_ready,
            )
            self.assertNotIn("failure_recovery", summary)

    def test_wait_marks_the_unit_and_the_next_resume_reruns_exactly_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(paths, repo, sha, contract, on_failure="wait")
            self.assertEqual(summary["failure_recovery"]["awaiting_retry_units"], ["core"])
            core = summary["units"][0]
            self.assertTrue(core["awaiting_retry"])
            self.assertEqual(core["recovery_choice"]["choice"], CHOICE_WAIT)
            journal = build_fanout_run_journal(summary)
            row = journal["units"][0]
            self.assertTrue(row["awaiting_retry"])
            self.assertEqual(row["awaiting_retry_kind"], FAILURE_KIND_LIMIT_SHAPED)
            self.assertEqual(row["failure_class"], "transient_provider_limit")
            plan = plan_fanout_resume(journal, order=["core"], depends_on={"core": []})
            self.assertEqual(plan["selected_units"], ["core"])
            self.assertEqual(plan["decisions"][0]["action"], RESUME_RERUN_AWAITING_RETRY)

    def test_an_observed_success_is_still_skipped_by_the_resume(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = dispatch_fanout(
                paths,
                contract,
                goal_text=_GOAL,
                repo_root=repo,
                base_sha=sha,
                runner=_runner({}),
                readiness=_ready,
            )
            journal = build_fanout_run_journal(summary)
            plan = plan_fanout_resume(journal, order=["core"], depends_on={"core": []})
            self.assertEqual(plan["selected_units"], [])
            self.assertEqual(plan["held_units"], ["core"])

    def test_retarget_redispatches_under_the_chosen_owner_with_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(
                paths, repo, sha, contract, on_failure=CHOICE_RETARGET, retarget_owner="claude-code"
            )
            decision = summary["failure_recovery"]["decisions"][0]
            self.assertEqual(decision["choice"], CHOICE_RETARGET)
            self.assertEqual(decision["target_owner"], "claude-code")
            attempt = decision["attempt"]
            self.assertEqual(attempt["owner"], "claude-code")
            self.assertEqual(attempt["unit_id"], "core-retarget-claude-code")
            self.assertEqual(attempt["status"], "completed")
            self.assertEqual(attempt["retargeted_from"], {"unit_id": "core", "owner": "codex"})
            # Its own worktree, so the failed unit's directory is never reused
            # and never deleted.
            self.assertTrue((repo.parent / f"{repo.name}-fanout-core-retarget-claude-code").is_dir())
            self.assertTrue((repo.parent / f"{repo.name}-fanout-core").is_dir())

    def test_retargeting_to_the_owner_that_just_failed_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(
                paths, repo, sha, contract, on_failure=CHOICE_RETARGET, retarget_owner="codex"
            )
            decision = summary["failure_recovery"]["decisions"][0]
            self.assertEqual(decision["choice"], CHOICE_REPORT)
            self.assertIn("the owner that just failed", decision["reason"])
            self.assertNotIn("attempt", decision)

    def test_hermes_choice_dispatches_through_the_injected_lane_with_consent(self) -> None:
        calls: list[dict] = []

        def stub_hermes(**kwargs):
            calls.append(kwargs)
            return {"status": "completed", "exit_code": 0, "run_id": kwargs["run_id"]}

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(
                paths,
                repo,
                sha,
                contract,
                on_failure="hermes",
                hermes_routing={"model": "m", "provider": "p", "reasoning": "high"},
                hermes_child=stub_hermes,
            )
            decision = summary["failure_recovery"]["decisions"][0]
            self.assertEqual(decision["choice"], CHOICE_HERMES)
            self.assertIn("--confirm-dispatch", decision["consent"])
            self.assertEqual(decision["attempt"]["status"], "completed")
            self.assertEqual(decision["attempt"]["owner"], "hermes")
            self.assertEqual(len(calls), 1)
            # The child runs in the unit's own worktree, never the repo root.
            self.assertEqual(Path(calls[0]["cwd"]).name, f"{repo.name}-fanout-core")
            self.assertEqual(calls[0]["routing"]["model"], "m")
            self.assertIn("Work unit:", calls[0]["prompt"])

    def test_hermes_choice_without_routing_degrades_to_report(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            summary = self._dispatch(paths, repo, sha, contract, on_failure="hermes")
            decision = summary["failure_recovery"]["decisions"][0]
            self.assertEqual(decision["choice"], CHOICE_REPORT)
            self.assertIn("--hermes-model", decision["reason"])

    def test_the_interview_answer_drives_the_action(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            answers = iter(["3"])
            summary = self._dispatch(
                paths,
                repo,
                sha,
                contract,
                interactive=True,
                read_line=lambda _prompt: next(answers),
                write_line=lambda _line: None,
            )
            recovery = summary["failure_recovery"]
            self.assertTrue(recovery["interactive"])
            self.assertEqual(recovery["decisions"][0]["choice"], CHOICE_WAIT)
            self.assertTrue(summary["units"][0]["awaiting_retry"])

    def test_a_dry_run_neither_cools_down_nor_interviews(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            record_auth_failure_signal(
                paths, "codex", run_ref="r", unit_id="core", pattern_label="http_401"
            )
            summary = self._dispatch(paths, repo, sha, contract, dry_run=True)
            self.assertEqual(summary["units"][0]["status"], "dry_run_planned")
            self.assertNotIn("failure_recovery", summary)


_PY = shlex.quote(sys.executable)
_CHECK_FIX_COMMITTED = (
    f"{_PY} -c 'import subprocess,sys; "
    "sys.exit(subprocess.run([\"git\", \"cat-file\", \"-e\", \"HEAD:src/core/fix.txt\"]).returncode)'"
)
_FAILING_CHECK = f"{_PY} -c 'import sys; sys.exit(3)'"
_HERMES_ROUTING = {"model": "m", "provider": "p", "reasoning": "high"}


def _editing_child(status: str = "completed", exit_code: int = 0, *, also: tuple[str, ...] = ()):
    """A Hermes child stub that edits the worktree it is given, as the file-tools child would.

    It writes `src/core/fix.txt`, inside the fixture unit's `src/core/` scope,
    and each path in `also`.
    """
    calls: list[dict] = []

    def child(**kwargs):
        calls.append(kwargs)
        for name in ("src/core/fix.txt", *also):
            target = Path(kwargs["cwd"]) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixed\n", encoding="utf-8")
        return {"status": status, "exit_code": exit_code, "run_id": kwargs["run_id"]}

    child.calls = calls
    return child


def _no_edit_child(**kwargs):
    """A Hermes child stub that exits 0 having changed nothing, as a model that declined does."""
    return {"status": "completed", "exit_code": 0, "run_id": kwargs["run_id"]}


def _limit_then_real(argv, **kwargs):
    """Codex refuses on a usage limit; git and the declared checks really run."""
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    if argv[0] == sys.executable:
        return subprocess.run(argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"), text=True,
                              capture_output=True, timeout=kwargs.get("timeout"))
    return _FakeCompleted(1, _LIMIT_FAILURE_TEXT)


def _limit_after(leftover):
    """Codex does `leftover(worktree)` -- half its work, a branch switch -- then hits the limit."""
    def runner(argv, **kwargs):
        if argv[0] not in ("git", sys.executable):
            leftover(Path(kwargs["cwd"]))
        return _limit_then_real(argv, **kwargs)

    return runner


def _half_done(worktree: Path) -> None:
    """Half the work: a tracked file edited outside the scope, a new file inside it."""
    (worktree / "seed.txt").write_text("seed, edited by codex\n", encoding="utf-8")
    (worktree / "src" / "core").mkdir(parents=True, exist_ok=True)
    (worktree / "src" / "core" / "partial_from_codex.txt").write_text("half\n", encoding="utf-8")


def _secret_and_build_output(worktree: Path) -> None:
    """New files outside the scope that `.gitignore` does not cover: a secret and a build artifact."""
    (worktree / ".gitignore").write_text("build/\nnode_modules/\n", encoding="utf-8")
    _git(worktree, "add", ".gitignore")
    _git(worktree, "commit", "-q", "-m", "ignore build output")
    (worktree / ".env").write_text("OPENAI_API_KEY=fixture-not-a-key\n", encoding="utf-8")
    (worktree / "dist").mkdir()
    (worktree / "dist" / "bundle.js").write_text("bundle\n", encoding="utf-8")
    (worktree / "build").mkdir()
    (worktree / "build" / "ignored.o").write_text("object\n", encoding="utf-8")


class HermesRecoverySettlementTests(unittest.TestCase):
    """The Hermes lane's child can only edit, so the dispatcher commits and then verifies (#2108)."""

    def _setup(self, tmp: str, commands: list[str] | None = None):
        root = Path(tmp)
        paths = OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")
        repo, sha = _make_repo(root)
        # The dispatcher commits as whoever the repository says, like an executor would.
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "user.email", "t@t")
        units = [dict(unit) for unit in _UNITS]
        if commands is not None:
            units[0]["verification_commands"] = commands
        contract = write_fanout_contract(paths, build_fanout_contract(_GOAL, units))
        return paths, repo, sha, contract

    def _attempt(self, paths, repo, sha, contract, child, *, runner=_limit_then_real, **kwargs):
        summary = dispatch_fanout(
            paths, contract, goal_text=_GOAL, repo_root=repo, base_sha=sha, runner=runner,
            readiness=_ready, on_failure="hermes", hermes_routing=_HERMES_ROUTING, hermes_child=child,
            **kwargs,
        )
        (decision,) = summary["failure_recovery"]["decisions"]
        self.assertEqual(decision["choice"], CHOICE_HERMES)
        # The unit's own row keeps the failure that sent it here, whatever the
        # recovery reports, so the batch's exit code never reads it as success.
        self.assertEqual(_fanout_dispatch_exit_code(summary), 1)
        return decision["attempt"]

    def _branch(self, repo: Path, ref: str = "agent/core") -> tuple[str, list[str]]:
        head = subprocess.run(["git", "rev-parse", ref], cwd=repo, capture_output=True,
                              text=True, check=True).stdout.strip()
        changed = subprocess.run(["git", "show", "--name-only", "--format=", ref], cwd=repo,
                                 capture_output=True, text=True, check=True).stdout.split()
        return head, changed

    def test_the_child_is_asked_to_edit_and_never_to_verify_or_commit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp)
            child = _editing_child()
            attempt = self._attempt(paths, repo, sha, contract, child)
        prompt = child.calls[0]["prompt"]
        self.assertIn("Work unit: Core work", prompt)
        self.assertIn("Done means, and only means:", prompt)
        for sentence in ("run one full verification pass", "Commit your work",
                         "The work is committed on the unit branch", "fanout_unit_result/v1"):
            with self.subTest(sentence=sentence):
                self.assertNotIn(sentence, prompt)
        blocks = attempt["unit_prompt"]["blocks"]
        for name in ("head.verification_stop", "unit.commit_criterion", "tail.commit",
                     "head.unit_result_return", "head.parent_clarification"):
            with self.subTest(block=name):
                self.assertNotIn(name, blocks)

    def test_a_completed_recovery_is_committed_then_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(), run_verification=True)
            head, changed = self._branch(repo)
            parent = subprocess.run(["git", "rev-parse", "agent/core^"], cwd=repo, capture_output=True,
                                    text=True, check=True).stdout.strip()
            run_ref = f"{contract['fanout_id']}-core"
            recovery_events = [str(event["event"]) for event in
                               read_observation_events(paths, run_id=f"{run_ref}-hermes-recovery")]
            unit_events = [str(event["event"]) for event in read_observation_events(paths, run_id=run_ref)]
            roster = project_fanout_status(paths, str(contract["fanout_id"]))

        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["recovery_commit"], {
            "status": "committed", "head_sha": head, "paths": ["src/core/fix.txt"], "left_uncommitted": [],
        })
        self.assertEqual((parent, changed), (sha, ["src/core/fix.txt"]))
        # The check reads the file from HEAD, so it passes only on the commit.
        self.assertEqual(attempt["verification_status"], "passed")
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("verified", ""))
        # The checks are journaled on the recovery's own run, after the result
        # the journal requires; the unit's own run gains no observed result, so
        # a later dispatch does not skip the unit as already completed.
        self.assertEqual(recovery_events[-1], "unit_verification_observed")
        self.assertNotIn("unit_verification_observed", unit_events)
        self.assertEqual([unit["unit_id"] for unit in roster["units"]], ["core"])
        self.assertIs(roster["all_units_terminal"], True)

    def test_a_child_that_changed_nothing_is_not_verified_even_where_the_checks_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [f"{_PY} -c 'import sys; sys.exit(0)'"])
            attempt = self._attempt(paths, repo, sha, contract, _no_edit_child, run_verification=True)
            head, _changed = self._branch(repo)

        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["recovery_commit"], {
            "status": "nothing_to_commit", "head_sha": sha, "paths": [], "left_uncommitted": [],
        })
        self.assertEqual(head, sha)
        self.assertNotIn("verification_status", attempt)
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "no_changes"))

    def test_work_the_failed_attempt_left_is_committed_apart_from_the_recovery(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(),
                                    runner=_limit_after(_half_done), run_verification=True)
            recovery_head, recovery_changed = self._branch(repo)
            left_head, left_changed = self._branch(repo, "agent/core^")
            base, _ = self._branch(repo, "agent/core^^")

        # A tracked file's edit is committed wherever it is; a new file only inside the scope.
        self.assertEqual(attempt["pre_existing_commit"], {
            "status": "committed", "head_sha": left_head,
            "paths": ["seed.txt", "src/core/partial_from_codex.txt"], "left_uncommitted": [],
        })
        self.assertEqual(sorted(left_changed), ["seed.txt", "src/core/partial_from_codex.txt"])
        self.assertEqual(base, sha)
        # The recovery commit holds the child's edit and nothing the failed attempt wrote.
        self.assertEqual(attempt["recovery_commit"]["head_sha"], recovery_head)
        self.assertEqual(attempt["recovery_commit"]["paths"], ["src/core/fix.txt"])
        self.assertEqual(recovery_changed, ["src/core/fix.txt"])
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("verified", ""))

    def test_leftovers_alone_never_make_a_child_that_changed_nothing_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [f"{_PY} -c 'import sys; sys.exit(0)'"])
            attempt = self._attempt(paths, repo, sha, contract, _no_edit_child,
                                    runner=_limit_after(_half_done), run_verification=True)
            head, _changed = self._branch(repo)

        self.assertEqual((attempt["pre_existing_commit"]["status"], attempt["pre_existing_commit"]["head_sha"]),
                         ("committed", head))
        self.assertEqual(attempt["recovery_commit"], {
            "status": "nothing_to_commit", "head_sha": head, "paths": [], "left_uncommitted": [],
        })
        self.assertNotIn("verification_status", attempt)
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "no_changes"))

    def test_a_worktree_moved_off_its_branch_refuses_before_the_child(self) -> None:
        def switch_branch(worktree: Path) -> None:
            _git(worktree, "checkout", "-q", "-b", "elsewhere")
            (worktree / "scratch-notes.md").write_text("codex scratch\n", encoding="utf-8")

        child = _editing_child()
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, child,
                                    runner=_limit_after(switch_branch), run_verification=True)
            unit_branch, _ = self._branch(repo)
            elsewhere, _ = self._branch(repo, "elsewhere")

        self.assertEqual(child.calls, [])
        self.assertEqual(attempt["status"], "hermes_child_refused")
        self.assertEqual(attempt["reason_code"], "worktree_not_committable")
        self.assertEqual(attempt["pre_existing_commit"]["status"], "failed")
        self.assertEqual(attempt["pre_existing_commit"]["step"], "branch")
        self.assertEqual((unit_branch, elsewhere), (sha, sha))
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "commit_failed"))

    def test_new_files_left_outside_the_scope_refuse_before_the_child_and_are_never_committed(self) -> None:
        child = _editing_child()
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, child,
                                    runner=_limit_after(_secret_and_build_output), run_verification=True)
            tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "agent/core"], cwd=repo,
                                  capture_output=True, text=True, check=True).stdout.split()
            worktree = repo.parent / f"{repo.name}-fanout-core"
            still_there = [name for name in (".env", "dist/bundle.js") if (worktree / name).exists()]

        self.assertEqual(child.calls, [])
        self.assertEqual(attempt["status"], "hermes_child_refused")
        self.assertEqual(attempt["reason_code"], "untracked_leftovers")
        # Named, never committed, never deleted, and the ignored build output is not listed.
        self.assertEqual(attempt["pre_existing_commit"],
                         {"status": "refused", "paths": [], "left_uncommitted": [".env", "dist/bundle.js"]})
        self.assertEqual(sorted(tree), [".gitignore", "seed.txt"])
        self.assertEqual(still_there, [".env", "dist/bundle.js"])
        self.assertNotIn("fixture-not-a-key", json.dumps(attempt))
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "untracked_leftovers")
        )

    def test_a_file_the_failed_attempt_staged_outside_the_scope_is_judged_like_a_new_one(self) -> None:
        def staged_secret(worktree: Path) -> None:
            (worktree / "secret.env").write_text("TOKEN=fixture\n", encoding="utf-8")
            _git(worktree, "add", "secret.env")

        child = _editing_child()
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, child,
                                    runner=_limit_after(staged_secret), run_verification=True)
            head, _ = self._branch(repo)

        self.assertEqual(child.calls, [])
        self.assertEqual(attempt["pre_existing_commit"]["left_uncommitted"], ["secret.env"])
        self.assertEqual(head, sha)

    def _refused_move(self, target: str) -> None:
        def move_and_edit(worktree: Path) -> None:
            (worktree / target).parent.mkdir(parents=True, exist_ok=True)
            _git(worktree, "mv", "seed.txt", target)
            (worktree / target).write_text("OPENAI_API_KEY=fixture-not-a-key\n", encoding="utf-8")

        child = _editing_child()
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            # Copies too: config cannot turn rename detection back on.
            _git(repo, "config", "diff.renames", "copies")
            attempt = self._attempt(paths, repo, sha, contract, child,
                                    runner=_limit_after(move_and_edit), run_verification=True)
            head, _ = self._branch(repo)

        self.assertEqual(child.calls, [])
        self.assertEqual(attempt["reason_code"], "untracked_leftovers")
        self.assertEqual(attempt["pre_existing_commit"]["left_uncommitted"], [target])
        self.assertEqual(head, sha)

    def test_a_tracked_file_moved_out_of_the_scope_is_judged_as_a_new_file(self) -> None:
        self._refused_move(".env")

    def test_a_tracked_file_moved_into_an_out_of_scope_directory_is_judged_as_a_new_file(self) -> None:
        self._refused_move("conf/prod.env")

    def test_a_move_into_the_scope_records_both_of_its_paths(self) -> None:
        def move_in(worktree: Path) -> None:
            (worktree / "src" / "core").mkdir(parents=True, exist_ok=True)
            _git(worktree, "mv", "seed.txt", "src/core/seed.txt")

        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            _git(repo, "config", "diff.renames", "copies")
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(),
                                    runner=_limit_after(move_in), run_verification=True)

        self.assertEqual(attempt["pre_existing_commit"]["paths"], ["seed.txt", "src/core/seed.txt"])
        self.assertEqual(attempt["pre_existing_commit"]["left_uncommitted"], [])

    def test_a_name_that_is_not_utf8_is_committed_or_named_never_dropped(self) -> None:
        in_scope, out_of_scope = b"src/core/caf\xe9.txt", b"bad\xff.env"

        def child(**kwargs):
            root = os.fsencode(kwargs["cwd"])
            for name in (b"src/core/fix.txt", in_scope, out_of_scope):
                target = os.path.join(root, name)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as stream:
                    stream.write(b"fixed\n")
            return {"status": "completed", "exit_code": 0, "run_id": kwargs["run_id"]}

        with TemporaryDirectory() as tmp:
            try:
                with open(os.path.join(os.fsencode(tmp), b"probe\xff"), "wb"):
                    pass
            except (OSError, UnicodeError):
                self.skipTest("this filesystem refuses file names that are not UTF-8 (APFS does)")
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, child, run_verification=True)
            tree = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", "agent/core"], cwd=repo,
                                  capture_output=True, check=True).stdout.split(b"\0")

        self.assertIn(in_scope, tree)
        self.assertNotIn(out_of_scope, tree)
        self.assertEqual(attempt["recovery_commit"]["paths"], ["src/core/caf\ufffd.txt", "src/core/fix.txt"])
        self.assertEqual(attempt["recovery_commit"]["left_uncommitted"], ["bad\ufffd.env"])
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "out_of_scope_files")
        )

    def test_a_child_that_writes_outside_the_scope_is_not_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(also=(".env",)),
                                    run_verification=True)
            head, changed = self._branch(repo)

        self.assertEqual(attempt["recovery_commit"]["status"], "committed")
        self.assertEqual(attempt["recovery_commit"]["paths"], ["src/core/fix.txt"])
        self.assertEqual(attempt["recovery_commit"]["left_uncommitted"], [".env"])
        self.assertEqual(changed, ["src/core/fix.txt"])
        self.assertNotIn("verification_status", attempt)
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "out_of_scope_files")
        )

    def test_a_failing_check_leaves_the_recovery_failed_not_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_FAILING_CHECK])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(), run_verification=True)

        self.assertEqual(attempt["recovery_commit"]["status"], "committed")
        self.assertEqual(attempt["verification_status"], "failed")
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "verification_failed"))

    def test_without_run_verification_a_committed_recovery_is_still_not_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child())

        self.assertEqual(attempt["recovery_commit"]["status"], "committed")
        self.assertNotIn("verification_status", attempt)
        # Nothing ran and failed, so it is not `failed` either (#2461).
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]), ("unverified", "verification_not_observed")
        )

    def test_a_child_that_did_not_complete_is_neither_committed_nor_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            attempt = self._attempt(paths, repo, sha, contract, _editing_child("timed_out", 124),
                                    run_verification=True)
            head, _changed = self._branch(repo)

        self.assertNotIn("recovery_commit", attempt)
        self.assertNotIn("verification_status", attempt)
        self.assertEqual(head, sha)
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "process_not_completed")
        )

    def test_a_failed_commit_is_reported_and_nothing_is_verified(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, repo, sha, contract = self._setup(tmp, [_CHECK_FIX_COMMITTED])
            # A pre-commit hook that refuses: the commit an executor would hit too.
            hook = repo / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            hook.chmod(0o755)
            attempt = self._attempt(paths, repo, sha, contract, _editing_child(), run_verification=True)
            head, _changed = self._branch(repo)

        # The step and git's code say a hook refused, not an identity or a stage; no git output.
        self.assertEqual(attempt["recovery_commit"], {
            "status": "failed", "step": "commit", "exit_code": 1,
            "reason": "git commit did not complete in the unit worktree", "left_uncommitted": [],
        })
        self.assertNotIn("verification_status", attempt)
        self.assertEqual(head, sha)
        self.assertEqual((attempt["unit_state"], attempt["unit_state_reason"]), ("failed", "commit_failed"))


class HermesRecoveryFenceTests(unittest.TestCase):
    """The dispatcher's commit and checks run in the unit's fence, or the child is not started."""

    def _worktree(self, root: Path) -> tuple[OmhPaths, Path, str]:
        repo, sha = _make_repo(root)
        _git(repo, "config", "user.name", "t")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "worktree", "add", "-q", str(repo.parent / f"{repo.name}-fanout-core"), "-b", "agent/core", sha)
        return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes"), repo, sha

    def _recover(self, paths, repo, sha, child, *, allow_unconfined: bool):
        unit = {**_UNITS[0], "run_ref": "fanout-0123456789ab-core", "branch_suggestion": "agent/core",
                "boundary": {"file_scope": ["src/core/"]}}
        return _hermes_recovery_dispatch(
            paths, unit=unit, repo_root=repo, timeout=60, routing=_HERMES_ROUTING, hermes_child=child,
            unit_dispatch_kwargs={
                "fanout_id": "fanout-0123456789ab", "goal_text": _GOAL, "runner": signal_safe_unit_runner,
                "run_verification": False, "environment_policy": None, "base_env": None,
                "dispatch_depth": 0, "allow_unconfined": allow_unconfined, "base_sha": sha,
                "invocation_id": "invocation", "launch_gate": OwnerLaunchGate(),
                "verification_wave_width": 1, "verification_execution_gate": None,
            },
        )

    def test_the_commit_runs_inside_the_units_fence_where_the_host_has_one(self) -> None:
        unfenced_host = host_cannot_fence_fanout()
        with TemporaryDirectory() as tmp:
            paths, repo, sha = self._worktree(Path(tmp).resolve())
            attempt = self._recover(paths, repo, sha, _editing_child(), allow_unconfined=unfenced_host)
            branch_head = subprocess.run(["git", "rev-parse", "agent/core"], cwd=repo, capture_output=True,
                                         text=True, check=True).stdout.strip()

        self.assertIs(attempt["filesystem_confinement"]["enforced"], not unfenced_host)
        self.assertEqual(attempt["recovery_commit"], {
            "status": "committed", "head_sha": branch_head, "paths": ["src/core/fix.txt"], "left_uncommitted": [],
        })
        self.assertNotEqual(branch_head, sha)

    def test_no_provable_fence_refuses_before_the_child_starts(self) -> None:
        child = _editing_child()
        with TemporaryDirectory() as tmp:
            paths, repo, sha = self._worktree(Path(tmp).resolve())
            with mock.patch("omh.coding.fanout_confinement.backend_available", return_value=False):
                attempt = self._recover(paths, repo, sha, child, allow_unconfined=False)

        self.assertEqual(child.calls, [])
        self.assertEqual(attempt["status"], "hermes_child_refused")
        self.assertEqual(attempt["reason_code"], "filesystem_confinement_unavailable")
        self.assertEqual(
            (attempt["unit_state"], attempt["unit_state_reason"]),
            ("permission_blocked", "filesystem_confinement_unavailable"),
        )


class FailureRecoveryCliTests(unittest.TestCase):
    def _prepared(self, tmp: str) -> tuple[list[str], Path, Path, str]:
        root = Path(tmp)
        base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
        repo, _sha = _make_repo(root)
        goal_file = root / "goal.txt"
        goal_file.write_text(_GOAL, encoding="utf-8")
        units_file = root / "units.json"
        # Two units: a one-unit split is redirected to `omh coding run`, which
        # is a different (single-run) entry into the same engine.
        units_file.write_text(json.dumps(_CLI_UNITS), encoding="utf-8")
        status, stdout, stderr = run_cli(
            base
            + [
                "coding",
                "fanout",
                "prepare",
                "--goal",
                *_GOAL.split(),
                "--units",
                str(units_file),
                "--record",
            ]
        )
        self.assertEqual(status, 0, stderr)
        return base, repo, goal_file, json.loads(stdout)["fanout_id"]

    def test_an_unknown_on_failure_value_is_refused_before_anything_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            base, repo, goal_file, fanout_id = self._prepared(tmp)
            status, _stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(goal_file),
                    "--repo-root",
                    str(repo),
                    "--on-failure",
                    "switch-owner",
                ]
            )
            self.assertEqual(status, 2)
            self.assertIn("switch-owner", stderr)

    def test_an_unknown_retarget_owner_is_refused_by_name(self) -> None:
        with TemporaryDirectory() as tmp:
            base, repo, goal_file, fanout_id = self._prepared(tmp)
            status, _stdout, stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(goal_file),
                    "--repo-root",
                    str(repo),
                    "--on-failure",
                    "retarget:not-an-owner",
                ]
            )
            self.assertEqual(status, 2)
            self.assertIn("not-an-owner", stderr)

    def test_a_non_tty_dispatch_never_prompts_and_reports_the_options(self) -> None:
        with TemporaryDirectory() as tmp:
            base, repo, goal_file, fanout_id = self._prepared(tmp)
            status, stdout, _stderr = run_cli(
                base
                + [
                    "coding",
                    "fanout",
                    "dispatch",
                    fanout_id,
                    "--goal-file",
                    str(goal_file),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ]
            )
            self.assertEqual(status, 0, stdout)
            summary = json.loads(stdout)
            self.assertNotIn("failure_recovery", summary)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
