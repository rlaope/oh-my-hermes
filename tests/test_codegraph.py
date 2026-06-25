from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from omh.commands.main import build_parser


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sample_repo(root: Path) -> None:
    _write(
        root / "pyproject.toml",
        """
[project.scripts]
demo = "pkg.cli:amain"
""".lstrip(),
    )
    _write(root / "pkg" / "__init__.py", "")
    _write(
        root / "pkg" / "core.py",
        """
class Runner:
    def start(self):
        return "ok"

def run():
    return Runner().start()
""".lstrip(),
    )
    _write(
        root / "pkg" / "cli.py",
        """
import os
from pkg.core import Runner, run

async def amain():
    return run()

class Cli:
    def execute(self):
        return Runner().start()
""".lstrip(),
    )
    _write(
        root / "tests" / "test_core.py",
        """
from pkg.core import run

def test_run():
    assert run() == "ok"
""".lstrip(),
    )
    _write(
        root / "src" / "commands" / "demo.py",
        """
def cmd_demo(args):
    return 0
""".lstrip(),
    )
    _write(
        root / "src" / "plugin_bundle" / "omh" / "tools" / "demo_tool.py",
        """
def demo_tool_handler(args):
    return args
""".lstrip(),
    )


class CodegraphTests(unittest.TestCase):
    def test_build_graph_json_shape_and_internal_edges(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _sample_repo(repo)

            from omh.codegraph import build_codegraph

            graph = build_codegraph(repo, generated_at="2026-01-01T00:00:00Z")

        self.assertEqual(graph["schema_version"], "omh_codegraph/v1")
        self.assertEqual(graph["generated_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(graph["stats"]["parse_error_count"], 0)
        self.assertIn("Static local analysis is not execution/review/CI/merge evidence", graph["claim_boundary"])

        files = {record["path"]: record for record in graph["files"]}
        self.assertEqual(files["pkg/cli.py"]["kind"], "python")
        self.assertIn("package_script:demo", files["pkg/cli.py"]["entrypoint_tags"])
        self.assertIn("cli_command", files["src/commands/demo.py"]["entrypoint_tags"])
        self.assertIn("plugin_tool", files["src/plugin_bundle/omh/tools/demo_tool.py"]["entrypoint_tags"])
        self.assertIn("test", files["tests/test_core.py"]["entrypoint_tags"])

        cli_imports = {(item["kind"], item["module"], item.get("name")) for item in files["pkg/cli.py"]["imports"]}
        self.assertIn(("import", "os", None), cli_imports)
        self.assertIn(("from_import", "pkg.core", "Runner"), cli_imports)
        self.assertIn("pkg.cli.amain", files["pkg/cli.py"]["defines"])
        self.assertIn("pkg.cli.Cli.execute", files["pkg/cli.py"]["defines"])

        symbols = {record["qualified_name"]: record for record in graph["symbols"]}
        self.assertEqual(symbols["pkg.core.Runner"]["kind"], "class")
        self.assertEqual(symbols["pkg.cli.amain"]["kind"], "async_function")

        internal_imports = {
            (edge["from"], edge["to"])
            for edge in graph["edges"]
            if edge["kind"] == "imports_internal"
        }
        self.assertIn(("pkg/cli.py", "pkg/core.py"), internal_imports)

    def test_build_command_writes_artifact_and_prints_json(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _sample_repo(repo)

            status, stdout, stderr = run_cli(["codegraph", "build", "--repo", str(repo), "--write", "--json"])

            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            artifact_path = repo.resolve() / ".omh" / "codegraph" / "codegraph.json"
            self.assertTrue(artifact_path.exists())
            written = json.loads(artifact_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "omh_codegraph/v1")
        self.assertEqual(written["schema_version"], "omh_codegraph/v1")
        self.assertEqual(payload["artifact_path"], str(artifact_path))
        self.assertEqual(written["artifact_path"], str(artifact_path))

    def test_summary_human_output_keeps_boundary_visible(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _sample_repo(repo)

            status, stdout, stderr = run_cli(["codegraph", "summary", "--repo", str(repo)], output_json=False)

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertIn("OMH codegraph summary", stdout)
        self.assertIn("Files:", stdout)
        self.assertIn("Static local analysis is not execution/review/CI/merge evidence", stdout)

    def test_handoff_context_is_compact_prepared_context(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _sample_repo(repo)

            status, stdout, stderr = run_cli(
                ["codegraph", "handoff", "--repo", str(repo), "--task", "update runner command", "--json"],
                output_json=False,
            )

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], "omh_codegraph_context/v1")
        self.assertEqual(payload["task"], "update runner command")
        self.assertIn("Static local analysis is not execution/review/CI/merge evidence", payload["claim_boundary"])
        candidate_paths = {item["path"] for item in payload["focus_files"]}
        self.assertIn("pkg/core.py", candidate_paths)
        self.assertLessEqual(len(payload["focus_files"]), 12)
        self.assertLessEqual(len(payload["focus_symbols"]), 20)

    def test_parse_errors_are_file_warnings_not_command_failures(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write(repo / "good.py", "def ok():\n    return True\n")
            _write(repo / "broken.py", "def bad(:\n")

            status, stdout, stderr = run_cli(["codegraph", "build", "--repo", str(repo), "--json"])

        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        files = {record["path"]: record for record in payload["files"]}
        self.assertEqual(payload["stats"]["parse_error_count"], 1)
        self.assertIn("parse_error", files["broken.py"])
        self.assertTrue(any("broken.py" in warning for warning in payload["warnings"]))
        self.assertIn("good.ok", files["good.py"]["defines"])

    def test_src_layout_package_dir_does_not_invent_omh_modules(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write(
                repo / "pyproject.toml",
                """
[tool.setuptools.package-dir]
realpkg = "src/realpkg"
""".lstrip(),
            )
            _write(repo / "src" / "realpkg" / "core.py", "def run():\n    return 1\n")
            _write(repo / "src" / "realpkg" / "cli.py", "from .core import run\n\ndef main():\n    return run()\n")

            from omh.codegraph import build_codegraph

            graph = build_codegraph(repo, generated_at="2026-01-01T00:00:00Z")

        files = {record["path"]: record for record in graph["files"]}
        self.assertIn("realpkg.cli.main", files["src/realpkg/cli.py"]["defines"])
        self.assertNotIn("omh.realpkg.cli.main", files["src/realpkg/cli.py"]["defines"])
        self.assertIn(
            ("src/realpkg/cli.py", "src/realpkg/core.py"),
            {
                (edge["from"], edge["to"])
                for edge in graph["edges"]
                if edge["kind"] == "imports_internal"
            },
        )

    def test_package_dir_name_is_canonical_before_src_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write(
                repo / "pyproject.toml",
                """
[tool.setuptools.package-dir]
omh = "src"
""".lstrip(),
            )
            _write(repo / "src" / "codegraph" / "schema.py", "VALUE = 1\n")
            _write(repo / "src" / "codegraph" / "scanner.py", "from .schema import VALUE\n\ndef build():\n    return VALUE\n")

            from omh.codegraph import build_codegraph

            graph = build_codegraph(repo, generated_at="2026-01-01T00:00:00Z")

        files = {record["path"]: record for record in graph["files"]}
        self.assertIn("omh.codegraph.scanner.build", files["src/codegraph/scanner.py"]["defines"])
        self.assertNotIn("codegraph.scanner.build", files["src/codegraph/scanner.py"]["defines"])
        self.assertIn(
            ("src/codegraph/scanner.py", "src/codegraph/schema.py"),
            {
                (edge["from"], edge["to"])
                for edge in graph["edges"]
                if edge["kind"] == "imports_internal"
            },
        )

    def test_scanner_skips_python_symlink_files(self) -> None:
        with TemporaryDirectory() as tmp, TemporaryDirectory() as outside_tmp:
            repo = Path(tmp)
            outside = Path(outside_tmp) / "outside.py"
            outside.write_text("def outside_symbol():\n    return True\n", encoding="utf-8")
            (repo / "linked.py").symlink_to(outside)
            _write(repo / "inside.py", "def inside_symbol():\n    return True\n")

            from omh.codegraph import build_codegraph

            graph = build_codegraph(repo, generated_at="2026-01-01T00:00:00Z")

        paths = {record["path"] for record in graph["files"]}
        qualified_names = {symbol["qualified_name"] for symbol in graph["symbols"]}
        self.assertEqual(paths, {"inside.py"})
        self.assertIn("inside.inside_symbol", qualified_names)
        self.assertNotIn("linked.outside_symbol", qualified_names)
        self.assertTrue(any("skipped_symlink: linked.py" in warning for warning in graph["warnings"]))

    def test_build_write_filesystem_error_is_cli_error_not_traceback(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write(repo / "keep.py", "def keep():\n    return True\n")
            (repo / ".omh").write_text("not a directory", encoding="utf-8")

            status, stdout, stderr = run_cli(["codegraph", "build", "--repo", str(repo), "--write"])

        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertIn("omh:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_scanner_excludes_runtime_and_build_directories(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write(repo / "keep.py", "def keep():\n    return True\n")
            for rel_path in (
                ".git/ignored.py",
                ".venv/ignored.py",
                "venv/ignored.py",
                "__pycache__/ignored.py",
                ".mypy_cache/ignored.py",
                ".pytest_cache/ignored.py",
                ".ruff_cache/ignored.py",
                ".omh/codegraph/ignored.py",
                "node_modules/ignored.py",
                "dist/ignored.py",
                "build/ignored.py",
            ):
                _write(repo / rel_path, "def ignored():\n    return False\n")

            from omh.codegraph import build_codegraph

            graph = build_codegraph(repo, generated_at="2026-01-01T00:00:00Z")

        paths = {record["path"] for record in graph["files"]}
        self.assertEqual(paths, {"keep.py"})

    def test_codegraph_command_is_wired_into_root_help(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("codegraph", help_text)
        self.assertIn("Build static local codegraph artifacts", help_text)


if __name__ == "__main__":
    unittest.main()
