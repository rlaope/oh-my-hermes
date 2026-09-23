"""The readiness probe reports every PATH resolution, pinned to no version.

Users update codex and claude on their own cadence and through more than one
installer, so binaries of different versions routinely coexist on PATH.
Observed live: a stale npm codex 0.144.5 resolved first and probed "ready"
while the standalone 0.145.0 the auth session actually required sat one PATH
entry later -- `shutil.which` answers only "what will run", so the newer
install was invisible and the dispatch failed mid-flight.

The structural rule these pin: OMH never compares an executor version against
an expectation of its own. It observes what each resolution prints and says
when the binary that will run is not the only one installed.
"""

from __future__ import annotations

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()
from omh.coding.executor_readiness import (
    EXECUTOR_VERSION_POLICY,
    _COMMANDS,
    _executor_readiness_contract_cached,
    _run_probe,
    executor_readiness_contract,
    negotiate_session_capability,
)
from omh.coding.fanout_executor_sessions import bounded_session_probe
from omh.coding.fanout_dispatch import OMO_RUNTIME_HOST_CANDIDATES, signal_safe_unit_runner
from omh.coding.fanout_confinement import _resolve_executables


def _fake_binary(directory: str, name: str, version: str) -> Path:
    path = Path(directory) / name
    path.write_text(f"#!/bin/sh\necho 'codex-cli {version}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@requires_posix
class PathResolutionReportTests(unittest.TestCase):
    def _probe(self, path_value: str) -> dict:
        with patch.dict(os.environ, {"PATH": path_value}):
            return _run_probe(dict(executor_readiness_contract("codex")))

    def test_a_stale_binary_shadowing_a_newer_one_is_reported(self) -> None:
        # The live failure, reproduced: first-on-PATH is old, newer sits behind.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.144.5")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))

            self.assertTrue(result["shadowed"])
            versions = [row["observed_version"] for row in result["path_resolutions"]]
            self.assertEqual(versions, ["codex-cli 0.144.5", "codex-cli 0.145.0"])
            # The stale one is still what runs, so status stays honest...
            self.assertEqual(result["status"], "ready")
            # ...and the summary names the alternative instead of hiding it.
            self.assertIn("0.145.0", result["summary"])
            self.assertIn("PATH also resolves", result["summary"])

    def test_a_single_binary_reports_no_shadow(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "0.145.0")
            result = self._probe(only)
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)
            self.assertNotIn("PATH also resolves", result["summary"])

    def test_a_symlink_to_the_same_binary_is_not_a_conflict(self) -> None:
        # Dedup is by real path: standalone installs symlink through a
        # `current` pointer, and a chain to one binary is one binary.
        with TemporaryDirectory() as real_dir, TemporaryDirectory() as link_dir:
            real = _fake_binary(real_dir, "codex", "0.145.0")
            (Path(link_dir) / "codex").symlink_to(real)
            result = self._probe(os.pathsep.join([link_dir, real_dir]))
            self.assertFalse(result["shadowed"])
            self.assertEqual(len(result["path_resolutions"]), 1)

    def test_a_version_manager_shim_is_probed_through_its_path_identity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "mise"
            target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            target.chmod(target.stat().st_mode | stat.S_IEXEC)
            shim = root / "claude"
            shim.symlink_to(target)

            def probe(argv: list[str], **_kwargs: object) -> tuple[bytes | None, str]:
                if argv[0] != str(shim):
                    return None, "wrong_launch_identity"
                output = (
                    b"1.2.3 (Claude Code)\n"
                    if argv[1:] == ["--version"]
                    else b"--output-format stream-json --verbose --resume\n"
                )
                return output, "observed"

            with patch("omh.coding.executor_readiness.bounded_session_probe", side_effect=probe):
                capability = negotiate_session_capability(
                    "claude-code", "claude", env={"PATH": str(root)}
                )

            self.assertIsNotNone(capability)
            assert capability is not None
            self.assertEqual(capability.protocol, "claude_stream_json")
            self.assertEqual(capability.binary_identity.launch_path, str(shim))
            self.assertEqual(capability.binary_identity.resolved_path, str(target.resolve()))
            self.assertEqual(
                _resolve_executables((("claude", "--version"),), {"PATH": str(root)}),
                {"claude": str(shim)},
            )

    def test_retargeted_shim_is_refused_at_the_runner_spawn_boundary(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted = _fake_binary(temporary, "trusted", "1.2.3")
            marker = root / "spawned"
            replacement = root / "replacement"
            replacement.write_text(
                f"#!/bin/sh\nprintf spawned > {marker}\n",
                encoding="utf-8",
            )
            replacement.chmod(replacement.stat().st_mode | stat.S_IEXEC)
            shim = root / "codex"
            shim.symlink_to(trusted)

            with patch(
                "omh.coding.executor_readiness.bounded_session_probe",
                side_effect=((b"1.2.3\n", "observed"), (b"--json resume\n", "observed")),
            ):
                capability = negotiate_session_capability("codex", "codex", env={"PATH": str(root)})
            self.assertIsNotNone(capability)
            assert capability is not None

            def retarget_then_spawn(spawn):
                shim.unlink()
                shim.symlink_to(replacement)
                return spawn()

            with self.assertRaisesRegex(RuntimeError, "binary identity changed"):
                signal_safe_unit_runner(
                    (str(shim),),
                    env={"PATH": str(root)},
                    expected_binary_identity=capability.binary_identity,
                    launch=retarget_then_spawn,
                )

            self.assertFalse(marker.exists())

    def test_negotiation_executes_verified_bytes_when_shim_changes_at_probe(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted = root / "trusted"
            trusted.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = --version ]; then printf '1.2.3\\n'; "
                "else printf '%s\\n' '--json resume'; fi\n",
                encoding="utf-8",
            )
            trusted.chmod(0o755)
            marker = root / "probe-escaped"
            replacement = root / "replacement"
            replacement.write_text(
                "#!/bin/sh\n"
                f"printf escaped > {marker}\n"
                "if [ \"$1\" = --version ]; then printf '1.2.3\\n'; "
                "else printf '%s\\n' '--json resume'; fi\n",
                encoding="utf-8",
            )
            replacement.chmod(0o755)
            shim = root / "codex"
            shim.symlink_to(trusted)
            calls = 0

            def retarget_at_probe(argv: list[str], **kwargs: object) -> tuple[bytes | None, str]:
                nonlocal calls
                if calls == 0:
                    shim.unlink()
                    shim.symlink_to(replacement)
                calls += 1
                return bounded_session_probe(argv, **kwargs)

            with patch(
                "omh.coding.executor_readiness.bounded_session_probe",
                side_effect=retarget_at_probe,
            ):
                capability = negotiate_session_capability(
                    "codex", "codex", env={"PATH": str(root)}
                )

            self.assertIsNotNone(capability)
            assert capability is not None
            self.assertEqual(capability.protocol, "codex_exec_json")
            self.assertFalse(marker.exists())

    def test_runner_executes_verified_bytes_when_shim_changes_inside_popen(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted = root / "trusted"
            trusted.write_text("#!/bin/sh\nprintf trusted\n", encoding="utf-8")
            trusted.chmod(0o755)
            marker = root / "spawn-escaped"
            replacement = root / "replacement"
            replacement.write_text(
                f"#!/bin/sh\nprintf escaped > {marker}\nprintf replacement\n",
                encoding="utf-8",
            )
            replacement.chmod(0o755)
            shim = root / "codex"
            shim.symlink_to(trusted)
            identity = negotiate_session_capability(
                "other", "codex", env={"PATH": str(root)}
            )
            self.assertIsNotNone(identity)
            assert identity is not None
            real_popen = __import__("subprocess").Popen

            def retarget_inside_popen(*args: object, **kwargs: object):
                shim.unlink()
                shim.symlink_to(replacement)
                return real_popen(*args, **kwargs)

            with patch(
                "omh.coding.fanout_dispatch.subprocess.Popen",
                side_effect=retarget_inside_popen,
            ):
                completed = signal_safe_unit_runner(
                    (str(shim),),
                    env={"PATH": str(root)},
                    text=True,
                    capture_output=True,
                    expected_binary_identity=identity.binary_identity,
                )

            self.assertEqual(completed.stdout, "trusted")
            self.assertFalse(marker.exists())

    def test_runner_pinned_artifact_cannot_be_overwritten_inside_popen(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            trusted = root / "codex.js"
            trusted.write_text("#!/bin/sh\nprintf trusted\n", encoding="utf-8")
            trusted.chmod(0o755)
            marker = root / "artifact-overwritten"
            shim = root / "codex"
            shim.symlink_to(trusted)
            identity = negotiate_session_capability(
                "other", "codex", env={"PATH": str(root)}
            )
            self.assertIsNotNone(identity)
            assert identity is not None
            real_popen = __import__("subprocess").Popen

            def overwrite_pinned_artifact(*args: object, **kwargs: object):
                executable = kwargs.get("executable")
                self.assertIsInstance(executable, str)
                assert isinstance(executable, str)
                try:
                    Path(executable).unlink()
                    Path(executable).write_text(
                        f"#!/bin/sh\nprintf escaped > {marker}\n",
                        encoding="utf-8",
                    )
                except PermissionError:
                    pass
                return real_popen(*args, **kwargs)

            with patch(
                "omh.coding.fanout_dispatch.subprocess.Popen",
                side_effect=overwrite_pinned_artifact,
            ):
                completed = signal_safe_unit_runner(
                    (str(shim),),
                    env={"PATH": str(root)},
                    text=True,
                    capture_output=True,
                    expected_binary_identity=identity.binary_identity,
                )

            self.assertEqual(completed.stdout, "trusted")
            self.assertFalse(marker.exists())

    def test_generic_script_pin_never_mirrors_its_grandparent_directory(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            trusted = root / "codex"
            trusted.write_text("#!/bin/sh\nprintf trusted\n", encoding="utf-8")
            trusted.chmod(0o755)
            capability = negotiate_session_capability(
                "other", str(trusted), env={"PATH": temporary}
            )
            self.assertIsNotNone(capability)
            assert capability is not None
            original_iterdir = Path.iterdir
            observed: list[Path] = []

            def record_iterdir(path: Path):
                observed.append(path)
                return original_iterdir(path)

            with patch.object(Path, "iterdir", record_iterdir):
                completed = signal_safe_unit_runner(
                    (str(trusted),),
                    env={"PATH": temporary},
                    text=True,
                    capture_output=True,
                    expected_binary_identity=capability.binary_identity,
                )

            self.assertEqual(completed.stdout, "trusted")
            self.assertIn(root, observed)
            self.assertNotIn(root.parent, observed)


    def test_script_launcher_does_not_require_install_directory_writes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            binary_directory = package / "bin"
            binary_directory.mkdir(parents=True)
            trusted = binary_directory / "codex.js"
            trusted.write_text("#!/bin/sh\nprintf trusted\n", encoding="utf-8")
            trusted.chmod(0o555)
            binary_directory.chmod(0o555)
            package.chmod(0o555)
            shim = root / "codex"
            shim.symlink_to(trusted)
            try:
                identity = negotiate_session_capability(
                    "other", "codex", env={"PATH": str(root)}
                )
                self.assertIsNotNone(identity)
                assert identity is not None

                completed = signal_safe_unit_runner(
                    (str(shim),),
                    env={"PATH": str(root)},
                    text=True,
                    capture_output=True,
                    expected_binary_identity=identity.binary_identity,
                )

                self.assertEqual(completed.stdout, "trusted")
            finally:
                package.chmod(0o755)
                binary_directory.chmod(0o755)

    def test_same_version_in_two_places_is_not_flagged_as_shadowed(self) -> None:
        # Two distinct binaries printing the same version disagree about
        # nothing a user must resolve; flagging them would train people to
        # ignore the flag.
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            _fake_binary(first, "codex", "0.145.0")
            _fake_binary(second, "codex", "0.145.0")
            result = self._probe(os.pathsep.join([first, second]))
            self.assertFalse(result["shadowed"])

    def test_the_probe_carries_the_no_pinned_version_policy(self) -> None:
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "9.9.9")
            result = self._probe(only)
            self.assertEqual(result["version_policy"], EXECUTOR_VERSION_POLICY)
            # A future version OMH has never seen probes ready: nothing in the
            # contract encodes an expected version to fall behind.
            self.assertEqual(result["status"], "ready")

    def test_a_ready_probe_says_it_observed_only_the_binary_version(self) -> None:
        # The 2026-09-11 gap: `available: true` was read as "this executor can
        # do the work". The probe has no worktree, so it cannot have observed
        # anything about one, and the payload has to say that out loud.
        with TemporaryDirectory() as only:
            _fake_binary(only, "codex", "0.145.0")
            result = self._probe(only)

            self.assertEqual(result["status"], "ready")
            self.assertTrue(result["available"])
            self.assertEqual(result["observed"], "binary_version_only")
            self.assertIn("workspace not yet probed", result["summary"])
            self.assertIn("workspace_preflight", result["summary"])
            self.assertIn("workspace_preflight", result["claim_boundary"])
            self.assertIn("is not a claim that the work can be done", result["claim_boundary"])
            # The observed version line is still there; the qualification is
            # appended to it rather than replacing it.
            self.assertIn("0.145.0", result["summary"])

    def test_a_missing_binary_also_states_what_was_observed(self) -> None:
        with TemporaryDirectory() as empty:
            result = self._probe(empty)

            self.assertEqual(result["status"], "missing")
            self.assertEqual(result["observed"], "binary_version_only")

    def test_no_source_line_hardcodes_an_executor_version(self) -> None:
        # The guard for the structural rule itself: the module may print
        # versions it observed, never carry one of its own.
        import inspect

        import omh.coding.executor_readiness as module

        source = inspect.getsource(module)
        for literal in ("0.144", "0.145", "2.1.2"):
            self.assertNotIn(literal, source)


class OmoRuntimeProbeCommandTests(unittest.TestCase):
    """omo-runtime readiness probes the DETECTED host CLI, pi-first.

    The static `_COMMANDS` entry is a mirror of the first host candidate,
    never the resolution authority: `_resolved_command` always asks
    `omo_runtime_host` which host is actually on PATH.
    """

    def setUp(self) -> None:
        _executor_readiness_contract_cached.cache_clear()
        self.addCleanup(_executor_readiness_contract_cached.cache_clear)

    def test_contract_probes_the_detected_host_pi_first(self) -> None:
        with patch(
            "omh.coding.fanout_dispatch.shutil.which",
            lambda name: f"/x/{name}" if name in ("pi", "senpi") else None,
        ):
            contract = executor_readiness_contract("omo-runtime")
        self.assertEqual(contract["probe"]["command"], "pi")

    def test_detected_senpi_host_overrides_the_static_entry(self) -> None:
        with patch(
            "omh.coding.fanout_dispatch.shutil.which",
            lambda name: "/x/senpi" if name == "senpi" else None,
        ):
            contract = executor_readiness_contract("omo-runtime")
        self.assertEqual(contract["probe"]["command"], "senpi")

    def test_no_host_on_path_falls_back_to_the_first_candidate(self) -> None:
        with patch("omh.coding.fanout_dispatch.shutil.which", lambda name: None):
            contract = executor_readiness_contract("omo-runtime")
        self.assertEqual(contract["probe"]["command"], OMO_RUNTIME_HOST_CANDIDATES[0])
        self.assertEqual(contract["probe"]["command"], "pi")

    def test_static_command_entry_mirrors_the_first_host_candidate(self) -> None:
        # A future second consumer of `_COMMANDS` must see the same pi-first
        # default the detector promises; repinning the entry to one
        # distribution (the old senpi pin) fails here.
        self.assertEqual(_COMMANDS["omo-runtime"][0], OMO_RUNTIME_HOST_CANDIDATES[0])


if __name__ == "__main__":
    unittest.main()
