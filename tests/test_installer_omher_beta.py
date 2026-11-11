"""`install.sh` with the `omher@beta` argument: Hermes when missing, OMH, setup, the omher app.

Plain `curl ... | sh` must keep doing exactly what it did before the argument
existed, so the first cases pin that it neither fetches Hermes nor looks for the
app. The rest drive the three starting points (OMH user, Hermes-only user,
neither) through stubs on PATH: `curl`, `bash`'s download, `hdiutil`, `uname`
and every interpreter are fakes, so nothing is downloaded, mounted, or
installed on the machine running the suite.
"""

from __future__ import annotations

import glob
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_ROOT / "install.sh"
ONE_LINER = "curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta"
HERMES_URL = "https://hermes-agent.nousresearch.com/install.sh"
# The absolute paths install.sh probes beyond PATH (HOME-relative ones point
# into the test's temporary home).
HOST_PYTHON_GLOBS = (
    "/opt/homebrew/bin/python3.[0-9]*",
    "/usr/local/bin/python3.[0-9]*",
    "/Library/Frameworks/Python.framework/Versions/*/bin/python3",
)

# Only these host commands are visible; a real `hdiutil`, `uname`, `curl`,
# `ditto` or `xattr` never is.
SYSTEM_TOOLS = (
    "sh", "bash", "awk", "sed", "grep", "tr", "tail", "head", "dirname", "readlink",
    "ln", "mkdir", "cp", "chmod", "rm", "mktemp", "cat", "mv", "shasum", "sha256sum", "perl",
)

# A supported interpreter that stands in for `-m venv`, `-m pip` and
# `-m omh.cli`, logging every omh.cli call so setup and doctor are observable.
STUB_PYTHON = """#!/bin/sh
case "$*" in
  *"import sys; print"*) echo "3.12"; exit 0 ;;
  *"-m omh.cli"*doctor) printf '%s\\n' "$*" >> "$FAKE_LOG/omh-cli"; exit "${FAKE_DOCTOR_STATUS:-0}" ;;
  *"-m omh.cli"*) printf '%s\\n' "$*" >> "$FAKE_LOG/omh-cli"; exit 0 ;;
esac
case "$2" in
  venv)
    mkdir -p "$3/bin"
    cp "$0" "$3/bin/python"
    printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/omh"
    chmod +x "$3/bin/omh"
    exit 0
    ;;
esac
exit 0
"""

# Logs each call (and every argument, so a token on the command line would
# show); answers the Hermes installer, the release pages, the dmg and its
# SHA256SUMS.txt from files the test prepares under $FAKE_NET. `--config -`
# is read from stdin into its own log. FAKE_RELEASES_STATUS makes the API
# answer with that HTTP status instead.
STUB_CURL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/curl-argv"
out=""
url=""
fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -H) shift 2 ;;
    -w) fmt="$2"; shift 2 ;;
    --config) cat >> "$FAKE_LOG/curl-config"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\\n' "$url" >> "$FAKE_LOG/curl"
case "$url" in
  https://hermes-agent.nousresearch.com/install.sh) src="$FAKE_NET/hermes-install.sh" ;;
  https://api.github.com/repos/rlaope/oh-my-hermes/releases*)
    if [ -n "${FAKE_RELEASES_STATUS:-}" ]; then
      printf '{"message":"API rate limit exceeded"}' > "$out"
      printf '%s' "$FAKE_RELEASES_STATUS"
      exit 0
    fi
    page="${url##*page=}"
    src="$FAKE_NET/releases-$page.json"
    [ -f "$src" ] || src="$FAKE_NET/releases.json"
    ;;
  */SHA256SUMS.txt) src="$FAKE_NET/SHA256SUMS.txt" ;;
  *.dmg) src="$FAKE_NET/omher.dmg" ;;
  *.AppImage) src="$FAKE_NET/omher.AppImage" ;;
  */icon.png) src="$FAKE_NET/icon.png" ;;
  *) [ -n "$fmt" ] && printf '404'; exit 22 ;;
esac
[ -f "$src" ] || { [ -n "$fmt" ] && printf '404'; exit 22; }
if [ -n "$out" ]; then /bin/cp "$src" "$out"; else cat "$src"; fi
[ -n "$fmt" ] && printf '200'
exit 0
"""

# `cp` that refuses to copy omher.app when FAKE_CP_FAIL is set (the disk
# filling up mid-copy); every other copy goes through.
STUB_CP = """#!/bin/sh
case "$*" in
  *omher.app*) [ -n "${FAKE_CP_FAIL:-}" ] && exit 1 ;;
esac
exec /bin/cp "$@"
"""

# What Hermes' installer leaves behind: its venv Python, nothing else.
FAKE_HERMES_INSTALLER = """#!/bin/bash
printf '%s\\n' "$*" > "$FAKE_LOG/hermes-installer-args"
mkdir -p "$HOME/.hermes/hermes-agent/venv/bin"
cp "$FAKE_NET/python-stub" "$HOME/.hermes/hermes-agent/venv/bin/python"
chmod +x "$HOME/.hermes/hermes-agent/venv/bin/python"
"""

STUB_HDIUTIL = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/hdiutil"
case "$1" in
  attach)
    mp=""
    while [ $# -gt 0 ]; do
      if [ "$1" = "-mountpoint" ]; then mp="$2"; shift 2; continue; fi
      shift
    done
    mkdir -p "$mp/omher.app/Contents"
    printf 'new\\n' > "$mp/omher.app/Contents/marker"
    ;;
esac
exit 0
"""

STUB_UNAME = """#!/bin/sh
case "$1" in
  -s) echo "${FAKE_UNAME_S:-Darwin}" ;;
  -a) echo "${FAKE_UNAME_S:-Darwin} host 25.0.0 Darwin Kernel ${FAKE_UNAME_M:-arm64}" ;;
  *) echo "${FAKE_UNAME_S:-Darwin}" ;;
esac
"""

STUB_XATTR = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG/xattr"
"""


def _release(tag: str, names: list[str]) -> dict[str, object]:
    return {
        "tag_name": tag,
        "assets": [
            {"name": n, "browser_download_url": f"https://github.com/rlaope/oh-my-hermes/releases/download/{tag}/{n}"}
            for n in names
        ],
    }


DMG = b"not really a dmg"
DMG_SHA256 = hashlib.sha256(DMG).hexdigest()
APPIMAGE = b"\x7fELF not really an AppImage"
APPIMAGE_SHA256 = hashlib.sha256(APPIMAGE).hexdigest()

# Newest first, as the API lists them: an OMH package release ahead of the app's.
RELEASES = [
    _release("v4.0.7", ["oh_my_hermes-4.0.7-py3-none-any.whl"]),
    _release("omher-v0.1.0", [
        "omher-0.1.0-macos-arm64.dmg", "omher-0.1.0-macos-x64.dmg",
        "omher-0.1.0-windows-x64-setup.exe", "omher-0.1.0-windows-x64.msi", "omher-0.1.0-linux-x64.AppImage",
        "SHA256SUMS.txt",
    ]),
]


@unittest.skipIf(sys.platform == "win32", "install.sh is the POSIX installer; install.ps1 covers Windows")
class OmherBetaInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "log"
        self.log.mkdir()
        self.net = self.root / "net"
        self.net.mkdir()
        (self.root / "tmp").mkdir()
        self.apps = self.root / "Applications"
        tools = self.root / "tools"
        tools.mkdir()
        for name in SYSTEM_TOOLS:
            found = shutil.which(name, path="/usr/bin:/bin")
            if found is not None:
                (tools / name).symlink_to(found)
        self.tools = tools
        for name, body in (
            ("curl", STUB_CURL), ("hdiutil", STUB_HDIUTIL), ("uname", STUB_UNAME), ("xattr", STUB_XATTR),
            ("cp", STUB_CP),
        ):
            self._write(self.bin / name, body)
        self._write(self.net / "python-stub", STUB_PYTHON)
        self._write(self.net / "hermes-install.sh", FAKE_HERMES_INSTALLER)
        (self.net / "omher.dmg").write_bytes(DMG)
        (self.net / "omher.AppImage").write_bytes(APPIMAGE)
        (self.net / "icon.png").write_bytes(b"png")
        self._sums(DMG_SHA256)
        (self.net / "releases.json").write_text(json.dumps(RELEASES), encoding="utf-8")

    def _sums(self, digest: str) -> None:
        (self.net / "SHA256SUMS.txt").write_text(
            "".join(f"{digest}  {name}\n" for name in ("omher-0.1.0-macos-arm64.dmg", "omher-0.1.0-macos-x64.dmg"))
            + f"{'0' * 64}  omher-0.1.0-windows-x64-setup.exe\n"
            + f"{APPIMAGE_SHA256}  omher-0.1.0-linux-x64.AppImage\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write(path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    def _system_python(self) -> None:
        self._write(self.bin / "python3.12", STUB_PYTHON)

    def _existing_hermes(self) -> None:
        venv = self.home / ".hermes" / "hermes-agent" / "venv" / "bin"
        venv.mkdir(parents=True)
        self._write(venv / "python", STUB_PYTHON)

    def _existing_omh(self) -> None:
        venv = self.home / ".local" / "share" / "omh" / "venv" / "bin"
        venv.mkdir(parents=True)
        self._write(venv / "omh", "#!/bin/sh\nexit 0\n")

    def _run(self, *args: str, **environment: str) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{self.tools}",
            "TMPDIR": str(self.root / "tmp"),
            "OMH_PACKAGE_URL": str(self.root / "oh_my_hermes-0-py3-none-any.whl"),
            "OMH_LINK_COMMAND": "0",
            "OMH_APP_DIR": str(self.apps),
            "FAKE_LOG": str(self.log),
            "FAKE_NET": str(self.net),
            "NO_COLOR": "1",
            **environment,
        }
        return subprocess.run(
            ["sh", str(INSTALLER), *args], env=env, capture_output=True, text=True, timeout=120, check=False,
        )

    def _calls(self, name: str) -> list[str]:
        path = self.log / name
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def _dmg_call(self) -> str:
        return next(u for u in self._calls("curl") if u.endswith(".dmg"))

    def _setup_ran(self) -> bool:
        return any(" -m omh.cli setup " in f" {line} " for line in self._calls("omh-cli"))

    def _assert_app_installed(self, result: subprocess.CompletedProcess[str]) -> None:
        marker = self.apps / "omher.app" / "Contents" / "marker"
        self.assertTrue(marker.is_file(), result.stdout + result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8").strip(), "new")
        self.assertIn(f"-dr com.apple.quarantine {self.apps}/omher.app", self._calls("xattr"))
        hdiutil = self._calls("hdiutil")
        self.assertEqual([c.split()[0] for c in hdiutil], ["attach", "detach"], hdiutil)
        self.assertIn("-nobrowse", hdiutil[0])

    # -- the plain one-liner is unchanged ------------------------------------------------------

    def test_without_the_argument_nothing_new_happens(self) -> None:
        self._system_python()
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._calls("curl"), [])
        self.assertEqual(self._calls("hdiutil"), [])
        self.assertFalse(self._setup_ran())
        self.assertFalse((self.apps / "omher.app").exists())
        self.assertNotIn("omher", result.stdout)

    def test_the_opt_out_variables_alone_do_not_switch_anything_on(self) -> None:
        self._system_python()
        result = self._run(OMH_WITH_DESKTOP="1", OMH_WITH_HERMES="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._calls("curl"), [])
        self.assertFalse(self._setup_ran())

    def test_an_unknown_argument_is_refused_before_any_work(self) -> None:
        self._system_python()
        result = self._run("omher@stable")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown argument 'omher@stable'", result.stderr)
        self.assertIn(ONE_LINER, result.stderr)
        self.assertEqual(self._calls("curl"), [])
        self.assertFalse((self.home / ".local" / "share" / "omh" / "venv").exists())

    # -- the three starting points --------------------------------------------------------------

    def test_an_existing_omh_user_is_upgraded_and_gets_the_app_without_a_new_setup(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("found Hermes and OMH", result.stdout)
        self.assertNotIn(HERMES_URL, self._calls("curl"))
        self.assertFalse(self._setup_ran())
        self._assert_app_installed(result)
        self.assertTrue(self._dmg_call().endswith("/omher-v0.1.0/omher-0.1.0-macos-arm64.dmg"), self._calls("curl"))

    def test_a_hermes_user_without_omh_gets_omh_setup_and_the_app(self) -> None:
        self._system_python()
        self._existing_hermes()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("found Hermes without OMH", result.stdout)
        self.assertNotIn(HERMES_URL, self._calls("curl"))
        self.assertTrue(self._setup_ran(), self._calls("omh-cli"))
        self.assertTrue(any(line.endswith(" doctor") for line in self._calls("omh-cli")))
        self._assert_app_installed(result)

    def test_a_machine_with_neither_installs_hermes_first(self) -> None:
        self._system_python()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("found neither Hermes nor OMH", result.stdout)
        curls = self._calls("curl")
        self.assertEqual(curls[0], HERMES_URL)
        self.assertEqual(self._calls("hermes-installer-args"), ["--non-interactive"])
        self.assertTrue(self._setup_ran())
        self._assert_app_installed(result)
        # the model is picked in the app, not in a terminal
        self.assertIn("pick a model from the model menu", result.stdout)
        self.assertNotIn("hermes setup", result.stdout)
        # Hermes came first: its installer ran before the OMH venv existed.
        self.assertLess(result.stdout.index("Install Hermes Agent"), result.stdout.index("Install OMH package"))

    @unittest.skipIf(
        any(glob.glob(p) for p in HOST_PYTHON_GLOBS),
        "this host has an interpreter install.sh probes by absolute path, which would be chosen first",
    )
    def test_with_no_python_at_all_omh_builds_on_the_python_hermes_brought(self) -> None:
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Python: {self.home}/.hermes/hermes-agent/venv/bin/python", result.stdout)
        self._assert_app_installed(result)

    def test_omh_with_hermes_0_skips_the_hermes_install(self) -> None:
        self._system_python()
        result = self._run("omher@beta", OMH_WITH_HERMES="0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(HERMES_URL, self._calls("curl"))
        self.assertIn("OMH_WITH_HERMES=0 skips it", result.stdout)
        self.assertFalse(self._setup_ran())

    # -- the desktop phase -------------------------------------------------------------------------

    def test_an_older_app_is_replaced(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        old = self.apps / "omher.app" / "Contents"
        old.mkdir(parents=True)
        (old / "stale").write_text("old\n", encoding="utf-8")
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Replacing the omher.app", result.stdout)
        self.assertFalse((old / "stale").exists())
        self._assert_app_installed(result)

    def test_intel_macs_get_the_x64_image(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta", FAKE_UNAME_M="x86_64")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self._dmg_call().endswith("/omher-0.1.0-macos-x64.dmg"), self._calls("curl"))

    def test_pretty_printed_api_json_is_read_too(self) -> None:
        (self.net / "releases.json").write_text(json.dumps(RELEASES, indent=2), encoding="utf-8")
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self._assert_app_installed(result)

    def test_no_omher_release_yet_is_a_note_not_a_failure(self) -> None:
        (self.net / "releases.json").write_text(json.dumps(RELEASES[:1]), encoding="utf-8")
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No omher release was found", result.stdout)
        self.assertIn("https://omher.app/", result.stdout)
        self.assertEqual(self._calls("hdiutil"), [])

    def test_omh_with_desktop_0_installs_hermes_and_omh_only(self) -> None:
        self._system_python()
        result = self._run("omher@beta", OMH_WITH_DESKTOP="0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._calls("curl"), [HERMES_URL])
        self.assertTrue(self._setup_ran())
        self.assertEqual(self._calls("hdiutil"), [])
        self.assertIn("OMH_WITH_DESKTOP=0", result.stdout)
        # this is the app's own Install button: the app is where the model gets picked
        self.assertIn("pick a model from the model menu", result.stdout)
        self.assertNotIn("hermes setup", result.stdout)

    def _linux(self, **environment: str) -> subprocess.CompletedProcess[str]:
        self._system_python()
        self._existing_hermes()
        env = {"FAKE_UNAME_S": "Linux", "FAKE_UNAME_M": "x86_64", "XDG_DATA_HOME": str(self.root / "share")}
        env.update(environment)
        return self._run("omher@beta", **env)

    def test_linux_installs_the_appimage_with_a_menu_entry(self) -> None:
        result = self._linux()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        app = self.apps / "omher"
        self.assertEqual(app.read_bytes(), APPIMAGE)
        self.assertTrue(app.stat().st_mode & 0o111, oct(app.stat().st_mode))
        self.assertTrue(any(u.endswith("/omher-v0.1.0/omher-0.1.0-linux-x64.AppImage") for u in self._calls("curl")))
        desktop = (self.root / "share" / "applications" / "omher.desktop").read_text(encoding="utf-8")
        self.assertIn(f'Exec="{app}" %U\n', desktop)
        self.assertIn("Icon=omher\n", desktop)
        self.assertTrue((self.root / "share" / "icons" / "hicolor" / "512x512" / "apps" / "omher.png").is_file())
        self.assertEqual(self._calls("hdiutil"), [])
        self.assertTrue(self._setup_ran())
        self.assertIn("Open it from your app menu", result.stdout)
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), ["omher"])

    def test_linux_without_app_dir_uses_local_bin(self) -> None:
        result = self._linux(OMH_APP_DIR="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.home / ".local" / "bin" / "omher").read_bytes(), APPIMAGE)

    def test_linux_refuses_an_appimage_that_does_not_match_sha256sums(self) -> None:
        self.apps.mkdir()
        (self.apps / "omher").write_bytes(b"old")
        (self.net / "omher.AppImage").write_bytes(b"tampered")
        result = self._linux()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("does not match SHA256SUMS.txt", result.stdout)
        self.assertEqual((self.apps / "omher").read_bytes(), b"old")
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), ["omher"])

    def test_linux_on_arm_skips_the_app_with_a_note(self) -> None:
        result = self._linux(FAKE_UNAME_M="aarch64")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("x86_64 only", result.stdout)
        self.assertFalse(self.apps.exists())
        self.assertTrue(self._setup_ran())

    def test_a_doctor_complaint_after_a_fresh_hermes_does_not_cost_the_app(self) -> None:
        self._system_python()
        result = self._run("omher@beta", FAKE_DOCTOR_STATUS="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("omh doctor reported problems", result.stdout)
        self._assert_app_installed(result)

    def test_a_failed_copy_keeps_the_existing_app(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        old = self.apps / "omher.app" / "Contents"
        old.mkdir(parents=True)
        (old / "stale").write_text("old\n", encoding="utf-8")
        result = self._run("omher@beta", FAKE_CP_FAIL="1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Could not copy omher.app", result.stdout)
        self.assertEqual((old / "stale").read_text(encoding="utf-8"), "old\n")
        self.assertEqual(sorted(p.name for p in self.apps.iterdir()), ["omher.app"])

    def test_the_image_is_checked_against_sha256sums(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SHA-256 matches SHA256SUMS.txt (omher-0.1.0-macos-arm64.dmg)", result.stdout)
        self.assertIn(
            "https://github.com/rlaope/oh-my-hermes/releases/download/omher-v0.1.0/SHA256SUMS.txt", self._calls("curl"),
        )

    def test_a_checksum_mismatch_stops_before_anything_is_mounted(self) -> None:
        self._sums("f" * 64)
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("does not match SHA256SUMS.txt", result.stdout)
        self.assertEqual(self._calls("hdiutil"), [])
        self.assertFalse((self.apps / "omher.app").exists())

    def test_the_release_lookup_reads_one_small_page_and_stops(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        api = [u for u in self._calls("curl") if u.startswith("https://api.github.com/")]
        self.assertEqual(api, ["https://api.github.com/repos/rlaope/oh-my-hermes/releases?per_page=10&page=1"])
        self.assertTrue(any("--compressed" in line for line in self._calls("curl-argv")))

    def test_an_omher_release_behind_ten_package_releases_is_still_found(self) -> None:
        packages = [_release(f"v4.1.{i}", [f"oh_my_hermes-4.1.{i}-py3-none-any.whl"]) for i in range(10)]
        (self.net / "releases-1.json").write_text(json.dumps(packages), encoding="utf-8")
        (self.net / "releases-2.json").write_text(json.dumps(RELEASES), encoding="utf-8")
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        api = [u for u in self._calls("curl") if u.startswith("https://api.github.com/")]
        self.assertEqual([u.rsplit("=", 1)[1] for u in api], ["1", "2"])
        self._assert_app_installed(result)

    def test_a_rate_limited_api_fails_loudly_instead_of_skipping_the_app(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta", FAKE_RELEASES_STATUS="403")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("rate limit", result.stdout)
        self.assertIn("GITHUB_TOKEN", result.stdout)
        self.assertEqual(self._calls("hdiutil"), [])

    def test_github_token_is_sent_through_curl_config_not_argv(self) -> None:
        self._system_python()
        self._existing_hermes()
        self._existing_omh()
        result = self._run("omher@beta", GITHUB_TOKEN="ghs_example_not_real")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('header = "Authorization: Bearer ghs_example_not_real"', self._calls("curl-config"))
        self.assertFalse(any("ghs_example_not_real" in line for line in self._calls("curl-argv")))
        self.assertNotIn("ghs_example_not_real", result.stdout + result.stderr)

    # -- a profile HERMES_HOME ----------------------------------------------------------------------

    def test_a_profile_hermes_home_finds_hermes_under_its_root(self) -> None:
        self._system_python()
        self._existing_hermes()
        (self.home / ".hermes" / "config.yaml").write_text("model: x\n", encoding="utf-8")
        profile = self.home / ".hermes" / "profiles" / "kami"
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text("model: y\n", encoding="utf-8")
        result = self._run("omher@beta", HERMES_HOME=str(profile), OMH_WITH_DESKTOP="0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("found Hermes without OMH", result.stdout)
        self.assertNotIn(HERMES_URL, self._calls("curl"))
        self.assertFalse((profile / "hermes-agent").exists())

    def test_a_profiles_folder_without_a_root_config_is_taken_as_given(self) -> None:
        # the same rule as the bridge: no <root>/config.yaml, no mapping
        self._system_python()
        self._existing_hermes()
        home = self.root / "elsewhere" / "profiles" / "kami"
        home.mkdir(parents=True)
        result = self._run("omher@beta", HERMES_HOME=str(home), OMH_WITH_DESKTOP="0")
        self.assertIn("found neither Hermes nor OMH", result.stdout)
        self.assertEqual(self._calls("curl")[0], HERMES_URL)

    def test_a_failed_hermes_download_stops_before_omh(self) -> None:
        (self.net / "hermes-install.sh").unlink()
        result = self._run("omher@beta")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(f"Could not download {HERMES_URL}", result.stdout)
        self.assertFalse((self.home / ".local" / "share" / "omh" / "venv").exists())


if __name__ == "__main__":
    unittest.main()
