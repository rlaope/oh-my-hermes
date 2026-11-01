"""Contracts for identity profiles — user-named prompt + model chain pairs.

`~/.omh/routing/identities.json` (`omh_identity_profiles/v1`) binds one user
prompt to one ordered model chain. The loader never raises: an absent,
malformed, or future-schema document reads as absent, and invalid profiles are
dropped by name in `rejected` while valid siblings keep working. Only bounded
metadata (identity id, fingerprint, selected model/effort) ever reaches route
records — prompt text stays out of metadata.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.coding.identity_profiles import (
    IDENTITY_PROFILES_SCHEMA_VERSION,
    clear_identity_profile,
    identity_profiles_path,
    read_identity_profiles_config,
    set_identity_profile,
)


def _write_config(omh_home: Path, document: object) -> Path:
    path = identity_profiles_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _document(identities: dict) -> dict:
    return {
        "schema_version": IDENTITY_PROFILES_SCHEMA_VERSION,
        "identities": identities,
    }


_VALID = {
    "script-coding": {
        "prompt": "Implement small scripts directly.",
        "model_chain": [
            {"model_id": "deepseek-flash", "reasoning_effort": "low"},
            {"model_id": "glm-5.3-flash", "reasoning_effort": "low"},
        ],
    },
    "review": {
        "prompt": "Find concrete defects first.",
        "model_chain": [{"model_id": "gpt-6.1-sol", "reasoning_effort": "xhigh"}],
    },
}


class IdentityProfileLoaderTests(unittest.TestCase):
    def test_missing_file_reads_as_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(read_identity_profiles_config(Path(tmp)))

    def test_valid_document_reads_with_fingerprint_and_no_rejections(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(home, _document(_VALID))
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(config["schema_version"], IDENTITY_PROFILES_SCHEMA_VERSION)
            self.assertEqual(sorted(config["identities"]), ["review", "script-coding"])
            self.assertEqual(
                config["identities"]["script-coding"]["model_chain"],
                (
                    {"model_id": "deepseek-flash", "reasoning_effort": "low"},
                    {"model_id": "glm-5.3-flash", "reasoning_effort": "low"},
                ),
            )
            fingerprint = config["fingerprint"]
            self.assertEqual(fingerprint["source"], "identities.json")
            self.assertEqual(len(fingerprint["digest"]), 16)
            self.assertEqual(config["rejected"], [])

    def test_malformed_and_wrong_schema_documents_read_as_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = identity_profiles_path(home)
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(read_identity_profiles_config(home))
            _write_config(home, {"schema_version": "omh_identity_profiles/v2", "identities": _VALID})
            self.assertIsNone(read_identity_profiles_config(home))
            _write_config(home, {"schema_version": "other/v1", "identities": _VALID})
            self.assertIsNone(read_identity_profiles_config(home))
            # A top-level non-object and a missing `identities` object also
            # read as absent, never as a crash.
            path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
            self.assertIsNone(read_identity_profiles_config(home))
            _write_config(home, {"schema_version": IDENTITY_PROFILES_SCHEMA_VERSION})
            self.assertIsNone(read_identity_profiles_config(home))

    def test_invalid_names_are_dropped_and_named(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                _document(
                    {
                        **_VALID,
                        "Has Upper": {"prompt": "x", "model_chain": [{"model_id": "m"}]},
                        "": {"prompt": "x", "model_chain": [{"model_id": "m"}]},
                        "bad space": {"prompt": "x", "model_chain": [{"model_id": "m"}]},
                        "a" * 65: {"prompt": "x", "model_chain": [{"model_id": "m"}]},
                    }
                ),
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(sorted(config["identities"]), ["review", "script-coding"])
            rejected = "\n".join(config["rejected"])
            self.assertIn("Has Upper", rejected)
            self.assertIn("bad space", rejected)

    def test_empty_and_oversized_prompts_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                _document(
                    {
                        **_VALID,
                        "empty-prompt": {
                            "prompt": "   ",
                            "model_chain": [{"model_id": "m"}],
                        },
                        "huge-prompt": {
                            "prompt": "x" * 4001,
                            "model_chain": [{"model_id": "m"}],
                        },
                    }
                ),
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(sorted(config["identities"]), ["review", "script-coding"])
            rejected = "\n".join(config["rejected"])
            self.assertIn("empty-prompt", rejected)
            self.assertIn("huge-prompt", rejected)
            self.assertIn("4000", rejected)

    def test_empty_and_invalid_chains_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                _document(
                    {
                        **_VALID,
                        "empty-chain": {"prompt": "x", "model_chain": []},
                        "no-chain": {"prompt": "x"},
                        "long-chain": {
                            "prompt": "x",
                            "model_chain": [{"model_id": f"m{i}"} for i in range(9)],
                        },
                        "bad-model": {
                            "prompt": "x",
                            "model_chain": [{"model_id": "has space"}],
                        },
                        "flag-model": {
                            "prompt": "x",
                            "model_chain": [{"model_id": "--danger"}],
                        },
                        "bad-effort": {
                            "prompt": "x",
                            "model_chain": [{"model_id": "m", "reasoning_effort": "Bad Effort"}],
                        },
                        "non-generative": {
                            "prompt": "x",
                            "model_chain": [{"model_id": "jev-1.13.0"}],
                        },
                    }
                ),
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(sorted(config["identities"]), ["review", "script-coding"])
            rejected = "\n".join(config["rejected"])
            for name in (
                "empty-chain",
                "no-chain",
                "long-chain",
                "bad-model",
                "flag-model",
                "bad-effort",
                "non-generative",
            ):
                self.assertIn(name, rejected)
            self.assertIn("non_generative", rejected)

    def test_unknown_profile_fields_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                _document(
                    {
                        **_VALID,
                        "extra-field": {
                            "prompt": "x",
                            "model_chain": [{"model_id": "m"}],
                            "inherits": "other",
                        },
                    }
                ),
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(sorted(config["identities"]), ["review", "script-coding"])
            self.assertIn("extra-field", "\n".join(config["rejected"]))
            self.assertIn("inherits", "\n".join(config["rejected"]))

    def test_partially_invalid_document_keeps_valid_profiles(self) -> None:
        # One bad sibling must not poison the others.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                _document(
                    {
                        "good": _VALID["review"],
                        "bad": {"prompt": "", "model_chain": []},
                    }
                ),
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(list(config["identities"]), ["good"])
            self.assertIn("bad", "\n".join(config["rejected"]))

    def test_document_that_validates_to_nothing_reads_as_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(home, _document({"bad": {"prompt": "", "model_chain": []}}))
            rejected: list[str] = []
            self.assertIsNone(read_identity_profiles_config(home, rejected_out=rejected))
            # The operator still sees why the only profile was dropped.
            self.assertIn("bad", "\n".join(rejected))

    def test_pathologically_nested_json_reads_as_absent_not_a_crash(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = identity_profiles_path(home)
            path.parent.mkdir(parents=True)
            path.write_text("[" * 60000 + "]" * 60000, encoding="utf-8")
            self.assertIsNone(read_identity_profiles_config(home))

    def test_fingerprint_changes_with_content(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(home, _document(_VALID))
            first = read_identity_profiles_config(home)["fingerprint"]["digest"]
            changed = {**_VALID, "review": {**_VALID["review"], "prompt": "Different."}}
            _write_config(home, _document(changed))
            second = read_identity_profiles_config(home)["fingerprint"]["digest"]
            self.assertNotEqual(first, second)


class IdentityProfileWriterTests(unittest.TestCase):
    def test_set_then_read_round_trips_and_clear_removes(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            set_identity_profile(
                home,
                "script-coding",
                prompt="Implement small scripts directly.",
                model_chain=[{"model_id": "deepseek-flash", "reasoning_effort": "low"}],
            )
            config = read_identity_profiles_config(home)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(
                config["identities"]["script-coding"]["prompt"],
                "Implement small scripts directly.",
            )
            cleared = clear_identity_profile(home, "script-coding")
            self.assertTrue(cleared["removed"])
            self.assertIsNone(read_identity_profiles_config(home))
            again = clear_identity_profile(home, "script-coding")
            self.assertFalse(again["removed"])

    def test_set_rejects_bad_name_prompt_and_chain(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            good_chain = [{"model_id": "m"}]
            with self.assertRaises(ValueError):
                set_identity_profile(home, "Bad Name", prompt="x", model_chain=good_chain)
            with self.assertRaises(ValueError):
                set_identity_profile(home, "ok", prompt="   ", model_chain=good_chain)
            with self.assertRaises(ValueError):
                set_identity_profile(home, "ok", prompt="x" * 4001, model_chain=good_chain)
            with self.assertRaises(ValueError):
                set_identity_profile(home, "ok", prompt="x", model_chain=[])
            with self.assertRaises(ValueError):
                set_identity_profile(
                    home, "ok", prompt="x", model_chain=[{"model_id": "has space"}]
                )
            with self.assertRaises(ValueError):
                set_identity_profile(
                    home,
                    "ok",
                    prompt="x",
                    model_chain=[{"model_id": "m", "reasoning_effort": "a" * 33}],
                )
            with self.assertRaises(ValueError):
                set_identity_profile(
                    home, "ok", prompt="x", model_chain=[{"model_id": "--flag"}]
                )
            self.assertFalse(identity_profiles_path(home).exists())

    def test_writers_refuse_an_unrecognized_existing_file(self) -> None:
        # A future-version or hand-edited document is never overwritten by a
        # write path that does not recognize it.
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = identity_profiles_path(home)
            path.parent.mkdir(parents=True)
            original = json.dumps(
                {
                    "schema_version": "omh_identity_profiles/v2",
                    "identities": {"keepme": {"prompt": "x", "model_chain": [{"model_id": "m"}]}},
                    "notes": "hand written",
                }
            )
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                set_identity_profile(
                    home, "x", prompt="y", model_chain=[{"model_id": "m"}]
                )
            with self.assertRaises(ValueError):
                clear_identity_profile(home, "keepme")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_clear_noop_creates_no_file(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = clear_identity_profile(home, "ghost")
            self.assertFalse(result["removed"])
            self.assertFalse(identity_profiles_path(home).exists())


if __name__ == "__main__":
    unittest.main()
