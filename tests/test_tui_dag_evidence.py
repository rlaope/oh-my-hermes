"""The real /dag command reads and renders only the selected session's node."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.tui.dag_evidence import CATALOG, HANDOFF_BYTES, evidence, evidence_lines, read_handoff  # noqa: E402
from omh.tui.keys import CHAR, TAB, Key  # noqa: E402
from test_dag_panels import NODES, THEME  # noqa: E402
from test_tui_delegation_block import press, screen, with_hud  # noqa: E402
from test_tui_modes import make_app  # noqa: E402
from test_tui_muscle_memory import send  # noqa: E402
from _delegation_graphs import dag_export_run  # noqa: E402


def owned_graph() -> dict:
    graph = dag_export_run()
    graph["scope"] = "session"
    for node in graph["nodes"][1:]:
        node["dag_node"] = node["id"].split(":")[-1]
    return graph


def seed(home: Path, session: str, *, record_session: str | None = None) -> Path:
    record = dag_run.new_record(record_session or session, "r1", "Export", "Show evidence", NODES, time.time())
    handoff = dag_run.handoff_path(home, session, "r1", "api")
    handoff.parent.mkdir(parents=True, exist_ok=True)
    dag_run.write_run(dag_run.record_path(home, session, "r1"), record)
    handoff.write_text("# Verified export\n\n- Contract passed\n- [Build log](https://example.invalid/build)",
                       encoding="utf-8")
    handoff.with_name("ui.md").write_text("SIBLING SECRET", encoding="utf-8")
    return handoff


def text(rows) -> str:
    return "\n".join("".join(span.text for span in row) for row in rows)


class DagEvidenceImportTests(unittest.TestCase):
    def test_the_tui_loads_the_dag_record_reader_only_when_evidence_is_read(self) -> None:
        # A fresh interpreter: this process imported dag_run above.
        probe = (
            "import sys, tempfile\n"
            "import omh.tui.app\n"
            "names = ('omh.plugin_bundle.omh.dag_run', 'omh.plugin_bundle.omh.runtime_reader')\n"
            "print('after import:', [name for name in names if name in sys.modules])\n"
            "from omh.tui.dag_evidence import read_handoff\n"
            "with tempfile.TemporaryDirectory() as home:\n"
            "    print('read:', repr(read_handoff(home, '20261014_000000_aaaaaa', 'd:r1:api')))\n"
            "print('after a read:', 'omh.plugin_bundle.omh.dag_run' in sys.modules)\n"
        )
        done = subprocess.run([sys.executable, "-P", "-c", probe], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), ["after import: []", "read: ''", "after a read: True"])


class DagEvidenceTests(unittest.TestCase):
    def test_catalog_records_drive_the_terminal_and_reject_an_invalid_surface(self) -> None:
        message, fallback = evidence({"title": "Export API", "status": "accepted"}, "- Test passed")
        records = message["createSurface"]["components"]
        self.assertEqual(message["version"], "1.0")
        self.assertEqual(message["createSurface"]["catalogId"], CATALOG)
        self.assertEqual(records[0], {"id": "root", "component": "Card", "child": "body"})
        records[2]["text"] = "Render this record"
        rendered = text(evidence_lines(message, fallback, 80, THEME))
        self.assertIn("Render this record", rendered)
        self.assertNotIn("Export API", rendered)
        self.assertIn("─", rendered)
        for invalid in ("version", "broken-child", "foreign-component", "duplicate", "dynamic"):
            with self.subTest(invalid=invalid):
                rejected = deepcopy(message)
                bad = rejected["createSurface"]["components"]
                if invalid == "version":
                    rejected["version"] = "9.0"
                elif invalid == "broken-child":
                    bad[0]["child"] = ["body"]
                elif invalid == "foreign-component":
                    bad[2]["component"] = "Button"
                elif invalid == "duplicate":
                    bad[2]["id"] = "body"
                else:
                    bad[2]["text"] = {"@path": "/secret"}
                rendered = text(evidence_lines(rejected, fallback, 80, THEME))
                self.assertIn("Basic Catalog unavailable", rendered)
                self.assertIn("Export API", rendered)
                self.assertIn("Test passed", rendered)
                self.assertNotIn("Render this record", rendered)

    def test_nested_link_and_title_targets_are_inert_in_both_render_paths(self) -> None:
        message, fallback = evidence(
            {"title": "[Export](https://example.invalid/private)", "status": "accepted"},
            "[outer [inner](https://inner.invalid/token)](https://outer.invalid/secret)",
        )
        for surface in (message, {**message, "version": "9.0"}):
            with self.subTest(version=surface["version"]):
                rendered = text(evidence_lines(surface, fallback, 100, THEME))
                self.assertIn("Export", rendered)
                self.assertIn("outer inner", rendered)
                for target in ("example.invalid", "inner.invalid", "outer.invalid"):
                    self.assertNotIn(target, rendered)

    def test_nested_bracket_label_targets_are_inert_in_both_render_paths(self) -> None:
        message, fallback = evidence(
            {"title": "[a [b] c](https://host.invalid/title)", "status": "accepted"},
            "[a [b] c](https://host.invalid/secret)",
        )
        for surface in (message, {**message, "version": "9.0"}):
            with self.subTest(version=surface["version"]):
                rendered = text(evidence_lines(surface, fallback, 100, THEME))
                self.assertIn("a [b] c", rendered)
                self.assertNotIn("host.invalid", rendered)

    def test_escaped_backslashes_and_deep_labels_are_inert_in_both_render_paths(self) -> None:
        escaped = r"\\[Export](https://double.invalid/secret)"
        deep = "[" * 1100 + "Deep label" + "](x)" * 1100
        self.assertLess(len(deep), HANDOFF_BYTES)
        message, fallback = evidence({"title": escaped}, f"{escaped}\n\n{deep}")
        for surface in (message, {**message, "version": "9.0"}):
            with self.subTest(version=surface["version"]):
                rendered = text(evidence_lines(surface, fallback, 100, THEME))
                self.assertIn("Export", rendered)
                self.assertIn("Deep label", rendered)
                self.assertNotIn("double.invalid", rendered)
                self.assertNotIn("](x)", rendered)

    def test_malformed_link_closers_do_not_display_targets(self) -> None:
        sample = "[label\\](https://escaped.invalid/log)\n\n[cross\nline](https://split.invalid/log)"
        message, fallback = evidence({"title": "[title\\](https://title.invalid/log)"}, sample)
        for surface in (message, {**message, "version": "9.0"}):
            with self.subTest(version=surface["version"]):
                rendered = text(evidence_lines(surface, fallback, 100, THEME))
                for label in ("title", "label", "cross", "line"):
                    self.assertIn(label, rendered)
                self.assertNotIn(".invalid", rendered)

    def test_exact_record_ownership_and_bounded_regular_handoff(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            handoff = seed(home, "selected")
            seed(home, "foreign")
            seed(home, "misfiled", record_session="foreign")
            self.assertIn("Contract passed", read_handoff(home, "selected", "d:r1:api"))
            for stored, node in (("missing", "d:r1:api"), ("misfiled", "d:r1:api"),
                                 ("selected", "d:r1:../../api"), ("selected", "d:r1:unlisted"),
                                 ("selected", "d:other:api")):
                self.assertEqual(read_handoff(home, stored, node), "")
            handoff.write_bytes(b"\x1b]52;c;sneak\x07" + b"x" * HANDOFF_BYTES + b"OUTSIDE")
            clipped = read_handoff(home, "selected", "d:r1:api")
            self.assertIn("[Handoff preview clipped]", clipped)
            self.assertNotIn("OUTSIDE", clipped)
            self.assertNotIn("sneak", clipped)
            handoff.unlink()
            if hasattr(os, "mkfifo"):
                os.mkfifo(handoff)
                self.assertEqual(read_handoff(home, "selected", "d:r1:api"), "")
                handoff.unlink()
            if os.name != "nt":
                handoff.symlink_to(dag_run.handoff_path(home, "foreign", "r1", "api"))
                self.assertEqual(read_handoff(home, "selected", "d:r1:api"), "")
                handoff.unlink()
                handoff.with_name("ui.md").unlink()
                handoff.parent.rmdir()
                handoff.parent.symlink_to(dag_run.handoff_path(home, "foreign", "r1", "api").parent)
                self.assertEqual(read_handoff(home, "selected", "d:r1:api"), "")

    def test_dag_keys_refresh_the_read_and_drop_evidence_on_session_change(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            handoff = seed(home, "selected")
            app, client = make_app(rows=50, cols=100, environ={"OMH_HOME": str(home)})
            app.stored_id = "selected"
            graph = owned_graph()
            with_hud(app, graph, received_at=1)
            send(app, "/dag")
            self.assertIn("e Evidence", "\n".join(screen(app)))
            # Running node opens first; navigate back to the accepted API node.
            rows = "\n".join(press(app, Key(TAB, shift=True), Key(CHAR, "e")))
            self.assertIn("Evidence · Export API", rows)
            self.assertIn("Contract passed", rows)
            self.assertIn("Build log", rows)
            self.assertNotIn("example.invalid", rows)
            self.assertNotIn("SIBLING SECRET", rows)
            handoff.write_text("Updated evidence\n[Build log](https://example.invalid/path(foo))", encoding="utf-8")
            updated = "\n".join(press(app, Key(CHAR, "r")))
            self.assertIn("Updated evidence", updated)
            self.assertIn("Build log", updated)
            self.assertNotIn("example.invalid", updated)
            handoff.write_text("Broken [Build log](https://example.invalid/path(foo)\nnext line", encoding="utf-8")
            broken = "\n".join(press(app, Key(CHAR, "r")))
            self.assertIn("Build log", broken)
            self.assertIn("next line", broken)
            self.assertNotIn("example.invalid", broken)
            handoff.write_text("New HUD evidence", encoding="utf-8")
            with_hud(app, graph, received_at=2)
            self.assertIn("New HUD evidence", "\n".join(screen(app)))
            self.assertIn("OMH / DAG", "\n".join(press(app, Key(CHAR, "e"))))
            self.assertEqual(app.pager.node, "d:r1:api")
            press(app, Key(CHAR, "e"))
            app.stored_id = "foreign"
            rows = "\n".join(screen(app))
            self.assertIn("Evidence unavailable", rows)
            self.assertNotIn("New HUD evidence", rows)
            press(app, Key(CHAR, "q"))
            self.assertIsNone(app.pager)
            self.assertEqual(client.calls, [])
            self.assertEqual(client.answers, [])
