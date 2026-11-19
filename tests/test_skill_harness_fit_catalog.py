"""The shipped catalogs pass OMH's own host-fit checker on the findings lane A fixed.

`harness_fit.check_catalog` runs over the committed packs, each read under the
root a host installs it to: `skills/` as `~/.hermes/skills`, `agent-skills/`
as `.agents/skills` (Codex, OpenClaw, OpenCode, Copilot CLI) and
`.claude/agent-skills/` as `.claude/skills` (Claude Code). The findings below
were all present on base a5649293 and are zero now; a regression in the
description projection, the read-cap split or a toolkit pointer brings one
back and fails here.

Findings still reported and not locked: COPILOT_LIST_BUDGET (a 32-skill count
limit no description length fixes), OPENCODE_LONG_LINES (three reference
files), the `*_ROOT` rows for hosts that do not scan a pack's root, and the
placeholder rows on omh-prompt-import-readiness, whose body quotes `$N`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from omh.skills.harness_fit import check_catalog

REPO = Path(__file__).resolve().parents[1]

# Hermes clips the situation clause; Claude Code / Codex list budget; OpenClaw
# compact cut (220) and prompt cap (150 skills / 18,000 chars); OpenClaw read
# cap; a toolkit file SKILL.md does not name.
LOCKED = (
    "HERMES_DESC_WINDOW",
    "CLAUDE_LIST_BUDGET",
    "CODEX_LIST_BUDGET",
    "OPENCLAW_DESC_WINDOW",
    "OPENCLAW_LIST_BUDGET",
    "OPENCLAW_READ_CAP",
    "HERMES_LINKED_LAYOUT",
)
PACKS = (
    ("skills", ("hermes",), "~/.hermes/skills", ("HERMES_DESC_WINDOW", "HERMES_LINKED_LAYOUT")),
    ("agent-skills", None, ".agents/skills", LOCKED),
    (".claude/agent-skills", None, ".claude/skills", LOCKED),
)


def _locked_findings(folder: str, hosts, install_root: str, locked) -> list[str]:
    report = check_catalog(REPO / folder, hosts=hosts, install_root=install_root)
    found = []
    for skill in report["skills"]:
        name = Path(skill["target"]).name
        for row in skill["hosts"]:
            found += [f"{name} {row['host']} {f['id']}: {f['message']}" for f in row["findings"] if f["id"] in locked]
    return found


class ShippedCatalogHostFitTests(unittest.TestCase):
    def test_no_locked_host_fit_finding_on_any_shipped_pack(self) -> None:
        for folder, hosts, install_root, locked in PACKS:
            with self.subTest(pack=folder):
                self.assertTrue((REPO / folder).is_dir(), folder)
                self.assertEqual(_locked_findings(folder, hosts, install_root, locked), [])


if __name__ == "__main__":
    unittest.main()
