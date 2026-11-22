from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.install.compression_defaults import (  # noqa: E402
    compression_fallback_chain_lines,
    ensure_compression_defaults,
    remove_compression_fallback_chain,
)
from _legacy_display import activate_display_sections, activate_omh_skin, activate_tui_interface  # noqa: E402
from omh.config_adapter import (  # noqa: E402
    section_edit_guard,
    config_container_paths,
    ensure_external_dir,
    ensure_plugin_enabled,
    remove_childless_containers,
    revert_display_scalar,
    remove_display_sections,
    remove_external_dir,
    memory_provider_selection,
    remove_memory_provider,
    remove_plugin_enabled,
    set_memory_provider,
)
from omh.config_adapter import read_config, write_config  # noqa: E402
from omh.install.config_adapter import childless_containers  # noqa: E402
from omh.install.config_reversal import (  # noqa: E402
    DISPLAY_KEYS,
    MANAGED_CONFIG_WRITES_SCHEMA,
    MANAGED_CONTAINERS,
    config_names_key,
    drop_emptied_containers,
    load_managed_config_writes,
    managed_config_reading,
    managed_config_writes,
    release_managed_display,
    reverse_managed_config,
)

CONFIG_PATH = "/tmp/does-not-exist/config.yaml"


def _apply_setup_writes(config_text: str, skills_dir: str = "/tmp/omh/skills") -> str:
    """The chain of writers `_apply_result` ran before the display release, in the same order."""
    text = ensure_external_dir(config_text, skills_dir).text
    text = ensure_compression_defaults(text).text
    text = ensure_plugin_enabled(text, "omh").text
    text = activate_tui_interface(text).text
    text = activate_omh_skin(text, "omh").text
    text = activate_display_sections(text).text
    text = set_memory_provider(text, "omh").text
    return text


def _record(before: str, after: str, previous: object = None) -> dict[str, object]:
    """The stored per-config map after one apply pass on CONFIG_PATH."""
    return managed_config_writes(
        before,
        after,
        config_path=CONFIG_PATH,
        previous=previous,
        now="2026-09-19T00:00:00Z",
    )


def _entry(stored: dict[str, object]) -> dict[str, object]:
    """CONFIG_PATH's own record out of that map."""
    return load_managed_config_writes(stored, config_path=CONFIG_PATH)


class InverseWriterTests(unittest.TestCase):
    def test_remove_plugin_enabled_takes_only_the_named_item(self) -> None:
        fixtures = (
            ("plugins:\n  enabled:\n    - omh\n    - other\n", "plugins:\n  enabled:\n    - other\n"),
            ("plugins:\n  enabled:\n  - omh\n  - other\n", "plugins:\n  enabled:\n  - other\n"),
            ("plugins:\n  enabled: [omh, other]\n", "plugins:\n  enabled: [other]\n"),
            ("plugins:\n  enabled: [omh]\n", "plugins:\n  enabled: []\n"),
            (
                "plugins:\n  enabled:\n    - omh\n  disabled:\n    - other\n",
                "plugins:\n  enabled:\n  disabled:\n    - other\n",
            ),
        )
        for original, expected in fixtures:
            with self.subTest(original=original):
                change = remove_plugin_enabled(original, "omh")
                self.assertTrue(change.changed)
                self.assertEqual(change.text, expected)

    def test_remove_plugin_enabled_never_touches_the_disabled_opt_out(self) -> None:
        original = "plugins:\n  disabled:\n    - omh\n"

        change = remove_plugin_enabled(original, "omh")

        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)
        self.assertIn("not in plugins.enabled", change.message)

    def test_revert_display_scalar_refuses_a_value_that_is_no_longer_ours(self) -> None:
        original = "display:\n  interface: cli\n"

        change = revert_display_scalar(original, "interface", "tui")

        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)
        self.assertIn("display.interface is cli, not tui", change.message)

    def test_revert_display_scalar_refuses_every_shape_the_writer_refuses(self) -> None:
        fixtures = (
            "display: {interface: tui}\n",
            "display.interface: tui\n",
            "display:\n  interface: tui\ndisplay:\n  compact: true\n",
            "display:\n  interface: tui\n  interface: tui\n",
            "display:\n  interface:\n    mode: tui\n",
            "﻿display:\n  interface: tui\n",
            "- display\n",
        )
        for original in fixtures:
            with self.subTest(original=original):
                change = revert_display_scalar(original, "interface", "tui")
                self.assertFalse(change.changed)
                self.assertEqual(change.text, original)

    def test_revert_display_scalar_puts_back_the_value_consent_replaced(self) -> None:
        change = revert_display_scalar("display:\n  interface: tui\n", "interface", "tui", "cli")

        self.assertTrue(change.changed)
        self.assertEqual(change.text, "display:\n  interface: cli\n")

    def test_remove_display_sections_keeps_a_child_the_person_changed(self) -> None:
        original = (
            "display:\n"
            "  sections:\n"
            "    thinking: collapsed\n"
            "    tools: expanded\n"
            "    subagents: collapsed\n"
        )

        change = remove_display_sections(original, ["thinking", "tools", "subagents"], "collapsed")

        self.assertTrue(change.changed)
        self.assertEqual(change.text, "display:\n  sections:\n    tools: expanded\n")

    def test_remove_memory_provider_drops_the_line_rather_than_emptying_it(self) -> None:
        change = remove_memory_provider("memory:\n  provider: omh\n  limit: 5\n", "omh")

        self.assertTrue(change.changed)
        self.assertEqual(change.text, "memory:\n  limit: 5\n")

    def test_remove_memory_provider_leaves_another_products_slot_alone(self) -> None:
        original = "memory:\n  provider: honcho\n"

        change = remove_memory_provider(original, "omh")

        self.assertFalse(change.changed)
        self.assertEqual(change.text, original)
        self.assertIn("memory.provider is honcho, not omh", change.message)

    def test_remove_compression_fallback_chain_requires_a_verbatim_match(self) -> None:
        original = (
            "auxiliary:\n"
            "  compression:\n"
            "    provider: og\n"
            "    fallback_chain:\n"
            "      - provider: zai\n"
        )
        written = compression_fallback_chain_lines(original)

        self.assertEqual(written, ["    fallback_chain:", "      - provider: zai"])
        self.assertTrue(remove_compression_fallback_chain(original, written).changed)

        edited = original.replace("zai", "kimi")
        kept = remove_compression_fallback_chain(edited, written)
        self.assertFalse(kept.changed)
        self.assertEqual(kept.text, edited)
        self.assertIn("no longer matches", kept.message)

    def test_container_paths_list_only_keys_that_carry_children(self) -> None:
        text = "version: 1\ndisplay:\n  skin: omh\n  sections:\n    tools: collapsed\nskills:\n  external_dirs: []\n"

        self.assertEqual(
            config_container_paths(text),
            {"display", "display.sections", "skills"},
        )

    def test_remove_childless_containers_goes_deepest_first_and_eats_the_separator(self) -> None:
        text = "version: 1\n\nskills:\n  external_dirs:\n"

        change = remove_childless_containers(text, ["skills", "skills.external_dirs"])

        self.assertTrue(change.changed)
        self.assertEqual(change.text, "version: 1\n")

    def test_remove_childless_containers_keeps_a_container_with_children_left(self) -> None:
        text = "display:\n  compact: true\n"

        change = remove_childless_containers(text, ["display"])

        self.assertFalse(change.changed)
        self.assertEqual(change.text, text)


ISSUE_2244_CONFIG = "providers:\n  z.ai-coding-plan:\n    api_key_env: ZAI_CODING_PLAN_API_KEY\n"


class DottedKeyContainerTests(unittest.TestCase):
    """A key holding a dot is one key, never a level of nesting (#2244)."""

    def test_a_dotted_second_level_key_has_no_container_path(self) -> None:
        self.assertEqual(config_container_paths(ISSUE_2244_CONFIG), {"providers"})

    def test_childless_containers_reads_the_issue_config_without_raising(self) -> None:
        self.assertEqual(childless_containers(ISSUE_2244_CONFIG), set())

    def test_nothing_under_a_dotted_top_level_key_has_a_path(self) -> None:
        text = "z.ai:\n  inner:\n    k: v\n  empty:\n"

        self.assertEqual(config_container_paths(text), set())
        self.assertEqual(childless_containers(text), set())

    def test_a_dotted_key_that_is_itself_childless_is_neither_named_nor_removed(self) -> None:
        text = "providers:\n  z.ai-coding-plan:\nz.ai:\n"

        self.assertEqual(config_container_paths(text), {"providers"})
        self.assertEqual(childless_containers(text), set())
        # A record on disk is not checked against the producer, so its
        # joined spelling can still be asked for; no line answers to it.
        for path in ("providers.z.ai-coding-plan", "z.ai"):
            change = remove_childless_containers(text, [path])
            self.assertFalse(change.changed, path)
            self.assertEqual(change.text, text)

    def test_the_reversal_cleanup_leaves_the_issue_config_byte_identical(self) -> None:
        change = remove_childless_containers(ISSUE_2244_CONFIG, list(MANAGED_CONTAINERS))

        self.assertFalse(change.changed)
        self.assertEqual(change.text, ISSUE_2244_CONFIG)

    def test_a_dotted_top_level_key_no_longer_hides_the_container_setup_creates(self) -> None:
        before = "skills.external_dirs:\n  - /x\n"
        after = ensure_external_dir(before, "/tmp/omh/skills").text

        self.assertIn("skills:\n  external_dirs:\n", after)
        self.assertEqual(config_container_paths(before), set())
        self.assertEqual(
            config_container_paths(after) - config_container_paths(before),
            {"skills", "skills.external_dirs"},
        )
        created = _entry(_record(before, after))["containers_created"]
        self.assertEqual(created, ["skills", "skills.external_dirs"])

        unregistered = remove_external_dir(after, "/tmp/omh/skills").text
        cleanup = drop_emptied_containers(
            unregistered, childless_containers(after), recorded=created, record_is_complete=True
        )

        self.assertEqual(cleanup.text, before)

    def test_plain_two_part_paths_read_and_remove_as_before(self) -> None:
        text = "version: 1\nskills:\n  external_dirs:\nplugins:\n  entries:\n    omh: {}\ndisplay:\n"

        self.assertEqual(
            config_container_paths(text),
            {"skills", "skills.external_dirs", "plugins", "plugins.entries", "display"},
        )
        self.assertEqual(childless_containers(text), {"skills.external_dirs", "display"})
        change = remove_childless_containers(text, ["skills", "skills.external_dirs", "plugins.entries", "display"])
        self.assertTrue(change.changed)
        self.assertEqual(change.text, "version: 1\nplugins:\n  entries:\n    omh: {}\n")


class DottedKeySetupTests(unittest.TestCase):
    """`omh setup` against the issue's config, through the CLI (#2244)."""

    def _homes(self, root: Path) -> tuple[list[str], Path]:
        hermes = root / ".hermes"
        hermes.mkdir()
        config = hermes / "config.yaml"
        config.write_text(ISSUE_2244_CONFIG, encoding="utf-8", newline="\n")
        return ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes)], config

    def test_setup_dry_run_connects_and_leaves_the_config_alone(self) -> None:
        with TemporaryDirectory() as tmp:
            base, config = self._homes(Path(tmp))

            status, stdout, stderr = run_cli(base + ["setup", "--core", "--yes", "--dry-run"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertNotIn("too many values to unpack", stderr)
            self.assertIn("OMH setup preview complete.", stdout)
            self.assertEqual(config.read_text(encoding="utf-8"), ISSUE_2244_CONFIG)

    def test_setup_applies_its_writes_and_keeps_the_dotted_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            base, config = self._homes(Path(tmp))

            status, stdout, stderr = run_cli(base + ["setup", "--core", "--yes", "--json"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertTrue(json.loads(stdout)["ok"])
            text = config.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(ISSUE_2244_CONFIG), text)
            self.assertIn("skills:\n  external_dirs:\n", text)
            self.assertIn("memory:\n  provider: omh\n", text)


class NewlineHandlingTests(unittest.TestCase):
    def test_a_crlf_config_never_reaches_the_line_editors_carrying_carriage_returns(self) -> None:
        """CR is a control character to the text guards, so it must not get in.

        `read_config` opens in universal-newline mode and `write_config`
        opens with `newline=""`, on every platform, so the whole adapter
        works in LF space and a Windows config is normalised on read rather
        than splicing CR into a removed or restored line. The consequence
        worth knowing is that any OMH write converts a CRLF config to LF;
        that predates the reversal and this pins it rather than claiming it
        is untested.
        """
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_bytes(b"display:\r\n  interface: tui\r\n  skin: omh\r\n")

            text = read_config(path)
            self.assertNotIn("\r", text)

            change, _rows = reverse_managed_config(text, {}, config_path=str(path))
            self.assertNotIn("\r", change.text)
            write_config(path, change.text)

            self.assertEqual(path.read_bytes(), b"display:\n  interface: tui\n")


class GuardParityTests(unittest.TestCase):
    """Every remover refuses the shapes its forward writer refuses.

    The display removers took `_display_edit_guard` from the start; the
    memory, plugins and compression removers took none of it, and two of the
    shapes on that list are not merely untouched by an unguarded remover,
    they are damaged by it. Both cases below were reproduced before the
    guard was shared.
    """

    SHAPES = (
        ("BOM", "\ufeffmemory:\n  provider: omh\nplugins:\n  enabled:\n    - omh\n"),
        # One opening `---` is a single document Hermes reads, and the guard
        # takes it (#3075); a second one is the stream it refuses.
        ("multi-document", "---\nmemory:\n  provider: omh\nplugins:\n  enabled:\n    - omh\n---\nx: 1\n"),
        ("root sequence", "- memory\n"),
        ("quoted mapping key", 'memory:\n  provider: omh\n"plugins":\n  enabled:\n    - omh\n'),
        ("anchor", "memory: &m\n  provider: omh\nplugins:\n  enabled: &p\n    - omh\n"),
        ("alias", "memory:\n  provider: omh\nplugins:\n  enabled: *elsewhere\n"),
        ("explicit key", "? memory\n: provider\n"),
    )

    def test_the_shared_guard_refuses_every_listed_shape_for_every_section(self) -> None:
        for label, text in self.SHAPES:
            for section, key in (("display", "skin"), ("memory", "provider"), ("plugins", "enabled")):
                with self.subTest(shape=label, section=section):
                    self.assertNotEqual(section_edit_guard(text.splitlines(), section, key), "")

    def test_a_dotted_memory_provider_beside_a_block_does_not_delete_the_persons_value(self) -> None:
        """Reproduced damage: the owner check read the dotted `omh`, the
        mutator then deleted `provider: honcho`, and OMH's own marker was
        the thing left behind."""
        before = "memory.provider: omh\nmemory:\n  provider: honcho\n"

        self.assertFalse(remove_memory_provider(before, "omh").changed)
        change, rows = reverse_managed_config(before, {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(change.text, before)
        self.assertEqual(by_key["memory.provider"].status, "kept")
        self.assertIn("dotted memory.provider is user-owned", by_key["memory.provider"].detail)

    def test_an_anchored_plugins_list_is_not_emptied_under_its_own_anchor(self) -> None:
        """Reproduced damage: `&plist` was left anchoring null, so every
        `*plist` alias in the file resolved to null."""
        before = "plugins:\n  enabled: &plist\n    - omh\nother:\n  also: *plist\ndisplay:\n  skin: omh\n"

        self.assertFalse(remove_plugin_enabled(before, "omh").changed)
        change, rows = reverse_managed_config(before, {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(change.text, before)
        self.assertEqual(by_key["plugins.enabled"].status, "kept")
        self.assertIn("YAML node properties", by_key["plugins.enabled"].detail)
        # The display path already refused; both must now agree.
        self.assertEqual(by_key["display.skin"].status, "kept")

    def test_a_quoted_inline_plugins_list_is_left_to_the_person(self) -> None:
        """`_parse_inline_list` splits on commas before it strips quotes, so
        `["a,b", omh]` parses as three entries and re-renders as two."""
        for before in ('plugins:\n  enabled: ["a,b", omh]\n', 'plugins:\n  enabled: ["other", "omh"]\n'):
            with self.subTest(before=before):
                change, rows = reverse_managed_config(before, {}, config_path=CONFIG_PATH)
                by_key = {row.key: row for row in rows}
                self.assertEqual(change.text, before)
                self.assertEqual(by_key["plugins.enabled"].status, "kept")

    def test_a_flow_mapping_plugins_node_is_reported_kept_and_not_absent(self) -> None:
        """#1814: the reader walked past `plugins: {enabled: [omh]}`, so the
        uninstall report said OMH's own entry was absent from a file that
        names it, with the refusal beside it saying the node was left alone.
        The remover still declines the shape; the row now agrees with it."""
        before = "plugins: {enabled: [omh, other]}\n"

        change, rows = reverse_managed_config(before, {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(change.text, before)
        self.assertEqual(by_key["plugins.enabled"].status, "kept")
        self.assertIn("noncanonical plugins configuration", by_key["plugins.enabled"].detail)

    def test_a_plugins_node_that_was_not_read_is_never_reported_absent(self) -> None:
        """An unread node cannot support "nothing is left here". Every entry
        here is valid YAML Hermes loads `omh` from, measured with the PyYAML
        in Hermes' own venv, so `absent` would be a false statement about a
        file the person still has to clean up by hand."""
        for before in (
            "base: &plugins\n  enabled: [omh]\nplugins: *plugins\n",
            "plugins: &p\n  enabled:\n    - omh\n",
        ):
            with self.subTest(before=before):
                change, rows = reverse_managed_config(before, {}, config_path=CONFIG_PATH)
                by_key = {row.key: row for row in rows}

                self.assertEqual(change.text, before)
                self.assertEqual(by_key["plugins.enabled"].status, "kept")

    def test_a_document_with_no_plugins_key_is_still_reported_absent(self) -> None:
        # The negative control for the two above: "unread" must not become a
        # blanket "kept" that hides a file with nothing left in it.
        change, rows = reverse_managed_config("display:\n  skin: omh\n", {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["plugins.enabled"].status, "absent")

    def test_an_unquoted_inline_list_still_reverses(self) -> None:
        change = remove_plugin_enabled("plugins:\n  enabled: [other, omh]\n", "omh")

        self.assertTrue(change.changed)
        self.assertEqual(change.text, "plugins:\n  enabled: [other]\n")

    def test_the_compression_remover_refuses_a_document_it_must_not_edit(self) -> None:
        # The anchor, not a BOM: a BOM already defeats the chain READER, so
        # it would pass with or without the guard and prove nothing. Here
        # the chain is perfectly readable and matches verbatim, and the only
        # thing standing between the remover and a document carrying YAML
        # node properties is the shared guard.
        chain = ["    fallback_chain:", "      - provider: zai"]
        before = (
            "providers: &shared\n  og: 1\nauxiliary:\n  compression:\n    provider: og\n"
            + "\n".join(chain)
            + "\n"
        )
        self.assertEqual(compression_fallback_chain_lines(before), chain)

        change = remove_compression_fallback_chain(before, chain)

        self.assertFalse(change.changed)
        self.assertEqual(change.text, before)
        self.assertIn("YAML node properties", change.message)


class RowStatusTests(unittest.TestCase):
    """A row's status is read off the config, never off the message text."""

    def test_a_key_present_in_a_shape_we_refuse_is_kept_not_absent(self) -> None:
        change, rows = reverse_managed_config("memory.provider: omh\n", {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(change.text, "memory.provider: omh\n")
        self.assertEqual(by_key["memory.provider"].status, "kept")

    def test_a_key_whose_own_refusal_message_reads_like_absence_is_still_kept(self) -> None:
        """The case that separates reading the config from reading the message.

        OMH wrote `display.sections.tools`; the person has since deleted that
        line and kept `thinking`. The remover has nothing to take out and
        says so -- "no display.sections child to remove" -- which is one of
        the six English fragments the old classifier searched for, so it
        answered `absent` about a key the config still carries. Reading the
        config answers `kept`.

        The two cases that used to stand for this could not: the dotted
        `memory.provider` fixture now refuses at the guard with a message
        containing none of the six fragments, so both classifiers agree on
        it, and the presence test calls `config_names_key` directly, which
        the old classifier left intact and merely stopped calling.
        """
        record = {
            CONFIG_PATH: {
                "schema_version": MANAGED_CONFIG_WRITES_SCHEMA,
                "config_path": CONFIG_PATH,
                "keys": {"display.sections": ["tools"]},
                "restores": {},
                "containers_created": [],
            }
        }
        config = "display:\n  sections:\n    thinking: collapsed\n"

        change, rows = reverse_managed_config(config, record, config_path=CONFIG_PATH)
        row = {item.key: item for item in rows}["display.sections"]

        self.assertEqual(change.text, config)
        self.assertEqual(row.status, "kept")
        self.assertIn("no display.sections child to remove", row.detail)

    def test_presence_is_looser_than_the_writers_readers(self) -> None:
        # The writers' readers return "" for a shape they refuse to edit,
        # which is the right answer for "may I write" and the wrong one for
        # "is anything left".
        self.assertEqual(memory_provider_selection("memory.provider: omh\n"), "omh")
        for text, key, expected in (
            ("memory.provider: omh\n", "memory.provider", True),
            ("version: 1\n", "memory.provider", False),
            ("display:\n  skin: omh\n", "display.skin", True),
            ("display: {skin: omh}\n", "display.skin", True),
            # Hermes' YAML loader skips a leading BOM, so a key on the line
            # after it is still there.
            ("\ufeffdisplay:\n  skin: omh\n", "display.skin", True),
            ("\ufeffmemory:\n  provider: omh\n", "memory.provider", True),
            ("version: 1\n", "display.skin", False),
            ("plugins:\n  enabled:\n    - omh\n", "plugins.enabled", True),
            ("plugins:\n  enabled:\n    - other\n", "plugins.enabled", False),
        ):
            with self.subTest(text=text, key=key):
                self.assertEqual(config_names_key(text, key), expected)

    def test_a_clean_config_reports_every_key_absent_and_prints_nothing(self) -> None:
        _change, rows = reverse_managed_config("version: 1\n", {}, config_path=CONFIG_PATH)

        self.assertEqual({row.status for row in rows}, {"absent"})


class ManagedConfigWritesTests(unittest.TestCase):
    def test_record_names_only_the_keys_this_pass_added(self) -> None:
        before = "display:\n  interface: cli\n  sections:\n    tools: expanded\n"
        after = _apply_setup_writes(before)

        record = _entry(_record(before, after))

        self.assertEqual(record["schema_version"], MANAGED_CONFIG_WRITES_SCHEMA)
        keys = record["keys"]
        assert isinstance(keys, dict)
        # `activate_*` carries consent, so it may migrate a stock `cli`.
        self.assertEqual(keys["display.interface"], "tui")
        self.assertEqual(keys["display.skin"], "omh")
        self.assertEqual(keys["memory.provider"], "omh")
        self.assertEqual(keys["plugins.enabled"], ["omh"])
        # `tools` was the person's and stays out of the record.
        self.assertEqual(keys["display.sections"], ["subagents", "thinking"])
        self.assertNotIn("auxiliary.compression.fallback_chain", keys)
        # `display:` was the person's; only keys inside it are OMH's.
        self.assertNotIn("display", record["containers_created"])

    def test_record_carries_an_earlier_run_forward_when_a_later_one_writes_nothing(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        first = _record(before, after)

        # `omh update` re-runs the same pass; every writer now reports
        # "already set" and changes nothing.
        second = _record(after, _apply_setup_writes(after), previous=first)

        self.assertEqual(_entry(second)["keys"], _entry(first)["keys"])
        self.assertEqual(_entry(second)["containers_created"], _entry(first)["containers_created"])

    def test_record_keeps_the_value_consent_replaced(self) -> None:
        before = "display:\n  interface: cli\n  skin: ares\n"
        after = _apply_setup_writes(before)
        first = _record(before, after)

        self.assertEqual(_entry(first)["restores"], {"display.interface": "cli", "display.skin": "ares"})

        # A later pass that replaces nothing reads OMH's own values back;
        # the record must not adopt them as the thing to restore.
        second = _record(after, _apply_setup_writes(after), previous=first)
        self.assertEqual(_entry(second)["restores"], _entry(first)["restores"])

    def test_record_follows_a_choice_the_person_made_after_the_first_install(self) -> None:
        first = _record("display:\n  interface: cli\n", _apply_setup_writes("display:\n  interface: cli\n"))
        # The person picks `classic`, then re-consents; `classic` is the
        # choice uninstall owes them back, not the `cli` they left behind.
        chosen = _apply_setup_writes("display:\n  interface: cli\n").replace(
            "  interface: tui", "  interface: classic"
        )
        second = _record(chosen, _apply_setup_writes(chosen), previous=first)

        self.assertEqual(_entry(second)["restores"]["display.interface"], "classic")  # type: ignore[index]

    def test_record_from_another_profile_is_not_this_configs_record(self) -> None:
        stored = _record("", _apply_setup_writes(""))

        mine = load_managed_config_writes(stored, config_path=CONFIG_PATH)
        self.assertEqual(mine["config_path"], CONFIG_PATH)
        self.assertEqual(load_managed_config_writes(stored, config_path="/other/config.yaml"), {})
        self.assertEqual(load_managed_config_writes({"schema_version": "other/v1"}, config_path=CONFIG_PATH), {})
        self.assertEqual(load_managed_config_writes("not a record", config_path=CONFIG_PATH), {})
        # An entry filed under a key that is not its own `config_path` is a
        # hand-edited map, and must not answer for either path.
        forged = {"/other/config.yaml": dict(mine)}
        self.assertEqual(load_managed_config_writes(forged, config_path="/other/config.yaml"), {})

    def test_one_setup_run_keeps_a_record_per_hermes_home_in_one_store(self) -> None:
        """Bot profiles share the primary's OMH home, so one slot is not enough."""
        primary_after = _apply_setup_writes("")
        stored = _record("", primary_after)
        profile_path = "/tmp/does-not-exist/profiles/bot/config.yaml"
        stored = managed_config_writes(
            "",
            _apply_setup_writes("", skills_dir="/tmp/omh/skills"),
            config_path=profile_path,
            previous=stored,
            now="2026-09-19T00:00:00Z",
        )

        self.assertEqual(sorted(stored), sorted([CONFIG_PATH, profile_path]))
        self.assertEqual(
            load_managed_config_writes(stored, config_path=CONFIG_PATH)["config_path"], CONFIG_PATH
        )
        self.assertEqual(
            load_managed_config_writes(stored, config_path=profile_path)["config_path"], profile_path
        )


class ReverseManagedConfigTests(unittest.TestCase):
    def test_uninstall_restores_the_bytes_that_were_there_before_setup(self) -> None:
        before = (
            "version: 1\n"
            "model:\n"
            "  fallback_providers:\n"
            "    - provider: zai\n"
            "      model: glm-5.3\n"
            "auxiliary:\n"
            "  compression:\n"
            "    provider: og\n"
        )
        after = _apply_setup_writes(before)
        self.assertNotEqual(after, before)
        record = _record(before, after)
        # The compression chain is derived from the person's own providers,
        # so this fixture proves the recorded-lines path, not a constant.
        self.assertIn("auxiliary.compression.fallback_chain", _entry(record)["keys"])  # type: ignore[operator]

        unregistered = remove_external_dir(after, "/tmp/omh/skills").text
        change, rows = reverse_managed_config(unregistered, record, config_path=CONFIG_PATH)

        self.assertTrue(change.changed)
        self.assertEqual(change.text, before)
        self.assertEqual(
            {row.key for row in rows if row.status == "reversed"},
            {
                "display.interface",
                "display.sections",
                "display.skin",
                "memory.provider",
                "plugins.enabled",
                "auxiliary.compression.fallback_chain",
            },
        )

    def test_a_key_the_person_changed_is_kept_and_named(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        moved = after.replace("  provider: omh", "  provider: honcho").replace(
            "  interface: tui", "  interface: cli"
        )

        change, rows = reverse_managed_config(moved, record, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["memory.provider"].status, "kept")
        self.assertIn("honcho", by_key["memory.provider"].detail)
        self.assertEqual(by_key["display.interface"].status, "kept")
        self.assertIn("display.interface is cli, not tui", by_key["display.interface"].detail)
        self.assertIn("provider: honcho", change.text)
        self.assertIn("interface: cli", change.text)

    def test_the_guard_is_the_recorded_value_not_the_keys_presence(self) -> None:
        """Mutation proof: dropping the compare reverses a value that is not ours."""
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        moved = after.replace("  skin: omh", "  skin: ares")

        change, rows = reverse_managed_config(moved, record, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["display.skin"].status, "kept")
        self.assertIn("  skin: ares", change.text)

    def test_an_install_with_no_record_reverses_only_what_names_omh(self) -> None:
        after = _apply_setup_writes("")

        change, rows = reverse_managed_config(after, {}, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["display.skin"].status, "reversed")
        self.assertEqual(by_key["memory.provider"].status, "reversed")
        self.assertEqual(by_key["plugins.enabled"].status, "reversed")
        # `tui` and `collapsed` are values a person can legitimately hold.
        self.assertEqual(by_key["display.interface"].status, "unrecorded")
        self.assertEqual(by_key["display.sections"].status, "unrecorded")
        self.assertIn("  interface: tui", change.text)
        self.assertIn("    thinking: collapsed", change.text)
        self.assertNotIn("skin: omh", change.text)
        self.assertNotIn("provider: omh", change.text)

    def test_a_theme_chosen_after_the_record_was_taken_is_still_reversed(self) -> None:
        """`omh theme use` rewrote `display.skin` without touching the record.

        Mutation proof: without the by-construction rule on the recorded
        branch, the recorded `omh` does not match `omh-amber` and uninstall
        keeps a skin name whose file it is about to delete.
        """
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        themed = after.replace("  skin: omh\n", "  skin: omh-amber\n")

        change, rows = reverse_managed_config(themed, record, config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["display.skin"].status, "reversed")
        self.assertNotIn("skin:", change.text)

    def test_an_omh_theme_is_reversed_without_a_record_but_a_foreign_skin_is_not(self) -> None:
        for skin, status in (("omh-crimson", "reversed"), ("ares", "kept")):
            with self.subTest(skin=skin):
                text = f"display:\n  skin: {skin}\n"
                _change, rows = reverse_managed_config(text, {}, config_path=CONFIG_PATH)
                by_key = {row.key: row for row in rows}
                self.assertEqual(by_key["display.skin"].status, status)

    def test_uninstall_restores_a_display_value_consent_migrated_away_from(self) -> None:
        before = "display:\n  interface: cli\n  skin: ares\n"
        after = _apply_setup_writes(before)
        record = _record(before, after)

        change, rows = reverse_managed_config(
            remove_external_dir(after, "/tmp/omh/skills").text, record, config_path=CONFIG_PATH
        )
        by_key = {row.key: row for row in rows}

        self.assertEqual(change.text, before)
        self.assertIn("restored display.interface to cli", by_key["display.interface"].detail)
        self.assertIn("restored display.skin to ares", by_key["display.skin"].detail)

    def test_a_container_the_person_already_kept_empty_is_left_exactly_as_it_was(self) -> None:
        # `memory:` with nothing under it is the person's, and no reversal
        # touched it; `display:` is emptied by this pass and goes.
        text = "memory:\ndisplay:\n  skin: omh\n"

        change, _rows = reverse_managed_config(text, {}, config_path=CONFIG_PATH)

        self.assertEqual(change.text, "memory:\n")

    def test_an_install_with_no_record_leaves_behind_no_container_omh_created(self) -> None:
        """#1767. Uninstall unregisters first, so the baseline is the pre-removal text."""
        before = "version: 1\n"
        after = _apply_setup_writes(before)
        unregistered = remove_external_dir(after, "/tmp/omh/skills").text
        self.assertIn("  external_dirs:\n", unregistered)

        change, _rows = reverse_managed_config(
            unregistered, {}, config_path=CONFIG_PATH, text_before_removals=after
        )

        # `display:` stays with the person: `interface: tui` and three
        # collapsed sections are values a person can hold, and a pre-record
        # install has nothing that says OMH wrote them. Everything OMH names
        # by construction goes, and takes its containers with it.
        self.assertEqual(
            change.text,
            "version: 1\n"
            "\n"
            "display:\n"
            "  sections:\n"
            "    thinking: collapsed\n"
            "    tools: collapsed\n"
            "    subagents: collapsed\n"
            "  interface: tui\n",
        )

    def test_a_container_the_person_had_before_setup_survives_a_recorded_uninstall(self) -> None:
        """The record says OMH did not create `skills:`; the guess must not outvote it.

        The axis the older empty-container case does not cover: empty BEFORE
        setup, filled by OMH, empty again after the reversal. `empty_before`
        cannot see it -- at uninstall time the container has children -- so
        only `containers_created` knows, and a candidate set that unions the
        guess on top of the record deletes the person's key.
        """
        # The last two are containers `main` already lost before this change:
        # `memory:` at the top level and the nested `display.sections:`.
        for section in ("skills", "display", "plugins", "memory", "display:\n  sections"):
            with self.subTest(section=section):
                before = f"version: 1\n{section}:\n"
                after = _apply_setup_writes(before)
                record = _record(before, after)
                created = _entry(record)["containers_created"]
                self.assertNotIn(section.replace(":\n  ", "."), created)  # type: ignore[operator]
                unregistered = remove_external_dir(after, "/tmp/omh/skills").text

                change, _rows = reverse_managed_config(
                    unregistered, record, config_path=CONFIG_PATH, text_before_removals=after
                )

                self.assertEqual(change.text, before)

    def test_the_baseline_is_the_text_before_the_callers_own_removals(self) -> None:
        """Mutation proof for #1767, and the contract of the default.

        Read on the post-removal text, `skills.external_dirs` is already
        childless and reads as a container the person kept empty, so it
        survives. That is the right answer for a caller that removed nothing
        first -- which is what the default means -- and the wrong one for
        uninstall, which strips the registration before it gets here.
        """
        after = _apply_setup_writes("version: 1\n")
        unregistered = remove_external_dir(after, "/tmp/omh/skills").text

        default_baseline, _rows = reverse_managed_config(unregistered, {}, config_path=CONFIG_PATH)

        self.assertIn("  external_dirs:\n", default_baseline.text)

    def test_a_container_goes_with_the_last_child_this_pass_removed(self) -> None:
        """`plugins:` is childless only once `plugins.enabled:` is gone."""
        change, _rows = reverse_managed_config(
            "version: 1\nplugins:\n  enabled:\n    - omh\n", {}, config_path=CONFIG_PATH
        )

        self.assertEqual(change.text, "version: 1\n")

    def test_an_absent_key_reports_absent_rather_than_left_in_place(self) -> None:
        _change, rows = reverse_managed_config("version: 1\n", {}, config_path=CONFIG_PATH)

        self.assertEqual({row.status for row in rows}, {"absent"})

    def test_reading_and_reversal_agree_on_what_is_managed(self) -> None:
        after = _apply_setup_writes("")
        reading = managed_config_reading(after)

        self.assertEqual(reading["display.interface"], "tui")
        self.assertEqual(reading["display.skin"], "omh")
        self.assertEqual(reading["memory.provider"], "omh")
        self.assertEqual(reading["plugins.enabled"], ["omh"])
        self.assertEqual(reading["skills.external_dirs"], ["/tmp/omh/skills"])

    def test_uninstall_after_the_release_leaves_a_skin_the_person_chose_since(self) -> None:
        """Once released, an `omh*` skin is the person's, and uninstall says so."""
        before = ""
        after = _apply_setup_writes(before)
        first = _record(before, after)
        released = _released_record(after, first)
        chosen = release_managed_display(after, first, config_path=CONFIG_PATH)[0].text
        chosen = chosen + "display:\n  skin: omh-crimson\n"

        change, rows = reverse_managed_config(chosen, _released_record(chosen, released), config_path=CONFIG_PATH)
        by_key = {row.key: row for row in rows}

        self.assertEqual(by_key["display.skin"].status, "kept")
        self.assertIn("  skin: omh-crimson\n", change.text)
        self.assertEqual(by_key["display.interface"].status, "absent")
        self.assertEqual(by_key["memory.provider"].status, "reversed")


def _released_record(text: str, stored: dict[str, object]) -> dict[str, object]:
    """The map after one setup/update pass that ran the display release on `text`."""
    released = release_managed_display(text, stored, config_path=CONFIG_PATH)[0].text
    return managed_config_writes(
        text,
        released,
        config_path=CONFIG_PATH,
        previous=stored,
        now="2026-10-14T00:00:00Z",
        released=DISPLAY_KEYS,
        display_released=True,
    )


class ReleaseManagedDisplayTests(unittest.TestCase):
    """Setup and update take OMH's display keys back so bare `hermes` is stock Hermes."""

    def _release(self, text: str, stored: object) -> tuple[str, dict[str, object]]:
        change, rows = release_managed_display(text, stored, config_path=CONFIG_PATH)
        return change.text, {row.key: row for row in rows}

    def test_a_shape_the_editor_does_not_understand_is_never_edited(self) -> None:
        # The guards the consented writers used to apply now stand in front of
        # the release, which is what still edits `display`. Each of these
        # names an OMH skin, which the record-less rule takes back in the
        # canonical shape, so a change here is a guard that let a shape
        # through. The positive control shows the rule does fire.
        canonical = "display:\n  skin: omh\n"
        self.assertNotEqual(self._release(canonical, None)[0], canonical)
        for original in (
            '"display":\n  skin: omh\n',
            "'display':\n  skin: omh\n",
            'display:\n  "skin": omh\n',
            "display:\n  'skin': omh\n",
            '{"display": {"skin": "omh"}}\n',
            "display: {skin: omh, compact: true}\n",
            '? "display"\n:\n  skin: omh\n',
            '"displ\\u0061y":\n  skin: omh\n',
            'display:\n  "sk\\u0069n": omh\n',
            "!!str display:\n  skin: omh\n",
            "display:\n  &key skin: omh\n",
            "display:\n  !!str skin: omh\n",
            "display:\n  ? !!str skin\n  : omh\n",
            "display:\n  *skin_key : omh\n",
            "display:\n  skin: &current omh\ncopy: *current\n",
            "current: &current omh\ndisplay:\n  skin: *current\n",
            'display:\n  - "skin": omh\n',
            "display:\n  - skin: omh\n",
            '- "display":\n    skin: omh\n',
            "model: local\n---\ndisplay:\n  skin: omh\n",
            "\ufeffdisplay:\n  skin: omh\n",
            "display:\n  skin: # theme\n    name: omh\n",
            "display.skin: omh\n",
            "display:\n  skin: omh\ndisplay:\n  compact: true\n",
            "display:\n  skin: omh\n  skin: omh-amber\n",
            "display:\n    skin: omh\n",
            "display :\n  skin: omh\n",
        ):
            with self.subTest(original=original):
                self.assertEqual(self._release(original, None)[0], original)

    def test_a_sections_shape_the_editor_does_not_understand_is_never_edited(self) -> None:
        # Same rule one level down, with a record that says OMH wrote all
        # three sections, so only the guard stands between them and removal.
        written = activate_display_sections("version: 1\n").text
        stored = _record("version: 1\n", written)
        self.assertNotIn("sections", self._release(written, stored)[0])
        for original in (
            "display:\n  sections: {}\n",
            "display:\n  sections: {thinking: collapsed, tools: collapsed, subagents: collapsed}\n",
            "display:\n  sections: |\n    text\n",
            "display.sections:\n  tools: collapsed\n",
            "display:\n  sections:\n    tools:\n      mode: collapsed\n",
            "display:\n  sections:\n    tools: collapsed\n  sections:\n    thinking: collapsed\n",
            '"display":\n  sections:\n    tools: collapsed\n',
            "display:\n  &key sections:\n    tools: collapsed\n",
            "display:\n  - sections:\n      tools: collapsed\n",
            "model: local\n---\ndisplay:\n  sections:\n    tools: collapsed\n",
        ):
            with self.subTest(original=original):
                self.assertEqual(self._release("version: 1\n" + original, stored)[0], "version: 1\n" + original)

    def test_recorded_display_keys_go_and_the_bytes_before_setup_come_back(self) -> None:
        before = "version: 1\n"
        after = _apply_setup_writes(before)
        record = _record(before, after)

        released, by_key = self._release(after, record)

        self.assertEqual({key for key, row in by_key.items() if row.status == "reversed"}, set(DISPLAY_KEYS))
        self.assertNotIn("display:", released)
        # Only the display half: OMH's plugin, memory provider and
        # registration stay, which is what keeps OMH working inside Hermes.
        self.assertIn("    - omh\n", released)
        self.assertIn("  provider: omh\n", released)
        self.assertIn("/tmp/omh/skills", released)

    def test_a_value_consent_replaced_is_put_back(self) -> None:
        before = "display:\n  interface: cli\n  skin: ares\n"
        after = _apply_setup_writes(before)

        released, by_key = self._release(after, _record(before, after))

        self.assertIn("display:\n  interface: cli\n  skin: ares\n", released)
        self.assertIn("restored display.skin to ares", by_key["display.skin"].detail)

    def test_a_value_the_person_changed_after_omh_wrote_it_stays(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        moved = (
            after.replace("  interface: tui\n", "  interface: cli\n")
            .replace("  skin: omh\n", "  skin: ares\n")
            .replace("    tools: collapsed\n", "    tools: expanded\n")
        )

        released, by_key = self._release(moved, _record(before, after))

        self.assertEqual(by_key["display.interface"].status, "kept")
        self.assertEqual(by_key["display.skin"].status, "kept")
        self.assertEqual(by_key["display.sections"].kept, "tools")
        self.assertIn("  interface: cli\n", released)
        self.assertIn("  skin: ares\n", released)
        self.assertIn("    tools: expanded\n", released)
        self.assertNotIn("collapsed", released)

    def test_an_omh_skin_with_no_record_goes_and_the_persons_own_keys_stay(self) -> None:
        text = "display:\n  interface: tui\n  skin: omh-crimson\n  compact: true\n"

        released, by_key = self._release(text, {})

        self.assertEqual(released, "display:\n  interface: tui\n  compact: true\n")
        self.assertEqual(by_key["display.skin"].status, "reversed")
        # `tui` is a value a person can choose; nothing says OMH wrote it.
        self.assertEqual(by_key["display.interface"].status, "unrecorded")

    def test_a_skin_omh_theme_use_wrote_over_the_recorded_one_goes(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        themed = after.replace("  skin: omh\n", "  skin: omh-amber\n")

        released, by_key = self._release(themed, _record(before, after))

        self.assertEqual(by_key["display.skin"].status, "reversed")
        self.assertNotIn("skin:", released)

    def test_a_persons_own_display_choices_are_never_touched(self) -> None:
        for text in (
            "display:\n  skin: ares\n",
            "display:\n  interface: cli\n",
            "display:\n  skin: amber\n",
            "display:\n  sections:\n    tools: collapsed\n",
            "display: {skin: omh}\n",
        ):
            with self.subTest(text=text):
                released, _by_key = self._release(text, {})
                self.assertEqual(released, text)

    def test_a_key_the_editor_refuses_is_refused_not_kept(self) -> None:
        """Mutation proof: read as `kept`, a refusal let setup record the release with OMH's keys on disk."""
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        for extra in ('aliases:\n  "fast/model": glm-5.3\n', "defaults: &defaults\n  retries: 1\n"):
            with self.subTest(extra=extra):
                shaped = after + extra

                released, by_key = self._release(shaped, record)

                self.assertEqual(released, shaped)
                self.assertEqual({key: row.status for key, row in by_key.items()}, dict.fromkeys(DISPLAY_KEYS, "refused"))
                self.assertIn("user-owned", by_key["display.skin"].detail)

    def test_a_tag_or_anchor_on_the_value_is_refused_not_read_as_the_persons(self) -> None:
        """Mutation proof: the reader returns "!!str omh-crimson" verbatim, which is no OMH skin name."""
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        for prefix in ("!!str ", "&s "):
            with self.subTest(prefix=prefix):
                shaped = after.replace("  skin: omh\n", f"  skin: {prefix}omh-crimson\n").replace(
                    "  interface: tui\n", f"  interface: {prefix}tui\n"
                )

                released, by_key = self._release(shaped, record)

                self.assertEqual(released, shaped)
                self.assertEqual(by_key["display.skin"].status, "refused")
                self.assertEqual(by_key["display.interface"].status, "refused")

    def test_a_key_set_twice_never_reads_as_the_persons(self) -> None:
        """Mutation proof: the reader takes the first value, Hermes' YAML loader the last."""
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        for name, shaped in (
            ("second skin in the block", after.replace("  skin: omh\n", "  skin: ares\n  skin: omh\n")),
            ("dotted key before the block", "display.skin: ares\n" + after),
            ("second display before the block", "display:\n  skin: ares\n" + after),
        ):
            with self.subTest(shape=name):
                _released, by_key = self._release(shaped, record)

                self.assertEqual(by_key["display.skin"].status, "refused")

    def test_a_key_set_once_in_a_refused_shape_still_reads_as_the_persons(self) -> None:
        # A dotted key alone is one value: Hermes reads it as a key of its
        # own and resolves its default skin, so nothing of OMH's is left.
        before = ""
        after = _apply_setup_writes(before)
        shaped = after.replace("  skin: omh\n", "") + "display.skin: ares\n"

        _released, by_key = self._release(shaped, _record(before, after))

        self.assertEqual(by_key["display.skin"].status, "kept")

    def test_a_value_after_a_bom_is_read_past_it(self) -> None:
        """Mutation proof: read through the BOM-blind reader, the person's value came back empty, so possibly OMH's."""
        before = ""
        after = _apply_setup_writes(before)
        record = _record(before, after)
        start = after.index("display:")
        for value, expected in (("ares", "kept"), ("omh-crimson", "refused")):
            with self.subTest(value=value):
                block = "display:\n  skin: " + value + "\n"
                shaped = "\ufeff" + block + after[:start]

                released, by_key = self._release(shaped, record)

                self.assertEqual(released, shaped)
                self.assertEqual(by_key["display.skin"].status, expected)
        # Past the BOM, a key set twice is seen as twice, and without a record
        # an OMH name among the values is seen.
        twice = "\ufeffdisplay:\n  skin: ares\n  skin: omh-crimson\n" + after[:start]
        for stored in (record, {}):
            with self.subTest(recorded=bool(stored)):
                _released, by_key = self._release(twice, stored)

                self.assertEqual(by_key["display.skin"].status, "refused")
        _released, by_key = self._release("\ufeffdisplay:\n  skin: omh-crimson\n" + after[:start], {})
        self.assertEqual(by_key["display.skin"].status, "refused")

    def test_an_omh_skin_set_anywhere_in_a_duplicate_is_refused_without_a_record(self) -> None:
        """Mutation proof: read first-wins, `ares` before `omh-crimson` was the person's while Hermes resolves omh-crimson."""
        for text in (
            "display:\n  skin: ares\n  skin: omh-crimson\n",
            "display:\n  skin: omh-crimson\n  skin: ares\n",
            "display.skin: ares\ndisplay:\n  skin: omh-crimson\n",
        ):
            with self.subTest(text=text):
                released, by_key = self._release("version: 1\n" + text, {})

                self.assertEqual(released, "version: 1\n" + text)
                self.assertEqual(by_key["display.skin"].status, "refused")
        # No OMH name among the values: still the person's.
        _released, by_key = self._release("version: 1\ndisplay:\n  skin: ares\n  skin: mytheme\n", {})
        self.assertEqual(by_key["display.skin"].status, "kept")

    def test_an_unreadable_value_no_record_names_is_kept(self) -> None:
        """Mutation proof: refusing it held the release open on a fresh install's own flow `display`."""
        for text in (
            "display: {skin: mytheme}\n",
            "display: {skin: omh-crimson}\n",
            "display:\n  skin: !!str omh-crimson\n",
        ):
            with self.subTest(text=text):
                released, by_key = self._release("version: 1\n" + text, {})

                self.assertEqual(released, "version: 1\n" + text)
                self.assertEqual(by_key["display.skin"].status, "kept")
        # An OMH skin name OMH can read is still OMH's without a record.
        _released, by_key = self._release("version: 1\ndisplay.skin: omh-crimson\n", {})
        self.assertEqual(by_key["display.skin"].status, "refused")

    def test_a_value_that_reads_as_the_persons_stays_kept_under_a_refused_shape(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        moved = after.replace("  interface: tui\n", "  interface: cli\n").replace("  skin: omh\n", "  skin: ares\n")

        _released, by_key = self._release(moved + 'aliases:\n  "fast/model": glm-5.3\n', _record(before, after))

        self.assertEqual(by_key["display.interface"].status, "kept")
        self.assertEqual(by_key["display.skin"].status, "kept")
        # The sections reader honours the editor's guards, so nothing reads
        # them as anybody's under this shape.
        self.assertEqual(by_key["display.sections"].status, "refused")

    def test_a_display_section_the_person_had_survives_a_recorded_release(self) -> None:
        before = "version: 1\ndisplay:\n"
        after = _apply_setup_writes(before)

        released, _by_key = self._release(after, _record(before, after))

        self.assertIn("version: 1\ndisplay:\n", released)
        self.assertNotIn("  interface:", released)

    def test_the_release_runs_once_per_config(self) -> None:
        """Mutation proof: without the marker, update takes back a skin the person picked later."""
        before = ""
        after = _apply_setup_writes(before)
        stored = _released_record(after, _record(before, after))
        later = "display:\n  skin: omh-crimson\n"

        released, by_key = self._release(later, stored)

        self.assertEqual(released, later)
        self.assertEqual(by_key, {})

    def test_the_record_after_a_release_names_no_display_key_or_restore(self) -> None:
        """Mutation proof: `released` must filter `restores` too.

        Putting `ares` back reads, to the before/after comparison, like OMH
        replacing its own `omh` with `ares`, so an unfiltered record would
        keep `omh` as the value to restore and name `ares` as OMH's write.
        """
        before = "display:\n  interface: cli\n  skin: ares\n"
        after = _apply_setup_writes(before)

        entry = _entry(_released_record(after, _record(before, after)))

        self.assertEqual(entry["restores"], {})
        self.assertFalse(set(DISPLAY_KEYS) & set(entry["keys"]))  # type: ignore[arg-type]
        self.assertEqual(entry["display_released_at"], "2026-10-14T00:00:00Z")
        self.assertIn("memory.provider", entry["keys"])  # type: ignore[operator]

    def test_the_record_keeps_the_first_release_time_and_drops_display_containers(self) -> None:
        before = ""
        after = _apply_setup_writes(before)
        first = _record(before, after)
        self.assertIn("display", _entry(first)["containers_created"])  # type: ignore[operator]
        released = _released_record(after, first)

        again = managed_config_writes(
            after, after, config_path=CONFIG_PATH, previous=released, now="2026-12-01T00:00:00Z",
            released=DISPLAY_KEYS, display_released=True,
        )

        self.assertEqual(_entry(again)["display_released_at"], "2026-10-14T00:00:00Z")
        self.assertNotIn("display", _entry(again)["containers_created"])  # type: ignore[operator]
        self.assertNotIn("display.sections", _entry(again)["containers_created"])  # type: ignore[operator]


if __name__ == "__main__":
    unittest.main()
