"""Setup edits a Hermes config whose root keys hold column-0 lists, or that opens with `%YAML 1.1` (#3075).

Reported by @chhxbchhxb: `omh setup --core` stopped at step 2 with "non-mapping or unsupported root YAML is
user-owned" on a `config.yaml` whose root key held a list at column 0. Older Hermes releases, hand edits and other
YAML tools write that spelling; current `hermes_yaml` indents lists (`indent(sequence=4, offset=2)`):

    toolsets:
    - hermes-cli

`config_adapter._root_is_plain_block_mapping` took every column-0 `-` line for a sequence document, so neither
`skills.external_dirs` nor `plugins.enabled` could be registered. It now reads the shapes
`route_endpoint_guard.scan_config` reads since #2917: a block sequence at column 0 under a root key with no value
of its own, and one opening `---`, optionally after one `%YAML 1.1` directive. A document that opens with a
sequence, a second document, `%TAG`, `%YAML 1.2` and the column-0 lists the loaders refuse stay refused.

Letting those files through reached two writers that inserted a mapping key above a list under their own section
(`plugins:` or `memory:` then `- x`) and wrote a file Hermes cannot load. Both now refuse a list there, the way
`section_edit_guard` refuses it for every other section.

Two more faults of the same writers, fixed with it:

- A section key with a comment on its line (`memory: # mine`) was no section to `set_memory_provider`, which
  appended a second `memory:` Hermes refuses as a duplicate key; the plugin writer refused `plugins: # x`
  outright. Every writer and guard now finds a section through one test, `_block_header`, and edits it in place.
- The skills writer edited inside a `%YAML 1.2`, `%TAG` or `...` envelope while the plugin and memory writers
  appended past the `...`. Every writer and remover now edits the body `_document_parts` splits off and puts the
  envelope back (`_with_document_body`), so a registered install with any envelope updates without a write.

`HermesAgreesTest` loads each accepted shape and every written file with Hermes' own reader; it is skipped where
Hermes is not installed, and `PINNED` holds a few of its answers so the readers are checked against them anyway.
"""

from __future__ import annotations

import difflib
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.install import config_adapter as adapter  # noqa: E402
from omh.install.compression_defaults import ensure_compression_defaults  # noqa: E402
from test_route_guard_yaml_directive import HERMES_PYTHON, HERMES_ROOT, hermes_reads  # noqa: E402

DIRECTIVE = "%YAML 1.1\n---\n"
TOOLSETS = "toolsets:\n- hermes-cli\n- web\n"
PROVIDERS = "fallback_providers:\n- model: example\n  provider: custom\n"
MODEL = "model:\n  provider: custom\n"
SKILLS = "skills:\n  external_dirs: []\n"
PLUGINS = "plugins:\n  enabled: []\n"

# The issue's minimal config, column-0 and indented.
ISSUE_COLUMN0 = MODEL + "toolsets:\n- hermes-cli\n" + SKILLS + PLUGINS
ISSUE_INDENTED = MODEL + "toolsets:\n  - hermes-cli\n" + SKILLS + PLUGINS

# Each is one block mapping: the guard takes it and Hermes' loader reads it to a mapping.
READABLE = {
    "indented list": ISSUE_INDENTED,
    "column-0 list": ISSUE_COLUMN0,
    "column-0 list of mappings": MODEL + PROVIDERS + SKILLS,
    "column-0 list before skills": TOOLSETS + SKILLS + PLUGINS,
    "column-0 list after skills": SKILLS + TOOLSETS + PLUGINS,
    "column-0 list after plugins": SKILLS + PLUGINS + TOOLSETS,
    "two column-0 lists": TOOLSETS + PROVIDERS + SKILLS,
    "nested lists at their key's indent": "approvals:\n  patterns:\n  - rm -rf\n  - sudo\n" + TOOLSETS + SKILLS,
    "column-0 item with a nested list": "fallback_providers:\n- model: x\n  args:\n  - a\n- model: y\n" + SKILLS,
    "comments between items": "toolsets: # Hermes writes these\n- hermes-cli\n# kept\n- web\n" + SKILLS,
    "bare dash item": "toolsets:\n-\n- web\n" + SKILLS,
    "document start": "---\n" + TOOLSETS + SKILLS,
    "directive": DIRECTIVE + MODEL + SKILLS + PLUGINS,
    "directive with comments": "%YAML 1.1   # the version\n--- # doc\n" + MODEL + SKILLS,
    "directive after a comment line": "# my config\n" + DIRECTIVE + MODEL + SKILLS,
    "directive and column-0 list": DIRECTIVE + ISSUE_COLUMN0,
}

# Each must stay refused; the comment names why.
REFUSED = {
    "sequence document": "- item\n",
    "sequence after document start": "---\n- item\n",
    "item before the first key": "- item\n" + MODEL,  # the loaders raise
    "item after a key with a value": "foo: bar\n- x\n" + SKILLS,  # the loaders raise
    "item after indented lines": "foo:\n  a: 1\n- x\n" + SKILLS,  # the loaders raise
    "item after an indented list": "foo:\n  - a\n- b\n" + SKILLS,  # the loaders raise
    "second document": DIRECTIVE + MODEL + "---\nx: 1\n",
    "second document start": MODEL + "---\nx: 1\n",
    "document end": MODEL + "...\n",
    "TAG directive": "%TAG ! tag:example.com,2000:\n---\n" + MODEL,
    "YAML 1.2 directive": "%YAML 1.2\n---\n" + MODEL,
    "two directives": "%YAML 1.1\n%YAML 1.1\n---\n" + MODEL,  # the loaders raise
    "directive without document start": "%YAML 1.1\n" + MODEL,  # the loaders raise
    "directive alone": "%YAML 1.1\n",
    "directive after a key": MODEL + "%YAML 1.1\n---\n",
    "flow sequence root": "[a, b]\n",
    "indented root under document start": "---\n  model: x\n",
    "indented root": "  model: x\n",  # a section appended at column 0 beside it does not load
    # Hermes reads `memory: # c` as part of the string, never as a key.
    "quoted value across lines": 'note: "first line\nmemory: # c\n  still"\n' + MODEL,
}
# The guard refuses these whole; every writer edits their body instead (`_with_document_body`).
EDITED_THROUGH_ENVELOPE = {"document end", "TAG directive", "YAML 1.2 directive"}

# What Hermes' `hermes_yaml.safe_load` returned for a few shapes, so the readers are checked without Hermes too.
PINNED = {
    "column-0 list": {"model": {"provider": "custom"}, "toolsets": ["hermes-cli"],
                      "skills": {"external_dirs": []}, "plugins": {"enabled": []}},
    # YAML 1.1 reads a plain `y` as true.
    "column-0 item with a nested list": {"fallback_providers": [{"model": "x", "args": ["a"]}, {"model": True}],
                                         "skills": {"external_dirs": []}},
    "directive and column-0 list": {"model": {"provider": "custom"}, "toolsets": ["hermes-cli"],
                                    "skills": {"external_dirs": []}, "plugins": {"enabled": []}},
}

SECTIONS = ("skills", "plugins", "memory", "display", "auxiliary")

# Every section key with a comment on its line: one section each, edited in place.
COMMENTED_HEADERS = (
    "model:\n  provider: custom\n"
    "skills: # where my skills live\n  external_dirs: []\n"
    "plugins:  # third-party\n  enabled: []\n"
    "memory: # mine\n  recall: true\n"
)


def hermes_load(text: str) -> object:
    """What Hermes' own `hermes_yaml.safe_load` reads from `text`, as JSON data."""
    script = (
        "import json, sys; sys.path.insert(0, sys.argv[1]); import hermes_yaml as h\n"
        "print(json.dumps(h.safe_load(sys.stdin.read())))\n"
    )
    done = subprocess.run([str(HERMES_PYTHON), "-I", "-c", script, str(HERMES_ROOT)], input=text, text=True,
                          capture_output=True, timeout=60, check=True)
    return json.loads(done.stdout)


def setup_writes(text: str, skill_dir: str = "/o/skills") -> str:
    """The two registrations setup's step 2 makes, through the real writers."""
    text = adapter.ensure_external_dir(text, skill_dir).text
    return adapter.ensure_plugin_enabled(text, "omh").text


class GuardTest(unittest.TestCase):
    def test_a_block_mapping_reads_with_its_lists_at_either_indent(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                lines = text.splitlines()
                self.assertTrue(adapter._root_is_plain_block_mapping(lines), name)
                for section in SECTIONS:
                    self.assertEqual(adapter.section_edit_guard(lines, section), "", section)

    def test_the_issue_probe_passes_both_spellings(self) -> None:
        for text in (ISSUE_INDENTED, ISSUE_COLUMN0):
            with self.subTest(text=text):
                adapter._validate_external_dirs_mutation_shape(text)

    def test_the_shapes_that_stay_refused(self) -> None:
        for name, text in REFUSED.items():
            with self.subTest(shape=name):
                lines = text.splitlines()
                self.assertFalse(adapter._root_is_plain_block_mapping(lines), name)
                self.assertNotEqual(adapter.section_edit_guard(lines, "plugins", "enabled"), "", name)
                if name in EDITED_THROUGH_ENVELOPE:
                    continue
                with self.assertRaises(ValueError):
                    adapter.ensure_external_dir(text, "/o/skills")
                with self.assertRaises(ValueError):
                    adapter.ensure_plugin_enabled(text, "omh")
                memory = adapter.set_memory_provider(text, "omh")
                self.assertFalse(memory.changed, memory.text)

    def test_a_header_is_the_key_alone_or_with_a_comment(self) -> None:
        for line in ("memory:", "memory:  ", "memory: # mine", "memory:\t# mine"):
            self.assertTrue(adapter._block_header(line, "memory"), line)
        for line in ("memory:#x", "memory: x", "memory: {}", " memory:", "memory_x:", "memory"):
            self.assertFalse(adapter._block_header(line, "memory"), line)

    def test_the_readers_agree_with_what_hermes_loaded(self) -> None:
        for name, loaded in PINNED.items():
            with self.subTest(shape=name):
                text = READABLE[name]
                self.assertEqual(adapter.external_dirs(text), loaded["skills"]["external_dirs"])
                self.assertEqual(adapter.plugin_enablement(text)["enabled"], loaded.get("plugins", {}).get("enabled", []))

    def test_a_list_under_the_edited_section_stays_refused(self) -> None:
        for indent in ("", "  "):
            for section in SECTIONS:
                text = f"{MODEL}{section}:\n{indent}- x\n"
                with self.subTest(section=section, indent=indent):
                    self.assertTrue(adapter._root_is_plain_block_mapping(text.splitlines()))
                    self.assertIn(f"sequence {section} configuration", adapter.section_edit_guard(text.splitlines(), section))
            with self.subTest(writer="skills", indent=indent):
                with self.assertRaisesRegex(ValueError, "sequence skills configuration"):
                    adapter.ensure_external_dir(f"{MODEL}skills:\n{indent}- x\n", "/o/skills")
            with self.subTest(writer="plugins", indent=indent):
                text = f"{MODEL}plugins:\n{indent}- x\n"
                with self.assertRaisesRegex(ValueError, "sequence plugins configuration"):
                    adapter.ensure_plugin_enabled(text, "omh")
                self.assertIn("sequence plugins configuration", adapter.plugins_enabled_extension_error(text, "omh"))
            with self.subTest(writer="memory", indent=indent):
                text = f"{MODEL}memory:\n{indent}- x\n"
                change = adapter.set_memory_provider(text, "omh")
                self.assertFalse(change.changed)
                self.assertEqual(change.text, text)
                self.assertIn("sequence memory configuration", change.message)


class WriterTest(unittest.TestCase):
    """The section writers place their lines around column-0 lists and change nothing else."""

    MANAGED_BEFORE = {"  external_dirs: []", "  enabled: []"}
    MANAGED_AFTER = {"skills:", "  external_dirs:", "    - /o/skills", "plugins:", "  enabled:", "    - omh"}

    def assert_only_managed_lines_changed(self, before: str, after: str) -> None:
        old, new = before.splitlines(), after.splitlines()
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            self.assertLessEqual(set(old[i1:i2]), self.MANAGED_BEFORE, after)
            self.assertLessEqual(set(new[j1:j2]), self.MANAGED_AFTER | {""}, after)

    def test_setup_registers_skills_and_plugin_beside_every_readable_shape(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                after = setup_writes(text)
                self.assert_only_managed_lines_changed(text, after)
                self.assertEqual(adapter.external_dirs(after), ["/o/skills"])
                self.assertEqual(adapter.plugin_enablement(after)["enabled"], ["omh"])
                self.assertTrue(adapter._root_is_plain_block_mapping(after.splitlines()), after)
                # A second pass finds both and writes nothing.
                self.assertEqual(setup_writes(after), after)

    def test_the_column_0_lists_survive_byte_for_byte(self) -> None:
        after = setup_writes(DIRECTIVE + TOOLSETS + SKILLS + PROVIDERS + PLUGINS)
        self.assertEqual(
            after,
            DIRECTIVE + TOOLSETS + "skills:\n  external_dirs:\n    - /o/skills\n" + PROVIDERS
            + "plugins:\n  enabled:\n    - omh\n",
        )

    def test_a_section_after_a_column_0_list_is_extended_where_it_is(self) -> None:
        text = TOOLSETS + "skills:\n  external_dirs:\n  - /existing\n" + PROVIDERS + "plugins:\n  enabled:\n  - other\n" + TOOLSETS.replace("toolsets", "extra")
        after = setup_writes(text)
        self.assertEqual(adapter.external_dirs(after), ["/existing", "/o/skills"])
        self.assertEqual(adapter.plugin_enablement(after)["enabled"], ["omh", "other"])
        self.assertIn("  - /existing\n  - /o/skills\n" + PROVIDERS, after)
        self.assertIn("  enabled:\n  - omh\n  - other\nextra:\n- hermes-cli\n- web\n", after)

    def test_absent_sections_are_appended_after_a_trailing_column_0_list(self) -> None:
        after = setup_writes(MODEL + TOOLSETS)
        self.assertTrue(after.startswith(MODEL + TOOLSETS), after)
        self.assertEqual(adapter.external_dirs(after), ["/o/skills"])
        self.assertEqual(adapter.plugin_enablement(after)["enabled"], ["omh"])

    def test_the_other_step_2_writers_leave_the_lists_alone(self) -> None:
        text = DIRECTIVE + TOOLSETS + SKILLS + PLUGINS + "memory:\n  provider: honcho\n" + PROVIDERS
        after = ensure_compression_defaults(setup_writes(text)).text
        memory = adapter.set_memory_provider(after, "omh")
        self.assertFalse(memory.changed)
        home = adapter.ensure_plugin_omh_home(after, "/o")
        self.assertTrue(home.changed, home.message)
        self.assertIn(TOOLSETS, home.text)
        self.assertTrue(home.text.endswith(PROVIDERS), home.text)
        self.assertEqual(adapter.plugin_omh_home_setting(home.text), "/o")

    def test_the_removers_take_back_exactly_what_setup_wrote(self) -> None:
        for name in ("column-0 list after skills", "column-0 list after plugins", "directive and column-0 list"):
            with self.subTest(shape=name):
                text = READABLE[name]
                after = setup_writes(text)
                removed = adapter.remove_plugin_enabled(adapter.remove_external_dir(after, "/o/skills").text, "omh")
                self.assertTrue(removed.changed, removed.message)
                self.assertEqual(adapter.external_dirs(removed.text), [])
                self.assertEqual(adapter.plugin_enablement(removed.text)["enabled"], [])
                self.assert_only_managed_lines_changed(text, removed.text)


class SetupCommandTest(unittest.TestCase):
    """`omh setup --core` gets through step 2 on the reported config (#3075)."""

    def run_setup(self, config_text: str) -> tuple[int, str, str, Path]:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        hermes = root / ".hermes"
        hermes.mkdir()
        config = hermes / "config.yaml"
        config.write_bytes(config_text.encode("utf-8"))
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / ".omh"), "--hermes-home", str(hermes),
             "setup", "--core", "--yes", "--no-interactive", "--no-menubar", "--json"],
            output_json=False,
        )
        return status, stdout, stderr, root

    def test_setup_registers_omh_and_keeps_every_line_the_person_wrote(self) -> None:
        # A memory provider of the person's own, as in the report, so setup has no slot to claim.
        for head in ("", DIRECTIVE):
            original = head + ISSUE_COLUMN0 + "memory:\n  provider: honcho\n" + PROVIDERS
            with self.subTest(head=head):
                status, stdout, stderr, root = self.run_setup(original)
                self.assertEqual(status, 0, stderr)
                self.assertTrue(json.loads(stdout)["ok"])
                omh = (root / ".omh").resolve()
                written = (root / ".hermes" / "config.yaml").read_text(encoding="utf-8")
                # `plugins.entries.omh.settings.omh_home` binds the plugin to this store (#1960); it is
                # OMH's own key, written for every store setup installs.
                self.assertEqual(
                    written,
                    head + MODEL + "toolsets:\n- hermes-cli\n"
                    + f"skills:\n  external_dirs:\n    - {omh / 'skills'}\n"
                    + "plugins:\n  enabled:\n    - omh\n"
                    + f"  entries:\n    omh:\n      settings:\n        omh_home: '{omh}'\n"
                    + "memory:\n  provider: honcho\n" + PROVIDERS,
                )
                skills = sorted(path.parent.name for path in (omh / "skills").rglob("SKILL.md"))
                self.assertEqual(len(skills), 10, skills)
                if hermes_reads("a: 1\n") is not None:
                    loaded = hermes_load(written)
                    self.assertEqual(loaded["toolsets"], ["hermes-cli"])
                    self.assertEqual(loaded["fallback_providers"], [{"model": "example", "provider": "custom"}])
                    self.assertEqual(loaded["skills"]["external_dirs"], [str(omh / "skills")])
                    self.assertEqual(loaded["plugins"]["enabled"], ["omh"])

    def test_setup_still_refuses_a_sequence_document_and_writes_nothing(self) -> None:
        status, _stdout, stderr, root = self.run_setup("- item\n")
        self.assertEqual(status, 2)
        self.assertIn("non-mapping", stderr)
        self.assertEqual((root / ".hermes" / "config.yaml").read_bytes(), b"- item\n")

    def test_setup_claims_the_memory_slot_under_a_commented_header(self) -> None:
        original = MODEL + "memory: # mine\n  recall: true\n"
        status, _stdout, stderr, root = self.run_setup(original)
        self.assertEqual(status, 0, stderr)
        written = (root / ".hermes" / "config.yaml").read_text(encoding="utf-8")
        self.assertEqual(written.count("memory"), 1, written)
        self.assertIn("memory: # mine\n  provider: omh\n  recall: true\n", written)
        if hermes_reads("a: 1\n") is not None:
            self.assertEqual(hermes_load(written)["memory"], {"provider": "omh", "recall": True})

    def test_setup_and_update_on_every_envelope(self) -> None:
        """Setup writes inside the envelope, and update on that registered install writes nothing (#3075)."""
        for name, (head, tail) in EnvelopeTest.ENVELOPES.items():
            if name in EnvelopeTest.REFUSED_STREAMS:
                continue
            original = head + MODEL + "memory:\n  provider: honcho\n" + tail
            with self.subTest(envelope=name):
                status, _stdout, stderr, root = self.run_setup(original)
                self.assertEqual(status, 0, stderr)
                config = root / ".hermes" / "config.yaml"
                written = config.read_text(encoding="utf-8")
                self.assertTrue(written.startswith(head + MODEL + "memory:\n  provider: honcho\n"), written)
                # Every write lands before the `...`.
                self.assertTrue(written.endswith("\n" + tail if tail else "\n"), written)
                self.assertEqual(written.count("..."), tail.count("..."), written)
                if hermes_reads("a: 1\n") is not None:
                    loaded = hermes_load(written)
                    self.assertEqual(loaded["plugins"]["enabled"], ["omh"])
                    self.assertEqual(len(loaded["skills"]["external_dirs"]), 1)
                before = config.read_bytes()
                status, _stdout, stderr = run_cli(
                    ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "update", "--json"],
                    output_json=False,
                )
                self.assertEqual(status, 0, stderr)
                self.assertEqual(config.read_bytes(), before)


class CommentedHeaderTest(unittest.TestCase):
    """A section key with a trailing comment is that section's header: edited in place, never duplicated."""

    def root_keys(self, text: str) -> list[str]:
        return [line.split(":")[0] for line in text.splitlines() if adapter._ends_top_level_node(line)]

    def test_setup_writes_go_under_the_commented_headers(self) -> None:
        text = adapter.set_memory_provider(setup_writes(COMMENTED_HEADERS), "omh").text
        text = adapter.ensure_plugin_omh_home(text, "/o").text
        self.assertEqual(
            text,
            "model:\n  provider: custom\n"
            "skills: # where my skills live\n  external_dirs:\n    - /o/skills\n"
            "plugins:  # third-party\n  enabled:\n    - omh\n  entries:\n    omh:\n      settings:\n"
            "        omh_home: '/o'\n"
            "memory: # mine\n  provider: omh\n  recall: true\n",
        )
        self.assertEqual(self.root_keys(text), ["model", "skills", "plugins", "memory"])

    def test_the_readers_see_through_the_comment(self) -> None:
        self.assertEqual(adapter.memory_provider_selection("memory: # mine\n  provider: honcho\n"), "honcho")
        self.assertEqual(adapter.display_skin_selection("display: # look\n  skin: mono\n"), "mono")
        self.assertIn("memory", adapter.config_container_paths(COMMENTED_HEADERS))

    def test_a_provider_under_a_commented_header_is_kept(self) -> None:
        text = "memory: # mine\n  provider: honcho\n"
        change = adapter.set_memory_provider(text, "omh")
        self.assertFalse(change.changed)
        self.assertEqual(change.text, text)
        self.assertIn("memory.provider is honcho", change.message)

    def test_a_memory_node_this_writer_cannot_fill_is_refused_never_duplicated(self) -> None:
        for text in ("memory: {}\n", "memory: null\n", "memory: honcho\n", "memory: &m\n  recall: true\n",
                     "memory:\n  recall: true\nmemory: # again\n  x: 1\n"):
            with self.subTest(text=text):
                change = adapter.set_memory_provider(text, "omh")
                self.assertFalse(change.changed, change.text)
                self.assertEqual(change.text, text)

    def test_the_removers_take_the_writes_back_under_the_commented_headers(self) -> None:
        written = adapter.set_memory_provider(setup_writes(COMMENTED_HEADERS), "omh").text
        text = adapter.remove_external_dir(written, "/o/skills").text
        text = adapter.remove_plugin_enabled(text, "omh").text
        text = adapter.remove_memory_provider(text, "omh").text
        self.assertEqual(adapter.external_dirs(text), [])
        self.assertEqual(adapter.plugin_enablement(text)["enabled"], [])
        self.assertEqual(adapter.memory_provider_selection(text), "")
        for header in ("skills: # where my skills live", "plugins:  # third-party", "memory: # mine"):
            self.assertEqual(text.count(header), 1, text)
        self.assertEqual(self.root_keys(text), ["model", "skills", "plugins", "memory"])
        self.assertIn("memory: # mine\n  recall: true\n", text)


class EnvelopeTest(unittest.TestCase):
    """Every writer and remover edits the document's body and keeps its envelope as written (#3075)."""

    ENVELOPES = {
        "document start": ("---\n", ""),
        "document start with a comment": ("# mine\n--- # doc\n", ""),
        "YAML 1.1": (DIRECTIVE, ""),
        "YAML 1.1 with comments": ("%YAML 1.1 # v\n--- # doc\n", ""),
        "YAML 1.2": ("%YAML 1.2\n---\n", ""),
        "TAG": ("%TAG !e! tag:example.com,2026:\n---\n", ""),
        "YAML 1.1 and TAG": ("%YAML 1.1\n%TAG !e! tag:example.com,2026:\n---\n", ""),
        "document end": ("", "...\n"),
        "document end with a comment after it": ("---\n", "... # end\n# after\n"),
        "YAML 1.2 and document end": ("%YAML 1.2\n---\n", "...\n"),
        "second document": ("", "---\nx: 1\n"),
        "content after document end": ("", "...\nx: 1\n"),
        "two YAML directives": ("%YAML 1.1\n%YAML 1.2\n---\n", ""),
    }
    REFUSED_STREAMS = {"second document", "content after document end", "two YAML directives"}

    def write_all(self, text: str) -> str:
        text = adapter.set_memory_provider(setup_writes(text), "omh").text
        return adapter.ensure_plugin_omh_home(text, "/o").text

    def test_the_writers_write_inside_the_envelope_and_the_removers_take_it_back(self) -> None:
        for name, (head, tail) in self.ENVELOPES.items():
            if name in self.REFUSED_STREAMS:
                continue
            text = head + MODEL + tail
            with self.subTest(envelope=name):
                written = self.write_all(text)
                self.assertTrue(written.startswith(head + MODEL), written)
                self.assertTrue(written.endswith("memory:\n  provider: omh\n" + tail), written)
                self.assertEqual(adapter.external_dirs(written), ["/o/skills"])
                self.assertEqual(adapter.plugin_enablement(written)["enabled"], ["omh"])
                self.assertEqual(adapter.memory_provider_selection(written), "omh")
                self.assertEqual(adapter.plugin_omh_home_setting(written), "/o")
                # A second pass writes nothing.
                self.assertEqual(self.write_all(written), written)
                removed = adapter.remove_external_dir(written, "/o/skills").text
                removed = adapter.remove_plugin_enabled(removed, "omh").text
                removed = adapter.remove_memory_provider(removed, "omh").text
                removed = adapter.remove_plugin_omh_home(removed, "/o").text
                self.assertEqual(adapter.external_dirs(removed), [])
                self.assertEqual(adapter.plugin_enablement(removed)["enabled"], [])
                self.assertEqual(adapter.memory_provider_selection(removed), "")
                self.assertTrue(removed.startswith(head + MODEL), removed)
                self.assertTrue(removed.endswith(tail), removed)

    def test_a_stream_of_more_than_one_document_is_refused_only_when_there_is_something_to_write(self) -> None:
        registered = "skills:\n  external_dirs:\n    - /o/skills\nplugins:\n  enabled:\n    - omh\n"
        for name in sorted(self.REFUSED_STREAMS):
            head, tail = self.ENVELOPES[name]
            with self.subTest(envelope=name):
                with self.assertRaises(ValueError):
                    adapter.ensure_external_dir(head + MODEL + tail, "/o/skills")
                with self.assertRaises(ValueError):
                    adapter.ensure_plugin_enabled(head + MODEL + tail, "omh")
                self.assertFalse(adapter.set_memory_provider(head + MODEL + tail, "omh").changed)
                text = head + MODEL + registered + tail
                self.assertFalse(adapter.ensure_external_dir(text, "/o/skills").changed)
                self.assertFalse(adapter.ensure_plugin_enabled(text, "omh").changed)
                self.assertFalse(adapter.remove_external_dir(head + MODEL + tail, "/o/skills").changed)
                self.assertFalse(adapter.remove_plugin_enabled(head + MODEL + tail, "omh").changed)

    def test_doctor_passes_an_enabled_install_whatever_its_envelope(self) -> None:
        enabled = "plugins:\n  enabled:\n    - omh\n"
        for name, (head, tail) in self.ENVELOPES.items():
            with self.subTest(envelope=name):
                self.assertEqual(adapter.plugins_enabled_extension_error(head + MODEL + enabled + tail, "omh"), "")
        for name in sorted(self.REFUSED_STREAMS):
            head, tail = self.ENVELOPES[name]
            with self.subTest(refused=name):
                message = adapter.plugins_enabled_extension_error(head + MODEL + tail, "omh")
                self.assertIn("one YAML document", message)
                self.assertIn("hermes plugins enable omh", message)
        # A second `enabled:` key is still a fault, listed or not: Hermes refuses the file over it.
        self.assertIn("duplicate plugins.enabled", adapter.plugins_enabled_extension_error(
            "plugins:\n  enabled:\n    - omh\n  enabled: []\n", "omh"))


@unittest.skipIf(hermes_reads("a: 1\n") is None, "Hermes is not installed here")
class HermesAgreesTest(unittest.TestCase):
    """The guard never takes a file Hermes' own loader refuses, and what setup writes still loads there."""

    def test_every_readable_shape_loads_to_a_mapping_in_hermes(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                self.assertTrue(hermes_reads(text), name)

    def test_the_refused_loader_failures_fail_in_hermes(self) -> None:
        rejected = [name for name, text in REFUSED.items() if hermes_reads(text) is False]
        for name in ("sequence document", "sequence after document start", "item before the first key",
                     "item after a key with a value", "item after indented lines", "item after an indented list",
                     "second document", "two directives", "directive without document start"):
            self.assertIn(name, rejected)

    def test_setup_writes_load_to_the_same_data_plus_the_registrations(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                expected = hermes_load(text)
                expected.setdefault("skills", {})["external_dirs"] = ["/o/skills"]
                expected.setdefault("plugins", {})["enabled"] = ["omh"]
                self.assertEqual(hermes_load(setup_writes(text)), expected)

    def test_the_commented_header_writes_load_without_a_duplicate_key(self) -> None:
        self.assertTrue(hermes_reads(COMMENTED_HEADERS))
        written = adapter.set_memory_provider(setup_writes(COMMENTED_HEADERS), "omh").text
        written = adapter.ensure_plugin_omh_home(written, "/o").text
        loaded = hermes_load(written)
        self.assertEqual(loaded["skills"], {"external_dirs": ["/o/skills"]})
        self.assertEqual(loaded["plugins"], {"enabled": ["omh"], "entries": {"omh": {"settings": {"omh_home": "/o"}}}})
        self.assertEqual(loaded["memory"], {"provider": "omh", "recall": True})

    def test_every_envelope_the_writers_take_still_loads(self) -> None:
        for name, (head, tail) in EnvelopeTest.ENVELOPES.items():
            if name in EnvelopeTest.REFUSED_STREAMS:
                continue
            with self.subTest(envelope=name):
                written = EnvelopeTest().write_all(head + MODEL + tail)
                loaded = hermes_load(written)
                self.assertEqual(loaded["skills"], {"external_dirs": ["/o/skills"]})
                self.assertEqual(loaded["plugins"]["enabled"], ["omh"])
                self.assertEqual(loaded["memory"], {"provider": "omh"})

    def test_the_pinned_results_are_what_hermes_loads(self) -> None:
        for name, loaded in PINNED.items():
            with self.subTest(shape=name):
                self.assertEqual(hermes_load(READABLE[name]), loaded)

    def test_a_quoted_value_across_lines_hides_no_key(self) -> None:
        self.assertNotIn("memory", hermes_load(REFUSED["quoted value across lines"]))

    def test_both_spellings_of_the_issue_config_load_alike(self) -> None:
        self.assertEqual(hermes_load(ISSUE_COLUMN0), hermes_load(ISSUE_INDENTED))
        self.assertEqual(hermes_load(setup_writes(ISSUE_COLUMN0)), hermes_load(setup_writes(ISSUE_INDENTED)))


if __name__ == "__main__":
    unittest.main()
