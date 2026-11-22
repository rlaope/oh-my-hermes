from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.config_adapter import (
    ensure_plugin_enabled,
    plugin_enablement,
    plugin_enablement_is_readable,
    plugin_enablement_shape_error,
    plugin_is_enabled,
    plugins_enabled_extension_error,
    remove_plugin_enabled,
)
from omh.maintenance import doctor as doctor_module
from omh.maintenance.doctor import run_doctor
from omh.paths import resolve_paths
from omh.plugin_pack import PLUGIN_NAME


ENABLED_CONFIG = """skills:
  external_dirs: []

plugins:
  enabled:
    - omh
  disabled: []
  entries:
    omh:
      allow_tool_override: false
"""

DISABLED_CONFIG = ENABLED_CONFIG.replace("  enabled:\n    - omh\n", "  enabled:\n")

# One corpus, answered by every caller below. Each pair is a `plugins` node
# OMH reads and whether it enables `omh`; each expectation is the answer
# Hermes' own loader gives that text, measured with the PyYAML in the Hermes
# venv rather than reasoned about here. The block form, the single-line flow
# mapping and a `plugins:` line carrying only a comment are all forms Hermes
# loads, so all three have to reach the same answer (#1814).
READABLE_PLUGINS_NODES: tuple[tuple[str, bool], ...] = (
    ("plugins:\n  enabled:\n    - omh\n", True),
    ("plugins: {enabled: [omh]}\n", True),
    ("plugins: {enabled: [omh], disabled: [browser]}\n", True),
    ("plugins: {enabled: [omh]} # third-party\n", True),
    ("plugins:   {  enabled : [ omh , other ] }\n", True),
    ("plugins:  # third-party\n  enabled:\n    - omh\n", True),
    ("plugins: {enabled: ['omh']}\n", True),
    ("plugins:\n  enabled: []\n", False),
    ("plugins: {}\n", False),
    ("plugins: {enabled: [browser]}\n", False),
    ("plugins: {enabled: [omh], disabled: [omh]}\n", False),
    ("plugins: {disabled: [omh]}\n", False),
    ("plugins: {enabled: null}\n", False),
    ("plugins:  # none yet\n  enabled: []\n", False),
)

# Nodes outside what the reader follows. The first two and the fifth are valid
# YAML that enables `omh` -- an alias, an anchored block, a repeated key whose
# last value wins -- so an empty answer over them would be the exact false
# negative this corpus exists to keep out. The fourth and the last are files
# Hermes refuses to parse at all. None of them may render as "not enabled".
UNREADABLE_PLUGINS_NODES: tuple[str, ...] = (
    "base: &plugins\n  enabled: [omh]\nplugins: *plugins\n",
    "plugins: &p\n  enabled:\n    - omh\n",
    "plugins: {enabled: {omh: true}}\n",
    "plugins: {enabled: [omh}\n",
    "plugins: {enabled: [a], enabled: [omh]}\n",
    'plugins: {enabled: ["om\\"h"]}\n',
    "plugins: browser\n",
    "plugins: {enabled [omh]}\n",
)


class PluginEnablementReaderTests(unittest.TestCase):
    """Hermes keeps enablement in `plugins.enabled` and nowhere else."""

    def test_block_list_form(self) -> None:
        self.assertTrue(plugin_is_enabled(ENABLED_CONFIG, PLUGIN_NAME))
        self.assertFalse(plugin_is_enabled(DISABLED_CONFIG, PLUGIN_NAME))

    def test_inline_list_form(self) -> None:
        self.assertTrue(plugin_is_enabled("plugins:\n  enabled: [omh, other]\n  disabled: []\n", PLUGIN_NAME))
        self.assertFalse(plugin_is_enabled("plugins:\n  enabled: []\n  disabled: []\n", PLUGIN_NAME))

    def test_explicitly_disabled_outranks_enabled(self) -> None:
        text = "plugins:\n  enabled:\n    - omh\n  disabled:\n    - omh\n"
        self.assertFalse(plugin_is_enabled(text, PLUGIN_NAME))

    def test_quoted_items_are_read(self) -> None:
        self.assertTrue(plugin_is_enabled('plugins:\n  enabled:\n    - "omh"\n  disabled: []\n', PLUGIN_NAME))

    def test_a_config_without_a_plugins_block_is_not_enabled(self) -> None:
        self.assertFalse(plugin_is_enabled("skills:\n  external_dirs: []\n", PLUGIN_NAME))

    def test_another_plugin_does_not_count(self) -> None:
        self.assertFalse(plugin_is_enabled("plugins:\n  enabled:\n    - browser\n  disabled: []\n", PLUGIN_NAME))

    def test_enablement_reports_both_lists(self) -> None:
        listed = plugin_enablement("plugins:\n  enabled:\n    - omh\n  disabled:\n    - browser\n")
        self.assertEqual(listed, {"enabled": ["omh"], "disabled": ["browser"]})


    def test_level_indented_list_items_are_read(self) -> None:
        # Issue #1322: `  - omh` (item level with its key) is valid YAML and
        # what a hand-edited config used; the reader saw it as a key line and
        # reported an empty list, so doctor blocked on a plugin that was on.
        level = "plugins:\n  enabled:\n  - omh\n  - agentiker-plan-follow\n  disabled:\n  - github-prs\n"
        self.assertEqual(plugin_enablement(level), {"enabled": ["omh", "agentiker-plan-follow"], "disabled": ["github-prs"]})
        self.assertTrue(plugin_is_enabled(level, PLUGIN_NAME))

    def test_level_indented_items_stay_with_their_own_key(self) -> None:
        level = "plugins:\n  enabled:\n  - other\n  disabled:\n  - omh\n  entries:\n    omh:\n      allow_tool_override: false\n"
        self.assertEqual(plugin_enablement(level), {"enabled": ["other"], "disabled": ["omh"]})
        self.assertFalse(plugin_is_enabled(level, PLUGIN_NAME))

    def test_items_under_an_untracked_key_are_ignored(self) -> None:
        text = "plugins:\n  order:\n  - omh\n  enabled: []\n"
        self.assertEqual(plugin_enablement(text), {"enabled": [], "disabled": []})


class PluginsNodeCorpusTests(unittest.TestCase):
    """Every caller answers the same corpus, and none of them invents a negative.

    The #1814 report: `plugins: {enabled: [hermes-jev]}` is valid YAML Hermes
    loads the plugin from, and the reader's entry condition was the exact text
    `plugins:`, so it returned the empty lists a config enabling nothing
    returns and every caller said "not enabled" about a plugin the host had
    on. The corpus above is what keeps the two answers apart: a node OMH reads
    answers like the block form, a node it does not read answers "unknown"
    everywhere, and neither ever reads as a negative.
    """

    def test_every_readable_node_answers_what_hermes_answers(self) -> None:
        for text, enabled in READABLE_PLUGINS_NODES:
            with self.subTest(text=text):
                self.assertTrue(plugin_enablement_is_readable(text), text)
                self.assertEqual(plugin_is_enabled(text, PLUGIN_NAME), enabled)

    def test_the_flow_form_and_the_block_form_read_the_same_lists(self) -> None:
        # The success criterion stated as one comparison rather than as two
        # separate expectations that could drift apart.
        flow = plugin_enablement("plugins: {enabled: [omh, other], disabled: [browser]}\n")
        block = plugin_enablement(
            "plugins:\n  enabled:\n    - omh\n    - other\n  disabled:\n    - browser\n"
        )
        self.assertEqual(flow, block)
        self.assertEqual(flow, {"enabled": ["omh", "other"], "disabled": ["browser"]})

    def test_every_unreadable_node_is_reported_unread_and_not_as_empty(self) -> None:
        for text in UNREADABLE_PLUGINS_NODES:
            with self.subTest(text=text):
                self.assertFalse(plugin_enablement_is_readable(text), text)
                self.assertEqual(plugin_enablement(text), {"enabled": [], "disabled": []})
                self.assertFalse(plugin_is_enabled(text, PLUGIN_NAME))

    def test_the_reader_enters_only_the_top_level_plugins_key(self) -> None:
        # The classifier matches on the key rather than on the exact line, so
        # the negative control is a key that merely starts the same way and a
        # `plugins` mapping nested under something else.
        for text in (
            "plugins_extra: {enabled: [omh]}\n",
            "hermes:\n  plugins: {enabled: [omh]}\n",
            "other: {plugins: {enabled: [omh]}}\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(plugin_enablement(text), {"enabled": [], "disabled": []})
                self.assertTrue(plugin_enablement_is_readable(text))

    def test_the_writer_refuses_every_node_it_cannot_take_an_item_back_out_of(self) -> None:
        # `remove_plugin_enabled` goes through `section_edit_guard`, which
        # refuses every `plugins` node that is not the plain block. Before
        # this, the writer found no `plugins:` line under a flow mapping and
        # appended a second top-level `plugins:` block; measured with the
        # PyYAML in Hermes' own venv, a duplicate top-level key resolves to
        # its last value, so the person's own list was dropped silently.
        for text in [entry for entry, _ in READABLE_PLUGINS_NODES] + list(UNREADABLE_PLUGINS_NODES):
            listed = plugin_enablement(text)
            if re.fullmatch(r"plugins:[ \t]*(?:#.*)?", text.splitlines()[0]):
                # The plain block, with or without a comment on its key line (#3075).
                continue
            if PLUGIN_NAME in listed["enabled"] or PLUGIN_NAME in listed["disabled"]:
                # No write is needed, so there is nothing to refuse; those
                # nodes are the subject of the test below.
                continue
            with self.subTest(text=text):
                refusal = plugins_enabled_extension_error(text, PLUGIN_NAME)
                self.assertIn("setup extends a plain `plugins:` block", refusal)
                with self.assertRaises(ValueError) as caught:
                    ensure_plugin_enabled(text, PLUGIN_NAME)
                self.assertEqual(str(caught.exception), refusal)
                self.assertFalse(remove_plugin_enabled(text, PLUGIN_NAME).changed)

    def test_the_writer_is_silent_over_a_node_it_would_not_write_to(self) -> None:
        # A flow config that already enables the bridge needs no write, so
        # setup answers "already enabled" and doctor reports no fault.
        for text in ("plugins: {enabled: [omh]}\n", "plugins: {disabled: [omh]}\n"):
            with self.subTest(text=text):
                self.assertEqual(plugins_enabled_extension_error(text, PLUGIN_NAME), "")
                change = ensure_plugin_enabled(text, PLUGIN_NAME)
                self.assertFalse(change.changed)
                self.assertEqual(change.text, text)


class PluginsNodeDoctorTests(unittest.TestCase):
    """`plugin_enabled_in_hermes` over the same corpus.

    The corpus goes through the check function, and one entry per answer also
    goes through `run_doctor`, which is what proves the check is wired into
    the report rather than only callable. Running the whole corpus that way
    costs a doctor sweep per entry and proves the same thing twenty-two times.
    """

    def _check_for(self, config_text: str):
        self.hermes_home.mkdir(parents=True, exist_ok=True)
        (self.hermes_home / "config.yaml").write_text(config_text, encoding="utf-8")
        paths = resolve_paths(self.root / ".omh", self.hermes_home)
        return doctor_module._plugin_enabled_check(paths)

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hermes_home = self.root / ".hermes"

    def test_doctor_reports_the_answer_the_node_carries(self) -> None:
        for text, enabled in READABLE_PLUGINS_NODES:
            with self.subTest(text=text):
                check = self._check_for(text)
                self.assertEqual(check.ok, enabled, check.message)
                self.assertTrue(check.observed)

    def test_doctor_reports_an_unread_node_as_unread_and_never_as_disabled(self) -> None:
        for text in UNREADABLE_PLUGINS_NODES:
            with self.subTest(text=text):
                check = self._check_for(text)
                self.assertFalse(check.observed, check.message)
                self.assertEqual(check.severity, "warning")
                self.assertIn("form OMH does not read", check.message)
                self.assertIn("was not established", check.message)
                self.assertNotIn("not in plugins.enabled", check.message)
                self.assertNotIn("will not load it", check.message)

    def test_the_report_carries_both_answers_end_to_end(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes_home)]
            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)
            config_path = hermes_home / "config.yaml"
            paths = resolve_paths(root / ".omh", hermes_home)

            config_path.write_text("plugins: {enabled: [omh]}\n", encoding="utf-8")
            check = next(c for c in run_doctor(paths) if c.name == "plugin_enabled_in_hermes")
            self.assertTrue(check.ok, check.message)
            self.assertIn("is enabled in", check.message)

            config_path.write_text("plugins: *missing\n", encoding="utf-8")
            check = next(c for c in run_doctor(paths) if c.name == "plugin_enabled_in_hermes")
            self.assertFalse(check.observed, check.message)
            self.assertIn("form OMH does not read", check.message)


class EnsurePluginEnabledMatchesTheFilesIndentTests(unittest.TestCase):
    """A new list item takes the indent the file's plugin lists already use.

    Writing `    - omh` into a file whose items sit at `  - ` puts items at
    two depths under one key, which YAML reads as two nodes, not one list.
    """

    def test_level_style_file_gets_a_level_item(self) -> None:
        text = "plugins:\n  enabled:\n  - other\n  disabled:\n  - github-prs\n"
        change = ensure_plugin_enabled(text, PLUGIN_NAME)
        self.assertEqual((change.changed, change.text), (True, "plugins:\n  enabled:\n  - omh\n  - other\n  disabled:\n  - github-prs\n"))
        self.assertTrue(plugin_is_enabled(change.text, PLUGIN_NAME))

    def test_nested_style_file_keeps_a_nested_item(self) -> None:
        change = ensure_plugin_enabled(DISABLED_CONFIG, PLUGIN_NAME)
        self.assertEqual((change.changed, change.text), (True, ENABLED_CONFIG))

    def test_empty_enabled_follows_the_sibling_list(self) -> None:
        text = "plugins:\n  enabled:\n  disabled:\n  - github-prs\n"
        change = ensure_plugin_enabled(text, PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n  - omh\n  disabled:\n  - github-prs\n")

    def test_inline_expansion_follows_the_sibling_list(self) -> None:
        text = "plugins:\n  enabled: [other]\n  disabled:\n  - github-prs\n"
        change = ensure_plugin_enabled(text, PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n  - other\n  - omh\n  disabled:\n  - github-prs\n")

    def test_a_file_without_items_defaults_to_the_hermes_style(self) -> None:
        change = ensure_plugin_enabled("plugins:\n  enabled: []\n", PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n    - omh\n")
        change = ensure_plugin_enabled("plugins:\n  entries: {}\n", PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n    - omh\n  entries: {}\n")

    def test_a_level_item_never_reads_as_already_enabled_for_another_key(self) -> None:
        text = "plugins:\n  disabled:\n  - other\n"
        change = ensure_plugin_enabled(text, PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n  - omh\n  disabled:\n  - other\n")


class DoctorPluginEnabledCheckTests(unittest.TestCase):
    """The gap this closes: everything installed, nothing reachable.

    A live check found `omh doctor` reporting `Hermes registration: ok (4/4)`
    while the plugin sat disabled in Hermes, so no OMH tool was callable in chat
    and no check said so. Bundle installed, importable, and registrable are all
    separate questions from whether Hermes will load it.
    """

    def _paths(self, root: Path, config_text: str):
        hermes = root / ".hermes"
        (hermes / "plugins" / PLUGIN_NAME).mkdir(parents=True)
        (hermes / "config.yaml").write_text(config_text, encoding="utf-8")
        return resolve_paths(root / ".omh", hermes)

    def _check(self, checks, name: str):
        return next((c for c in checks if c.name == name), None)

    def test_a_disabled_plugin_is_a_blocking_check(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp), DISABLED_CONFIG)
            check = self._check(run_doctor(paths), "plugin_enabled_in_hermes")
            self.assertIsNotNone(check)
            self.assertFalse(check.ok)
            self.assertEqual(check.severity, "blocking")
            self.assertIn("not in plugins.enabled", check.message)
            self.assertIn("no OMH tool is reachable", check.message)
            self.assertIn(f"hermes plugins enable {PLUGIN_NAME}", check.remediation)

    def test_an_enabled_plugin_passes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp), ENABLED_CONFIG)
            check = self._check(run_doctor(paths), "plugin_enabled_in_hermes")
            self.assertIsNotNone(check)
            self.assertTrue(check.ok, check.message)

    def test_an_explicitly_disabled_plugin_says_so(self) -> None:
        with TemporaryDirectory() as tmp:
            text = "plugins:\n  enabled:\n    - omh\n  disabled:\n    - omh\n"
            paths = self._paths(Path(tmp), text)
            check = self._check(run_doctor(paths), "plugin_enabled_in_hermes")
            self.assertFalse(check.ok)
            self.assertIn("listed as disabled", check.message)

    def test_a_missing_config_does_not_block(self) -> None:
        """Before setup runs there is nothing to enable, and that is not a fault."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes" / "plugins" / PLUGIN_NAME).mkdir(parents=True)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            check = self._check(run_doctor(paths), "plugin_enabled_in_hermes")
            self.assertTrue(check.ok)
            self.assertFalse(check.observed)

    def test_the_check_only_runs_when_a_bundle_is_installed(self) -> None:
        """No installed bridge means nothing to enable; doctor must not invent a fault."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".hermes").mkdir(parents=True)
            (root / ".hermes" / "config.yaml").write_text(DISABLED_CONFIG, encoding="utf-8")
            paths = resolve_paths(root / ".omh", root / ".hermes")
            self.assertIsNone(self._check(run_doctor(paths), "plugin_enabled_in_hermes"))


class SetupEnablesThePluginTests(unittest.TestCase):
    """Installing the bridge without switching it on is the same as not shipping it."""

    def test_setup_leaves_the_plugin_enabled_and_doctor_clean(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(stderr, "")
            self.assertEqual(status, 0)

            config_text = (root / ".hermes" / "config.yaml").read_text(encoding="utf-8")
            self.assertTrue(
                plugin_is_enabled(config_text, PLUGIN_NAME),
                f"setup installed the bridge without enabling it: {plugin_enablement(config_text)}",
            )

            paths = resolve_paths(root / ".omh", root / ".hermes")
            check = next((c for c in run_doctor(paths) if c.name == "plugin_enabled_in_hermes"), None)
            self.assertIsNotNone(check)
            self.assertTrue(check.ok, check.message)

    def test_setup_does_not_re_enable_a_deliberate_opt_out(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)

            config_path = root / ".hermes" / "config.yaml"
            opted_out = config_path.read_text(encoding="utf-8").replace(
                "  enabled:\n    - omh\n", "  enabled:\n  disabled:\n    - omh\n"
            )
            config_path.write_text(opted_out, encoding="utf-8")

            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)
            self.assertFalse(
                plugin_is_enabled(config_path.read_text(encoding="utf-8"), PLUGIN_NAME),
                "setup must not override an explicit opt-out",
            )


# What setup wrote for `enabled: '[]'` before #1825. YAML refuses children
# under a closed value, so Hermes fails the file ("did not find expected key").
BROKEN_CONFIG = "plugins:\n  enabled: '[]'\n    - omh\n"
# Valid YAML: the items fold into the string `browser - omh`, so Hermes
# reads no list and loads no plugin, and nothing reports it.
FOLDED_CONFIG = "plugins:\n  enabled: browser\n    - omh\n"


class ScalarEnabledValueTests(unittest.TestCase):
    """`enabled: '[]'` is a string to YAML and no plugins to Hermes (#1825)."""

    def test_reader_treats_every_scalar_as_no_plugins(self) -> None:
        for value in ("'[]'", '"[]"', "null", "~", "browser", "'[browser]'"):
            with self.subTest(value=value):
                listed = plugin_enablement(f"plugins:\n  enabled: {value}\n  disabled: []\n")
                self.assertEqual(listed, {"enabled": [], "disabled": []})

    def test_reader_keeps_members_under_node_properties(self) -> None:
        # `&plist` / `!!seq` are properties of the list below, not a scalar:
        # every `*plist` alias in the file resolves to that list.
        for value in ("&plist", "!!seq", "&plist !!seq", "&plist  # shared"):
            with self.subTest(value=value):
                text = f"plugins:\n  enabled: {value}\n    - omh\n"
                self.assertEqual(plugin_enablement(text)["enabled"], ["omh"])
                self.assertEqual(plugin_enablement_shape_error(text), "")

    def test_reader_does_not_attribute_items_under_a_scalar(self) -> None:
        self.assertFalse(plugin_is_enabled(BROKEN_CONFIG, PLUGIN_NAME))
        self.assertFalse(plugin_is_enabled(FOLDED_CONFIG, PLUGIN_NAME))
        self.assertEqual(plugin_enablement(BROKEN_CONFIG), {"enabled": [], "disabled": []})

    def test_shape_error_names_what_hermes_does_with_the_file(self) -> None:
        self.assertIn("cannot parse", plugin_enablement_shape_error(BROKEN_CONFIG))
        self.assertIn("plugins.enabled is the scalar `'[]'`", plugin_enablement_shape_error(BROKEN_CONFIG))
        self.assertIn("folds", plugin_enablement_shape_error(FOLDED_CONFIG))
        self.assertIn(
            "plugins.disabled",
            plugin_enablement_shape_error("plugins:\n  disabled: '[]'\n  - omh\n"),
        )

    def test_shape_error_is_silent_for_every_shape_hermes_reads(self) -> None:
        cases = (
            ENABLED_CONFIG,
            DISABLED_CONFIG,
            "plugins:\n  enabled: '[]'\n",
            "plugins:\n  enabled: []\n",
            "plugins:\n  enabled: null\n  disabled:\n    - browser\n",
            "plugins:\n  enabled: browser\n  entries:\n    omh:\n      allow_tool_override: false\n",
            "plugins:\n  enabled:  # none yet\n    - omh\n",
            "skills:\n  external_dirs:\n    - x\n",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(plugin_enablement_shape_error(text), "")

    def test_writer_normalizes_an_empty_scalar_to_a_block_list(self) -> None:
        for value in ("'[]'", '"[]"', "null", "~"):
            with self.subTest(value=value):
                change = ensure_plugin_enabled(f"plugins:\n  enabled: {value}\n  disabled: []\n", PLUGIN_NAME)
                self.assertTrue(change.changed)
                self.assertEqual(change.message, "normalized empty plugins.enabled to a block list")
                self.assertEqual(change.text, "plugins:\n  enabled:\n    - omh\n  disabled: []\n")
                self.assertTrue(plugin_is_enabled(change.text, PLUGIN_NAME))
                self.assertEqual(plugin_enablement_shape_error(change.text), "")

    def test_writer_follows_the_sibling_indent_when_normalizing(self) -> None:
        change = ensure_plugin_enabled("plugins:\n  enabled: '[]'\n  disabled:\n  - browser\n", PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled:\n  - omh\n  disabled:\n  - browser\n")

    def test_a_trailing_comment_does_not_hide_an_inline_list(self) -> None:
        # YAML reads `[omh] # keep` as the list; the comment rides the key line
        # through the rewrite instead of turning the value into a refusal.
        self.assertEqual(plugin_enablement("plugins:\n  enabled: [omh] # keep\n")["enabled"], ["omh"])
        self.assertEqual(plugin_enablement_shape_error("plugins:\n  enabled: [omh] # keep\n"), "")
        change = ensure_plugin_enabled("plugins:\n  enabled: [] # none yet\n", PLUGIN_NAME)
        self.assertEqual(change.text, "plugins:\n  enabled: # none yet\n    - omh\n")
        self.assertTrue(plugin_is_enabled(change.text, PLUGIN_NAME))
        removed = remove_plugin_enabled("plugins:\n  enabled: [omh, browser] # c\n", PLUGIN_NAME)
        self.assertEqual(removed.text, "plugins:\n  enabled: [browser] # c\n")
        # A quoted item that contains ` #` is not a comment.
        self.assertEqual(plugin_enablement("plugins:\n  enabled: ['a #b', omh]\n")["enabled"], ["a #b", "omh"])

    def test_a_level_item_under_a_plain_scalar_is_a_parse_error(self) -> None:
        # `  - omh` at the key's own indent ends the scalar; YAML refuses it
        # (measured), unlike a deeper item, which folds into the string.
        self.assertIn("cannot parse", plugin_enablement_shape_error("plugins:\n  enabled: browser\n  - omh\n"))
        self.assertIn("folds", plugin_enablement_shape_error(FOLDED_CONFIG))

    def test_duplicate_enabled_keys_are_refused(self) -> None:
        # YAML keeps the last key and the writer would edit the first.
        text = "plugins:\n  enabled:\n    - browser\n  enabled: '[]'\n"
        self.assertIn("duplicate plugins.enabled keys", plugins_enabled_extension_error(text, PLUGIN_NAME))
        with self.assertRaises(ValueError) as caught:
            ensure_plugin_enabled(text, PLUGIN_NAME)
        self.assertEqual(str(caught.exception), plugins_enabled_extension_error(text, PLUGIN_NAME))

    def test_writer_refuses_any_other_scalar_and_names_the_hermes_writer(self) -> None:
        for value in ("browser", "'[browser]'", "'[]' # quoted keeps its comment", "'omh'"):
            text = f"plugins:\n  enabled: {value}\n"
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    ensure_plugin_enabled(text, PLUGIN_NAME)
                self.assertIn("unsupported plugins.enabled shape", str(caught.exception))
                self.assertIn(f"hermes plugins enable {PLUGIN_NAME}", str(caught.exception))

    def test_writer_refuses_a_file_hermes_cannot_read_as_a_list(self) -> None:
        for text in (BROKEN_CONFIG, FOLDED_CONFIG):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    ensure_plugin_enabled(text, PLUGIN_NAME)
                self.assertEqual(str(caught.exception), plugin_enablement_shape_error(text))

    def test_extension_error_is_the_sentence_the_writer_raises(self) -> None:
        # One home for the verdict: doctor reports what setup refused.
        for text in (BROKEN_CONFIG, FOLDED_CONFIG, "plugins:\n  enabled: browser\n", "plugins:\n  enabled: '[browser]'\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as caught:
                    ensure_plugin_enabled(text, PLUGIN_NAME)
                self.assertEqual(plugins_enabled_extension_error(text, PLUGIN_NAME), str(caught.exception))
        for text in (ENABLED_CONFIG, "plugins:\n  enabled: '[]'\n", "plugins:\n  enabled: []\n", "skills:\n  external_dirs: []\n", ""):
            with self.subTest(text=text):
                self.assertEqual(plugins_enabled_extension_error(text, PLUGIN_NAME), "")


class SetupWithScalarEnabledTests(unittest.TestCase):
    """The #1825 reproduction, end to end through `omh setup` and `omh doctor`."""

    def test_setup_normalizes_a_quoted_empty_list_and_doctor_stays_clean(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            hermes_home.mkdir()
            config_path = hermes_home / "config.yaml"
            config_path.write_text("plugins:\n  enabled: '[]'\n", encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes_home)]

            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)

            config_text = config_path.read_text(encoding="utf-8")
            self.assertNotIn("'[]'", config_text)
            self.assertIn("  enabled:\n    - omh\n", config_text)
            self.assertEqual(plugin_enablement_shape_error(config_text), "")
            self.assertTrue(plugin_is_enabled(config_text, PLUGIN_NAME), config_text)

            paths = resolve_paths(root / ".omh", hermes_home)
            by_name = {c.name: c for c in run_doctor(paths)}
            self.assertTrue(by_name["plugin_enabled_in_hermes"].ok, by_name["plugin_enabled_in_hermes"].message)
            self.assertTrue(by_name["hermes_config_plugins_enabled"].ok, by_name["hermes_config_plugins_enabled"].message)

    def test_setup_fails_closed_on_a_scalar_it_cannot_extend(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            hermes_home.mkdir()
            config_path = hermes_home / "config.yaml"
            before = "plugins:\n  enabled: browser\n"
            config_path.write_text(before, encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes_home)]

            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertNotEqual(status, 0)
            self.assertIn("unsupported plugins.enabled shape", stderr)
            self.assertEqual(config_path.read_text(encoding="utf-8"), before)

            # Setup stopped before it installed the bundle, so the plugin
            # checks do not run; doctor still has to name the cause.
            paths = resolve_paths(root / ".omh", hermes_home)
            by_name = {c.name: c for c in run_doctor(paths)}
            self.assertNotIn("plugin_enabled_in_hermes", by_name)
            check = by_name["hermes_config_plugins_enabled"]
            self.assertFalse(check.ok)
            self.assertIn("unsupported plugins.enabled shape ('browser')", check.message)
            self.assertIn("YAML block list", check.next_action)

    def test_doctor_reports_the_file_setup_used_to_write(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hermes_home = root / ".hermes"
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes_home)]
            status, _stdout, stderr = run_cli(base + ["setup"])
            self.assertEqual(status, 0, stderr)

            config_path = hermes_home / "config.yaml"
            config_path.write_text(BROKEN_CONFIG, encoding="utf-8")

            paths = resolve_paths(root / ".omh", hermes_home)
            check = next((c for c in run_doctor(paths) if c.name == "plugin_enabled_in_hermes"), None)
            self.assertIsNotNone(check)
            self.assertFalse(check.ok)
            self.assertIn("cannot parse", check.message)
            self.assertIn("YAML block list", check.next_action or "")


# Hermes' own config separates the children of `plugins:` with banners at
# column 0. A comment carries no structure, so `enabled:` below the banner is
# still a child of `plugins:` (#2304).
BANNER_CONFIG = """attachments:
  storage: "hermes-home"

# =============================================================================
# Plugin Installation
# =============================================================================
plugins:
  # Deadline for each Git clone, fetch or checkout during plugin install. Default: 300
  clone_timeout_seconds: 300

# =============================================================================
# Model Configuration
# =============================================================================
  enabled:
    - rea
    - superpowers
  disabled: []
"""


def _plugins_enabled_keys(text: str) -> int:
    """How many `enabled:` keys sit directly under the top-level `plugins:` node."""
    count = 0
    in_plugins = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            in_plugins = stripped.partition(":")[0] == "plugins"
            continue
        if in_plugins and line.startswith("  ") and not line.startswith("   "):
            count += stripped.partition(":")[0] == "enabled"
    return count


class ColumnZeroCommentInsidePluginsTests(unittest.TestCase):
    """A column-0 comment inside `plugins:` does not end the node (#2304)."""

    def test_the_reader_sees_the_list_below_the_banner(self) -> None:
        self.assertEqual(plugin_enablement(BANNER_CONFIG), {"enabled": ["rea", "superpowers"], "disabled": []})
        self.assertEqual(plugins_enabled_extension_error(BANNER_CONFIG, PLUGIN_NAME), "")

    def test_setup_extends_the_one_enabled_list_instead_of_writing_a_second(self) -> None:
        change = ensure_plugin_enabled(BANNER_CONFIG, PLUGIN_NAME)

        self.assertTrue(change.changed)
        self.assertEqual(change.message, "added plugin to plugins.enabled")
        self.assertEqual(_plugins_enabled_keys(change.text), 1)
        # The writer puts a new item directly under the key, as it always has.
        self.assertEqual(plugin_enablement(change.text)["enabled"], [PLUGIN_NAME, "rea", "superpowers"])
        self.assertEqual(plugins_enabled_extension_error(change.text, PLUGIN_NAME), "")

    def test_uninstall_takes_the_item_back_out_below_the_banner(self) -> None:
        added = ensure_plugin_enabled(BANNER_CONFIG, PLUGIN_NAME)
        removed = remove_plugin_enabled(added.text, PLUGIN_NAME)

        self.assertTrue(removed.changed)
        self.assertEqual(removed.text, BANNER_CONFIG)

    def test_a_banner_before_a_sibling_top_level_key_still_ends_the_node(self) -> None:
        text = (
            "plugins:\n"
            "  clone_timeout_seconds: 300\n"
            "\n"
            "# =====\n"
            "# Tools\n"
            "# =====\n"
            "toolsets:\n"
            "  enabled:\n"
            "    - web\n"
        )
        self.assertEqual(plugin_enablement(text), {"enabled": [], "disabled": []})

        change = ensure_plugin_enabled(text, PLUGIN_NAME)

        self.assertEqual(change.message, "inserted plugins.enabled")
        self.assertEqual(_plugins_enabled_keys(change.text), 1)
        self.assertEqual(plugin_enablement(change.text)["enabled"], [PLUGIN_NAME])
        self.assertTrue(change.text.endswith("# Tools\n# =====\ntoolsets:\n  enabled:\n    - web\n"))

    def test_the_writer_refuses_a_composed_file_that_would_not_read_back(self) -> None:
        from omh.install import config_adapter

        original = config_adapter._compose_plugin_enable

        def _writes_a_second_key(text: str, name: str):
            change = original(text, name)
            return config_adapter.ConfigChange(True, change.message, "plugins:\n  enabled:\n    - rea\n  enabled:\n    - omh\n")

        with mock.patch.object(config_adapter, "_compose_plugin_enable", _writes_a_second_key):
            with self.assertRaises(ValueError) as caught:
                ensure_plugin_enabled("plugins:\n  enabled:\n    - rea\n", PLUGIN_NAME)
        self.assertIn("file is left alone", str(caught.exception))
        self.assertIn(f"hermes plugins enable {PLUGIN_NAME}", str(caught.exception))

        def _drops_a_name(text: str, name: str):
            return config_adapter.ConfigChange(True, "dropped", f"plugins:\n  enabled:\n    - {name}\n")

        with mock.patch.object(config_adapter, "_compose_plugin_enable", _drops_a_name):
            with self.assertRaises(ValueError) as caught:
                ensure_plugin_enabled("plugins:\n  enabled:\n    - rea\n", PLUGIN_NAME)
        self.assertIn("would not read back", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
