"""Real per-arm Hermes homes for confirmed paired-run evaluation.

A fake `hermes` stands in for both processes the harness starts: `gateway run
--quiet` writes `gateway.pid` and keeps a grandchild in its process group;
`chat --query-file -` records its argv, home and environment names.
"""

from __future__ import annotations

import ast
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import textwrap
import time
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.hermes_child_arm_setup import ArmSetup, observe_arm_setup  # noqa: E402
from omh.coding.hermes_child_dispatch import (  # noqa: E402
    HermesChildObservation,
    HermesChildRequest,
    dispatch_hermes_child,
)
from omh.coding.hermes_child_receipts import (  # noqa: E402
    ReceiptVerificationError,
    load_hermes_child_receipt,
    write_signed_observation,
)
from omh.coding.paired_run_arm_home import (  # noqa: E402
    PairedRunArmHomeError,
    arm_root_parent,
    prepare_arm_home,
    validate_provider_config,
)
from omh.coding.paired_run_execution import (  # noqa: E402
    PairedRunExecutionFanInError,
    build_paired_run_execution_decision,
)
from omh.coding.paired_run_execution_fan_in import arm_setup_error  # noqa: E402
from omh.coding.routing_observation import (  # noqa: E402
    authenticate_child_observation,
    build_routing_observation,
)
from omh.quality.paired_run_model import ArmRole  # noqa: E402
from omh.quality.paired_run_values import exposure_digest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
KEY_ENV = "OMH_TEST_PAIRED_PROVIDER_KEY"
KEY_VALUE = "sk-test-paired-key-value-7f1c2d9e"

_FAKE = r"""
import json, os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[0]).resolve().parent
args = sys.argv[1:]
home = Path(os.environ["HERMES_HOME"])
if args[:2] == ["gateway", "run"]:
    if (root / "gateway-exits").exists():
        sys.exit(1)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with (root / "gateways.jsonl").open("a") as handle:
        handle.write(json.dumps({"argv": args, "home": str(home), "pid": os.getpid(),
                                 "grandchild": child.pid, "env": sorted(os.environ),
                                 "key": os.environ.get("%(key)s", "")}) + "\n")
    (home / "gateway.pid").write_text(str(os.getpid()))
    while True:
        time.sleep(0.2)
prompt = sys.stdin.read()
with (root / "chats.jsonl").open("a") as handle:
    handle.write(json.dumps({"argv": args, "home": str(home), "env": sorted(os.environ),
                             "safe": os.environ.get("HERMES_SAFE_MODE"),
                             "ignore_config": os.environ.get("HERMES_IGNORE_USER_CONFIG"),
                             "warmup": "READY" in prompt}) + "\n")
if "READY" in prompt:
    time.sleep(float((root / "warm-seconds").read_text()) if (root / "warm-seconds").exists() else 0)
    sys.exit(1 if (root / "warm-fails").exists() else 0)
print("done")
""" % {"key": KEY_ENV}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return waited == 0


@unittest.skipIf(os.name == "nt", "POSIX process groups")
class PairedRunArmHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory(prefix="omh-arm-home-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(f"#!{sys.executable}\n" + textwrap.dedent(_FAKE).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.parent = self.root / "arms"
        self.parent.mkdir()
        self.env = {"PATH": os.environ.get("PATH", os.defpath), KEY_ENV: KEY_VALUE,
                    "OTHER_API_KEY": "sk-unrelated-should-not-travel"}
        self.provider = validate_provider_config(
            "claude-proxy", "http://127.0.0.1:8317/v1", "chat_completions", KEY_ENV, env=self.env
        )

    def _prepare(self, role: str, skills: tuple[str, ...], plugin: bool, **extra: object):
        run = prepare_arm_home(
            role, provider="claude-proxy", model="claude-sonnet-5-5", reasoning="low",
            hermes=str(self.hermes), provider_config=self.provider, exposed_skills=skills,
            omh_plugin=plugin, parent=self.parent, ready_seconds=10, warmup_timeout_seconds=10,
            env=self.env, **extra,
        )
        self.addCleanup(run.close)
        return run

    def _lines(self, name: str) -> list[dict[str, object]]:
        path = self.root / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_variant_home_holds_plugin_and_exactly_its_skills_and_baseline_holds_neither(self) -> None:
        variant = self._prepare("variant", ("code-review", "verification-gate"), True)
        baseline = self._prepare("baseline", (), False)
        vhome, bhome = variant.arm_home.hermes_home, baseline.arm_home.hermes_home
        self.assertTrue((vhome / "plugins" / "omh" / "plugin.yaml").is_file())
        self.assertEqual(sorted(p.name for p in (vhome / "skills").iterdir()),
                         ["omh-code-review", "omh-verification-gate"])
        config = json.loads((vhome / "config.yaml").read_text())
        self.assertEqual(config["plugins"]["enabled"], ["omh"])
        self.assertEqual(config["plugins"]["entries"]["omh"]["settings"]["omh_home"],
                         str(variant.arm_home.root / "omh"))
        self.assertEqual(variant.setup, ArmSetup(True, exposure_digest(("code-review", "verification-gate"))))
        self.assertFalse((bhome / "plugins").exists())
        self.assertEqual(list((bhome / "skills").iterdir()), [])
        self.assertNotIn("plugins", json.loads((bhome / "config.yaml").read_text()))
        self.assertEqual(baseline.setup, ArmSetup(False, exposure_digest(())))
        for home in (vhome, bhome):
            config = json.loads((home / "config.yaml").read_text())
            self.assertEqual(config["model"], {"default": "claude-sonnet-5-5", "provider": "claude-proxy"})
            self.assertEqual(config["providers"]["claude-proxy"]["key_env"], KEY_ENV)
            self.assertNotIn("profiles", home.resolve().parts)

    def test_setup_is_observed_from_disk_not_from_the_request(self) -> None:
        variant = self._prepare("variant", ("code-review",), True)
        (variant.arm_home.hermes_home / "plugins" / "omh" / "plugin.yaml").unlink()
        self.assertFalse(observe_arm_setup(variant.arm_home).omh_plugin)
        baseline = self._prepare("baseline", (), False)
        (baseline.arm_home.hermes_home / "skills" / "omh-code-review").mkdir()
        (baseline.arm_home.hermes_home / "skills" / "omh-code-review" / "SKILL.md").write_text("x")
        # An unlisted label is not an OMH skill this home was declared to hold.
        self.assertEqual(observe_arm_setup(baseline.arm_home).exposure_digest, exposure_digest(()))

    def test_gateway_gets_minimal_env_key_by_name_and_no_secret_reaches_disk(self) -> None:
        run = self._prepare("variant", ("code-review",), True)
        gateway = self._lines("gateways.jsonl")[0]
        self.assertEqual(gateway["argv"], ["gateway", "run", "--quiet"])
        self.assertEqual(gateway["key"], KEY_VALUE)
        self.assertNotIn("OTHER_API_KEY", gateway["env"])
        self.assertIn("OMH_ISOLATED_HERMES_PARENT", gateway["env"])
        for path in run.arm_home.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(KEY_VALUE.encode(), path.read_bytes(), str(path))

    def test_cells_run_without_safe_mode_in_the_arm_home_and_warmup_is_not_timed(self) -> None:
        (self.root / "warm-seconds").write_text("0.6")
        run = self._prepare("variant", ("code-review",), True)
        self.assertGreaterEqual(run.warmup_seconds, 0.6)
        events: list[HermesChildObservation] = []
        dispatch_hermes_child(
            HermesChildRequest(
                prompt="cell task", model="claude-sonnet-5-5", provider="claude-proxy", reasoning="low",
                parent_run_id="decision", run_id="cell-1", timeout_seconds=10, hermes=str(self.hermes),
                cwd=self.root, env=self.env, allow_parallel=True, arm_home=run.arm_home,
            ),
            dispatch_policy="ask_before_dispatch", confirmed=True, observe=events.append,
        )
        terminal = events[-1]
        self.assertEqual(terminal.status, "completed")
        self.assertLess(terminal.elapsed_seconds, 0.6, "warm-up seconds stay outside the cell clock")
        self.assertEqual(terminal.arm_setup, run.setup)
        cell = [line for line in self._lines("chats.jsonl") if not line["warmup"]][0]
        self.assertEqual(cell["home"], str(run.arm_home.hermes_home))
        self.assertIsNone(cell["safe"])
        self.assertIsNone(cell["ignore_config"])
        self.assertEqual(cell["argv"][10:], ["--ignore-rules", "--toolsets", "file,skills"])
        self.assertNotIn("--safe-mode", cell["argv"])
        self.assertIn(KEY_ENV, cell["env"])
        self.assertNotIn("OTHER_API_KEY", cell["env"])

    def test_gateway_group_is_stopped_and_root_removed_when_warmup_fails(self) -> None:
        (self.root / "warm-fails").write_text("1")
        with self.assertRaises(PairedRunArmHomeError):
            self._prepare("variant", ("code-review",), True)
        gateway = self._lines("gateways.jsonl")[0]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _alive(int(gateway["grandchild"])):
            time.sleep(0.05)
        self.assertFalse(_alive(int(gateway["pid"])))
        self.assertFalse(_alive(int(gateway["grandchild"])))
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_close_stops_the_whole_gateway_group(self) -> None:
        run = self._prepare("baseline", (), False)
        gateway = self._lines("gateways.jsonl")[0]
        self.assertTrue(_alive(int(gateway["grandchild"])))
        self.assertTrue(run.close())
        self.assertFalse(_alive(int(gateway["pid"])))
        self.assertFalse(_alive(int(gateway["grandchild"])))
        self.assertFalse(run.arm_home.root.exists())

    def test_gateway_that_exits_before_ready_is_an_infra_failure(self) -> None:
        (self.root / "gateway-exits").write_text("1")
        with self.assertRaisesRegex(PairedRunArmHomeError, "exited with status 1"):
            self._prepare("baseline", (), False)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_unknown_exposed_skill_is_refused(self) -> None:
        with self.assertRaisesRegex(PairedRunArmHomeError, "not packaged OMH skills"):
            self._prepare("variant", ("no-such-skill",), True)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_arm_root_skips_a_profiles_ancestor(self) -> None:
        profiled = self.root / "profiles" / "p" / "tmp"
        profiled.mkdir(parents=True)
        self.assertEqual(arm_root_parent((str(profiled), str(self.parent))), self.parent)


class ProviderConfigTests(unittest.TestCase):
    ENV = {KEY_ENV: KEY_VALUE}

    def test_builtin_provider_declares_nothing(self) -> None:
        self.assertIsNone(validate_provider_config("anthropic", "", "", "", env=self.ENV))

    def test_refusals(self) -> None:
        cases = (
            (("p", "http://127.0.0.1:1/v1", "chat_completions", ""), "together"),
            (("p", "http://127.0.0.1:1/v1", "chat_completions", "sk-inline-key-1234"), "name an environment variable"),
            (("p", "http://127.0.0.1:1/v1", "chat_completions", "UNSET_KEY_NAME"), "not set"),
            (("p", "http://10.0.0.5/v1", "chat_completions", KEY_ENV), "loopback"),
            (("p", "http://example.com/v1", "chat_completions", KEY_ENV), "loopback"),
            (("p", "https://user:pw@example.com/v1", "chat_completions", KEY_ENV), "credentials"),
            (("p", "https://example.com/v1?key=1", "chat_completions", KEY_ENV), "query"),
            (("p", "https://example.com/v1", "telepathy", KEY_ENV), "api-mode"),
            (("Bad Name", "https://example.com/v1", "chat_completions", KEY_ENV), "plain provider name"),
        )
        for args, message in cases:
            with self.subTest(args=args), self.assertRaisesRegex(PairedRunArmHomeError, message):
                validate_provider_config(*args, env=self.ENV)

    def test_accepts_https_and_loopback_http(self) -> None:
        for url in ("https://apis.example.com/v1", "http://127.0.0.1:8317/v1", "http://localhost:9/v1", "http://[::1]:9/v1"):
            with self.subTest(url=url):
                self.assertIsNotNone(validate_provider_config("p", url, "chat_completions", KEY_ENV, env=self.ENV))


class ArmSetupReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory(prefix="omh-arm-receipt-")
        self.addCleanup(temp.cleanup)
        self.omh_home = Path(temp.name).resolve() / ".omh"

    def _sign(self, terminal: HermesChildObservation, **extra: object) -> Path:
        run_dir = self.omh_home / "coding" / "hermes-child" / terminal.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = build_routing_observation(
            route={"selected_model": "p/m", "selected_reasoning_effort": "low", "role": "agent_maintainer",
                   "executor_profile": "hermes_child", "chain": []},
            child_dispatch=authenticate_child_observation({"status": terminal.status, "run_id": terminal.run_id}),
            run_id=terminal.run_id,
        )
        payload.update(extra)
        write_signed_observation(run_dir, payload, terminal)
        return run_dir

    def _terminal(self, setup: ArmSetup | None) -> HermesChildObservation:
        events: list[HermesChildObservation] = []
        with TemporaryDirectory(prefix="omh-arm-receipt-cwd-") as raw:
            hermes = Path(raw) / "hermes.py"
            hermes.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\n", encoding="utf-8")
            hermes.chmod(0o755)
            dispatch_hermes_child(
                HermesChildRequest(prompt="x", model="m", provider="p", reasoning="low", parent_run_id="d",
                                   run_id="cell-1", timeout_seconds=10, hermes=str(hermes), cwd=Path(raw)),
                dispatch_policy="ask_before_dispatch", confirmed=True, observe=events.append,
            )
        terminal = events[-1]
        return replace(terminal, arm_setup=setup)

    def test_dispatcher_setup_is_signed_and_a_caller_value_never_survives(self) -> None:
        setup = ArmSetup(True, exposure_digest(("code-review",)))
        self._sign(self._terminal(setup), arm_setup={"omh_plugin": False, "exposure_digest": "0" * 64})
        self.assertEqual(load_hermes_child_receipt(self.omh_home, "cell-1").arm_setup, setup)

    def test_caller_cannot_add_a_setup_to_a_plain_child_receipt(self) -> None:
        self._sign(self._terminal(None), arm_setup={"omh_plugin": True, "exposure_digest": "0" * 64})
        self.assertIsNone(load_hermes_child_receipt(self.omh_home, "cell-1").arm_setup)

    def test_tampered_setup_fails_verification(self) -> None:
        run_dir = self._sign(self._terminal(ArmSetup(False, exposure_digest(()))))
        path = run_dir / "observation.json"
        observation = json.loads(path.read_text())
        observation["arm_setup"]["omh_plugin"] = True
        path.write_text(json.dumps(observation))
        with self.assertRaises(ReceiptVerificationError):
            load_hermes_child_receipt(self.omh_home, "cell-1")


class FanInArmSetupTests(unittest.TestCase):
    def test_arm_setup_error_names_each_mismatch(self) -> None:
        skills = ("code-review",)
        good_variant = ArmSetup(True, exposure_digest(skills))
        good_baseline = ArmSetup(False, exposure_digest(()))
        self.assertIsNone(arm_setup_error(good_variant, ArmRole.VARIANT, skills))
        self.assertIsNone(arm_setup_error(good_baseline, ArmRole.BASELINE, ()))
        self.assertEqual(arm_setup_error(None, ArmRole.VARIANT, skills), "missing signed arm setup")
        self.assertEqual(arm_setup_error(ArmSetup(False, exposure_digest(skills)), ArmRole.VARIANT, skills),
                         "variant arm ran without the OMH plugin")
        self.assertEqual(arm_setup_error(ArmSetup(True, exposure_digest(())), ArmRole.BASELINE, ()),
                         "baseline arm ran with the OMH plugin")
        self.assertEqual(arm_setup_error(ArmSetup(True, exposure_digest(())), ArmRole.VARIANT, skills),
                         "arm setup skills do not match exposed_skills")

    def test_fan_in_refuses_a_matrix_whose_variant_ran_without_the_plugin(self) -> None:
        from paired_run_execution_support import arm_setup_record
        from test_paired_run_execution_fan_in import _execute, _request
        import paired_run_execution_support as support

        original = support.arm_setup_record
        with TemporaryDirectory(prefix="omh-arm-fan-in-") as raw:
            home = (Path(raw) / ".omh").resolve()
            support.arm_setup_record = lambda plugin, skills: arm_setup_record(False, skills)
            try:
                report = _execute(home)
            finally:
                support.arm_setup_record = original
            with self.assertRaises(PairedRunExecutionFanInError) as raised:
                build_paired_run_execution_decision(_request(report), report, home)
        self.assertTrue(raised.exception.blockers)
        self.assertTrue(all(b.endswith("variant arm ran without the OMH plugin")
                            for b in raised.exception.blockers), raised.exception.blockers)


class NonPairedCallersKeepSafeModeTests(unittest.TestCase):
    SANCTIONED = {"src/coding/paired_run_hermes_adapter.py", "src/coding/paired_run_arm_home.py"}

    def test_only_paired_run_passes_an_arm_home(self) -> None:
        offenders = []
        for path in sorted((REPO / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "arm_home":
                    relative = path.relative_to(REPO).as_posix()
                    if relative not in self.SANCTIONED:
                        offenders.append(relative)
        self.assertEqual(offenders, [])
        callers = {"src/commands/hermes_child.py", "src/coding/final_review_local_engine.py",
                   "src/coding/dispatch_failure_recovery.py"}
        for relative in callers:
            self.assertIn("HermesChildRequest(", (REPO / relative).read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "POSIX fake executable")
    def test_request_without_arm_home_keeps_the_safe_mode_argv_and_env(self) -> None:
        with TemporaryDirectory(prefix="omh-safe-mode-") as raw:
            root = Path(raw)
            hermes = root / "hermes.py"
            hermes.write_text(
                f"#!{sys.executable}\nimport json, os, sys\nsys.stdin.read()\n"
                "open(os.path.join(os.path.dirname(sys.argv[0]), 'seen.json'), 'w').write(json.dumps("
                "{'argv': sys.argv[1:], 'safe': os.environ.get('HERMES_SAFE_MODE'),"
                " 'ignore': os.environ.get('HERMES_IGNORE_USER_CONFIG')}))\n",
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            dispatch_hermes_child(
                HermesChildRequest(prompt="x", model="m", provider="p", reasoning="low", parent_run_id="d",
                                   run_id="r", timeout_seconds=10, hermes=str(hermes), cwd=root),
                dispatch_policy="ask_before_dispatch", confirmed=True,
            )
            seen = json.loads((root / "seen.json").read_text())
        self.assertEqual(seen["argv"][10:], ["--safe-mode", "--ignore-user-config", "--ignore-rules", "--toolsets", "file"])
        self.assertEqual((seen["safe"], seen["ignore"]), ("1", "1"))


if __name__ == "__main__":
    unittest.main()
