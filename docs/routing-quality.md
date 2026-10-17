# Routing quality gate

The meta-router has a deterministic golden evaluation in
`tests/test_routing_quality.py`. It is intentionally separate from individual
skill tests so catalog or scoring changes are reviewed against user-shaped
routing outcomes.

The gate currently measures:

- known-lane dispatch accuracy across representative research, planning,
  coding, memory, paper, visual, and feedback requests;
- ambiguity guardrail behavior, including bounded candidates and a high
  confidence threshold; and
- unknown-input fallback behavior, including explicit fallback metadata.

The current baseline is 100% (7/7) on the known-lane golden set. This is a
regression baseline, not a claim about production traffic. The next telemetry
step should measure the same dimensions from privacy-safe route metadata:
dispatch accuracy from operator corrections, clarification rate, fallback
rate, and confidence-margin distributions.

Local traces can be summarized with:

```bash
omh learning metrics
```

The metrics command reads only metadata-only learning traces. Operator
missed-route corrections are counted separately and may include an expected
workflow identifier, while prompts and operator notes remain excluded.

## Adding a trigger language pack

People type in their own language. A trigger language pack is how OMH
recognises one, and adding a language is authoring a data file — not editing
the router, the catalog, or any list of supported locales.

A pack is one JSON document per language:

```json
{
  "schema_version": "trigger_language_pack/v1",
  "language": "pt-br",
  "skills": {
    "frontend": ["página inicial", "layout responsivo"],
    "build-failure-triage": ["falha de build", "erro de compilação"]
  },
  "whole_phrase_only_tokens": {
    "adversarial-consensus": ["revisão"]
  }
}
```

There are two places a pack can live, and the difference matters:

- **Shipped with the repo** — `src/routing/trigger_packs/<lang>.json`. These are
  product data: they merge into the catalog itself, so scoring, the rendered
  `skills/*/SKILL.md` trigger lists, and `docs/WORKFLOWS.md` all read one
  trigger table. Adding one means regenerating those artifacts in the same
  commit (see the Generated Artifacts Map in `CLAUDE.md`).
- **Your own** — `~/.omh/routing/trigger-packs/<lang>.json`, beside
  `routing/model-chains.json`. These merge at the scoring layer only, so your
  local phrases change what your router recognises and never rewrite the
  repo's generated artifacts. `omh doctor` lists both, and names any pack it
  refused. The route hint the Hermes plugin shows in chat uses them only
  where Hermes' interpreter can import `omh`; see
  [What the Hermes interpreter must be able to import](INSTALLATION.md#what-the-hermes-interpreter-must-be-able-to-import).

Rules the validator enforces, and why:

- `language` must match the filename. The file name is the pack's identity.
- Every key under `skills` must be a real skill id. An entry naming a skill
  that does not exist is a refusal, never a silent drop — a phrase quietly
  attached to nothing, or to the wrong lane, is the failure mode a pack has
  to make impossible.
- A phrase must contain word characters, and a `whole_phrase_only_tokens`
  entry must produce at least one scored token. An entry the normalizer cannot
  see is dead weight its author believes is live.
- Every problem in a document is reported at once, so fixing a pack takes one
  round trip.

Two things to get right in the phrases themselves:

- **Short, natural, unambiguous.** Phrases match by containment, so a phrase
  generic enough to sit inside an ordinary sentence turns every such sentence
  into a dispatch. Prefer fewer, safer phrases over broad coverage.
- **Pay for them with negative controls.** Add cases to
  `ROUTING_PRECISION_CASES` in `src/quality/routing_precision.py` proving
  ordinary questions in that language still get answered rather than routed,
  and to `ROUTING_INTERVENTION_CASES` proving the lanes you claim are reached.
  Both corpora assert exact counts; update them in the same commit.

A shipped pack phrase written entirely in ASCII is phrase-only. A Hangul,
Kana or Han phrase never shares a word with an English message, but a
Latin-script phrase can: Indonesian borrows `bug`, `crash`, `error` and
`file`. So an ASCII pack phrase scores only as a whole phrase. Its words do
not join the skill's trigger tokens, and the lexical shortlist's English index
leaves the phrase out of the skill's document and anchors, as it already
leaves out every non-ASCII trigger. The pack does not have to list those
words, and must not: an ASCII `whole_phrase_only_tokens` entry that none of the
pack's own non-ASCII phrases for the skill carries can only remove the skill's
English words. A phrase with any non-ASCII character scores as before, word by
word too, and that includes a Latin-script phrase with a diacritic:
`revisión de código` folds to the tokens `revision` and `codigo`, which score
on their own. ASCII pack phrases also merge after every pack phrase that has a
non-ASCII character, so where a surface shows only a skill's first triggers
(the `SKILL.md` description, the capability row), an ASCII pack phrase takes
none of the places the Hangul, Kana or Han phrases had. This covers shipped
packs only: a user pack's phrases also score word by word, so hold a word back
with `whole_phrase_only_tokens` where it should count only inside its phrase.

Two gates hold the mechanism together. `tests/test_trigger_language_packs.py`
proves every shipped phrase is live in its skill's scored surface, that every
skill's trigger tokens, lexical document and anchors stay as they are with its
shipped ASCII pack phrases taken out, that no pack holds back an ASCII word
none of its own non-ASCII phrases for that skill carries, and that every
language with a shipped `--language` / `OMH_LANG` **output** localization also
ships a **trigger** pack, so input and output support cannot diverge.
`tests/test_trigger_holdback_reachability.py` proves no hold-back entry, in any
language, quietly removes nothing.

## Calibrating the corpus against real recorded decisions

`ROUTING_PRECISION_CASES` and `ROUTING_INTERVENTION_CASES` are hand-written.
That is right for guarding regressions and useless for answering "does this
corpus look like what the router actually sees?" Tuning a threshold against a
corpus nobody has compared to real traffic is tuning against an assumption.

`omh chat route --record` already writes the raw material: one
`runtime/runs/<run-id>/routing.json` per recorded decision, carrying the
`route_decision/v1` contract. `omh learning route-calibration` aggregates those
files — no network, no model.

```sh
# Record decisions as you use the router. --record is per invocation.
omh chat route --record "why is the build failing on main"

# Read them back. --json for the full payload.
omh learning route-calibration
omh learning route-calibration --since "" --json   # every record, ignoring the window
```

**What it can and cannot tell you.** A routing record stores `message_sha256`
and `message_length`, never the message. So the report calibrates *decision
distributions* — which router stages fire, how often the router is confident,
how thin its margins run — and never phrasings. A new corpus phrase still has
to come from an operator's own message; these numbers say whether the corpus's
shape is wrong, not which sentence to add.

The procedure:

1. **Record a working week's worth of real decisions.** One sample is noise.
   Anything you would otherwise have typed into Hermes goes through
   `omh chat route --record` instead.
2. **Read parse coverage first, before any other number.** The report opens
   with `parsed / routing records found`, and names every skipped record under
   a reason (`no_routing_record`, `unreadable_json`, `unexpected_schema`,
   `missing_recorded_at`, `recorded_before_since`). A format skew that silently
   dropped a third of the records would bias everything below it, and nothing
   else in the output would say so. An empty store reports coverage as
   unmeasured, not as 0%.
3. **Compare shape, not counts.** Corpus totals and recorded totals are not
   commensurate. What is comparable: the router-stage mix, the confidence mix,
   and the margin spread. A corpus whose cases are almost all `explicit` while
   real decisions are mostly `recommendation` is tuned for a router path the
   operator rarely takes.
4. **Read the day-normalized median, not the flat one.** Recorded routing runs
   carry no session id, so the recording day is the normalization unit and the
   payload says so. `normalized_median` is the median of per-day medians, so an
   afternoon of heavy recording cannot dominate. When the two disagree
   sharply, the flat median is describing one day.
5. **Mind the window.** `--since` defaults to the modification time of
   `src/routing/chat.py`, so the default report covers only decisions made by
   the current router. Widen it with an explicit `--since` when you want a
   before/after across a router change, and say which window a reported number
   came from.
6. **Then change one thing.** Add the cases, move the threshold, or adjust the
   triggers — and re-run both the corpus gates and this report, quoting the
   window and the parse coverage alongside any number you report.
