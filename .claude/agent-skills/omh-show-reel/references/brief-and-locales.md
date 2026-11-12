# Brief and locale decisions

Craft depth for the brief (what to ask and not ask, concept candidates, the
`concept.md` form, time/credit estimates, research prompts) is in
`references/craft-brief.md`. This page decides language and locale; where the
craft text assumes Korean content, this page's resolution wins.

## Intake before aesthetics

Recover supplied objective, audience, channel, source revision, brand permissions,
requested duration, dimensions/aspect ratio, fps, container, filesize cap, deadline,
budget and delivery target. Honor explicit duration and format; no universal 10 s,
vertical, dark-terminal, Korean or English production default. Ask only for
irretrievable hard facts that change production; mark reversible creative choices
as assumptions and proceed within scope. Do not interrogate the user for a palette.

Fill `show_reel_brief/v1`:

- objective, audience/channel, requested action and success evidence;
- duration, aspect_ratio, dimensions, fps, filesize_cap, deadline, revision_budget;
- source/brand boundaries, available tools, missing facts and stop conditions;
- reply_language, audience_locales, content_locale and decision_basis;
- onscreen_text, subtitle_text, narration_script, pronunciation_text;
- typography_policy, font_policy, direction_policy, voice_policy, translation_policy;
- literal_tokens with original bytes, locale version, reviewer and approval state.

These are authored artifact fields, not executable schemas or new OMH RPCs.
Keep media and copy in the approved project directory; metadata records contain
bounded safe references, hashes, status and gaps only.

## Language resolution

Priority: current explicit user/audience/channel instructions > applicable stable
preferences > user language. Do not infer a US locale from an English sentence or
Korean content from Korean conversation. Same-priority conflicts need one question;
unknown facts remain unknown. Keep reply_language under the host's persona even
when content_locale differs. Translation must not silently change an approved claim.

Separate screen/subtitle/voice/pronunciation versions. Preserve IDs, commit SHA,
commands, flags, paths, URLs, API keys as field names (never secret values), user
names and nontranslatable trademarks literally. An approved pronunciation respelling
belongs only in pronunciation_text, not in onscreen_text or source quotations.

Each text run records BCP47 language/script, direction, approved copy, font chain,
line break policy and measured reading/utterance timing. Do not assume locale
support because a field or TTS language option exists. Verify the exact renderer,
font file, representative strings, shaping, fallback, weights and actual output.
No font download, translation API, TTS, STT or paid voice is implicit. voice_policy
starts absent/not_required/unknown, never with a fixed language or voice ID.

## Acceptance fixtures (coverage contracts, not support certification)

| Case | Decision and checks |
| --- | --- |
| EN | Explicit English audience on a muted channel: English screen/subtitles; no required voice, audio or STT. Inspect actual glyphs and measured reading time. |
| KO→EN | Korean reply with current explicit English audience beats stable Korean preferences: content English, reply unchanged. Literal brands/commands survive. |
| KO | Explicit Korean audience: native Hangul line break and grapheme grouping; no forced Hangul-as-material aesthetic. |
| JA | Japanese audience with long brand/number strings: native prohibited-break rules, glyph fallback and measured pacing; preserve trademarks. |
| ZH | Distinguish zh-Hans/zh-Hant and any explicit region; conflicting script requests HOLD rather than auto-conversion. Inspect native line break and punctuation. |
| AR | Arabic with numbers, URL and command: Arabic shaping and bidi order must be rendered; isolate LTR runs individually, do not reverse the whole scene. |
| Mixed | English/Japanese/Arabic runs in one scene with Korean reply: per-run language, font and direction; never rewrite every run to one locale. |
| Missing font | Missing glyph/tofu, broken shaping or unverified fallback means HOLD; an installed family name is not font coverage evidence. |
| Voice absent | No narration required means no forced voice. If speech was requested but unsupported or unconsented, offer subtitle-only explicitly or HOLD; never claim audio creation. |

CLI language is independent: English by default, explicit `--language` or `OMH_LANG`
only. No OS detection. Canonical triggers remain English; existing language packs
follow their own authoring rules. Arabic content QA does not claim an Arabic
lexical routing pack: use explicit `omh-show-reel` or observed host selection,
and name unverified natural-language routing coverage.
