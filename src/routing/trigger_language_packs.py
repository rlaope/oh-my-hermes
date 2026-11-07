"""Trigger language packs: the mechanism that makes any input language addable.

A skill's trigger phrases are how a deterministic router recognises what a
person typed. Those phrases used to exist only as source literals, so the set
of languages OMH could recognise was whatever the source happened to contain,
and reaching a new one meant editing `src/skills/catalog_definitions.py`. That
is a hardcoded language list wearing a data structure, and it makes every
language after the first two somebody else's pull request.

A trigger language pack is that same phrase table as validated data: one JSON
document per language, mapping a skill id to the phrases speakers of that
language actually type for it. Two sources merge deterministically:

* Repo-shipped packs in `omh.routing.trigger_packs` (`<lang>.json`). These are
  part of the product, so they merge into the catalog itself and every surface
  built from it -- scoring, the rendered `SKILL.md` trigger lists, the
  generated workflow docs -- sees exactly one trigger table.
* User packs under `<omh-home>/routing/trigger-packs/<lang>.json`, following
  the `routing/model-chains.json` precedent. These merge at the scoring layer
  only: a local pack changes what your router recognises, and never rewrites
  the product's generated artifacts, so the repo's byte gates stay a property
  of the repo rather than of whoever runs them.

Validation is strict, atomic, and loud. A pack naming a skill id that does not
exist is invalid rather than silently dropped, because a silently-dropped entry
is indistinguishable from a phrase that quietly pulls unrelated requests toward
the wrong lane. A phrase or hold-back entry that normalizes away to nothing is
invalid too: that is the #1188 lesson generalized -- an entry written in
composed Hangul that the NFKD-folding matcher can never see is dead weight the
author believes is live, and a dead entry in *any* language should fail at
authoring time rather than at routing time.

Everything here is pure: reading JSON files off disk and folding strings. No
network, no dependency, no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
import json
from pathlib import Path
import re
import unicodedata

from .localization import routing_terms, routing_tokens


TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION = "trigger_language_pack/v1"

# The package that carries the shipped packs. One `<lang>.json` per language.
SHIPPED_TRIGGER_PACK_PACKAGE = "omh.routing.trigger_packs"

# A language code is the pack's identity and its filename, so it stays a plain
# lowercase tag: `ko`, `ja`, `zh`, `pt-br`. No path separators, no case games.
_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")

# A trigger phrase is something a person types, not a paragraph. The bound is
# generous enough for a full sentence cue and tight enough that a pack cannot
# smuggle a document into a trigger table.
MAX_TRIGGER_PHRASE_CHARS = 120

ORIGIN_SHIPPED = "shipped"
ORIGIN_USER = "user"


class TriggerLanguagePackError(ValueError):
    """A shipped pack is invalid. Shipped packs are source, so this is a bug."""


@dataclass(frozen=True)
class TriggerLanguagePack:
    """One validated language pack, with its phrases in authored order."""

    language: str
    origin: str
    source: str
    skills: tuple[tuple[str, tuple[str, ...]], ...]
    whole_phrase_only_tokens: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def phrase_count(self) -> int:
        return sum(len(phrases) for _, phrases in self.skills)

    def phrases_by_skill(self) -> dict[str, tuple[str, ...]]:
        return {skill: phrases for skill, phrases in self.skills}

    def holdback_by_skill(self) -> dict[str, tuple[str, ...]]:
        return {skill: tokens for skill, tokens in self.whole_phrase_only_tokens}


def user_trigger_pack_dir(omh_home: str | Path | None = None) -> Path:
    """Where a person drops their own packs, beside `routing/model-chains.json`.

    Resolves the same default the rest of OMH does, `OMH_HOME` included, so a
    relocated home does not quietly leave the packs behind.
    """
    from ..system.paths import default_omh_home

    root = Path(omh_home).expanduser() if omh_home else default_omh_home()
    return root / "routing" / "trigger-packs"


def parse_trigger_language_pack(
    raw: object,
    *,
    language: str,
    origin: str,
    source: str,
    known_skills: frozenset[str],
) -> tuple[TriggerLanguagePack | None, str]:
    """Validate one already-parsed pack document.

    Returns ``(pack, "applied")`` or ``(None, "invalid: <problem>; <problem>")``.
    Every problem in the document is reported, not just the first, because a
    person fixing a pack by hand should need one round trip rather than five.
    """
    if not isinstance(raw, dict):
        return None, "invalid: document must be a JSON object"

    problems: list[str] = []

    if raw.get("schema_version") != TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION:
        problems.append(f"schema_version must be {TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION}")
    unsupported = sorted(set(raw) - {"schema_version", "language", "skills", "whole_phrase_only_tokens"})
    if unsupported:
        problems.append(f"unsupported fields {unsupported}")

    declared = raw.get("language")
    if not isinstance(declared, str) or not _LANGUAGE_CODE_RE.fullmatch(declared):
        problems.append("language must be a lowercase language tag such as 'ko' or 'pt-br'")
    elif declared != language:
        problems.append(f"language {declared!r} does not match the pack name {language!r}")

    skills_raw = raw.get("skills")
    skills: list[tuple[str, tuple[str, ...]]] = []
    if not isinstance(skills_raw, dict) or not skills_raw:
        problems.append("skills must be an object with at least one skill")
    else:
        for skill in sorted(skills_raw):
            entries = skills_raw[skill]
            if skill not in known_skills:
                problems.append(f"unknown skill id {skill!r}")
                continue
            if not isinstance(entries, list) or not entries:
                problems.append(f"skill {skill!r} must list at least one trigger phrase")
                continue
            phrases = _validated_phrases(skill, entries, problems)
            if phrases:
                skills.append((skill, phrases))

    holdback_raw = raw.get("whole_phrase_only_tokens", {})
    holdback: list[tuple[str, tuple[str, ...]]] = []
    if not isinstance(holdback_raw, dict):
        problems.append("whole_phrase_only_tokens must be an object")
    else:
        for skill in sorted(holdback_raw):
            entries = holdback_raw[skill]
            if skill not in known_skills:
                problems.append(f"whole_phrase_only_tokens names unknown skill id {skill!r}")
                continue
            if not isinstance(entries, list) or not entries:
                problems.append(f"whole_phrase_only_tokens for {skill!r} must list at least one token")
                continue
            tokens = _validated_holdback_tokens(skill, entries, problems)
            if tokens:
                holdback.append((skill, tokens))

    if problems:
        return None, "invalid: " + "; ".join(problems)

    return (
        TriggerLanguagePack(
            language=language,
            origin=origin,
            source=source,
            skills=tuple(skills),
            whole_phrase_only_tokens=tuple(holdback),
        ),
        "applied",
    )


def _validated_phrases(skill: str, entries: list[object], problems: list[str]) -> tuple[str, ...]:
    phrases: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            problems.append(f"skill {skill!r} has a trigger phrase that is not a non-empty string")
            continue
        phrase = entry.strip()
        if len(phrase) > MAX_TRIGGER_PHRASE_CHARS:
            problems.append(f"skill {skill!r} trigger phrase {phrase[:24]!r}... exceeds {MAX_TRIGGER_PHRASE_CHARS} characters")
            continue
        if not routing_terms(phrase):
            problems.append(
                f"skill {skill!r} trigger phrase {phrase!r} carries no word characters, "
                "so nothing in it can ever match"
            )
            continue
        if phrase in seen:
            problems.append(f"skill {skill!r} repeats trigger phrase {phrase!r}")
            continue
        seen.add(phrase)
        phrases.append(phrase)
    return tuple(phrases)


def _validated_holdback_tokens(skill: str, entries: list[object], problems: list[str]) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            problems.append(f"whole_phrase_only_tokens for {skill!r} has an entry that is not a non-empty string")
            continue
        token = entry.strip()
        if not routing_tokens(token):
            problems.append(
                f"whole_phrase_only_tokens for {skill!r} names {token!r}, which produces no scored token, "
                "so holding it back removes nothing"
            )
            continue
        if token in seen:
            problems.append(f"whole_phrase_only_tokens for {skill!r} repeats {token!r}")
            continue
        seen.add(token)
        tokens.append(token)
    return tuple(tokens)


def shipped_trigger_pack_languages() -> tuple[str, ...]:
    """Language codes the repo ships a pack for, sorted."""
    return tuple(sorted(name for name, _ in _shipped_pack_documents()))


@lru_cache(maxsize=1)
def _shipped_pack_documents() -> tuple[tuple[str, str], ...]:
    """(language, raw JSON text) for every shipped pack, sorted by language."""
    resources = files(SHIPPED_TRIGGER_PACK_PACKAGE)
    documents = [
        (entry.name[: -len(".json")], entry.read_text(encoding="utf-8"))
        for entry in resources.iterdir()
        if entry.name.endswith(".json")
    ]
    return tuple(sorted(documents))


@lru_cache(maxsize=2)
def shipped_trigger_language_packs(known_skills: frozenset[str]) -> tuple[TriggerLanguagePack, ...]:
    """Every shipped pack, validated. An invalid shipped pack raises."""
    packs: list[TriggerLanguagePack] = []
    for language, text in _shipped_pack_documents():
        source = f"{SHIPPED_TRIGGER_PACK_PACKAGE}/{language}.json"
        try:
            raw = json.loads(text)
        except ValueError as error:
            raise TriggerLanguagePackError(f"{source} is not valid JSON: {error}") from error
        pack, status = parse_trigger_language_pack(
            raw,
            language=language,
            origin=ORIGIN_SHIPPED,
            source=source,
            known_skills=known_skills,
        )
        if pack is None:
            raise TriggerLanguagePackError(f"{source} is {status}")
        packs.append(pack)
    return tuple(packs)


def load_user_trigger_language_packs(
    omh_home: str | Path | None,
    known_skills: frozenset[str],
) -> tuple[tuple[TriggerLanguagePack, ...], tuple[tuple[str, str], ...]]:
    """Read `<omh-home>/routing/trigger-packs/*.json`.

    Returns ``(packs, statuses)`` where statuses pairs each pack file name with
    ``applied`` or ``invalid: <problems>``. An invalid user pack is refused with
    its problems named and the rest keep loading -- one bad local file must not
    take the router's other languages down with it.
    """
    directory = user_trigger_pack_dir(omh_home)
    try:
        candidates = sorted(path for path in directory.iterdir() if path.suffix == ".json")
    except (FileNotFoundError, NotADirectoryError, OSError):
        return (), ()

    packs: list[TriggerLanguagePack] = []
    statuses: list[tuple[str, str]] = []
    for path in candidates:
        language = path.stem
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            statuses.append((language, "invalid: unreadable JSON"))
            continue
        pack, status = parse_trigger_language_pack(
            raw,
            language=language,
            origin=ORIGIN_USER,
            source=str(path),
            known_skills=known_skills,
        )
        statuses.append((language, status))
        if pack is not None:
            packs.append(pack)
    return tuple(packs), tuple(statuses)


def merged_trigger_phrases(packs: tuple[TriggerLanguagePack, ...]) -> dict[str, tuple[str, ...]]:
    """Skill id -> the packs' phrases, in pack order, de-duplicated."""
    merged: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for pack in packs:
        for skill, phrases in pack.skills:
            bucket = merged.setdefault(skill, [])
            known = seen.setdefault(skill, set())
            for phrase in phrases:
                if phrase in known:
                    continue
                known.add(phrase)
                bucket.append(phrase)
    return {skill: tuple(phrases) for skill, phrases in merged.items()}


def is_latin_script(phrase: str) -> bool:
    """True when every letter of `phrase` is a Latin letter, ASCII or not.

    A pack phrase in a Latin-script language shares the English token space:
    the router folds `lỗi` to `loi` and `cần` to `can`, so a diacritic does not
    keep its words apart from English ones. A phrase with any Hangul, Kana or
    Han letter is not Latin script. Digits, spaces, punctuation and combining
    marks are not letters and do not decide.

    The letters are read after NFKC, because the router folds by NFKD: a
    fullwidth `ｂｕｇ` or the ordinal `º` folds to an ASCII word, so it must
    count as Latin here too. Modifier letters (`ʼ`, `ʻ`, category Lm) mark a
    neighbouring letter rather than spell a word, and do not decide either.
    """
    return all(
        unicodedata.name(character, "").startswith("LATIN")
        for character in unicodedata.normalize("NFKC", phrase)
        if character.isalpha() and unicodedata.category(character) != "Lm"
    )


def merged_holdback_tokens(packs: tuple[TriggerLanguagePack, ...]) -> dict[str, frozenset[str]]:
    """Skill id -> the packs' whole-phrase-only hold-back entries."""
    merged: dict[str, set[str]] = {}
    for pack in packs:
        for skill, tokens in pack.whole_phrase_only_tokens:
            merged.setdefault(skill, set()).update(tokens)
    return {skill: frozenset(tokens) for skill, tokens in merged.items()}


def trigger_pack_state(
    omh_home: str | Path | None,
    known_skills: frozenset[str],
) -> dict[str, object]:
    """Machine-readable description of which packs are in force."""
    shipped = shipped_trigger_language_packs(known_skills)
    user_packs, statuses = load_user_trigger_language_packs(omh_home, known_skills)
    return {
        "schema_version": TRIGGER_LANGUAGE_PACK_SCHEMA_VERSION,
        "shipped": [
            {
                "language": pack.language,
                "skill_count": len(pack.skills),
                "phrase_count": pack.phrase_count,
                "source": pack.source,
            }
            for pack in shipped
        ],
        "user_pack_dir": str(user_trigger_pack_dir(omh_home)),
        "user": [
            {
                "language": language,
                "status": status,
                "skill_count": next(
                    (len(pack.skills) for pack in user_packs if pack.language == language), 0
                ),
                "phrase_count": next(
                    (pack.phrase_count for pack in user_packs if pack.language == language), 0
                ),
            }
            for language, status in statuses
        ],
    }
