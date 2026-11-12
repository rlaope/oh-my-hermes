# Briefing Document Format

The rules below govern the briefing the research engine writes when the reader is a person. They do not govern the coding-agent handoff, which stays dense findings, exact symbols, and file paths with no narrative. Ask which one is wanted before retrieval starts, because the answer changes what the run records, not only how it is written up.

These rules are authored in English and applied to a document written in any language. A rule about sentence order or title shape is not an English rule; it survives translation. The clause-level examples below are English so the shape is legible, and each names the property being tested rather than the words.

## Titles

**Compress a title to a noun phrase.** Name the subject; do not state a sentence about it.

- WRONG: `Load rises as input grows` -> RIGHT: `Load growth under rising input`
- WRONG: `Each expert gets different traffic` -> RIGHT: `Expert load imbalance`
- WRONG: `Deployment is simple` -> RIGHT: `What a GQA deployment has to decide`

**Use the established term.** Write the term the field uses rather than a paraphrase of it. When the document body is not in English, put the English term in parentheses at first use.

**Prefix a role label.** The shape is `Role - noun phrase`. Without the label a reader cannot tell whether the section states a problem, an advantage, or an observation. The vocabulary is closed: Concept, Problem, Option, Solution, Reversal, Case, Guideline, Constraint, Pitfall, Limit, Cost, Deployment, Check.

**A cost title names both sides.** Say what was spent and what it bought.

- WRONG: `Cost - precise retrieval and reproducibility are given up`
- RIGHT: `Cost - retrieval precision weakens in proportion to the KV cache removed`

**Five title shapes are banned.**

- Numeric scaffolding: `(1) problem / (2) mechanism / (3) numbers`
- Evaluation only: `Deployment is simple`
- Counting only: `Three options`
- Repetition: the same title used for four different sections
- Metaphor: `Copying something compressed is wasted work`

## Sentences

- **Order.** Cause before effect, premise before verdict, observation before reading. Do not state the conclusion first and attach its support afterward.
- **Endings.** Ban the shapes that announce their own rhetorical role: `that is the cost`, `the point is that`, `the reason is`. Rewrite `the reason it works is here` as `it works because ...`.
- **Deixis.** Do not point across sentences with `here` or `this`. Name the thing.
- **Emphasis.** Do not bold a conclusion and then supply its evidence underneath. Emphasis marks a term, not a verdict.
- **Enumeration.** Ban `A is X. B is Y. C is Z.` Carry the previous paragraph's conclusion into the next paragraph's opening.
- **Length.** Inside one list, keep the items the same size.

Four sentence forms are banned outright: the question-and-answer frame (`the question X answered was`), the rhetorical question (`so what happens?`), intensifiers (`dramatically`, `overwhelmingly`, `decisively`), and methodology exposure - the document never mentions its own method, its review, or the feedback that shaped it.

## Content

- Open on the problem, with numbers, and establish the premises before anything else.
- Define a term where it first appears, expanding the acronym there. A definition that exists only in the appendix is not a definition.
- Ground every number in a premise the reader has already been given, so the figure is derived rather than asserted.
- Explain every setting and parameter, not one selected example. The order is: what it decides, then the options, then why this value.
- Derive a setting from the preceding calculation. Do not list settings as items.
- Open each chapter with one paragraph defining its subject and a figure contrasting it with the neighbouring idea.
- Let the limit that closes a chapter become the problem that opens the next.
- When the assessment turns from favourable to unfavourable, write the transition paragraph: state what has been solved so far and what has not been examined yet.
- Keep back-references minimal, and never forward-reference.

## Form

- **Figures.** Draw flow, structure, calculation, and scale contrasts in code blocks.
- **Lists.** Bullets for parameter explanations. A table only when several subjects are compared on the same axes.
- **Block quotes.** Analogies and warnings only. Body explanation never goes in a quote.
- **Subheads.** What should be a subhead is written as a subhead, not as a sentence in running text.
- **Code.** Runnable form, attached to every case the document discusses.

## Structure

Learning objectives (what the reader can do once the document is closed) -> assumed knowledge, what is built from scratch, and what is out of scope -> contents -> body as part, chapter, section -> Appendix A: glossary -> Appendix B: misconceptions and traps -> Appendix C: sources.

## Exercises

Run exercises as a hypothetical scenario, and build failure into it: a session that succeeds on the first attempt teaches nothing. Logs and output follow the real format of the tool being shown, with the values marked as simulated.

## Currency

Confirm the current state by retrieval rather than recall. Separate durable principles from time-dependent figures, and give every time-dependent figure its as-of date and how it was confirmed. Separate vendor claims from independent measurement, and present the unfavourable data alongside the favourable.

## Language

The output language is declared by the requester and never inferred from the language of the request. Body prose, role labels, chapter headings, and appendix captions follow the declared language together -- a Korean briefing under English section captions is a half-translated document. Identifiers, schema ids, file paths, command names, and code stay as written. The language declaration is required; omission is refused.

OMH holds no translation table for the scaffolding, because one would have to be maintained for every language the engine can write in. Supply the labels with the payload instead: `role_labels` maps a role to its label in the document's language, `captions` supplies headings, metadata labels and the displayed evidence boundary. Explicit `en` may use English defaults; non-English output requires caller-supplied translations for every role and caption actually rendered. Unused labels need no translation. Translating the body while leaving rendered captions unset is refused. Structured receipt values and schema boundaries stay unchanged; only display labels are translated.

## Evidence boundary

A briefing is prepared decision context. It is not execution, review, CI, merge-readiness, or merge evidence, and neither is any figure inside it. A rendered page is a page: calling it a PDF requires observed file evidence, and the format handoff is `handoff_prepared` until then.
