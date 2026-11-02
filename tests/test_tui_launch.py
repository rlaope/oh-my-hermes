"""How bare `omh` reaches the OMH TUI: availability, environment, and the Node shim."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from omh.tui import launch

REPO_ROOT = Path(__file__).resolve().parents[1]
# Puts argv[1] first on the path, imports `omh` from there, and reports the root `omh_import_root` gives,
# the package file, and what a path search of that root alone finds.
_IMPORT_ROOT_PROBE = (
    "import importlib.machinery, json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import omh\n"
    "from omh.tui.launch import omh_import_root\n"
    "root = omh_import_root()\n"
    "spec = importlib.machinery.PathFinder.find_spec('omh', [root])\n"
    "print(json.dumps({'root': root, 'file': omh.__file__, 'found': spec.origin if spec else None}))\n"
)


class _Tty:
    def isatty(self) -> bool:
        return True


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def _stub_omh(root: Path) -> Path:
    """A stand-in `omh` under `root` whose `omh.tui.app.main` records where it ran from, and returns 0."""
    for package in (root / "omh", root / "omh" / "tui"):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (root / "omh" / "tui" / "app.py").write_text(
        "import json, sys\n"
        "def main(environ):\n"
        "    with open(environ['STUB_RECORD'], 'w', encoding='utf-8') as out:\n"
        "        json.dump({'file': __file__, 'path': sys.path, 'no_bytecode': sys.dont_write_bytecode}, out)\n"
        "    return 0\n",
        encoding="utf-8", newline="\n",
    )
    return root


class NodeAvailabilityTests(unittest.TestCase):
    def test_an_executable_hermes_node_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            node = _executable(Path(tmp) / "node", "#!/bin/sh\n")
            self.assertTrue(launch.node_available({"HERMES_NODE": str(node), "PATH": ""}, Path(tmp)))

    @unittest.skipIf(os.name == "nt", "shutil.which needs a PATHEXT extension on Windows, where the TUI is never attempted")
    def test_node_on_path_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            _executable(Path(tmp) / "bin" / "node", "#!/bin/sh\n")
            self.assertTrue(launch.node_available({"PATH": str(Path(tmp) / "bin")}, Path(tmp) / "home"))

    def test_hermes_own_tools_node_counts(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _executable(home / "tools" / "node-26.7.0-darwin-arm64" / "bin" / "node", "#!/bin/sh\n")
            self.assertTrue(launch.node_available({"PATH": ""}, home))

    def test_no_node_anywhere_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertFalse(launch.node_available({"PATH": "", "HERMES_NODE": str(Path(tmp) / "missing")}, Path(tmp)))


class AvailabilityTests(unittest.TestCase):
    def test_unsupported_terminal_means_no_attempt(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertFalse(launch.omh_tui_available(_Tty(), _Tty(), {"TERM": "dumb"}, Path(tmp)))

    def test_missing_node_means_no_attempt(self) -> None:
        with TemporaryDirectory() as tmp, patch.object(launch, "terminal_supported", return_value=True):
            self.assertFalse(launch.omh_tui_available(_Tty(), _Tty(), {"PATH": ""}, Path(tmp)))

    def test_supported_terminal_with_node_and_the_shim_present_attempts(self) -> None:
        with TemporaryDirectory() as tmp, patch.object(launch, "terminal_supported", return_value=True):
            node = _executable(Path(tmp) / "node", "#!/bin/sh\n")
            self.assertTrue(launch.omh_tui_available(_Tty(), _Tty(), {"HERMES_NODE": str(node)}, Path(tmp)))

    def test_each_blocker_is_named_and_none_when_the_attempt_goes_ahead(self) -> None:
        with TemporaryDirectory() as tmp:
            node = _executable(Path(tmp) / "node", "#!/bin/sh\n")
            with patch.object(launch, "terminal_supported", return_value=False), \
                    patch.object(launch, "terminal_blocker", return_value="TERM=dumb cannot draw the OMH TUI"):
                self.assertEqual(
                    launch.omh_tui_blocker(_Tty(), _Tty(), {"HERMES_NODE": str(node)}, Path(tmp)),
                    "TERM=dumb cannot draw the OMH TUI",
                )
            with patch.object(launch, "terminal_supported", return_value=True):
                with patch.object(launch, "FRONTEND_ENTRY", Path(tmp) / "missing" / "entry.js"):
                    self.assertIn(
                        "the OMH TUI frontend is missing",
                        launch.omh_tui_blocker(_Tty(), _Tty(), {"HERMES_NODE": str(node)}, Path(tmp)),
                    )
                self.assertIn("no Node found", launch.omh_tui_blocker(_Tty(), _Tty(), {"PATH": ""}, Path(tmp)))
                self.assertEqual(launch.omh_tui_blocker(_Tty(), _Tty(), {"HERMES_NODE": str(node)}, Path(tmp)), "")

    def test_the_shim_ships_where_hermes_looks_for_it(self) -> None:
        self.assertTrue(launch.FRONTEND_ENTRY.is_file())
        self.assertEqual(launch.FRONTEND_ENTRY, launch.FRONTEND_DIR / "dist" / "entry.js")


class EnvironmentTests(unittest.TestCase):
    def test_the_environment_adds_six_names_and_keeps_the_rest(self) -> None:
        env = launch.omh_tui_environment(
            {"PATH": "/bin", "HERMES_HOME": "/h"},
            python="/py", site="/site", omh_home=Path("/o"), fallback_sentinel=Path("/t/f"),
            session_file=Path("/t/s"),
        )
        self.assertEqual(env["HERMES_TUI_DIR"], str(launch.FRONTEND_DIR))
        self.assertEqual(env["OMH_TUI_PYTHON"], "/py")
        self.assertEqual(env["OMH_TUI_SITE"], "/site")
        self.assertEqual(env["OMH_HOME"], str(Path("/o")))
        self.assertEqual(env["OMH_TUI_FALLBACK_SENTINEL"], str(Path("/t/f")))
        self.assertEqual(env["OMH_TUI_SESSION_FILE"], str(Path("/t/s")))
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["HERMES_HOME"], "/h")

    def test_only_a_bare_resume_asks_for_the_picker_and_an_inherited_ask_is_dropped(self) -> None:
        for pick, expected in ((True, "1"), (False, None)):
            with self.subTest(pick=pick):
                env = launch.omh_tui_environment(
                    {launch.PICK_SESSION_ENV: "1"},
                    python="/py", site="/site", omh_home=Path("/o"), fallback_sentinel=Path("/t/f"),
                    session_file=Path("/t/s"), pick_session=pick,
                )
                self.assertEqual(env.get(launch.PICK_SESSION_ENV), expected)

    def test_a_site_left_in_the_environment_is_replaced(self) -> None:
        env = launch.omh_tui_environment(
            {launch.SITE_ENV: "/another/tree"},
            python="/py", site="/site", omh_home=Path("/o"), fallback_sentinel=Path("/t/f"),
            session_file=Path("/t/s"),
        )
        self.assertEqual(env[launch.SITE_ENV], "/site")

    def _import_root_in_a_fresh_process(self, root: Path) -> dict:
        # Not this process: a shard worker may hold the synthetic `omh` tests/_local_package.py makes,
        # whose `__file__` is a directory rather than a package's `__init__.py`.
        result = subprocess.run(
            [sys.executable, "-P", "-c", _IMPORT_ROOT_PROBE, str(root)],
            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_the_import_root_is_where_the_process_found_omh(self) -> None:
        recorded = self._import_root_in_a_fresh_process(REPO_ROOT)
        self.assertEqual(recorded["root"], str(REPO_ROOT))
        self.assertEqual(recorded["file"], str(REPO_ROOT / "omh" / "__init__.py"))
        self.assertEqual(recorded["found"], recorded["file"])

    @unittest.skipIf(os.name == "nt", "symbolic links; the OMH TUI is never attempted on Windows")
    def test_the_import_root_of_a_tree_of_links_is_the_tree_not_the_source(self) -> None:
        # A uv editable install is this shape: a directory of links into src/. Resolving `omh.__file__` would
        # name src/, which is not the directory the process imported `omh` from.
        with TemporaryDirectory() as tmp:
            tree = Path(tmp) / "tree"
            (tree / "omh").mkdir(parents=True)
            for entry in (REPO_ROOT / "src" / "omh").iterdir():
                (tree / "omh" / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
            recorded = self._import_root_in_a_fresh_process(tree)
        self.assertEqual(recorded["root"], str(tree))
        self.assertEqual(recorded["found"], recorded["file"])

    def test_the_fallback_code_is_none_hermes_or_a_session_uses(self) -> None:
        self.assertNotIn(launch.FALLBACK_EXIT, (0, 1, 2, 42, 130))


class FallbackSentinelTests(unittest.TestCase):
    """Exit 75 is a fallback request only together with the file `omh` named."""

    def test_the_sentinel_is_a_fresh_path_in_a_directory_removed_afterwards(self) -> None:
        with launch.fallback_sentinel() as sentinel:
            self.assertFalse(sentinel.exists())
            self.assertTrue(sentinel.parent.is_dir())
            self.assertEqual(list(sentinel.parent.iterdir()), [])
            sentinel.touch()
        self.assertFalse(sentinel.parent.exists())

    def test_two_launches_never_share_a_sentinel(self) -> None:
        with launch.fallback_sentinel() as first, launch.fallback_sentinel() as second:
            self.assertNotEqual(first.parent, second.parent)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits; the OMH TUI is never attempted on Windows")
    def test_the_sentinel_directory_is_private(self) -> None:
        with launch.fallback_sentinel() as sentinel:
            self.assertEqual(sentinel.parent.stat().st_mode & 0o777, 0o700)

    def test_the_directory_is_removed_when_the_launch_raises(self) -> None:
        with self.assertRaises(KeyboardInterrupt), launch.fallback_sentinel() as sentinel:
            sentinel.touch()
            raise KeyboardInterrupt
        self.assertFalse(sentinel.parent.exists())

    @unittest.skipIf(os.name == "nt", "SIGHUP is POSIX-only, and the OMH TUI is never attempted on Windows")
    def test_exit_on_signals_turns_the_pair_into_system_exit_and_puts_the_handlers_back(self) -> None:
        before = {name: signal.getsignal(getattr(signal, name)) for name in launch.EXIT_SIGNALS}
        with launch.exit_on_signals():
            for name in launch.EXIT_SIGNALS:
                with self.subTest(signal=name), self.assertRaises(SystemExit) as raised:
                    os.kill(os.getpid(), getattr(signal, name))
                    time.sleep(1)  # the handler raises before this returns
                self.assertEqual(raised.exception.code, 128 + getattr(signal, name))
        self.assertEqual({name: signal.getsignal(getattr(signal, name)) for name in launch.EXIT_SIGNALS}, before)

    def test_only_the_fallback_code_with_the_file_is_a_request(self) -> None:
        with launch.fallback_sentinel() as sentinel:
            self.assertFalse(launch.fallback_requested(launch.FALLBACK_EXIT, sentinel))
            sentinel.touch()
            self.assertTrue(launch.fallback_requested(launch.FALLBACK_EXIT, sentinel))
            for code in (0, 1, 2, 42, 130):
                with self.subTest(code=code):
                    self.assertFalse(launch.fallback_requested(code, sentinel))

    def test_request_fallback_creates_the_named_file_and_returns_the_code(self) -> None:
        with launch.fallback_sentinel() as sentinel:
            code = launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(sentinel)})
            self.assertEqual(code, launch.FALLBACK_EXIT)
            self.assertTrue(sentinel.is_file())
            self.assertEqual(launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(sentinel)}), launch.FALLBACK_EXIT)

    def test_the_marker_carries_what_the_tui_said_for_omh_to_say_again(self) -> None:
        # Hermes' own TUI clears the screen the reason was printed on; `omh` prints it again once that closes.
        said = "omh: the Hermes gateway did not start: it exited\n  [gateway-exit] refused: \x1b[31mowned\x1b[0m\n\n"
        with launch.fallback_sentinel() as sentinel:
            launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(sentinel)}, said)
            self.assertEqual(launch.fallback_reason(sentinel), [
                "omh: the Hermes gateway did not start: it exited", "  [gateway-exit] refused: [31mowned[0m"])
            # A long traceback keeps its end, where the cause is; a longer earlier reason leaves nothing behind.
            long = "Traceback\n" + "x" * launch.FALLBACK_REASON_BYTES + "\nRuntimeError: the cause\n"
            launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(sentinel)}, long)
            kept = launch.fallback_reason(sentinel)
            self.assertEqual(kept[-1], "RuntimeError: the cause")
            self.assertNotIn("Traceback", kept)
            launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(sentinel)}, "short\n")
            self.assertEqual(launch.fallback_reason(sentinel), ["short"])
        self.assertEqual(launch.fallback_reason(sentinel), [])  # gone with its directory

    def test_an_empty_marker_has_no_reason(self) -> None:
        with launch.fallback_sentinel() as sentinel:
            sentinel.touch()  # what the frontend shim writes
            self.assertEqual(launch.fallback_reason(sentinel), [])

    def test_request_fallback_without_a_name_or_a_place_still_returns_the_code(self) -> None:
        self.assertEqual(launch.request_fallback({}), launch.FALLBACK_EXIT)
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone" / "fallback"
            self.assertEqual(launch.request_fallback({launch.FALLBACK_SENTINEL_ENV: str(missing)}), launch.FALLBACK_EXIT)
            self.assertFalse(missing.exists())


@unittest.skipIf(shutil.which("node") is None or os.name == "nt", "needs node and a POSIX shell")
class ShimTests(unittest.TestCase):
    """Run the shipped `entry.js` under Node with a fake interpreter that records what it got."""

    def _run_shim(self, tmp: Path, *, exit_code: int = 0, extra_env: dict[str, str] | None = None):
        record = tmp / "record.json"
        fake_python = _executable(
            tmp / "fake-python",
            "#!/bin/sh\n"
            f'"{sys.executable}" -c \'import json, os, sys; '
            f'json.dump({{"argv": sys.argv[1:], "env": dict(os.environ)}}, open("{record}", "w"))\' "$@"\n'
            f"exit {exit_code}\n",
        )
        env = {
            "PATH": os.environ.get("PATH", ""),
            "OMH_TUI_PYTHON": str(fake_python),
            "PYTHONPATH": "/hermes/root:/hermes/runtime/site-packages",
            "NODE_OPTIONS": "--max-old-space-size=8192",
            "HERMES_PYTHON": "/hermes/python",
            **(extra_env or {}),
        }
        result = subprocess.run(
            ["node", str(launch.FRONTEND_ENTRY)], env=env, capture_output=True, text=True, timeout=30
        )
        recorded = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
        return result, recorded

    def test_the_shim_starts_python_with_dash_e_dash_p_and_moves_the_launcher_path_aside(self) -> None:
        with TemporaryDirectory() as tmp:
            result, recorded = self._run_shim(Path(tmp))
        self.assertEqual(result.returncode, 0, result.stderr)
        # -E drops PYTHONPATH/PYTHONHOME, -P the working directory; -I (and -s) would drop the
        # user site-packages a `pip install --user` OMH lives in.
        self.assertEqual(recorded["argv"][:3], ["-E", "-P", "-c"])
        self.assertIn("from omh.tui.app import main", recorded["argv"][3])
        self.assertFalse({"-I", "-s"} & set(recorded["argv"]))
        self.assertNotIn("PYTHONPATH", recorded["env"])
        self.assertNotIn("NODE_OPTIONS", recorded["env"])
        self.assertEqual(recorded["env"]["OMH_TUI_GATEWAY_PYTHONPATH"], "/hermes/root:/hermes/runtime/site-packages")
        self.assertEqual(recorded["env"]["HERMES_PYTHON"], "/hermes/python")

    def test_the_tui_exit_code_reaches_the_launcher_unchanged(self) -> None:
        for code in (0, 3, launch.FALLBACK_EXIT, 130):
            with self.subTest(code=code), TemporaryDirectory() as tmp:
                sentinel = Path(tmp) / "fallback"
                result, _recorded = self._run_shim(
                    Path(tmp), exit_code=code, extra_env={launch.FALLBACK_SENTINEL_ENV: str(sentinel)}
                )
                self.assertEqual(result.returncode, code)
                # The TUI's own 75 carries its own sentinel; the shim passes the code on and creates nothing.
                self.assertFalse(sentinel.exists())

    def test_an_interpreter_that_cannot_import_omh_asks_for_the_fallback(self) -> None:
        # `-S` leaves site-packages, where this OMH is installed, off the path: `import omh` fails.
        with TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "fallback"
            no_site = _executable(Path(tmp) / "python", f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
            result = subprocess.run(
                ["node", str(launch.FRONTEND_ENTRY)],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "OMH_TUI_PYTHON": str(no_site),
                    launch.FALLBACK_SENTINEL_ENV: str(sentinel),
                },
                capture_output=True, text=True, timeout=30, cwd=tmp,
            )
            self.assertTrue(sentinel.is_file())
        self.assertEqual(result.returncode, launch.FALLBACK_EXIT, result.stderr)
        self.assertIn("could not import", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_an_omh_that_only_the_named_site_holds_is_the_one_the_tui_imports(self) -> None:
        # The npm and Bun launcher's shape (#2168): the interpreter cannot import `omh` by itself, and `omh` names
        # the directory it imported its own package from. `-S` keeps every install of this OMH off the path.
        with TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "fallback"
            no_site = _executable(Path(tmp) / "python", f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
            alone = subprocess.run(
                [str(no_site), "-E", "-P", "-c", "import omh"], capture_output=True, text=True, timeout=30, cwd=tmp
            )
            self.assertNotEqual(alone.returncode, 0, "this interpreter must not import omh by itself")
            result = subprocess.run(
                ["node", str(launch.FRONTEND_ENTRY)],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "OMH_TUI_PYTHON": str(no_site),
                    launch.SITE_ENV: launch.omh_import_root(),
                    launch.FALLBACK_SENTINEL_ENV: str(sentinel),
                },
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, cwd=tmp,
            )
            fell_back = sentinel.is_file()
        self.assertNotIn("could not import", result.stderr)
        # Past the import, `main` itself turns down a stdout that is not a terminal and asks for the fallback.
        self.assertIn("this terminal cannot run the OMH TUI", result.stderr)
        self.assertEqual(result.returncode, launch.FALLBACK_EXIT, result.stderr)
        self.assertTrue(fell_back)

    def _venv_with_a_stub_omh(self, tmp: Path) -> tuple[Path, Path]:
        """An interpreter whose own path imports a stub `omh`, and the directory that stub is in."""
        venv = tmp / "venv"
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, capture_output=True, timeout=120
        )
        python = venv / "bin" / "python"
        purelib = subprocess.run(
            [str(python), "-E", "-P", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return python, _stub_omh(Path(purelib))

    def _run_stub(self, tmp: Path, python: Path, site: Path) -> dict:
        record = tmp / "record.json"
        result = subprocess.run(
            ["node", str(launch.FRONTEND_ENTRY)],
            env={
                "PATH": os.environ.get("PATH", ""),
                "OMH_TUI_PYTHON": str(python),
                launch.SITE_ENV: str(site),
                "STUB_RECORD": str(record),
            },
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, cwd=tmp,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(record.read_text(encoding="utf-8"))

    def test_a_site_the_interpreter_already_imports_omh_from_is_not_added_again(self) -> None:
        with TemporaryDirectory() as tmp:
            python, own = self._venv_with_a_stub_omh(Path(tmp))
            recorded = self._run_stub(Path(tmp), python, own)
        path = [os.path.realpath(entry) for entry in recorded["path"]]
        self.assertEqual(os.path.realpath(Path(recorded["file"]).parents[2]), os.path.realpath(own))
        self.assertEqual(path.count(os.path.realpath(own)), 1)
        self.assertNotEqual(path[0], os.path.realpath(own))
        self.assertFalse(recorded["no_bytecode"])

    def test_the_same_site_named_through_a_link_is_not_added_either(self) -> None:
        # One directory, two spellings (macOS gives /var and /private/var for the same temp directory).
        with TemporaryDirectory() as tmp:
            python, own = self._venv_with_a_stub_omh(Path(tmp))
            alias = Path(tmp) / "alias-site"
            alias.symlink_to(own, target_is_directory=True)
            recorded = self._run_stub(Path(tmp), python, alias)
        self.assertNotIn(str(alias), recorded["path"])
        self.assertFalse(recorded["no_bytecode"])

    def test_the_named_site_wins_over_another_omh_on_the_interpreters_own_path(self) -> None:
        # The TUI runs the `omh` that `omh` ran, not an older install the interpreter would find first; and it
        # writes no bytecode into that directory, which for npm and Bun is a cache checked against a digest.
        with TemporaryDirectory() as tmp:
            python, _own = self._venv_with_a_stub_omh(Path(tmp))
            site = _stub_omh(Path(tmp) / "cache" / "site")
            recorded = self._run_stub(Path(tmp), python, site)
            written = sorted(str(path) for path in site.rglob("__pycache__"))
        self.assertEqual(os.path.realpath(Path(recorded["file"]).parents[2]), os.path.realpath(site))
        self.assertEqual(recorded["path"][0], str(site))
        self.assertTrue(recorded["no_bytecode"])
        self.assertEqual(written, [])

    def test_without_an_interpreter_the_shim_asks_for_the_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "fallback"
            result = subprocess.run(
                ["node", str(launch.FRONTEND_ENTRY)],
                env={"PATH": os.environ.get("PATH", ""), launch.FALLBACK_SENTINEL_ENV: str(sentinel)},
                capture_output=True, text=True, timeout=30,
            )
            self.assertTrue(sentinel.is_file())
        self.assertEqual(result.returncode, launch.FALLBACK_EXIT)
        self.assertIn("OMH_TUI_PYTHON", result.stderr)

    def test_an_interpreter_that_cannot_start_asks_for_the_fallback(self) -> None:
        with TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "fallback"
            result = subprocess.run(
                ["node", str(launch.FRONTEND_ENTRY)],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "OMH_TUI_PYTHON": str(Path(tmp) / "missing-python"),
                    launch.FALLBACK_SENTINEL_ENV: str(sentinel),
                },
                capture_output=True, text=True, timeout=30,
            )
            self.assertTrue(sentinel.is_file())
        self.assertEqual(result.returncode, launch.FALLBACK_EXIT)

    def test_a_kill_that_fails_after_the_child_started_asks_for_no_fallback(self) -> None:
        # Node emits 'error' for a failed kill too. The preload makes every kill fail that way; the SIGTERM sent to
        # the shim alone then reaches only the failing kill, and the child goes on to exit 0 on its own.
        with TemporaryDirectory() as tmp:
            sentinel, started = Path(tmp) / "fallback", Path(tmp) / "started"
            preload = Path(tmp) / "failing-kill.js"
            preload.write_text(
                "const cp = require('node:child_process')\n"
                "const spawn = cp.spawn\n"
                "cp.spawn = function (...args) {\n"
                "  const child = spawn.apply(this, args)\n"
                "  child.kill = () => { process.nextTick(() => child.emit('error', new Error('kill EPERM'))); return false }\n"
                "  return child\n"
                "}\n",
                encoding="utf-8",
            )
            fake_python = _executable(Path(tmp) / "fake-python", f'#!/bin/sh\ntouch "{started}"\nsleep 1\nexit 0\n')
            shim = subprocess.Popen(
                ["node", "-r", str(preload), str(launch.FRONTEND_ENTRY)],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "OMH_TUI_PYTHON": str(fake_python),
                    launch.FALLBACK_SENTINEL_ENV: str(sentinel),
                },
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                deadline = time.monotonic() + 20
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                shim.send_signal(signal.SIGTERM)
                _out, err = shim.communicate(timeout=30)
            finally:
                if shim.poll() is None:  # a failed assertion or a timeout above must not leave node running
                    shim.kill()
                    shim.communicate(timeout=10)
            self.assertFalse(sentinel.exists())
        self.assertEqual(shim.returncode, 0, err)

    def test_a_fallback_without_a_sentinel_name_still_exits_75(self) -> None:
        # `python -m omh.tui` by hand, or a launcher that set no name: the code is the same, no file is made.
        result = subprocess.run(
            ["node", str(launch.FRONTEND_ENTRY)], env={"PATH": os.environ.get("PATH", "")},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, launch.FALLBACK_EXIT)


if __name__ == "__main__":
    unittest.main()


class SessionRecordTests(unittest.TestCase):
    """What the TUI writes to the file `omh` names, and what `omh` reads back from it."""

    def test_the_record_names_the_open_session_and_the_ones_this_launch_had_open_before(self) -> None:
        from test_tui_modes import make_app

        with TemporaryDirectory() as tmp:
            record = Path(tmp) / "session"
            app, _client = make_app(environ={launch.SESSION_FILE_ENV: str(record), "HERMES_HOME": tmp})
            for stored in ("sess-a", "sess-b", "sess-a", "sess-c"):
                app._adopt_stored(stored)
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")),
                             {"session_id": "sess-c", "hermes_home": tmp, "opened": ["sess-a", "sess-b"]})
            self.assertEqual(launch.closed_session(record), ("sess-c", tmp, ("sess-a", "sess-b")))
            record.write_text(json.dumps({"session_id": "s", "hermes_home": tmp, "opened": ["ok", 3, "bad\x1bid", ""]}))
            self.assertEqual(launch.closed_session(record), ("s", tmp, ("ok",)))
