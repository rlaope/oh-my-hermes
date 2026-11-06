"""Closed per-language word lists for the messenger chat gate.

Data only; `messenger_gate` holds the logic. Each language is one entry in
`LANGUAGES`, and every entry is checked for every message whatever the
profile's language is: a Korean deployment still understands "shut up".

To add a language, add one `Language` row. Keep each list small and closed:

- `quiet`: whole messages that tell the bot to be quiet. A message matches only
  when, after Unicode NFKC, casefolding, and dropping punctuation, symbols,
  emoji and every space, it equals one entry normalized the same way. A quiet
  word inside a longer sentence never matches.
- `quiet_needs_address`: the `quiet` entries that are also ordinary single
  words (`silence`, `うるさい`). They mute only when aimed at the bot by a
  mention, a reply or its name, never just for arriving in a thread.
- `vocative_suffixes`: what follows a name when someone is called
  (Korean `민수야`, Japanese `田中さん`). An entry may start with a space when
  the language writes one (Vietnamese `Lan ơi`).
- `vocative_prefixes`: words that open a call before a name (`hey alex`).
- `second_person_tokens`: words for "you", matched as whole words. For
  languages written with spaces.
- `second_person_substrings`: words for "you" in scripts written without
  spaces, matched anywhere. Only words that cannot be part of another word.

German formal `Sie` is not listed: casefolding makes it `sie` (she, they).
"""

from __future__ import annotations

from typing import NamedTuple


class Language(NamedTuple):
    code: str
    quiet: tuple[str, ...]
    quiet_needs_address: tuple[str, ...] = ()
    vocative_suffixes: tuple[str, ...] = ()
    vocative_prefixes: tuple[str, ...] = ()
    second_person_tokens: tuple[str, ...] = ()
    second_person_substrings: tuple[str, ...] = ()


LANGUAGES: tuple[Language, ...] = (
    Language(
        "en",
        quiet=("quiet", "be quiet", "shut up", "stay out", "hush", "shush", "shh", "stop talking", "keep quiet"),
        quiet_needs_address=("quiet", "hush", "shh"),
        vocative_prefixes=("hey", "hi", "yo"),
        second_person_tokens=("you", "your", "yours", "yourself"),
    ),
    Language(
        "ko",
        quiet=(
            "조용히", "조용", "조용히 해", "조용히 좀 해", "좀 조용히 해", "조용히 해줘", "조용히 해 줘",
            "조용히 하세요", "조용히 해 주세요", "닥쳐", "닥쳐라", "입 다물어", "빠져", "빠져 있어",
            "그만 끼어들어", "끼어들지 마",
        ),
        quiet_needs_address=("조용", "조용히", "빠져"),
        vocative_suffixes=("야", "아"),
        vocative_prefixes=("야",),
        second_person_tokens=(
            "니가", "너가", "네가", "너", "너는", "너도", "너랑", "너한테", "너를", "너의", "니", "니도",
            "니는", "너희", "너희들", "당신", "당신이", "당신은", "당신도",
        ),
    ),
    Language(
        "ja",
        quiet=("黙って", "黙れ", "黙ってて", "静かに", "静かにして", "静かにしてください", "うるさい"),
        quiet_needs_address=("うるさい", "静かに"),
        vocative_suffixes=("さん", "くん", "ちゃん", "さま", "様"),
        second_person_substrings=("あなた", "あんた", "お前", "おまえ"),
    ),
    Language(
        "zh-Hans",
        quiet=("闭嘴", "安静", "安静点", "安静一点", "别说了", "别说话"),
        quiet_needs_address=("安静",),
        second_person_substrings=("你", "您"),
    ),
    Language(
        "zh-Hant",
        quiet=("閉嘴", "安靜", "安靜點", "安靜一點", "別說了", "別說話"),
        quiet_needs_address=("安靜",),
        second_person_substrings=("你", "您"),
    ),
    Language(
        "es",
        quiet=("cállate", "callate", "cállense", "silencio", "a callar"),
        quiet_needs_address=("silencio",),
        vocative_prefixes=("oye", "hola"),
        second_person_tokens=("tú", "tu", "usted", "te", "ti"),
    ),
    Language(
        "fr",
        quiet=("tais-toi", "taisez-vous", "silence", "chut"),
        quiet_needs_address=("silence", "chut"),
        vocative_prefixes=("hé", "salut"),
        second_person_tokens=("tu", "toi", "vous", "te"),
    ),
    Language(
        "de",
        quiet=("sei still", "seid still", "halt den mund", "halt die klappe", "ruhe", "sei ruhig"),
        quiet_needs_address=("ruhe",),
        vocative_prefixes=("hallo",),
        second_person_tokens=("du", "dich", "dir", "dein", "deine"),
    ),
    Language(
        "pt",
        quiet=("cala a boca", "cala-te", "silêncio", "fica quieto", "fique quieto"),
        quiet_needs_address=("silêncio",),
        vocative_prefixes=("ei", "oi", "olá"),
        second_person_tokens=("você", "voce", "tu", "te"),
    ),
    Language(
        "ru",
        quiet=("замолчи", "помолчи", "молчи", "тихо", "заткнись"),
        quiet_needs_address=("тихо", "молчи"),
        vocative_prefixes=("эй", "привет"),
        second_person_tokens=("ты", "вы", "тебя", "тебе", "вас", "вам"),
    ),
    Language(
        "vi",
        quiet=("im đi", "im lặng", "câm miệng", "im mồm"),
        quiet_needs_address=("im lặng",),
        vocative_suffixes=(" ơi",),
        second_person_tokens=("bạn", "mày", "cậu"),
    ),
)
