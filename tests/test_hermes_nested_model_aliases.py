"""Hermes' nested model alias form, as `parse_hermes_model_aliases` reads it.

Hermes writes an alias as a mapping (`hermes config set
model_aliases.<name>.model <model>` produces `<name>:` with `model:`,
`provider:`, `base_url:`, `key_env:` children), under the root `model_aliases`
key and under `model.aliases`. Before #2863 the parser read only the flat
`alias: target` form and reported every such config as corrupt. Both callers,
`omh coding model-routing status` and the setup profile pack, read through this
one parser.

A nested entry's target is its `model` child. Every other child is skipped
without being screened, because Hermes' own `key_env: SOME_API_KEY` fails the
opaque-reference screen, and its value is never kept. These tests pin both
halves: the skipped values never reach the output, and a credential-shaped
value cannot reach it either.

`POSITIVE_FIXTURES` stays a plain literal so a reviewer can load each fixture
with a real YAML loader and check the structure claimed here.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _credential_fixtures import AWS_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402

from omh.maintenance.advisory import parse_hermes_model_aliases  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.profiles.pack import build_setup_profile_pack  # noqa: E402
from omh.profiles.setup import write_setup_profile  # noqa: E402


# The repro from #2863, byte for byte.
ISSUE_2863_CONFIG = (
    "model:\n"
    '  default: "some-provider/some-model"\n'
    "  aliases:\n"
    "    mistral:\n"
    "      model: mistral-large-latest\n"
    "      provider: custom\n"
    "      base_url: https://api.mistral.ai/v1\n"
    "      key_env: SOME_API_KEY\n"
)

POSITIVE_FIXTURES: dict[str, tuple[str, dict[str, str]]] = {
    "issue_2863_model_dot_aliases": (
        ISSUE_2863_CONFIG,
        {"mistral": "mistral-large-latest"},
    ),
    "root_model_aliases": (
        "model_aliases:\n"
        "  mistral:\n"
        "    model: mistral-large-latest\n"
        "    provider: custom\n"
        "    base_url: https://api.mistral.ai/v1\n"
        "    key_env: SOME_API_KEY\n"
        "  qw:\n"
        "    model: qwen3:32b\n",
        {"mistral": "mistral-large-latest", "qw": "qwen3:32b"},
    ),
    # What `hermes config set` wrote when asked for both shapes in one home.
    "hermes_writer_mixed": (
        "model_aliases:\n"
        "  mistral:\n"
        "    model: mistral-large-latest\n"
        "    provider: custom\n"
        "model:\n"
        "  aliases:\n"
        "    fast:\n"
        "      model: glm-5.2\n"
        "    cheap: zai/glm-5.2\n",
        {"cheap": "zai/glm-5.2", "fast": "glm-5.2", "mistral": "mistral-large-latest"},
    ),
    "flat_between_nested": (
        "model:\n"
        "  aliases:\n"
        "    a:\n"
        "      provider: custom\n"
        "      model: m-a\n"
        "    b: vendor/m-b\n"
        "    c:\n"
        "      model: m-c\n"
        "  provider: custom\n",
        {"a": "m-a", "b": "vendor/m-b", "c": "m-c"},
    ),
    "four_space_indent": (
        "model:\n"
        "    default: x\n"
        "    aliases:\n"
        "        mistral:\n"
        "            model: mistral-large-latest\n"
        "            provider: custom\n"
        "        cheap: zai/glm-5.2\n"
        "telemetry:\n"
        "    enabled: false\n",
        {"cheap": "zai/glm-5.2", "mistral": "mistral-large-latest"},
    ),
    "quoted_values_and_comments": (
        "# Hermes config\n"
        "model_aliases:\n"
        "  # nested, quoted\n"
        "  'mistral':\n"
        '    model: "mistral-large-latest"\n'
        "    # a comment between children\n"
        "    provider: 'custom'\n"
        "\n"
        "  \"cheap\": 'zai/glm-5.2'\n",
        {"cheap": "zai/glm-5.2", "mistral": "mistral-large-latest"},
    ),
    "empty_aliases_block": (
        "model:\n"
        "  aliases:\n"
        "  default: some/model\n",
        {},
    ),
    "flat_form_unchanged": (
        "model:\n"
        "  aliases:\n"
        "    main: kimi-coding/kimi-k3.1-pro\n"
        "    cheap: zai/glm-5.2\n",
        {"cheap": "zai/glm-5.2", "main": "kimi-coding/kimi-k3.1-pro"},
    ),
}

_SK_SHAPED = "sk" + "-" + "abcdefghijklmnopqrstuvwx"


def _nested(children: str) -> str:
    return "model:\n  aliases:\n    mistral:\n" + children


class NestedModelAliasParserTests(unittest.TestCase):
    def test_every_positive_fixture_reads_its_targets(self) -> None:
        for name, (text, expected) in POSITIVE_FIXTURES.items():
            with self.subTest(fixture=name):
                self.assertEqual(parse_hermes_model_aliases(text), (expected, ""))

    def test_skipped_children_never_reach_the_output(self) -> None:
        aliases, error = parse_hermes_model_aliases(ISSUE_2863_CONFIG)
        self.assertEqual(error, "")
        rendered = json.dumps(aliases)
        for value in ("custom", "api.mistral.ai", "SOME_API_KEY", "provider", "base_url", "key_env"):
            self.assertNotIn(value, rendered)

    def test_a_credential_under_a_skipped_child_cannot_reach_the_output(self) -> None:
        for secret in (AWS_ACCESS_KEY_ID, _SK_SHAPED):
            with self.subTest(secret=secret[:4]):
                text = _nested(
                    "      model: mistral-large-latest\n"
                    f"      api_key: {secret}\n"
                    f"      key_env: '{secret}'\n"
                )
                aliases, error = parse_hermes_model_aliases(text)
                self.assertEqual((aliases, error), ({"mistral": "mistral-large-latest"}, ""))
                self.assertNotIn(secret, json.dumps([aliases, error]))

    def test_nested_entry_without_a_model_child_is_an_unsupported_shape(self) -> None:
        text = _nested("      provider: custom\n      base_url: https://api.mistral.ai/v1\n")
        self.assertEqual(parse_hermes_model_aliases(text), ({}, "model alias entry shape is unsupported"))
        # The same entry closed by a following sibling, not by end of input.
        text = _nested("      provider: custom\n") + "    cheap: zai/glm-5.2\n"
        self.assertEqual(parse_hermes_model_aliases(text), ({}, "model alias entry shape is unsupported"))
        # A repeated `aliases:` header closes the pending entry, so a later
        # `model:` line cannot be absorbed into it across the header.
        text = _nested("      provider: custom\n") + "  aliases:\n      model: absorbed\n"
        self.assertEqual(parse_hermes_model_aliases(text), ({}, "model alias entry shape is unsupported"))

    def test_an_alias_with_neither_value_nor_children_stays_malformed(self) -> None:
        text = "model:\n  aliases:\n    mistral:\n    cheap: zai/glm-5.2\n"
        self.assertEqual(parse_hermes_model_aliases(text), ({}, "model alias entry is malformed or unsafe"))

    def test_refusals_carry_a_fixed_message_and_no_value(self) -> None:
        cases = {
            "duplicate_model_child": _nested("      model: first-model\n      model: second-model\n"),
            "deeper_child": _nested("      model: mistral-large-latest\n        provider: custom\n"),
            "misaligned_child": _nested("        model: mistral-large-latest\n      provider: custom\n"),
            "nested_sub_block": _nested("      model: mistral-large-latest\n      extra:\n        k: v\n"),
            # A child key named `aliases` is not the alias block's header: its
            # sub-block is refused, never read as top-level aliases.
            "aliases_named_child": _nested(
                "      model: mistral-large-latest\n      aliases:\n        leaked: from-a-child\n"
            ),
            "unsafe_model_aws": _nested(f"      model: {AWS_ACCESS_KEY_ID}\n"),
            "unsafe_model_sk": "model_aliases:\n  mistral:\n" + f"    model: '{_SK_SHAPED}'\n",
            "unsafe_model_marker": _nested("      model: my-secret-model\n"),
            "empty_model_child": _nested("      model:\n      provider: custom\n"),
            "unsafe_alias_name": "model_aliases:\n  api_key:\n    model: mistral-large-latest\n",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                aliases, error = parse_hermes_model_aliases(text)
                self.assertEqual(aliases, {})
                self.assertEqual(error, "model alias entry is malformed or unsafe")
                for secret in (AWS_ACCESS_KEY_ID, _SK_SHAPED):
                    self.assertNotIn(secret, error)

    def test_a_child_without_a_colon_or_under_a_flat_entry_is_malformed(self) -> None:
        cases = {
            "child_without_colon": _nested("      model: mistral-large-latest\n      just-a-word\n"),
            "child_of_a_flat_entry": "model:\n  aliases:\n    cheap: zai/glm-5.2\n      model: other\n",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertEqual(parse_hermes_model_aliases(text), ({}, "model alias entry is malformed"))


class NestedModelAliasCallerTests(unittest.TestCase):
    def _paths(self, root: Path):
        paths = resolve_paths(root / ".omh", root / ".hermes")
        paths.hermes_config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.hermes_config_path.write_text(ISSUE_2863_CONFIG, encoding="utf-8")
        return paths

    def test_model_routing_status_reports_the_issue_config_as_configured(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", str(paths.omh_home),
                    "--hermes-home", str(paths.hermes_home),
                    "coding", "model-routing", "status",
                    "--discovery-home", str(root / "empty-home"),
                    "--json",
                ]
            )
        self.assertEqual(status, 0, stderr)
        hermes = json.loads(stdout)["hermes"]
        self.assertEqual(hermes["status"], "configured")
        self.assertEqual(hermes["aliases"], {"mistral": "mistral-large-latest"})
        self.assertNotIn("error", hermes)
        self.assertNotIn("SOME_API_KEY", stdout)

    def test_setup_profile_pack_carries_the_nested_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            write_setup_profile(paths, ["3"], default_executor="codex")
            pack = build_setup_profile_pack(paths)
        section = pack["model_aliases"]
        self.assertEqual(section["status"], "configured")
        self.assertEqual(section["aliases"], {"mistral": "mistral-large-latest"})
        self.assertNotIn("SOME_API_KEY", json.dumps(pack))


if __name__ == "__main__":
    unittest.main()
