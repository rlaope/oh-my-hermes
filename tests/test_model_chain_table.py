"""Contract for the generated shipped-chain table in docs/INSTALLATION.md.

The table is the public projection of `SHIPPED_MODEL_RECOMMENDATIONS`. It was
hand-maintained until this module's producer existed, so these tests pin both
halves of the gate:

1. the checked-in region is current, and the projection is faithful in the
   direction the byte check cannot see -- every documented display label maps
   back to the alias and effort the catalog actually ships;
2. the failure surface. A stale table must name the row and both strings, a
   missing purpose or display label must name the key to add, and a surface
   that gains or loses a chain must be reported as that row rather than as a
   byte difference somewhere in a file.

Point 2 is deliberate: a projection gate whose only output is "stale" sends
the reader diffing the whole document to find which chain moved.
"""

from __future__ import annotations

import unittest
from copy import deepcopy
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.catalogs.model_chain_table import (
    CHAIN_SURFACE_PURPOSES,
    MODEL_CHAIN_TABLE_PATH,
    MODEL_CHAIN_TABLE_REGION_BEGIN,
    MODEL_CHAIN_TABLE_REGION_END,
    MODEL_DISPLAY_LABELS,
    chain_table_rows,
    installation_with_generated_region,
    model_chain_table_drift,
    model_chain_table_region,
)
from omh.coding.model_recommendations import (
    HERMES_MODEL_SETUP_ROLE_SLOTS,
    MODEL_RECOMMENDATION_DOMAINS,
    MODEL_RECOMMENDATION_LAST_RESORT_SLOTS,
    SHIPPED_MODEL_RECOMMENDATIONS,
)
from omh.coding.model_routing import MODEL_CATEGORIES
from omh.maintenance.drift import repo_root_default

REPO_ROOT = repo_root_default()


def _installation_text() -> str:
    return (REPO_ROOT / MODEL_CHAIN_TABLE_PATH).read_text(encoding="utf-8")


def _catalog_chain(section: str, key: str) -> list[tuple[str, str]]:
    chain = SHIPPED_MODEL_RECOMMENDATIONS[section][key]  # type: ignore[index]
    return [(entry["model_alias"], entry["reasoning_effort"]) for entry in chain]


def _documented_chain(order_cell: str) -> list[tuple[str, str]]:
    """Read one rendered order cell back into (alias, effort) pairs.

    The reader is the inverse of the renderer: one effort token per entry,
    bound to that entry, and no token where the catalog declares none. Labels
    resolve through the same map the renderer used, so a label that does not
    round-trip fails here instead of reading as plausible prose.
    """
    label_to_alias = {label: alias for alias, label in MODEL_DISPLAY_LABELS.items()}
    entries: list[tuple[str, str]] = []
    # No shipped display label contains a comma, so ", " separates entries.
    for chunk in order_cell.split(", "):
        chunk = chunk.strip()
        effort = ""
        if chunk.endswith("`)") and " (`" in chunk:
            chunk, _, tail = chunk.rpartition(" (`")
            effort = tail[:-2]
        entries.append((label_to_alias[chunk], effort))
    return entries


class GeneratedChainTableTests(unittest.TestCase):
    def test_checked_in_region_is_current(self) -> None:
        text = _installation_text()
        self.assertIn(MODEL_CHAIN_TABLE_REGION_BEGIN, text)
        self.assertIn(MODEL_CHAIN_TABLE_REGION_END, text)
        self.assertEqual(installation_with_generated_region(text), text)
        self.assertEqual(model_chain_table_drift(text), ())

    def test_every_shipped_chain_surface_has_a_row(self) -> None:
        rows = chain_table_rows()
        expected_ids = (
            [f"role.{slot}" for slot in HERMES_MODEL_SETUP_ROLE_SLOTS]
            + list(MODEL_CATEGORIES)
            + [f"domain.{domain}" for domain in MODEL_RECOMMENDATION_DOMAINS]
            + [f"last_resort.{slot}" for slot in MODEL_RECOMMENDATION_LAST_RESORT_SLOTS]
        )
        self.assertEqual([row.row_id for row in rows], expected_ids)
        documented = _installation_text()
        for row in rows:
            self.assertIn(f"| {row.surface} | {row.purpose} | {row.order} |", documented)

    def test_documented_orders_round_trip_to_the_catalog(self) -> None:
        """The byte gate proves the doc equals the renderer; this proves the
        renderer equals the catalog, alias and effort included."""
        by_id = {row.row_id: row for row in chain_table_rows()}
        for slot in HERMES_MODEL_SETUP_ROLE_SLOTS:
            self.assertEqual(
                _documented_chain(by_id[f"role.{slot}"].order),
                _catalog_chain("role_suggestions", slot),
            )
        for category in MODEL_CATEGORIES:
            self.assertEqual(
                _documented_chain(by_id[category].order),
                _catalog_chain("categories", category),
            )
        for domain in MODEL_RECOMMENDATION_DOMAINS:
            self.assertEqual(
                _documented_chain(by_id[f"domain.{domain}"].order),
                _catalog_chain("domain_affinities", domain),
            )
        for slot in MODEL_RECOMMENDATION_LAST_RESORT_SLOTS:
            self.assertEqual(
                _documented_chain(by_id[f"last_resort.{slot}"].order),
                _catalog_chain("last_resort", slot),
            )

    def test_undeclared_effort_prints_no_token(self) -> None:
        """`role.main` mixes declared and undeclared effort, which is exactly
        the row a trailing-token rendering would have made unreadable."""
        main = {row.row_id: row for row in chain_table_rows()}["role.main"]
        self.assertEqual(
            main.order,
            "GPT-6.1 Sol (`high`), Claude Opus 5.5, Claude Fable 5.1, "
            "GPT-6 Astra (`xhigh`), Kimi K3.1 Pro",
        )

    def test_every_declared_effort_is_annotated_on_its_own_entry(self) -> None:
        architect = {row.row_id: row for row in chain_table_rows()}["architect"]
        self.assertEqual(
            architect.order,
            "Claude Opus 5.5 (`xhigh`), GPT-6 Astra (`xhigh`), "
            "Claude Fable 5.1 (`xhigh`), Kimi K3.1 Pro (`xhigh`)",
        )

    def test_empty_chain_renders_without_inventing_a_model(self) -> None:
        catalog = deepcopy(dict(SHIPPED_MODEL_RECOMMENDATIONS))
        catalog["categories"] = dict(catalog["categories"])  # type: ignore[arg-type]
        catalog["categories"]["artistry"] = []  # type: ignore[index]
        row = {row.row_id: row for row in chain_table_rows(catalog)}["artistry"]
        self.assertEqual(row.order, "(none shipped)")


class ChainTableFailureSurfaceTests(unittest.TestCase):
    def test_stale_row_is_named_with_both_orders(self) -> None:
        text = _installation_text().replace(
            "| `ultrabrain` | Deepest reasoning | Claude Fable 5.1 (`xhigh`), GPT-6 Astra (`xhigh`), "
            "Claude Opus 5.5 (`xhigh`) |",
            "| `ultrabrain` | Deepest reasoning | GPT-5.6 Sol (`xhigh`) |",
        )
        findings = model_chain_table_drift(text)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("`ultrabrain`", findings[0])
        self.assertIn("GPT-5.6 Sol (`xhigh`)", findings[0])
        self.assertIn("Claude Fable 5.1 (`xhigh`), GPT-6 Astra (`xhigh`), Claude Opus 5.5 (`xhigh`)", findings[0])

    def test_stale_purpose_is_reported_as_that_row(self) -> None:
        text = _installation_text().replace(
            "| `quick` | Short tasks |", "| `quick` | Tiny tasks |"
        )
        findings = model_chain_table_drift(text)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("`quick`", findings[0])
        self.assertIn("Tiny tasks", findings[0])
        self.assertIn("Short tasks", findings[0])

    def test_missing_row_is_reported_as_a_missing_surface(self) -> None:
        text = _installation_text()
        dropped = [
            line
            for line in text.splitlines(keepends=True)
            if not line.startswith("| `writing` |")
        ]
        findings = model_chain_table_drift("".join(dropped))
        self.assertTrue(
            any("`writing`" in finding and "missing from the table" in finding for finding in findings),
            findings,
        )

    def test_unknown_row_is_reported_as_not_a_shipped_surface(self) -> None:
        text = _installation_text().replace(
            MODEL_CHAIN_TABLE_REGION_END,
            "| `invented` | Nothing | Kimi K3 |\n" + MODEL_CHAIN_TABLE_REGION_END,
        )
        findings = model_chain_table_drift(text)
        self.assertTrue(
            any("`invented`" in finding and "not a shipped chain surface" in finding for finding in findings),
            findings,
        )

    def test_region_without_markers_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            model_chain_table_drift("no generated region here\n")
        self.assertIn("markers", str(caught.exception))

    def test_surface_without_a_purpose_names_the_key_to_add(self) -> None:
        purposes = dict(CHAIN_SURFACE_PURPOSES)
        purposes.pop("quick")
        with patch.dict(CHAIN_SURFACE_PURPOSES, purposes, clear=True):
            with self.assertRaises(ValueError) as caught:
                chain_table_rows()
        message = str(caught.exception)
        self.assertIn("'quick'", message)
        self.assertIn("CHAIN_SURFACE_PURPOSES", message)
        self.assertIn("src/catalogs/model_chain_table.py", message)

    def test_model_without_a_display_label_names_the_alias(self) -> None:
        labels = dict(MODEL_DISPLAY_LABELS)
        labels.pop("kimi-k3.1-pro")
        with patch.dict(MODEL_DISPLAY_LABELS, labels, clear=True):
            with self.assertRaises(ValueError) as caught:
                chain_table_rows()
        message = str(caught.exception)
        self.assertIn("'kimi-k3.1-pro'", message)
        self.assertIn("MODEL_DISPLAY_LABELS", message)
        self.assertIn("src/catalogs/model_chain_table.py", message)

    def test_generated_region_keeps_the_document_around_it(self) -> None:
        text = _installation_text()
        start = text.index(MODEL_CHAIN_TABLE_REGION_BEGIN)
        stop = text.index(MODEL_CHAIN_TABLE_REGION_END) + len(MODEL_CHAIN_TABLE_REGION_END)
        hand_edited = (
            text[:start]
            + MODEL_CHAIN_TABLE_REGION_BEGIN
            + "\n| hand | edited | row |\n"
            + MODEL_CHAIN_TABLE_REGION_END
            + text[stop:]
        )
        rewritten = installation_with_generated_region(hand_edited)
        self.assertEqual(rewritten, text)
        self.assertIn("The shipped catalog is editorial policy", rewritten)
        self.assertIn(model_chain_table_region(), rewritten)


if __name__ == "__main__":
    unittest.main()
