"""The PR delivery grant and its gate (owner-approved, 2026-11-23).

The contract this file holds:

* the grant is off by default, and every doubt about its file reads as off;
* it is per profile and never read as on for another profile or a delegated child;
* nothing but the person's CLI writes it, and the CLI refuses inside a Hermes session;
* in a session nobody can answer, the never-allowed classes are refused whatever
  the grant says, and the grant-covered ones are refused while it is off;
* in an attended session the gate has no opinion; a cron turn reads as attended;
* "a PR this bot opened" is OMH's record of what `gh pr create` printed;
* the skill text and the boundary statements say the same thing.

Every hook case drives the real `pre_tool_call` / `post_tool_call` entry with
the argument shape Hermes sends, against a temporary OMH home.
"""

from __future__ import annotations

import ast
import io
import json
from types import SimpleNamespace
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands import pr_delivery as pr_delivery_cli  # noqa: E402
from omh.plugin_bundle.omh import pr_delivery  # noqa: E402
from omh.plugin_bundle.omh import pr_delivery_gate as gate  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, session_attendance  # noqa: E402
from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call, pre_tool_call  # noqa: E402
from omh.plugin_bundle.omh.tools.status_tool import omh_status_handler  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SESSION = "20261123_101010_abc123"
URL = "https://github.com/acme/widgets/pull/42"
OPENED = frozenset({("github.com/acme/widgets", 42)})
# Hermes exports these into every command its terminal tool runs; a person's shell has none.
HERMES_SESSION_VARS = ("HERMES_SESSION_ID", "HERMES_SINGLE_QUERY_SESSION")


def _without_hermes_session():
    # Every marker Hermes leaves in a child's environment, so the CLI sees a person's own shell.
    env = {key: value for key, value in os.environ.items()
           if key not in HERMES_SESSION_VARS and not key.startswith("HERMES_SESSION_")
           and key not in ("HERMES_UI_SESSION_ID", "HERMES_CRON_SESSION", "HERMES_AGENT", "HERMES_EXEC_ASK")}
    return mock.patch.dict(os.environ, env, clear=True)


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.home = root / "omh"
        self.hermes = root / "hermes"
        self.other_hermes = root / "hermes-other"
        for path in (self.home / "runtime", self.hermes, self.other_hermes, root / "repo"):
            path.mkdir(parents=True)
        session_attendance.reset_session_attendance()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(session_attendance.reset_session_attendance)
        self.addCleanup(nudge_budget.reset_nudge_budget)
        env = _without_hermes_session()
        env.start()
        self.addCleanup(env.stop)
        cwd = mock.patch.dict(os.environ, {"TERMINAL_CWD": str(root / "repo")})
        cwd.start()
        self.addCleanup(cwd.stop)

    def cli(self, *argv: str, hermes: Path | None = None, typed_yes: bool = True):
        # `on` asks for a yes on the controlling terminal; the test stands in for the person typing it.
        with mock.patch.object(pr_delivery_cli, "confirm_on_terminal", return_value=typed_yes):
            code, stdout, stderr = run_cli(["--omh-home", str(self.home), "--hermes-home",
                                            str(hermes or self.hermes), "capability-policy", "pr-delivery", *argv],
                                           output_json=False)
        return SimpleNamespace(code=code, stdout=stdout, stderr=stderr)

    def grant_on(self, prefix: str = "bot/") -> None:
        result = self.cli("on", "--branch-prefix", prefix, "--json")
        self.assertEqual(result.code, 0, result.stdout + result.stderr)

    def state(self, hermes: Path | None = None) -> dict:
        return pr_delivery.read_grant(self.home, hermes or self.hermes)

    def pre(self, tool: str, args: dict, *, session: str = SESSION) -> dict | None:
        return pre_tool_call(tool_name=tool, args=args, session_id=session, task_id=session, turn_id="turn-1",
                             omh_home=str(self.home), hermes_home=str(self.hermes))

    def terminal(self, command: str, *, session: str = SESSION) -> dict | None:
        return self.pre("terminal", {"command": command}, session=session)


class GrantStoreTests(_Home):
    def test_default_is_off(self):
        status = self.state()
        self.assertEqual(status["state"], "off")
        self.assertEqual(status["reason"], "no_grant_recorded")
        self.assertEqual(status["allowed_actions"], [])

    def test_every_doubt_reads_as_off(self):
        self.grant_on()
        path = pr_delivery.grant_path(self.home, self.hermes)
        good = json.loads(path.read_text(encoding="utf-8"))
        cases = {
            "grant_file_unreadable": "{not json",
            "grant_file_malformed": json.dumps(["on"]),
            "grant_schema_unknown": json.dumps({**good, "schema_version": "omh_pr_delivery_grant/v2"}),
            "grant_names_another_profile": json.dumps({**good, "hermes_home": str(self.other_hermes)}),
            "grant_scope_changed": json.dumps({**good, "allowed_actions": [*good["allowed_actions"], "merge"]}),
            "grant_branch_prefix_invalid": json.dumps({**good, "branch_prefix": "main"}),
            "grant_turned_off": json.dumps({**good, "state": "ON"}),
            "grant_file_too_large": json.dumps({**good, "pad": "x" * pr_delivery.MAX_GRANT_BYTES}),
        }
        for reason, text in cases.items():
            with self.subTest(reason=reason):
                path.write_text(text, encoding="utf-8")
                status = self.state()
                self.assertEqual((status["state"], status["reason"]), ("off", reason))
        path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(self.state()["state"], "on")

    def test_a_grant_is_per_profile_even_in_a_shared_omh_home(self):
        self.grant_on()
        self.assertEqual(self.state()["state"], "on")
        self.assertEqual(self.state(self.other_hermes)["state"], "off")
        # A copy of one profile's file under another profile's name still names its own profile.
        source = pr_delivery.grant_path(self.home, self.hermes)
        pr_delivery.grant_path(self.home, self.other_hermes).write_bytes(source.read_bytes())
        self.assertEqual(self.state(self.other_hermes)["reason"], "grant_names_another_profile")

    def test_branch_prefix_validation(self):
        for good in ("bot/", "omh-bot/", "Bot.1/"):
            self.assertTrue(pr_delivery.valid_branch_prefix(good), good)
        for bad in ("", "bot", "main", "a/b/", "refs/", "/", "-bot/", "bot /", "x" * 41 + "/"):
            self.assertFalse(pr_delivery.valid_branch_prefix(bad), bad)


class CliTests(_Home):
    def test_on_records_a_schema_versioned_artifact_with_its_fixed_scope(self):
        result = self.cli("on", "--branch-prefix", "omh-bot/")
        self.assertEqual(result.code, 0, result.stderr)
        for action in (*pr_delivery.ALLOWED_ACTIONS, *pr_delivery.NEVER_ALLOWED_ACTIONS):
            self.assertIn(action, result.stdout)
        path = pr_delivery.grant_path(self.home, self.hermes)
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], pr_delivery.GRANT_SCHEMA_VERSION)
        self.assertEqual(document["state"], "on")
        self.assertEqual(document["branch_prefix"], "omh-bot/")
        self.assertEqual(document["hermes_home"], pr_delivery.profile_key(self.hermes))
        self.assertTrue(document["granted_at"].endswith("Z"))
        self.assertEqual(document["allowed_actions"], list(pr_delivery.ALLOWED_ACTIONS))
        self.assertEqual(document["never_allowed_actions"], list(pr_delivery.NEVER_ALLOWED_ACTIONS))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_show_on_off_round_trip_in_json(self):
        shown = json.loads(self.cli("show", "--json").stdout)
        self.assertEqual((shown["state"], shown["schema_version"]), ("off", pr_delivery.GRANT_STATUS_SCHEMA_VERSION))
        changed = json.loads(self.cli("on", "--json").stdout)
        self.assertEqual((changed["requested_state"], changed["already_in_state"]), ("on", False))
        self.assertTrue(json.loads(self.cli("on", "--json").stdout)["already_in_state"])
        turned_off = json.loads(self.cli("off", "--json").stdout)
        self.assertEqual(turned_off["grant"]["state"], "off")
        self.assertTrue(turned_off["grant"]["turned_off_at"])
        self.assertTrue(turned_off["grant"]["granted_at"], "off keeps when it had been turned on")
        self.assertEqual(self.state()["reason"], "grant_turned_off")

    def test_on_and_off_refuse_inside_a_hermes_session_and_write_nothing(self):
        for verb in ("on", "off"):
            with self.subTest(verb=verb), mock.patch.dict(os.environ, {"HERMES_SESSION_ID": "s-1"}):
                result = self.cli(verb)
                self.assertEqual(result.code, 2)
                self.assertIn("Only the person", result.stdout)
        self.assertFalse(pr_delivery.grant_path(self.home, self.hermes).exists())

    def test_on_and_off_refuse_on_any_hermes_marker_without_the_session_id(self):
        # `env -u HERMES_SESSION_ID` alone is not enough: the other markers Hermes sets are read too.
        for marker in ("HERMES_AGENT", "HERMES_SESSION_PLATFORM", "HERMES_CRON_SESSION", "HERMES_EXEC_ASK",
                       "HERMES_UI_SESSION_ID", "HERMES_SINGLE_QUERY_SESSION"):
            for verb in ("on", "off"):
                with self.subTest(marker=marker, verb=verb), mock.patch.dict(os.environ, {marker: "1"}):
                    result = self.cli(verb)
                    self.assertEqual(result.code, 2)
                    self.assertIn(marker, result.stdout)
        self.assertFalse(pr_delivery.grant_path(self.home, self.hermes).exists())
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.hermes)}):
            self.assertEqual(self.cli("on").code, 0)  # a person's own HERMES_HOME is not a marker

    def test_on_needs_a_yes_typed_at_the_terminal(self):
        result = self.cli("on", typed_yes=False)
        self.assertEqual(result.code, 2)
        self.assertIn("typed at your own terminal", result.stdout)
        self.assertFalse(pr_delivery.grant_path(self.home, self.hermes).exists())
        # With no controlling terminal (a gateway or cron child) the confirmation is a no.
        with mock.patch("builtins.open", side_effect=OSError("no tty")):
            self.assertFalse(pr_delivery_cli.confirm_on_terminal("yes? "))

    def test_windows_confirmation_uses_the_console_and_never_crashes(self):
        # Runs on every platform through fakes: Windows has no /dev/tty, its console is CONIN$/CONOUT$.
        opened: list[str] = []

        def fake_open(name, *args, **kwargs):
            opened.append(name)
            return io.StringIO("yes\n")

        # Host-independent: Windows and the visible console are faked, so a real Windows runner
        # (whose own console may be hidden) gives the same answer as macOS and Linux.
        with mock.patch.object(pr_delivery_cli, "on_windows", return_value=True), \
                mock.patch.object(pr_delivery_cli, "console_is_visible", return_value=True), \
                mock.patch("builtins.open", fake_open):
            self.assertTrue(pr_delivery_cli.confirm_on_terminal("yes? "))
        self.assertEqual(opened, ["CONOUT$", "CONIN$"])
        with mock.patch.object(pr_delivery_cli, "on_windows", return_value=True), \
                mock.patch.object(pr_delivery_cli, "console_is_visible", return_value=True), \
                mock.patch("builtins.open", side_effect=OSError("no console")):
            self.assertFalse(pr_delivery_cli.confirm_on_terminal("yes? "))

    def test_a_hidden_windows_console_is_a_no_without_waiting(self):
        # Hermes spawns terminal children with CREATE_NO_WINDOW: CONIN$ would open on a console nobody sees.
        with mock.patch.object(pr_delivery_cli, "on_windows", return_value=True), \
                mock.patch.object(pr_delivery_cli, "console_is_visible", return_value=False), \
                mock.patch("builtins.open", side_effect=AssertionError("must not open the console")):
            self.assertFalse(pr_delivery_cli.confirm_on_terminal("yes? "))

    def test_console_visibility_reads_the_window_and_fails_closed(self):
        import ctypes

        def windll(window: int, visible: int, *, raises: bool = False):
            def get_window():
                if raises:
                    raise OSError("no console API")
                return window
            return SimpleNamespace(kernel32=SimpleNamespace(GetConsoleWindow=get_window),
                                   user32=SimpleNamespace(IsWindowVisible=lambda handle: visible))

        cases = ((windll(42, 1), True), (windll(42, 0), False), (windll(0, 1), False),
                 (windll(42, 1, raises=True), False))
        for fake, expected in cases:
            with self.subTest(expected=expected), mock.patch.object(ctypes, "windll", fake, create=True):
                self.assertIs(pr_delivery_cli.console_is_visible(), expected)

    def test_on_windows_the_grant_file_mode_is_not_checked(self):
        # POSIX mode bits mean nothing there: the grant reads as recorded (documented residual).
        self.grant_on()
        path = pr_delivery.grant_path(self.home, self.hermes)
        if os.name == "posix":
            path.chmod(0o666)
        with mock.patch.object(pr_delivery, "MODE_BITS_MEAN_SOMETHING", False):
            status = self.state()
        self.assertEqual((status["state"], status["reason"]), ("on", "granted"))

    def test_a_grant_file_others_can_write_reads_off(self):
        if os.name != "posix":
            self.skipTest("mode bits mean nothing on Windows")
        self.grant_on()
        path = pr_delivery.grant_path(self.home, self.hermes)
        path.chmod(0o666)
        self.assertEqual(self.state()["reason"], "grant_file_not_private")

    def test_an_invalid_prefix_is_refused(self):
        result = self.cli("on", "--branch-prefix", "main")
        self.assertEqual(result.code, 2)
        self.assertFalse(pr_delivery.grant_path(self.home, self.hermes).exists())

    def test_doctor_warns_when_two_granted_profiles_share_a_prefix(self):
        self.grant_on()
        self.cli("on", hermes=self.other_hermes)
        _code, stdout, _stderr = run_cli(["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "doctor",
                                          "--json", "--no-state-write", "--no-personal-files"])
        shared = json.loads(stdout)["pr_delivery"]["shared_prefixes"]
        self.assertEqual([row["branch_prefix"] for row in shared], ["bot/"])
        self.assertEqual(len(shared[0]["profiles"]), 2)

    def test_doctor_lists_the_profiles_whose_grant_is_on(self):
        self.grant_on()
        self.cli("on", hermes=self.other_hermes)
        self.cli("off", hermes=self.other_hermes)
        _code, stdout, _stderr = run_cli(["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "doctor",
                                          "--json", "--no-state-write", "--no-personal-files"])
        delivery = json.loads(stdout)["pr_delivery"]
        self.assertEqual(delivery["this_profile"]["state"], "on")
        states = {row["hermes_home"]: row["state"] for row in delivery["profiles"]}
        self.assertEqual(states, {pr_delivery.profile_key(self.hermes): "on",
                                  pr_delivery.profile_key(self.other_hermes): "off"})


class OnlyThePersonTurnsItOnTests(unittest.TestCase):
    """INVARIANT: no code path can turn the grant on except the person's CLI command."""

    WRITER = "write_pr_delivery_grant"
    CLI_MODULE = ROOT / "src/commands/pr_delivery.py"

    def test_the_writer_is_called_only_by_the_cli_module(self):
        callers = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                name = ""
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if isinstance(node, (ast.ImportFrom, ast.Import)):
                    if any(alias.name == self.WRITER for alias in node.names):
                        callers.append(path.relative_to(ROOT).as_posix())
                if name == self.WRITER:
                    callers.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(sorted(set(callers)), ["src/commands/pr_delivery.py"])

    def test_no_plugin_module_imports_the_cli_or_writes_the_grant_file(self):
        for path in sorted((ROOT / "src/plugin_bundle").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("commands.pr_delivery", text)
                self.assertNotIn(self.WRITER, text)
        # The bundle's own store module only reads the grant; its one writer is the opened-PR record.
        tree = ast.parse((ROOT / "src/plugin_bundle/omh/pr_delivery.py").read_text(encoding="utf-8"))
        writers = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                   and "os.open" in ast.unparse(node)]
        self.assertEqual(writers, ["append_opened_pr"])

    def test_no_skill_tells_the_bot_to_run_the_on_command(self):
        for path in sorted((ROOT / "skills").rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if pr_delivery.TURN_ON_COMMAND not in text:
                continue
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertRegex(text, r"only the person|Only the person")


class AttendedSessionTests(_Home):
    def test_attended_chat_has_no_opinion_on_any_forge_command(self):
        session_attendance.note_session_platform(SESSION, "cli")
        for command in ("git push --force origin HEAD:main", "gh pr merge 42", "git push", "eval git push"):
            with self.subTest(command=command):
                self.assertIsNone(self.terminal(command))

    def test_a_cron_turn_is_held_as_unattended(self):
        # Hermes builds every cron agent with platform="cron", and pre_llm_call
        # records it (`session_attendance.note_session_platform`).
        session = "cron_widgets-pr-42_20261124_101010"
        session_attendance.note_session_platform(session, "cron")
        self.assertEqual(self.terminal("git push origin HEAD:main", session=session)["action"], "block")
        directive = self.terminal("git push origin HEAD:refs/heads/bot/x", session=session)
        self.assertIn("grant is off", directive["message"])
        self.grant_on()
        self.assertIsNone(self.terminal("git push origin HEAD:refs/heads/bot/x", session=session))
        self.assertEqual(self.terminal("gh pr merge 42", session=session)["action"], "block")

    def test_a_session_whose_platform_is_subagent_is_a_child(self):
        self.grant_on()
        session_attendance.note_session_platform("child-2", "subagent")
        directive = self.terminal("git push origin HEAD:refs/heads/bot/x", session="child-2")
        self.assertIn("A delegated child does not carry the PR delivery grant", directive["message"])

    def test_developing_this_repo_through_hermes_is_not_refused(self):
        session_attendance.note_session_platform(SESSION, "cli")
        for command in ("uv run python -m unittest tests/test_pr_delivery_grant.py",
                        "cat src/plugin_bundle/omh/pr_delivery.py", "grep -rn pr_delivery src",
                        'git commit -m "docs: explain pr-delivery on and off"', "grep -rn runtime/pr_ src"):
            with self.subTest(command=command):
                self.assertIsNone(self.terminal(command))

    def test_turning_the_grant_on_or_off_is_refused_in_every_session(self):
        session_attendance.note_session_platform(SESSION, "cli")
        refused = (
            "omh capability-policy pr-delivery on",
            "env -u HERMES_SESSION_ID omh capability-policy pr-delivery on --branch-prefix bot/",
            "uv run python -P -m omh.cli capability-policy pr-delivery off",
            "sh -c 'omh capability-policy pr-delivery on'",
            "echo '{}' > ~/.omh/runtime/pr_delivery/grant-0123456789abcdef.json",
            "echo a#b; env -u HERMES_SESSION_ID omh capability-policy pr-delivery on",
            "X=on; env -u HERMES_SESSION_ID omh capability-policy pr-delivery $X",
            "env -u HERMES_SESSION_ID omh capability-policy pr-delivery $'on'",
            "omh capability-policy pr-delivery `echo on`",
            "printf on | env -u HERMES_SESSION_ID xargs omh capability-policy pr-delivery",
            "P=pr-delivery; omh capability-policy $P on",
            "cat > ~/.omh/runtime/pr_deliv''ery/grant-0123456789abcdef.json < /tmp/forged.json",
            "cp /tmp/forged.json ~/.omh/runtime/pr_*/grant-0123456789abcdef.json",
            "cd ~/.omh/runtime && cp /tmp/f.json pr_deliver?/grant-x.json",
            "echo x >> ~/.omh/runtime/PR_DELIVERY/opened-x.jsonl",
            "ln -s ~/.omh/runtime/pr_deliv''ery /tmp/s",
            "copy f C:\\Users\\u\\.omh\\runtime\\pr_delivery\\grant-0123456789abcdef.json",
        )
        for command in refused:
            with self.subTest(command=command):
                directive = self.terminal(command)
                self.assertIsNotNone(directive)
                self.assertEqual(directive["action"], "block")
                self.assertIn("Only the person", directive["message"])
        for code in ("open('runtime/pr_delivery/grant.json','w').write('{}')",
                     "p = '~/.omh/runtime/pr_' + 'delivery'",
                     "subprocess.run(['omh', 'capability-policy', 'pr-' + 'delivery', 'on'], env={})"):
            with self.subTest(code=code):
                self.assertEqual(self.pre("execute_code", {"code": code})["action"], "block")
        submitted = self.pre("process", {"action": "submit", "session_id": "p1",
                                         "data": "omh capability-policy pr-delivery on"})
        self.assertEqual(submitted["action"], "block")
        # Whatever the verb: the bot reads the grant through omh_status, never the CLI.
        self.assertIsNotNone(self.terminal("omh capability-policy pr-delivery show"))

    def test_a_file_tool_write_into_the_store_is_refused(self):
        target = self.home / "runtime" / "pr_delivery" / "grant-0123456789abcdef.json"
        directive = self.pre("write_file", {"path": str(target), "content": "{}"})
        self.assertEqual(directive["action"], "block")
        self.assertIn("PR delivery grant", directive["message"])


class UnattendedMatrixTests(_Home):
    GRANT_COVERED = (
        "git push origin HEAD:refs/heads/bot/fix-ci",
        "git push -u origin HEAD:bot/fix-ci",
        "git add -A && git commit -m 'fix: ci' && git push origin HEAD:refs/heads/bot/fix-ci",
        "gh pr create --head bot/fix-ci --title 'fix: ci' --body 'Fixes the lint job.'",
        f"gh pr comment {URL} --body 'Round 1 pushed.'",
        "gh pr comment 42 --repo acme/widgets --body 'Round 1 pushed.'",
        "git commit -m \"subject\n\nbody\" && git push origin HEAD:refs/heads/bot/x",
        # A literal backslash escape inside an argument reads the same under Git Bash.
        "git commit -m 'fix\\n\\nbody' && git push origin HEAD:refs/heads/bot/x",
    )
    ALWAYS_REFUSED = {
        "git push --force origin HEAD:refs/heads/bot/fix-ci": gate.FORCE_PUSH,
        "git push -f origin HEAD:bot/x": gate.FORCE_PUSH,
        "git push -uf origin HEAD:bot/x": gate.FORCE_PUSH,
        "git push --force-with-lease origin HEAD:bot/x": gate.FORCE_PUSH,
        "git push --force-with-lease=bot/x:abc123 origin HEAD:bot/x": gate.FORCE_PUSH,
        "git push origin +HEAD:refs/heads/bot/x": gate.FORCE_PUSH,
        "git push origin --delete bot/x": gate.FORCE_PUSH,
        "git push origin :refs/heads/bot/x": gate.FORCE_PUSH,
        "git push --mirror origin": gate.FORCE_PUSH,
        "git push origin HEAD:main": gate.PUSH_OUTSIDE,
        "git push origin HEAD:refs/heads/main": gate.PUSH_OUTSIDE,
        "git push origin main": gate.PUSH_OUTSIDE,
        "git push --all origin": gate.PUSH_OUTSIDE,
        "git push --tags origin": gate.PUSH_OUTSIDE,
        "git push origin HEAD:refs/tags/v1": gate.PUSH_OUTSIDE,
        "git push origin 'HEAD:refs/heads/*'": gate.PUSH_OUTSIDE,
        "git -C /srv/repo push origin HEAD:main": gate.UNCLASSIFIED,
        "git merge bot/x && git push origin HEAD:main": gate.PUSH_OUTSIDE,
        "gh pr merge 42 --squash": gate.FORGE_MERGE,
        f"gh pr merge {URL} --auto --merge": gate.FORGE_MERGE,
        "gh api -X PUT repos/acme/widgets/pulls/42/merge": gate.FORGE_MERGE,
        "gh api repos/acme/widgets/merges -f base=main -f head=bot/x": gate.FORGE_MERGE,
        "gh pr create --repo other/repo --head bot/x --title t --body b": gate.OTHER_PR_OR_REPO,
        "gh pr create --head someone:bot/x --title t --body b": gate.OTHER_PR_OR_REPO,
        "gh pr create --head feature/x --title t --body b": gate.PUSH_OUTSIDE,
        "gh pr comment https://github.com/acme/widgets/pull/7 --body hi": gate.OTHER_PR_OR_REPO,
        "gh pr comment 7 --repo acme/widgets --body hi": gate.OTHER_PR_OR_REPO,
        "gh pr edit 42 --title retitled": gate.OTHER_PR_OR_REPO,
        "gh pr close 7": gate.OTHER_PR_OR_REPO,
        "gh pr review 7 --approve": gate.OTHER_PR_OR_REPO,
        "gh repo edit --default-branch bot/x": gate.OTHER_PR_OR_REPO,
        "gh secret set TOKEN --body x": gate.OTHER_PR_OR_REPO,
        "gh api -X DELETE repos/acme/widgets": gate.OTHER_PR_OR_REPO,
        "gh api repos/acme/widgets/issues/7/comments -f body=hi": gate.OTHER_PR_OR_REPO,
        "git push": gate.UNQUALIFIED,
        "git push origin": gate.UNQUALIFIED,
        "git push origin HEAD": gate.UNQUALIFIED,
        "git push -u origin bot/fix-ci": gate.UNQUALIFIED,
        "git push origin HEAD:$BRANCH": gate.UNCLASSIFIED,
        "gh pr create --fill": gate.UNQUALIFIED,
        "gh pr comment 42 --body hi": gate.UNQUALIFIED,
        "sh -c 'git push -f origin HEAD:bot/x'": gate.FORCE_PUSH,
        "bash -lc 'git push origin HEAD:main'": gate.PUSH_OUTSIDE,
        "env GIT_TRACE=1 git push origin HEAD:main": gate.UNCLASSIFIED,
        "timeout 60 git push origin HEAD:main": gate.PUSH_OUTSIDE,
        "eval 'git push origin HEAD:main'": gate.PUSH_OUTSIDE,
        "git add -A\ngit push origin HEAD:main": gate.PUSH_OUTSIDE,
        "git submodule foreach git push origin HEAD:main": gate.PUSH_OUTSIDE,
        "git push origin `git branch --show-current`": gate.UNCLASSIFIED,
        "git push origin 'HEAD:bot/x": gate.UNCLASSIFIED,
        "env -S 'git push origin HEAD:main'": gate.UNCLASSIFIED,
        "git p origin HEAD:main": gate.UNCLASSIFIED,
        "git -c alias.p=push p origin HEAD:main": gate.UNCLASSIFIED,
        "git -c remote.origin.pushurl=x push origin HEAD:bot/x": gate.UNCLASSIFIED,
        "git push --frobnicate origin HEAD:bot/x": gate.UNCLASSIFIED,
        "echo origin HEAD:main | xargs git push": gate.UNCLASSIFIED,
        "python3 -c \"import subprocess; subprocess.run(['git', 'push', 'origin', 'HEAD:main'])\"": gate.UNCLASSIFIED,
        "cat <<EOF | sh\ngit push origin HEAD:main\nEOF": gate.UNCLASSIFIED,
        "gh extension-thing do-it": gate.UNCLASSIFIED,
        # Review of record for #3154: each of these reached a never-allowed effect before.
        "echo a#b; git push origin HEAD:main": gate.PUSH_OUTSIDE,
        "git status a#b; git push -f origin HEAD:main": gate.FORCE_PUSH,
        "git push origin HEAD:refs/heads/bot/x#y; git push -f origin HEAD:main": gate.FORCE_PUSH,
        "git status # <<\ngit push -f origin HEAD:main": gate.UNCLASSIFIED,
        "git status <<EOF\nEOF\ngit push -f origin HEAD:main": gate.UNCLASSIFIED,
        "git log --format='<<'\ngh pr merge 42": gate.UNCLASSIFIED,
        "gh pr view 42 # <<\ngh pr merge 42 --admin": gate.UNCLASSIFIED,
        "gh pr merge 42 -b -h": gate.FORGE_MERGE,
        "gh pr merge 42 --body -h --squash": gate.FORGE_MERGE,
        "gh api -X PUT repos/o/r/pulls/1/merge -H -h": gate.FORGE_MERGE,
        "gh api -X PUT -f -h repos/o/r/pulls/1/merge": gate.FORGE_MERGE,
        "git rebase HEAD~1 -x 'true' -x 'git push -f origin HEAD:main'": gate.FORCE_PUSH,
        "git bisect run sh -c 'git push -f origin HEAD:main'": gate.FORCE_PUSH,
        "git -c core.sshCommand='git push --force origin HEAD:main' fetch origin": gate.UNCLASSIFIED,
        "GIT_SSH_COMMAND='git push -f origin HEAD:main' git fetch origin": gate.UNCLASSIFIED,
        "GIT_SSH_COMMAND=x git push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.sshCommand GIT_CONFIG_VALUE_0=x git fetch": gate.UNCLASSIFIED,
        "export GIT_SSH_COMMAND='git push -f origin HEAD:main'": gate.UNCLASSIFIED,
        "git fetch --upload-pack='git push -f origin HEAD:main' origin": gate.UNCLASSIFIED,
        "git clone -u 'sh -c x' https://example.invalid/r.git": gate.UNCLASSIFIED,
        "gh repo clone o/r -- --upload-pack=x": gate.UNCLASSIFIED,
        "git -c protocol.ext.allow=always fetch 'ext::sh -c x'": gate.UNCLASSIFIED,
        "git fetch 'ext::sh -c x'": gate.UNCLASSIFIED,
        "git difftool -x 'git push -f origin HEAD:main'": gate.UNCLASSIFIED,
        "git grep -O'git push -f' x": gate.UNCLASSIFIED,
        "git push --receive-pack='sh -c x' ../r HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "git --exec-path=/tmp/evil push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "git push origin $'+HEAD:refs/heads/bot/x'": gate.UNCLASSIFIED,
        "$'\\x67it' push -f origin HEAD:main": gate.UNCLASSIFIED,
        "$GIT push origin HEAD:main": gate.UNCLASSIFIED,
        "G=git; $G push origin HEAD:main": gate.UNCLASSIFIED,
        "GIT push origin HEAD:main": gate.PUSH_OUTSIDE,  # a case-insensitive file system finds git
        "gh pr comment 42 -R acme/widgets --repo other/r -b x": gate.OTHER_PR_OR_REPO,
        "GH_REPO=other/repo gh pr create --head bot/x --title t --body b": gate.UNCLASSIFIED,
        "env GH_REPO=victim/repo gh pr create --head bot/x --title t --body b": gate.UNCLASSIFIED,
        "GH_HOST=evil.example gh pr create --head bot/x --title t --body b": gate.UNCLASSIFIED,
        "git push -o merge_request.create -o merge_request.merge_when_pipeline_succeeds origin HEAD:refs/heads/bot/x":
            gate.OTHER_PR_OR_REPO,
        "gh pr create --head bot/x --title t --body b; gh pr create --head bot/y --title t --body b":
            gate.UNCLASSIFIED,
        "gh pr create --head bot/x --title t --body b && echo done": gate.UNCLASSIFIED,
        f"gh pr comment {URL} -b '/merge'": gate.FORGE_MERGE,
        f"gh pr comment {URL} -b '@dependabot merge'": gate.FORGE_MERGE,
        f"gh pr comment {URL} -b 'bors r+'": gate.FORGE_MERGE,
        "gh pr create --head bot/x --label automerge --title t --body b": gate.OTHER_PR_OR_REPO,
        "gh pr create --head bot/x --body-file /etc/passwd --title t": gate.UNCLASSIFIED,
        "gh auth token": gate.UNCLASSIFIED,
        "gh auth status -t": gate.UNCLASSIFIED,
        "gh auth setup-git": gate.UNCLASSIFIED,
        "gh auth refresh -s delete_repo": gate.UNCLASSIFIED,
        "git() { command git push -f origin HEAD:main; }": gate.UNCLASSIFIED,
        "gh () { echo https://github.com/victim/r/pull/9; }": gate.UNCLASSIFIED,
        "alias git='git push -f origin HEAD:main'": gate.UNCLASSIFIED,
        "git config core.sshCommand 'sh -c x'": gate.UNCLASSIFIED,
        "git config core.hooksPath /tmp/hooks": gate.UNCLASSIFIED,
        "git remote set-url origin https://example.invalid/victim.git": gate.UNCLASSIFIED,
        "git push https://github.com/victim/repo.git HEAD:refs/heads/bot/x": gate.PUSH_OUTSIDE,
        "git push upstream HEAD:refs/heads/bot/x": gate.PUSH_OUTSIDE,
        "gh api -X GET -f query='mutation{mergePullRequest}' graphql": gate.OTHER_PR_OR_REPO,
        "gh repo set-default other/repo": gate.UNCLASSIFIED,
        "sh <<< 'git push origin HEAD:main'": gate.UNCLASSIFIED,
        "bash -c \"$CMD\"": gate.UNCLASSIFIED,
        "echo Z2l0IHB1c2g= | base64 -d | sh": gate.UNCLASSIFIED,
        "curl -X PUT -H 'Authorization: token x' https://api.github.com/repos/o/r/pulls/1/merge":
            gate.OTHER_PR_OR_REPO,
        "git push --dry-run=no origin HEAD:main": gate.UNCLASSIFIED,
        "git push origin HEAD:refs/heads/bot/x:refs/heads/main": gate.UNQUALIFIED,
        # Windows spellings (cmd.exe, PowerShell): classified, or refused as unparseable.
        "git.exe push -f origin HEAD:main": gate.FORCE_PUSH,
        "gh.exe pr merge 42": gate.FORGE_MERGE,
        "& git push -f origin HEAD:main": gate.FORCE_PUSH,
        "C:\\Program Files\\Git\\cmd\\git.exe push -f origin HEAD:main": gate.UNCLASSIFIED,
        "\"C:\\Program Files\\Git\\cmd\\git.exe\" push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "g^it push -f origin HEAD:main": gate.UNCLASSIFIED,
        "%G% push origin HEAD:main": gate.UNCLASSIFIED,
        "cmd /c \"git push -f origin HEAD:main\"": gate.UNCLASSIFIED,
        "powershell -Command \"git push -f origin HEAD:main\"": gate.UNCLASSIFIED,
        "Start-Process git -ArgumentList push,-f": gate.UNCLASSIFIED,
        "$env:GH_REPO='victim/r'": gate.UNCLASSIFIED,
        "$env:GIT_SSH_COMMAND='x'; git fetch origin": gate.UNCLASSIFIED,
        "Set-Item -Path Env:GH_REPO -Value x": gate.UNCLASSIFIED,
        "set GIT_SSH_COMMAND=x": gate.UNCLASSIFIED,
        "setx GH_REPO victim/r": gate.UNCLASSIFIED,
        # Second Windows pass (W1): PowerShell and cmd decided by the executable.
        "powershell.exe -EncodedCommand ZwBoACAAcAByACAAbQBlAHIAZwBlACAANAAyAA==": gate.UNCLASSIFIED,
        "powershell -enc ZwBoACAAcAByACAAbQBlAHIAZwBlACAANAAyAA==": gate.UNCLASSIFIED,
        "pwsh -e ZwBoACAAcAByACAAbQBlAHIAZwBlACAANAAyAA==": gate.UNCLASSIFIED,
        "pwsh -ec ZwBoACAAcAByACAAbQBlAHIAZwBlACAANAAyAA==": gate.UNCLASSIFIED,
        "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -EncodedC ZwBo": gate.UNCLASSIFIED,
        "cmd.exe /k dir": gate.UNCLASSIFIED,
        "timeout 5 C:\\Git\\git.exe push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "sudo -u x C:\\Git\\gh.exe pr merge 1": gate.UNCLASSIFIED,
        "env -u A C:\\Git\\git.exe push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        "git push origin HEAD:refs/heads/bot/%X%": gate.UNQUALIFIED,
        # Second verification round (R1-R5).
        "git status;(gh pr merge 42)": gate.FORGE_MERGE,
        "git status&&(gh pr merge 42)": gate.FORGE_MERGE,
        "git status||(git push -f origin HEAD:main)": gate.FORCE_PUSH,
        "(git status);gh pr merge 42": gate.FORGE_MERGE,
        "git status|(sh)": gate.UNCLASSIFIED,
        "g\\\nit push -f origin HEAD:main": gate.FORCE_PUSH,
        "gi\\\nt push -f origin HEAD:main": gate.FORCE_PUSH,
        "git -C ../repo push origin HEAD:refs/heads/bot/fix-ci": gate.UNCLASSIFIED,
        "git --git-dir=/tmp/other/.git push origin HEAD:refs/heads/bot/x": gate.UNCLASSIFIED,
        f"gh pr comment {URL} -b '!merge'": gate.FORGE_MERGE,
        f"gh pr comment {URL} -b '\u200b/merge'": gate.FORGE_MERGE,
        "gh pr create --head bot/x --title t --body '/merge'": gate.FORGE_MERGE,
        "gh pr create --head bot/x -t t -b b -m v1": gate.OTHER_PR_OR_REPO,
    }
    LOCAL = (
        "git status", "git diff --stat", "git commit -m 'fix: ci'", "git fetch origin", "git log -1",
        "git push --dry-run origin HEAD:main", "gh pr view 42 --json state",
        "gh pr checks 42", "gh run view 7 --log-failed", "gh api repos/acme/widgets/pulls/42",
        "gh api -X GET repos/acme/widgets/pulls -f state=open", "ls -la", "cat README.md",
        "git config user.email bot@example.invalid", "git config --get remote.origin.url", "git remote -v",
        "gh auth status", "gh repo set-default --view", "git push origin HEAD:refs/heads/bot/x --dry-run",
        "git log --format='%h\\t%s'", "grep -E '\\bfoo\\b' notes.txt",
        "powershell -NoProfile -File build.ps1", "pwsh build.ps1", "cmd /c build.bat", "ls .git",
        # Plain reads of a protected path are not writes.
        "cat .git/config", "head -5 ~/.gitconfig", "tail .gitmodules", "wc -l .git/config",
        "grep -n url .git/config", "stat .git/hooks/pre-push", "git config --list",
        "git config --get remote.origin.url",
    )

    def setUp(self) -> None:
        super().setUp()
        session_attendance.note_session_platform(SESSION, "webhook")

    def test_the_classifier_names_every_hostile_spelling(self):
        for command, expected in self.ALWAYS_REFUSED.items():
            with self.subTest(command=command):
                self.assertEqual(gate.classify_command(command, prefix="bot/", opened=OPENED), expected)
        for command in self.GRANT_COVERED:
            with self.subTest(command=command):
                self.assertIn(gate.classify_command(command, prefix="bot/", opened=OPENED), gate.GRANT_COVERED)

    def test_grant_off_refuses_the_covered_actions_with_a_hand_off(self):
        self._record_opened(URL)  # a PR it opened while the grant was on
        for command in self.GRANT_COVERED:
            with self.subTest(command=command):
                directive = self.terminal(command)
                self.assertEqual(directive["action"], "block")
                self.assertIn("hand the push and the pull request to a person's turn", directive["message"])
                self.assertIn(pr_delivery.TURN_ON_COMMAND, directive["message"])

    def test_grant_on_allows_the_covered_actions(self):
        self.grant_on()
        self._record_opened(URL)
        for command in self.GRANT_COVERED:
            with self.subTest(command=command):
                self.assertIsNone(self.terminal(command))

    def test_grant_on_still_refuses_every_never_allowed_class(self):
        self.grant_on()
        self._record_opened(URL)
        for command in self.ALWAYS_REFUSED:
            with self.subTest(command=command):
                directive = self.terminal(command)
                self.assertIsNotNone(directive)
                self.assertEqual(directive["action"], "block")
                self.assertIn("did not run", directive["message"])

    def test_local_commands_pass_in_an_unattended_session(self):
        for command in self.LOCAL:
            with self.subTest(command=command):
                self.assertIsNone(self.terminal(command))

    def test_issue_and_run_verbs_follow_the_owner_call(self):
        for command in ("gh issue edit 3 --add-label bug", "gh issue comment 3 -b hi", "gh issue close 3"):
            self.assertEqual(gate.classify_command(command, prefix="bot/"), gate.NOT_GOVERNED)
            self.assertIsNone(self.terminal(command))
        for command in ("gh run rerun 9", "gh run cancel 9", "gh run delete 9", "gh issue delete 3 --yes",
                        "gh issue transfer 3 other/repo"):
            self.assertEqual(self.terminal(command)["action"], "block")

    def test_comments_substitution_and_credentials_fail_closed(self):
        for command in ("git status # note", "git status $(echo x)", "echo $GITHUB_TOKEN", "cat ~/.config/gh/hosts.yml",
                        "cat ~/.git-credentials"):
            self.assertEqual(gate.classify_command(command, prefix="bot/"), gate.UNCLASSIFIED, command)

    def test_every_unattended_kind_is_held_the_same_way(self):
        self.grant_on()
        kinds = {"api_server": {"platform": "api_server"}, "msgraph_webhook": {"platform": "msgraph_webhook"},
                 "single_query": {"env": {"HERMES_SINGLE_QUERY_SESSION": "1"}}}
        for kind, setup in kinds.items():
            session = f"session-{kind}"
            with self.subTest(kind=kind), mock.patch.dict(os.environ, setup.get("env", {})):
                if "platform" in setup:
                    session_attendance.note_session_platform(session, setup["platform"])
                self.assertIsNone(self.terminal("git push origin HEAD:refs/heads/bot/x", session=session))
                self.assertEqual(self.terminal("git push origin HEAD:main", session=session)["action"], "block")
                self.assertEqual(self.terminal("gh pr merge 42", session=session)["action"], "block")

    def test_a_second_pr_in_one_session_is_a_persons(self):
        self.grant_on()
        self._record_opened(URL, session=SESSION)
        directive = self.terminal("gh pr create --head bot/second --title t --body b")
        self.assertIn("already opened a pull request", directive["message"])
        session_attendance.note_session_platform("other-run", "webhook")
        self.assertIsNone(self.terminal("gh pr create --head bot/second --title t --body b", session="other-run"))

    def test_process_stdin_is_read_as_a_command_line(self):
        self.grant_on()
        submit = self.pre("process", {"action": "submit", "session_id": "p1", "data": "git push -f origin HEAD:main"})
        self.assertEqual(submit["action"], "block")
        partial = self.pre("process", {"action": "write", "session_id": "p1", "data": "git pu"})
        self.assertEqual(partial["action"], "block")
        self.assertIsNone(self.pre("process", {"action": "submit", "session_id": "p1", "data": "git status"}))
        self.assertIsNone(self.pre("process", {"action": "poll", "session_id": "p1"}))

    def test_process_sends_joined_by_a_continuation_are_held(self):
        for args in ({"action": "write", "data": "g\\\n"}, {"action": "submit", "data": "g\\"},
                     {"action": "submit", "data": "git status;(gh pr merge 42)"},
                     {"action": "write", "data": "gh pr merge 42\r"}):
            with self.subTest(args=args):
                self.assertEqual(self.pre("process", {"session_id": "p1", **args})["action"], "block")

    def test_forge_configuration_files_are_held_case_folded(self):
        for path in ("repo/.GIT/hooks/pre-push", "repo/.git", "/home/u/.gitconfig", "/home/u/.config/git/config",
                     "/home/u/.config/gh/config.yml", "repo/.gitmodules",
                     "C:\\repo\\.git\\hooks\\pre-push", "C:\\repo\\.GIT\\hooks\\pre-push", "C:\\repo\\.git.\\config",
                     "C:\\repo\\.git::$INDEX_ALLOCATION\\config", "C:\\repo\\GIT~1\\config", "C:\\Users\\u\\.gitconfig",
                     "C:\\Users\\u\\AppData\\Roaming\\GitHub CLI\\hosts.yml", "C:\\Users\\u\\GITCON~1",
                     "C:\\repo\\GITMOD~1", "C:\\Users\\u\\AppData\\Roaming\\GITHUB~1\\hosts.yml",
                     "/etc/gitconfig", "C:\\Users\\u\\AppData\\Local\\Programs\\Git\\etc\\gitconfig"):
            with self.subTest(path=path):
                self.assertEqual(self.pre("write_file", {"path": path, "content": "x"})["action"], "block")
        for tool in ("mcp_github_add_issue_comment", "mcp_github_update_issue", "github_merge_pr",
                     "MCP_GitHub_Merge", "mcp__github__merge_pull_request", "mcp_github_enable_pr_auto_merge"):
            with self.subTest(tool=tool):
                self.assertEqual(self.pre(tool, {"body": "/merge"})["action"], "block")

    def test_a_write_through_a_symlinked_parent_is_held(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlinks on this platform")
        repo = Path(os.environ["TERMINAL_CWD"])
        (repo / ".git" / "hooks").mkdir(parents=True)
        try:
            (repo / "g").symlink_to(repo / ".git", target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation not permitted")
        self.grant_on()
        directive = self.pre("write_file", {"path": "g/hooks/pre-push", "content": "#!/bin/sh\n"})
        self.assertEqual(directive["action"], "block")
        self.assertIsNone(self.pre("write_file", {"path": "src/app.py", "content": "x = 1\n"}))

    def test_variables_that_name_a_program_are_refused_beside_git_and_gh(self):
        names = ("EDITOR", "VISUAL", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "PAGER", "GIT_PAGER", "GH_PAGER",
                 "MANPAGER", "LESS", "LESSOPEN", "LESSCLOSE", "LESSKEYIN", "SSH_ASKPASS", "GIT_ASKPASS",
                 "BROWSER", "GH_BROWSER", "GH_EDITOR", "GIT_EXTERNAL_DIFF", "GIT_PROXY_COMMAND")
        for name in names:
            for command in (f"{name}='gh pr merge 42' git commit", f"env {name}='gh pr merge 42' git commit",
                            f"export {name}='gh pr merge 42'; git commit -m x"):
                with self.subTest(command=command):
                    self.assertEqual(gate.classify_command(command, prefix="bot/"), gate.UNCLASSIFIED)
                    self.assertEqual(self.terminal(command)["action"], "block")

    def test_making_a_link_to_git_config_is_held(self):
        for command in ("ln -s .git g", "ln -s ../.git/hooks h", "mklink /J g .git", "cmd /c mklink /J g .git",
                        "New-Item -ItemType Junction -Path g -Target .git", "cp evil.sh .git/hooks/pre-push",
                        "echo x > .git/hooks/pre-push", "ln -s ~/.gitconfig c", "cat x > .git/hooks/pre-push",
                        "tee .git/hooks/pre-push", "cp x .git/config", "find .git -delete",
                        "find .git/hooks -exec rm {} +", "echo x >> ~/.ssh/config",
                        "LESSOPEN='|gh pr merge 42 %s' less README.md",
                        "LESSOPEN=\"|git push -f origin HEAD:main %s\" less README.md",
                        "env LESSOPEN='|gh pr merge 42' less README.md", "LESSOPEN='|gh pr merge 42 %s' more README.md",
                        "less '+!gh pr merge 42' README.md", "tree -o .git/hooks/pre-push",
                        "rg --pre ./x url .git/config", "less .git/config", "more .git/config",
                        "find .git -name config", "LESSCLOSE='|x' cat .git/config", "PAGER=x cat .git/config",
                        "GIT_PAGER=x cat .git/config", "env LESS=x cat .git/config", "LANG=C cat .git/config",
                        "export LESSOPEN='|gh pr merge 42'; cat README.md", "grep 'git push' notes.md",
                        "cat .git/config | sh"):
            with self.subTest(command=command):
                self.assertEqual(self.terminal(command)["action"], "block")
        self.assertIsNone(self.terminal("ln -s build/out latest"))

    def test_mcp_forge_writes_and_git_dir_writes_are_held(self):
        self.grant_on()
        self.assertEqual(self.pre("mcp_github_merge_pull_request", {"pull_number": 42})["action"], "block")
        self.assertEqual(self.pre("mcp_github_push_files", {"branch": "main"})["action"], "block")
        self.assertIsNone(self.pre("mcp_github_get_pull_request", {"pull_number": 42}))
        hook = self.pre("write_file", {"path": "repo/.git/hooks/pre-push", "content": "#!/bin/sh\n"})
        self.assertEqual(hook["action"], "block")
        self.assertIsNone(self.pre("write_file", {"path": "repo/src/app.py", "content": "x = 1\n"}))

    def test_a_delegated_child_does_not_carry_the_grant(self):
        self.grant_on()
        child = "child-session-1"
        nudge_budget.note_delegated_session(child)  # keyed the way `session_attendance` reads it
        directive = self.terminal("git push origin HEAD:refs/heads/bot/x", session=child)
        self.assertEqual(directive["action"], "block")
        self.assertIn("A delegated child does not carry the PR delivery grant", directive["message"])
        self.assertEqual(self.terminal("gh pr merge 42", session=child)["action"], "block")

    def test_a_malformed_grant_reads_off_in_the_gate(self):
        path = pr_delivery.grant_path(self.home, self.hermes)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"state": "on"}', encoding="utf-8")
        self.assertEqual(self.terminal("git push origin HEAD:refs/heads/bot/x")["action"], "block")

    def test_execute_code_naming_git_beside_a_forge_verb_is_refused(self):
        self.grant_on()
        directive = self.pre("execute_code", {"code": "import os\nos.system('git push origin HEAD:main')"})
        self.assertEqual(directive["action"], "block")
        self.assertIsNone(self.pre("execute_code", {"code": "print(sum(range(10)))"}))

    def test_an_ask_rule_never_overrides_the_refusal(self):
        rules = self.home / "rules"
        rules.mkdir()
        (rules / "toolcall-rules.json").write_text(json.dumps({
            "schema_version": "omh_toolcall_rules/v1",
            "rules": [{"name": "ask-push", "pattern": "git push", "message": "Push?", "tools": ["terminal"],
                       "effect": "ask", "repeat": "always"}],
        }), encoding="utf-8")
        session_attendance.note_session_platform(SESSION, "cli")
        self.assertEqual(self.terminal("omh capability-policy pr-delivery on")["action"], "block")

    def _record_opened(self, url: str, session: str = "an-earlier-run") -> None:
        self.assertTrue(pr_delivery.append_opened_pr(self.home, self.hermes, url=url, head_branch="bot/fix-ci",
                                                     session_id=session))


class ReviewProbeTableTests(unittest.TestCase):
    """Every input of the review of record for #3154, with the verdict the gate gives it.

    A refused row must stay refused. An allowed row carries the reason it is
    allowed (grant-covered, a local read, an ungoverned issue verb, or a stated
    residual), so loosening or tightening the gate shows up as a row that moved.
    """

    FIXTURE = ROOT / "tests/fixtures/pr_delivery_probe_cases.json"
    GRANT_CHANGES = (
        ("terminal", "omh capability-policy pr-delivery on"),
        ("terminal", "env -u HERMES_SESSION_ID omh capability-policy pr-delivery on"),
        ("terminal", "X=on; env -u HERMES_SESSION_ID omh capability-policy pr-delivery $X"),
        ("terminal", "env -u HERMES_SESSION_ID omh capability-policy pr-delivery $'on'"),
        ("terminal", "echo a#b; env -u HERMES_SESSION_ID omh capability-policy pr-delivery on"),
        ("terminal", "omh capability-policy pr-delivery on\xa0"),
        ("terminal", "omh capability-policy pr-delivery --branch-prefix x/ on"),
        ("terminal", "omh capability-policy pr-deliver''y on"),
        ("terminal", "omh capability-policy pr-delivery o''n"),
        ("terminal", 'omh capability-policy pr-delivery "o"n'),
        ("terminal", "P=pr-delivery; omh capability-policy $P on"),
        ("terminal", "omh capability-policy pr-delivery `echo on`"),
        ("terminal", "printf on | xargs omh capability-policy pr-delivery"),
        ("terminal", "python3 -m omh.cli capability-policy pr-delivery on"),
        ("terminal", "cat > ~/.omh/runtime/pr_deliv''ery/grant-0123456789abcdef.json < /tmp/forged.json"),
        ("terminal", "cp /tmp/forged.json ~/.omh/runtime/pr_*/grant-0123456789abcdef.json"),
        ("terminal", "cd ~/.omh/runtime && cp /tmp/f.json pr_deliver?/grant-x.json"),
        ("terminal", "ln -s ~/.omh/runtime/pr_deliv''ery /tmp/s"),
        ("terminal", "python3 -c \"import json;open('/h/runtime/pr_'+'delivery/opened-x.jsonl','a').write('{}')\""),
        ("terminal", "echo x >> ~/.omh/runtime/PR_DELIVERY/opened-x.jsonl"),
        ("execute_code", "import os; p=os.path.expanduser('~/.omh/runtime/pr_'+'delivery'); open(p+'/x','w')"),
        ("execute_code", "import subprocess; subprocess.run(['omh','capability-policy','pr-'+'delivery','on'], env={})"),
        ("terminal", "OMH_HOME=/tmp/forged omh capability-policy pr-delivery on"),
    )

    def test_every_probe_input_keeps_its_verdict(self):
        table = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        allowed = {gate.LOCAL, gate.NOT_GOVERNED, *gate.GRANT_COVERED}
        for case in table["cases"]:
            with self.subTest(command=case["command"]):
                found = gate.classify_command(case["command"], prefix="bot/", opened=OPENED)
                self.assertEqual(found, case["class"])
                self.assertEqual("allowed" if found in allowed else "refused", case["verdict"])
                if case["verdict"] == "allowed":
                    self.assertTrue(case["why_allowed"])

    # The review's tool-surface probes: (tool, args, refused?). The three allowed rows are
    # a send whose refused first half leaves it harmless, and code built from string
    # pieces (a stated residual).
    TOOL_CASES = (
        ("process", {"action": "submit", "data": "gh pr \\"}, True),
        ("process", {"action": "submit", "data": "merge 42"}, False),
        ("process", {"action": "write", "data": "g\\\n"}, True),
        ("process", {"action": "write", "data": "it push -f origin HEAD:main\n"}, False),
        ("process", {"action": "submit", "data": "git status;(gh pr merge 42)"}, True),
        ("process", {"action": "write", "data": "gh pr merge 42\r"}, True),
        ("process", {"action": "send_keys", "data": "gh pr merge 42\n"}, True),
        ("write_file", {"path": "/home/u/.gitconfig", "content": "x"}, True),
        ("write_file", {"path": "/home/u/.config/git/config", "content": "x"}, True),
        ("write_file", {"path": "/home/u/.config/gh/config.yml", "content": "x"}, True),
        ("write_file", {"path": "repo/.gitmodules", "content": "x"}, True),
        ("write_file", {"path": "repo/.git/hooks/pre-push", "content": "x"}, True),
        ("write_file", {"path": "repo/.GIT/hooks/pre-push", "content": "x"}, True),
        ("write_file", {"path": "repo/.git", "content": "gitdir: /tmp/evil"}, True),
        ("patch", {"path": "repo/.git/config", "old_string": "a", "new_string": "b"}, True),
        ("mcp_github_merge_pull_request", {}, True),
        ("mcp_github_add_issue_comment", {"issue_number": 42, "body": "/merge"}, True),
        ("mcp_github_update_issue", {"issue_number": 42, "state": "closed"}, True),
        ("mcp_github_create_pull_request_review", {"event": "APPROVE"}, True),
        ("mcp_github_enable_pr_auto_merge", {}, True),
        ("mcp_github_update_pull_request_branch", {}, True),
        ("github_merge_pr", {}, True),
        ("MCP_GitHub_Merge", {}, True),
        ("mcp__github__merge_pull_request", {}, True),
        ("execute_code", {"code": "import subprocess; subprocess.run(['g'+'h','pr','mer'+'ge','42'])"}, False),
        ("execute_code", {"code": "import subprocess; subprocess.run(['gh','pr','merge','42'])"}, True),
    )

    def test_every_tool_probe_keeps_its_verdict(self):
        for tool, args, refused in self.TOOL_CASES:
            with self.subTest(tool=tool, args=args):
                found = gate._tool_class(tool, args, "bot/", OPENED)
                self.assertEqual(found not in (gate.LOCAL, gate.NOT_GOVERNED), refused)

    def test_every_grant_change_spelling_is_refused(self):
        for tool, text in self.GRANT_CHANGES:
            with self.subTest(text=text):
                directive = gate.grant_change_directive(tool_name=tool, tool_input={"command": text, "code": text})
                self.assertIsNotNone(directive)


class OpenedPrRecordTests(_Home):
    COMMAND = "gh pr create --head bot/fix-ci --title 'fix: ci' --body 'Fixes the lint job.'"

    def post(self, command: str, output: str, *, exit_code: int = 0, status: str = "") -> None:
        post_tool_call(tool_name="terminal", args={"command": command},
                       result=json.dumps({"output": output, "exit_code": exit_code}), status=status,
                       session_id=SESSION, task_id=SESSION, tool_call_id="call-1", turn_id="turn-1",
                       omh_home=str(self.home), hermes_home=str(self.hermes))

    def opened(self) -> frozenset:
        return pr_delivery.opened_prs(self.home, self.hermes)

    def test_a_grant_allowed_pr_create_records_the_url_gh_printed(self):
        self.grant_on()
        self.post(self.COMMAND, f"Creating pull request for bot/fix-ci into main\n\n{URL}\n")
        self.assertEqual(self.opened(), OPENED)
        row = json.loads(pr_delivery.opened_prs_path(self.home, self.hermes).read_text(encoding="utf-8"))
        self.assertEqual((row["schema_version"], row["head_branch"]),
                         (pr_delivery.OPENED_PR_SCHEMA_VERSION, "bot/fix-ci"))
        session_attendance.note_session_platform(SESSION, "webhook")
        self.assertIsNone(self.terminal(f"gh pr comment {URL} --body 'Round 1 pushed.'"))

    def test_nothing_else_makes_a_record(self):
        self.post(self.COMMAND, URL)  # grant off
        self.grant_on()
        self.post(self.COMMAND, URL, exit_code=1)
        self.post(self.COMMAND, URL, status="blocked")
        self.post(f"{self.COMMAND} && echo {URL}", URL)
        self.post(f"echo {URL}", URL)
        self.post("gh pr create --fill", URL)
        self.post(self.COMMAND, f"{URL}\nwarning: something after the URL")
        self.assertEqual(self.opened(), frozenset())


class StatusToolTests(_Home):
    def test_omh_status_reports_the_grant_read_only(self):
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.hermes)}):
            payload = json.loads(omh_status_handler({"omh_home": str(self.home)}))
            self.assertEqual(payload["pr_delivery_grant"]["state"], "off")
            self.grant_on()
            payload = json.loads(omh_status_handler({"omh_home": str(self.home)}))
        grant = payload["pr_delivery_grant"]
        self.assertEqual((grant["state"], grant["branch_prefix"]), ("on", "bot/"))
        self.assertEqual(grant["turn_on_command"], pr_delivery.TURN_ON_COMMAND)


class StatedContractTests(unittest.TestCase):
    def test_the_unattended_gate_names_the_one_exception(self):
        from omh.skills.catalog_feature_surfaces import _UNATTENDED_GATE

        for phrase in ("push a new branch under the grant's branch prefix", "open a pull request from that branch",
                       "push fix commits to and comment on a pull request it opened", "and nothing else",
                       "Merging, force-pushing, pushing to the default branch, and anything on a pull request it did "
                       "not open stay a person's", "which only the person runs", pr_delivery.TURN_ON_COMMAND):
            self.assertIn(phrase, _UNATTENDED_GATE)

    def test_the_skill_states_delivery_and_its_evidence(self):
        body = (ROOT / "skills/omh-github-event-ops/SKILL.md").read_text(encoding="utf-8")
        for phrase in ("git push origin HEAD:refs/heads/<prefix><topic>", "gh pr create --head <prefix><topic>",
                       "gh pr comment <PR URL>", "git ls-remote origin refs/heads/<branch>",
                       "gh pr view <URL> --json url,headRefName,state", "listed as prepared",
                       "Never merge, force-push, push to the default branch, or act on a PR the bot did not open"):
            self.assertIn(phrase, body)
        reference = (ROOT / "skills/omh-github-event-ops/references/pr-watch.md").read_text(encoding="utf-8")
        for phrase in ("## 7. Delivering the bot's own PR", "| comment on a PR it opened | act on a PR it did not "
                       "open, or change repository settings |", "a watch job or any\ncron turn"):
            self.assertIn(phrase, reference)
        for action in ("push a new branch under the grant's prefix", "open a PR from that branch",
                       "push fix commits to a PR it opened", "force-push, or delete a remote branch",
                       "push to the default branch"):
            self.assertIn(action, reference)

    def test_the_boundary_statements_exist(self):
        boundaries = (ROOT / "docs/IMPLEMENTATION-BOUNDARIES.md").read_text(encoding="utf-8")
        self.assertIn("**PR delivery grant** (owner-approved, 2026-11-23)", boundaries)
        self.assertIn("`omh` itself runs no forge command and INVARIANT 3 is unchanged", boundaries)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("**PR delivery grant** (owner-approved, 2026-11-23)", agents)
        self.assertIn("`omh` runs no forge command; INVARIANT 3 is unchanged.", agents)


if __name__ == "__main__":
    unittest.main()
