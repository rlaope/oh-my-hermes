from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from zipfile import ZipFile

from _distribution_helpers import (
    NPM_PACKAGE_SOURCE,
    PROJECT_ROOT,
    PROJECT_VERSION,
    build_wheel,
    command_for,
    locate_global_omh,
    pack_npm_package,
    require_tool,
    run,
    stage_npm_package,
)

METADATA_TOOL = (
    PROJECT_ROOT / "tools" / "package_manager" / "metadata.py"
)
PYTHON_BRIDGE = NPM_PACKAGE_SOURCE / "bin" / "python_bridge.py"
# Stands in for Hermes' launcher: with HERMES_TUI_DIR set it runs the OMH
# frontend shim as the launcher does, under a PYTHONPATH of its own; without
# it, it is the fallback terminal and exits at once.
STUB_HERMES = """#!/bin/sh
echo "hermes $*" >> "$STUB_LOG"
if [ -n "$HERMES_TUI_DIR" ]; then
  echo "site=$OMH_TUI_SITE" >> "$STUB_LOG"
  PYTHONPATH="$STUB_HERMES_PATH" exec node "$HERMES_TUI_DIR/dist/entry.js"
fi
exit 0
"""


def _run_in_pty(
    argv: list[str], env: dict[str, str], timeout: float = 120.0
) -> tuple[int, str]:
    """Run `argv` with a pty as its stdin, stdout and stderr; its exit code and what it wrote.

    A run still going at `timeout` raises `subprocess.TimeoutExpired`, after
    its session is killed and reaped.
    """
    import pty  # POSIX only

    master, slave = pty.openpty()
    try:
        child = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
        )
    except BaseException:
        os.close(master)
        raise
    finally:
        os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if not ready:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:  # EIO once every process has closed the terminal
                break
            if not chunk:
                break
            output += chunk
        child.wait(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        if child.poll() is None:
            # The session this call started, by its id, and nothing else.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=30)
        os.close(master)
    return child.returncode, output.decode("utf-8", "replace")


class DistributionHelperTests(unittest.TestCase):
    def test_cache_retention_count_is_machine_readable(self) -> None:
        cache_module = (NPM_PACKAGE_SOURCE / "lib" / "cache.js").as_uri()
        script = (
            f'import {{ CACHE_RETENTION_COUNT }} from "{cache_module}";'
            "console.log(CACHE_RETENTION_COUNT);"
        )
        result = run(
            [
                require_tool("node"),
                "--input-type=module",
                "--eval",
                script,
            ]
        )
        self.assertEqual(result.stdout.strip(), "3")

    def test_python_discovery_includes_supported_versioned_commands(self) -> None:
        python_module = (NPM_PACKAGE_SOURCE / "lib" / "python.js").as_uri()
        script = (
            f'import {{ pythonCandidates }} from "{python_module}";'
            'console.log(JSON.stringify({'
            'posix: pythonCandidates("linux"),'
            'windows: pythonCandidates("win32")'
            "}));"
        )
        result = run(
            [
                require_tool("node"),
                "--input-type=module",
                "--eval",
                script,
            ]
        )
        candidates = json.loads(result.stdout)
        for platform in ("posix", "windows"):
            executables = [
                candidate["executable"]
                for candidate in candidates[platform]
            ]
            for versioned in (
                "python3.14",
                "python3.13",
                "python3.12",
                "python3.11",
            ):
                self.assertIn(versioned, executables)
        self.assertEqual(candidates["windows"][0], {
            "executable": "py",
            "prefix": ["-3"],
        })

    @unittest.skipIf(os.name == "nt", "POSIX signal numbers are platform-specific")
    def test_child_signal_exit_codes_follow_shell_convention(self) -> None:
        launcher = (NPM_PACKAGE_SOURCE / "lib" / "launcher.js").as_uri()
        script = (
            f'import {{ signalExitCode }} from "{launcher}";'
            'console.log(JSON.stringify({'
            'hup: signalExitCode("SIGHUP"),'
            'quit: signalExitCode("SIGQUIT"),'
            'term: signalExitCode("SIGTERM"),'
            'unknown: signalExitCode("UNKNOWN")'
            "}));"
        )
        result = run(
            [
                require_tool("node"),
                "--input-type=module",
                "--eval",
                script,
            ]
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"hup": 129, "quit": 131, "term": 143, "unknown": 1},
        )

    def test_windows_global_command_prefers_cmd_shim(self) -> None:
        with TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            binary = prefix / "bin"
            binary.mkdir()
            (binary / "omh").touch()
            command = binary / "omh.cmd"
            command.touch()
            self.assertEqual(
                locate_global_omh(prefix, platform="nt"),
                command,
            )
            self.assertEqual(
                command_for(command, "--version", platform="nt"),
                ["cmd", "/d", "/c", str(command), "--version"],
            )


class DistributionMetadataTests(unittest.TestCase):
    def test_wheel_and_tarball_are_reproducible(self) -> None:
        require_tool("npm")
        environment = {**os.environ, "SOURCE_DATE_EPOCH": "1700000000"}
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts: list[tuple[Path, Path]] = []
            for attempt in ("first", "second"):
                wheel = build_wheel(
                    root / attempt / "wheel",
                    env=environment,
                )
                package = stage_npm_package(
                    wheel,
                    root / attempt / "package",
                )
                tarball = pack_npm_package(
                    package,
                    root / attempt / "tarball",
                    env=environment,
                )
                artifacts.append((wheel, tarball))
            self.assertEqual(
                artifacts[0][0].read_bytes(),
                artifacts[1][0].read_bytes(),
            )
            self.assertEqual(
                artifacts[0][1].read_bytes(),
                artifacts[1][1].read_bytes(),
            )

    def test_wheel_metadata_matches_canonical_version(self) -> None:
        with TemporaryDirectory() as tmp:
            wheel = build_wheel(Path(tmp))
            self.assertTrue(
                METADATA_TOOL.is_file(),
                f"distribution metadata tool is missing: {METADATA_TOOL}",
            )
            result = run(
                [
                    sys.executable,
                    str(METADATA_TOOL),
                    "--wheel",
                    str(wheel),
                    "--json",
                ]
            )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["name"], "oh-my-hermes")
        self.assertEqual(payload["version"], PROJECT_VERSION)
        self.assertEqual(payload["requires_python"], ">=3.11")
        self.assertEqual(payload["wheel"], wheel.name)


class PythonBridgeTests(unittest.TestCase):
    def test_bridge_bounds_file_directory_member_collisions(self) -> None:
        cases = (
            ("file-before-child", ("pkg", "pkg/module.py")),
            ("child-before-file", ("pkg/module.py", "pkg")),
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, members in cases:
                with self.subTest(case=name):
                    wheel = root / f"{name}.whl"
                    with ZipFile(wheel, "w") as archive:
                        for member in members:
                            archive.writestr(member, "content")
                    result = run(
                        [
                            sys.executable,
                            "-I",
                            str(PYTHON_BRIDGE),
                            "bootstrap",
                            "--wheel",
                            str(wheel),
                            "--site",
                            str(root / name / "site"),
                            "--version",
                            PROJECT_VERSION,
                            "--sha256",
                            hashlib.sha256(wheel.read_bytes()).hexdigest(),
                            "--tree-sha256",
                            "0" * 64,
                        ],
                        check=False,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("wheel member collision", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_bridge_rejects_unsafe_wheel_members(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "unsafe.whl"
            with ZipFile(wheel, "w") as archive:
                archive.writestr("../escape.py", "raise RuntimeError")
            self.assertTrue(
                PYTHON_BRIDGE.is_file(),
                f"Python wheel bridge is missing: {PYTHON_BRIDGE}",
            )
            result = run(
                [
                    sys.executable,
                    "-I",
                    str(PYTHON_BRIDGE),
                    "bootstrap",
                    "--wheel",
                    str(wheel),
                    "--site",
                    str(root / "stage" / "site"),
                    "--version",
                    PROJECT_VERSION,
                    "--sha256",
                    hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    "--tree-sha256",
                    "0" * 64,
                ],
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe wheel member", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((root / "escape.py").exists())


class NpmBunDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.root = Path(self.stack.name)
        (self.root / "package.json").write_text(
            json.dumps({"name": "omh-test-isolation-barrier", "type": "commonjs"}),
            encoding="utf-8",
        )
        self.wheel = build_wheel(self.root / "wheel")
        self.package = stage_npm_package(self.wheel, self.root / "package")

    def _tarball(self) -> Path:
        return pack_npm_package(self.package, self.root / "tarballs")

    def _launcher_env(self, cache: Path) -> dict[str, str]:
        return {
            **os.environ,
            "OMH_CACHE_DIR": str(cache),
            "OMH_PYTHON": sys.executable,
            "PYTHONPATH": "must-not-be-inherited",
            "PIP_NO_INDEX": "1",
        }

    def _run_staged_launcher(
        self,
        cache: Path,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return run(
            [
                require_tool("node"),
                str(self.package / "bin" / "omh.js"),
                *arguments,
            ],
            env=self._launcher_env(cache),
            check=check,
        )

    def _published_cache(self, cache: Path) -> Path:
        candidates = [
            path
            for path in cache.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
        self.assertEqual(len(candidates), 1, candidates)
        return candidates[0]

    def _assert_cli(
        self,
        binary: Path,
        cache: Path,
        *,
        package_manager: str,
    ) -> None:
        env = {
            **os.environ,
            "OMH_CACHE_DIR": str(cache),
            "OMH_PYTHON": sys.executable,
            "PYTHONPATH": "must-not-be-inherited",
            "PIP_NO_INDEX": "1",
            # This fixture installs an unpublished local tarball with network
            # access disabled. Package-manager self-update is covered by the
            # update routing tests and the public-release QA; this assertion
            # verifies the staged artifact's own CLI and provenance.
            "OMH_SKIP_COMMAND_PACKAGE_UPDATE": "1",
        }
        if package_manager == "bun":
            env["BUN_INSTALL"] = str(self.root / "bun-global")
        for arguments in (("--version",), ("--help",), ("setup", "--help")):
            result = run(command_for(binary, *arguments), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
        version = run(command_for(binary, "--version"), env=env)
        self.assertIn(PROJECT_VERSION, version.stdout)
        doctor_root = cache.parent / f"{cache.name}-doctor"
        doctor = run(
            command_for(
                binary,
                "--omh-home",
                str(doctor_root / "omh"),
                "--hermes-home",
                str(doctor_root / "hermes"),
                "doctor",
                "--json",
            ),
            env=env,
            check=False,
        )
        self.assertIn(doctor.returncode, {0, 1}, doctor.stderr)
        doctor_payload = json.loads(doctor.stdout)
        self.assertIn("ok", doctor_payload)
        self.assertIn("checks", doctor_payload)
        update = run(
            command_for(
                binary,
                "--omh-home",
                str(doctor_root / "omh"),
                "--hermes-home",
                str(doctor_root / "hermes"),
                "update",
                "--json",
            ),
            env=env,
        )
        update_payload = json.loads(update.stdout)
        self.assertEqual(
            update_payload["command_package"]["package_manager"],
            package_manager,
        )
        expected_update = {
            "npm": "npm update -g oh-my-hermes",
            "bun": "bun update -g --latest oh-my-hermes",
        }[package_manager]
        self.assertEqual(
            update_payload["command_package"]["update_instruction"],
            expected_update,
        )
        manager_update_env = dict(env)
        manager_update_env.pop("OMH_SKIP_COMMAND_PACKAGE_UPDATE")
        pinned = run(
            command_for(
                binary,
                "--omh-home",
                str(doctor_root / "omh"),
                "--hermes-home",
                str(doctor_root / "hermes"),
                "update",
                "--channel",
                "stable",
                "--version",
                PROJECT_VERSION,
                "--json",
            ),
            env=manager_update_env,
            check=False,
        )
        self.assertEqual(pinned.returncode, 2)
        self.assertIn(
            "default published update only",
            pinned.stderr,
        )

    def _installer_env(self) -> dict[str, str]:
        home = self.root / "installer-home"
        home.mkdir(exist_ok=True)
        return {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "npm_config_cache": str(home / "npm-cache"),
            "npm_config_userconfig": str(home / "npmrc"),
            "npm_config_globalconfig": str(home / "global-npmrc"),
            "npm_config_audit": "false",
            "npm_config_fund": "false",
            "BUN_INSTALL_CACHE_DIR": str(home / "bun-cache"),
            "BUN_INSTALL_GLOBAL_DIR": str(self.root / "bun-global" / "install" / "global"),
            "BUN_INSTALL_BIN": str(self.root / "bun-global" / "bin"),
        }

    def test_global_tarball_launchers(self) -> None:
        tarball = self._tarball()
        npm = Path(require_tool("npm"))
        bun = Path(require_tool("bun"))

        npm_prefix = self.root / "npm-global"
        run(
            command_for(
                npm,
                "install",
                "--global",
                "--ignore-scripts",
                "--prefix",
                str(npm_prefix),
                str(tarball),
            ),
            cwd=self.root,
            env=self._installer_env(),
        )
        self._assert_cli(
            locate_global_omh(npm_prefix),
            self.root / "npm-cache",
            package_manager="npm",
        )

        bun_root = self.root / "bun-global"
        bun_workspace = bun_root / "install" / "global"
        bun_workspace.mkdir(parents=True)
        (bun_workspace / "package.json").write_text('{"private":true}\n', encoding="utf-8")
        bun_env = {**self._installer_env(), "BUN_INSTALL": str(bun_root)}
        run(
            command_for(bun, "install", "--global", str(tarball)),
            cwd=bun_workspace,
            env=bun_env,
        )
        self._assert_cli(
            locate_global_omh(bun_root),
            self.root / "bun-cache",
            package_manager="bun",
        )

    def test_staged_package_has_exact_wheel_and_no_lifecycle_scripts(self) -> None:
        package = json.loads((self.package / "package.json").read_text())
        self.assertEqual(package["name"], "oh-my-hermes")
        self.assertEqual(package["version"], PROJECT_VERSION)
        self.assertEqual(package["bin"], {"omh": "bin/omh.js"})
        for lifecycle in (
            "preinstall",
            "install",
            "postinstall",
            "prepare",
        ):
            self.assertNotIn(lifecycle, package.get("scripts", {}))

        vendored = self.package / package["omhDistribution"]["wheel"]
        self.assertEqual(vendored.read_bytes(), self.wheel.read_bytes())
        self.assertEqual(
            package["omhDistribution"]["wheelSha256"],
            hashlib.sha256(self.wheel.read_bytes()).hexdigest(),
        )
        self.assertRegex(
            package["omhDistribution"]["cacheTreeSha256"],
            r"^[0-9a-f]{64}$",
        )
        staged_files = [
            path.relative_to(self.package)
            for path in self.package.rglob("*")
            if path.is_file()
        ]
        self.assertFalse(
            any(
                "__pycache__" in path.parts or path.suffix == ".pyc"
                for path in staged_files
            ),
            staged_files,
        )

    @unittest.skipIf(
        os.name == "nt", "needs a pty; the OMH TUI is never attempted on Windows"
    )
    def test_bare_omh_opens_the_tui_from_the_launcher_cache(self) -> None:
        # #2168: the bridge puts the cache on the import path in-process, and
        # the TUI's interpreter, started `-E -P` by the frontend shim, could
        # not import `omh`, so bare `omh` fell back to Hermes' own TUI.
        venv = self.root / "venv"
        run([sys.executable, "-m", "venv", "--without-pip", str(venv)])
        python = venv / "bin" / "python"
        alone = run([str(python), "-E", "-P", "-c", "import omh"], check=False)
        self.assertNotEqual(
            alone.returncode, 0, "the launcher's interpreter must not import omh by itself"
        )
        stub_bin = self.root / "stub-bin"
        stub_bin.mkdir()
        hermes = stub_bin / "hermes"
        hermes.write_text(STUB_HERMES, encoding="utf-8", newline="\n")
        hermes.chmod(0o755)
        hermes_path = self.root / "hermes-pythonpath"
        hermes_path.mkdir()
        marker = self.root / "hermes-pythonpath-reached"
        (hermes_path / "sitecustomize.py").write_text(
            "import os\n"
            "open(os.environ['STUB_MARKER'], 'a').write('reached\\n')\n",
            encoding="utf-8",
            newline="\n",
        )
        cache = self.root / "tui-cache"
        log = self.root / "hermes.log"
        (self.root / "home").mkdir()
        env = {
            "PATH": os.pathsep.join(
                [str(stub_bin), str(Path(require_tool("node")).parent), "/usr/bin", "/bin"]
            ),
            "HOME": str(self.root / "home"),
            "TERM": "xterm-256color",
            "OMH_CACHE_DIR": str(cache),
            "OMH_PYTHON": str(python),
            "STUB_LOG": str(log),
            "STUB_HERMES_PATH": str(hermes_path),
            "STUB_MARKER": str(marker),
            # A value left in the person's environment does not pick the tree.
            "OMH_TUI_SITE": str(self.root / "another-tree"),
        }
        omh_js = str(self.package / "bin" / "omh.js")
        run([require_tool("node"), omh_js, "--version"], env=env)
        site = self._published_cache(cache) / "site"
        ready_inode = (site.parent / "ready.json").stat().st_ino

        returncode, output = _run_in_pty(
            [
                require_tool("node"),
                omh_js,
                "--omh-home",
                str(self.root / "omh-home"),
                "--hermes-home",
                str(self.root / "hermes-home"),
            ],
            env,
        )

        self.assertEqual(returncode, 0, output)
        self.assertNotIn("could not import itself", output)
        # Past the import: `main` ran from the cache and stopped at the gateway
        # the stub launcher does not provide, then asked for the fallback.
        self.assertIn("the Hermes gateway did not start", output)
        calls = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls[0], "hermes --tui")
        named = [line.removeprefix("site=") for line in calls if line.startswith("site=")]
        self.assertEqual([os.path.realpath(path) for path in named], [os.path.realpath(site)])
        self.assertFalse(marker.exists(), "Hermes' PYTHONPATH reached an OMH interpreter")
        # The bridge checks the cache against its digest on every run: the TUI
        # wrote nothing into it, and the next run used it as it was.
        self.assertEqual(sorted(site.rglob("__pycache__")), [])
        run([require_tool("node"), omh_js, "--version"], env=env)
        self.assertEqual((site.parent / "ready.json").stat().st_ino, ready_inode)

    def test_cache_tampering_and_unsafe_permissions_force_rebuild(self) -> None:
        cache = self.root / "tampered-cache"
        self._run_staged_launcher(cache, "--version")
        published = self._published_cache(cache)
        injected = published / "site" / "attacker.py"
        injected.write_text("raise RuntimeError('cache injection')\n")

        self._run_staged_launcher(cache, "--version")
        self.assertFalse(injected.exists())

        if os.name != "nt":
            cache.chmod(0o777)
            published.chmod(0o777)
            self._run_staged_launcher(cache, "--version")
            self.assertEqual(cache.stat().st_mode & 0o077, 0)
            for path in (published, *published.rglob("*")):
                self.assertEqual(path.lstat().st_mode & 0o077, 0, path)
                self.assertEqual(path.lstat().st_uid, os.getuid(), path)

    def test_cache_prunes_old_exact_wheel_versions(self) -> None:
        cache = self.root / "bounded-cache"
        cache.mkdir(mode=0o700)
        for index in range(5):
            old = cache / f"0.0.{index}-{'a' * 63}{index}"
            old.mkdir(mode=0o700)
            os.utime(old, (index + 1, index + 1))
        stale_stage = cache / ".stage-stale"
        stale_stage.mkdir(mode=0o700)
        os.utime(stale_stage, (1, 1))

        self._run_staged_launcher(cache, "--version")

        published = [
            path
            for path in cache.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
        self.assertLessEqual(len(published), 3, published)
        self.assertFalse(stale_stage.exists())

    @unittest.skipIf(os.name == "nt", "symlink attack probe is POSIX-only")
    def test_cached_and_vendored_symlinks_are_rejected(self) -> None:
        cache = self.root / "symlink-cache"
        self._run_staged_launcher(cache, "--version")
        published = self._published_cache(cache)
        cached_cli = published / "site" / "omh" / "cli" / "__init__.py"
        external_cli = self.root / "external-cli.py"
        external_cli.write_bytes(cached_cli.read_bytes())
        cached_cli.unlink()
        cached_cli.symlink_to(external_cli)

        self._run_staged_launcher(cache, "--version")
        self.assertFalse(cached_cli.is_symlink())

        package = json.loads((self.package / "package.json").read_text())
        vendored = self.package / package["omhDistribution"]["wheel"]
        vendored.unlink()
        vendored.symlink_to(self.wheel)
        result = self._run_staged_launcher(
            self.root / "vendored-symlink-cache",
            "--version",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)

    @unittest.skipIf(os.name == "nt", "hardlink probe is POSIX-only")
    def test_hardlinked_vendored_wheel_uses_private_snapshot(self) -> None:
        package = json.loads((self.package / "package.json").read_text())
        vendored = self.package / package["omhDistribution"]["wheel"]
        hardlink = self.root / "bun-content-store-wheel.whl"
        os.link(vendored, hardlink)
        self.assertGreater(vendored.stat().st_nlink, 1)

        cache = self.root / "hardlinked-wheel-cache"
        self._run_staged_launcher(cache, "--version")
        self.assertFalse((self._published_cache(cache) / "wheel.whl").exists())

        hardlink.write_bytes(b"tampered\n")
        result = self._run_staged_launcher(
            cache,
            "--version",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("digest does not match", result.stderr)

    @unittest.skipIf(os.name == "nt", "symlink attack probe is POSIX-only")
    def test_forged_readiness_and_final_links_never_authorize_cache(self) -> None:
        cache = self.root / "forged-cache"
        self._run_staged_launcher(cache, "--version")
        published = self._published_cache(cache)
        version_source = published / "site" / "omh" / "version.py"
        original_version_source = version_source.read_bytes()
        version_source.write_bytes(original_version_source + b"\n# injected\n")

        self._run_staged_launcher(cache, "--version")
        self.assertEqual(version_source.read_bytes(), original_version_source)

        ready = published / "ready.json"
        external_ready = self.root / "external-ready.json"
        external_ready.write_bytes(ready.read_bytes())
        ready.unlink()
        ready.symlink_to(external_ready)
        self._run_staged_launcher(cache, "--version")
        self.assertFalse(ready.is_symlink())
        self.assertEqual(external_ready.read_bytes(), ready.read_bytes())

        target = self.root / "final-link-target"
        target.mkdir()
        marker = target / "marker"
        marker.write_text("preserve\n")
        shutil.rmtree(published)
        published.symlink_to(target, target_is_directory=True)
        self._run_staged_launcher(cache, "--version")
        self.assertFalse(published.is_symlink())
        self.assertEqual(marker.read_text(), "preserve\n")

    @unittest.skipIf(os.name == "nt", "symlink attack probe is POSIX-only")
    def test_vendored_wheel_parent_link_is_rejected(self) -> None:
        vendor = self.package / "vendor"
        external_vendor = self.root / "external-vendor"
        vendor.rename(external_vendor)
        vendor.symlink_to(external_vendor, target_is_directory=True)

        cache = self.root / "vendor-parent-cache"
        result = self._run_staged_launcher(
            cache,
            "--version",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)
        self.assertFalse(cache.exists())

    @unittest.skipIf(os.name == "nt", "symlink attack probe is POSIX-only")
    def test_symlinked_cache_root_and_wheel_input_fail_closed(self) -> None:
        target = self.root / "cache-target"
        target.mkdir()
        marker = target / "marker"
        marker.write_text("preserve\n")
        cache = self.root / "cache-link"
        cache.symlink_to(target, target_is_directory=True)
        result = self._run_staged_launcher(
            cache,
            "--version",
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cache root", result.stderr)
        self.assertEqual(marker.read_text(), "preserve\n")

        wheel_link = self.root / self.wheel.name
        wheel_link.symlink_to(self.wheel)
        output = self.root / "symlinked-wheel-package"
        result = run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "package_manager" / "stage_npm.py"),
                "--wheel",
                str(wheel_link),
                "--output",
                str(output),
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regular file", result.stderr)
        self.assertFalse(output.exists())

    @unittest.skipIf(os.name == "nt", "symlink attack probe is POSIX-only")
    def test_staging_refuses_symlinked_output_path(self) -> None:
        target = self.root / "staging-target"
        target.mkdir()
        marker = target / "marker"
        marker.write_text("preserve\n")
        output = self.root / "package-output"
        output.symlink_to(target, target_is_directory=True)

        result = run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "package_manager" / "stage_npm.py"),
                "--wheel",
                str(self.wheel),
                "--output",
                str(output),
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symbolic link", result.stderr)
        self.assertEqual(marker.read_text(), "preserve\n")
        self.assertTrue(output.is_symlink())

    def test_staging_preserves_an_existing_output(self) -> None:
        output = self.root / "existing-package"
        output.mkdir()
        marker = output / "marker"
        marker.write_text("preserve\n")

        result = run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "package_manager" / "stage_npm.py"),
                "--wheel",
                str(self.wheel),
                "--output",
                str(output),
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(marker.read_text(), "preserve\n")

    def test_missing_python_is_bounded_and_does_not_mutate_cache(self) -> None:
        cache = self.root / "missing-python-cache"
        env = {
            **os.environ,
            "OMH_CACHE_DIR": str(cache),
            "OMH_PYTHON": str(self.root / "missing-python"),
        }
        result = run(
            [require_tool("node"), str(self.package / "bin" / "omh.js"), "--version"],
            env=env,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.11", result.stderr)
        self.assertNotIn(" at ", result.stderr)
        self.assertLess(len(result.stderr), 500)
        self.assertFalse(cache.exists())

    def test_concurrent_first_runs_publish_one_valid_cache(self) -> None:
        cache = self.root / "concurrent-cache"
        env = {
            **os.environ,
            "OMH_CACHE_DIR": str(cache),
            "OMH_PYTHON": sys.executable,
        }
        command = [
            require_tool("node"),
            str(self.package / "bin" / "omh.js"),
            "--version",
        ]
        processes = [
            subprocess.Popen(
                command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        try:
            results = [process.communicate(timeout=120) for process in processes]
        finally:
            # A timeout or assertion failure below must not orphan a still-running
            # child (issue #1731): kill and reap anything left over.
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    _ = process.communicate()
        for process, (stdout, stderr) in zip(processes, results, strict=True):
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn(PROJECT_VERSION, stdout)
        final = [path for path in cache.iterdir() if not path.name.startswith(".")]
        self.assertEqual(len(final), 1)
        self.assertTrue((final[0] / "ready.json").is_file())
        self.assertFalse(list(cache.glob(".stage-*")))
        self.assertFalse(list(final[0].rglob("__pycache__")))
