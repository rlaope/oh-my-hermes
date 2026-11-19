"""OMH's offline host-fit checker (`omh.skills.harness_fit`).

Every finding class is exercised on a minimal bad skill and shown silent on a
good one, all built in temporary folders. `UpstreamParityTests` pins the
classes to what NVIDIA SkillEvaluator 1.0.1 recorded for this repository at
a5649293: the numbers are copied as literals, each with the evidence file it
came from, so the test needs neither the evidence folder nor the upstream tool.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from unittest import mock
from dataclasses import fields as dataclass_fields
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.skills.harness_fit import SCHEMA, check_catalog, check_skill, hermes_listing  # noqa: E402
from omh.skills.harness_fit_hosts import FACT_FIELDS, HOSTS, SOURCES, HostFacts  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
GOOD = "[omh] Fixture skill to check: does one small thing. Use when the user says: fixture."


def frontmatter(name: str | None, description: str | None, extra: str = "") -> str:
    lines = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {json.dumps(description, ensure_ascii=False)}")
    if extra:
        lines.append(extra)
    lines.append("---")
    return "\n".join(lines) + "\n"


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def skill(self, folder: str, *, root: Path | None = None, name: str | None = "", description: str | None = GOOD,
              body: str = "# Fixture\n\nDo the one thing.\n", extra: str = "", manifest: str = "SKILL.md",
              files: dict[str, str] | None = None) -> Path:
        base = root if root is not None else self.tmp / "pack"
        path = base / folder
        path.mkdir(parents=True, exist_ok=True)
        (path / manifest).write_text(
            frontmatter(folder if name == "" else name, description, extra) + body, encoding="utf-8", newline="")
        for relative, content in (files or {}).items():
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
        return path

    def catalog(self, count: int, length: int, *, root: Path | None = None) -> Path:
        base = root if root is not None else self.tmp / "catalog"
        for index in range(count):
            self.skill(f"s{index:03d}", root=base, description=description_of(length, index))
        return base

    @staticmethod
    def ids(result: dict, host: str | None = None) -> set[str]:
        return {finding["id"] for row in result["hosts"] if host in (None, row["host"]) for finding in row["findings"]}

    @staticmethod
    def row(result: dict, host: str) -> dict:
        return next(row for row in result["hosts"] if row["host"] == host)

    @staticmethod
    def finding(result: dict, finding_id: str) -> dict:
        return next(f for row in result["hosts"] for f in row["findings"] if f["id"] == finding_id)


def description_of(length: int, index: int = 0) -> str:
    """A description of exactly `length` characters whose opening differs per index."""
    lead = f"[omh] Case {index:03d} fixture: "
    return (lead + "x" * length)[:length]


class CleanSkillTests(_Fixture):
    def test_a_clean_skill_loads_on_all_six_hosts_with_no_findings(self):
        result = check_skill(self.skill("clean"))

        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual([row["host"] for row in result["hosts"]],
                         ["hermes", "claude-code", "codex", "openclaw", "opencode", "copilot-cli"])
        for row in result["hosts"]:
            with self.subTest(host=row["host"]):
                self.assertEqual((row["status"], row["findings"], row["root"]), ("loads", [], "not_checked"))
                self.assertTrue(row["verified"]["version"] and row["verified"]["date"] and row["verified"]["source"])
        self.assertEqual((result["static"], result["overlap"]), ([], []))
        self.assertEqual(result["summary"], {"not_loaded": 0, "degraded": 0, "unverified": 0})
        self.assertEqual(result["catalog"]["size"], 1)

    def test_host_selection_and_unknown_hosts(self):
        result = check_skill(self.skill("clean"), hosts=["codex"])
        self.assertEqual([row["host"] for row in result["hosts"]], ["codex"])
        with self.assertRaises(ValueError):
            check_skill(self.skill("clean"), hosts=["cursor"])


class ListingWindowTests(_Fixture):
    def test_hermes_window_fires_when_neither_situation_nor_trigger_is_visible(self):
        long_situation = ("[omh] A situation clause that runs well past the sixty character window: "
                          "does it. Use when the user says: x.")
        result = check_skill(self.skill("late", description=long_situation), hosts=["hermes"])

        self.assertEqual(self.finding(result, "HERMES_DESC_WINDOW")["effect"], "advisory")
        self.assertEqual(self.row(result, "hermes")["status"], "loads")
        for description in (GOOD, "Use when the user asks for a PDF table pulled into CSV with page numbers kept."):
            with self.subTest(description=description):
                self.assertEqual(self.ids(check_skill(self.skill("ok", description=description), hosts=["hermes"])),
                                 set())

    def test_hermes_listing_mirrors_the_word_boundary_clip(self):
        self.assertEqual(hermes_listing("short"), "short")
        # Outputs of hermes-agent 3b4215785882 `clip_skill_description` on these inputs.
        self.assertEqual(hermes_listing("[omh] Software feature or bugfix not yet planned: structured planning"),
                         "[omh] Software feature or bugfix not yet planned...")
        self.assertEqual(hermes_listing("x" * 70), "x" * 57 + "...")

    def test_codex_cuts_over_1024_codepoints(self):
        self.assertIn("CODEX_DESC_WINDOW", self.ids(check_skill(self.skill("a", description="U" * 1025), hosts=["codex"])))
        self.assertEqual(self.ids(check_skill(self.skill("b", description="U" * 1024), hosts=["codex"])), set())

    def test_copilot_counts_utf16_units_and_drops_the_skill(self):
        description = "Use when " + "a" * 991 + "\U0001F600" * 13  # 1,013 codepoints, 1,026 UTF-16 units
        result = check_skill(self.skill("emoji", description=description), hosts=["codex", "copilot-cli"])

        self.assertEqual(self.finding(result, "COPILOT_DESC_WINDOW")["effect"], "not_loaded")
        self.assertEqual(self.row(result, "copilot-cli")["status"], "not_loaded")
        self.assertNotIn("CODEX_DESC_WINDOW", self.ids(result))

    def test_claude_counts_when_to_use_with_the_description(self):
        result = check_skill(self.skill("cc", description="U" * 1500, extra=f"when_to_use: {'w' * 100}"),
                             hosts=["claude-code"])
        self.assertIn("CLAUDE_DESC_WINDOW", self.ids(result))
        self.assertEqual(self.ids(check_skill(self.skill("cc2", description="U" * 1500), hosts=["claude-code"])), set())


class CatalogBudgetTests(_Fixture):
    def test_claude_and_codex_budget_fires_at_124_by_70_and_not_at_100_by_60(self):
        over = check_skill(self.catalog(124, 70, root=self.tmp / "over") / "s000", hosts=["claude-code", "codex"])
        under = check_skill(self.catalog(100, 60, root=self.tmp / "under") / "s000", hosts=["claude-code", "codex"])

        self.assertEqual(over["catalog"]["desc_chars"], 8_680)
        self.assertEqual(self.ids(over), {"CLAUDE_LIST_BUDGET", "CODEX_LIST_BUDGET"})
        self.assertIn("8,000", self.finding(over, "CLAUDE_LIST_BUDGET")["message"])
        self.assertEqual(self.ids(under), set())

    def test_a_known_large_context_raises_the_budget(self):
        root = self.catalog(124, 70)
        self.assertEqual(self.ids(check_skill(root / "s000", hosts=["claude-code", "codex"], context_tokens=1_000_000)),
                         set())
        # Claude Code: 1% of 200,000 tokens at 4 chars per token is 8,000 chars.
        self.assertIn("CLAUDE_LIST_BUDGET",
                      self.ids(check_skill(root / "s000", hosts=["claude-code"], context_tokens=200_000)))

    def test_copilot_lists_full_descriptions_for_32_skills(self):
        self.assertIn("COPILOT_LIST_BUDGET",
                      self.ids(check_skill(self.catalog(33, 40, root=self.tmp / "a") / "s000", hosts=["copilot-cli"])))
        self.assertEqual(self.ids(check_skill(self.catalog(32, 40, root=self.tmp / "b") / "s000",
                                              hosts=["copilot-cli"])), set())

    def test_openclaw_cap_and_compact_cut(self):
        root = self.catalog(151, 100)
        self.skill("long", root=root, description=description_of(221, 999))
        long_result = check_skill(root / "long", hosts=["openclaw"])
        short_result = check_skill(root / "s000", hosts=["openclaw"])

        self.assertEqual(self.ids(long_result), {"OPENCLAW_LIST_BUDGET", "OPENCLAW_DESC_WINDOW"})
        self.assertEqual(self.ids(short_result), {"OPENCLAW_LIST_BUDGET"})
        self.assertEqual(self.ids(check_skill(self.catalog(150, 100, root=self.tmp / "ok") / "s000",
                                              hosts=["openclaw"])), set())

    def test_check_catalog_reports_every_skill_and_counts_ids(self):
        result = check_catalog(self.catalog(124, 70), hosts=["claude-code", "codex"])

        self.assertEqual(result["summary"]["skills"], 124)
        self.assertEqual(result["summary"]["findings"], {"CLAUDE_LIST_BUDGET": 124, "CODEX_LIST_BUDGET": 124})
        self.assertEqual(result["summary"]["degraded"], 248)


class BodyReadTests(_Fixture):
    def test_openclaw_read_cap_depends_on_context_and_weights_wide_characters(self):
        path = self.skill("big", body="a" * 20_000)
        self.assertIn("OPENCLAW_READ_CAP", self.ids(check_skill(path, hosts=["openclaw"])))
        self.assertEqual(self.ids(check_skill(path, hosts=["openclaw"], context_tokens=150_000)), set())
        wide = self.skill("wide", body="\u4e2d" * 4_000)  # 4,000 CJK characters weigh 16,000
        self.assertIn("OPENCLAW_READ_CAP", self.ids(check_skill(wide, hosts=["openclaw"])))
        self.assertEqual(self.ids(check_skill(self.skill("small", body="a" * 15_000), hosts=["openclaw"])), set())

    def test_hermes_view_budget(self):
        self.assertIn("HERMES_VIEW_BUDGET", self.ids(check_skill(self.skill("huge", body="a" * 100_001),
                                                                 hosts=["hermes"])))
        self.assertEqual(self.ids(check_skill(self.skill("fits", body="a" * 90_000), hosts=["hermes"])), set())

    def test_opencode_long_lines_in_files_it_reads(self):
        path = self.skill("lines", files={"references/table.md": "x" * 2_001 + "\n"})
        self.assertIn("references/table.md", self.finding(check_skill(path, hosts=["opencode"]),
                                                          "OPENCODE_LONG_LINES")["message"])
        self.assertEqual(self.ids(check_skill(self.skill("wrapped", files={"references/t.md": "x" * 2_000}),
                                              hosts=["opencode"])), set())

    def test_host_file_caps(self):
        result = check_skill(self.skill("giant", body="a" * 256_001), hosts=["openclaw", "claude-code"])
        self.assertIn("OPENCLAW_FILE_CAP", self.ids(result))
        self.assertNotIn("CLAUDE_FILE_CAP", self.ids(result))
        self.assertEqual(self.row(result, "openclaw")["status"], "not_loaded")
        self.assertIn("STATIC_SIZE", {item["id"] for item in result["static"]})


class LinkedLayoutTests(_Fixture):
    TOOLKIT = {"toolkit/README.md": "readme", "toolkit/scripts/run.py": "print()\n"}

    def test_hermes_flags_unlisted_files_unless_skill_md_names_their_path(self):
        unnamed = check_skill(self.skill("tk", files=self.TOOLKIT), hosts=["hermes"])
        named = check_skill(self.skill("tk2", files=self.TOOLKIT,
                                       body="Read `toolkit/README.md` before running anything.\n"), hosts=["hermes"])

        self.assertIn("2 files", self.finding(unnamed, "HERMES_LINKED_LAYOUT")["message"])
        self.assertEqual(self.ids(named), set())

    def test_listed_folders_follow_the_host_globs(self):
        listed = {"references/a.md": "a", "templates/deep/t.yaml": "t", "assets/x/logo.png": "p", "scripts/s.py": "s"}
        self.assertEqual(self.ids(check_skill(self.skill("ok", files=listed), hosts=["hermes"])), set())
        stray = check_skill(self.skill("stray", files={"references/notes.txt": "n"}), hosts=["hermes"])
        self.assertIn("references/ (1)", self.finding(stray, "HERMES_LINKED_LAYOUT")["message"])


class PlaceholderTests(_Fixture):
    def test_bare_arguments_fires_and_a_code_span_or_fence_does_not(self):
        bare = check_skill(self.skill("bare", body="Pass $ARGUMENTS to the script.\n"))
        span = check_skill(self.skill("span", body="Claude Code fills `$ARGUMENTS` for you.\n"))
        fence = check_skill(self.skill("fence", body="```sh\nrun $ARGUMENTS\n```\n"))

        self.assertEqual({row["host"] for row in bare["hosts"] if any("ARGUMENTS" in f["id"] for f in row["findings"])},
                         {"hermes", "codex", "openclaw", "opencode", "copilot-cli"})
        self.assertIn("line 5", self.finding(bare, "HERMES_PLACEHOLDER_ARGUMENTS")["message"])
        self.assertEqual(self.ids(span), set())
        self.assertEqual(self.ids(fence), set())

    def test_skill_dir_and_positional_tokens(self):
        skill_dir = check_skill(self.skill("dir", body="Run ${CLAUDE_SKILL_DIR}/x.sh\n"))
        price = check_skill(self.skill("price", body="It costs $4.00 a run.\n"))

        self.assertIn("HERMES_PLACEHOLDER_SKILL_DIR", self.ids(skill_dir))
        self.assertNotIn("CLAUDE_PLACEHOLDER_SKILL_DIR", self.ids(skill_dir))
        self.assertEqual({f for f in self.ids(price) if "POSITIONAL" in f},
                         {"CLAUDE_PLACEHOLDER_POSITIONAL", "OPENCODE_PLACEHOLDER_POSITIONAL"})
        self.assertEqual(self.ids(check_skill(self.skill("usd", body="It costs USD 4.00 a run.\n"))), set())


class RootTests(_Fixture):
    def test_named_and_inferred_install_roots(self):
        agents = check_skill(self.skill("r"), install_root=".agents/skills")
        self.assertEqual(self.row(agents, "claude-code")["root"], "not_scanned")
        self.assertEqual(self.row(agents, "claude-code")["status"], "not_loaded")
        self.assertEqual(self.row(agents, "codex")["root"], "scanned")
        self.assertIn("HERMES_ROOT_TRUST", self.ids(agents, "hermes"))

        inferred = check_skill(self.skill("r", root=self.tmp / "repo" / ".claude" / "skills"))
        self.assertEqual(self.row(inferred, "claude-code")["root"], "scanned")
        self.assertIn("CODEX_ROOT", self.ids(inferred))

        user = check_skill(self.skill("r"), install_root="~/.hermes/skills", hosts=["hermes"])
        self.assertEqual((self.row(user, "hermes")["root"], self.ids(user)), ("scanned", set()))

    def test_an_unknown_root_is_not_checked_rather_than_an_error(self):
        result = check_skill(self.skill("r", root=self.tmp / "skills"))
        self.assertEqual({row["root"] for row in result["hosts"]}, {"not_checked"})
        self.assertFalse(any(f.endswith("_ROOT") for f in self.ids(result)))


class StaticTests(_Fixture):
    def static(self, result: dict) -> dict[str, str]:
        return {item["id"]: item["effect"] for item in result["static"]}

    def test_frontmatter_defects(self):
        cases = {
            "STATIC_NAME_MISSING": self.skill("noname", name=None),
            "STATIC_DESC_MISSING": self.skill("nodesc", description=None),
            "STATIC_DESC_EMPTY": self.skill("empty", description=""),
            "STATIC_NAME_MISMATCH": self.skill("folder", name="other"),
            "STATIC_DUPLICATE_KEY": self.skill("dup", extra="name: dup"),
            "STATIC_CASING": self.skill("lower", manifest="skill.md"),
        }
        for finding_id, path in cases.items():
            with self.subTest(finding=finding_id):
                self.assertIn(finding_id, self.static(check_skill(path)))
        self.assertEqual(self.row(check_skill(cases["STATIC_DESC_MISSING"]), "codex")["status"], "not_loaded")
        self.assertEqual(self.row(check_skill(cases["STATIC_NAME_MISSING"]), "opencode")["status"], "not_loaded")
        self.assertEqual(self.row(check_skill(cases["STATIC_CASING"]), "hermes")["status"], "not_loaded")
        self.assertEqual(self.row(check_skill(cases["STATIC_DUPLICATE_KEY"]), "hermes")["status"], "loads")

    def test_missing_frontmatter_and_missing_manifest(self):
        bare = self.tmp / "pack" / "bare"
        bare.mkdir(parents=True)
        (bare / "SKILL.md").write_text("# No frontmatter\n", encoding="utf-8")
        self.assertIn("STATIC_NO_FRONTMATTER", self.static(check_skill(bare)))
        self.assertEqual(self.row(check_skill(bare), "copilot-cli")["status"], "not_loaded")

        empty = self.tmp / "pack" / "empty-dir"
        empty.mkdir(parents=True)
        result = check_skill(empty)
        self.assertEqual({row["status"] for row in result["hosts"]}, {"not_loaded"})
        self.assertEqual(self.static(result), {"STATIC_NO_SKILL_MD": "not_loaded"})

    def test_symlinked_manifest(self):
        source = self.skill("src", root=self.tmp / "elsewhere")
        link = self.tmp / "pack" / "src"
        link.mkdir(parents=True)
        try:
            os.symlink(source / "SKILL.md", link / "SKILL.md")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = check_skill(link)
        self.assertIn("STATIC_SYMLINK", self.static(result))
        self.assertEqual(self.row(result, "hermes")["status"], "not_loaded")
        self.assertEqual(self.row(result, "claude-code")["status"], "loads")


class OverlapTests(_Fixture):
    def test_shared_openings_are_grouped(self):
        root = self.tmp / "pack"
        self.skill("one", root=root, description="[omh] Release notes draft: write them. Use when: a.")
        self.skill("two", root=root, description="[omh] Release notes draft, again: other. Use when: b.")
        self.skill("three", root=root)

        self.assertEqual(check_catalog(root)["overlap"], [{"opening": "release notes draft", "skills": ["one", "two"]}])
        self.assertEqual(check_skill(root / "three")["overlap"], [])


class HostFactTests(unittest.TestCase):
    def test_six_hosts_and_every_fact_cites_a_known_source(self):
        self.assertEqual(sorted(HOSTS), sorted(["hermes", "claude-code", "codex", "openclaw", "opencode", "copilot-cli"]))
        defaults = {f.name: f for f in dataclass_fields(HostFacts)}
        for facts in HOSTS.values():
            for name in FACT_FIELDS:
                with self.subTest(host=facts.host, fact=name):
                    value = getattr(facts, name)
                    default = defaults[name].default
                    if value not in (None, (), {}, False) and value != default:
                        self.assertIn(facts.provenance.get(name), SOURCES)
            self.assertTrue(set(facts.provenance) <= set(FACT_FIELDS), facts.host)

    def test_the_checker_opens_no_network_or_process(self):
        banned = {"socket", "urllib", "http", "requests", "asyncio", "subprocess", "ssl"}
        for path in (REPO_ROOT / "src/skills/harness_fit.py", REPO_ROOT / "src/skills/harness_fit_hosts.py",
                     Path(__file__)):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                        for alias in node.names}
            imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom) and node.level == 0}
            with self.subTest(path=path.name):
                self.assertEqual(imported & banned, set())


class UpstreamParityTests(_Fixture):
    """OMH classes against SkillEvaluator 1.0.1 output for this repo at a5649293.

    Evidence lives outside the repository (the run's evidence folder
    `se-1.0.1-origin-main-a5649293/`); the numbers below are copied from it.
    """

    def test_hm_desc_60_matches_hermes_desc_window(self):
        # h_skills_omh-data-pipelines.json: HM-DESC-60 on this description (its
        # situation clause runs to 167 characters, so Hermes clips it).
        description = (
            "[omh] Data pipeline work -- an ETL or streaming job, a backfill or replay, duplicate events, a "
            "schema change downstream, a lineage question, a data-quality regression: make every rerun "
            "idempotent, bound every replay, and gate each load on observed checks. Use when the user says: "
            "data-pipelines, data pipeline, data pipelines, etl, elt, etl pipeline, etl job, etl backfill."
        )
        self.assertEqual(len(description), 373)
        result = check_skill(self.skill("omh-data-pipelines", description=description), hosts=["hermes"])
        self.assertIn("HERMES_DESC_WINDOW", self.ids(result))

    def test_list_budget_compact_and_prompt_cap_on_the_155_skill_pack(self):
        # h_skills_dag-ulw.json: "The 155 skills in this folder have 53,650
        # description chars; ... fits 8,000" (CC-LIST-BUDGET, CX-LIST-BUDGET),
        # OW-COMPACT and OW-PROMPT-CAP at 155 skills / 53,650 chars, and
        # CP-LIST-BUDGET past 32 skills.
        root = self.tmp / "skills"
        for index in range(155):
            self.skill(f"s{index:03d}", root=root, description=description_of(347 if index < 20 else 346, index))
        result = check_skill(root / "s000")

        self.assertEqual(result["catalog"]["size"], 155)
        self.assertEqual(result["catalog"]["desc_chars"], 53_650)
        for finding_id in ("CLAUDE_LIST_BUDGET", "CODEX_LIST_BUDGET"):
            message = self.finding(result, finding_id)["message"]
            self.assertIn("53,650", message)
            self.assertIn("8,000", message)
        self.assertTrue({"OPENCLAW_DESC_WINDOW", "OPENCLAW_LIST_BUDGET", "COPILOT_LIST_BUDGET"} <= self.ids(result))

    def test_ow_read_budget_weighted_size(self):
        # h_skills_omh-frontend.json: "SKILL.md reads as 21,370 characters" for a
        # 20,352-character file holding 315 wide (CJK) characters.
        body = "\u4e2d" * 315
        head = frontmatter("omh-frontend", GOOD)
        body += "a" * (20_352 - len(head) - len(body))
        result = check_skill(self.skill("omh-frontend", body=body), hosts=["openclaw"])

        self.assertIn("21,370", self.finding(result, "OPENCLAW_READ_CAP")["message"])

    def test_hm_linked_layout_counts_toolkit_files_and_omh_spares_a_named_path(self):
        # h_skills_omh-show-reel.json: "28 files outside references/, templates/,
        # assets/ and scripts/ (toolkit)". Upstream flags the pack even though
        # SKILL.md names toolkit/README.md; OMH does not, because Hermes'
        # skill_view still opens a path SKILL.md names.
        files = {f"toolkit/part{index:02d}.mjs": "x" for index in range(27)} | {"toolkit/README.md": "readme"}
        unnamed = check_skill(self.skill("omh-show-reel", files=files), hosts=["hermes"])
        named = check_skill(self.skill("named", files=files, body="Read toolkit/README.md first.\n"), hosts=["hermes"])

        self.assertIn("28 files", self.finding(unnamed, "HERMES_LINKED_LAYOUT")["message"])
        self.assertEqual(self.ids(named), set())

    def test_oc_long_lines(self):
        # h_skills_omh-web-research.json: "1 lines over 2,000 chars
        # (references/search-fields.md)".
        path = self.skill("omh-web-research", files={"references/search-fields.md": "f" * 2_400 + "\n"})
        self.assertIn("references/search-fields.md",
                      self.finding(check_skill(path, hosts=["opencode"]), "OPENCODE_LONG_LINES")["message"])

    def test_dollar_n_in_a_code_span_is_documentation(self):
        # h_skills_omh-prompt-import-readiness.json: CC-DOLLAR-N and OC-DOLLAR-N
        # on "lines 70, 116". Line 70 holds `$1-$9 prompt arguments` inside a
        # code span, so OMH flags line 116 only.
        head = frontmatter("omh-prompt-import-readiness", GOOD)
        lines = ["filler"] * 120
        lines[70 - head.count("\n") - 1] = "Signals: `$1-$9 prompt arguments`, `{{args}} mapping`."
        lines[116 - head.count("\n") - 1] = "- argument_interpolation_policy/v1 for $ARGUMENTS, $1-$9, {{args}}"
        result = check_skill(self.skill("omh-prompt-import-readiness", body="\n".join(lines) + "\n"),
                             hosts=["claude-code", "opencode", "hermes"])

        message = self.finding(result, "CLAUDE_PLACEHOLDER_POSITIONAL")["message"]
        self.assertIn("line 116", message)
        self.assertNotIn("70", message)
        self.assertIn("OPENCODE_PLACEHOLDER_POSITIONAL", self.ids(result))
        self.assertIn("HERMES_PLACEHOLDER_ARGUMENTS", self.ids(result))


def _link(test: unittest.TestCase, link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        test.skipTest(f"symlinks unavailable: {error}")


class FrontmatterTypeTests(_Fixture):
    """Typed, quoted, listed, tab-indented and unparsed frontmatter per host (R2)."""

    def statuses(self, meta: str) -> dict[str, str]:
        path = self.tmp / "pack" / "demo"
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text("---\n" + meta + "---\n\n# Demo\n", encoding="utf-8")
        return {row["host"]: row["status"] for row in check_skill(path)["hosts"]}

    def test_an_unquoted_number_is_no_string_description(self):
        # codex.yaml CX-DESC-MISSING, copilot-cli.yaml CP-STRICT-YAML, opencode.yaml OC-DESC-MISSING and
        # claude-code.yaml CC-DESC-MISSING read `description_type != 'str'`; no fact covers Hermes or OpenClaw.
        self.assertEqual(self.statuses("name: demo\ndescription: 123\n"), {
            "hermes": "unverified", "claude-code": "degraded", "codex": "not_loaded", "openclaw": "unverified",
            "opencode": "not_loaded", "copilot-cli": "not_loaded",
        })
        for typed in ("true", "1.5", "2026-11-19", "0x1F", "no"):
            with self.subTest(value=typed):
                self.assertEqual(self.statuses(f"name: demo\ndescription: {typed}\n")["codex"], "not_loaded")
        quoted = self.statuses('name: demo\ndescription: "123"\n')
        self.assertEqual(set(quoted.values()), {"loads"})

    def test_quoted_keys_are_keys(self):
        result = self.statuses('"name": demo\n\'description\': Assemble demo artifacts.\n')
        self.assertEqual(set(result.values()), {"loads"})

    def test_a_list_description_follows_each_host(self):
        # openclaw.yaml notes: a list description is stringified and listed; copilot-cli.yaml CP-STRICT-YAML
        # rejects a non-string type.
        for meta in ("name: demo\ndescription: [Build, test]\n", "name: demo\ndescription:\n  - Build\n  - test\n",
                     "name: demo\ndescription:\n- Build\n- test\n"):
            with self.subTest(meta=meta):
                self.assertEqual(self.statuses(meta), {
                    "hermes": "unverified", "claude-code": "degraded", "codex": "not_loaded", "openclaw": "loads",
                    "opencode": "not_loaded", "copilot-cli": "not_loaded",
                })

    def test_a_tab_indented_line_is_invalid_yaml_where_hosts_are_strict(self):
        # codex.yaml CX-STRICT-YAML, openclaw.yaml OW-STRICT-YAML, copilot-cli.yaml CP-STRICT-YAML; opencode.yaml
        # and claude-code.yaml notes: tabs tolerated.
        self.assertEqual(self.statuses("name: demo\ndescription: Assemble demo artifacts.\nmetadata:\n\tauthor: omh\n"), {
            "hermes": "unverified", "claude-code": "loads", "codex": "not_loaded", "openclaw": "not_loaded",
            "opencode": "loads", "copilot-cli": "not_loaded",
        })

    def test_yaml_this_reader_does_not_parse_is_unverified_never_loads(self):
        for meta in ("name: demo\ndescription: &d Assemble demo artifacts.\n",
                     "name: demo\ndescription: Use when: the user says demo\n",
                     'name: demo\ndescription: "unclosed\n',
                     "name: demo\ndescription: Assemble demo artifacts.\n? complex key\n"):
            with self.subTest(meta=meta):
                statuses = self.statuses(meta)
                self.assertNotIn("loads", statuses.values())
                self.assertEqual(statuses["opencode"], "unverified")
        path = self.tmp / "pack" / "demo"
        result = check_skill(path, hosts=["codex"])
        self.assertIn("CODEX_YAML_UNSUPPORTED", self.ids(result))
        self.assertEqual(result["summary"]["unverified"], 1)
        self.assertIn("STATIC_YAML_UNSUPPORTED", {item["id"] for item in result["static"]})

    def test_block_scalars_and_comments_still_read_as_strings(self):
        for meta in ("name: demo\ndescription: >-\n  Assemble demo\n  artifacts.\n",
                     "name: demo\ndescription: Assemble demo artifacts. # trailing note\n",
                     "# leading comment\nname: demo\ndescription: 'It''s a demo.'\n"):
            with self.subTest(meta=meta):
                self.assertEqual(set(self.statuses(meta).values()), {"loads"})


class InstallRootTests(_Fixture):
    """The install root is read off the path as given, and a catalog is walked as Hermes walks it (R1)."""

    def setUp(self) -> None:
        super().setUp()
        self.home = self.tmp / "home"
        self.profile = self.home / ".hermes" / "profiles" / "work"
        self.skills = self.profile / "skills"
        self.agents = self.home / ".agents" / "skills"
        for folder in ("top", "devops/deploy", "devops/cloud/aws", "research/arxiv"):
            self.skill(folder.split("/")[-1], root=self.skills / Path(folder).parent)
        # Never skills: a support folder of a skill and a dependency folder.
        self.skill("inner", root=self.skills / "devops" / "deploy" / "references")
        self.skill("dep", root=self.skills / "node_modules")
        self.skill("shared", root=self.agents)
        _link(self, self.skills / "aaa-linked", self.agents / "shared")
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home),
                                               "HERMES_HOME": str(self.profile)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_catalog_is_every_skill_hermes_walks(self):
        result = check_catalog(self.skills, hosts=["hermes"])
        found = sorted(Path(skill["target"]).relative_to(self.skills).as_posix() for skill in result["skills"])
        self.assertEqual(found, ["aaa-linked", "devops/cloud/aws", "devops/deploy", "research/arxiv", "top"])
        self.assertEqual(result["catalog"]["grouped"], 3)
        rows = [row for skill in result["skills"] for row in skill["hosts"]]
        self.assertEqual({(row["root"], row["status"]) for row in rows}, {("scanned", "loads")})

    def test_a_linked_skill_in_the_profile_is_listed_where_the_link_sits(self):
        result = check_skill(self.skills / "aaa-linked", hosts=["hermes", "claude-code"])
        self.assertEqual(self.row(result, "hermes")["root"], "scanned")
        self.assertEqual(self.row(result, "hermes")["status"], "loads")
        self.assertIn("CLAUDE_ROOT", self.ids(result))
        self.assertEqual(result["catalog"]["size"], 5)

    def test_a_profile_root_is_found_without_hermes_home_and_a_grouped_skill_is_checked(self):
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.home / ".hermes")}):
            result = check_skill(self.skills / "devops" / "deploy", hosts=["hermes", "codex", "copilot-cli"])
        self.assertEqual(self.row(result, "hermes")["root"], "scanned")
        self.assertEqual(self.row(result, "codex")["root"], "not_scanned")
        self.assertNotIn("HERMES_GROUPING", self.ids(result))
        self.assertNotIn("COPILOT_GROUPING", self.ids(result))

    def test_grouping_deeper_than_a_host_looks(self):
        nested = self.home / "repo" / ".claude" / "skills"
        self.skill("grouped", root=nested / "category")
        result = check_skill(nested / "category" / "grouped", hosts=["claude-code", "opencode"])
        self.assertEqual(self.finding(result, "CLAUDE_GROUPING")["effect"], "not_loaded")
        self.assertEqual(self.row(result, "opencode")["status"], "loads")

    def test_external_dirs_count_as_hermes_roots_only(self):
        external = self.tmp / "shared-pack"
        self.skill("ext", root=external)
        (self.profile / "config.yaml").write_text(f"skills:\n  external_dirs:\n    - {external}\n", encoding="utf-8")
        result = check_skill(external / "ext", hosts=["hermes", "codex"])
        self.assertEqual(self.row(result, "hermes")["root"], "scanned")
        self.assertEqual(self.row(result, "codex")["root"], "not_scanned")

    def test_a_linked_first_child_does_not_stamp_its_root_on_the_catalog(self):
        pack = self.home / "repo" / ".claude" / "skills"
        self.skill("zzz-plain", root=pack)
        _link(self, pack / "aaa-linked", self.agents / "shared")
        result = check_catalog(pack, hosts=["claude-code"])
        self.assertEqual({row["root"] for skill in result["skills"] for row in skill["hosts"]}, {"scanned"})


class FolderLinkTests(_Fixture):
    """OpenClaw rejects a skill folder linked from outside its root; Codex follows it (R4)."""

    def test_in_root_and_out_of_root_folder_links(self):
        root = self.tmp / "repo" / ".agents" / "skills"
        self.skill("real", root=root / "group")
        self.skill("outside", root=self.tmp / "elsewhere")
        _link(self, root / "inside-link", root / "group" / "real")
        _link(self, root / "outside-link", self.tmp / "elsewhere" / "outside")

        inside = check_skill(root / "inside-link", hosts=["codex", "openclaw"])
        outside = check_skill(root / "outside-link", hosts=["codex", "openclaw"])
        named = check_skill(root / "outside-link", hosts=["codex", "openclaw"], install_root=".agents/skills")

        self.assertEqual({row["status"] for row in inside["hosts"]}, {"loads"})
        for result in (outside, named):
            self.assertEqual(self.row(result, "codex")["status"], "loads")
            self.assertEqual(self.finding(result, "OPENCLAW_DIR_LINK_ESCAPE")["effect"], "not_loaded")


class MultilineCodeSpanTests(_Fixture):
    """A code span may cross a line ending; masking keeps every line number (R3)."""

    def test_a_multiline_span_is_documentation_and_bare_prose_after_it_is_not(self):
        body = "Example: `sample\n$ARGUMENTS` here.\nThen pass $ARGUMENTS on.\n"
        result = check_skill(self.skill("multi", body=body), hosts=["hermes"])
        message = self.finding(result, "HERMES_PLACEHOLDER_ARGUMENTS")["message"]
        # Frontmatter is lines 1-4, so the body opens on line 5.
        self.assertIn("line 7", message)
        self.assertNotIn("6", message)

    def test_unpaired_runs_and_paragraph_breaks_leave_the_text_live(self):
        cases = {
            "lone backtick": "A lone ` then $ARGUMENTS.\n",
            "different run widths": "``open $ARGUMENTS` close`\n",
            "blank line ends the paragraph": "Start `a\n\n$ARGUMENTS` b\n",
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                self.assertIn("HERMES_PLACEHOLDER_ARGUMENTS",
                              self.ids(check_skill(self.skill("x", body=body), hosts=["hermes"])))
        self.assertEqual(self.ids(check_skill(self.skill("y", body="``a `$ARGUMENTS` b``\n"), hosts=["hermes"])), set())


class OpenCodeBodyCapTests(_Fixture):
    """OpenCode's skill tool cuts the delivered body at 2,000 lines or 51,200 bytes (R5)."""

    def test_line_and_byte_caps(self):
        many = check_skill(self.skill("many", body="Short line.\n" * 2_050), hosts=["opencode"])
        heavy = check_skill(self.skill("heavy", body=("x" * 1_000 + "\n") * 60), hosts=["opencode"])
        fits = check_skill(self.skill("fits", body="Short line.\n" * 1_990), hosts=["opencode"])

        self.assertEqual(self.finding(many, "OPENCODE_BODY_CAP")["effect"], "degraded")
        self.assertIn("2,050 lines", self.finding(many, "OPENCODE_BODY_CAP")["message"])
        self.assertIn("OPENCODE_BODY_CAP", self.ids(heavy))
        self.assertNotIn("OPENCODE_LONG_LINES", self.ids(many))
        self.assertEqual(self.ids(fits), set())


if __name__ == "__main__":
    unittest.main()
