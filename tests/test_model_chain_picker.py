"""The arrow-key chain picker behind bare `omh model-chains`.

Two layers, tested apart. The plugin bundle's `model_chain_picker` owns the
rules — which aliases the ring holds, how a head model or effort steps, how a
save composes the override document — and is what the Modern-TUI widget will
walk too, so its tests pin behaviour a widget must be able to rely on. The
command's picker only paints frames and reads key tokens through injected
seams, exactly like the theme picker, so navigation, cancel-writes-nothing,
NO_COLOR and width are driven here without a terminal. The command tests pin
the bare form's degrade to `show` off a terminal and the `omh model` alias.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli

from omh.catalogs.model_chain_table import CHAIN_SURFACE_PURPOSES, MODEL_DISPLAY_LABELS
from omh.coding.model_routing import REASONING_EFFORT_LADDER
from omh.commands.model_chain_picker import CURSOR_MARK, effort_bar, render_frame, run_picker
from omh.commands.theme_picker import (
    ESC,
    KEY_DEFAULT,
    KEY_DOWN,
    KEY_ENTER,
    KEY_LEFT,
    KEY_MINUS,
    KEY_NONE,
    KEY_PLUS,
    KEY_QUIT,
    KEY_RIGHT,
)
from omh.plugin_bundle.omh.hermes_delegation import (
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    alias_is_served,
)
from omh.plugin_bundle.omh.model_chain_picker import (
    PICKER_EFFORT_RING,
    PICKER_SCHEMA_VERSION,
    _EFFORT_LADDER,
    apply_picker_changes,
    chain_from_entries,
    compose_override_document,
    known_model_aliases,
    picker_rows,
    read_override_document,
    step_effort,
    step_head_model,
)
from _module_patch import patch_modules

OVERRIDE_QUICK = (("kimi-k3-ultrafast", "low"), ("glm-5.3", "low"))


def _omh_home(root: Path) -> Path:
    return root / ".omh"


def _write_overrides(root: Path, categories: dict[str, tuple[tuple[str, str], ...]]) -> None:
    path = _omh_home(root) / "routing" / "model-chains.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
        "categories": {
            name: [{"model": model, "reasoning_effort": effort} for model, effort in chain]
            for name, chain in categories.items()
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_entitlements(root: Path, providers: dict[str, str]) -> None:
    path = _omh_home(root) / "routing" / "providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
        "providers": providers,
        "subscription_clis": [],
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _payload(root: Path, *, labels: bool = True) -> dict[str, object]:
    # A Hermes home with nothing linked, so only what a test records counts.
    return picker_rows(
        _omh_home(root),
        hermes_home=root / ".hermes",
        labels=MODEL_DISPLAY_LABELS if labels else None,
        purposes=CHAIN_SURFACE_PURPOSES if labels else None,
    )


def _drive(payload, keys: list[str], *, use_color: bool = False, width: int = 120):
    """Run the picker over a scripted key sequence, returning (result, frames)."""
    remaining = list(keys)
    frames: list[str] = []

    def read_key() -> str:
        return remaining.pop(0) if remaining else KEY_QUIT

    result = run_picker(payload, read_key=read_key, write=frames.append, use_color=use_color, width=width)
    return result, frames


def _chains(payload) -> dict[str, tuple[tuple[str, str], ...]]:
    return {row["category"]: chain_from_entries(row["chain"]) for row in payload["categories"]}


class PickerModelTests(unittest.TestCase):
    """The bundle layer: rules a widget and the CLI both rely on."""

    def test_rows_cover_every_shipped_category_in_order_with_origins(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_overrides(root, {"quick": OVERRIDE_QUICK})
            payload = _payload(root)
        self.assertEqual(payload["schema_version"], PICKER_SCHEMA_VERSION)
        self.assertEqual(
            [row["category"] for row in payload["categories"]],
            list(HERMES_MIXTURE_CATEGORY_CHAINS),
        )
        by_name = {row["category"]: row for row in payload["categories"]}
        self.assertEqual(by_name["quick"]["origin"], "override")
        self.assertEqual(chain_from_entries(by_name["quick"]["chain"]), OVERRIDE_QUICK)
        self.assertEqual(
            chain_from_entries(by_name["quick"]["default_chain"]),
            HERMES_MIXTURE_CATEGORY_CHAINS["quick"],
        )
        self.assertEqual(by_name["deep"]["origin"], "default")
        self.assertEqual(by_name["deep"]["purpose"], CHAIN_SURFACE_PURPOSES["deep"])
        self.assertEqual(payload["efforts"], list(PICKER_EFFORT_RING))
        self.assertEqual(payload["document_status"], "applied")

    def test_a_none_store_binds_to_the_named_hermes_home_not_the_ambient_one(self) -> None:
        """Naming no store means the store `hermes_home` dispatches from.

        The widget spawns both scripts with no store named (#1679); the
        `hermes_home` argument is what binds it, not the `HERMES_HOME` the
        process happens to carry, and a binding refusal on the save path is
        a sentence in the reply rather than a traceback.
        """
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()

            def hermes_home(name: str) -> Path:
                home = root / name
                home.mkdir()
                store = (root / f"{name}-store").as_posix()
                (home / "config.yaml").write_text(
                    f"plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: {store}\n", encoding="utf-8"
                )
                return home

            named, ambient = hermes_home("named"), hermes_home("ambient")
            document = root / "named-store" / "routing" / "model-chains.json"
            with patch_modules({"hermes_constants": None}), patch.dict(
                os.environ, {"HERMES_HOME": str(ambient), "HOME": str(root), "USERPROFILE": str(root)}
            ):
                os.environ.pop("OMH_HOME", None)
                self.assertEqual(Path(picker_rows(None, hermes_home=named)["path"]), document)
                result = apply_picker_changes(
                    None, {"deep": [{"model": "kimi-k3", "reasoning_effort": "high"}]}, hermes_home=named
                )
                self.assertEqual(Path(result["path"]), document)
                self.assertTrue(document.exists())
                self.assertFalse((root / "ambient-store").exists())
                (named / "config.yaml").write_text(
                    "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: true\n", encoding="utf-8"
                )
                self.assertIn("not a path string", apply_picker_changes(None, {}, hermes_home=named)["error"])

    def test_rows_carry_the_stored_chain_not_the_entitlement_shaped_one(self) -> None:
        # `show` reorders a chain so served entries lead; the picker must not,
        # or a save would freeze that reordering into the override document.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_overrides(root, {"quick": (("gpt-6-astra", "low"), ("glm-5.3", "low"))})
            _write_entitlements(root, {"zai": "zai"})
            payload = _payload(root)
        quick = next(row for row in payload["categories"] if row["category"] == "quick")
        self.assertEqual(chain_from_entries(quick["chain"]), (("gpt-6-astra", "low"), ("glm-5.3", "low")))
        self.assertEqual([entry["served"] for entry in quick["chain"]], [False, True])

    def test_ring_names_only_what_chains_name_and_joins_override_members(self) -> None:
        shipped = {model for chain in HERMES_MIXTURE_CATEGORY_CHAINS.values() for model, _ in chain}
        self.assertEqual(set(known_model_aliases()), shipped)
        self.assertNotIn("kimi-k3-ultrafast", shipped)
        joined = known_model_aliases({"quick": OVERRIDE_QUICK})
        self.assertIn("kimi-k3-ultrafast", joined)
        self.assertEqual(joined, tuple(sorted(joined)))
        # Recognition-only and superseded aliases sit in the price table, not
        # in a shipped chain, and must not be offered as a step.
        self.assertNotIn("claude-mythos-5-1", joined)

    def test_ring_puts_served_aliases_first_and_marks_unserved(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_entitlements(root, {"zai": "zai"})
            payload = _payload(root)
            entitlements = {"providers": {"zai": "zai"}, "subscription_clis": []}
            self.assertFalse(alias_is_served("gpt-6-astra", entitlements))
            self.assertTrue(alias_is_served("glm-5.3", entitlements))
        served_flags = [row["served"] for row in payload["models"]]
        self.assertIn(False, served_flags)
        self.assertEqual(served_flags, sorted(served_flags, reverse=True))
        served_aliases = [row["alias"] for row in payload["models"] if row["served"]]
        self.assertEqual(served_aliases, sorted(served_aliases))
        self.assertIn("glm-5.3", served_aliases)
        self.assertNotIn("gpt-6-astra", served_aliases)

    def test_without_entitlements_everything_is_served(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = _payload(Path(tmp))
        self.assertTrue(all(row["served"] for row in payload["models"]))
        self.assertTrue(all(entry["served"] for row in payload["categories"] for entry in row["chain"]))

    def test_labels_fall_back_to_the_alias_without_a_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            bare = _payload(Path(tmp), labels=False)
            labelled = _payload(Path(tmp))
        self.assertTrue(all(row["label"] == row["alias"] for row in bare["models"]))
        self.assertTrue(all(row["purpose"] == "" for row in bare["categories"]))
        astra = next(row for row in labelled["models"] if row["alias"] == "gpt-6-astra")
        self.assertEqual(astra["label"], MODEL_DISPLAY_LABELS["gpt-6-astra"])

    def test_effort_ladder_mirrors_model_routing(self) -> None:
        # The bundle cannot import src/coding, so it carries a copy; this is
        # the one place the copy is held to the original.
        self.assertEqual(_EFFORT_LADDER, REASONING_EFFORT_LADDER)
        self.assertEqual(PICKER_EFFORT_RING, tuple(r for r in REASONING_EFFORT_LADDER if r in PICKER_EFFORT_RING))

    def test_step_head_model_wraps_and_dedupes_the_tail(self) -> None:
        ring = ("a", "b", "c")
        chain = (("b", "high"), ("c", "low"), ("a", ""))
        self.assertEqual(step_head_model(chain, ring, 1), (("c", "high"), ("a", "")))
        self.assertEqual(step_head_model(chain, ring, -1), (("a", "high"), ("c", "low")))
        self.assertEqual(step_head_model((("c", "x"),), ring, 1), (("a", "x"),))
        self.assertEqual(step_head_model((("a", "x"),), ring, -1), (("c", "x"),))

    def test_step_head_model_enters_the_ring_from_a_custom_head(self) -> None:
        ring = ("a", "b", "c")
        self.assertEqual(step_head_model((("custom", "high"),), ring, 1), (("a", "high"),))
        self.assertEqual(step_head_model((("custom", "high"),), ring, -1), (("c", "high"),))
        self.assertEqual(step_head_model((), ring, 1), ())
        self.assertEqual(step_head_model((("a", ""),), (), 1), (("a", ""),))

    def test_step_effort_clamps_and_enters_the_ring(self) -> None:
        tail = (("t", "low"),)
        self.assertEqual(step_effort((("m", "medium"),) + tail, 1), (("m", "high"),) + tail)
        self.assertEqual(step_effort((("m", "medium"),) + tail, -1), (("m", "low"),) + tail)
        self.assertEqual(step_effort((("m", "low"),), -1), (("m", "low"),))
        self.assertEqual(step_effort((("m", "xhigh"),), 1), (("m", "xhigh"),))
        self.assertEqual(step_effort((("m", ""),), 1), (("m", "low"),))
        self.assertEqual(step_effort((("m", ""),), -1), (("m", "low"),))
        self.assertEqual(step_effort((("m", "minimal"),), 1), (("m", "low"),))
        self.assertEqual(step_effort((("m", "max"),), 1), (("m", "max"),))
        self.assertEqual(step_effort((("m", "max"),), -1), (("m", "xhigh"),))
        self.assertEqual(step_effort((), 1), ())

    def test_compose_clears_a_default_and_preserves_untouched_overrides(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_overrides(root, {"quick": OVERRIDE_QUICK, "writing": (("qwen3-coder", "high"),)})
            document = read_override_document(_omh_home(root))
        composed = compose_override_document(
            document,
            {
                "quick": HERMES_MIXTURE_CATEGORY_CHAINS["quick"],
                "deep": (("gpt-6-astra", "high"),),
            },
        )
        self.assertEqual(set(composed["categories"]), {"writing", "deep"})
        self.assertEqual(composed["categories"]["deep"], [{"model": "gpt-6-astra", "reasoning_effort": "high"}])
        self.assertEqual(composed["categories"]["writing"], document["categories"]["writing"])
        # The input document is left alone: a caller that then cancels has
        # nothing to undo.
        self.assertEqual(set(document["categories"]), {"quick", "writing"})
        self.assertEqual(composed["schema_version"], MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION)

    def test_compose_refuses_unknown_categories_and_invalid_chains(self) -> None:
        with self.assertRaises(ValueError):
            compose_override_document({"categories": {}}, {"nope": (("a", ""),)})
        with self.assertRaises(ValueError):
            compose_override_document({"categories": {}}, {"quick": (("not a token", ""),)})

    def test_read_override_document_yields_the_empty_document_for_anything_unreadable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty = read_override_document(_omh_home(root))
            self.assertEqual(empty, {"schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION, "categories": {}})
            path = _omh_home(root) / "routing" / "model-chains.json"
            path.parent.mkdir(parents=True)
            path.write_text("{", encoding="utf-8")
            self.assertEqual(read_override_document(_omh_home(root)), empty)


class PickerNavigationTests(unittest.TestCase):
    """The command layer, driven through its key and frame seams."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_right_and_plus_edit_the_cursor_row_only(self) -> None:
        payload = _payload(self.root)
        original = _chains(payload)
        ring = tuple(row["alias"] for row in payload["models"])
        result, frames = _drive(payload, [KEY_DOWN, KEY_RIGHT, KEY_PLUS, KEY_ENTER])
        deep = step_effort(step_head_model(original["deep"], ring, 1), 1)
        self.assertEqual(result, {"deep": deep})
        # One frame per accepted key: initial, then down, right, plus.
        self.assertEqual(len(frames), 4)
        self.assertIn(f" {CURSOR_MARK} deep ", frames[-1])
        self.assertIn("● edited", frames[-1])
        self.assertIn("1 unsaved change ·", frames[-1])

    def test_left_and_minus_step_the_other_way_and_wrap_the_cursor(self) -> None:
        payload = _payload(self.root)
        original = _chains(payload)
        ring = tuple(row["alias"] for row in payload["models"])
        last = payload["categories"][-1]["category"]
        result, _ = _drive(payload, [KEY_NONE, KEY_LEFT, KEY_MINUS, KEY_ENTER])
        first = payload["categories"][0]["category"]
        self.assertEqual(result, {first: step_effort(step_head_model(original[first], ring, -1), -1)})
        result, frames = _drive(payload, [KEY_LEFT, KEY_LEFT, KEY_ENTER])
        self.assertNotEqual(result, {})
        result, frames = _drive(payload, ["up", KEY_ENTER])
        self.assertEqual(result, {})
        self.assertIn(f" {CURSOR_MARK} {last} ", frames[-1])

    def test_default_key_on_an_override_row_is_a_change_that_clears_it(self) -> None:
        _write_overrides(self.root, {"quick": OVERRIDE_QUICK})
        payload = _payload(self.root)
        quick_index = [row["category"] for row in payload["categories"]].index("quick")
        result, frames = _drive(payload, [KEY_DOWN] * quick_index + [KEY_DEFAULT, KEY_ENTER])
        self.assertEqual(result, {"quick": HERMES_MIXTURE_CATEGORY_CHAINS["quick"]})
        self.assertIn("◆ override", frames[0])
        self.assertIn("● edited", frames[-1])
        composed = compose_override_document(read_override_document(_omh_home(self.root)), result)
        self.assertEqual(composed["categories"], {})

    def test_default_key_on_a_default_row_changes_nothing(self) -> None:
        payload = _payload(self.root)
        result, frames = _drive(payload, [KEY_DEFAULT, KEY_ENTER])
        self.assertEqual(result, {})
        self.assertIn("no unsaved changes", frames[-1])

    def test_cancel_returns_none_even_after_edits(self) -> None:
        payload = _payload(self.root)
        for cancel in ([KEY_RIGHT, KEY_PLUS, KEY_QUIT], [KEY_RIGHT]):
            with self.subTest(keys=cancel):
                result, frames = _drive(payload, cancel)
                self.assertIsNone(result)
                self.assertIn("edited", frames[-1])
        self.assertIsNone(run_picker({"categories": [], "models": []}, read_key=lambda: KEY_ENTER, write=lambda _: None, use_color=False))

    def test_frames_carry_no_escape_bytes_without_color_and_cut_to_width(self) -> None:
        payload = _payload(self.root)
        _, frames = _drive(payload, [KEY_ENTER], width=60)
        self.assertNotIn(ESC, frames[0])
        for line in frames[0].splitlines():
            self.assertLessEqual(len(line), 60, line)
        # The purpose column is the first thing to go on a narrow terminal;
        # a wide one keeps it.
        self.assertNotIn("PURPOSE", frames[0])
        _, wide = _drive(payload, [KEY_ENTER], width=120)
        self.assertIn("PURPOSE", wide[0])
        self.assertTrue(all(len(line) <= 120 for line in wide[0].splitlines()))
        _, frames = _drive(payload, [KEY_DOWN, KEY_ENTER], use_color=True)
        self.assertIn(ESC, frames[0])
        # Exactly one row sits on the selection background -- the cursor row
        # -- and every category is present.
        self.assertEqual(sum("48;2;" in line for line in frames[0].splitlines()), 1)
        for row in payload["categories"]:
            self.assertIn(row["category"], frames[0])

    def test_a_frame_never_wraps_the_override_path(self) -> None:
        # The regression this exists for: a wrapped path line put the
        # cursor-up repaint off by one row and drew the header twice.
        payload = _payload(self.root)
        payload["path"] = "/" + "deep/" * 60 + "model-chains.json"
        for use_color in (False, True):
            lines = render_frame(payload, _chains(payload), 0, use_color=use_color, width=100)
            visible = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
            self.assertTrue(all(len(line) <= 100 for line in visible), max(visible, key=len))
            self.assertIn("…", visible[0])

    def test_the_frame_shows_labels_effort_bar_chain_and_default_for_the_cursor_row(self) -> None:
        _write_overrides(self.root, {"ultrabrain": (("claude-fable-5-1", "medium"), ("gpt-6-astra", "xhigh"))})
        payload = _payload(self.root)
        chains = _chains(payload)
        lines = render_frame(payload, chains, 0, use_color=False, width=200)
        row = next(line for line in lines if " ultrabrain " in line)
        self.assertTrue(row.startswith(f" {CURSOR_MARK} "))
        self.assertIn(f"◂ {MODEL_DISPLAY_LABELS['claude-fable-5-1']} ▸", row)
        self.assertIn(f"− {effort_bar('medium')} + medium", row)
        self.assertTrue(row.rstrip().endswith("◆ override"))
        self.assertIn("   chain             claude-fable-5-1:medium, gpt-6-astra:xhigh", lines)
        self.assertIn(
            f"   shipped default   {', '.join(m + ':' + e for m, e in HERMES_MIXTURE_CATEGORY_CHAINS['ultrabrain'])}",
            lines,
        )
        self.assertTrue(lines[0].startswith(" ⚚ OMH · Model chains"))
        self.assertEqual(lines[1], "   providers  none linked to Hermes yet · every model counts as served")
        self.assertIn("CATEGORY", lines[3])
        self.assertIn("↑↓ category   ←→ head model   −/+ effort   d default   ⏎ save   q cancel", lines[-1])
        self.assertEqual(effort_bar("low"), "■□□□")
        self.assertEqual(effort_bar("xhigh"), "■■■■")
        self.assertEqual(effort_bar("max"), "■■■■")
        self.assertEqual(effort_bar(""), "□□□□")

    def test_the_providers_line_names_every_counted_provider_and_where_it_was_found(self) -> None:
        _write_entitlements(self.root, {"zai": "zai"})
        hermes_home = self.root / ".hermes"
        hermes_home.mkdir(parents=True, exist_ok=True)
        (hermes_home / "auth.json").write_text(
            json.dumps({"version": 1, "providers": {"openai-codex": {"access_token": "tok-secret-value"}}}), encoding="utf-8"
        )
        (hermes_home / "config.yaml").write_text("providers:\n  og:\n    base_url: x\n", encoding="utf-8")
        payload = _payload(self.root)
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertEqual(lines[1], "   providers  zai (recorded) · openai-codex (login) · og (config)")
        self.assertNotIn("tok-secret-value", "\n".join(lines))
        # Nothing is unserved once a gateway is linked: no `!` anywhere.
        self.assertFalse(any(" !" in line for line in lines))
        # The line is cut like every other free-text line, never wrapped.
        narrow = render_frame(payload, _chains(payload), 0, use_color=False, width=60)
        self.assertLessEqual(len(narrow[1]), 60)
        self.assertTrue(narrow[1].endswith("…"), narrow[1])

    def test_an_ignored_record_is_said_once_under_the_providers_line(self) -> None:
        """An invalid providers.json drops its kinds and its exclusions silently.

        The providers line then shows the linked rows as if the operator had
        never corrected them, so the frame says the record is ignored and
        why; a valid or absent record adds no row and the layout is the one
        every other frame test pins.
        """
        hermes_home = self.root / ".hermes"
        hermes_home.mkdir(parents=True, exist_ok=True)
        (hermes_home / "config.yaml").write_text("providers:\n  og:\n    base_url: x\n", encoding="utf-8")
        record = _omh_home(self.root) / "routing" / "providers.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text("{", encoding="utf-8")
        payload = _payload(self.root)
        self.assertEqual(payload["entitlements_status"], "invalid: unreadable JSON")
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertEqual(lines[1], "   providers  og (config)")
        self.assertEqual(lines[2], "   ! providers.json ignored: unreadable JSON · any providers it excluded count again")
        self.assertIn("CATEGORY", lines[4])
        self.assertEqual(sum("providers.json ignored" in line for line in lines), 1)
        narrow = render_frame(payload, _chains(payload), 0, use_color=False, width=60)
        self.assertLessEqual(len(narrow[2]), 60)
        # A valid record restores the plain layout: header on the fourth line.
        _write_entitlements(self.root, {"og": "gateway"})
        payload = _payload(self.root)
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertFalse(any("providers.json ignored" in line for line in lines))
        self.assertIn("CATEGORY", lines[3])

    def test_an_ignored_document_is_said_once_under_the_providers_line(self) -> None:
        """An override file the reader rejects is ignored whole, so every row
        reads `default` -- the exact picture of a chain that was never set,
        which is how a person who just set one reads it. The frame says the
        file is there and why it is not in effect; a valid or absent document
        adds no row and the layout is the one every other frame test pins.
        """
        document = _omh_home(self.root) / "routing" / "model-chains.json"
        document.parent.mkdir(parents=True, exist_ok=True)
        document.write_text("{", encoding="utf-8")
        payload = _payload(self.root)
        self.assertEqual(payload["document_status"], "invalid: unreadable JSON")
        self.assertTrue(all(row["origin"] == "default" for row in payload["categories"]))
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertEqual(lines[2], "   ! model-chains.json ignored: unreadable JSON · every category shows its shipped default")
        self.assertIn("CATEGORY", lines[4])
        self.assertEqual(sum("model-chains.json ignored" in line for line in lines), 1)
        narrow = render_frame(payload, _chains(payload), 0, use_color=False, width=60)
        self.assertLessEqual(len(narrow[2]), 60)
        # Both files ignored: one row each, providers first, header two lower.
        record = _omh_home(self.root) / "routing" / "providers.json"
        record.write_text("{", encoding="utf-8")
        payload = _payload(self.root)
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertIn("providers.json ignored", lines[2])
        self.assertIn("model-chains.json ignored", lines[3])
        self.assertIn("CATEGORY", lines[5])
        # A valid document and record restore the plain layout.
        record.unlink()
        _write_overrides(self.root, {"deep": (("kimi-k3", "high"),)})
        payload = _payload(self.root)
        self.assertEqual(payload["document_status"], "applied")
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        self.assertFalse(any("ignored" in line for line in lines))
        self.assertIn("CATEGORY", lines[3])

    def test_an_unserved_head_is_marked_on_its_row_and_explained_once(self) -> None:
        _write_entitlements(self.root, {"zai": "zai"})
        payload = _payload(self.root)
        lines = render_frame(payload, _chains(payload), 0, use_color=False, width=200)
        ultrabrain = next(line for line in lines if " ultrabrain " in line)
        self.assertEqual(payload["categories"][0]["chain"][0]["model"], "gpt-6-astra")
        self.assertIn(f"◂ {MODEL_DISPLAY_LABELS['gpt-6-astra']} ! ▸", ultrabrain)
        self.assertEqual(sum("is not served by this machine's providers" in line for line in lines), 1)
        # Off the cursor the mark stays on the row and the explanation goes
        # (row 4, unspecified-low, heads with GLM, which zai does serve).
        lines = render_frame(payload, _chains(payload), 4, use_color=False, width=200)
        self.assertIn(f"  {MODEL_DISPLAY_LABELS['gpt-6-astra']} !", next(line for line in lines if " ultrabrain " in line))
        self.assertEqual(sum("is not served by" in line for line in lines), 0)


class PickerCommandTests(unittest.TestCase):
    def test_bare_form_off_a_terminal_prints_show(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            status, stdout, stderr = run_cli(["--omh-home", str(_omh_home(root)), "model-chains"], output_json=False)
            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertIn("Current model chains", stdout)
            status, stdout, _ = run_cli(["--omh-home", str(_omh_home(root)), "model-chains", "--json"], output_json=False)
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(stdout)["schema_version"], "model_chain_state/v1")
            self.assertFalse((_omh_home(root) / "routing" / "model-chains.json").exists())

    def test_model_alias_reaches_the_same_command(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(_omh_home(Path(tmp)))]
            status, stdout, stderr = run_cli(base + ["model", "show"], output_json=False)
            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertIn("Current model chains", stdout)
            status, stdout, _ = run_cli(base + ["model", "set", "quick", "glm-5.3:low"], output_json=False)
            self.assertEqual(status, 0, stdout)
            self.assertIn("quick: glm-5.3:low (override)", stdout)

    def test_bare_form_writes_what_the_picker_returns_through_the_set_path(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_overrides(root, {"writing": (("qwen3-coder", "high"),)})
            changes = {"quick": OVERRIDE_QUICK, "writing": HERMES_MIXTURE_CATEGORY_CHAINS["writing"]}
            with (
                patch("omh.commands.model_chains.picker_available", return_value=True),
                patch("omh.commands.model_chains.pick_chains_interactively", return_value=changes) as picker,
            ):
                status, stdout, stderr = run_cli(["--omh-home", str(_omh_home(root)), "model-chains"], output_json=False)
            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertIn("Saved 2 categories to", stdout)
            self.assertIn("quick: kimi-k3-ultrafast:low, glm-5.3:low (override)", stdout)
            payload = picker.call_args.args[0]
            self.assertEqual(payload["schema_version"], PICKER_SCHEMA_VERSION)
            self.assertEqual(payload["categories"][0]["purpose"], CHAIN_SURFACE_PURPOSES["ultrabrain"])
            document = json.loads((_omh_home(root) / "routing" / "model-chains.json").read_text(encoding="utf-8"))
            self.assertEqual(set(document["categories"]), {"quick"})

    def test_cancelled_and_unchanged_pickers_leave_the_file_absent(self) -> None:
        for outcome, message in ((None, "Cancelled;"), ({}, "No changes.")):
            with self.subTest(outcome=outcome), TemporaryDirectory() as tmp:
                root = Path(tmp)
                with (
                    patch("omh.commands.model_chains.picker_available", return_value=True),
                    patch("omh.commands.model_chains.pick_chains_interactively", return_value=outcome),
                ):
                    status, stdout, stderr = run_cli(["--omh-home", str(_omh_home(root)), "model"], output_json=False)
                self.assertEqual((status, stderr), (0, ""), stdout)
                self.assertIn(message, stdout)
                self.assertFalse((_omh_home(root) / "routing" / "model-chains.json").exists())


if __name__ == "__main__":
    unittest.main()
