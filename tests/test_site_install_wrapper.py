"""`omher.app/install`, the short form of the OMH one-liner, run against a stub installer.

`site/install` is served by the Pages deploy as https://omher.app/install. It
downloads install.sh to a temp file and runs it with only the caller's own
arguments, so `curl -fsSL https://omher.app/install | sh` installs exactly
what the long `raw.githubusercontent.com/.../install.sh | sh` form does. A
stub `curl` on PATH answers the one URL the wrapper may fetch with a stub
installer that records its arguments, so nothing leaves the machine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = PROJECT_ROOT / "site" / "install"
WRAPPER_PS1 = PROJECT_ROOT / "site" / "install.ps1"
INSTALL_SH_URL = "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh"
INSTALL_PS1_URL = "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.ps1"

# Logs the URL, then copies the stub installer to `-o` only for install.sh's
# raw main URL; FAKE_CURL_FAIL is a failed download (curl -f exits 22).
STUB_CURL = """#!/bin/sh
out=""
url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
printf '%s\\n' "$url" >> "$FAKE_LOG/curl"
[ -n "${FAKE_CURL_FAIL:-}" ] && exit 22
[ "$url" = "https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh" ] || exit 22
/bin/cp "$FAKE_NET/install.sh" "$out"
"""

# Records every argument on its own line (none at all is an empty file) and
# exits with FAKE_RC.
STUB_INSTALLER = """#!/bin/sh
: > "$FAKE_LOG/args"
for a in "$@"; do printf '%s\\n' "$a" >> "$FAKE_LOG/args"; done
exit "${FAKE_RC:-0}"
"""


@unittest.skipIf(sys.platform == "win32", "site/install is the POSIX wrapper; site/install.ps1 covers Windows")
class ShortInstallWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.bin = root / "bin"
        self.log = root / "log"
        self.net = root / "net"
        self.tmp = root / "tmp"
        for d in (self.bin, self.log, self.net, self.tmp):
            d.mkdir()
        tools = root / "tools"
        tools.mkdir()
        for name in ("sh", "mktemp", "rm", "cat", "cp"):
            found = shutil.which(name, path="/usr/bin:/bin")
            assert found is not None, name
            (tools / name).symlink_to(found)
        (self.bin / "curl").write_text(STUB_CURL, encoding="utf-8")
        (self.bin / "curl").chmod(0o755)
        (self.net / "install.sh").write_text(STUB_INSTALLER, encoding="utf-8")
        self.path = f"{self.bin}:{tools}"

    def _env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": self.path,
            "TMPDIR": str(self.tmp),
            "FAKE_LOG": str(self.log),
            "FAKE_NET": str(self.net),
            **extra,
        }

    def _run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(WRAPPER), *args], env=self._env(**extra),
            capture_output=True, text=True, timeout=30, check=False,
        )

    def _piped(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        # `curl ... | sh` and `curl ... | sh -s -- <args>`: the script arrives on stdin.
        command = ["sh", "-s", "--", *args] if args else ["sh"]
        return subprocess.run(
            command, input=WRAPPER.read_text(encoding="utf-8"), env=self._env(**extra),
            capture_output=True, text=True, timeout=30, check=False,
        )

    def _args(self) -> list[str]:
        return (self.log / "args").read_text(encoding="utf-8").splitlines()

    def test_the_plain_one_liner_runs_install_sh_with_no_argument(self) -> None:
        result = self._piped()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._args(), [])
        self.assertEqual((self.log / "curl").read_text(encoding="utf-8").splitlines(), [INSTALL_SH_URL])
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_the_callers_arguments_are_forwarded_and_nothing_is_added(self) -> None:
        self.assertEqual(self._run("omher@beta", "two words").returncode, 0)
        self.assertEqual(self._args(), ["omher@beta", "two words"])
        self.assertEqual(self._piped("omher@beta").returncode, 0)
        self.assertEqual(self._args(), ["omher@beta"])

    def test_the_installers_exit_code_is_passed_through(self) -> None:
        self.assertEqual(self._run(FAKE_RC="7").returncode, 7)
        self.assertEqual(self._piped(FAKE_RC="2").returncode, 2)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_a_failed_download_exits_1_and_leaves_no_temp_file(self) -> None:
        result = self._run(FAKE_CURL_FAIL="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not download the OMH installer", result.stderr)
        self.assertFalse((self.log / "args").exists())
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_the_script_runs_from_one_function_called_on_the_last_line(self) -> None:
        # The shell must have read the whole file before the installer reads
        # the same stdin (`curl ... | sh`).
        lines = WRAPPER.read_text(encoding="utf-8").rstrip("\n").splitlines()
        self.assertEqual(lines[0], "#!/bin/sh")
        self.assertEqual(lines[-1], 'omh_install_main "$@"')
        self.assertEqual(lines[-2], "}")
        self.assertEqual(subprocess.run(["sh", "-n", str(WRAPPER)], check=False).returncode, 0)


class ShortInstallWrapperSourceTests(unittest.TestCase):
    def test_both_wrappers_fetch_only_the_main_branch_installer(self) -> None:
        sh_text = WRAPPER.read_text(encoding="utf-8")
        ps1_text = WRAPPER_PS1.read_text(encoding="utf-8")
        code = lambda text: "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
        self.assertEqual(re.findall(r"https://\S+", code(sh_text)), [INSTALL_SH_URL])
        self.assertEqual(re.findall(r"https://[^\s)]+", code(ps1_text)), [INSTALL_PS1_URL])

    def test_the_powershell_wrapper_forwards_args_and_never_exits(self) -> None:
        # `exit` inside `irm | iex` would close the window the user ran it in.
        ps1 = [l for l in WRAPPER_PS1.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
        self.assertEqual(
            ps1,
            [f"& ([scriptblock]::Create((Invoke-RestMethod {INSTALL_PS1_URL}))) @args"],
        )
        self.assertNotIn("omher@beta", "\n".join(ps1))

    def test_pages_serves_the_wrappers_as_committed_files(self) -> None:
        # pages.yml copies site/. verbatim; .nojekyll keeps an extensionless
        # file served as-is.
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("cp -R site/. _site/", workflow)
        self.assertTrue((PROJECT_ROOT / "site" / ".nojekyll").is_file())


if __name__ == "__main__":
    unittest.main()
