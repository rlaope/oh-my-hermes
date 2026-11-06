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
from omh.coding.model_contracts import contract_effort_option
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
    EFFORT_VOCABULARY,
    MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
    PICKER_SCHEMA_VERSION,
    PickerChanges,
    apply_picker_changes,
    chain_from_entries,
    compose_override_document,
    effort_option_resolver,
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


def _write_identities(root: Path, identities: dict[str, dict[str, object]]) -> None:
    path = _omh_home(root) / "routing" / "identities.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "omh_identity_profiles/v1", "identities": identities}),
        encoding="utf-8",
    )


def _write_efforts(root: Path, models: dict[str, list[str]]) -> None:
    path = _omh_home(root) / "routing" / "model-efforts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
                "models": {name: {"efforts": efforts} for name, efforts in models.items()},
            }
        ),
        encoding="utf-8",
    )


def _payload(root: Path, *, labels: bool = True) -> dict[str, object]:
    # A Hermes home with nothing linked, so only what a test records counts.
    store = _omh_home(root)
    effort_options, effort_status = effort_option_resolver(store, contract_option=contract_effort_option)
    return picker_rows(
        store,
        hermes_home=root / ".hermes",
        labels=MODEL_DISPLAY_LABELS if labels else None,
        purposes=CHAIN_SURFACE_PURPOSES if labels else None,
        effort_options=effort_options,
        effort_status=effort_status,
    )


def _row_index(payload, name: str) -> int:
    return [row["category"] for row in payload["categories"]].index(name)


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
        self.assertEqual(payload["effort_vocabulary"], list(EFFORT_VOCABULARY))
        self.assertEqual(payload["document_status"], "applied")
        by_alias = {row["alias"]: row for row in payload["models"]}
        self.assertEqual(
            by_alias["gpt-6-astra"]["efforts"],
            ["low", "medium", "high", "xhigh", "max"],
        )
        self.assertIsNone(by_alias["glm-5.3"]["efforts"])
        self.assertFalse(by_alias["glm-5.3"]["efforts_configured"])



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
                effort_options, _status = effort_option_resolver(document.parent.parent, contract_option=contract_effort_option)
                result = apply_picker_changes(
                    None,
                    {"deep": [{"model": "kimi-k3", "reasoning_effort": "high"}]},
                    hermes_home=named,
                    effort_options=effort_options,
                )
                self.assertEqual(Path(result["path"]), document)
                self.assertTrue(document.exists())
                self.assertFalse((root / "ambient-store").exists())
                (named / "config.yaml").write_text(
                    "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: true\n", encoding="utf-8"
                )
                self.assertIn(
                    "not a path string",
                    apply_picker_changes(None, {}, hermes_home=named, effort_options=lambda alias: None)["error"],
                )

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

    def test_effort_vocabulary_mirrors_model_routing_with_none_for_off(self) -> None:
        # The bundle cannot import src/coding, so it carries the vocabulary;
        # this is the one place the copy is held to the original. `off` is
        # the old OMH spelling and Hermes spells the same no-thinking rung
        # `none`, so the picker's vocabulary carries `none` in its slot.
        self.assertEqual(
            EFFORT_VOCABULARY,
            tuple("none" if rung == "off" else rung for rung in REASONING_EFFORT_LADDER),
        )

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

    def test_step_effort_clamps_inside_the_model_ladder(self) -> None:
        tail = (("t", "low"),)
        haiku = ("none", "low", "medium", "high", "xhigh", "max")
        self.assertEqual(step_effort((("m", "xhigh"),) + tail, 1, haiku), (("m", "max"),) + tail)
        self.assertEqual(step_effort((("m", "low"),), -1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((("m", "none"),), -1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((("m", "none"),), 1, haiku), (("m", "low"),))
        self.assertEqual(step_effort((("m", "max"),), 1, haiku), (("m", "max"),))
        self.assertEqual(step_effort((("m", "max"),), -1, haiku), (("m", "xhigh"),))
        self.assertEqual(step_effort((("m", ""),), 1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((("m", "auto"),), 1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((), 1, haiku), ())
        # An empty or absent ladder refuses to move: that is the unconfigured
        # model and the explicit no-knob case, not a fallback ring.
        self.assertEqual(step_effort((("m", "low"),), 1, ()), (("m", "low"),))
        self.assertEqual(step_effort((("m", "low"),), 1, None), (("m", "low"),))

    def test_step_effort_lands_mapping_aliases_on_the_next_real_rung(self) -> None:
        # DeepSeek's documented table maps medium/xhigh to high; they are not
        # independent ladder rungs, so the first +/- moves to a real rung.
        deepseek = ("none", "low", "high", "max")
        self.assertEqual(step_effort((("d", "low"),), 1, deepseek), (("d", "high"),))
        self.assertEqual(step_effort((("d", "high"),), 1, deepseek), (("d", "max"),))
        self.assertEqual(step_effort((("d", "medium"),), 1, deepseek), (("d", "high"),))
        self.assertEqual(step_effort((("d", "medium"),), -1, deepseek), (("d", "low"),))
        self.assertEqual(step_effort((("d", "xhigh"),), 1, deepseek), (("d", "max"),))
        self.assertEqual(step_effort((("d", "xhigh"),), -1, deepseek), (("d", "high"),))
        kimi = ("low", "high", "max")
        self.assertEqual(step_effort((("k", "medium"),), 1, kimi), (("k", "high"),))
        self.assertEqual(step_effort((("k", "medium"),), -1, kimi), (("k", "low"),))

    def test_step_effort_reads_old_off_as_none_and_writes_the_hermes_spelling(self) -> None:
        haiku = ("none", "low", "high")
        self.assertEqual(step_effort((("m", "off"),), 1, haiku), (("m", "low"),))
        self.assertEqual(step_effort((("m", "off"),), -1, haiku), (("m", "none"),))
        no_disable = ("low", "high")
        self.assertEqual(step_effort((("m", "off"),), 1, no_disable), (("m", "low"),))
        self.assertEqual(step_effort((("m", "off"),), -1, no_disable), (("m", "low"),))

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
        efforts = {
            row["alias"]: tuple(row["efforts"]) if row["efforts"] is not None else None
            for row in payload["models"]
        }
        result, frames = _drive(payload, [KEY_DOWN, KEY_RIGHT, KEY_PLUS, KEY_ENTER])
        moved = step_head_model(original["deep"], ring, 1)
        deep = step_effort(moved, 1, efforts.get(moved[0][0]))
        self.assertEqual(result, {"deep": deep})
        # One frame per accepted key: initial, then down, right, plus.
        self.assertEqual(len(frames), 4)
        self.assertIn(f" {CURSOR_MARK} deep ", frames[-1])
        self.assertIn("● edited", frames[-1])
        self.assertIn("1 unsaved change ·", frames[-1])

    def test_left_and_minus_step_the_other_way_and_the_cursor_stops_at_the_ends(self) -> None:
        payload = _payload(self.root)
        original = _chains(payload)
        ring = tuple(row["alias"] for row in payload["models"])
        efforts = {
            row["alias"]: tuple(row["efforts"]) if row["efforts"] is not None else None
            for row in payload["models"]
        }
        last = payload["categories"][-1]["category"]
        result, _ = _drive(payload, [KEY_NONE, KEY_LEFT, KEY_MINUS, KEY_ENTER])
        first = payload["categories"][0]["category"]
        moved = step_head_model(original[first], ring, -1)
        expected = step_effort(moved, -1, efforts.get(moved[0][0]))
        self.assertEqual(result, {first: expected})
        result, frames = _drive(payload, [KEY_LEFT, KEY_LEFT, KEY_ENTER])
        self.assertNotEqual(result, {})
        result, frames = _drive(payload, ["up", KEY_ENTER])
        self.assertEqual(result, {})
        self.assertIn(f" {CURSOR_MARK} {first} ", frames[-1])  # up on the first row stays there
        rows = len(payload["categories"])
        _result, frames = _drive(payload, [KEY_DOWN] * (rows + 2) + [KEY_ENTER])
        self.assertIn(f" {CURSOR_MARK} {last} ", frames[-1])  # down past the last row stays on it

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
        _write_overrides(self.root, {"ultrabrain": (("claude-opus-5-5", "medium"), ("gpt-6-astra", "xhigh"))})
        payload = _payload(self.root)
        chains = _chains(payload)
        lines = render_frame(payload, chains, 0, use_color=False, width=200)
        row = next(line for line in lines if " ultrabrain " in line)
        opus = ("low", "medium", "high", "xhigh", "max")
        self.assertTrue(row.startswith(f" {CURSOR_MARK} "))
        self.assertIn(f"◂ {MODEL_DISPLAY_LABELS['claude-opus-5-5']} ▸", row)
        self.assertIn(f"− {effort_bar('medium', opus):<8} +", row)
        self.assertIn("medium", row)
        self.assertTrue(row.rstrip().endswith("◆ override"))
        self.assertIn("   chain             claude-opus-5-5:medium, gpt-6-astra:xhigh", lines)
        self.assertIn(
            f"   shipped default   {', '.join(m + ':' + e for m, e in HERMES_MIXTURE_CATEGORY_CHAINS['ultrabrain'])}",
            lines,
        )
        self.assertIn("   effort            low, medium, high, xhigh, max  (contract)", lines)
        self.assertTrue(lines[0].startswith(" ⚚ OMH · Model chains"))
        self.assertEqual(lines[1], "   providers  none linked to Hermes yet · every model counts as served")
        self.assertIn("CATEGORY", lines[3])
        self.assertIn("↑↓ category   ←→ head model   −/+ effort   d default   ⏎ save   esc cancel", lines[-1])
        self.assertEqual(effort_bar("low", opus), "■□□□□")
        self.assertEqual(effort_bar("xhigh", opus), "■■■■□")
        self.assertEqual(effort_bar("max", opus), "■■■■■")
        self.assertEqual(effort_bar("", opus), "□□□□□")
        self.assertEqual(effort_bar("none", ("none", "low")), "□□")
        self.assertEqual(effort_bar("low"), "")

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


class EffortPickerTests(unittest.TestCase):
    """Model-dependent +/- across the CLI picker, the TUI save and cancel paths."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _index(self, payload, name: str) -> int:
        return [row["category"] for row in payload["categories"]].index(name)

    def test_haiku_xhigh_plus_reaches_max_and_then_holds(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "xhigh"),)})
        payload = _payload(self.root)
        index = self._index(payload, "quick")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("claude-haiku-5-5", "max"),)})
        self.assertIn("effort            none, low, medium, high, xhigh, max  (contract)", frames[-1])
        result, _frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("claude-haiku-5-5", "max"),)})

    def test_deepseek_steps_low_high_max_and_never_offers_mapping_aliases(self) -> None:
        _write_overrides(self.root, {"deep": (("deepseek-flash", "low"),)})
        payload = _payload(self.root)
        index = self._index(payload, "deep")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"deep": (("deepseek-flash", "max"),)})
        self.assertIn("effort            none, low, high, max  (contract)", frames[-1])
        # `medium` is a documented provider mapping, not a rung; stepping down
        # from `high` lands on `low`, not on the alias.
        _write_overrides(self.root, {"deep": (("deepseek-flash", "high"),)})
        payload = _payload(self.root)
        index = self._index(payload, "deep")
        result, _frames = _drive(payload, [KEY_DOWN] * index + [KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {"deep": (("deepseek-flash", "low"),)})

    def test_none_is_written_as_none_and_old_off_normalizes_on_edit(self) -> None:
        _write_overrides(self.root, {"quick": (("deepseek-flash", "off"),)})
        payload = _payload(self.root)
        index = self._index(payload, "quick")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "none"),)})
        self.assertIn("legacy spelling of `none`", frames[index])
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "low"),)})
        _write_overrides(self.root, {"quick": (("deepseek-flash", "none"),)})
        payload = _payload(self.root)
        result, frames = _drive(payload, [KEY_DOWN] * self._index(payload, "quick") + [KEY_ENTER])
        self.assertEqual(result, {})
        self.assertIn("explicit no thinking (`none`)", frames[-1])

    def test_unset_and_auto_are_distinguished_from_explicit_none(self) -> None:
        for effort, needle in (
            ("", "unset: the model/provider default applies"),
            ("auto", "`auto` is the provider default"),
        ):
            with self.subTest(effort=effort):
                _write_overrides(self.root, {"quick": (("deepseek-flash", effort),)})
                payload = _payload(self.root)
                frames = render_frame(
                    payload, _chains(payload), self._index(payload, "quick"), use_color=False, width=200
                )
                self.assertTrue(any(needle in line for line in frames), frames[-6:])
                self.assertFalse(any("explicit no thinking" in line for line in frames))
                result, _frames = _drive(payload, [KEY_DOWN] * self._index(payload, "quick") + [KEY_ENTER])
                self.assertEqual(result, {})

    def test_an_unknown_head_disables_both_effort_keys_and_keeps_the_value(self) -> None:
        _write_overrides(self.root, {"quick": (("glm-5.3", "high"),)})
        payload = _payload(self.root)
        by_alias = {row["alias"]: row for row in payload["models"]}
        self.assertIsNone(by_alias["glm-5.3"]["efforts"])
        index = self._index(payload, "quick")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {})
        self.assertEqual(len(frames), 1 + index)  # both keys were refused, not repainted
        row = next(line for line in frames[-1].splitlines() if " quick " in line)
        self.assertIn("unconfigured", row)
        self.assertIn("high", row)
        self.assertIn("unconfigured · no contract or override names this model; +/- disabled", frames[-1])

    def test_an_explicit_empty_list_is_a_no_knob_and_not_unknown(self) -> None:
        _write_overrides(self.root, {"quick": (("glm-5.3", "high"),)})
        _write_efforts(self.root, {"glm-5.3": []})
        payload = _payload(self.root)
        by_alias = {row["alias"]: row for row in payload["models"]}
        self.assertEqual(by_alias["glm-5.3"]["efforts"], [])
        self.assertTrue(by_alias["glm-5.3"]["efforts_configured"])
        self.assertEqual(by_alias["glm-5.3"]["efforts_source"], "user")
        index = self._index(payload, "quick")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {})
        self.assertIn("no adjustable effort", frames[-1])
        row = next(line for line in frames[-1].splitlines() if " quick " in line)
        self.assertIn("no knob", row)

    def test_a_user_override_replaces_the_ladder_for_a_known_model(self) -> None:
        _write_efforts(self.root, {"claude-haiku-5-5": ["low", "max"]})
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),)})
        payload = _payload(self.root)
        by_alias = {row["alias"]: row for row in payload["models"]}
        self.assertEqual(by_alias["claude-haiku-5-5"]["efforts"], ["low", "max"])
        self.assertEqual(by_alias["claude-haiku-5-5"]["efforts_source"], "user")
        index = self._index(payload, "quick")
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_PLUS, KEY_PLUS, KEY_ENTER])
        # `medium`/`high`/`xhigh` are not in the user's replacement list.
        self.assertEqual(result, {"quick": (("claude-haiku-5-5", "max"),)})
        self.assertIn("low, max  (user)", frames[index])
        # A stored value outside the replacement list is marked, not rewritten.
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
        payload = _payload(self.root)
        frames = render_frame(payload, _chains(payload), self._index(payload, "quick"), use_color=False, width=200)
        row = next(line for line in frames if " quick " in line)
        self.assertIn("high!", row)
        self.assertTrue(any("chosen effort `high` is not selectable" in line for line in frames))

    def test_switching_a_head_keeps_an_out_of_list_effort_until_the_next_plus(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "xhigh"),)})
        payload = _payload(self.root)
        index = self._index(payload, "quick")
        ring = tuple(row["alias"] for row in payload["models"])
        moved = step_head_model(step_head_model((("claude-opus-5-5", "xhigh"),), ring, 1), ring, 1)
        self.assertEqual(moved[0], ("deepseek-flash", "xhigh"))
        result, frames = _drive(payload, [KEY_DOWN] * index + [KEY_RIGHT, KEY_RIGHT, KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "xhigh"),)})
        self.assertIn("not selectable for this model", frames[-1])
        result, _frames = _drive(payload, [KEY_DOWN] * index + [KEY_RIGHT, KEY_RIGHT, KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "max"),)})


    def test_an_invalid_effort_document_is_painted_and_custom_heads_stay_unconfigured(self) -> None:
        path = _omh_home(self.root) / "routing" / "model-efforts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        _write_overrides(self.root, {"quick": (("my-custom", "high"),)})
        payload = _payload(self.root)
        self.assertTrue(str(payload["effort_document_status"]).startswith("invalid:"))
        frames = render_frame(payload, _chains(payload), self._index(payload, "quick"), use_color=False, width=200)
        self.assertTrue(any("model-efforts.json ignored" in line for line in frames))
        row = next(line for line in frames if " quick " in line)
        self.assertIn("unconfigured", row)
        result, _frames = _drive(payload, [KEY_DOWN] * self._index(payload, "quick") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {})


class EffortSaveTests(unittest.TestCase):
    """The two save entrances re-check only the +/- changes against live config."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _stored(self, name: str = "quick") -> list[dict[str, str]]:
        document = json.loads((_omh_home(self.root) / "routing" / "model-chains.json").read_text(encoding="utf-8"))
        return document["categories"][name]

    def test_model_only_switch_preserves_a_shifted_legacy_tail(self) -> None:
        _write_overrides(self.root, {"quick": (
            ("claude-opus-5-5", "high"),
            ("claude-sonnet-5-5", "low"),
            ("deepseek-flash", "medium"),
        )})
        payload = _payload(self.root)
        changes, _frames = _drive(
            payload, [KEY_DOWN] * _row_index(payload, "quick") + [KEY_RIGHT, KEY_ENTER]
        )
        expected = (("claude-sonnet-5-5", "high"), ("deepseek-flash", "medium"))
        self.assertEqual(changes, {"quick": expected})
        resolver, status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        result = apply_picker_changes(
            _omh_home(self.root), changes, effort_options=resolver, effort_status=status
        )
        self.assertNotIn("error", result)
        self.assertEqual(self._stored(), [
            {"model": model, "reasoning_effort": effort} for model, effort in expected
        ])

    def test_switched_head_effort_round_trip_is_rechecked_against_live_options(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "high"),)})
        document = _omh_home(self.root) / "routing" / "model-chains.json"
        before = document.read_bytes()
        payload = _payload(self.root)
        changes, _frames = _drive(
            payload, [KEY_DOWN] * _row_index(payload, "quick")
            + [KEY_RIGHT, KEY_RIGHT, KEY_MINUS, KEY_PLUS, KEY_ENTER]
        )
        self.assertEqual(changes, {"quick": (("deepseek-flash", "high"),)})
        _write_efforts(self.root, {"deepseek-flash": ["low"]})
        resolver, status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        result = apply_picker_changes(
            _omh_home(self.root), changes, effort_options=resolver, effort_status=status
        )
        self.assertIn("not selectable", result.get("error", ""))
        self.assertEqual(document.read_bytes(), before)

    def test_both_entrances_preserve_real_picker_effort_provenance(self) -> None:
        from omh.tui.app import run_model_chain_picker
        from omh.tui.theme import DEFAULT_THEME

        for surface in ("cli", "tui"):
            with self.subTest(surface=surface):
                _write_overrides(self.root, {"quick": (("claude-opus-5-5", "high"),)})
                _write_efforts(self.root, {"deepseek-flash": ["low", "high", "max"]})
                document = _omh_home(self.root) / "routing" / "model-chains.json"
                before = document.read_bytes()

                def pick_then_narrow(payload, **_kwargs):
                    changes, _frames = _drive(
                        payload, [KEY_DOWN] * _row_index(payload, "quick")
                        + [KEY_RIGHT, KEY_RIGHT, KEY_MINUS, KEY_PLUS, KEY_ENTER]
                    )
                    self.assertEqual(changes, {"quick": (("deepseek-flash", "high"),)})
                    _write_efforts(self.root, {"deepseek-flash": ["low"]})
                    return changes

                if surface == "cli":
                    with (
                        patch("omh.commands.model_chains.picker_available", return_value=True),
                        patch("omh.commands.model_chains.pick_chains_interactively", side_effect=pick_then_narrow),
                    ):
                        status, _stdout, message = run_cli(
                            ["--omh-home", str(_omh_home(self.root)), "model-chains"], output_json=False
                        )
                    self.assertEqual(status, 2)
                else:
                    with patch("omh.commands.model_chain_picker.run_picker", side_effect=pick_then_narrow):
                        message = run_model_chain_picker(
                            {"OMH_HOME": str(_omh_home(self.root)), "HERMES_HOME": str(self.root / ".hermes")},
                            DEFAULT_THEME, read_key=lambda: KEY_QUIT, write=lambda _text: None, width=100,
                        )
                self.assertIn("not selectable", message)
                self.assertEqual(document.read_bytes(), before)

    def test_reset_then_model_switch_does_not_retain_an_earlier_effort_edit(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
        payload = _payload(self.root)
        changes, _frames = _drive(
            payload, [KEY_DOWN] * _row_index(payload, "quick")
            + [KEY_MINUS, KEY_DEFAULT, KEY_RIGHT, KEY_ENTER]
        )
        self.assertTrue(changes)
        self.assertEqual(changes.effort_edits, frozenset())
        effort_path = _omh_home(self.root) / "routing" / "model-efforts.json"
        effort_path.write_text("{", encoding="utf-8")
        resolver, status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        result = apply_picker_changes(
            _omh_home(self.root), changes, effort_options=resolver, effort_status=status
        )
        self.assertNotIn("error", result)
        self.assertIn("model-efforts.json ignored", result["warning"])
        self.assertEqual(self._stored(), [
            {"model": model, "reasoning_effort": effort} for model, effort in changes["quick"]
        ])

    def test_a_model_switch_keeps_an_unsupported_effort_but_an_effort_edit_is_refused(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "xhigh"),)})
        resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        switched = apply_picker_changes(
            _omh_home(self.root),
            {"quick": (("deepseek-flash", "xhigh"),)},
            effort_options=resolver,
        )
        self.assertNotIn("error", switched)
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "xhigh"}])
        resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        refused = apply_picker_changes(
            _omh_home(self.root),
            PickerChanges({"quick": (("deepseek-flash", "medium"),)}, effort_edits=frozenset({"quick"})),
            effort_options=resolver,
        )
        self.assertIn("not selectable", refused["error"])
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "xhigh"}])

    def test_an_unknown_or_empty_ladder_refuses_a_new_effort(self) -> None:
        _write_overrides(self.root, {"quick": (("glm-5.3", "high"),)})
        resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        refused = apply_picker_changes(
            _omh_home(self.root),
            PickerChanges({"quick": (("glm-5.3", "low"),)}, effort_edits=frozenset({"quick"})),
            effort_options=resolver,
        )
        self.assertIn("no configured effort options", refused["error"])
        _write_efforts(self.root, {"glm-5.3": []})
        resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        refused = apply_picker_changes(
            _omh_home(self.root),
            PickerChanges({"quick": (("glm-5.3", "low"),)}, effort_edits=frozenset({"quick"})),
            effort_options=resolver,
        )
        self.assertIn("no selectable efforts", refused["error"])
        self.assertEqual(self._stored(), [{"model": "glm-5.3", "reasoning_effort": "high"}])


    def test_save_rechecks_the_live_effort_document(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),)})
        # The picker was opened while `high` was selectable...
        picker_resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        self.assertIn("high", picker_resolver("claude-haiku-5-5")["efforts"])
        # ...then the person restricts the model while the picker is open.
        _write_efforts(self.root, {"claude-haiku-5-5": ["low"]})
        save_resolver, _status = effort_option_resolver(_omh_home(self.root), contract_option=contract_effort_option)
        refused = apply_picker_changes(
            _omh_home(self.root),
            PickerChanges({"quick": (("claude-haiku-5-5", "high"),)}, effort_edits=frozenset({"quick"})),
            effort_options=save_resolver,
        )
        self.assertIn("not selectable", refused["error"])
        self.assertEqual(self._stored(), [{"model": "claude-haiku-5-5", "reasoning_effort": "low"}])

    def test_both_entrances_refuse_the_same_stale_edit_without_writing(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),)})
        _write_efforts(self.root, {"claude-haiku-5-5": ["low"]})
        base = ["--omh-home", str(_omh_home(self.root))]
        changes = PickerChanges({"quick": (("claude-haiku-5-5", "high"),)}, effort_edits=frozenset({"quick"}))
        with (
            patch("omh.commands.model_chains.picker_available", return_value=True),
            patch("omh.commands.model_chains.pick_chains_interactively", return_value=changes),
        ):
            status, stdout, stderr = run_cli(base + ["model-chains"], output_json=False)
        self.assertEqual(status, 2, stdout)
        self.assertIn("picker save incomplete", stderr)
        self.assertIn("not selectable", stderr)
        self.assertEqual(self._stored(), [{"model": "claude-haiku-5-5", "reasoning_effort": "low"}])

        from omh.tui.app import run_model_chain_picker
        from omh.tui.theme import DEFAULT_THEME

        environ = {
            "OMH_HOME": str(_omh_home(self.root)),
            "HERMES_HOME": str(self.root / ".hermes"),
            "NO_COLOR": "1",
        }
        with patch("omh.commands.model_chain_picker.run_picker", return_value=changes):
            message = run_model_chain_picker(
                environ,
                DEFAULT_THEME,
                read_key=lambda: "quit",
                write=lambda _text: None,
                width=100,
            )
        self.assertIn("/omh-model save incomplete", message)
        self.assertIn("not selectable", message)
        self.assertEqual(self._stored(), [{"model": "claude-haiku-5-5", "reasoning_effort": "low"}])



    def test_both_entrances_refuse_an_effort_edit_when_the_document_turned_malformed(self) -> None:
        # The review's F2: the save-time resolver silently fell back to the
        # built-in ladder. A new effort must instead be refused with the
        # document named, in both entrances, and nothing written.
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),)})
        _write_efforts(self.root, {"claude-haiku-5-5": ["low", "high"]})
        changes = PickerChanges({"quick": (("claude-haiku-5-5", "high"),)}, effort_edits=frozenset({"quick"}))
        effort_path = _omh_home(self.root) / "routing" / "model-efforts.json"
        document = _omh_home(self.root) / "routing" / "model-chains.json"
        before = document.read_bytes()

        def break_document(*_args, **_kwargs):
            effort_path.write_text("{", encoding="utf-8")
            return changes

        base = ["--omh-home", str(_omh_home(self.root))]
        with (
            patch("omh.commands.model_chains.picker_available", return_value=True),
            patch("omh.commands.model_chains.pick_chains_interactively", side_effect=break_document),
        ):
            status, stdout, stderr = run_cli(base + ["model-chains"], output_json=False)
        self.assertEqual(status, 2, stdout)
        self.assertIn("model-efforts.json is invalid", stderr)
        self.assertEqual(document.read_bytes(), before)

        from omh.tui.app import run_model_chain_picker
        from omh.tui.theme import DEFAULT_THEME

        _write_efforts(self.root, {"claude-haiku-5-5": ["low", "high"]})
        before = document.read_bytes()

        def break_and_return(*_args, **_kwargs):
            effort_path.write_text("{", encoding="utf-8")
            return changes

        with patch("omh.commands.model_chain_picker.run_picker", side_effect=break_and_return):
            message = run_model_chain_picker(
                {
                    "OMH_HOME": str(_omh_home(self.root)),
                    "HERMES_HOME": str(self.root / ".hermes"),
                    "NO_COLOR": "1",
                },
                DEFAULT_THEME,
                read_key=lambda: KEY_QUIT,
                write=lambda _text: None,
                width=100,
            )
        self.assertIn("/omh-model save incomplete", message)
        self.assertIn("model-efforts.json is invalid", message)
        self.assertEqual(document.read_bytes(), before)


    def test_default_reset_is_not_revalidated_as_an_effort_edit(self) -> None:
        # `quick` ships with GLM 5.3 Flash, which has no contract. A `d`
        # reset to that shipped chain must still save: it is explicit and
        # does not produce a stray selectable effort.
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
        payload = _payload(self.root)
        changes, _frames = _drive(
            payload, [KEY_DOWN] * _row_index(payload, "quick") + [KEY_MINUS, KEY_DEFAULT, KEY_ENTER]
        )
        self.assertEqual(changes, {"quick": HERMES_MIXTURE_CATEGORY_CHAINS["quick"]})
        self.assertEqual(changes.effort_edits, frozenset())
        resolver, _status = effort_option_resolver(
            _omh_home(self.root), contract_option=contract_effort_option
        )
        result = apply_picker_changes(
            _omh_home(self.root),
            changes,
            effort_options=resolver,
        )
        self.assertNotIn("error", result)
        document = json.loads(
            (_omh_home(self.root) / "routing" / "model-chains.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("quick", document["categories"])

    def test_both_surfaces_receive_the_same_resolved_effort_metadata(self) -> None:
        base = ["--omh-home", str(_omh_home(self.root))]
        with (
            patch("omh.commands.model_chains.picker_available", return_value=True),
            patch("omh.commands.model_chains.pick_chains_interactively", return_value={}) as cli_picker,
        ):
            status, _stdout, _stderr = run_cli(base + ["model-chains"], output_json=False)
        self.assertEqual(status, 0)
        cli_payload = cli_picker.call_args.args[0]
        cli_models = {row["alias"]: row for row in cli_payload["models"]}
        self.assertIn("none", cli_models["claude-haiku-5-5"]["efforts"])

        from omh.tui.app import run_model_chain_picker
        from omh.tui.theme import DEFAULT_THEME

        captured: dict[str, object] = {}

        def capture(payload, **_kwargs):
            captured.update(payload)
            return None

        environ = {
            "OMH_HOME": str(_omh_home(self.root)),
            "HERMES_HOME": str(self.root / ".hermes"),
            "NO_COLOR": "1",
        }
        with patch("omh.commands.model_chain_picker.run_picker", side_effect=capture):
            message = run_model_chain_picker(
                environ,
                DEFAULT_THEME,
                read_key=lambda: "quit",
                write=lambda _text: None,
                width=100,
            )
        self.assertTrue(message.startswith("Cancelled;"), message)
        tui_models = {row["alias"]: row for row in captured["models"]}
        self.assertEqual(tui_models["claude-haiku-5-5"], cli_models["claude-haiku-5-5"])
        self.assertEqual(tui_models["glm-5.3"]["efforts"], None)

    def test_model_chains_set_keeps_its_no_subset_validation_semantics(self) -> None:
        base = ["--omh-home", str(_omh_home(self.root))]
        status, stdout, stderr = run_cli(base + ["model-chains", "set", "quick", "deepseek-flash:medium"], output_json=False)
        self.assertEqual((status, stderr), (0, ""), stdout)
        self.assertIn("quick: deepseek-flash:medium (override)", stdout)
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "medium"}])


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
