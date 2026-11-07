"""`omh doctor` says which Jev-class plugins a machine holds, and only that.

Jev is a non-generative decision model OMH never calls. What these tests hold
is the boundary between the three things OMH may say about it and the many it
may not. It may say a plugin directory exists, that Hermes' config lists the
name, and that a credential NAME appears in the env file. It may quote what a
catalog entry declares, naming where the quote was read. It may not say the
plugin ran, that Jev is served, or that anything left the machine -- and it may
never copy a credential value, which the fixtures below prove by writing one
and asserting it reaches no output.

The check is appended on every run, in both branches, because an optional
surface that appears only on some machines makes the operator summary's
`total` vary by machine and makes a clean home indistinguishable from a check
that did not run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package
from _platform_support import requires_posix, requires_symlinks

load_local_package()

from omh.commands import setup as setup_commands  # noqa: E402
from omh.install.config_adapter import ensure_plugin_enabled  # noqa: E402
from omh.maintenance.doctor import doctor_ok, run_doctor  # noqa: E402
from omh.paths import OmhPaths  # noqa: E402
from omh.plugin_bundle.omh.jev_sidekick import (  # noqa: E402
    JEV_CATALOG_READ_ON,
    JEV_CREDENTIAL_ENV_NAMES,
    JEV_TOOL_PREFIX,
    KNOWN_JEV_PLUGINS,
    classify_plugin,
    is_jev_tool_name,
)
from omh.plugin_bundle.omh.metadata import PROVIDED_HOOKS  # noqa: E402
from omh.plugin_bundle.omh.provider_detection import (  # noqa: E402
    HERMES_ENV_KEY_PROVIDERS,
    env_key_names,
)
from omh.maintenance import doctor as doctor_module  # noqa: E402
from omh.workflows.jev_sidekick_posture import (  # noqa: E402
    ENABLEMENT_ENABLED,
    ENABLEMENT_NOT_ENABLED,
    ENABLEMENT_UNKNOWN,
    JEV_SIDEKICK_POSTURE_SCHEMA_VERSION,
    MAX_CONFIG_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PLUGIN_DIRECTORIES,
    MAX_PLUGIN_NAME_CHARS,
    POSTURE_STATUSES,
    UNREADABLE_DECLARATION_FIELDS,
    build_jev_sidekick_posture,
    posture_overlaps,
    posture_unestablished_hook_overlap,
    posture_unknown_enablement,
)

# A value, not a name. Every assertion about it is that it never appears.
SECRET_VALUE = "sk-jev-do-not-print-this-value"


def _write(path: Path, body: str) -> None:
    # `newline="\n"` on every fixture write: `write_text` without it emits
    # CRLF on Windows, and a manifest fixture that differs by platform makes a
    # reader's line handling untested on one of them.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def _paths(root: Path) -> OmhPaths:
    paths = OmhPaths(root / ".omh", root / ".hermes")
    paths.hermes_home.mkdir(parents=True, exist_ok=True)
    return paths


def _install_plugin(paths: OmhPaths, directory: str, manifest: str) -> Path:
    plugin_dir = paths.hermes_plugins_dir / directory
    _write(plugin_dir / "plugin.yaml", manifest)
    return plugin_dir


def _enable(paths: OmhPaths, *names: str) -> None:
    """Add each name to `plugins.enabled`, keeping whatever the config already holds.

    Through the writer `omh setup` itself uses, so a fixture that enables a
    third-party plugin does not quietly un-register OMH and turn every other
    doctor check red.
    """
    body = paths.hermes_config_path.read_text(encoding="utf-8") if paths.hermes_config_path.is_file() else ""
    for name in names:
        body = ensure_plugin_enabled(body, name).text
    _write(paths.hermes_config_path, body)


def _doctor_check(paths: OmhPaths):
    checks = run_doctor(paths)
    return checks, next(check for check in checks if check.name == "plugin_jev_sidekick")


def _without_jev(checks):
    return [check for check in checks if check.name != "plugin_jev_sidekick"]


class _ZeroSizeStat:
    """A real stat result that reports `st_size == 0`.

    What a `/proc`-style file does on its own, and what a file that grows
    between a `stat` and the read after it does to a cap taken from the first.
    Everything but the size is delegated, so `is_file` and `is_dir` still
    answer from the real mode bits.
    """

    def __init__(self, real: object) -> None:
        self._real = real

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    @property
    def st_size(self) -> int:
        return 0


def _installed_paths(root: Path) -> OmhPaths:
    """A home `omh setup` has written, so the CLI report is not dominated by absence."""
    paths = _paths(root)
    base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]
    status, _stdout, stderr = run_cli(base + ["setup", "--no-interactive"], output_json=False)
    assert status == 0, stderr
    return paths


class ClassifierTests(unittest.TestCase):
    def test_a_known_name_classifies_with_its_catalog_quote(self) -> None:
        record = classify_plugin("typesafe-skill-router", (), ("pre_llm_call",))

        self.assertIsNotNone(record)
        assert record is not None
        self.assertTrue(record["known"])
        self.assertEqual(record["repo"], "https://github.com/DECRUX9812/typesafe-skill-router")
        self.assertEqual(record["jev_tools"], [])
        self.assertIn("pre_llm_call", record["hook_overlap"])
        self.assertIn("two nominations", str(record["overlap"]))
        self.assertTrue(str(record["read_from"]).startswith("hermes-agent plugin-catalog/"))
        self.assertEqual(record["read_on"], JEV_CATALOG_READ_ON)

    def test_an_unknown_name_classifies_on_the_tool_prefix_and_quotes_nothing(self) -> None:
        record = classify_plugin("someone-elses-plugin", ("jev_ask", "unrelated_tool"), ())

        self.assertIsNotNone(record)
        assert record is not None
        self.assertFalse(record["known"])
        self.assertEqual(record["jev_tools"], ["jev_ask"])
        # No record was read for this name, so the plugin must not inherit
        # another plugin's disclosure, repo, or provenance.
        self.assertEqual(record["declared_disclosure"], "")
        self.assertEqual(record["overlap"], "")
        self.assertEqual(record["repo"], "")
        self.assertEqual(record["read_from"], "")
        self.assertEqual(record["read_on"], "")

    def test_the_renamed_nerve_lineage_classifies_on_its_own_prefix(self) -> None:
        record = classify_plugin("nerve", ("nerve_decide", "nerve_work_status", "unrelated_tool"), ())

        assert record is not None
        self.assertTrue(record["known"])
        self.assertEqual(record["repo"], "https://github.com/keeltrace/hermes-nerve")
        self.assertEqual(record["jev_tools"], ["nerve_decide", "nerve_work_status"])
        # #119045 is open: the provenance must say it is a PR head, not the
        # catalog Hermes ships.
        self.assertIn("open PR NousResearch/hermes-agent#119045", str(record["read_from"]))
        self.assertIn("(not merged)", str(record["read_from"]))
        self.assertEqual(record["read_on"], "2026-09-23")

    def test_the_pre_rename_name_stays_known(self) -> None:
        record = classify_plugin("hermes-jev", ("jev_decide",), ())

        assert record is not None
        self.assertTrue(record["known"])
        self.assertEqual(record["jev_tools"], ["jev_decide"])

    def test_a_nerve_tool_under_another_name_is_not_a_jev_signal(self) -> None:
        # The lineage prefix is honored for the `nerve` name alone. Another
        # plugin's `nerve_` tool, including one the Nerve entry declares, is
        # not evidence of a Jev-class plugin.
        self.assertIsNone(classify_plugin("brainstem", ("nerve_ping",), ()))
        self.assertIsNone(classify_plugin("brainstem", ("nerve_decide",), ()))

    def test_a_hermes_jev_directory_updated_in_place_keeps_its_nerve_tools(self) -> None:
        # The repository rename redirects, so an existing `plugins/hermes-jev`
        # checkout can be updated in place: the directory keeps the old name
        # while its manifest declares `nerve_` tools. Those tools stay on the
        # lineage's record instead of leaving the rung with an empty list.
        record = classify_plugin("hermes-jev", ("nerve_decide", "unrelated_tool"), ())
        assert record is not None
        self.assertTrue(record["known"])
        self.assertEqual(record["jev_tools"], ["nerve_decide"])

    def test_is_jev_tool_name_takes_exact_lineage_names_and_no_bare_prefix(self) -> None:
        self.assertTrue(is_jev_tool_name("jev_decide"))
        self.assertTrue(is_jev_tool_name("jev_anything_new"))
        self.assertTrue(is_jev_tool_name("nerve_decide"))
        self.assertTrue(is_jev_tool_name("nerve_remote_worker_control"))
        self.assertFalse(is_jev_tool_name("nerve_ping"))
        self.assertFalse(is_jev_tool_name("nerve_"))
        self.assertFalse(is_jev_tool_name("read_file"))

    def test_jev_curator_is_known_with_its_catalog_quote(self) -> None:
        record = classify_plugin("jev-curator", ("jev_skill_relations",), ("on_skill_lifecycle", "pre_tool_call"))

        assert record is not None
        self.assertTrue(record["known"])
        self.assertEqual(record["repo"], "https://github.com/anpicasso/hermes-jev-curator")
        self.assertIn("allow_content_egress", str(record["declared_disclosure"]))
        self.assertEqual(record["read_from"], "hermes-agent plugin-catalog/jev-curator.yaml @ origin/main 38c289c014")
        self.assertEqual(record["read_on"], "2026-09-23")

    def test_neither_signal_is_not_a_finding(self) -> None:
        self.assertIsNone(classify_plugin("herdr-agent-state", ("herdr_state",), ("on_session_start",)))
        self.assertIsNone(classify_plugin("jevons-paradox", (), ()))

    def test_hook_overlap_is_computed_against_the_bridge_not_stored(self) -> None:
        # The claim "this plugin shares a hook with OMH" is derived from OMH's
        # own declared hook list at the moment it is made. A stored sentence
        # would keep saying it after the bridge stopped registering the hook.
        shared = next(hook for hook in PROVIDED_HOOKS)
        record = classify_plugin("hermes-jev", (), (shared, "a_hook_omh_does_not_register"))

        assert record is not None
        self.assertEqual(record["hook_overlap"], [shared])
        self.assertIn("a_hook_omh_does_not_register", record["declares_hooks"])

    # The original transcription, and the 2026-09-23 refresh that added
    # jev-curator and the nerve rename. A third date is a new read and names
    # itself here.
    READ_ON = (JEV_CATALOG_READ_ON, "2026-09-23")

    def test_every_record_carries_where_and_when_it_was_read(self) -> None:
        for record in KNOWN_JEV_PLUGINS:
            with self.subTest(plugin=record.name):
                self.assertTrue(record.repo.startswith("https://github.com/"))
                self.assertTrue(record.read_from.startswith("hermes-agent plugin-catalog/"))
                self.assertIn(f"/{record.name}.yaml", record.read_from)
                self.assertIn(record.read_on, self.READ_ON)
                for tool in record.declares_tools:
                    self.assertTrue(tool.startswith((JEV_TOOL_PREFIX, record.lineage_tool_prefix or JEV_TOOL_PREFIX)))
                if record.declared_disclosure:
                    self.assertTrue(record.declared_disclosure.startswith("Disclosure — "))

    def test_the_credential_names_are_the_two_that_are_declared_somewhere(self) -> None:
        self.assertEqual(JEV_CREDENTIAL_ENV_NAMES, frozenset({"TYPESAFE_API_KEY", "OPENROUTER_API_KEY"}))
        # CLOUDFLARE_JEV_API_TOKEN is named by no vendor page and no catalog
        # entry. Reporting an invented variable name as a machine fact is the
        # failure this assertion exists to keep out.
        self.assertNotIn("CLOUDFLARE_JEV_API_TOKEN", JEV_CREDENTIAL_ENV_NAMES)

    def test_jev_names_never_join_the_provider_registry(self) -> None:
        # HERMES_ENV_KEY_PROVIDERS feeds effective_provider_entitlements, so a
        # name added there reorders mixture chains. Jev cannot be a chain
        # member at all, so its credential names must reach the posture
        # through the `allowed` parameter and never through enrolment.
        self.assertNotIn("TYPESAFE_API_KEY", HERMES_ENV_KEY_PROVIDERS)


class CatalogTranscriptionTests(unittest.TestCase):
    """A second hand copy of the same catalog read, kept beside the first.

    Parity between a table and something generated from it would agree with a
    wrong table. This is the other kind of check: two independent
    transcriptions of the same YAML, so an edit to either side that nobody
    intended fails. It detects a local change to the table; it does not and
    cannot detect upstream drift, because nothing here reads the catalog.
    """

    MIRROR = {
        "jev": (
            "https://github.com/ourines/hermes-jev",
            ("jev_evaluate",),
            (),
            "",
        ),
        "jev-typesafe": (
            "https://github.com/ajensenwaud/hermes-jev-plugin",
            ("jev_evaluate", "jev_check", "jev_route", "jev_score"),
            (),
            "Disclosure — every tool call sends the model-supplied question/state together with your "
            "TYPESAFE_API_KEY to api.typesafe.ai (TypeSafe AI, an independent vendor); the catalog has not "
            "verified the plugin author's affiliation with that vendor.",
        ),
        "hermes-jev": (
            "https://github.com/keeltrace/hermes-jev",
            (
                "jev_decide",
                "jev_rank",
                "jev_verify",
                "jev_assess",
                "jev_context_curate",
                "jev_context_rehydrate",
                "jev_stats",
                "jev_nervous_event",
            ),
            (
                "pre_tool_call",
                "post_tool_call",
                "pre_llm_call",
                "transform_tool_result",
                "pre_verify",
                "post_llm_call",
                "on_session_end",
            ),
            "Disclosure — with the default settings (nervous_enabled / turn_admission on) each turn's user "
            "prompt (up to 12k characters) and redacted tool/result previews are sent to OpenRouter Decisions "
            "(TypeSafe Jev) using your OPENROUTER_API_KEY or TYPESAFE_API_KEY, spending your credits on every turn.",
        ),
        "nerve": (
            "https://github.com/keeltrace/hermes-nerve",
            (
                "nerve_decide",
                "nerve_rank",
                "nerve_verify",
                "nerve_assess",
                "nerve_context_curate",
                "nerve_context_rehydrate",
                "nerve_stats",
                "nerve_nervous_event",
                "nerve_supervise_card",
                "nerve_work_event",
                "nerve_work_status",
                "nerve_remote_delegate_task",
                "nerve_remote_worker_status",
                "nerve_remote_worker_result",
                "nerve_remote_worker_cancel",
                "nerve_remote_worker_control",
            ),
            (
                "pre_tool_call",
                "post_tool_call",
                "pre_llm_call",
                "transform_tool_result",
                "pre_verify",
                "post_api_request",
                "api_request_error",
                "post_llm_call",
                "on_session_end",
            ),
            "Disclosure — the default Reflex backend is hosted Jev; when enabled it can send user prompts and "
            "redacted tool/result previews to the configured Jev provider using the user's provider credentials. "
            "Laya and OpenJev can be configured as local/self-hosted backends.",
        ),
        "jev-curator": (
            "https://github.com/anpicasso/hermes-jev-curator",
            ("jev_skill_relations",),
            ("on_skill_lifecycle", "pre_tool_call"),
            "Disclosure — no egress occurs by default; after allow_content_egress is explicitly enabled, "
            "redacted bounded skill content is sent to the configured TypeSafe, OpenRouter, or custom Jev "
            "endpoint and may spend provider credits. Automatic refreshes never apply mutations, and missing, "
            "stale, or incomplete evidence fails closed.",
        ),
        "jev-approvals": (
            "https://github.com/anpicasso/hermes-jev-approvals",
            (),
            (),
            "Disclosure — each command routed to smart approval (redacted best-effort) and the operator's "
            "smart-policy text leave the machine for the configured third-party endpoint; provider or validation "
            "failures fail closed to ESCALATE.",
        ),
        "hermes-structured-aux-models": (
            "https://github.com/trajectoire-ai/hermes-structured-aux-models",
            (),
            (),
            "Disclosure — sends redacted approval prompts, MCP tool names and compression transcript blocks "
            "to openrouter.ai using your OpenRouter key (read-only); on any error approvals escalate to you, never "
            "auto-approve; the default decision_model is a moving alias, pin it.",
        ),
        "typesafe-skill-router": (
            "https://github.com/DECRUX9812/typesafe-skill-router",
            (),
            ("pre_llm_call",),
            "",
        ),
        "jev-model-router": ("https://github.com/Pinutss/jev-model-router", (), (), ""),
        "jev-memory-selector": ("https://github.com/Pinutss/jev-memory-selector", (), (), ""),
        "jev-agent-router": ("https://github.com/Pinutss/jev-agent-router", (), (), ""),
        "jev-mcp-router": ("https://github.com/Pinutss/jev-mcp-router", (), (), ""),
    }

    def test_the_table_matches_the_second_transcription(self) -> None:
        self.assertEqual({record.name for record in KNOWN_JEV_PLUGINS}, set(self.MIRROR))
        for record in KNOWN_JEV_PLUGINS:
            with self.subTest(plugin=record.name):
                self.assertEqual(
                    (record.repo, record.declares_tools, record.declares_hooks, record.declared_disclosure),
                    self.MIRROR[record.name],
                )


class PostureTests(unittest.TestCase):
    def test_a_home_with_no_plugins_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["schema_version"], JEV_SIDEKICK_POSTURE_SCHEMA_VERSION)
            self.assertEqual(posture["status"], "absent")
            self.assertEqual(posture["plugins"], [])
            self.assertEqual(posture["skipped"], [])
            self.assertIn("never copies or reports credential values", str(posture["claim_boundary"]))
            self.assertIn(posture["status"], POSTURE_STATUSES)

    def test_a_missing_hermes_home_is_absent_rather_than_an_error(self) -> None:
        with TemporaryDirectory() as tmp:
            posture = build_jev_sidekick_posture(Path(tmp) / "never-created")

            self.assertEqual(posture["status"], "absent")

    def test_a_plugin_that_is_neither_known_nor_jev_tooled_is_not_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "herdr-agent-state", "name: herdr-agent-state\ndescription: panes\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "absent")
            self.assertEqual(posture["skipped"], [])

    def test_an_installed_jev_tool_is_found_under_any_directory_name(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "local-checkout", "name: mystery\nprovides_tools:\n  - jev_ask\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "installed")
            entry = posture["plugins"][0]
            self.assertEqual(entry["name"], "mystery")
            self.assertEqual(entry["directory"], "local-checkout")
            self.assertFalse(entry["known"])
            self.assertEqual(entry["enablement"], ENABLEMENT_NOT_ENABLED)

    def test_an_installed_nerve_reports_known_with_its_renamed_tools(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "nerve", "name: nerve\nprovides_tools:\n  - nerve_decide\n  - nerve_stats\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "installed")
            entry = posture["plugins"][0]
            self.assertTrue(entry["known"])
            self.assertEqual(entry["jev_tools"], ["nerve_decide", "nerve_stats"])
            self.assertIn("hosted Jev", str(entry["declared_disclosure"]))

    def test_an_unrelated_nerve_tool_plugin_is_not_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "brainstem", "name: brainstem\nprovides_tools:\n  - nerve_ping\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "absent")
            self.assertEqual(posture["plugins"], [])

    def test_a_known_name_is_found_with_no_tools_declared(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev-approvals", "name: jev-approvals\nversion: \"0.3.0\"\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            entry = posture["plugins"][0]
            self.assertTrue(entry["known"])
            self.assertEqual(entry["jev_tools"], [])
            self.assertIn("fail closed to ESCALATE", str(entry["declared_disclosure"]))

    def test_enablement_is_read_from_the_hermes_config(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")

            before = build_jev_sidekick_posture(paths.hermes_home)
            self.assertEqual(before["status"], "installed")
            self.assertEqual(before["plugins"][0]["enablement"], ENABLEMENT_NOT_ENABLED)
            self.assertEqual(before["plugins"][0]["enablement_reason"], "")

            _enable(paths, "jev")

            posture = build_jev_sidekick_posture(paths.hermes_home)
            self.assertEqual(posture["status"], "enabled")
            self.assertEqual(posture["plugins"][0]["enablement"], ENABLEMENT_ENABLED)
            self.assertEqual(posture_unknown_enablement(posture), [])

    def test_a_credential_name_is_read_and_its_value_is_not(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            _enable(paths, "jev")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "credential_name_present")
            self.assertEqual(posture["credential_names_present"], ["TYPESAFE_API_KEY"])
            self.assertNotIn(SECRET_VALUE, json.dumps(posture))

    def test_an_openrouter_key_alone_is_not_a_jev_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _write(paths.hermes_home / ".env", f"OPENROUTER_API_KEY={SECRET_VALUE}\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "absent")
            self.assertEqual(posture["credential_names_present"], [])

    def test_a_key_outside_the_jev_set_never_reaches_the_posture(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            _enable(paths, "jev")
            _write(paths.hermes_home / ".env", f"ANTHROPIC_API_KEY={SECRET_VALUE}\nTYPESAFE_API_KEY={SECRET_VALUE}\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["credential_names_present"], ["TYPESAFE_API_KEY"])

    def test_an_unreadable_manifest_is_named_rather_than_dropped(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            # Unquoted, which YAML itself rejects: the bounded reader refuses
            # the document rather than reading the keys around it.
            _install_plugin(paths, "broken", "name: broken\nrequires_hermes: >=0.21\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["status"], "absent")
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["broken"])
            self.assertIn("outside the readable subset", posture["skipped"][0]["reason"])

    def test_a_tool_declaration_the_reader_does_not_model_is_named(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            # An inline flow sequence. `[]` and `[jev_evaluate]` are the same
            # shape to the bounded reader, so an unknown name whose tools it
            # could not read is a plugin it could not clear.
            _install_plugin(paths, "inline", "name: inline\nprovides_tools: [jev_evaluate]\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["inline"])
            self.assertIn("provides_tools", posture["skipped"][0]["reason"])

    def test_an_unread_hook_declaration_leaves_the_overlap_unestablished(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks: []\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            entry = posture["plugins"][0]
            self.assertEqual(entry["hook_overlap"], [])
            self.assertEqual(entry["unreadable_declarations"], ["provides_hooks"])
            # An empty overlap means two different things and only one of them
            # is "no overlap".
            self.assertEqual(posture_overlaps(posture), [])
            self.assertEqual(posture_unestablished_hook_overlap(posture), ["jev"])

    def test_a_read_hook_declaration_establishes_the_overlap(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(
                paths,
                "typesafe-skill-router",
                "name: typesafe-skill-router\nprovides_hooks:\n  - pre_llm_call\n",
            )

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"][0]["hook_overlap"], ["pre_llm_call"])
            self.assertEqual(posture_unestablished_hook_overlap(posture), [])
            self.assertEqual(posture_overlaps(posture), ["typesafe-skill-router"])

    @requires_symlinks
    def test_a_symlinked_plugin_directory_is_reported_and_not_followed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            outside = root / "outside-the-home"
            _write(outside / "plugin.yaml", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            paths.hermes_plugins_dir.mkdir(parents=True, exist_ok=True)
            (paths.hermes_plugins_dir / "linked").symlink_to(outside, target_is_directory=True)

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"], [])
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["linked"])
            self.assertIn("symlinked", posture["skipped"][0]["reason"])

    @requires_symlinks
    def test_a_symlinked_plugin_manifest_is_reported_and_not_followed(self) -> None:
        # The directory guard above states the reason a symlink is refused --
        # resolving one reads a path outside the home OMH was asked about --
        # and `is_file()` plus a read resolve one just as happily, so without
        # this the same escape works one level down and `skipped` stays empty.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            outside = root / "outside-the-home"
            _write(outside / "plugin.yaml", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            plugin_dir = paths.hermes_plugins_dir / "linked-manifest"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.yaml").symlink_to(outside / "plugin.yaml")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"], [])
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["linked-manifest"])
            self.assertIn("symlinked plugin manifest", posture["skipped"][0]["reason"])

    @requires_posix
    def test_a_directory_name_cannot_forge_a_report_line(self) -> None:
        # The manifest reader bans control characters in a declared `name:`;
        # a directory name passes no reader at all. `\x1b[2K\r` repaints the
        # line above it and a newline writes a whole new one, in the artifact
        # an operator pastes into a bug report.
        forged = "jev\x1b[2K\r-evil\nplugin_jev_sidekick: ok"
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, forged, "provides_tools:\n  - jev_evaluate\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)
            _checks, check = _doctor_check(paths)

            entry = posture["plugins"][0]
            self.assertEqual(entry["name"], "jev-evilplugin_jev_sidekick: ok")
            self.assertEqual(entry["directory"], "jev-evilplugin_jev_sidekick: ok")
            for text in (json.dumps(posture), check.message, check.next_action):
                self.assertNotIn("\x1b", text)
                self.assertNotIn("\r", text)
            self.assertNotIn("\n", check.message)
            self.assertNotIn("\n", check.next_action)

    def test_a_directory_name_is_bounded(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev-" + "x" * 200, "provides_tools:\n  - jev_evaluate\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            entry = posture["plugins"][0]
            self.assertEqual(len(str(entry["name"])), MAX_PLUGIN_NAME_CHARS)
            # A name OMH truncated is no longer the name Hermes would match,
            # so the enablement answer is not OMH's to give.
            self.assertEqual(entry["enablement"], ENABLEMENT_UNKNOWN)

    def test_an_unreadable_name_does_not_inherit_another_maintainers_record(self) -> None:
        # `name: [weird]` is an inline flow value the bounded reader does not
        # model, so this manifest's identity is unread and the directory name
        # is a guess. Classifying against the guess would attach keeltrace's
        # verbatim egress disclosure to this install.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "hermes-jev", "name: [weird]\nprovides_tools:\n  - jev_evaluate\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)
            _checks, check = _doctor_check(paths)

            entry = posture["plugins"][0]
            self.assertFalse(entry["known"])
            self.assertEqual(entry["declared_disclosure"], "")
            self.assertEqual(entry["repo"], "")
            self.assertEqual(entry["read_from"], "")
            self.assertEqual(entry["name"], "hermes-jev")
            self.assertEqual(entry["unreadable_declarations"], ["name"])
            self.assertEqual(entry["enablement"], ENABLEMENT_UNKNOWN)
            self.assertNotIn("discloses", check.message)

    def test_an_unreadable_plugins_directory_is_reported_rather_than_read_as_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.hermes_plugins_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(Path, "iterdir", side_effect=PermissionError(13, "denied")):
                posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"], [])
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["plugins"])
            self.assertIn("plugins directory is unreadable: PermissionError", posture["skipped"][0]["reason"])

    def test_the_sweep_stops_at_the_directory_budget_and_names_an_unread_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.hermes_plugins_dir.mkdir(parents=True, exist_ok=True)
            for index in range(MAX_PLUGIN_DIRECTORIES):
                (paths.hermes_plugins_dir / f"plugin-{index:04d}").mkdir()
            # Sorts after every filler directory, so it is only reachable if
            # the budget did not stop the sweep.
            _install_plugin(paths, "zzz-jev", "name: zzz-jev\nprovides_tools:\n  - jev_evaluate\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"], [])
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["zzz-jev"])
            # The row names the entry the sweep did not reach, not the
            # container: "plugins" in that field reads as a plugin name.
            self.assertIn(f"stopped at {MAX_PLUGIN_DIRECTORIES} plugin directories", posture["skipped"][0]["reason"])
            self.assertIn("this entry was not read", posture["skipped"][0]["reason"])

    def test_loose_files_are_not_counted_against_the_directory_budget(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.hermes_plugins_dir.mkdir(parents=True, exist_ok=True)
            for index in range(MAX_PLUGIN_DIRECTORIES + 8):
                _write(paths.hermes_plugins_dir / f"loose-{index:04d}.txt", "not a plugin\n")
            _install_plugin(paths, "zzz-jev", "name: zzz-jev\nprovides_tools:\n  - jev_evaluate\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual([entry["name"] for entry in posture["plugins"]], ["zzz-jev"])
            self.assertEqual(posture["skipped"], [])

    def test_an_oversized_manifest_is_named_rather_than_read(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            body = "name: jev\nprovides_tools:\n  - jev_evaluate\n"
            _install_plugin(paths, "huge", body + "# " + "p" * MAX_MANIFEST_BYTES + "\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual(posture["plugins"], [])
            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["huge"])
            self.assertIn(f"manifest exceeds {MAX_MANIFEST_BYTES} bytes", posture["skipped"][0]["reason"])

    def test_a_zero_length_stat_does_not_walk_past_the_byte_cap(self) -> None:
        # The cap is taken at the read, not from a preceding `stat`: a file
        # reporting `st_size == 0` and a file that grows between the two calls
        # both walk past a size check and neither walks past a short read.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "huge", "name: jev\n" + "# " + "p" * MAX_MANIFEST_BYTES + "\n")

            real_stat = Path.stat

            def zero_size(self: Path, *args: object, **kwargs: object) -> object:
                result = real_stat(self, *args, **kwargs)  # type: ignore[arg-type]
                return _ZeroSizeStat(result) if self.name == "plugin.yaml" else result

            with patch.object(Path, "stat", zero_size):
                posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual([entry["plugin"] for entry in posture["skipped"]], ["huge"])
            self.assertIn("manifest exceeds", posture["skipped"][0]["reason"])

    def test_a_plugins_node_the_reader_walks_past_leaves_enablement_unknown(self) -> None:
        # Valid YAML Hermes loads -- measured with the PyYAML in Hermes' own
        # venv, this loads as `{'plugins': {'enabled': ['jev']}}` -- and a
        # node the reader does not follow, so it reports the same empty lists
        # a config that enables nothing reports. "Nothing enables it" and
        # "nobody read it" are different facts about a machine.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _write(paths.hermes_config_path, "base: &plugins\n  enabled: [jev]\nplugins: *plugins\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)
            _checks, check = _doctor_check(paths)

            entry = posture["plugins"][0]
            self.assertEqual(entry["enablement"], ENABLEMENT_UNKNOWN)
            self.assertIn("form OMH does not read", str(entry["enablement_reason"]))
            self.assertEqual(posture_unknown_enablement(posture), ["jev"])
            self.assertEqual(posture["status"], "installed")
            self.assertNotIn("not enabled", check.message)
            self.assertIn("enablement not established", check.message)

    def test_a_flow_mapping_plugins_node_reads_as_enabled(self) -> None:
        # The other half of the pair above, and the #1814 report: the flow
        # form is the node OMH used to walk past, so the posture said the
        # enablement was not established for a plugin Hermes loads. It is a
        # read now, and an unknown here would be the old false answer wearing
        # the new label.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _write(paths.hermes_config_path, "plugins: {enabled: [jev]}\n")

            posture = build_jev_sidekick_posture(paths.hermes_home)
            _checks, check = _doctor_check(paths)

            entry = posture["plugins"][0]
            self.assertEqual(entry["enablement"], ENABLEMENT_ENABLED)
            self.assertEqual(entry["enablement_reason"], "")
            self.assertEqual(posture_unknown_enablement(posture), [])
            self.assertEqual(posture["status"], "enabled")
            self.assertNotIn("enablement not established", check.message)

    def test_a_config_that_cannot_be_read_whole_leaves_enablement_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _write(
                paths.hermes_config_path,
                "plugins:\n  enabled:\n    - jev\n# " + "c" * MAX_CONFIG_BYTES + "\n",
            )

            posture = build_jev_sidekick_posture(paths.hermes_home)

            entry = posture["plugins"][0]
            self.assertEqual(entry["enablement"], ENABLEMENT_UNKNOWN)
            self.assertIn("could not be read whole", str(entry["enablement_reason"]))

    def test_enablement_is_only_ever_one_of_the_three_spellings(self) -> None:
        # Three states and no fourth spelling: `_jev_enablement_label` maps
        # two of them by name and treats everything else as unread, so a new
        # value would silently print "enablement not established".
        states = {ENABLEMENT_ENABLED, ENABLEMENT_NOT_ENABLED, ENABLEMENT_UNKNOWN}
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            _install_plugin(paths, "hermes-jev", "name: [weird]\nprovides_tools:\n  - jev_ask\n")
            _enable(paths, "jev")

            posture = build_jev_sidekick_posture(paths.hermes_home)

            self.assertEqual({str(entry["enablement"]) for entry in posture["plugins"]}, {ENABLEMENT_ENABLED, ENABLEMENT_UNKNOWN})
            for entry in posture["plugins"]:
                self.assertIn(entry["enablement"], states)

    def test_the_catalog_side_of_the_comparison_is_not_carried(self) -> None:
        # The table's own tool and hook lists were carried for a
        # catalog-versus-disk comparison nothing made. A field shipped for a
        # comparison no code, message or test performs is a claim the change
        # does not keep, so the table stays the place to read them.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")

            entry = build_jev_sidekick_posture(paths.hermes_home)["plugins"][0]

            self.assertNotIn("catalog_tools", entry)
            self.assertNotIn("catalog_hooks", entry)

    def test_zero_writes_to_hermes_home(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\n")
            _enable(paths, "jev")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")
            before = {
                str(item): (item.stat().st_mtime_ns, item.stat().st_size)
                for item in paths.hermes_home.rglob("*")
                if item.is_file()
            }

            build_jev_sidekick_posture(paths.hermes_home)

            after = {
                str(item): (item.stat().st_mtime_ns, item.stat().st_size)
                for item in paths.hermes_home.rglob("*")
                if item.is_file()
            }
            self.assertEqual(before, after)


class EnvKeyNameSeamTests(unittest.TestCase):
    def test_the_default_call_is_unchanged(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / ".env", f"GLM_API_KEY={SECRET_VALUE}\nTYPESAFE_API_KEY={SECRET_VALUE}\n")

            # The registry table decides when nothing is passed, exactly as
            # before: the Jev name is present in the file and absent from the
            # result, because it was never enrolled.
            self.assertEqual(env_key_names(home), ["GLM_API_KEY"])
            self.assertEqual(env_key_names(home, allowed=None), ["GLM_API_KEY"])
            # The same table decides the `environ` half of the scan, which the
            # posture never passes but every other caller may.
            self.assertEqual(
                env_key_names(home, environ={"ANTHROPIC_API_KEY": SECRET_VALUE, "TYPESAFE_API_KEY": SECRET_VALUE}),
                ["ANTHROPIC_API_KEY", "GLM_API_KEY"],
            )

    def test_the_allowed_parameter_scopes_both_scans(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "hermes"
            _write(home / ".env", f"GLM_API_KEY={SECRET_VALUE}\nTYPESAFE_API_KEY={SECRET_VALUE}\n")

            names = env_key_names(
                home,
                environ={"OPENROUTER_API_KEY": SECRET_VALUE, "PATH": "/bin"},
                allowed=JEV_CREDENTIAL_ENV_NAMES,
            )

            self.assertEqual(names, ["OPENROUTER_API_KEY", "TYPESAFE_API_KEY"])


class DoctorCheckTests(unittest.TestCase):
    def test_the_check_is_appended_on_a_machine_with_no_signal(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))

            checks, check = _doctor_check(paths)

            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "ok")
            self.assertTrue(check.message.startswith("optional: no Jev-class plugin installed | omh_jev_ask: "))
            self.assertEqual(check.detail["status"], "absent")
            self.assertEqual(doctor_ok(checks), doctor_ok(_without_jev(checks)))

    def test_omh_jev_ask_is_reported_in_the_same_check_from_names_only(self) -> None:
        # F8: one home. OMH's own tool rides the existing check; the key is a
        # planted sentinel and must never reach the message or the detail.
        sentinel = "sk-omh-jev-sentinel-9f8e7d6c5b4a"
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": sentinel, "TYPESAFE_BASE_URL": "https://gateway.example/v1"}):
                _checks, check = _doctor_check(paths)
            self.assertIn("route typesafe (custom base URL configured) by variable name", check.message)
            self.assertIn("no ask recorded", check.message)
            self.assertIn("HTTPS proxy", check.message)
            self.assertTrue(check.detail["omh_jev_ask"]["typesafe_base_url_configured"])
            self.assertNotIn(sentinel, check.message)
            self.assertNotIn(sentinel, json.dumps(check.detail))
            self.assertEqual(check.detail["omh_jev_ask"]["route_available"], "typesafe")
            self.assertEqual(check.detail["credential_names_present"], [])

    def test_an_openrouter_key_alone_is_not_an_omh_jev_ask_route(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            env = {"OPENROUTER_API_KEY": "or-key"}
            with patch.dict(os.environ, env):
                os.environ.pop("TYPESAFE_API_KEY", None)
                _checks, check = _doctor_check(paths)
                self.assertEqual(check.detail["omh_jev_ask"]["route_available"], "none")
                setting = paths.omh_home / "jev" / "settings.json"
                setting.parent.mkdir(parents=True, exist_ok=True)
                setting.write_text('{"openrouter_route": true}', encoding="utf-8")
                _checks, check = _doctor_check(paths)
                self.assertEqual(check.detail["omh_jev_ask"]["route_available"], "openrouter")

    def test_a_configured_plugin_with_no_overlap_stays_quiet(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _enable(paths, "jev")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "ok")
            self.assertIn("jev (enabled) declares jev_evaluate", check.message)
            self.assertIn("read from hermes-agent plugin-catalog/jev.yaml", check.message)

    def test_a_hook_overlap_warns_and_names_the_shared_hook(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(
                paths,
                "typesafe-skill-router",
                "name: typesafe-skill-router\nprovides_hooks:\n  - pre_llm_call\n",
            )
            _enable(paths, "typesafe-skill-router")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            checks, check = _doctor_check(paths)

            self.assertTrue(check.ok)
            self.assertEqual(check.severity, "warning")
            self.assertIn("shares with the OMH bridge the hooks pre_llm_call", check.message)
            self.assertIn("two nominations", check.message)
            self.assertIn("omh doctor --json", check.next_action)
            # A third-party plugin the operator installed is not an OMH
            # install failure and must not flip the exit code. The fixture
            # home has no OMH install, so the absolute verdict is not the
            # claim: the claim is that removing this check changes nothing.
            self.assertEqual(doctor_ok(checks), doctor_ok(_without_jev(checks)))

    def test_a_detected_plugin_without_a_credential_name_warns(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _enable(paths, "jev")

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "warning")
            self.assertEqual(check.detail["status"], "enabled")

    def test_an_unswept_directory_is_not_reported_as_absence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "broken", "name: broken\nrequires_hermes: >=0.21\n")

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "warning")
            self.assertNotIn("no Jev-class plugin installed", check.message)
            self.assertIn("1 entry under plugins/ not fully read: broken", check.message)

    def test_no_message_on_any_branch_carries_a_credential_value(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "hermes-jev", "name: hermes-jev\nprovides_hooks:\n  - pre_llm_call\n")
            _enable(paths, "hermes-jev")
            _write(paths.hermes_home / ".env", f"OPENROUTER_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertIn("OPENROUTER_API_KEY", check.message)
            self.assertNotIn(SECRET_VALUE, check.message)
            self.assertNotIn(SECRET_VALUE, json.dumps(check.detail))

    def test_the_next_action_states_no_branch_that_did_not_fire(self) -> None:
        # The three-sentence fixed string printed all three reasons on every
        # warning branch, so an operator whose credential name was right read
        # that it was missing and an operator whose sweep was complete read
        # about a directory OMH could not clear.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(
                paths,
                "typesafe-skill-router",
                "name: typesafe-skill-router\nprovides_hooks:\n  - pre_llm_call\n",
            )
            _enable(paths, "typesafe-skill-router")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertIn("declares the same hook OMH registers: pre_llm_call", check.next_action)
            self.assertNotIn("No name a Jev-class plugin declares as its route", check.next_action)
            self.assertNotIn("complete sweep", check.next_action)
            self.assertNotIn("did not read whether Hermes enables", check.next_action)
            self.assertNotIn("neither established nor ruled out", check.next_action)

    def test_the_next_action_describes_an_overlap_as_a_declaration(self) -> None:
        # `post_tool_call` is one of the eight hooks the bridge registers and
        # is not the nomination surface. The fixed string told the operator
        # this plugin "sends the model two nominations for one message",
        # which is a runtime claim OMH did not observe and is false for seven
        # of the eight hooks it fired on.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(
                paths,
                "weird",
                "name: weird\nprovides_tools:\n  - jev_stats\nprovides_hooks:\n  - post_tool_call\n",
            )
            _enable(paths, "weird")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertIn("weird declares the same hook OMH registers: post_tool_call", check.next_action)
            self.assertNotIn("two nominations", check.next_action)
            self.assertNotIn("sends the model", check.next_action)
            self.assertNotIn("cannot answer", check.next_action)

    def test_the_next_action_names_the_env_file_omh_read(self) -> None:
        # The hardcoded `~/.hermes/.env` named a file this verdict did not
        # come from on every machine running under `--hermes-home`.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _enable(paths, "jev")

            _checks, check = _doctor_check(paths)

            self.assertIn(str(paths.hermes_home / ".env"), check.next_action)
            self.assertNotIn("~/.hermes/.env", check.next_action)

    def test_the_next_action_reports_an_unread_sweep_and_nothing_else(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "broken", "name: broken\nrequires_hermes: >=0.21\n")

            _checks, check = _doctor_check(paths)

            self.assertIn("not a complete sweep", check.next_action)
            self.assertNotIn("No name a Jev-class plugin declares as its route", check.next_action)
            self.assertNotIn("declares the same hook", check.next_action)

    def test_the_next_action_names_the_enablement_read_that_did_not_happen(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _write(paths.hermes_config_path, "base: &plugins\n  enabled: [jev]\nplugins: *plugins\n")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertEqual(check.severity, "warning")
            self.assertIn("OMH did not read whether Hermes enables jev", check.next_action)
            self.assertIn("form OMH does not read", check.next_action)

    def test_every_unread_declaration_field_carries_its_own_clause(self) -> None:
        # The note table is keyed on a vocabulary another module owns. A
        # fourth field added there must cost one generic clause, not a
        # `KeyError` that takes the whole `omh doctor` command down -- and
        # every field that vocabulary declares today has a specific clause,
        # so the fallback stays unreached.
        for field in UNREADABLE_DECLARATION_FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, doctor_module._JEV_UNREAD_DECLARATION_NOTES)
        entry = {"name": "made-up", "unreadable_declarations": ["a_field_the_notes_do_not_hold"]}

        note = doctor_module._jev_plugin_note(entry)

        self.assertIn("declares a_field_the_notes_do_not_hold in a form OMH does not read", note)

    def test_the_message_says_a_quoted_disclosure_is_a_declaration(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            _install_plugin(paths, "jev-approvals", "name: jev-approvals\nprovides_hooks:\n")
            _enable(paths, "jev-approvals")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")

            _checks, check = _doctor_check(paths)

            self.assertIn("its catalog entry discloses", check.message)
            self.assertIn("is not evidence that Jev is served", check.message)

    def test_the_check_joins_optional_surfaces_and_no_other_group(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))

            summary = setup_commands._doctor_operator_summary(run_doctor(paths))

            groups = {group["name"]: group for group in summary["groups"]}
            self.assertIn("plugin_jev_sidekick", _group_member_names(paths, "optional_surfaces"))
            for name, group in groups.items():
                if name == "optional_surfaces":
                    continue
                self.assertNotIn("plugin_jev_sidekick", _group_member_names(paths, name), name)


def _group_member_names(paths: OmhPaths, group_name: str) -> list[str]:
    checks = [
        {"name": check.name, "ok": check.ok, "severity": check.severity} for check in run_doctor(paths)
    ]
    prefixes = {
        "command": ("command_path",),
        "managed_skills": (
            "manifest",
            "manifest_skills_dir",
            "local_modifications",
            "skill_freshness",
            "skills_dir",
            "skill:",
            "route_hint_skills",
            "guidance_projection",
        ),
        "runtime": ("runtime_artifacts", "workflow_state", "runtime_state"),
        "hermes_registration": ("hermes_config", "external_dir", "identity_conflicts", "runtime_context"),
        "targets": ("target_registry", "target_topology"),
        "model_routing": ("hermes_model_routing", "provider_entitlements"),
        "optional_surfaces": ("plugin_", "team_profile_packs", "structural_search", "trigger_language_packs"),
    }[group_name]
    return [
        str(check["name"]) for check in checks if any(str(check["name"]).startswith(prefix) for prefix in prefixes)
    ]


class DoctorJsonTests(unittest.TestCase):
    def test_the_posture_reaches_the_json_report_under_detail(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _installed_paths(Path(tmp))
            _install_plugin(paths, "jev", "name: jev\nprovides_tools:\n  - jev_evaluate\nprovides_hooks:\n")
            _enable(paths, "jev")
            _write(paths.hermes_home / ".env", f"TYPESAFE_API_KEY={SECRET_VALUE}\n")
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)

            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            check = {item["name"]: item for item in payload["checks"]}["plugin_jev_sidekick"]
            self.assertTrue(check["ok"])
            posture = check["detail"]
            self.assertEqual(posture["schema_version"], JEV_SIDEKICK_POSTURE_SCHEMA_VERSION)
            self.assertEqual(posture["status"], "credential_name_present")
            self.assertEqual(posture["plugins"][0]["name"], "jev")
            self.assertNotIn(SECRET_VALUE, stdout)

    def test_a_check_with_no_structured_finding_carries_none(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _installed_paths(Path(tmp))
            base = ["--omh-home", str(paths.omh_home), "--hermes-home", str(paths.hermes_home)]

            with patch("omh.command_path.shutil.which", return_value="/usr/local/bin/omh"):
                status, stdout, stderr = run_cli(base + ["doctor", "--json"], output_json=False)

            self.assertEqual(status, 0, stderr)
            checks = {item["name"]: item for item in json.loads(stdout)["checks"]}
            self.assertIsNone(checks["command_path"]["detail"])


if __name__ == "__main__":
    unittest.main()
