"""Contracts for the built-in shell-edit rule at the pre_tool_call seam.

A `terminal` command that edits an existing source file in place is refused
with a message naming `patch` / `write_file`; reads, searches, tests, git,
new files, non-source files and generated directories are never refused. The
rule is off unless the profile setting or the env switch turns it on.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call
from omh.plugin_bundle.omh.shell_edit_rules import (
    DEFAULT_ENABLED,
    ENV_NAME,
    shell_edit_directive,
    shell_edit_in_command,
    shell_edit_rules_enabled,
)

FILES = (
    "src/benchapp/retries.py",
    "tests/test_retries.py",
    "README.md",
    "data.json",
    "build/gen.py",
    "patches/retry.diff",
    "tools/gen_constants.py",
)

REFUSED = {
    "sed -i GNU": "sed -i 's/DEFAULT_RETRY_LIMIT/MAX_RETRY_ATTEMPTS/g' src/benchapp/retries.py tests/test_retries.py",
    "sed -i BSD empty suffix": "sed -i '' 's/a/b/' src/benchapp/retries.py",
    "sed -i suffix and -e": "sed -i.bak -e 's/a/b/' src/benchapp/retries.py",
    "sed flag cluster": "sed -Ei 's/a/b/' src/benchapp/retries.py",
    "sed --in-place": "sed --in-place -e 's/a/b/' src/benchapp/retries.py",
    "xargs sed -i": "grep -rl DEFAULT src tests | xargs sed -i 's/A/B/g'",
    "find -exec sed -i over py": "find . -name '*.py' -exec sed -i 's/a/b/' {} +",
    "loop variable target": "for f in src/benchapp/*.py; do sed -i 's/a/b/' \"$f\"; done",
    "perl -pi": "perl -pi -e 's/a/b/' src/benchapp/retries.py",
    "perl -i.bak": "perl -i.bak -pe 's/a/b/' src/benchapp/retries.py",
    "python -c open w via name": (
        "python3 -c \"p='src/benchapp/retries.py'; s=open(p).read(); open(p,'w').write(s.replace('a','b'))\""
    ),
    "python -c Path.write_text": "python3 -c \"from pathlib import Path; Path('tests/test_retries.py').write_text('x')\"",
    "python heredoc loop": (
        "python3 - <<'EOF'\nfor p in ['src/benchapp/retries.py']:\n    s = open(p).read()\n"
        "    open(p, 'w').write(s)\nEOF"
    ),
    "cat heredoc over existing": "cat > src/benchapp/retries.py <<'EOF'\nX = 1\nEOF",
    "append redirect": "echo 'X = 1' >> tests/test_retries.py",
    "tee": "printf 'x' | tee src/benchapp/retries.py",
    "cd then relative": "cd src && sed -i 's/a/b/' benchapp/retries.py",
    "bash -c": "bash -c \"sed -i 's/a/b/' src/benchapp/retries.py\"",
    "uv run python -c": "uv run python -c \"open('src/benchapp/retries.py','w').write('')\"",
    "env and timeout wrappers": "FOO=1 timeout 30 sed -i 's/a/b/' src/benchapp/retries.py",
    # claude-opus-5-5, 2026-10-30 A/B: the write path is a helper's parameter.
    "python helper writes the source it is handed": (
        "python3 - <<'EOF'\nimport re\ndef sub(p, pairs):\n    s=open(p).read()\n    for a,b in pairs:\n"
        "        assert a in s,(p,a); s=s.replace(a,b)\n    open(p,'w').write(s)\n"
        "sub('src/benchapp/retries.py',[('a','b')])\nEOF"
    ),
}

ALLOWED = {
    "sed -n read": "sed -n '1,20p' src/benchapp/retries.py",
    "sed to stdout into tmp": "sed 's/a/b/' src/benchapp/retries.py > /tmp/out.py",
    "grep": "grep -rn DEFAULT src tests",
    "tests into a log": "python -m pytest -q > build/test-report.txt 2>&1",
    "generated module under build": "mkdir -p build/generated && python tools/gen.py > build/generated/constants.py",
    "regenerate an existing build file": "python tools/gen.py > build/gen.py",
    "git apply --check": "git apply --check patches/retry.diff",
    "git restores a file": "git show HEAD:src/benchapp/retries.py > src/benchapp/retries.py",
    "answer json heredoc": "cat > .omh-benchmark-answer.json <<'EOF'\n{\"changed_paths\": []}\nEOF",
    "data file redirect": "echo '{}' > data.json",
    "sed -i on non-source": "sed -i 's/a/b/' README.md data.json",
    "new source file": "cat > src/benchapp/new_module.py <<'EOF'\nX = 1\nEOF",
    "python reads source writes json": (
        "python3 -c \"import json; s=open('src/benchapp/retries.py').read(); open('out.json','w').write(json.dumps(s))\""
    ),
    "python reads only": "python3 -c \"print(open('src/benchapp/retries.py').read())\"",
    "find -exec over json": "find . -name '*.json' -exec sed -i 's/a/b/' {} +",
    "dev null": "echo hi > /dev/null; ls -la 2>&1",
    "pytest": "pytest -q tests/test_retries.py",
    "unparseable fails open": "python3 -c 'unbalanced",
    "python script file": "python3 tools/rewrite.py src/benchapp/retries.py",
    # Three refusals on the negative template in the 2026-10-30 A/B: programs that run the
    # generator, hash every existing file, and write only build/ output and the answer file.
    "python writes build output through root joins": (
        "python - <<'PY'\nfrom pathlib import Path\nimport subprocess, sys\nroot = Path.cwd()\n"
        "(root / 'build/generated').mkdir(parents=True, exist_ok=True)\n"
        "generated = subprocess.run([sys.executable, 'tools/gen_constants.py'], stdout=subprocess.PIPE, check=True)\n"
        "(root / 'build/generated/constants.py').write_bytes(generated.stdout)\n"
        "with (root / 'build/test-report.txt').open('wb') as report:\n    pass\n"
        "retry_line = (root / 'src/benchapp/retries.py').read_text().splitlines()[0]\n"
        "(root / '.omh-benchmark-answer.json').write_text('{}')\nPY"
    ),
    "python writes listed outputs by index": (
        "python - <<'PY'\nimport hashlib\nfrom pathlib import Path\nimport subprocess\nroot = Path.cwd()\n"
        "existing = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}\n"
        "outputs = [Path('build/generated/constants.py'), Path('build/test-report.txt'), Path('.omh-benchmark-answer.json')]\n"
        "generated = subprocess.run(['python', 'tools/gen_constants.py'], stdout=subprocess.PIPE, check=True).stdout\n"
        "with outputs[0].open('xb') as f:\n    f.write(generated)\n"
        "line = Path('src/benchapp/retries.py').read_text().splitlines()[0]\nPY"
    ),
    "python -c binds joined outputs to names": (
        "python -c 'import pathlib, subprocess; root=pathlib.Path.cwd(); generated=root/\"build/generated/constants.py\"; "
        "result=subprocess.run([\"python\",\"tools/gen_constants.py\"],stdout=subprocess.PIPE,check=True); "
        "generated.write_bytes(result.stdout); print((root/\"src/benchapp/retries.py\").read_text())'"
    ),
}


class _Workspace(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "ws"
        for relative in FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        self.hermes = Path(directory.name) / "hermes"
        self.hermes.mkdir()
        self.omh = Path(directory.name) / "omh"
        self.omh.mkdir()
        environment = patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(ENV_NAME, None)

    def _setting(self, value: str) -> None:
        (self.hermes / "config.yaml").write_text(
            f"plugins:\n  entries:\n    omh:\n      settings:\n        shell_edit_rules: {value}\n", encoding="utf-8"
        )


class DetectionTest(_Workspace):
    def test_in_place_source_edits_are_found(self):
        for label, command in REFUSED.items():
            with self.subTest(label):
                self.assertIsNotNone(shell_edit_in_command(command, self.root), command)

    def test_reads_tests_git_and_new_or_non_source_writes_are_left_alone(self):
        for label, command in ALLOWED.items():
            with self.subTest(label):
                self.assertIsNone(shell_edit_in_command(command, self.root), command)

    def test_redirect_onto_a_relative_path_needs_a_known_directory(self):
        # Without a working directory the file cannot be shown to exist, so the rule lets it run.
        self.assertIsNone(shell_edit_in_command("echo x > src/benchapp/retries.py", None))
        # An in-place editor changes an existing file by definition; no directory is needed.
        self.assertIsNotNone(shell_edit_in_command("sed -i 's/a/b/' src/benchapp/retries.py", None))


class SettingTest(_Workspace):
    def test_default_is_off(self):
        self.assertFalse(DEFAULT_ENABLED)
        self.assertEqual(shell_edit_rules_enabled(str(self.hermes)), DEFAULT_ENABLED)

    def test_profile_setting_turns_it_on_and_off(self):
        self._setting("true")
        self.assertTrue(shell_edit_rules_enabled(str(self.hermes)))
        self._setting("off")
        self.assertFalse(shell_edit_rules_enabled(str(self.hermes)))

    def test_env_wins_over_the_setting(self):
        self._setting("true")
        os.environ[ENV_NAME] = "0"
        self.assertFalse(shell_edit_rules_enabled(str(self.hermes)))
        self._setting("false")
        os.environ[ENV_NAME] = "1"
        self.assertTrue(shell_edit_rules_enabled(str(self.hermes)))


class DirectiveTest(_Workspace):
    def _call(self, command: str, tool: str = "terminal") -> dict | None:
        return shell_edit_directive(
            tool_name=tool,
            tool_input={"command": command, "workdir": str(self.root)},
            hermes_home=str(self.hermes),
        )

    def test_block_message_names_the_edit_tools_and_the_target(self):
        self._setting("true")
        directive = self._call("sed -i 's/a/b/' src/benchapp/retries.py")
        self.assertEqual(directive["action"], "block")
        message = directive["message"]
        self.assertIn("`patch`", message)
        self.assertIn("`write_file`", message)
        self.assertIn("src/benchapp/retries.py", message)
        self.assertIn("Not run", message)

    def test_off_setting_and_other_tools_are_untouched(self):
        self.assertIsNone(self._call("sed -i 's/a/b/' src/benchapp/retries.py"))
        self._setting("true")
        self.assertIsNone(self._call("sed -i 's/a/b/' src/benchapp/retries.py", tool="execute_code"))
        self.assertIsNone(
            shell_edit_directive(tool_name="terminal", tool_input="sed -i x f.py", hermes_home=str(self.hermes))
        )

    def test_relative_workdir_resolves_against_the_workspace(self):
        self._setting("true")
        with patch.dict(os.environ, {"TERMINAL_CWD": str(self.root)}):
            directive = shell_edit_directive(
                tool_name="terminal",
                tool_input={"command": "echo x > benchapp/retries.py", "workdir": "src"},
                hermes_home=str(self.hermes),
            )
        self.assertIsNotNone(directive)


class HookTest(_Workspace):
    def test_pre_tool_call_refuses_an_in_place_edit_when_on(self):
        self._setting("true")
        result = pre_tool_call(
            tool_name="terminal",
            args={"command": "sed -i 's/a/b/' src/benchapp/retries.py", "workdir": str(self.root)},
            session_id="session-a",
            omh_home=str(self.omh),
            hermes_home=str(self.hermes),
        )
        self.assertEqual(result["action"], "block")
        self.assertIn("[OMH shell-edit rule]", result["message"])
        # A refused call never dispatched, so the burst ledger has nothing.
        self.assertFalse((self.omh / "runtime" / "tool-bursts.json").exists())

    def test_pre_tool_call_lets_a_read_through_when_on(self):
        self._setting("true")
        result = pre_tool_call(
            tool_name="terminal",
            args={"command": "sed -n '1p' src/benchapp/retries.py", "workdir": str(self.root)},
            session_id="session-a",
            omh_home=str(self.omh),
            hermes_home=str(self.hermes),
        )
        self.assertFalse(result and result.get("action") == "block")


if __name__ == "__main__":
    unittest.main()
