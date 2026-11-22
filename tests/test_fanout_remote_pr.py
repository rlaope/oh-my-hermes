"""The opt-in remote PR lane, refused: double opt-in, hook and URL grammar.

The lane itself is not built. Importing a PR head needs a dispatcher network
`git fetch`, INVARIANT 3 has no approved exception for one, and the scoped
exception design.md §6 asks for was never approved. So these tests hold the
release to the honest alternative:

* all four combinations of the two opt-ins, with exactly one -- both false --
  leaving the local lane, and every other one answering one closed reason;
* a dispatcher that refuses a unit which asked for the lane before any probe,
  worktree or child, and leaves ordinary local dispatches alone;
* the exact stdout URL grammar §6 step 4 specifies, which a later PR reuses:
  documented shapes accepted, everything else -- wrong host, repo, port, query,
  fragment, userinfo, escape, oversize -- rejected;
* no subprocess on any refused path: every refusal runs with `Popen` and
  friends patched to fail the test if they are ever called.

Where a test names a cloud CLI it is a name in a toml file; no vendor CLI is
installed, none is launched, and no socket is opened anywhere in this module.
"""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_presets import get_preset  # noqa: E402
from omh.coding.fanout import build_fanout_contract  # noqa: E402
from omh.coding.fanout_artifacts import write_fanout_contract  # noqa: E402
from omh.coding.fanout_dispatch import dispatch_fanout  # noqa: E402
from omh.coding.fanout_remote_pr import (  # noqa: E402
    LANE_LOCAL,
    LANE_REFUSED,
    MAX_URL_BYTES,
    REFUSAL_REMOTE_PR_NOT_AVAILABLE,
    REMOTE_PR_CLAIM_BOUNDARY,
    decide_lane_kind,
    parse_pull_request_url,
    parse_session_url,
    plan_remote_pr_dispatch,
)
from omh.coding.user_executors import load_user_executors  # noqa: E402
from omh.system.paths import OmhPaths  # noqa: E402

_GOAL = "hand one bounded unit to the cloud lane"

_SESSION_ID = "0123456789abcdef0123456789abcdef"
_SESSION_URL = f"https://app.devin.ai/sessions/{_SESSION_ID}"
_PR_URL = "https://github.com/khope-sionic/oh-my-hermes/pull/1"

# A fake harness CLI that commits, so the local lane stays provably unaffected
# by the refusal hook. It is a script on a temporary PATH, never a vendor CLI.
_FAKE_CLI = '''#!{python}
import pathlib
import subprocess
import sys

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("fake-agent 2.3.4")
    raise SystemExit(0)
pathlib.Path("agent_output.txt").write_text("worked\\n", encoding="utf-8")
subprocess.run(["git", "add", "agent_output.txt"], check=True)
subprocess.run(
    ["git", "-c", "user.name=fake-agent", "-c", "user.email=fake@example.test",
     "commit", "-q", "-m", "agent: unit work"],
    check=True,
)
print("done")
'''


def _git(repo: Path, *argv: str) -> str:
    completed = subprocess.run(
        ["git", *argv], cwd=str(repo), check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _make_repo(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "seed.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    return repo, _git(repo, "rev-parse", "HEAD")


def _bin_dir(root: Path, name: str) -> Path:
    directory = root / f"bin-{name}"
    directory.mkdir()
    script = directory / name
    script.write_text(_FAKE_CLI.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o755)
    return directory


def _home(root: Path, toml: str) -> OmhPaths:
    """A disposable OMH home whose executor file is `toml`, verbatim."""
    home = root / ".omh"
    routing = home / "routing"
    routing.mkdir(parents=True)
    (routing / "executors.toml").write_text(toml, encoding="utf-8")
    return OmhPaths(omh_home=home, hermes_home=root / ".hermes")


_DEVIN_REMOTE_TOML = (
    "schema_version = 1\n\n"
    "[executors.devin]\n"
    'preset = "devin"\n'
    "remote_pr = true\n"
)

_LOCAL_TOML = (
    "schema_version = 1\n\n"
    "[executors.my-agent]\n"
    'label = "my-agent fake"\n'
    'argv = ["my-agent", "run", "--", "{prompt}"]\n'
    'version = ["my-agent", "--version"]\n'
)


def _unit(owner: str) -> dict[str, object]:
    return {
        "unit_id": "core",
        "title": "Core work",
        "owner": owner,
        "file_scope": ["src/"],
    }


def _no_process() -> ExitStack:
    """`Popen`/`run`/`call`/`spawn` patched to fail the test if reached.

    A refusal that spawns anything -- the cloud CLI, a readiness probe, a git
    worktree command -- is exactly the failure this suite must catch, so each
    is an assertion rather than a stub.
    """
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a refused executor lane must not start a process")

    stack = ExitStack()
    targets = [
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    ]
    # Windows has neither; patching an absent attribute raises mid-loop and
    # leaked every patch entered before it into the rest of the shard.
    targets.extend(f"os.{name}" for name in ("posix_spawn", "fork") if hasattr(os, name))
    try:
        for target in targets:
            stack.enter_context(mock.patch(target, side_effect=forbidden))
    except BaseException:
        stack.close()
        raise
    return stack


class LaneDecisionTests(unittest.TestCase):
    """Four combinations, one local answer, one closed refusal."""

    def test_both_opt_ins_false_is_the_local_lane(self) -> None:
        with _no_process():
            decision = decide_lane_kind(entry_remote_pr=False, allow_remote_pr=False)
        self.assertEqual(decision.lane, LANE_LOCAL)
        self.assertFalse(decision.refused)
        self.assertEqual(decision.reason, "")
        self.assertFalse(decision.would_use_remote_pr)

    def test_a_declared_entry_without_the_flag_is_refused(self) -> None:
        with _no_process():
            decision = decide_lane_kind(entry_remote_pr=True, allow_remote_pr=False)
        self.assertEqual(decision.lane, LANE_REFUSED)
        self.assertTrue(decision.refused)
        self.assertEqual(decision.reason, REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        # No silent downgrade: the entry asked for a PR, so nothing runs locally.
        self.assertNotEqual(decision.lane, LANE_LOCAL)
        self.assertFalse(decision.would_use_remote_pr)

    def test_the_flag_without_a_declared_entry_is_refused(self) -> None:
        with _no_process():
            decision = decide_lane_kind(entry_remote_pr=False, allow_remote_pr=True)
        self.assertEqual(decision.lane, LANE_REFUSED)
        self.assertEqual(decision.reason, REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        self.assertTrue(decision.allow_remote_pr)
        self.assertFalse(decision.entry_remote_pr)

    def test_both_opt_ins_are_refused_because_the_lane_is_absent(self) -> None:
        with _no_process():
            decision = decide_lane_kind(entry_remote_pr=True, allow_remote_pr=True)
        self.assertEqual(decision.lane, LANE_REFUSED)
        self.assertEqual(decision.reason, REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        self.assertTrue(decision.would_use_remote_pr)
        # The refusal says the lane is missing, not that the request was wrong.
        self.assertEqual(decision.claim_boundary, REMOTE_PR_CLAIM_BOUNDARY)
        self.assertIn("not implemented pending a policy decision", decision.claim_boundary)

    def test_a_truthy_non_boolean_is_not_consent(self) -> None:
        for value in ("true", 1, [1], {"remote_pr": True}):
            with self.subTest(value=value):
                with _no_process():
                    decision = decide_lane_kind(entry_remote_pr=value, allow_remote_pr=False)
                self.assertEqual(decision.lane, LANE_LOCAL, value)
                with _no_process():
                    flagged = decide_lane_kind(entry_remote_pr=False, allow_remote_pr=value)
                self.assertEqual(flagged.lane, LANE_LOCAL, value)

    def test_the_claim_boundary_names_every_absent_effect(self) -> None:
        with _no_process():
            boundary = decide_lane_kind(
                entry_remote_pr=True, allow_remote_pr=True
            ).claim_boundary
        for absent in (
            "no cloud executor was launched",
            "no session or pull request was observed",
            "no remote ref was fetched",
            "no commit was imported",
            "OMH opened no socket",
        ):
            self.assertIn(absent, boundary)


class BatchRefusalTests(unittest.TestCase):
    """The batch projection the dispatcher hands to the hook."""

    def test_an_all_local_batch_has_no_refusal(self) -> None:
        with _no_process():
            refusal = plan_remote_pr_dispatch(
                entry_remote_pr_by_unit={"core": False, "docs": False},
                allow_remote_pr=False,
            )
        self.assertIsNone(refusal)

    def test_a_declared_unit_refuses_the_batch_and_names_it(self) -> None:
        with _no_process():
            refusal = plan_remote_pr_dispatch(
                entry_remote_pr_by_unit={"core": False, "docs": True},
                allow_remote_pr=False,
            )
        assert refusal is not None
        self.assertEqual(refusal.reason, REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        self.assertEqual(refusal.remote_pr_declared_unit_ids, ("docs",))
        self.assertEqual(refusal.refused_unit_ids, ("core", "docs"))

    def test_the_flag_alone_refuses_even_with_no_declared_unit(self) -> None:
        with _no_process():
            refusal = plan_remote_pr_dispatch(
                entry_remote_pr_by_unit={"core": False}, allow_remote_pr=True
            )
        # §6 step 1: a flag with zero eligible lanes is an error, not a no-op.
        assert refusal is not None
        self.assertEqual(refusal.remote_pr_declared_unit_ids, ())
        self.assertEqual(refusal.refused_unit_ids, ("core",))
        self.assertTrue(refusal.allow_remote_pr)

    def test_a_truthy_non_boolean_flag_does_not_refuse(self) -> None:
        with _no_process():
            refusal = plan_remote_pr_dispatch(
                entry_remote_pr_by_unit={"core": False}, allow_remote_pr="yes"
            )
        self.assertIsNone(refusal)


class SessionUrlTests(unittest.TestCase):
    """`https://app.devin.ai/sessions/<id>`, and nothing near it."""

    def test_the_two_documented_id_shapes_are_accepted(self) -> None:
        for session_id in (_SESSION_ID, f"devin-{_SESSION_ID}"):
            with self.subTest(session_id=session_id):
                self.assertEqual(
                    parse_session_url(f"https://app.devin.ai/sessions/{session_id}"),
                    f"https://app.devin.ai/sessions/{session_id}",
                )

    def test_the_returned_url_is_rebuilt_not_echoed(self) -> None:
        token = _SESSION_URL
        parsed = parse_session_url(token)
        self.assertEqual(parsed, _SESSION_URL)
        self.assertIsInstance(parsed, str)

    def test_shapes_that_are_not_the_lane_are_rejected(self) -> None:
        rejected = {
            # Wrong host, subdomain, suffix, scheme.
            "host": (
                f"http://app.devin.ai/sessions/{_SESSION_ID}",
                f"https://app.devin.ai.evil.test/sessions/{_SESSION_ID}",
                f"https://evil.test/app.devin.ai/sessions/{_SESSION_ID}",
                f"https://devin.ai/sessions/{_SESSION_ID}",
                f"https://app.devin.ai:443/sessions/{_SESSION_ID}",
            ),
            # Id grammar: length, alphabet, case, prefix.
            "id": (
                "https://app.devin.ai/sessions/" + "0" * 31,
                "https://app.devin.ai/sessions/" + "0" * 33,
                "https://app.devin.ai/sessions/" + "A" * 32,
                f"https://app.devin.ai/sessions/devin-{_SESSION_ID[:-1]}",
                "https://app.devin.ai/sessions/" + "0123456789abcdef-0123456789abcdef",
                "https://app.devin.ai/sessions/",
                "https://app.devin.ai/sessions",
            ),
            # Userinfo, query, fragment, trailing path, escape, whitespace.
            "suffix": (
                f"https://user@app.devin.ai/sessions/{_SESSION_ID}",
                f"https://app.devin.ai/sessions/{_SESSION_ID}?next=1",
                f"https://app.devin.ai/sessions/{_SESSION_ID}#top",
                f"https://app.devin.ai/sessions/{_SESSION_ID}/",
                f"https://app.devin.ai/sessions/{_SESSION_ID}/events",
                f"https://app.devin.ai/sessions/{_SESSION_ID[:8]}%2f{_SESSION_ID[8:]}",
                f" {_SESSION_ID} ",
                f"https://app.devin.ai/sessions/{_SESSION_ID}\n",
                f"https://app.devin.ai/sessions/{_SESSION_ID}x",
            ),
        }
        for family, tokens in rejected.items():
            for token in tokens:
                with self.subTest(family=family, token=token):
                    self.assertIsNone(parse_session_url(token))

    def test_an_oversize_token_is_rejected_before_matching(self) -> None:
        oversize = _SESSION_URL + "a" * MAX_URL_BYTES
        self.assertGreater(len(oversize.encode("utf-8")), MAX_URL_BYTES)
        self.assertIsNone(parse_session_url(oversize))

    def test_non_strings_are_not_urls(self) -> None:
        for value in (None, 1, b"https://app.devin.ai/sessions/" + _SESSION_ID.encode()):
            with self.subTest(value=value):
                self.assertIsNone(parse_session_url(value))


class PullRequestUrlTests(unittest.TestCase):
    """`https://github.com/<owner>/<repo>/pull/<n>` for the trusted identity."""

    OWNER = "khope-sionic"
    REPO = "oh-my-hermes"

    def test_the_documented_shape_is_accepted(self) -> None:
        self.assertEqual(
            parse_pull_request_url(_PR_URL, owner=self.OWNER, repository=self.REPO),
            (1, _PR_URL),
        )

    def test_the_number_bound_is_ten_digits(self) -> None:
        self.assertEqual(
            parse_pull_request_url(
                f"https://github.com/{self.OWNER}/{self.REPO}/pull/9999999999",
                owner=self.OWNER,
                repository=self.REPO,
            ),
            (9999999999, f"https://github.com/{self.OWNER}/{self.REPO}/pull/9999999999"),
        )
        for number in ("0", "01", "10000000000", "1.0", "-1", "1a", ""):
            with self.subTest(number=number):
                self.assertIsNone(
                    parse_pull_request_url(
                        f"https://github.com/{self.OWNER}/{self.REPO}/pull/{number}",
                        owner=self.OWNER,
                        repository=self.REPO,
                    )
                )

    def test_a_different_repository_is_refused(self) -> None:
        for token in (
            "https://github.com/someone-else/oh-my-hermes/pull/1",
            "https://github.com/khope-sionic/another-repo/pull/1",
            "https://github.com/khope-sionic/pull/1",
        ):
            with self.subTest(token=token):
                self.assertIsNone(
                    parse_pull_request_url(token, owner=self.OWNER, repository=self.REPO)
                )

    def test_the_canonical_url_uses_the_trusted_identity(self) -> None:
        # GitHub's namespace is case-insensitive; the stored URL is the
        # operator's spelling so output can never choose a fetch target.
        parsed = parse_pull_request_url(
            "https://github.com/Khope-Sionic/OH-MY-HERMES/pull/7",
            owner=self.OWNER,
            repository=self.REPO,
        )
        self.assertEqual(
            parsed, (7, f"https://github.com/{self.OWNER}/{self.REPO}/pull/7")
        )

    def test_shapes_that_are_not_a_pull_request_are_rejected(self) -> None:
        base = f"https://github.com/{self.OWNER}/{self.REPO}"
        rejected = {
            "host": (
                f"http://github.com/{self.OWNER}/{self.REPO}/pull/1",
                f"https://github.com.evil.test/{self.OWNER}/{self.REPO}/pull/1",
                f"https://api.github.com/{self.OWNER}/{self.REPO}/pull/1",
                f"https://github.com:443/{self.OWNER}/{self.REPO}/pull/1",
                f"https://git@github.com/{self.OWNER}/{self.REPO}/pull/1",
            ),
            "path": (
                f"{base}/pull",
                f"{base}/pull/",
                f"{base}/pull/1/",
                f"{base}/pull/1/files",
                f"{base}/pull/1/commits",
                f"{base}/issues/1",
                f"{base}/pull/1#discussion",
                f"{base}/pull/1?diff=split",
                f"{base}/pull/1%2f..%2f2",
                f"{base}/pull/1\n",
                f" {base}/pull/1",
                f"git@{base}/pull/1",
            ),
            "grammar": (
                "refs/pull/1/head",
                "pull/1",
                "https://github.com//oh-my-hermes/pull/1",
                f"https://github.com/{self.OWNER}/../pull/1",
            ),
        }
        for family, tokens in rejected.items():
            for token in tokens:
                with self.subTest(family=family, token=token):
                    self.assertIsNone(
                        parse_pull_request_url(token, owner=self.OWNER, repository=self.REPO)
                    )

    def test_an_oversize_token_is_rejected(self) -> None:
        token = f"{_PR_URL}?" + "a" * MAX_URL_BYTES
        self.assertIsNone(
            parse_pull_request_url(token, owner=self.OWNER, repository=self.REPO)
        )

    def test_an_untrusted_identity_is_not_a_target(self) -> None:
        for owner, repository in (
            ("", self.REPO),
            (self.OWNER, ""),
            ("owner name", self.REPO),
            (self.OWNER, "repo/../other"),
            (None, self.REPO),
            (self.OWNER, 7),
        ):
            with self.subTest(owner=owner, repository=repository):
                self.assertIsNone(
                    parse_pull_request_url(_PR_URL, owner=owner, repository=repository)
                )


class DispatchRefusalTests(unittest.TestCase):
    """The hook: refused before a probe, a worktree or a child."""

    def _prepare(self, paths: OmhPaths, owner: str) -> tuple[dict, Path, str]:
        """Contract, repository and base sha, all built before any patch.

        The repository is real git work, so it happens outside the
        `_no_process()` block: the patch must only span the dispatch itself.
        """
        root = Path(paths.omh_home).parent
        registry = load_user_executors(paths.omh_home)
        contract = write_fanout_contract(
            paths, build_fanout_contract(_GOAL, [_unit(owner)], registry=registry)
        )
        repo, sha = _make_repo(root)
        return contract, repo, sha

    # Exercise the remote-policy refusal even on a host that would stop at the platform gate.
    @mock.patch("omh.coding.user_executors.USER_EXECUTOR_LAUNCH_SUPPORTED", True)
    def _run(
        self, paths: OmhPaths, contract: dict, repo: Path, sha: str, **kwargs
    ) -> dict:
        return dispatch_fanout(
            paths,
            contract,
            goal_text=_GOAL,
            repo_root=repo,
            base_sha=sha,
            env=dict(os.environ),
            **kwargs,
        )

    def test_unit_gate_independent_of_batch_selection(self):
        # Recovery reaches unit dispatch without repeating the batch gate.
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), _DEVIN_REMOTE_TOML)
            contract, repo, sha = self._prepare(paths, "devin")
            readiness = mock.Mock(return_value={"status": "blocked"})
            with mock.patch("omh.coding.fanout_dispatch._remote_pr_lane_refusal", return_value=None):
                unit = self._run(paths, contract, repo, sha, readiness=readiness)["units"][0]
        self.assertEqual(unit["reason"], REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        readiness.assert_not_called()

    def test_rendered_model_switch_refused_without_a_worker(self):
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), _LOCAL_TOML + '\nmodel = ["--model", "{model}"]\n')
            contract, repo, sha = self._prepare(paths, "my-agent")
            for token in ("--cloud", "--cloud=true"):
                with self.subTest(token=token), mock.patch(
                        "omh.coding.fanout_dispatch._dispatch_model_preference", return_value=token):
                    unit = self._run(paths, contract, repo, sha, dry_run=True,
                                     readiness=lambda *a, **k: {"status": "ready"})["units"][0]
                    self.assertEqual(unit.get("reason"), REFUSAL_REMOTE_PR_NOT_AVAILABLE)
                    self.assertNotIn("planned_argv", unit)

    def test_a_declared_remote_pr_unit_is_refused_before_any_child(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, _DEVIN_REMOTE_TOML)
            contract, repo, sha = self._prepare(paths, "devin")
            with _no_process():
                summary = self._run(paths, contract, repo, sha)
            worktree = repo.parent / "repo-fanout-core"
        self.assertTrue(summary["refused"], summary)
        self.assertEqual(summary["refusal_reason"], REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        self.assertEqual(summary["units"], [], "nothing ran, so nothing is reported as run")
        self.assertEqual(summary["remote_pr"]["declared_unit_ids"], ["core"])
        self.assertFalse(summary["remote_pr"]["allow_remote_pr"])
        self.assertIn("not implemented pending a policy decision", summary["remote_pr"]["claim_boundary"])
        self.assertFalse(worktree.exists(), "a refused unit never allocates a worktree")

    def test_the_flag_alone_is_refused_with_no_eligible_unit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, _LOCAL_TOML)
            contract, repo, sha = self._prepare(paths, "my-agent")
            with _no_process():
                summary = self._run(paths, contract, repo, sha, allow_remote_pr=True)
            worktree = repo.parent / "repo-fanout-core"
        self.assertTrue(summary["refused"], summary)
        self.assertEqual(summary["refusal_reason"], REFUSAL_REMOTE_PR_NOT_AVAILABLE)
        self.assertEqual(summary["remote_pr"]["declared_unit_ids"], [])
        self.assertEqual(summary["remote_pr"]["refused_unit_ids"], ["core"])
        self.assertFalse(worktree.exists())

    def test_both_opt_ins_are_refused_and_the_lane_is_named(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, _DEVIN_REMOTE_TOML)
            contract, repo, sha = self._prepare(paths, "devin")
            with _no_process():
                summary = self._run(paths, contract, repo, sha, allow_remote_pr=True)
        self.assertTrue(summary["refused"], summary)
        self.assertTrue(summary["remote_pr"]["allow_remote_pr"])
        self.assertEqual(summary["remote_pr"]["declared_unit_ids"], ["core"])
        self.assertIn("no cloud executor was launched", summary["reason"])
        # No stdout, no transcript, no URL: a refusal carries none of them.
        self.assertNotIn("stdout", summary)
        self.assertNotIn("output", summary)
        self.assertNotIn("session_url", summary["remote_pr"])

    def test_a_dry_run_is_refused_rather_than_planned_as_a_submit(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _home(root, _DEVIN_REMOTE_TOML)
            contract, repo, sha = self._prepare(paths, "devin")
            with _no_process():
                summary = self._run(paths, contract, repo, sha, dry_run=True)
        self.assertTrue(summary["refused"], summary)
        self.assertTrue(summary["dry_run"])
        self.assertEqual(summary["units"], [])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_an_unselected_remote_unit_does_not_refuse_the_batch(self) -> None:
        # The selection is the invocation's own scope: a unit that asked for
        # the lane but is not selected keeps the ordinary local path.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = _bin_dir(root, "my-agent")
            paths = _home(
                root,
                _DEVIN_REMOTE_TOML
                + "\n[executors.my-agent]\n"
                + 'argv = ["my-agent", "run", "--", "{prompt}"]\n'
                + 'version = ["my-agent", "--version"]\n',
            )
            registry = load_user_executors(paths.omh_home)
            contract = write_fanout_contract(
                paths,
                build_fanout_contract(
                    _GOAL,
                    [
                        _unit("my-agent"),
                        {**_unit("devin"), "unit_id": "cloud", "file_scope": ["docs/"]},
                    ],
                    registry=registry,
                ),
            )
            environment = {
                **os.environ,
                "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            repo, sha = _make_repo(root)
            with mock.patch.dict(os.environ, environment):
                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    only_units=["core"],
                    env=environment,
                )
            units = {str(entry["unit_id"]): entry for entry in summary["units"]}
        self.assertFalse(summary.get("refused", False), summary)
        self.assertEqual(units["core"]["status"], "completed", units["core"])
        self.assertEqual(units["cloud"]["status"], "not_selected", units["cloud"])

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_local_batch_with_both_opt_ins_off_runs_as_before(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = _bin_dir(root, "my-agent")
            paths = _home(root, _LOCAL_TOML)
            registry = load_user_executors(paths.omh_home)
            contract = write_fanout_contract(
                paths, build_fanout_contract(_GOAL, [_unit("my-agent")], registry=registry)
            )
            environment = {
                **os.environ,
                "PATH": f"{binaries}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            repo, sha = _make_repo(root)
            with mock.patch.dict(os.environ, environment):
                summary = dispatch_fanout(
                    paths,
                    contract,
                    goal_text=_GOAL,
                    repo_root=repo,
                    base_sha=sha,
                    env=environment,
                )
            unit = summary["units"][0]
            head = _git(repo.parent / "repo-fanout-core", "rev-parse", "HEAD")
        self.assertFalse(summary.get("refused", False), summary)
        self.assertEqual(unit["status"], "completed", unit)
        self.assertNotEqual(head, sha)
        self.assertNotIn("remote_pr", unit)


class PresetSurfaceTests(unittest.TestCase):
    """The preset the lane would use stays declared-but-not-enabled for cloud."""

    def test_the_devin_preset_has_a_remote_adapter_and_no_cloud_argv(self) -> None:
        preset = get_preset("devin")
        assert preset is not None
        self.assertEqual(preset.remote_adapter, "devin_cloud_v1")
        # Opt-in is not the default, and the local argv never carries --cloud.
        self.assertFalse(getattr(preset, "remote_pr", False))
        self.assertNotIn("--cloud", preset.argv)

    def test_a_custom_entry_cannot_declare_a_cloud_lane(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(
                Path(tmp),
                "schema_version = 1\n\n"
                "[executors.my-agent]\n"
                'argv = ["my-agent", "{prompt}"]\n'
                "remote_pr = true\n",
            )
            registry = load_user_executors(paths.omh_home)
        self.assertNotIn("my-agent", registry.entries)
        self.assertEqual(
            [issue.reason for issue in registry.issues if issue.field == "remote_pr"],
            ["remote_pr_unsupported"],
        )


if __name__ == "__main__":
    unittest.main()
