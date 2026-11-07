"""The trigger language pack contract.

Three things have to hold for packs to be a mechanism rather than a second
place to hide language literals:

1. A pack is validated data. Naming a skill that does not exist, or a phrase
   that can never match, is a refusal that says what is wrong -- not a silent
   drop, which is how a pack entry becomes a phrase its author believes is live.
2. Every shipped pack entry is reachable: routing the phrase actually reaches
   the skill the pack named. A dead entry fails here in whatever language it
   was written, which is the `whole_phrase_only_tokens` lesson applied to
   phrases.
3. Input and output support cannot diverge. Every language OMH will answer in
   is a language OMH can be addressed in.
"""

from __future__ import annotations

import json
import tempfile
import unicodedata
import unittest
from copy import copy
from pathlib import Path
from unittest import mock

from omh.commands.language import LANGUAGE_CODES
from omh.routing import lexical_shortlist
from omh.routing.localization import normalized_phrase
from omh.routing.recommend import (
    _prepare_definition,
    _prepared_routable_definitions,
    _tokens,
    recommend_skills,
)
from omh.routing.trigger_language_packs import (
    ORIGIN_SHIPPED,
    TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION,
    TriggerLanguagePack,
    is_latin_script,
    load_user_trigger_language_packs,
    merged_trigger_phrases,
    parse_trigger_language_pack,
    shipped_trigger_language_packs,
    shipped_trigger_pack_languages,
    trigger_pack_state,
    user_trigger_pack_dir,
)
from omh.skills import catalog
from omh.skills.catalog import builtin_definitions, routable_definitions


def _known_skills() -> frozenset[str]:
    return frozenset(definition.name for definition in builtin_definitions())


def _pack_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION,
        "language": "xx",
        "skills": {"plan": ["planlama yap"]},
    }
    document.update(overrides)
    return document


class TriggerLanguagePackValidationTests(unittest.TestCase):
    def _parse(self, document: object, *, language: str = "xx"):
        return parse_trigger_language_pack(
            document,
            language=language,
            origin="user",
            source="test",
            known_skills=_known_skills(),
        )

    def test_a_well_formed_pack_applies(self) -> None:
        pack, status = self._parse(_pack_document())

        self.assertEqual(status, "applied")
        assert pack is not None
        self.assertEqual(pack.phrases_by_skill(), {"plan": ("planlama yap",)})
        self.assertEqual(pack.phrase_count, 1)

    def test_an_unknown_skill_id_is_refused_rather_than_dropped(self) -> None:
        _, status = self._parse(_pack_document(skills={"not-a-skill": ["bir sey"]}))

        self.assertIn("unknown skill id 'not-a-skill'", status)

    def test_a_phrase_with_no_word_characters_is_refused(self) -> None:
        _, status = self._parse(_pack_document(skills={"plan": ["---"]}))

        self.assertIn("can ever match", status)

    def test_a_holdback_entry_that_removes_nothing_is_refused(self) -> None:
        # `ab` is under the tokenizer's three-character floor, so subtracting it
        # would remove nothing -- the exact shape of the #1188 dead hold-back.
        _, status = self._parse(_pack_document(whole_phrase_only_tokens={"plan": ["ab"]}))

        self.assertIn("produces no scored token", status)

    def test_every_problem_is_reported_at_once(self) -> None:
        _, status = self._parse(
            _pack_document(
                language="yy",
                skills={"not-a-skill": ["bir sey"], "plan": ["ok phrase", "ok phrase"]},
            )
        )

        self.assertIn("does not match the pack name", status)
        self.assertIn("unknown skill id", status)
        self.assertIn("repeats trigger phrase", status)

    def test_a_wrong_schema_version_is_refused(self) -> None:
        _, status = self._parse(_pack_document(schema_version="trigger_language_pack/v0"))

        self.assertIn("schema_version must be", status)

    def test_unsupported_fields_are_refused(self) -> None:
        _, status = self._parse(_pack_document(negative_controls=[]))

        self.assertIn("unsupported fields", status)

    def test_a_non_object_document_is_refused(self) -> None:
        _, status = self._parse([])

        self.assertEqual(status, "invalid: document must be a JSON object")


class UserTriggerPackLoadingTests(unittest.TestCase):
    def test_an_invalid_user_pack_is_named_and_the_others_still_load(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            home = Path(raw_home)
            directory = user_trigger_pack_dir(home)
            directory.mkdir(parents=True)
            (directory / "tr.json").write_text(
                json.dumps(_pack_document(language="tr")), encoding="utf-8"
            )
            (directory / "xx.json").write_text(
                json.dumps(_pack_document(skills={"nope": ["x"]})), encoding="utf-8"
            )

            packs, statuses = load_user_trigger_language_packs(home, _known_skills())

        self.assertEqual([pack.language for pack in packs], ["tr"])
        self.assertEqual(dict(statuses)["tr"], "applied")
        self.assertIn("unknown skill id 'nope'", dict(statuses)["xx"])

    def test_an_absent_pack_directory_is_normal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            packs, statuses = load_user_trigger_language_packs(Path(raw_home), _known_skills())

        self.assertEqual(packs, ())
        self.assertEqual(statuses, ())

    def test_state_reports_shipped_packs_and_the_user_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw_home:
            state = trigger_pack_state(Path(raw_home), _known_skills())

        self.assertEqual(state["schema_version"], TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION)
        shipped = {row["language"] for row in state["shipped"]}
        self.assertEqual(shipped, set(shipped_trigger_pack_languages()))
        self.assertEqual(state["user"], [])


class ShippedTriggerPackTests(unittest.TestCase):
    def test_the_shipped_packs_validate(self) -> None:
        packs = shipped_trigger_language_packs(_known_skills())

        self.assertTrue(packs)
        for pack in packs:
            with self.subTest(language=pack.language):
                self.assertEqual(pack.origin, ORIGIN_SHIPPED)
                self.assertTrue(pack.skills)

    def test_korean_moved_out_of_source_and_into_its_pack(self) -> None:
        # The move is the point: Korean goes through the same mechanism as every
        # other language rather than being the one language the source knows.
        korean = next(
            pack for pack in shipped_trigger_language_packs(_known_skills()) if pack.language == "ko"
        )

        self.assertGreater(pack_skill_count := len(korean.skills), 90, "the ko pack lost skills")
        self.assertGreater(korean.phrase_count, 800, f"the ko pack lost phrases ({pack_skill_count} skills)")

    def test_every_shipped_pack_phrase_is_live_in_its_skills_scored_surface(self) -> None:
        """The phrase counterpart of the hold-back reachability contract.

        A hold-back is dead when the word it names still scores. A phrase is
        dead when the opposite happens: the entry exists but nothing about it
        reaches the skill's scored surface, so it credits nothing no matter what
        the user types. Composed-vs-decomposed text, a stray zero-width
        character, or a phrase that tokenizes away entirely all produce it, and
        none of them are visible by reading the pack.

        This does not assert the phrase *wins* -- which skill outranks which on
        a given sentence is the routing corpora's question, not the pack's.
        """
        prepared_by_name = {
            prepared.definition.name: prepared for prepared in _prepared_routable_definitions()
        }
        dead: list[str] = []
        for pack in shipped_trigger_language_packs(_known_skills()):
            for skill, phrases in pack.skills:
                prepared = prepared_by_name.get(skill)
                if prepared is None:
                    continue  # Not routable; the catalog-merge test covers it.
                for phrase in phrases:
                    scores_as_phrase = normalized_phrase(phrase) in prepared.plain_trigger_phrases
                    scores_as_token = bool(_tokens(phrase) & prepared.trigger_tokens)
                    if not scores_as_phrase and not scores_as_token:
                        dead.append(f"{pack.language}/{skill}: {phrase!r}")

        self.assertEqual(
            dead,
            [],
            "Trigger pack phrases that credit nothing: neither the +6 phrase match nor a "
            "single scored token survives normalization, so the entry is dead weight its "
            "author believes is live: " + "; ".join(dead[:20]),
        )

    def test_a_latin_script_pack_adds_whole_phrases_and_nothing_else(self) -> None:
        """A Latin-script pack phrase scores as a phrase; its words never score alone.

        `ja`, `zh` and `ko` phrases carry Hangul, Kana or Han, so their words
        never meet an English message. A pack in a Latin-script language shares
        the English token space: the first `id` draft's phrases borrowed `bug`,
        `crash`, `error` and `file`, and with those words scoring on their own,
        or in the lexical index, English routes and shortlists moved (#2154).
        A diacritic does not keep a word apart: the router folds the `vi`
        words `cần`, `bạn` and `thêm` to `can`, `ban` and `them`, and with the
        rule keyed on ASCII the first `vi` draft's words scored alone and moved
        English routes again (#2182). So each skill's scored tokens,
        lexical-index document and shortlist anchors must equal the view with
        that skill's shipped Latin-script pack phrases taken out of its
        triggers. The view is built here from the packs, not from
        `shipped_latin_pack_phrases`, so a fault in that function shows up as
        a difference. That the phrase itself still scores is held by
        `test_every_shipped_pack_phrase_is_live_in_its_skills_scored_surface`;
        that a pack's hold-backs remove no English word is held by
        `test_a_pack_holds_back_only_words_its_own_scored_phrases_carry`.

        A Latin-script pack phrase that repeats one of the skill's authored
        triggers stays in the view, so it fails here: the rule would take that
        trigger's words out of scoring.
        """
        latin_phrases: dict[str, set[str]] = {}
        for pack in shipped_trigger_language_packs(_known_skills()):
            for skill, phrases in pack.skills:
                latin_phrases.setdefault(skill, set()).update(phrase for phrase in phrases if is_latin_script(phrase))
        # Without a Latin-script pack phrase, and one with a diacritic, this
        # compares the catalog with itself or misses the `vi` case.
        self.assertTrue(any(latin_phrases.values()))
        self.assertTrue(any(not phrase.isascii() for phrases in latin_phrases.values() for phrase in phrases))
        authored = {definition.name: set(definition.triggers) for definition in catalog._DEFINITIONS}
        without = {}
        for definition in builtin_definitions():
            taken_out = latin_phrases.get(definition.name, set()) - authored.get(definition.name, set())
            view = copy(definition)
            object.__setattr__(view, "triggers", tuple(t for t in definition.triggers if t not in taken_out))
            without[definition.name] = view
        # `_anchor_vocabulary` finds the skill through `routable_definitions`;
        # its uncached body runs against the view, and the cached live answers
        # are read only outside the patch.
        with mock.patch.object(lexical_shortlist, "routable_definitions", return_value=tuple(without.values())):
            anchors_without = {
                name: lexical_shortlist._anchor_vocabulary.__wrapped__(name) for name in without
            }

        moved: list[str] = []
        for prepared in _prepared_routable_definitions():
            definition = prepared.definition
            view = without[definition.name]
            if prepared.trigger_tokens != _prepare_definition(view).trigger_tokens:
                moved.append(f"{definition.name}: trigger tokens")
            if lexical_shortlist._document(definition) != lexical_shortlist._document(view):
                moved.append(f"{definition.name}: lexical document")
            if lexical_shortlist._anchor_vocabulary(definition.name) != anchors_without[definition.name]:
                moved.append(f"{definition.name}: anchors")

        self.assertEqual(
            moved,
            [],
            "A Latin-script pack moved what its words score on their own; its phrases "
            "must count only as whole phrases (`shipped_latin_pack_phrases`): " + "; ".join(moved[:20]),
        )

    def test_latin_script_pack_phrases_come_after_every_other_trigger(self) -> None:
        """A Latin-script pack takes none of the first places in a trigger list.

        The SKILL.md description and the capability row show only a skill's
        first triggers, and packs merge in language-code order, where `id`
        sorts before `ja` and `vi` before `zh`. With the `id` phrases in front,
        the description of `design-orchestration` lost three Japanese cues,
        `deep-interview` two and `ultraqa` one. So every shipped Latin-script
        pack phrase that the authored triggers do not already carry sits after
        every other trigger.
        """
        latin_phrases: dict[str, set[str]] = {}
        for pack in shipped_trigger_language_packs(_known_skills()):
            for skill, phrases in pack.skills:
                latin_phrases.setdefault(skill, set()).update(phrase for phrase in phrases if is_latin_script(phrase))
        authored = {definition.name: set(definition.triggers) for definition in catalog._DEFINITIONS}
        misplaced: list[str] = []
        for definition in builtin_definitions():
            latin = latin_phrases.get(definition.name, set()) - authored.get(definition.name, set())
            if latin and set(definition.triggers[len(definition.triggers) - len(latin):]) != latin:
                misplaced.append(definition.name)

        self.assertEqual(
            misplaced, [], "Latin-script pack phrases ahead of another trigger in: " + ", ".join(misplaced)
        )

    def test_a_pack_holds_back_only_words_its_own_scored_phrases_carry(self) -> None:
        """An ASCII hold-back word must come from one of the pack's Hangul, Kana or Han phrases.

        A `whole_phrase_only_tokens` entry stops a word scoring for the skill on
        its own, which is what a pack needs for the words of its own phrases. A
        phrase written wholly in Latin script already scores only as a whole
        phrase, so its words need no entry. An ASCII entry that none of the
        pack's other phrases for the skill carries can then only take the
        skill's English words away: its English trigger tokens and shortlist
        anchors.
        The first `id` draft's list did that (`codex`, `chatbot`, `debug`), and
        the parity test above cannot see it, because both sides of its
        comparison read the same hold-backs.
        """
        stray: list[str] = []
        for pack in shipped_trigger_language_packs(_known_skills()):
            phrases = pack.phrases_by_skill()
            for skill, entries in pack.whole_phrase_only_tokens:
                scored: set[str] = set()
                for phrase in phrases.get(skill, ()):
                    if not is_latin_script(phrase):
                        scored |= set(_tokens(phrase))
                for entry in entries:
                    if {token for token in _tokens(entry) if token.isascii()} - scored:
                        stray.append(f"{pack.language}/{skill}: {entry!r}")

        self.assertEqual(
            stray,
            [],
            "Hold-back entries whose ASCII words none of the pack's own non-Latin phrases "
            "carry, so they can only remove the skill's English words: " + "; ".join(stray[:20]),
        )

    def test_the_seed_packs_reach_their_lane_end_to_end(self) -> None:
        """One live probe per seed language, through the ordinary router."""
        probes = (
            ("ja", "ボローチェッカーの所有権エラーを直して", "rust"),
            ("ja", "RAGパイプライン構築と構造化出力スキーマを設計して", "llm-app-dev"),
            ("ja", "セグメンテーション違反とコアダンプを調べて", "native-debugging"),
            ("ja", "フロントエンドのランディングページを作って", "frontend"),
            ("zh", "借用检查器报所有权错误", "rust"),
            ("zh", "大模型应用开发要做检索增强生成", "llm-app-dev"),
            ("zh", "段错误和核心转储怎么排查", "native-debugging"),
            ("zh", "前端落地页需要响应式布局", "frontend"),
            ("ko", "빌드 실패 원인 봐줘", "build-failure-triage"),
            ("id", "lakukan riset mendalam", "research"),
            ("id", "review kode ini", "code-review"),
            ("id", "audit aksesibilitas", "accessibility-audit"),
            ("id", "build gagal", "build-failure-triage"),
            ("vi", "lập kế hoạch thực hiện", "plan"),
            ("vi", "rà soát mã nguồn", "code-review"),
            ("vi", "kiểm tra accessibility", "accessibility-audit"),
            ("vi", "build thất bại", "build-failure-triage"),
            ("vi", "tiến hành nghiên cứu chuyên sâu", "research"),
            ("ru", "сделай ревью кода", "code-review"),
            ("ru", "сборка упала", "build-failure-triage"),
            ("ru", "составь план реализации", "plan"),
            ("ru", "проверь доступность сайта", "accessibility-audit"),
        )

        for language, message, expected in probes:
            with self.subTest(language=language, expected=expected):
                top = recommend_skills(message, limit=1)
                self.assertEqual(top[0]["skill"], expected)

    def test_shipped_pack_phrases_reach_the_catalog(self) -> None:
        catalog_triggers = {
            definition.name: set(definition.triggers) for definition in routable_definitions()
        }
        merged = merged_trigger_phrases(shipped_trigger_language_packs(_known_skills()))

        missing = [
            f"{skill}: {phrase!r}"
            for skill, phrases in merged.items()
            if skill in catalog_triggers
            for phrase in phrases
            if phrase not in catalog_triggers[skill]
        ]

        self.assertEqual(missing, [], "shipped pack phrases that never reached the catalog")


class LanguageParityTests(unittest.TestCase):
    def test_every_output_language_also_ships_a_trigger_pack(self) -> None:
        """Input and output support cannot diverge again.

        `--language` / `OMH_LANG` decides what OMH answers in. A language OMH
        answers in but cannot be addressed in is the exact asymmetry trigger
        packs exist to close, so shipping an output localization without a
        trigger pack fails here. English needs no pack: it is the base corpus
        the catalog is authored in.
        """
        shipped = set(shipped_trigger_pack_languages())
        missing = sorted(code for code in LANGUAGE_CODES if code != "en" and code not in shipped)

        self.assertEqual(
            missing,
            [],
            "These languages ship localized OUTPUT but no trigger pack, so OMH answers in "
            "them without being able to recognise them: "
            + ", ".join(missing)
            + ". Add src/routing/trigger_packs/<lang>.json -- see docs/routing-quality.md.",
        )

    def test_a_pack_language_does_not_have_to_ship_output_localization(self) -> None:
        # The gate is one-directional on purpose. Recognising a language is
        # cheap and additive; translating every message is not, so a community
        # pack must not be blocked on a full output localization.
        self.assertIsInstance(shipped_trigger_pack_languages(), tuple)


class LatinScriptPredicateTests(unittest.TestCase):
    """`is_latin_script` decides which shipped phrases score only whole.

    It reads letters the way the router folds them, so a phrase whose words
    fold to ASCII tokens is Latin however it was typed.
    """

    def test_vietnamese_is_latin_composed_or_decomposed(self) -> None:
        phrase = "kiểm tra lỗi"

        self.assertTrue(is_latin_script(unicodedata.normalize("NFC", phrase)))
        self.assertTrue(is_latin_script(unicodedata.normalize("NFD", phrase)))

    def test_letters_that_fold_to_ascii_are_latin(self) -> None:
        self.assertTrue(is_latin_script("1º"))
        self.assertTrue(is_latin_script("ｂｕｇ"))
        self.assertTrue(is_latin_script("ʻokina"))

    def test_a_letter_of_another_script_is_not_latin(self) -> None:
        self.assertFalse(is_latin_script("review 代码"))
        self.assertFalse(is_latin_script("빌드 failed"))
        self.assertFalse(is_latin_script("ελληνικά"))
        self.assertFalse(is_latin_script("проверка"))

    def test_a_phrase_with_no_letter_has_nothing_to_decide(self) -> None:
        # Validation refuses such a phrase before it reaches a pack.
        self.assertTrue(is_latin_script("!!! --- 123"))


class TriggerLanguagePackShapeTests(unittest.TestCase):
    def test_merging_keeps_pack_order_and_drops_repeats(self) -> None:
        first = TriggerLanguagePack("aa", "user", "a", (("plan", ("one", "two")),))
        second = TriggerLanguagePack("bb", "user", "b", (("plan", ("two", "three")),))

        self.assertEqual(
            merged_trigger_phrases((first, second)),
            {"plan": ("one", "two", "three")},
        )


if __name__ == "__main__":
    unittest.main()
