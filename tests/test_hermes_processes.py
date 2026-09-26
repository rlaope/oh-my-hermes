from __future__ import annotations

import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.surfaces.hermes_processes import HERMES_PROCESS_SCHEMA_VERSION, observe_hermes_processes


NOW = datetime(2026, 8, 16, 4, 30, tzinfo=timezone.utc)


class HermesProcessObservationTests(unittest.TestCase):
    def test_real_process_tree_classifies_one_root_and_filters_shell_decoy(self) -> None:
        ps_output = """\
31500 1 /Users/example/.hermes/hermes-agent/venv/bin/python /Users/example/.hermes/hermes-agent/hermes
31548 31500 /opt/homebrew/bin/node --expose-gc /Users/example/.hermes/hermes-agent/ui-tui/dist/entry.js
31549 31548 /Users/example/.hermes/hermes-agent/venv/bin/python -m tui_gateway.entry
31599 1 /bin/bash -c python3 /Users/example/.hermes/hermes-agent/hermes
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(now=NOW, ps_output=ps_output)

        self.assertEqual(result["schema_version"], HERMES_PROCESS_SCHEMA_VERSION)
        self.assertTrue(result["observed"])
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["agent_count"], 1)
        self.assertEqual(result["process_count"], 3)
        self.assertNotIn(31599, {row["pid"] for row in result["rows"]})
        self.assertEqual([row["role"] for row in result["rows"]], ["agent", "child", "child"])
        self.assertEqual(result["observed_at"], "2026-08-16T04:30:00Z")
        self.assertEqual(result["source"], "local_process_scan")
        self.assertEqual(
            result["claim_boundary"],
            "Local process observation is bounded, best-effort, and is not execution, review, CI, or merge evidence.",
        )

    def test_two_independent_roots_are_agents(self) -> None:
        ps_output = """\
41000 1 /usr/bin/python /opt/hermes-agent/hermes
42000 2 /usr/bin/python -m hermes_cli.main gateway run
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 2)
        self.assertEqual(result["process_count"], 2)
        self.assertEqual({row["role"] for row in result["rows"]}, {"agent"})

    def test_ignores_unrelated_commands_with_hermes_path_arguments(self) -> None:
        ps_output = """\
43000 1 /Applications/Electron.app/Contents/MacOS/Electron /Users/u/.hermes/hermes-agent/hermes
43001 1 /Applications/Visual Studio Code.app/Contents/MacOS/Electron --goto /Users/u/.hermes/hermes-agent/hermes
43002 1 /usr/bin/printf /Users/u/.hermes/hermes-agent/hermes
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 0)
        self.assertEqual(result["process_count"], 0)
        self.assertEqual(result["rows"], [])

    def test_quoted_paths_with_spaces_preserve_the_hermes_entrypoint(self) -> None:
        ps_output = (
            '44000 1 "/Users/Example User/.hermes/hermes-agent/venv/bin/python" '
            '"/Users/Example User/.hermes/hermes-agent/hermes"\n'
        )
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 1)
        self.assertEqual(result["process_count"], 1)
        self.assertEqual(result["rows"][0]["label"], "python hermes")

    def test_unquoted_ps_paths_with_spaces_preserve_the_hermes_entrypoint(self) -> None:
        ps_output = (
            "44500 1 python "
            "/tmp/Hermes Bare Space/hermes-agent/hermes --cli\n"
        )
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 1)
        self.assertEqual(result["process_count"], 1)
        self.assertEqual(result["rows"][0]["label"], "python hermes")

    def test_ignores_one_shot_hermes_cli_commands(self) -> None:
        ps_output = """\
45000 1 /usr/bin/python -m hermes_cli.main config check
45001 1 /usr/bin/python -m hermes_cli.main status
45002 1 /usr/bin/python /opt/hermes-agent/hermes doctor
45003 1 /usr/bin/python -m hermes_cli.main gateway status
45004 1 /usr/bin/python -m hermes_cli.main --profile work status
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 0)
        self.assertEqual(result["process_count"], 0)
        self.assertEqual(result["rows"], [])

    def test_profile_selector_before_persistent_command_is_counted(self) -> None:
        ps_output = """\
46000 1 /usr/bin/python -m hermes_cli.main --profile work gateway run
46001 1 /usr/bin/python /opt/hermes-agent/hermes --profile=personal chat
46002 1 /usr/bin/python -m hermes_cli.main -p work gateway run
46003 1 /usr/bin/python /opt/hermes-agent/hermes --profile=personal --tui
46004 1 /usr/bin/python /opt/hermes-agent/hermes --cli
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["agent_count"], 5)
        self.assertEqual(result["process_count"], 5)

    def test_empty_output_is_a_successful_zero_observation(self) -> None:
        result = observe_hermes_processes(now="2026-08-16T04:30:00Z", ps_output="")

        self.assertTrue(result["observed"])
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["agent_count"], 0)
        self.assertEqual(result["process_count"], 0)
        self.assertEqual(result["rows"], [])

    def test_oserror_from_ps_is_classified_as_unavailable(self) -> None:
        with patch("omh.surfaces.hermes_processes.subprocess.run", side_effect=OSError("ps missing")) as run:
            result = observe_hermes_processes(now=NOW)

        run.assert_called_once_with(
            ["ps", "-axo", "pid=,ppid=,command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )
        self.assertFalse(result["observed"])
        self.assertEqual(result["reason"], "ps_unavailable")
        self.assertEqual(result["agent_count"], 0)
        self.assertEqual(result["process_count"], 0)

    def test_nonzero_ps_exit_is_classified_as_unavailable(self) -> None:
        completed = subprocess.CompletedProcess(args=["ps"], returncode=1, stdout="ignored", stderr="denied")
        with patch("omh.surfaces.hermes_processes.subprocess.run", return_value=completed):
            result = observe_hermes_processes(now=NOW)

        self.assertFalse(result["observed"])
        self.assertEqual(result["reason"], "ps_unavailable")

    def test_filters_search_commands_and_observer_processes(self) -> None:
        ps_output = """\
51000 1 /usr/bin/grep hermes-agent/hermes
51001 1 /opt/homebrew/bin/rg hermes_cli.main
51002 1 /usr/bin/python /opt/hermes-agent/hermes
51003 1 /usr/bin/python /opt/hermes-agent/hermes
"""
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=51002), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=51003
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["rows"], [])

    def test_labels_use_entrypoint_basenames(self) -> None:
        ps_output = (
            "61000 1 /opt/homebrew/bin/node "
            "/a/path/that/is/longer/than/the/display/limit/ui-tui/dist/entry.js\n"
        )
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["rows"][0]["label"], "node entry.js")

    def test_published_launcher_runtimes_are_counted(self) -> None:
        # Hermes' published launcher runs `python -I -c <script> <args>`; macOS ps
        # renders the script's newlines as a literal backslash-012.
        script = (
            "import os, re, sys\\012os.environ.pop('PYTHONHOME', None)\\012"
            "sys.path.insert(0, '/Users/u/.hermes/source/hermes-custom')\\012"
            "import hermes_bootstrap\\012"
            "if sys.argv[1:2] == ['--run-module']:\\012    import runpy\\012    sys.exit(0)\\012"
            "from hermes_cli.main import main\\012"
            "sys.argv[0] = re.sub(r'(-script\\\\.pyw|\\\\.exe)?$', '', sys.argv[0])\\012"
            "sys.exit(main())\\012"
        )
        python = "/Users/u/.hermes/tools/python-3.14.7-darwin-arm64/bin/python3"
        runtime = (
            "import os, sys, runpy; os.environ.pop('PYTHONHOME', None); "
            "sys.path.insert(0, '/Users/u/.hermes/source/hermes-custom'); import hermes_bootstrap; "
        )
        ps_output = (
            f"47551 1 /usr/bin/osascript -e do shell script \"exec hermes gateway run\"\n"
            f"47577 47551 {python} -I -c {script} --run-module hermes_cli.stderr_timestamp"
            " --error-log /Users/u/.hermes/logs/gateway.error.log -- /Users/u/.hermes/bin/hermes gateway run\n"
            f"47584 47577 {python} -I -c {script} gateway run --external-supervisor\n"
            f"57697 57649 {python} -I -c {script} serve --host 127.0.0.1 --port 0\n"
            f"57700 57697 {python} -I -c {script} config check\n"
            f"58089 57697 {python} /var/folders/T/hermes_kernel_x/hermes_kernel_runner.py\n"
            f"59000 1 {python} -I -c {runtime}runpy.run_module('hermes_cli.main', run_name='__main__',"
            " alter_sys=True) --profile work gateway run --replace\n"
            f"59001 1 {python} -I -c {runtime}runpy.run_module('hermes_cli.stderr_timestamp',"
            " run_name='__main__', alter_sys=True) -- hermes gateway run\n"
            f"59002 1 {python} -I -c {runtime}runpy.run_module('hermes_cli.main', run_name='__main__',"
            " alter_sys=True) dashboard --port 9119\n"
        )
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual([row["pid"] for row in result["rows"]], [47584, 57697, 59000, 59002])
        self.assertEqual(result["agent_count"], 4)
        self.assertEqual(result["process_count"], 4)
        self.assertEqual({row["label"] for row in result["rows"]}, {"python3 hermes"})

    def test_inline_scripts_without_the_launcher_entrypoint_stay_filtered(self) -> None:
        ps_output = (
            "70000 1 /usr/bin/python3 -c import hermes_cli; print(1) gateway run\n"
            "70001 1 /usr/bin/python3 -c print('from hermes_cli.main import main') serve\n"
            "70002 1 /bin/bash -c python3 -I -c from hermes_cli.main import main\\012sys.exit(main()) serve\n"
        )
        with patch("omh.surfaces.hermes_processes.os.getpid", return_value=90001), patch(
            "omh.surfaces.hermes_processes.os.getppid", return_value=90000
        ):
            result = observe_hermes_processes(ps_output=ps_output)

        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
