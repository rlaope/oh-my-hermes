"""The plugin bundle must pass critical Hermes install-scanner rules.

`hermes plugins validate` runs the install scanner, and a `dangerous` verdict
fails a curated-catalog entry (hermes-agent `plugin-catalog/README.md`,
admission rule 7). The rule matches a credential-shaped NAME followed by a
long quoted literal, so a dict-key constant such as
`PRIVATE_TOKEN = "__omh_egress_attempt_token"` blocked admission although it
holds no secret.

The pattern below is copied verbatim from hermes-agent
`tools/skills_guard.py` (THREAT_PATTERNS entry `hardcoded_secret`, severity
critical; the same regex is `tools/threat_patterns.py`), compiled with
`re.IGNORECASE` as `_COMPILED_THREAT_PATTERNS` does and applied per line by
`scan_file`. `tools/plugin_guard.py` then lowers some hits (comments, docs,
test trees) to a reviewer-read warning; this guard applies none of those
exemptions, because a warning is still something a catalog reviewer must read
past. The `crypto_mining` pattern is pinned for the same reason: it treats a
cryptocurrency name as critical even when that word appears only in generated
lexical-index data. Read at hermes-agent 577990c3a0 (2026-09-19).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

HERMES_HARDCODED_SECRET = re.compile(
    r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9+/=_-]{20,}', re.IGNORECASE
)
HERMES_CRYPTO_MINING = re.compile(
    r"xmrig|stratum\+tcp|monero|coinhive|cryptonight", re.IGNORECASE
)
BUNDLE = Path(__file__).resolve().parents[1] / "src" / "plugin_bundle" / "omh"
# `SCANNABLE_EXTENSIONS` in hermes-agent `tools/skills_guard.py`.
SCANNABLE_EXTENSIONS = {
    ".md", ".txt", ".py", ".sh", ".bash", ".js", ".ts", ".rb", ".yaml", ".yml", ".json", ".toml",
    ".cfg", ".ini", ".conf", ".html", ".css", ".xml", ".tex", ".r", ".jl", ".pl", ".php",
}


def scanner_hits(root: Path, pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file() or path.suffix.lower() not in SCANNABLE_EXTENSIONS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(root).as_posix()}:{number}: {line.strip()}")
    return hits


class PluginBundleCatalogScanTests(unittest.TestCase):
    def test_the_rule_still_matches_the_line_that_blocked_admission(self) -> None:
        # Pins the copied pattern to the finding it exists for, so an edit that
        # weakens it cannot leave the bundle scan below passing vacuously.
        self.assertTrue(HERMES_HARDCODED_SECRET.search('PRIVATE_TOKEN = "__omh_egress_attempt_token"'))
        self.assertFalse(HERMES_HARDCODED_SECRET.search('PRIVATE_ARGUMENT_KEY = "__omh_egress_attempt_token"'))
        self.assertTrue(HERMES_CRYPTO_MINING.search('"anchors": "blockchain monero xmr"'))
        self.assertFalse(HERMES_CRYPTO_MINING.search('"anchors": "blockchain xmr"'))

    def test_no_bundle_line_matches_the_hermes_hardcoded_secret_rule(self) -> None:
        self.assertTrue((BUNDLE / "plugin.yaml").is_file(), BUNDLE)
        self.assertEqual(scanner_hits(BUNDLE, HERMES_HARDCODED_SECRET), [])

    def test_no_bundle_line_matches_the_hermes_crypto_mining_rule(self) -> None:
        self.assertTrue((BUNDLE / "plugin.yaml").is_file(), BUNDLE)
        self.assertEqual(scanner_hits(BUNDLE, HERMES_CRYPTO_MINING), [])


if __name__ == "__main__":
    unittest.main()
