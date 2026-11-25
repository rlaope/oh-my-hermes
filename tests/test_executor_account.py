"""Account tags, read from fake home directories for both readable owners.

Every fixture here writes config files shaped like the real ones into a
`TemporaryDirectory` that stands in for `~`. Nothing reads the operator's own
home, and no fixture carries a value shaped like a real credential -- the token
fields exist only to prove they are NOT what a tag is built from.
"""

from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.coding.executor_account import (  # noqa: E402
    ACCOUNT_TAG_CLAIM_BOUNDARY,
    observed_account_tag,
    redacted_email,
    short_digest,
)


# Evaluated once, guarded: `os.geteuid` does not exist on Windows, and a
# decorator argument is evaluated at class-creation time even when the skip
# would have fired.
_POSIX_NON_ROOT = os.name != "nt" and os.geteuid() != 0


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ClaudeAccountTagTests(unittest.TestCase):
    def test_the_email_becomes_a_redacted_tag(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude.json", {"oauthAccount": {"emailAddress": "demo@example.org"}})
            self.assertEqual(observed_account_tag("claude-code", home=base), "claude:de...@example.org")

    def test_the_tag_is_stable_across_reads(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude.json", {"oauthAccount": {"emailAddress": "demo@example.org"}})
            first = observed_account_tag("claude-code", home=base)
            self.assertEqual(first, observed_account_tag("claude-code", home=base))

    def test_two_accounts_do_not_tag_the_same(self) -> None:
        with TemporaryDirectory() as home_a, TemporaryDirectory() as home_b:
            write_json(Path(home_a) / ".claude.json", {"oauthAccount": {"emailAddress": "one@work.example"}})
            write_json(Path(home_b) / ".claude.json", {"oauthAccount": {"emailAddress": "two@work.example"}})
            self.assertNotEqual(
                observed_account_tag("claude-code", home=Path(home_a)),
                observed_account_tag("claude-code", home=Path(home_b)),
            )

    def test_no_email_falls_back_to_the_account_uuid(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude.json", {"oauthAccount": {"accountUuid": "f7c0-uuid"}})
            self.assertEqual(
                observed_account_tag("claude-code", home=base), f"claude:{short_digest('f7c0-uuid')}"
            )

    def test_no_profile_falls_back_to_the_single_oauth_slot(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude" / ".credentials.json", {"claudeAiOauth": {"expiresAt": 1}})
            self.assertEqual(observed_account_tag("claude-code", home=base), "claude:oauth-slot")

    def test_an_empty_oauth_slot_names_no_account(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude" / ".credentials.json", {"claudeAiOauth": {}})
            self.assertEqual(observed_account_tag("claude-code", home=base), "")

    def test_no_token_value_appears_in_the_tag(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(
                base / ".claude" / ".credentials.json",
                {"claudeAiOauth": {"accessToken": "not-a-real-token-value", "expiresAt": 1}},
            )
            write_json(base / ".claude.json", {"oauthAccount": {"emailAddress": "demo@example.org"}})
            tag = observed_account_tag("claude-code", home=base)
            self.assertNotIn("not-a-real-token-value", tag)
            self.assertNotIn(short_digest("not-a-real-token-value"), tag)


class CodexAccountTagTests(unittest.TestCase):
    def test_the_account_id_becomes_a_short_digest(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(
                base / ".codex" / "auth.json",
                {
                    "auth_mode": "chatgpt",
                    "OPENAI_API_KEY": None,
                    "tokens": {"id_token": "header.body.sig", "account_id": "acct-42"},
                },
            )
            tag = observed_account_tag("codex", home=base)
            self.assertEqual(tag, f"codex:{short_digest('acct-42')}")
            self.assertNotIn("header.body.sig", tag)

    def test_an_api_key_install_tags_as_api_key_without_reading_the_key(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".codex" / "auth.json", {"OPENAI_API_KEY": "sk-fixture-not-a-key"})
            tag = observed_account_tag("codex", home=base)
            self.assertEqual(tag, "codex:api-key")
            self.assertNotIn("sk-fixture-not-a-key", tag)
            self.assertNotIn(short_digest("sk-fixture-not-a-key"), tag)

    def test_an_empty_store_names_no_account(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".codex" / "auth.json", {"auth_mode": "chatgpt", "tokens": {}})
            self.assertEqual(observed_account_tag("codex", home=base), "")

    def test_the_two_owners_never_tag_the_same(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude.json", {"oauthAccount": {"accountUuid": "shared"}})
            write_json(base / ".codex" / "auth.json", {"tokens": {"account_id": "shared"}})
            self.assertNotEqual(
                observed_account_tag("claude-code", home=base), observed_account_tag("codex", home=base)
            )


class UnreadableAndAbsentTests(unittest.TestCase):
    def test_a_missing_file_is_an_empty_tag(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            self.assertEqual(observed_account_tag("claude-code", home=base), "")
            self.assertEqual(observed_account_tag("codex", home=base), "")

    def test_unparseable_json_is_an_empty_tag_and_never_raises(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            (base / ".codex").mkdir(parents=True)
            (base / ".codex" / "auth.json").write_text("{not json", encoding="utf-8")
            (base / ".claude.json").write_text("[]", encoding="utf-8")
            self.assertEqual(observed_account_tag("codex", home=base), "")
            self.assertEqual(observed_account_tag("claude-code", home=base), "")

    @unittest.skipUnless(
        _POSIX_NON_ROOT,
        "needs POSIX permission bits and a non-root euid: Windows does not deny the read and "
        "root reads a write-only file regardless of its mode",
    )
    def test_a_file_that_cannot_be_opened_is_an_empty_tag(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            path = base / ".codex" / "auth.json"
            write_json(path, {"tokens": {"account_id": "acct-42"}})
            path.chmod(stat.S_IWUSR)
            try:
                self.assertEqual(observed_account_tag("codex", home=base), "")
            finally:
                # Restore before the TemporaryDirectory tears the tree down.
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_an_owner_with_no_local_credential_store_is_an_empty_tag(self) -> None:
        with TemporaryDirectory() as home:
            base = Path(home)
            write_json(base / ".claude.json", {"oauthAccount": {"emailAddress": "demo@example.org"}})
            for owner in ("hermes", "pi-family-runtime", "generic", ""):
                with self.subTest(owner=owner):
                    self.assertEqual(observed_account_tag(owner, home=base), "")


class RedactionTests(unittest.TestCase):
    def test_only_two_characters_of_the_local_part_survive(self) -> None:
        self.assertEqual(redacted_email("demo3@example.com"), "de...@example.com")

    def test_a_short_local_part_is_not_padded_into_a_false_address(self) -> None:
        self.assertEqual(redacted_email("ab@x.example"), "ab@x.example")

    def test_a_value_that_is_not_an_address_is_digested_instead(self) -> None:
        self.assertEqual(redacted_email("no-at-sign"), short_digest("no-at-sign"))

    def test_the_digest_is_one_way_and_short(self) -> None:
        digest = short_digest("acct-42")
        self.assertEqual(len(digest), 8)
        self.assertNotIn("acct-42", digest)

    def test_the_claim_boundary_denies_login_truth(self) -> None:
        self.assertIn("not login truth", ACCOUNT_TAG_CLAIM_BOUNDARY)


if __name__ == "__main__":  # pragma: no cover - parity with the suite's modules
    unittest.main()
