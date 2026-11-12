# Prose Lexicon

`ai-slop-cleaner` is deletion-first and written for code. Prose in a repository
needs the same pass and a different instrument: README text, docstrings, commit
bodies, review comments, and report prose carry machine-writing tells that no
code smell describes. Load this when the cleanup target is written English.

Three instruments, used together: a word list in tiers, a pattern catalog with
severity, and a context profile that decides which rules apply at all.

## Word tiers

The tier says how much a hit weighs, not how hard it is to fix. Match inflected
forms - a listed word covers its plural, gerund, adverb, and conjugations -
except where a variant carries an honest separate sense, which is judged in
context rather than matched.

- **Tier 1A, frequency markers.** Words that appear far more often in machine
  text than in human writing. Replace every one. A cluster of them is evidence
  about how the passage was produced. Typical members: delve, leverage as a
  verb, seamless, robust as praise, testament, realm, landscape, pivotal,
  underscore, harness as a verb.
- **Tier 1B, clarity edits.** Wordiness and inflated formality: in order to,
  utilize, commence, ascertain, endeavor, prior to. Replace them too - the edit
  is identical - but a 1B hit is **not** evidence of machine authorship. People
  write this way. Keep 1B out of any density signal, so tightening wordy human
  prose can never push a document toward an "AI-written" verdict.
- **Tier 2, cluster words.** Fine alone, suspicious together. Flag when two or
  more appear in one paragraph.
- **Tier 3, density words.** Ordinary words that machine text overuses. Flag
  only at high density across the document, never on a single occurrence.

Report 1A and 1B separately. Merging them is what turns a wordiness report into
a false authorship accusation.

## Pattern severity

Patterns are shapes, not words, and they carry three severities.

- **P0, credibility killers.** Training-cutoff disclaimers, assistant artifacts
  left in the text, invented attributions to unnamed experts, unfilled
  placeholders, chat citation markup, and tracking parameters pasted in with a
  URL. Any one of these in a shipped document is a defect on its own.
- **P1, obvious tells.** Tier 1 vocabulary, slot-fill phrasing, "Let's" openers,
  formulaic openings, bold on every other phrase, em dashes well above the rate
  of ordinary prose, closing paragraphs that narrate a future, stacked hedges,
  moral adjectives on things that cannot have morals, and bullet lists whose
  items are bare noun phrases.
- **P2, polish.** Generic conclusions, the compulsive rule of three, uniform
  paragraph lengths, copula avoidance, and transition words carrying no
  transition.

## Context profiles

The same sentence is a defect in one register and correct in another. Name the
register before flagging anything.

| Profile | What it is | How the rules move |
| --- | --- | --- |
| `docs` | READMEs, guides, reference pages | clarity over voice; lists and structure are the format, not a smell |
| `code-comment` | comments, docstrings | strictest on overclaiming; a comment that asserts more than the code proves is P0 here |
| `commit-and-pr` | commit bodies, PR descriptions, review replies | strict on promotional and significance inflation; the reader is deciding whether to trust a claim |
| `report` | findings, postmortems, status writeups | extra strict on hedging and on anything that reads as evidence without being it |
| `casual` | internal notes, chat | P0 only |

When no profile is named, infer one from the destination and **say which one and
why** before reporting. The writer overrides. A rule absent from a profile's
adjustments applies at full strength.

## Running the pass

Prose cleanup follows the same discipline as `references/cleanup-passes.md`: one
category per pass, never bundled. Word tiers first, then patterns by severity,
then register fit. Between passes, re-read the paragraph whole - the failure
mode here is a document that passes every rule and no longer says anything,
because each fix was made against the rule instead of against the meaning.

Two edits are never in scope. Do not change a technical term because it appears
in a tier, and do not remove a hedge that is accurate; "may" in a sentence about
undefined behavior is doing work. Losing a true qualifier to a style rule turns
a correct document into a confident wrong one.
