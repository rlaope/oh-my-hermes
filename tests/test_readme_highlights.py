"""The README Highlights stay capability-first rather than command-heavy."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


READMES = ("README.md", "README.ko.md", "README.ja.md", "README.zh.md")

def _highlights_table(text: str) -> list[str]:
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        heading = line.strip()
        if (
            heading.startswith("**")
            and (
                "Highlight" in heading
                or "하이라이트" in heading
                or "ハイライト" in heading
                or "亮点" in heading
            )
        ):
            inside = True
            continue
        if inside:
            if line.startswith("|"):
                lines.append(line)
            elif lines:
                break
    return lines


class ReadmeHighlightsTests(unittest.TestCase):
    def test_highlights_are_two_column_capability_tables(self) -> None:
        lifecycle_contracts = {
            "README.md": (
                "### The workflow",
                "Understand → Research → Decide → Plan → Execute → Verify → Operate → Learn",
                "**Highlights**",
            ),
            "README.ko.md": (
                "### 작업 흐름",
                "이해 → 조사 → 결정 → 계획 → 실행 → 검증 → 운영 → 학습",
                "**하이라이트**",
            ),
            "README.ja.md": (
                "### 作業の流れ",
                "理解 → 調査 → 判断 → 計画 → 実行 → 検証 → 運用 → 学習",
                "**ハイライト**",
            ),
            "README.zh.md": (
                "### 工作流",
                "理解 → 调研 → 决策 → 计划 → 执行 → 验证 → 运维 → 学习",
                "**亮点**",
            ),
        }

        for rel in READMES:
            text = Path(rel).read_text(encoding="utf-8")
            heading, sequence, highlights = lifecycle_contracts[rel]
            with self.subTest(readme=rel, contract="workflow"):
                self.assertIn(sequence, text)
                self.assertLess(text.index(heading), text.index(highlights))
                for stage in sequence.split(" → "):
                    self.assertIn(f"| {stage} |", text)

            table = _highlights_table(text)
            self.assertGreaterEqual(len(table), 3, f"{rel}: no Highlights table found")
            for line in table:
                with self.subTest(readme=rel, line=line):
                    self.assertEqual(line.count("|"), 3, f"{rel}: Highlights must have two columns")

    def test_highlights_do_not_expose_internal_skill_labels(self) -> None:
        for rel in READMES:
            highlights = "\n".join(_highlights_table(Path(rel).read_text(encoding="utf-8")))
            self.assertNotIn("`omh-", highlights, f"{rel}: Highlights exposes omh skill labels")
            self.assertNotIn("`ulw-", highlights, f"{rel}: Highlights exposes ulw skill labels")

    def test_readmes_do_not_publish_mutable_skill_counts(self) -> None:
        mutable_count_claims = {
            "README.md": r"\b(?:106|94)\s+(?:installable workflow skills|skills use `omh-` labels)",
            "README.ko.md": r"(?:106개|94개)",
            "README.ja.md": r"(?:106 個|94 個)",
            "README.zh.md": r"(?:106 个|94 个)",
        }
        for rel, pattern in mutable_count_claims.items():
            text = Path(rel).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(pattern, text),
                f"{rel}: mutable installable-skill count leaked",
            )

    def test_localized_model_tables_and_install_details_keep_gfm_spacing(self) -> None:
        table_heads = {
            "README.ko.md": "| 카테고리 alias |",
            "README.ja.md": "| カテゴリ alias |",
            "README.zh.md": "| 类别 alias |",
        }
        for rel, table_head in table_heads.items():
            lines = Path(rel).read_text(encoding="utf-8").splitlines()
            table_index = next(index for index, line in enumerate(lines) if line.startswith(table_head))
            details_index = lines.index("<details>")
            fence_index = lines.index("```text", details_index)
            with self.subTest(readme=rel):
                self.assertEqual(lines[table_index - 1], "")
                self.assertEqual(lines[details_index - 1], "")
                self.assertEqual(lines[fence_index - 1], "")

    def test_quick_start_points_model_routing_users_to_the_model_setup_skill(self) -> None:
        comments = {
            "README.md": "# To onboard models or configure model routing, use this skill in Hermes:",
            "README.ko.md": "# 모델을 온보딩하거나 모델 라우팅을 설정하려면 Hermes에서 이 스킬을 사용하세요:",
            "README.ja.md": "# モデルのオンボーディングやモデルルーティングの設定には、Hermes でこのスキルを使ってください:",
            "README.zh.md": "# 如需接入模型或配置模型路由，请在 Hermes 中使用此技能：",
        }
        for rel, comment in comments.items():
            text = Path(rel).read_text(encoding="utf-8")
            expected = (
                "```sh\nomh doctor\n```\n\n"
                f"```sh\n{comment}\n/omh-model-setup\n```"
            )
            with self.subTest(readme=rel):
                self.assertIn(expected, text)
                self.assertNotIn("](", expected)

    def test_the_workflow_engines_are_advertised_with_their_ulw_label(self) -> None:
        # The ulw engines moved out of the Highlights table into a dedicated
        # Ultra-Skills section (one per README language). Every engine must be
        # advertised there by its exact installable name; the Highlights table
        # stays omh-only so the two surfaces do not repeat each other.
        section_heads = {
            "README.md": "## Ultra-Skills",
            "README.ko.md": "## 울트라 스킬",
            "README.ja.md": "## ウルトラスキル",
            "README.zh.md": "## Ultra 技能",
        }
        # The canonical engines only: the four retired engines (#954 stage 5)
        # left every advertised surface and their intents run as `ulw-work`
        # capabilities.
        engines = (
            "ulw-work", "ulw-plan", "ulw-interview", "ulw-loop",
            "ulw-qa", "ulw-research", "ulw-perf",
        )
        for rel, head in section_heads.items():
            text = Path(rel).read_text(encoding="utf-8")
            self.assertIn(head, text, f"{rel}: Ultra-Skills section missing")
            section = text.split(head, 1)[1].split("\n## ", 1)[0]
            for engine in engines:
                with self.subTest(readme=rel, engine=engine):
                    self.assertIn(f"`{engine}`", section)
            highlights = "\n".join(_highlights_table(text))
            self.assertNotIn("`ulw-", highlights, f"{rel}: Highlights should be omh-only")


if __name__ == "__main__":
    unittest.main()
