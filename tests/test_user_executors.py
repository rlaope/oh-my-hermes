"""The user executor registry: entry rules, file trust boundary, presets.

Every test uses an explicit disposable home. Nothing here reads the
developer's own home, a repository file or the cwd: the point of the module is
that the only trusted source is `<omh_home>/routing/executors.toml`, so a test
that passed by accident from an ambient file would prove the opposite of the
contract.
"""

from __future__ import annotations

import os
import stat
import tomllib
import unittest
from pathlib import Path
from threading import Thread
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _test_temp_root import make_test_tempdir  # noqa: E402
from omh.coding.executor_presets import PRESETS, get_preset, preset_ids  # noqa: E402
from omh.coding.user_executors import (  # noqa: E402
    RESERVED_OWNER_IDS,
    USER_EXECUTORS_MAX_BYTES,
    ExecutorConfigError,
    ExecutorRegistry,
    ExecutorSpec,
    add_executor_preset,
    fanout_owner_ids,
    load_user_executors,
    remove_user_executor,
    render_user_argv,
    user_executors_path,
    valid_executor_id,
    validate_executor_entry,
)

VALID_ENTRY_TOML = """\
schema_version = 1

[executors.my-agent]
label = "My Agent"
argv = ["my-agent", "run", "--", "{prompt}"]
model = ["--model", "{model}"]
effort = ["--effort", "{effort}"]
insert = 2
version = ["my-agent", "cli", "--version"]
"""


class _HomeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        holder = make_test_tempdir(prefix="omh-user-executors-")
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name)

    def write_config(self, text: str) -> Path:
        path = user_executors_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def load(self) -> ExecutorRegistry:
        return load_user_executors(self.home)

    def reasons(self, registry: ExecutorRegistry) -> set[str]:
        return {issue.reason for issue in registry.issues}


class EntryValidationTests(_HomeTestCase):
    def test_valid_entry_loads_with_defaults(self) -> None:
        self.write_config(VALID_ENTRY_TOML)

        registry = self.load()

        self.assertEqual(registry.issues, ())
        spec = registry.entries["my-agent"]
        self.assertIsInstance(spec, ExecutorSpec)
        self.assertEqual(spec.id, "my-agent")
        self.assertEqual(spec.label, "My Agent")
        self.assertEqual(spec.argv, ("my-agent", "run", "--", "{prompt}"))
        self.assertEqual(spec.model, ("--model", "{model}"))
        self.assertEqual(spec.effort, ("--effort", "{effort}"))
        self.assertEqual(spec.insert, 2)
        self.assertEqual(spec.version, ("my-agent", "cli", "--version"))
        self.assertEqual(spec.export, ())
        self.assertEqual(spec.resume, ())
        self.assertIsNone(spec.preset_id)
        self.assertIsNone(spec.remote_adapter)
        self.assertFalse(spec.remote_pr)
        self.assertFalse(spec.validated)
        self.assertEqual(len(spec.definition_sha256), 64)
        int(spec.definition_sha256, 16)

    def test_label_defaults_to_the_id_and_version_to_version_flag(self) -> None:
        spec, issues = validate_executor_entry(
            "bare", {"argv": ["bare", "--print", "{prompt}"]}
        )

        self.assertEqual(issues, ())
        assert spec is not None
        self.assertEqual(spec.label, "bare")
        self.assertEqual(spec.version, ("bare", "--version"))
        self.assertEqual(spec.insert, 1)

    def test_prompt_placeholder_must_occupy_exactly_one_element(self) -> None:
        cases = {
            "missing": (["my-agent", "run", "--"], "placeholder_count"),
            "twice": (["my-agent", "{prompt}", "{prompt}"], "placeholder_count"),
            "inline": (["my-agent", "--prompt={prompt}"], "placeholder_count"),
            "both": (["my-agent", "{prompt}", "{prompt_file}"], "placeholder_count"),
            "stray_brace": (["my-agent", "{prompt}", "--x={nope}"], "stray_braces"),
            "as_program": (["{prompt}", "run"], "program_placeholder"),
        }
        for name, (argv, reason) in cases.items():
            with self.subTest(case=name):
                spec, issues = validate_executor_entry("my-agent", {"argv": argv})
                self.assertIsNone(spec)
                self.assertTrue(issues)
                self.assertIn(reason, {issue.reason for issue in issues})

    def test_string_argv_is_refused(self) -> None:
        spec, issues = validate_executor_entry(
            "my-agent", {"argv": "my-agent run -- {prompt}"}
        )

        self.assertIsNone(spec)
        self.assertEqual(issues[0].field, "argv")
        self.assertEqual(issues[0].reason, "invalid_vector")

    def test_argv_vector_limits_and_token_types(self) -> None:
        cases = {
            "empty": [],
            "too_many": ["my-agent"] + ["x"] * 64 + ["{prompt}"],
            "empty_token": ["my-agent", "", "{prompt}"],
            "non_string": ["my-agent", 3, "{prompt}"],
            "control": ["my-agent", "a\x07b", "{prompt}"],
            "too_long": ["my-agent", "x" * 5000, "{prompt}"],
        }
        for name, argv in cases.items():
            with self.subTest(case=name):
                spec, issues = validate_executor_entry("my-agent", {"argv": argv})
                self.assertIsNone(spec)
                self.assertEqual(issues[0].field, "argv")

    def test_bad_ids_are_refused(self) -> None:
        for bad in ("a", "My-Agent", "1agent", "my_agent", "user:my-agent", "agent-" + "x" * 40):
            with self.subTest(executor_id=bad):
                self.assertFalse(valid_executor_id(bad))
                spec, issues = validate_executor_entry(
                    bad, {"argv": ["my-agent", "{prompt}"]}
                )
                self.assertIsNone(spec)
                self.assertEqual(issues[0].field, "id")
                self.assertEqual(issues[0].reason, "invalid_id")

    def test_builtins_presets_and_reserved_words_cannot_be_shadowed(self) -> None:
        for reserved in ("codex", "claude-code", "maestro", "choose", "unassigned", "devin", "gemini"):
            with self.subTest(executor_id=reserved):
                self.assertIn(reserved, RESERVED_OWNER_IDS)
                spec, issues = validate_executor_entry(
                    reserved, {"argv": [reserved, "-p", "{prompt}"]}
                )
                self.assertIsNone(spec)
                self.assertIn("shadowed_id", {issue.reason for issue in issues})

    def test_reserved_progress_aliases_cannot_be_declared(self) -> None:
        # `executor_progress.normalize_executor_profile` already maps these
        # names onto shipped lanes when a stored record is read, so a custom
        # executor spelled the same would silently change what that record
        # means. They are aliases, not free ids.
        for alias in ("claude", "claude-code-cli", "pi", "opencode", "hermes-local"):
            with self.subTest(executor_id=alias):
                self.assertIn(alias, RESERVED_OWNER_IDS)
                spec, issues = validate_executor_entry(
                    alias, {"argv": [alias, "-p", "{prompt}"]}
                )
                self.assertIsNone(spec)
                self.assertIn("shadowed_id", {issue.reason for issue in issues})

    def test_shell_and_path_programs_are_refused(self) -> None:
        cases = {
            "sh": "shell_program",
            "bash.exe": "shell_program",
            "python3": "shell_program",
            "runner.cmd": "shell_program",
            "/usr/bin/tool": "program_path",
            "./tool": "program_path",
            "-p": "invalid_program",
        }
        for program, reason in cases.items():
            with self.subTest(program=program):
                spec, issues = validate_executor_entry(
                    "my-agent", {"argv": [program, "{prompt}"]}
                )
                self.assertIsNone(spec)
                self.assertEqual(issues[0].field, "argv")
                self.assertEqual(issues[0].reason, reason)

    def test_local_vector_may_not_declare_the_cloud_lane(self) -> None:
        for argv in (
            ["devin", "--cloud", "-p", "{prompt}"],
            ["my-agent", "cloud", "-p", "{prompt}"],
        ):
            with self.subTest(argv=argv):
                spec, issues = validate_executor_entry("my-agent", {"argv": argv})
                self.assertIsNone(spec)
                self.assertEqual(issues[0].reason, "cloud_refused")

    def test_cloud_switch_is_refused_in_every_fragment(self) -> None:
        # Rendering splices a fragment into the final argv, so a fragment is
        # just as good a way to spell the cloud lane as the base vector: the
        # check has to read the whole effective command, not only argv.
        argv = ["my-agent", "run", "--", "{prompt}"]
        cases = {
            "model": {"model": ["--cloud", "--model", "{model}"]},
            "effort": {"effort": ["--cloud", "--effort", "{effort}"]},
            "session.export": {
                "session": {"export": ["--cloud", "--export", "{session_file}"]}
            },
            "session.resume": {
                "session": {
                    "export": ["--export", "{session_file}"],
                    "resume": ["--cloud", "-r", "{session_id}"],
                }
            },
            "version": {"version": ["my-agent", "--cloud", "--version"]},
        }
        for field, entry in cases.items():
            with self.subTest(field=field):
                spec, issues = validate_executor_entry("my-agent", {"argv": argv, **entry})
                self.assertIsNone(spec)
                fields = {issue.field for issue in issues if issue.reason == "cloud_refused"}
                self.assertEqual(fields, {field}, issues)

    def test_all_cloud_spellings_use_the_same_fragment_rule(self) -> None:
        for token in ("cloud", "--cloud", "--cloud=true"):
            cases = {
                "argv": {"argv": ["my-agent", token, "{prompt}"]},
                "version": {"version": ["my-agent", token, "--version"]},
                "model": {"model": [token, "{model}"]},
                "effort": {"effort": [token, "{effort}"]},
                "session.export": {"session": {"export": [token, "{session_file}"]}},
                "session.resume": {"session": {"export": ["--export", "{session_file}"],
                                               "resume": [token, "{session_id}"]}},
            }
            for field, entry in cases.items():
                with self.subTest(token=token, field=field):
                    spec, issues = validate_executor_entry("my-agent", {"argv": ["my-agent", "{prompt}"], **entry})
                    self.assertEqual({(issue.field, issue.reason) for issue in issues}, {(field, "cloud_refused")})
                    self.assertIsNone(spec)

    def test_insert_is_a_bounded_non_bool_int(self) -> None:
        cases = {
            0: "insert_out_of_range",
            99: "insert_out_of_range",
            True: "invalid_insert",
            "2": "invalid_insert",
            1.5: "invalid_insert",
        }
        for insert, reason in cases.items():
            with self.subTest(insert=insert):
                spec, issues = validate_executor_entry(
                    "my-agent", {"argv": ["my-agent", "{prompt}"], "insert": insert}
                )
                self.assertIsNone(spec)
                self.assertEqual(issues[0].field, "insert")
                self.assertEqual(issues[0].reason, reason)

    def test_version_probe_is_a_version_query_not_a_workload(self) -> None:
        cases = {
            '["other", "--version"]': "version_program",
            '["my-agent", "--json"]': "version_probe",
            '["my-agent", "run", "--version", "extra"]': "version_probe",
        }
        for version_toml, reason in cases.items():
            with self.subTest(version=version_toml):
                raw = tomllib.loads(
                    "argv = ['my-agent', '{prompt}']\nversion = " + version_toml
                )
                spec, issues = validate_executor_entry("my-agent", raw)
                self.assertIsNone(spec)
                self.assertEqual(issues[0].field, "version")
                self.assertEqual(issues[0].reason, reason)

    def test_unknown_entry_keys_are_refused(self) -> None:
        spec, issues = validate_executor_entry(
            "my-agent",
            {"argv": ["my-agent", "{prompt}"], "success": True},
        )

        self.assertIsNone(spec)
        self.assertEqual(issues[0].field, "success")
        self.assertEqual(issues[0].reason, "unknown_key")

    def test_session_table_requires_export_and_matching_placeholders(self) -> None:
        spec, issues = validate_executor_entry(
            "my-agent",
            {
                "argv": ["my-agent", "{prompt}"],
                "session": {"export": ["--export", "{session_file}"], "resume": ["-r", "{session_id}"]},
            },
        )
        self.assertEqual(issues, ())
        assert spec is not None
        self.assertEqual(spec.export, ("--export", "{session_file}"))
        self.assertEqual(spec.resume, ("-r", "{session_id}"))

        missing, missing_issues = validate_executor_entry(
            "my-agent", {"argv": ["my-agent", "{prompt}"], "session": {"resume": ["-r", "{session_id}"]}}
        )
        self.assertIsNone(missing)
        self.assertEqual(missing_issues[0].field, "session.export")
        self.assertEqual(missing_issues[0].reason, "missing")

        wrong, wrong_issues = validate_executor_entry(
            "my-agent",
            {"argv": ["my-agent", "{prompt}"], "session": {"export": ["--export", "{session_id}"]}},
        )
        self.assertIsNone(wrong)
        self.assertEqual(wrong_issues[0].field, "session.export")
        self.assertEqual(wrong_issues[0].reason, "placeholder_count")

    def test_remote_pr_is_only_for_the_shipped_cloud_adapter(self) -> None:
        custom, custom_issues = validate_executor_entry(
            "my-agent", {"argv": ["my-agent", "{prompt}"], "remote_pr": True}
        )
        self.assertIsNone(custom)
        self.assertEqual(custom_issues[0].reason, "remote_pr_unsupported")

        gemini, gemini_issues = validate_executor_entry(
            "gemini", {"preset": "gemini", "remote_pr": True}
        )
        self.assertIsNone(gemini)
        self.assertEqual(gemini_issues[0].reason, "remote_pr_unsupported")

        devin, devin_issues = validate_executor_entry(
            "devin", {"preset": "devin", "remote_pr": True}
        )
        self.assertEqual(devin_issues, ())
        assert devin is not None
        self.assertTrue(devin.remote_pr)
        self.assertEqual(devin.remote_adapter, "devin_cloud_v1")

    def test_preset_reference_requires_its_own_id_and_nothing_else(self) -> None:
        spec, issues = validate_executor_entry("my-devin", {"preset": "devin"})

        self.assertIsNone(spec)
        self.assertIn("preset_id_mismatch", {issue.reason for issue in issues})

        spec, issues = validate_executor_entry(
            "devin", {"preset": "devin", "argv": ["devin", "{prompt}"]}
        )
        self.assertIsNone(spec)
        self.assertIn("unknown_key", {issue.reason for issue in issues})

        spec, issues = validate_executor_entry("devin", {"preset": "not-a-preset"})
        self.assertIsNone(spec)
        self.assertEqual(issues[0].reason, "unknown_preset")

    def test_digest_covers_behaviour_but_not_display_fields(self) -> None:
        base, _ = validate_executor_entry(
            "my-agent", {"argv": ["my-agent", "{prompt}"], "label": "One"}
        )
        relabelled, _ = validate_executor_entry(
            "my-agent", {"argv": ["my-agent", "{prompt}"], "label": "Two"}
        )
        changed, _ = validate_executor_entry(
            "my-agent", {"argv": ["my-agent", "--", "{prompt}"]}
        )

        assert base is not None and relabelled is not None and changed is not None
        self.assertEqual(base.definition_sha256, relabelled.definition_sha256)
        self.assertNotEqual(base.definition_sha256, changed.definition_sha256)

    def test_a_second_home_is_not_shared_with_the_first(self) -> None:
        other_holder = make_test_tempdir(prefix="omh-user-executors-other-")
        self.addCleanup(other_holder.cleanup)
        other_home = Path(other_holder.name)
        self.write_config(VALID_ENTRY_TOML)
        other_path = user_executors_path(other_home)
        other_path.parent.mkdir(parents=True, exist_ok=True)
        other_path.write_text(
            "schema_version = 1\n\n[executors.others]\nargv = ['others', '{prompt}']\n",
            encoding="utf-8",
        )

        self.assertEqual(set(load_user_executors(self.home).entries), {"my-agent"})
        self.assertEqual(set(load_user_executors(other_home).entries), {"others"})


class FileTrustTests(_HomeTestCase):
    def test_missing_file_is_an_empty_registry_with_no_issue(self) -> None:
        registry = self.load()

        self.assertEqual(dict(registry.entries), {})
        self.assertEqual(registry.issues, ())

    def test_relative_home_is_refused(self) -> None:
        registry = load_user_executors(Path("relative-home"))

        self.assertEqual(dict(registry.entries), {})
        self.assertEqual(registry.issues[0].field, "omh_home")
        self.assertEqual(registry.issues[0].reason, "relative_home")

    def test_malformed_toml_is_reported_not_raised(self) -> None:
        self.write_config("schema_version = 1\n[executors.my-agent\n")

        registry = self.load()

        self.assertEqual(dict(registry.entries), {})
        self.assertEqual(self.reasons(registry), {"malformed_toml"})

    def test_undecodable_and_oversized_files_are_refused(self) -> None:
        path = user_executors_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\x00not utf-8")
        self.assertEqual(self.reasons(self.load()), {"undecodable"})

        path.write_bytes(b"#" + b"x" * (USER_EXECUTORS_MAX_BYTES + 16))
        self.assertEqual(self.reasons(self.load()), {"too_large"})

    def test_directory_in_place_of_the_file_is_refused(self) -> None:
        path = user_executors_path(self.home)
        path.mkdir(parents=True)

        self.assertEqual(self.reasons(self.load()), {"not_regular_file"})

    @unittest.skipUnless(os.name == "posix", "external executor lane is POSIX only")
    def test_a_fifo_registry_never_blocks_the_reader(self) -> None:
        # A writer-less FIFO blocks in open(2) until somebody reads it. Listing
        # or dispatching must not wait there: the reader opens non-blocking,
        # fstats first and reports a non-regular file instead of reading.
        path = user_executors_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(path)
        loaded: list[ExecutorRegistry] = []
        reader = Thread(target=lambda: loaded.append(self.load()), daemon=True)

        reader.start()
        reader.join(1.0)

        self.assertFalse(reader.is_alive(), "load_user_executors blocked on a FIFO registry")
        self.assertEqual(dict(loaded[0].entries), {})
        self.assertIn("not_regular_file", self.reasons(loaded[0]))

    def test_root_schema_is_closed(self) -> None:
        cases = {
            "unknown_key": ("schema_version = 1\nlayout = 2\n", "unknown_root_key"),
            "version": ("schema_version = 2\n", "unsupported_schema"),
            "missing_version": ("[executors.my-agent]\nargv = ['my-agent', '{prompt}']\n", "unsupported_schema"),
            "bool_version": ("schema_version = true\n", "unsupported_schema"),
        }
        for name, (text, reason) in cases.items():
            with self.subTest(case=name):
                self.write_config(text)
                registry = self.load()
                self.assertEqual(dict(registry.entries), {})
                self.assertIn(reason, self.reasons(registry))

    def test_one_bad_entry_does_not_drop_its_valid_sibling(self) -> None:
        self.write_config(
            VALID_ENTRY_TOML
            + "\n[executors.broken]\nargv = \"broken run {prompt}\"\n"
        )

        registry = self.load()

        self.assertEqual(set(registry.entries), {"my-agent"})
        self.assertEqual(len(registry.issues), 1)
        self.assertEqual(registry.issues[0].executor_id, "broken")
        self.assertEqual(registry.issues[0].field, "argv")
        self.assertEqual(registry.issues[0].reason, "invalid_vector")

    def test_a_file_in_the_cwd_is_never_the_registry(self) -> None:
        cwd_holder = make_test_tempdir(prefix="omh-user-executors-cwd-")
        self.addCleanup(cwd_holder.cleanup)
        cwd = Path(cwd_holder.name)
        (cwd / "routing").mkdir()
        (cwd / "routing" / "executors.toml").write_text(
            "schema_version = 1\n\n[executors.sneaky]\nargv = ['sneaky', '{prompt}']\n",
            encoding="utf-8",
        )
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(cwd)

        registry = self.load()

        self.assertEqual(dict(registry.entries), {})
        self.assertEqual(registry.issues, ())
        self.assertEqual(user_executors_path(self.home), self.home / "routing" / "executors.toml")

    def test_a_symlinked_file_outside_the_home_is_refused(self) -> None:
        outside_holder = make_test_tempdir(prefix="omh-user-executors-outside-")
        self.addCleanup(outside_holder.cleanup)
        outside = Path(outside_holder.name) / "executors.toml"
        outside.write_text(
            "schema_version = 1\n\n[executors.sneaky]\nargv = ['sneaky', '{prompt}']\n",
            encoding="utf-8",
        )
        link = user_executors_path(self.home)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)

        registry = self.load()

        self.assertEqual(dict(registry.entries), {})
        self.assertIn(self.reasons(registry), ({"symlink_refused"}, {"path_escape"}))

    def test_fanout_owner_ids_are_builtins_then_sorted_additions(self) -> None:
        self.write_config(
            VALID_ENTRY_TOML
            + "\n[executors.zeta]\nargv = ['zeta', '{prompt}']\n"
        )

        owners = fanout_owner_ids(self.load())

        self.assertIn("codex", owners)
        self.assertEqual(owners[-2:], ("my-agent", "zeta"))
        self.assertEqual(len(owners), len(set(owners)))


class MutationTests(_HomeTestCase):
    def test_add_and_remove_round_trip(self) -> None:
        spec = add_executor_preset(self.home, "devin")

        self.assertEqual(spec.preset_id, "devin")
        self.assertFalse(spec.validated)
        path = user_executors_path(self.home)
        self.assertEqual(
            tomllib.loads(path.read_text(encoding="utf-8")),
            {"schema_version": 1, "executors": {"devin": {"preset": "devin"}}},
        )
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

        registry = self.load()
        self.assertEqual(registry.issues, ())
        self.assertEqual(registry.entries["devin"].argv, PRESETS["devin"].argv)

        with self.assertRaises(ExecutorConfigError) as context:
            add_executor_preset(self.home, "devin")
        self.assertEqual(context.exception.reason, "already_exists")

        before = path.read_bytes()
        forced = add_executor_preset(self.home, "devin", force=True)
        self.assertEqual(forced.definition_sha256, spec.definition_sha256)
        self.assertEqual(path.read_bytes(), before)

        remove_user_executor(self.home, "devin")
        self.assertEqual(dict(self.load().entries), {})
        with self.assertRaises(ExecutorConfigError) as context:
            remove_user_executor(self.home, "devin")
        self.assertEqual(context.exception.reason, "not_found")

    def test_add_preserves_a_custom_entry_and_its_nested_values(self) -> None:
        self.write_config(
            VALID_ENTRY_TOML
            + "\n[executors.my-agent.session]\nexport = [\"--export\", \"{session_file}\"]\n"
            + "resume = [\"--resume\", \"{session_id}\"]\n"
        )

        add_executor_preset(self.home, "aider")

        registry = self.load()
        self.assertEqual(set(registry.entries), {"aider", "my-agent"})
        custom = registry.entries["my-agent"]
        self.assertEqual(custom.label, "My Agent")
        self.assertEqual(custom.model, ("--model", "{model}"))
        self.assertEqual(custom.effort, ("--effort", "{effort}"))
        self.assertEqual(custom.insert, 2)
        self.assertEqual(custom.version, ("my-agent", "cli", "--version"))
        self.assertEqual(custom.export, ("--export", "{session_file}"))
        self.assertEqual(custom.resume, ("--resume", "{session_id}"))

        remove_user_executor(self.home, "aider")

        registry = self.load()
        self.assertEqual(set(registry.entries), {"my-agent"})
        self.assertEqual(registry.entries["my-agent"].export, ("--export", "{session_file}"))

    def test_a_refused_file_is_never_rewritten(self) -> None:
        broken = "schema_version = 1\n[executors.my-agent\n"
        path = self.write_config(broken)
        before = path.read_bytes()

        for call in (
            lambda: add_executor_preset(self.home, "devin"),
            lambda: remove_user_executor(self.home, "devin"),
        ):
            with self.subTest(call=call):
                with self.assertRaises(ExecutorConfigError) as context:
                    call()
                self.assertEqual(context.exception.reason, "invalid_file")
                self.assertEqual(path.read_bytes(), before)

    def test_force_resets_an_existing_preset_reference(self) -> None:
        path = self.write_config(
            'schema_version = 1\n\n[executors.devin]\npreset = "devin"\nremote_pr = true\n'
        )
        with self.assertRaises(ExecutorConfigError) as context:
            add_executor_preset(self.home, "devin")
        self.assertEqual(context.exception.reason, "already_exists")

        spec = add_executor_preset(self.home, "devin", force=True)

        self.assertEqual(spec.preset_id, "devin")
        self.assertEqual(
            tomllib.loads(path.read_text(encoding="utf-8")),
            {"schema_version": 1, "executors": {"devin": {"preset": "devin"}}},
        )

    def test_unknown_preset_and_bad_ids_leave_no_file(self) -> None:
        with self.assertRaises(ExecutorConfigError) as context:
            add_executor_preset(self.home, "not-a-preset")
        self.assertEqual(context.exception.reason, "unknown_preset")

        with self.assertRaises(ExecutorConfigError) as context:
            remove_user_executor(self.home, "Not-A-Preset")
        self.assertEqual(context.exception.reason, "invalid_id")

        with self.assertRaises(ExecutorConfigError) as context:
            remove_user_executor(self.home, "not-a-preset")
        self.assertEqual(context.exception.reason, "not_found")

        self.assertFalse(user_executors_path(self.home).exists())

    def test_concurrent_adds_keep_both_entries(self) -> None:
        errors: list[BaseException] = []

        def add(preset_id: str) -> None:
            try:
                add_executor_preset(self.home, preset_id)
            except BaseException as error:  # noqa: BLE001 - reported below
                errors.append(error)

        threads = [
            Thread(target=add, args=("devin",)),
            Thread(target=add, args=("aider",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

        self.assertEqual(errors, [])
        self.assertEqual(set(self.load().entries), {"devin", "aider"})


class OperatorHomeTests(unittest.TestCase):
    def test_the_registry_home_is_the_operator_home_under_every_scope(self) -> None:
        holder = make_test_tempdir(prefix="omh-user-executors-operator-")
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        operator_home = (root / "operator" / ".omh").resolve()
        environment = {
            "HOME": str(root / "home"),
            "USERPROFILE": str(root / "home"),
            "HERMES_HOME": str(root / "home" / ".hermes"),
            "OMH_HOME": str(operator_home),
        }
        # Imported here, not at module scope, so a missing helper fails this
        # test rather than every test in the file.
        from omh.coding.user_executors import operator_executor_home

        with mock.patch.dict(os.environ, environment):
            self.assertEqual(
                operator_executor_home(None, None, scope="project"), operator_home
            )
            self.assertEqual(
                operator_executor_home(None, None, scope="user"), operator_home
            )
            # A store the operator named is the store the operator meant,
            # whatever the artifact scope says.
            named = (root / "named-home").resolve()
            self.assertEqual(
                operator_executor_home(named, None, scope="project"), named
            )


class PresetTests(unittest.TestCase):
    def test_every_preset_row_validates_as_an_opt_in_reference(self) -> None:
        self.assertEqual(len(preset_ids()), 9)
        for preset_id in preset_ids():
            with self.subTest(preset_id=preset_id):
                preset = PRESETS[preset_id]
                spec, issues = validate_executor_entry(preset_id, {"preset": preset_id})
                self.assertEqual(issues, ())
                assert spec is not None
                self.assertEqual(spec.id, preset_id)
                self.assertEqual(spec.preset_id, preset_id)
                self.assertEqual(spec.argv, preset.argv)
                self.assertEqual(spec.model, preset.model)
                self.assertEqual(spec.effort, preset.effort)
                self.assertEqual(spec.insert, preset.insert)
                self.assertEqual(spec.version, preset.version)
                self.assertEqual(spec.export, preset.export)
                self.assertEqual(spec.resume, preset.resume)
                self.assertEqual(spec.remote_adapter, preset.remote_adapter)
                self.assertFalse(preset.validated)
                self.assertFalse(spec.validated)
                self.assertTrue(preset.source_url.startswith("https://"))

    def test_devin_preset_matches_the_documented_flags_exactly(self) -> None:
        preset = get_preset("devin")

        assert preset is not None
        self.assertEqual(
            preset.argv,
            (
                "devin",
                "-p",
                "--permission-mode",
                "accept-edits",
                "--respect-workspace-trust",
                "false",
                "--",
                "{prompt}",
            ),
        )
        self.assertEqual(preset.model, ("--model", "{model}"))
        self.assertEqual(preset.insert, 6)
        self.assertEqual(preset.version, ("devin", "--version"))
        self.assertEqual(preset.export, ("--export", "{session_file}"))
        self.assertEqual(preset.resume, ("-r", "{session_id}"))
        self.assertEqual(preset.remote_adapter, "devin_cloud_v1")
        self.assertFalse(preset.validated)
        self.assertNotIn("--cloud", preset.argv)

    def test_only_devin_ships_session_and_adapter_fields(self) -> None:
        for preset_id in preset_ids():
            preset = PRESETS[preset_id]
            with self.subTest(preset_id=preset_id):
                self.assertEqual(preset.version[0], preset.argv[0])
                self.assertEqual(preset.version[1:], ("--version",))
                if preset_id == "devin":
                    continue
                self.assertEqual(preset.export, ())
                self.assertEqual(preset.resume, ())
                self.assertIsNone(preset.remote_adapter)

    def test_preset_lookup_is_exact_and_case_sensitive(self) -> None:
        self.assertIsNone(get_preset("Devin"))
        self.assertIsNone(get_preset("not-a-preset"))
        self.assertIsNone(get_preset(None))  # type: ignore[arg-type]
        self.assertEqual(preset_ids(), tuple(sorted(PRESETS)))


class RenderUserArgvTests(unittest.TestCase):
    def spec(self, **raw: object) -> ExecutorSpec:
        base: dict[str, object] = {"argv": ["my-agent", "run", "--", "{prompt}"]}
        base.update(raw)
        spec, issues = validate_executor_entry("my-agent", base)
        self.assertEqual(issues, ())
        assert spec is not None
        return spec

    def test_prompt_with_metacharacters_is_one_literal_element(self) -> None:
        prompt = "-rf $(rm -rf /) `id` ; echo\nexport X=1 {}"

        argv = render_user_argv(self.spec(), prompt=prompt)

        self.assertEqual(argv, ["my-agent", "run", "--", prompt])
        self.assertEqual(argv[3], prompt)

    def test_model_and_effort_splice_at_the_validated_index(self) -> None:
        spec = self.spec(model=["--model", "{model}"], effort=["--effort", "{effort}"], insert=2)

        argv = render_user_argv(spec, prompt="p", model="m", effort="high")

        self.assertEqual(
            argv,
            ["my-agent", "run", "--model", "m", "--effort", "high", "--", "p"],
        )

    def test_unsupported_fragments_are_refused_not_dropped(self) -> None:
        spec = self.spec()

        for kwargs, reason in (
            ({"model": "m"}, "model_unsupported"),
            ({"effort": "high"}, "effort_unsupported"),
            ({"session_file": Path("/tmp/session.json")}, "session_export_unsupported"),
            ({"session_id": "devin-abc"}, "session_resume_unsupported"),
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(ExecutorConfigError) as context:
                    render_user_argv(spec, prompt="p", **kwargs)  # type: ignore[arg-type]
                self.assertEqual(context.exception.reason, reason)

    def test_file_prompt_requires_a_real_dispatcher_owned_file(self) -> None:
        spec = self.spec(argv=["my-agent", "--task-file", "{prompt_file}"], insert=1)

        with self.assertRaises(ExecutorConfigError) as context:
            render_user_argv(spec, prompt="p")
        self.assertEqual(context.exception.reason, "prompt_file_required")

        with self.assertRaises(ExecutorConfigError) as context:
            render_user_argv(spec, prompt="p", prompt_file=Path("/nonexistent/prompt.txt"))
        self.assertEqual(context.exception.reason, "prompt_file_unavailable")

        holder = make_test_tempdir(prefix="omh-user-executors-prompt-")
        self.addCleanup(holder.cleanup)
        prompt_file = Path(holder.name) / "prompt.txt"
        prompt_file.write_text("task", encoding="utf-8")

        argv = render_user_argv(spec, prompt="p", prompt_file=prompt_file)
        self.assertEqual(argv, ["my-agent", "--task-file", str(prompt_file)])

    def test_devin_session_fragments_render_before_the_prompt_separator(self) -> None:
        spec, issues = validate_executor_entry("devin", {"preset": "devin"})
        self.assertEqual(issues, ())
        assert spec is not None

        argv = render_user_argv(
            spec,
            prompt="do the task",
            model="swe-1.5",
            session_file=Path("/tmp/unit/session.json"),
            session_id="devin-0123456789abcdef0123456789abcdef",
        )

        self.assertEqual(
            argv,
            [
                "devin",
                "-p",
                "--permission-mode",
                "accept-edits",
                "--respect-workspace-trust",
                "false",
                "--model",
                "swe-1.5",
                "--export",
                str(Path("/tmp/unit/session.json")),
                "-r",
                "devin-0123456789abcdef0123456789abcdef",
                "--",
                "do the task",
            ],
        )


if __name__ == "__main__":
    unittest.main()
