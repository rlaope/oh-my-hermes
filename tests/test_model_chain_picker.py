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
    PICKER_EFFORT_RING,
    PICKER_SCHEMA_VERSION,
    PickerChanges,
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


def _write_efforts(root: Path, models: dict[str, list[str]]) -> None:
    path = _omh_home(root) / "routing" / "model-efforts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
        "models": {name: {"efforts": efforts} for name, efforts in models.items()},
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _payload(root: Path, *, labels: bool = True) -> dict[str, object]:
    # A Hermes home with nothing linked, so only what a test records counts.
    return picker_rows(
        _omh_home(root),
        hermes_home=root / ".hermes",
        labels=MODEL_DISPLAY_LABELS if labels else None,
        purposes=CHAIN_SURFACE_PURPOSES if labels else None,
        contract_option=contract_effort_option,
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


def _row_index(payload, name: str) -> int:
    return [row["category"] for row in payload["categories"]].index(name)


def _down_to(payload, name: str) -> list[str]:
    return [KEY_DOWN] * _row_index(payload, name)


def _rights_to(payload, start: str, target: str) -> list[str]:
    aliases = [row["alias"] for row in payload["models"]]
    return [KEY_RIGHT] * ((aliases.index(target) - aliases.index(start)) % len(aliases))


def _frame(payload, name: str, width: int = 200) -> list[str]:
    return render_frame(payload, _chains(payload), _row_index(payload, name), use_color=False, width=width)


def _row_of(lines, name: str) -> str:
    return next(line for line in lines if f" {name} " in line)


def _screen_after(writes: list[str]) -> list[str]:
    """What a terminal shows after these writes: cursor-up, clear-line, clear-below."""
    screen: list[str] = []
    row = 0
    for chunk in writes:
        for piece in re.split(r"(\x1b\[\d*[AJK]|\x1b\[2K|\n)", chunk):
            if piece == "\n":
                row += 1
            elif piece == f"{ESC}[J":
                del screen[row:]
            elif piece == f"{ESC}[2K":
                if row < len(screen):
                    screen[row] = ""
            elif piece.startswith(ESC):
                row -= int(piece[2:-1])
            elif piece:
                screen.extend([""] * (row + 1 - len(screen)))
                screen[row] = piece
    return screen


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
        models = {row["alias"]: row for row in payload["models"]}
        self.assertEqual(models["gpt-6-astra"]["efforts"], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(models["gpt-6-astra"]["efforts_source"], "contract")
        self.assertTrue(models["gpt-6-astra"]["efforts_configured"])
        self.assertEqual(models["glm-5.3"]["efforts"], list(PICKER_EFFORT_RING))
        self.assertEqual(models["glm-5.3"]["efforts_source"], "unknown")
        self.assertFalse(models["glm-5.3"]["efforts_configured"])
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
                    None,
                    PickerChanges({"deep": (("kimi-k3", "high"),)}),
                    hermes_home=named,
                    contract_option=contract_effort_option,
                )
                self.assertEqual(Path(result["path"]), document)
                self.assertTrue(document.exists())
                self.assertFalse((root / "ambient-store").exists())
                (named / "config.yaml").write_text(
                    "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: true\n", encoding="utf-8"
                )
                self.assertIn(
                    "not a path string",
                    apply_picker_changes(
                        None, PickerChanges({}), hermes_home=named, contract_option=contract_effort_option
                    )["error"],
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

    def test_effort_ladder_mirrors_model_routing(self) -> None:
        # The bundle cannot import src/coding, so it carries a copy; this is
        # the one place the copy is held to the original. Hermes spells the
        # no-thinking rung `none` where the canonical ladder says `off`.
        self.assertEqual(EFFORT_VOCABULARY, tuple("none" if r == "off" else r for r in REASONING_EFFORT_LADDER))
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
        ring = PICKER_EFFORT_RING
        self.assertEqual(step_effort((("m", "medium"),) + tail, 1, ring), (("m", "high"),) + tail)
        self.assertEqual(step_effort((("m", "medium"),) + tail, -1, ring), (("m", "low"),) + tail)
        self.assertEqual(step_effort((("m", "low"),), -1, ring), (("m", "low"),))
        self.assertEqual(step_effort((("m", "xhigh"),), 1, ring), (("m", "xhigh"),))
        self.assertEqual(step_effort((("m", ""),), 1, ring), (("m", "low"),))
        self.assertEqual(step_effort((("m", ""),), -1, ring), (("m", "low"),))
        self.assertEqual(step_effort((("m", "minimal"),), 1, ring), (("m", "low"),))
        self.assertEqual(step_effort((("m", "none"),), -1, ring), (("m", "low"),))
        self.assertEqual(step_effort((("m", "max"),), 1, ring), (("m", "max"),))
        self.assertEqual(step_effort((("m", "max"),), -1, ring), (("m", "xhigh"),))
        self.assertEqual(step_effort((), 1, ring), ())

    def test_step_effort_walks_the_models_own_ladder(self) -> None:
        haiku = ("none", "low", "medium", "high", "xhigh", "max")
        self.assertEqual(step_effort((("m", "xhigh"),), 1, haiku), (("m", "max"),))
        self.assertEqual(step_effort((("m", "low"),), -1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((("m", "none"),), -1, haiku), (("m", "none"),))
        self.assertEqual(step_effort((("m", "max"),), 1, haiku), (("m", "max"),))
        self.assertEqual(step_effort((("m", "none"),), 1, haiku), (("m", "low"),))
        self.assertEqual(step_effort((("m", "low"),), 1, ()), (("m", "low"),))

    def test_a_press_on_a_value_that_says_nothing_never_turns_thinking_off(self) -> None:
        haiku = ("none", "low", "medium", "high", "xhigh", "max")
        for stored in ("", "auto", "ultra"):
            for direction in (1, -1):
                with self.subTest(stored=stored, direction=direction):
                    self.assertEqual(step_effort((("m", stored),), direction, haiku), (("m", "low"),))
        # A list holding nothing else still has to land somewhere on it.
        self.assertEqual(step_effort((("m", ""),), 1, ("none",)), (("m", "none"),))

    def test_step_effort_lands_a_value_off_the_ladder_on_the_next_rung_that_way(self) -> None:
        deepseek = ("none", "low", "high", "max")
        self.assertEqual(step_effort((("d", "medium"),), 1, deepseek), (("d", "high"),))
        self.assertEqual(step_effort((("d", "medium"),), -1, deepseek), (("d", "low"),))
        self.assertEqual(step_effort((("d", "xhigh"),), 1, deepseek), (("d", "max"),))
        self.assertEqual(step_effort((("d", "xhigh"),), -1, deepseek), (("d", "high"),))
        # Nothing above holds rather than falling back down the ladder.
        self.assertEqual(step_effort((("g", "xhigh"),), 1, ("low", "medium", "high")), (("g", "xhigh"),))
        self.assertEqual(step_effort((("g", "xhigh"),), -1, ("low", "medium", "high")), (("g", "high"),))
        # Nothing below enters at the lowest rung.
        self.assertEqual(step_effort((("k", "minimal"),), -1, ("low", "high")), (("k", "low"),))

    def test_step_effort_reads_old_off_as_none(self) -> None:
        self.assertEqual(step_effort((("m", "off"),), 1, ("none", "low")), (("m", "low"),))
        self.assertEqual(step_effort((("m", "off"),), -1, ("none", "low")), (("m", "none"),))
        self.assertEqual(step_effort((("m", "off"),), 1, ("low", "high")), (("m", "low"),))
        self.assertEqual(step_effort((("m", "off"),), -1, ("low", "high")), (("m", "low"),))

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
        ladders = {row["alias"]: tuple(row["efforts"]) for row in payload["models"]}
        result, frames = _drive(payload, [KEY_DOWN, KEY_RIGHT, KEY_PLUS, KEY_ENTER])
        moved = step_head_model(original["deep"], ring, 1)
        deep = step_effort(moved, 1, ladders[moved[0][0]])
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
        ladders = {row["alias"]: tuple(row["efforts"]) for row in payload["models"]}
        last = payload["categories"][-1]["category"]
        result, _ = _drive(payload, [KEY_NONE, KEY_LEFT, KEY_MINUS, KEY_ENTER])
        first = payload["categories"][0]["category"]
        moved = step_head_model(original[first], ring, -1)
        self.assertEqual(result, {first: step_effort(moved, -1, ladders[moved[0][0]])})
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
        _write_overrides(self.root, {"ultrabrain": (("claude-fable-5-1", "medium"), ("gpt-6-astra", "xhigh"))})
        payload = _payload(self.root)
        chains = _chains(payload)
        lines = render_frame(payload, chains, 0, use_color=False, width=200)
        row = next(line for line in lines if " ultrabrain " in line)
        self.assertTrue(row.startswith(f" {CURSOR_MARK} "))
        self.assertIn(f"◂ {MODEL_DISPLAY_LABELS['claude-fable-5-1']} ▸", row)
        self.assertIn(f"− {effort_bar('medium')} +   medium?", row)
        self.assertTrue(row.rstrip().endswith("◆ override"))
        self.assertIn("   chain             claude-fable-5-1:medium, gpt-6-astra:xhigh", lines)
        self.assertIn(
            f"   shipped default   {', '.join(m + ':' + e for m, e in HERMES_MIXTURE_CATEGORY_CHAINS['ultrabrain'])}",
            lines,
        )
        self.assertTrue(lines[0].startswith(" ⚚ OMH · Model chains"))
        self.assertEqual(lines[1], "   providers  none linked to Hermes yet · every model counts as served")
        self.assertIn("CATEGORY", lines[3])
        self.assertIn("↑↓ category   ←→ head model   −/+ effort   d default   ⏎ save   esc cancel", lines[-1])
        self.assertEqual(effort_bar("low"), "■□□□")
        self.assertEqual(effort_bar("xhigh"), "■■■■")
        self.assertEqual(effort_bar("max"), "■■■■")
        self.assertEqual(effort_bar(""), "□□□□")
        # A cell per rung of the model's own ladder, and `none` never takes one.
        self.assertEqual(effort_bar("high", ("low", "high", "max")), "■■□")
        self.assertEqual(effort_bar("low", ("none", "low", "high")), "■□")
        self.assertEqual(effort_bar("none", ("none", "low", "high")), "□□")
        self.assertEqual(effort_bar("max", ("low", "high")), "■■")
        self.assertEqual(effort_bar("medium", ("low", "high")), "□□")

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
    """Each model's -/+ through the real picker loop both surfaces share."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_contract_head_steps_its_own_ladder_and_says_so(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "xhigh"),), "deep": (("deepseek-flash", "high"),)})
        payload = _payload(self.root)
        result, frames = _drive(payload, _down_to(payload, "quick") + [KEY_PLUS, KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("claude-haiku-5-5", "max"),)})
        self.assertIn("effort            none, low, medium, high, xhigh, max  (contract)", frames[-1])
        # DeepSeek's `medium` is a provider mapping, not a rung to stop on.
        result, frames = _drive(payload, _down_to(payload, "deep") + [KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {"deep": (("deepseek-flash", "low"),)})
        self.assertIn("effort            none, low, high, max  (contract)", frames[-1])

    def test_old_off_is_explained_truthfully_and_moves_onto_the_list_on_a_press(self) -> None:
        # Measured per ladder: only `-` on a ladder holding `none` reaches it.
        cases = (
            ("claude-opus-5-5", KEY_PLUS, "low", "the route refuses `off` on claude-opus-5-5"),
            ("claude-opus-5-5", KEY_MINUS, "low", "the route refuses `off` on claude-opus-5-5"),
            ("gpt-6-luna", KEY_PLUS, "low", "so the provider default runs"),
            ("gpt-6-luna", KEY_MINUS, "none", "so the provider default runs"),
        )
        for model, key, landed, said in cases:
            with self.subTest(model=model, key=key):
                _write_overrides(self.root, {"quick": ((model, "off"),)})
                payload = _payload(self.root)
                result, frames = _drive(payload, _down_to(payload, "quick") + [key, KEY_ENTER])
                self.assertEqual(result, {"quick": ((model, landed),)})
                before_press = frames[-2]
                self.assertIn("off!", before_press)
                self.assertIn(said, before_press)
                self.assertNotIn("rewrites", before_press)

    def test_unset_auto_and_none_each_say_what_they_are(self) -> None:
        for effort, needle in (
            ("", "unset: the model or provider default applies"),
            ("auto", "`auto` is the provider default"),
            ("none", "explicit no thinking"),
        ):
            with self.subTest(effort=effort):
                _write_overrides(self.root, {"quick": (("deepseek-flash", effort),)})
                payload = _payload(self.root)
                frame = _frame(payload, "quick")
                self.assertEqual(sum(needle in line for line in frame), 1, frame)
                result, _ = _drive(payload, _down_to(payload, "quick") + [KEY_ENTER])
                self.assertEqual(result, {})

    def test_an_unconfigured_head_keeps_stepping_the_shared_ring(self) -> None:
        # The owner's rule: nobody on a custom model is stuck writing JSON.
        cases = (
            ("my-custom", "low", KEY_PLUS, "medium"),
            ("glm-5.3-flash", "low", KEY_PLUS, "medium"),
            ("grok-4.7", "high", KEY_PLUS, "xhigh"),
            ("claude-fable-5-1", "high", KEY_MINUS, "medium"),
        )
        for model, stored, key, landed in cases:
            with self.subTest(model=model):
                _write_overrides(self.root, {"swarm": ((model, stored),)})
                payload = _payload(self.root)
                row = next(row for row in payload["models"] if row["alias"] == model)
                self.assertEqual(row["efforts"], list(PICKER_EFFORT_RING))
                self.assertFalse(row["efforts_configured"])
                result, _ = _drive(payload, _down_to(payload, "swarm") + [key, KEY_ENTER])
                self.assertEqual(result, {"swarm": ((model, landed),)})
                self.assertEqual(result.effort_edits, frozenset({"swarm"}))

    def test_shipped_heads_with_no_contract_step_from_a_clean_install(self) -> None:
        payload = _payload(self.root)
        result, _ = _drive(payload, _down_to(payload, "quick") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result["quick"][0], ("glm-5.3-flash", "medium"))
        result, _ = _drive(payload, _down_to(payload, "x-search") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result["x-search"][0], ("grok-4.7", "xhigh"))

    def test_an_unconfigured_value_is_marked_not_known_and_never_called_wrong(self) -> None:
        for stored in ("low", "xhigh", "max", "auto"):
            with self.subTest(stored=stored):
                _write_overrides(self.root, {"swarm": (("my-custom", stored),)})
                payload = _payload(self.root)
                frame = _frame(payload, "swarm")
                row = _row_of(frame, "swarm")
                self.assertIn(f" {stored}? ", row)
                self.assertNotIn("!", row)
                self.assertIn(
                    "   effort            low, medium, high, xhigh  "
                    "(ladder not known: shared steps, not checked for this model)",
                    frame,
                )
                self.assertFalse(any(line.lstrip().startswith("! ") for line in frame), frame)
                self.assertIn(f"− {effort_bar(stored)} +", row)
        _write_overrides(self.root, {"swarm": (("my-custom", ""),)})
        payload = _payload(self.root)
        frame = _frame(payload, "swarm")
        self.assertIn(" -? ", _row_of(frame, "swarm"))

    def test_an_unset_effort_on_a_contract_head_is_not_off_its_list(self) -> None:
        _write_overrides(self.root, {"swarm": (("gpt-6-astra", ""),)})
        payload = _payload(self.root)
        frame = _frame(payload, "swarm")
        row = _row_of(frame, "swarm")
        self.assertIn(" - ", row)
        self.assertNotIn("!", row)
        self.assertFalse(any(line.lstrip().startswith("! ") for line in frame), frame)

    def test_a_contract_head_shows_neither_mark_on_a_rung_of_its_own(self) -> None:
        _write_overrides(self.root, {"swarm": (("gpt-6-astra", "xhigh"),)})
        payload = _payload(self.root)
        frame = _frame(payload, "swarm")
        row = _row_of(frame, "swarm")
        self.assertIn(" xhigh ", row)
        self.assertNotIn("xhigh?", row)
        self.assertNotIn("xhigh!", row)

    def test_max_on_the_ring_holds_on_plus_and_enters_xhigh_on_minus(self) -> None:
        _write_overrides(self.root, {"swarm": (("my-custom", "max"),)})
        payload = _payload(self.root)
        result, _ = _drive(payload, _down_to(payload, "swarm") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {})
        self.assertEqual(result.effort_edits, frozenset())
        result, _ = _drive(payload, _down_to(payload, "swarm") + [KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {"swarm": (("my-custom", "xhigh"),)})

    def test_no_thinking_on_an_unconfigured_head_is_marked_wrong_not_unknown(self) -> None:
        for stored in ("none", "off"):
            with self.subTest(stored=stored):
                _write_overrides(self.root, {"swarm": (("my-custom", stored),)})
                payload = _payload(self.root)
                frame = _frame(payload, "swarm")
                row = _row_of(frame, "swarm")
                self.assertIn(f" {stored}! ", row)
                self.assertNotIn("?", row)
                # Nothing says the route refuses it: a custom route does not.
                self.assertFalse(any("refuses" in line for line in frame), frame)
                self.assertTrue(any(line.lstrip().startswith("! ") for line in frame), frame)

    def test_a_model_switch_onto_an_always_thinking_head_warns_and_still_saves(self) -> None:
        # Model-only edits are not rechecked, so the row must say what the
        # route will do with the `none` the switch carried along.
        for target in ("claude-fable-5-1", "claude-opus-5-5"):
            with self.subTest(target=target):
                _write_overrides(self.root, {"swarm": (("gpt-6-luna", "none"),)})
                payload = _payload(self.root)
                result, frames = _drive(
                    payload, _down_to(payload, "swarm") + _rights_to(payload, "gpt-6-luna", target) + [KEY_ENTER]
                )
                self.assertEqual(result, {"swarm": ((target, "none"),)})
                self.assertEqual(result.effort_edits, frozenset())
                self.assertIn(" none! ", _row_of(frames[-1].splitlines(), "swarm"))
                self.assertIn(f"! the route refuses `none` on {target}: thinking is always on", frames[-1])
        _write_overrides(self.root, {"swarm": (("gpt-6-luna", "none"),)})
        payload = _payload(self.root)
        frame = _frame(payload, "swarm")
        self.assertNotIn("none!", "\n".join(frame))
        self.assertFalse(any("refuses" in line for line in frame), frame)

    def test_a_user_list_naming_none_does_not_talk_the_route_out_of_refusing_it(self) -> None:
        _write_efforts(self.root, {"claude-opus-5-5": ["none", "low"]})
        _write_overrides(self.root, {"swarm": (("claude-opus-5-5", "none"),)})
        payload = _payload(self.root)
        frame = _frame(payload, "swarm")
        self.assertIn(" none! ", _row_of(frame, "swarm"))
        self.assertTrue(any("! the route refuses `none` on claude-opus-5-5" in line for line in frame), frame)

    def test_an_explicit_empty_list_is_the_one_way_to_turn_the_keys_off(self) -> None:
        for model in ("glm-5.3", "claude-opus-5-5"):
            with self.subTest(model=model):
                _write_overrides(self.root, {"swarm": ((model, "high"),)})
                _write_efforts(self.root, {model: []})
                payload = _payload(self.root)
                row = next(row for row in payload["models"] if row["alias"] == model)
                self.assertEqual((row["efforts"], row["efforts_configured"], row["efforts_source"]), ([], True, "user"))
                result, frames = _drive(payload, _down_to(payload, "swarm") + [KEY_PLUS, KEY_MINUS, KEY_ENTER])
                self.assertEqual(result, {})
                self.assertIn("fixed: this model's list is empty", frames[-1])
                line = _row_of(frames[-1].splitlines(), "swarm")
                self.assertIn("fixed", line)
                self.assertNotIn("−", line)
                self.assertNotIn("+", line)

    def test_a_user_entry_replaces_the_ladder_and_marks_a_stored_value_it_left_out(self) -> None:
        _write_efforts(self.root, {"claude-haiku-5-5": ["low", "max"], "my-custom": ["none", "max"]})
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),), "swarm": (("my-custom", "none"),)})
        payload = _payload(self.root)
        result, frames = _drive(payload, _down_to(payload, "quick") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("claude-haiku-5-5", "max"),)})
        self.assertIn("low, max  (user)", frames[-1])
        # A user entry can name what the shared steps cannot, and it counts as known.
        result, frames = _drive(payload, _down_to(payload, "swarm") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"swarm": (("my-custom", "max"),)})
        self.assertNotIn("none!", frames[-2])
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
        payload = _payload(self.root)
        frame = _frame(payload, "quick")
        self.assertIn("high!", _row_of(frame, "quick"))
        self.assertTrue(any("! `high` is not on this list" in line for line in frame), frame)

    def test_switching_a_head_keeps_an_off_list_effort_until_the_next_press(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "xhigh"),)})
        payload = _payload(self.root)
        moves = _down_to(payload, "quick") + _rights_to(payload, "claude-opus-5-5", "deepseek-flash")
        result, frames = _drive(payload, moves + [KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "xhigh"),)})
        self.assertIn("! `xhigh` is not on this list", frames[-1])
        result, _ = _drive(payload, moves + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(result, {"quick": (("deepseek-flash", "max"),)})

    def test_a_document_broken_at_open_turns_the_keys_off_and_says_so(self) -> None:
        path = _omh_home(self.root) / "routing" / "model-efforts.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        _write_overrides(self.root, {"swarm": (("gpt-6-astra", "high"),)})
        payload = _payload(self.root)
        moves = _down_to(payload, "swarm")
        result, frames = _drive(payload, moves + [KEY_PLUS, KEY_MINUS, KEY_ENTER])
        self.assertEqual(result, {})
        self.assertEqual(len(frames), 1 + len(moves))  # neither key was accepted
        self.assertIn("! model-efforts.json ignored: unreadable JSON · −/+ are off until it is fixed", frames[-1])
        self.assertNotIn("− ■", frames[-1])
        # A head switch is still open, and it saves through the broken file.
        result, _ = _drive(payload, moves + [KEY_RIGHT, KEY_ENTER])
        self.assertEqual(set(result), {"swarm"})
        self.assertEqual(result.effort_edits, frozenset())

    def test_every_frame_fits_its_width_with_columns_aligned(self) -> None:
        _write_efforts(self.root, {"fixed-model": [], "wide-model": ["minimal", "low", "medium", "high", "xhigh", "max"]})
        _write_overrides(
            self.root,
            {
                "ultrabrain": (("gpt-6-astra", "xhigh"),),
                "deep": (("my-custom", "minimal"),),
                "quick": (("deepseek-flash", "medium"),),
                "swarm": (("claude-opus-5-5", "off"),),
                "review": (("fixed-model", "high"),),
                "forensics": (("wide-model", "max"),),
            },
        )
        payload = _payload(self.root)
        notice = "! a-long-category-name: xhigh is not on a-really-quite-long-model-identifier's list; −/+ or d"
        for width in (60, 80, 110, 160):
            for cursor in range(len(payload["categories"])):
                with self.subTest(width=width, cursor=cursor):
                    lines = render_frame(payload, _chains(payload), cursor, use_color=False, width=width, notice=notice)
                    self.assertTrue(all(len(line) <= width for line in lines), max(lines, key=len))
                    colored = render_frame(payload, _chains(payload), cursor, use_color=True, width=max(width, 80), notice=notice)
                    visible = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in colored]
                    self.assertTrue(all(len(line) <= max(width, 80) for line in visible), max(visible, key=len))
                    if width >= 110:
                        states = {line.index(glyph) for line in lines for glyph in ("· default", "◆ override") if glyph in line}
                        self.assertEqual(len(states), 1, lines)

    def test_a_marked_value_touches_neither_the_handle_nor_the_state(self) -> None:
        for model, stored, shown in (
            ("claude-opus-5-5", "off", "off!"),
            ("deepseek-flash", "medium", "medium!"),
            ("my-custom", "medium", "medium?"),
            ("my-custom", "minimal", "minima?"),
        ):
            with self.subTest(shown=shown):
                _write_overrides(self.root, {"swarm": ((model, stored),)})
                payload = _payload(self.root)
                self.assertRegex(_row_of(_frame(payload, "swarm", width=120), "swarm"), rf"\+ +{re.escape(shown)} +◆ override")


class EnterStaysOpenTests(unittest.TestCase):
    """Enter on a pressed effort off its head's list keeps the whole session."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _carry_xhigh_onto_argon(self, payload) -> list[str]:
        # On deep press + (high to xhigh), then step the head to a model whose
        # ladder stops at high. Each piece is legal; together a save refuses.
        return _down_to(payload, "deep") + [KEY_PLUS] + _rights_to(payload, "claude-opus-5-5", "gemini-4-argon")

    def test_the_refused_row_is_named_and_a_fix_then_saves_every_edit(self) -> None:
        payload = _payload(self.root)
        keys = self._carry_xhigh_onto_argon(payload) + ["up", KEY_PLUS, KEY_ENTER]
        _, frames = _drive(payload, keys)
        self.assertIn("! deep: xhigh is not on gemini-4-argon's list; −/+ or d", frames[-1])
        # The cursor went to the row the sentence names, so the next key fixes it.
        self.assertIn(f" {CURSOR_MARK} deep ", frames[-1])
        self.assertEqual(sum("is not on gemini-4-argon's list; −/+" in line for line in frames[-1].splitlines()), 1)

        result, frames = _drive(payload, keys + [KEY_MINUS, KEY_ENTER])
        self.assertNotIn("is not on gemini-4-argon's list; −/+", frames[-1])
        self.assertEqual(result["deep"][0], ("gemini-4-argon", "high"))
        self.assertEqual(result["ultrabrain"], (("gpt-6-astra", "max"),))
        self.assertEqual(result.effort_edits, frozenset({"deep", "ultrabrain"}))

    def test_d_clears_the_refused_row_and_the_other_rows_edit_survives(self) -> None:
        payload = _payload(self.root)
        keys = self._carry_xhigh_onto_argon(payload) + ["up", KEY_PLUS, KEY_ENTER, KEY_DEFAULT, KEY_ENTER]
        result, _ = _drive(payload, keys)
        self.assertEqual(result, {"ultrabrain": (("gpt-6-astra", "max"),)})

    def test_switching_the_head_onto_a_list_holding_the_value_also_saves(self) -> None:
        payload = _payload(self.root)
        keys = self._carry_xhigh_onto_argon(payload) + [KEY_ENTER, KEY_LEFT, KEY_LEFT, KEY_ENTER]
        result, _ = _drive(payload, keys)
        self.assertEqual(result["deep"][0], ("claude-sonnet-5-5", "xhigh"))

    def test_a_row_back_to_exactly_what_is_stored_is_no_edit_to_refuse(self) -> None:
        # Argon's stored xhigh is off its list. Stepped away, pressed down and
        # up, and stepped back, the row is what the file already holds.
        _write_overrides(self.root, {"swarm": (("gemini-4-argon", "xhigh"),)})
        payload = _payload(self.root)
        out = _rights_to(payload, "gemini-4-argon", "gpt-6-astra")
        back = [KEY_LEFT] * len(out)
        result, _ = _drive(payload, _down_to(payload, "swarm") + out + [KEY_MINUS, KEY_PLUS] + back + [KEY_ENTER])
        self.assertEqual(result, {})

    def test_cancel_after_a_refused_enter_still_hands_back_nothing(self) -> None:
        payload = _payload(self.root)
        result, frames = _drive(payload, self._carry_xhigh_onto_argon(payload) + [KEY_ENTER, KEY_QUIT])
        self.assertIsNone(result)
        self.assertIn("! deep: xhigh", frames[-1])

    def test_two_refused_rows_are_named_top_down_and_the_second_fix_saves(self) -> None:
        # deep sits above swarm, and Enter names deep though the cursor is on swarm.
        _write_overrides(self.root, {"swarm": (("claude-opus-5-5", "high"),)})
        payload = _payload(self.root)
        walk = _rights_to(payload, "claude-opus-5-5", "gemini-4-argon")
        keys = self._carry_xhigh_onto_argon(payload)
        keys += [KEY_DOWN] * (_row_index(payload, "swarm") - _row_index(payload, "deep"))
        keys += [KEY_PLUS, *walk, KEY_ENTER]
        result, frames = _drive(payload, keys)
        self.assertIsNone(result)
        self.assertIn("! deep: xhigh is not on", frames[-1])
        self.assertIn(f" {CURSOR_MARK} deep ", frames[-1])
        _, frames = _drive(payload, keys + [KEY_MINUS, KEY_ENTER])
        self.assertIn("! swarm: xhigh is not on", frames[-1])
        self.assertIn(f" {CURSOR_MARK} swarm ", frames[-1])
        result, _ = _drive(payload, keys + [KEY_MINUS, KEY_ENTER, KEY_MINUS, KEY_ENTER])
        self.assertEqual(result["deep"][0], ("gemini-4-argon", "high"))
        self.assertEqual(result["swarm"][0], ("gemini-4-argon", "high"))

    def test_a_list_with_no_rungs_offers_the_keys_that_can_still_move_the_row(self) -> None:
        _write_efforts(self.root, {"gemini-4-argon": []})
        payload = _payload(self.root)
        _, frames = _drive(payload, self._carry_xhigh_onto_argon(payload) + [KEY_ENTER])
        self.assertIn("! deep: xhigh is not on gemini-4-argon's list; ←→ or d", frames[-1])

    def test_a_shared_step_value_saves_and_one_carried_from_a_wider_ladder_does_not(self) -> None:
        # `max` and `none` are on no shared step: pressing to them on a contract
        # head and then switching to a model with no ladder stays open.
        for stored, key, carried in (("xhigh", KEY_PLUS, "max"), ("low", KEY_MINUS, "none")):
            with self.subTest(carried=carried):
                _write_overrides(self.root, {"swarm": (("gpt-6-luna", stored),)})
                payload = _payload(self.root)
                keys = _down_to(payload, "swarm") + [key] + _rights_to(payload, "gpt-6-luna", "grok-4.7") + [KEY_ENTER]
                result, frames = _drive(payload, keys)
                self.assertIsNone(result)
                self.assertIn(f"! swarm: {carried} is not on grok-4.7's list; −/+ or d", frames[-1])
                result, _ = _drive(payload, keys + [KEY_DEFAULT, KEY_ENTER])
                self.assertIsNotNone(result)
        _write_overrides(self.root, {"swarm": (("gpt-6-luna", "low"),)})
        payload = _payload(self.root)
        keys = _down_to(payload, "swarm") + [KEY_PLUS] + _rights_to(payload, "gpt-6-luna", "grok-4.7") + [KEY_ENTER]
        result, _ = _drive(payload, keys)
        self.assertEqual(result["swarm"], (("grok-4.7", "medium"),))

    def test_a_shorter_frame_leaves_no_ghost_lines_below_it(self) -> None:
        # Luna at `none` carries one explaining line more than at `low`, and a
        # refused Enter one more again, so the frame shrinks on the next key.
        _write_overrides(self.root, {"swarm": (("gpt-6-luna", "low"),)})
        payload = _payload(self.root)
        moves = _down_to(payload, "swarm")
        to_argon = _rights_to(payload, "gpt-6-luna", "gemini-4-argon")
        for keys in ([KEY_MINUS, KEY_PLUS], [KEY_PLUS, *to_argon, KEY_ENTER, KEY_MINUS]):
            with self.subTest(keys=keys):
                _, frames = _drive(payload, moves + keys)
                self.assertLess(frames[-1].count("\n"), frames[-2].count("\n"))
                visible = [re.sub(r"\x1b\[[0-9]*[AJK]", "", line) for line in frames[-1].splitlines()]
                self.assertEqual(_screen_after(frames), [line for line in visible if line])


class EffortSaveTests(unittest.TestCase):
    """The save rechecks only what a press produced, against the file as it is now."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.document = _omh_home(self.root) / "routing" / "model-chains.json"

    def _apply(self, changes) -> dict[str, object]:
        return apply_picker_changes(_omh_home(self.root), changes, contract_option=contract_effort_option)

    def _stored(self, name: str = "quick") -> list[dict[str, str]]:
        return json.loads(self.document.read_text(encoding="utf-8"))["categories"][name]

    def _surfaces(self, changes_for) -> dict[str, str]:
        """What each entrance reports when the real picker's session is `changes_for`."""
        from omh.tui.app import run_model_chain_picker
        from omh.tui.theme import DEFAULT_THEME

        outcome = {}
        with (
            patch("omh.commands.model_chains.picker_available", return_value=True),
            patch("omh.commands.model_chains.pick_chains_interactively", side_effect=changes_for),
        ):
            status, stdout, stderr = run_cli(["--omh-home", str(_omh_home(self.root)), "model-chains"], output_json=False)
        outcome["cli"] = (status, stdout + stderr)
        outcome["cli_stderr"] = stderr
        with patch("omh.commands.model_chain_picker.run_picker", side_effect=changes_for):
            outcome["tui"] = run_model_chain_picker(
                {"OMH_HOME": str(_omh_home(self.root)), "HERMES_HOME": str(self.root / ".hermes"), "NO_COLOR": "1"},
                DEFAULT_THEME,
                read_key=lambda: KEY_QUIT,
                write=lambda _text: None,
                width=100,
            )
        return outcome

    def test_a_press_recorded_by_either_sign_is_rechecked_against_a_file_edited_meanwhile(self) -> None:
        for key, landed in ((KEY_PLUS, "xhigh"), (KEY_MINUS, "medium")):
            with self.subTest(key=key):
                _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
                before = self.document.read_bytes()
                _write_efforts(self.root, {})
                payload = _payload(self.root)
                changes, _ = _drive(payload, _down_to(payload, "quick") + [key, KEY_ENTER])
                self.assertEqual(changes, {"quick": (("claude-haiku-5-5", landed),)})
                _write_efforts(self.root, {"claude-haiku-5-5": ["high"]})
                self.assertIn("is not selectable", self._apply(changes)["error"])
                self.assertEqual(self.document.read_bytes(), before)

    def test_an_effort_press_saves_over_a_tail_off_its_own_ladder(self) -> None:
        # Only the head was pressed. Shipped: gpt-6.1-sol:medium leads a tail
        # with kimi-k3.1-pro:medium, a rung Kimi's contract does not list.
        tail = HERMES_MIXTURE_CATEGORY_CHAINS["unspecified-high"][1:]
        self.assertIn(("kimi-k3.1-pro", "medium"), tail)
        self.assertNotIn("medium", contract_effort_option("kimi-k3.1-pro")["efforts"])
        payload = _payload(self.root)
        changes, _ = _drive(payload, _down_to(payload, "unspecified-high") + [KEY_PLUS, KEY_ENTER])
        self.assertEqual(changes, {"unspecified-high": (("gpt-6.1-sol", "high"),) + tail})
        self.assertNotIn("error", self._apply(changes))
        self.assertEqual(self._stored("unspecified-high")[0], {"model": "gpt-6.1-sol", "reasoning_effort": "high"})

    def test_a_model_only_switch_preserves_a_shifted_old_tail(self) -> None:
        _write_overrides(
            self.root, {"quick": (("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "low"), ("deepseek-flash", "medium"))}
        )
        payload = _payload(self.root)
        changes, _ = _drive(payload, _down_to(payload, "quick") + [KEY_RIGHT, KEY_ENTER])
        expected = (("claude-sonnet-5-5", "high"), ("deepseek-flash", "medium"))
        self.assertEqual(changes, {"quick": expected})
        self.assertNotIn("error", self._apply(changes))
        self.assertEqual(self._stored(), [{"model": model, "reasoning_effort": effort} for model, effort in expected])

    def test_an_effort_stepped_away_and_back_after_a_switch_is_still_rechecked(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "high"),)})
        before = self.document.read_bytes()
        payload = _payload(self.root)
        moves = _rights_to(payload, "claude-opus-5-5", "deepseek-flash")
        changes, _ = _drive(payload, _down_to(payload, "quick") + moves + [KEY_MINUS, KEY_PLUS, KEY_ENTER])
        self.assertEqual(changes, {"quick": (("deepseek-flash", "high"),)})
        _write_efforts(self.root, {"deepseek-flash": ["low"]})
        self.assertIn("is not selectable", self._apply(changes)["error"])
        self.assertEqual(self.document.read_bytes(), before)

    def test_reset_drops_the_earlier_press(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "high"),)})
        payload = _payload(self.root)
        changes, _ = _drive(payload, _down_to(payload, "quick") + [KEY_MINUS, KEY_DEFAULT, KEY_ENTER])
        self.assertEqual(changes, {"quick": HERMES_MIXTURE_CATEGORY_CHAINS["quick"]})
        self.assertEqual(changes.effort_edits, frozenset())
        self.assertNotIn("error", self._apply(changes))
        self.assertNotIn("quick", json.loads(self.document.read_text(encoding="utf-8"))["categories"])

    def test_a_switch_saves_what_a_press_would_have_refused(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "xhigh"),)})
        switched = self._apply(PickerChanges({"quick": (("deepseek-flash", "xhigh"),)}))
        self.assertNotIn("error", switched)
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "xhigh"}])
        pressed = PickerChanges({"quick": (("deepseek-flash", "medium"),)}, effort_edits=frozenset({"quick"}))
        self.assertIn("is not selectable", self._apply(pressed)["error"])
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "xhigh"}])

    def test_the_shared_steps_are_what_an_unconfigured_press_is_checked_against(self) -> None:
        for model in ("glm-5.3", "my-custom"):
            for effort in PICKER_EFFORT_RING:
                with self.subTest(model=model, effort=effort):
                    changes = PickerChanges({"quick": ((model, effort),)}, effort_edits=frozenset({"quick"}))
                    self.assertNotIn("error", self._apply(changes))
                    self.assertEqual(self._stored(), [{"model": model, "reasoning_effort": effort}])
            for effort in ("none", "max"):
                with self.subTest(model=model, effort=effort):
                    changes = PickerChanges({"quick": ((model, effort),)}, effort_edits=frozenset({"quick"}))
                    self.assertIn("is not selectable", self._apply(changes)["error"])
                    self.assertEqual(self._stored()[0]["reasoning_effort"], PICKER_EFFORT_RING[-1])

    def test_an_empty_list_written_while_open_refuses_a_press(self) -> None:
        _write_overrides(self.root, {"quick": (("glm-5.3", "high"),)})
        _write_efforts(self.root, {"glm-5.3": []})
        refused = self._apply(PickerChanges({"quick": (("glm-5.3", "low"),)}, effort_edits=frozenset({"quick"})))
        self.assertIn("is not selectable", refused["error"])
        self.assertEqual(self._stored(), [{"model": "glm-5.3", "reasoning_effort": "high"}])

    def test_both_entrances_save_a_rung_only_the_contract_lists(self) -> None:
        changes = PickerChanges({"quick": (("claude-opus-5-5", "max"),)}, effort_edits=frozenset({"quick"}))
        outcome = self._surfaces(lambda *_args, **_kwargs: changes)
        self.assertEqual(outcome["cli"][0], 0, outcome["cli"][1])
        self.assertIn("Saved 1 category", outcome["tui"])

    def test_both_entrances_read_the_file_again_after_the_picker_closes(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-opus-5-5", "high"),)})
        before = self.document.read_bytes()

        def pick_then_narrow(payload, **_kwargs):
            _write_efforts(self.root, {})
            fresh = _payload(self.root)
            changes, _ = _drive(fresh, _down_to(fresh, "quick") + [KEY_MINUS, KEY_ENTER])
            self.assertEqual(changes, {"quick": (("claude-opus-5-5", "medium"),)})
            _write_efforts(self.root, {"claude-opus-5-5": ["high"]})
            return changes

        outcome = self._surfaces(pick_then_narrow)
        self.assertEqual(outcome["cli"][0], 2)
        self.assertIn("omh: did not save: effort 'medium' is not selectable", outcome["cli"][1])
        self.assertIn("/omh-model did not save: effort 'medium' is not selectable", outcome["tui"])
        self.assertEqual(self.document.read_bytes(), before)

    def test_both_entrances_refuse_a_press_when_the_file_broke_while_open(self) -> None:
        _write_overrides(self.root, {"quick": (("claude-haiku-5-5", "low"),)})
        before = self.document.read_bytes()
        changes = PickerChanges({"quick": (("claude-haiku-5-5", "high"),)}, effort_edits=frozenset({"quick"}))
        effort_path = _omh_home(self.root) / "routing" / "model-efforts.json"

        def break_document(*_args, **_kwargs):
            effort_path.write_text("{", encoding="utf-8")
            return changes

        outcome = self._surfaces(break_document)
        self.assertEqual(outcome["cli"][0], 2)
        self.assertIn("model-efforts.json is invalid", outcome["cli"][1])
        self.assertIn("/omh-model did not save: model-efforts.json is invalid", outcome["tui"])
        self.assertEqual(self.document.read_bytes(), before)

    def test_a_model_only_edit_saves_through_a_broken_file_and_both_entrances_warn(self) -> None:
        effort_path = _omh_home(self.root) / "routing" / "model-efforts.json"
        effort_path.parent.mkdir(parents=True, exist_ok=True)
        effort_path.write_text("{", encoding="utf-8")
        changes = PickerChanges({"quick": (("deepseek-flash", "xhigh"),)})
        outcome = self._surfaces(lambda *_args, **_kwargs: changes)
        self.assertEqual(outcome["cli"][0], 0)
        self.assertIn("omh: warning: model-efforts.json ignored: unreadable JSON", outcome["cli_stderr"])
        self.assertIn("Saved 1 category", outcome["tui"])
        self.assertIn("Warning: model-efforts.json ignored: unreadable JSON", outcome["tui"])
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "xhigh"}])

    def test_the_replace_goes_through_the_windows_retry(self) -> None:
        # Windows denies a replace while a reader holds the target, and the CLI
        # picker saved through a retrying writer before it shared this one.
        with patch(
            "omh.plugin_bundle.omh.model_chain_picker._with_windows_retry", side_effect=lambda operation: operation()
        ) as retry:
            self.assertNotIn("error", self._apply(PickerChanges({"quick": (("deepseek-flash", "low"),)})))
        retry.assert_called_once()
        self.assertEqual(self._stored(), [{"model": "deepseek-flash", "reasoning_effort": "low"}])

    def test_both_entrances_hand_the_picker_the_same_resolved_ladders(self) -> None:
        captured = []

        def capture(payload, **_kwargs):
            captured.append(payload["models"])
            return None

        self._surfaces(capture)
        self.assertEqual(captured[0], captured[1])
        by_alias = {row["alias"]: row for row in captured[0]}
        self.assertIn("none", by_alias["claude-haiku-5-5"]["efforts"])
        self.assertFalse(by_alias["glm-5.3"]["efforts_configured"])

    def test_model_chains_set_keeps_its_unchecked_semantics(self) -> None:
        base = ["--omh-home", str(_omh_home(self.root))]
        status, stdout, stderr = run_cli(base + ["model-chains", "set", "quick", "deepseek-flash:medium"], output_json=False)
        self.assertEqual((status, stderr), (0, ""), stdout)
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
            changes = PickerChanges({"quick": OVERRIDE_QUICK, "writing": HERMES_MIXTURE_CATEGORY_CHAINS["writing"]})
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
