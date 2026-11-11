"""apps/omher/scripts/linux-build-deps.sh picks an Ubuntu mirror that answers and never waits unbounded.

The script runs on GitHub's Ubuntu runners before the omher Linux build. These tests drive it with stand-ins
for sudo, timeout, apt-get and curl, so they need bash but no network and no root.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "apps" / "omher" / "scripts" / "linux-build-deps.sh"
RUNNER_LIST = (
    "http://azure.archive.ubuntu.com/ubuntu/\tpriority:1\n"
    "https://archive.ubuntu.com/ubuntu/\tpriority:2\n"
    "https://security.ubuntu.com/ubuntu/\tpriority:3\n"
)
FIRST_FALLBACK = "https://mirrors.edge.kernel.org/ubuntu/"

STUBS = {
    # sudo and timeout only pass the command on; timeout drops its own options and the limit.
    "sudo": '#!/bin/sh\nexec "$@"\n',
    "timeout": '#!/bin/sh\nwhile :; do case "$1" in --*) shift ;; *) break ;; esac; done\nshift\nexec "$@"\n',
    # apt-get records its arguments and the mirror list it would read, and fails when told to.
    "apt-get": (
        "#!/bin/sh\n"
        'echo "apt-get $*" >> "$STUB_LOG"\n'
        'echo "list: $(head -1 "$OMHER_APT_MIRRORS")" >> "$STUB_LOG"\n'
        'case " $* " in *" install "*) [ "${STUB_APT_FAILS:-0}" = "1" ] && exit 100 ;; esac\n'
        "exit 0\n"
    ),
    # curl answers only for URLs that contain one of the words in STUB_UP.
    "curl": (
        "#!/bin/sh\n"
        'for a in "$@"; do url="$a"; done\n'
        'echo "curl $url" >> "$STUB_LOG"\n'
        'for up in $STUB_UP; do case "$url" in *"$up"*) exit 0 ;; esac; done\n'
        "exit 6\n"
    ),
}


@unittest.skipIf(os.name == "nt" or shutil.which("bash") is None, "needs bash on a POSIX host")
class LinuxBuildDepsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="omher-deps-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in STUBS.items():
            path = bin_dir / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.list = self.tmp / "apt-mirrors.txt"
        self.list.write_text(RUNNER_LIST)
        self.os_release = self.tmp / "os-release"
        self.os_release.write_text('VERSION_CODENAME=jammy\nNAME="Ubuntu"\n')
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.bin_dir = bin_dir

    def run_script(self, up: str, apt_fails: bool = False, with_list: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.tmp),
            "TMPDIR": str(self.tmp),
            "OMHER_APT_MIRRORS": str(self.list if with_list else self.tmp / "absent.txt"),
            "OMHER_OS_RELEASE": str(self.os_release),
            "STUB_LOG": str(self.log),
            "STUB_UP": up,
            "STUB_APT_FAILS": "1" if apt_fails else "0",
        }
        return subprocess.run(
            ["bash", str(SCRIPT), "libgtk-3-dev", "file"], env=env, capture_output=True, text=True, timeout=60
        )

    def test_the_runner_mirror_is_used_when_it_answers(self) -> None:
        done = self.run_script(up="azure.archive.ubuntu.com")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.list.read_text(), RUNNER_LIST)
        log = self.log.read_text()
        self.assertIn("curl http://azure.archive.ubuntu.com/ubuntu/dists/jammy/InRelease", log)
        self.assertIn("install -y libgtk-3-dev file", log)
        self.assertNotIn("kernel.org", log)

    def test_a_mirror_that_does_not_answer_is_skipped_before_apt_runs(self) -> None:
        done = self.run_script(up="mirrors.edge.kernel.org")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.list.read_text(), f"{FIRST_FALLBACK}\tpriority:1\n")
        log = self.log.read_text().splitlines()
        first_apt = next(i for i, line in enumerate(log) if line.startswith("apt-get"))
        # apt never ran against the list whose first mirror does not answer
        self.assertTrue(all("azure" not in line for line in log[first_apt:]), log)
        self.assertIn(f"list: {FIRST_FALLBACK}\tpriority:1", log)

    def test_every_apt_call_is_bounded(self) -> None:
        text = SCRIPT.read_text()
        calls = [line for line in text.splitlines() if "apt-get" in line and not line.lstrip().startswith("#")]
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("timeout --kill-after=30", calls[0])

    def test_a_failing_install_moves_on_and_the_list_is_put_back_when_all_fail(self) -> None:
        done = self.run_script(up="azure.archive.ubuntu.com kernel.org mit.edu princeton.edu", apt_fails=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no Ubuntu mirror answered", done.stderr)
        self.assertEqual(self.list.read_text(), RUNNER_LIST)
        self.assertEqual(self.log.read_text().count(" install "), 4)

    def test_no_mirror_answers(self) -> None:
        done = self.run_script(up="nothing-is-up")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.list.read_text(), RUNNER_LIST)
        self.assertNotIn("apt-get", self.log.read_text())

    def test_without_the_runner_list_the_configured_sources_are_used(self) -> None:
        done = self.run_script(up="", with_list=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("install -y libgtk-3-dev file", self.log.read_text())

    def test_the_workflows_install_through_the_script_with_a_step_limit(self) -> None:
        for name in ("omher-ci.yml", "omher-release.yml"):
            text = (REPO_ROOT / ".github" / "workflows" / name).read_text()
            self.assertIn("bash apps/omher/scripts/linux-build-deps.sh", text, name)
            self.assertNotIn("sudo apt-get", text, name)
            step = text.split("Install the Linux build libraries", 1)[1].split("- name:", 1)[0]
            self.assertIn("timeout-minutes:", step, name)


if __name__ == "__main__":
    unittest.main()
