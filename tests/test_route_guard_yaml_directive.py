"""A Hermes config that opens with `%YAML 1.1` or lists a root key's items at column 0 still routes (#2917).

Reported by @mazzy89: `omh_delegate_route` refused two valid configurations with `config_unreadable` before any
dispatch. Hermes' loaders (PyYAML at 0.21.x, ruamel in YAML 1.1 mode at 0.22 and later) read both:

    %YAML 1.1                       fallback_providers:
    ---                             - model: example
    delegation:                       provider: custom
      model: example                delegation:
                                      model: example

The guard's line scan (`route_endpoint_guard.scan_config`) took the directive and the column-0 `- ` lines for
top-level lines it could not read. It now reads one opening `%YAML 1.1` directive followed by `---`, and a block
sequence at column 0 under an empty root key it does not track. Everything that was refused for a reason stays
refused: a second directive, a directive with no `---`, `%YAML 1.2`, `%TAG`, a second document, a repeated key, a
column-0 sequence under `delegation`, `model` or a root model key, after a key that already has a value, or after
indented lines. Each positive case is also loaded with Hermes' own reader where it is installed, so these tests
fail if the scan accepts a file Hermes would not load.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from omh.plugin_bundle.omh import route_endpoint_guard as guard
from test_delegation_direct_endpoint import ENDPOINT, MODEL_BLOCK, GuardTestCase

DIRECTIVE = "%YAML 1.1\n---\n"
LIST_HEAD = "fallback_providers:\n- model: example\n  provider: custom\n"
HERMES_ROOT = Path(os.environ.get("OMH_TEST_HERMES_ROOT", Path.home() / ".hermes" / "hermes-agent"))
HERMES_PYTHON = HERMES_ROOT / "venv" / "bin" / "python"

# Each must route, and Hermes' loader must read it.
READABLE = {
    "directive": DIRECTIVE + MODEL_BLOCK,
    "directive with comments": "%YAML 1.1   # the version\n--- # doc\n" + MODEL_BLOCK,
    "directive after a comment line": "# my config\n" + DIRECTIVE + MODEL_BLOCK,
    "indentless list": LIST_HEAD + MODEL_BLOCK,
    "indentless list after the model": MODEL_BLOCK + LIST_HEAD,
    "directive and indentless list": DIRECTIVE + LIST_HEAD + MODEL_BLOCK,
    "indentless list of scalars": "toolsets:\n- web\n- terminal\n" + MODEL_BLOCK,
    "indentless item with nested map": "fallback_providers:\n- model: example\n  extra:\n    k: v\n" + MODEL_BLOCK,
    "indentless item naming a tracked key": "fallback_providers:\n- delegation: x\n- model: y\n" + MODEL_BLOCK,
    "bare dash item": "toolsets:\n-\n- web\n" + MODEL_BLOCK,
    "two indentless lists": "toolsets:\n- web\n" + LIST_HEAD + MODEL_BLOCK,
}

# Each must stay refused with `config_unreadable`; the comment names why.
UNREADABLE = {
    "two directives": "%YAML 1.1\n%YAML 1.1\n---\n" + MODEL_BLOCK,  # the loaders raise
    "directive without document start": "%YAML 1.1\n" + MODEL_BLOCK,  # the loaders raise
    "directive alone": "%YAML 1.1\n",
    "YAML 1.2 directive": "%YAML 1.2\n---\n" + MODEL_BLOCK,  # may resolve scalars differently
    "TAG directive": "%TAG ! tag:example.com,2000:\n---\n" + MODEL_BLOCK,
    "directive after document start": "---\n%YAML 1.1\n" + MODEL_BLOCK,  # the loaders raise
    "directive after a key": MODEL_BLOCK + "%YAML 1.1\n---\n",
    "second document": DIRECTIVE + MODEL_BLOCK + "---\nx: 1\n",  # one document only
    "indentless item after a scalar key": "foo: bar\n- x\n" + MODEL_BLOCK,  # the loaders raise
    "indentless item after indented lines": "foo:\n  a: 1\n- x\n" + MODEL_BLOCK,  # the loaders raise
    "indentless item after an indented list": "foo:\n  - a\n- b\n" + MODEL_BLOCK,  # the loaders raise
    "indentless item at the start": "- x\n" + MODEL_BLOCK,  # a sequence document, not a mapping
    "repeated key beside a list": LIST_HEAD + "fallback_providers:\n- x\n" + MODEL_BLOCK,
}


def hermes_reads(text: str) -> bool | None:
    """Whether Hermes' own `hermes_yaml.safe_load` loads `text` to a mapping; None when Hermes is not installed."""
    if not (HERMES_PYTHON.is_file() and (HERMES_ROOT / "hermes_yaml.py").is_file()):
        return None
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); import hermes_yaml as h\n"
        "try:\n    d = h.safe_load(sys.stdin.read())\nexcept Exception:\n    sys.exit(3)\n"
        "sys.exit(0 if isinstance(d, dict) else 4)\n"
    )
    done = subprocess.run([str(HERMES_PYTHON), "-I", "-c", script, str(HERMES_ROOT)], input=text, text=True,
                          capture_output=True, timeout=60, check=False)
    return done.returncode == 0


class ScanTest(unittest.TestCase):
    def test_the_reported_shapes_read_and_keep_their_sections(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                layer = guard.scan_config(text)
                self.assertFalse(layer.unreadable_top_level, name)
                self.assertEqual(layer.sections.get("model", {}).get("provider"), "openrouter")
                self.assertEqual(layer.unreadable_sections, set())

    def test_a_listed_root_key_reads_as_set_never_as_its_items(self) -> None:
        layer = guard.scan_config(LIST_HEAD + MODEL_BLOCK)
        self.assertIsNone(layer.root["fallback_providers"])
        self.assertNotIn("provider", layer.root)  # the item's `provider: custom` is not a root model key

    def test_the_shapes_that_stay_refused(self) -> None:
        for name, text in UNREADABLE.items():
            with self.subTest(shape=name):
                self.assertTrue(guard.scan_config(text).unreadable_top_level, name)

    def test_a_column_0_list_under_a_tracked_key_stays_unreadable(self) -> None:
        for text in ("delegation:\n- model: x\n" + MODEL_BLOCK, MODEL_BLOCK.replace("model:\n", "x: 1\n") + "model:\n- x\n",
                     "provider:\n- openrouter\n" + MODEL_BLOCK, "base_url:\n- " + ENDPOINT + "\n" + MODEL_BLOCK):
            with self.subTest(text=text):
                layer = guard.scan_config(text)
                self.assertTrue(layer.unreadable_top_level or layer.unreadable_sections, text)


@unittest.skipIf(hermes_reads("a: 1\n") is None, "Hermes is not installed here")
class HermesAgreesTest(unittest.TestCase):
    """The scan never reads a file Hermes' own loader refuses, and reads both reported shapes Hermes loads."""

    def test_every_readable_shape_loads_in_hermes(self) -> None:
        for name, text in READABLE.items():
            with self.subTest(shape=name):
                self.assertTrue(hermes_reads(text), name)

    def test_the_refused_shapes_hermes_rejects_are_refused(self) -> None:
        rejected = [name for name, text in UNREADABLE.items() if hermes_reads(text) is False]
        # At least the ones the module docstring names as loader failures.
        for name in ("two directives", "directive without document start", "second document",
                     "indentless item after a scalar key", "indentless item after indented lines"):
            self.assertIn(name, rejected)


class RouteTest(GuardTestCase):
    def test_both_reported_configs_route(self) -> None:
        for name in ("directive", "indentless list", "directive and indentless list"):
            with self.subTest(shape=name):
                self.config.write_text(READABLE[name], encoding="utf-8")
                self.assert_routed(self.set_route(), "anthropic")
                text = self.config.read_text(encoding="utf-8")
                # The written file keeps what the person wrote around the route.
                if "%YAML" in READABLE[name]:
                    self.assertTrue(text.startswith(DIRECTIVE), text)
                if "fallback_providers" in READABLE[name]:
                    self.assertIn(LIST_HEAD, text)
                if hermes_reads(text) is not None:
                    self.assertTrue(hermes_reads(text), text)

    def test_the_refused_shapes_still_refuse_and_write_nothing(self) -> None:
        for name in ("two directives", "YAML 1.2 directive", "indentless item after a scalar key", "second document"):
            with self.subTest(shape=name):
                self.config.write_text(UNREADABLE[name], encoding="utf-8")
                before = self.config.read_bytes()
                self.assert_refused(self.set_route(), before, "config_unreadable")

    def test_a_direct_endpoint_under_a_directive_is_still_found(self) -> None:
        before = self.write_config(f"  base_url: {ENDPOINT}\n", head=DIRECTIVE + LIST_HEAD + MODEL_BLOCK)
        self.assert_refused(self.set_route(), before, "direct_endpoint_overrides_provider", ["delegation.base_url"])


if __name__ == "__main__":
    unittest.main()
