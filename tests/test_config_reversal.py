from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.install.compression_defaults import (  # noqa: E402
    compression_fallback_chain_lines,
    ensure_compression_defaults,
    remove_compression_fallback_chain,
)
from omh.config_adapter import (  # noqa: E402
    section_edit_guard,
    activate_display_sections,
    activate_omh_skin,
    activate_tui_interface,
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
from omh.install.config_reversal import (  # noqa: E402
    MANAGED_CONFIG_WRITES_SCHEMA,
    config_names_key,
    load_managed_config_writes,
    managed_config_reading,
    managed_config_writes,
    reverse_managed_config,
)

CONFIG_PATH = "/tmp/does-not-exist/config.yaml"


def _apply_setup_writes(config_text: str, skills_dir: str = "/tmp/omh/skills") -> str:
    """The same chain of writers `_apply_result` runs, in the same order."""
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
        ("multi-document", "---\nmemory:\n  provider: omh\nplugins:\n  enabled:\n    - omh\n"),
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


if __name__ == "__main__":
    unittest.main()
