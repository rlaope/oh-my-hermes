# Handover Artifacts

Three artifacts close a long piece of work: a **deep guide**, an **ELI5 pass**,
and a **quiz**. They are written for whoever opens the work next - the same
person after the context is gone, or a model with no memory of the session.
Not a teammate being onboarded, not an outsider, and not publication prose.

`wiki`'s interview asks whether an agent is one of the readers. Here the answer
is always yes, so write for recall: short, named, and searchable over polished.

## Assemble from what is readable, never from what you remember

The other three sections depend on this one.

By the time these artifacts are written the early reasoning is no longer in
context - compaction took it - and a model asked to explain a decision it can
no longer see will reconstruct one. The reconstruction is fluent, it agrees
with the diff, and it is invented. It is also the worst thing to leave behind,
because nothing downstream can tell it from the reason that was actually there.

Some of the reasons were written down while they were still true.

| Source | Held where | Read these | What it supplies |
| --- | --- | --- | --- |
| Plan record (`omh_todo/v1` item) | durable record, read with `omh runtime todo show` | `state`, `phase`, `blocked_reason` | what was done, which stage it belonged to, and what was skipped with its reason |
| Verification gate (`omh-verification-gate`) | optional durable model declaration, read with `omh_todo action=recall`; absent unless recorded | `observed_check_results/v1`, `claim_verdict/v1` | command, source, exit status, summary, scope, freshness, and origin for each check that ran (`origin` on a failing check only), plus which checks are missing or failed |
| Review (`omh-code-review`) | optional durable model declaration, read with `omh_todo action=recall`; absent unless recorded | `ranked findings per axis` | what a reader misses unless someone tells them |
| QA (`ulw-qa`) | optional durable model declaration, read with `omh_todo action=recall`; absent unless recorded | `pass/fail evidence` | what nobody thought of the first time |

**Read the "held where" column before planning the work.** The live plan is at
`$OMH_HOME/runtime/todos/<session key>.json`, read with `omh runtime todo show`.
The other three -- Verification gate, Review and QA -- can be recorded as bounded declarations
with `omh_todo action=record` under a scope checkpoint, then read in a later
session with `omh_todo action=recall`. Read the checkpoint index first if its ID
is no longer in context. Only the active profile and logical project are visible.

Recording preserves what a model claimed, not what actually happened. Original
outputs remain separate; absent, stale or malformed records are not clean runs.
Do not reconstruct missing findings from conversation memory. A declared empty
finding set means only that the writer declared none found.

Every sentence in all three artifacts either restates one of those fields or is
marked as the writer's own inference. There is no third category. Quote the
field rather than paraphrasing it; a paraphrase of a reason is where the drift
starts.

An empty field is an answer, and an unreadable source is a different answer.
No item carrying a `blocked_reason` means nothing was blocked. A verification
verdict you cannot find means you cannot say whether one was issued. Never
collapse the second into the first.

This repository already applies the rule one stage earlier. `blocked_reason`
is a field because the stop criterion used to be inferred from item text, and
the inference was wrong in both directions on ordinary input. Reading a record
instead of a sentence is that same fix, applied at the end of the work instead
of the middle - and it works exactly as far as there is a record to read.

## Deep guide

The next reader has the diff. What they do not have is why it looks like that,
and that is all the deep guide carries.

- Start from the plan record or accepted scope checkpoint, in stored order.
  Read the live checklist with: `omh runtime todo show`. One section per done item, taken in plan
  order and grouped by `phase` where items carry one. There is no phase
  order to sort by: `phase` is a free-text label with no canonical sequence,
  and it is absent entirely on an item that was given none. The list's own
  order is the only order there is.
- Know what the record can hold before planning around it. It caps at
  20 items, so the guide has at most that many sections, and an
  item's text caps at 200 characters, which is the whole of
  "what changed" the record can give you. A plan that spends items on phase
  headers has that many fewer for the work.
- A done item absent from the guide is a gap: either write it or name it as
  deliberately omitted.
- Each section answers three questions. **What changed** - the item's own
  text. **Why this way** - the `blocked_reason` of what was not taken, plus
  whichever review findings the session still holds. **What proves it** - the
  observed check rows, by command and exit status, when they are still in
  reach; `not_in_reach` when they are not. The third answer is the one most
  often missing, and a guide that says so is more useful than one that fills
  the gap in.
- Delete any sentence `git show` would have told the reader. A guide that
  narrates the diff costs a read and returns nothing.
- Name the file and the symbol. Never the line number and never a count: both
  drift, and a pointer that drifts sends the next reader hunting for a string
  that is no longer there.
- A decision with no recorded reason is written as having no recorded reason.
  That sentence is worth more than a plausible one.

## ELI5 pass

Level `very_easy`, the word `omh-paper-learning` uses for the same idea, so one
level keeps one name. Nothing records the level - there is no handover store
to record it in - so it is shared vocabulary for saying what you wrote, not a
field anything reads back. The ELI5 pass is the deep guide at that level: not
a second document and not a second source.

- It is a projection. A claim the deep guide does not make was invented at the
  moment of simplifying.
- `very_easy` here means: expand every repo-internal term on first use, one idea
  per sentence, and the reason before the mechanism.
- `very_easy` never means dropping a boundary, a refusal, or a `blocked_reason`.
  Simplification removes vocabulary; it never removes a claim. That is the
  coverage-preserving constraint `omh-paper-learning` already holds, applied to a
  change instead of a paper.
- No deep guide, no ELI5 pass. An easy explanation with nothing behind it is a
  guess that reads as an authority.

## Quiz

The quiz is a completeness check on the deep guide. It is not a study aid and
nobody is being graded.

**Every question cites one entry, and a question that cannot cite one is not
written.** Three entry kinds are admissible and no others.

| Admissible entry | Where it comes from | What it proves |
| --- | --- | --- |
| A review finding | Review (recorded declaration, if available) | a reader misses this unless told |
| A failed check | QA (recorded declaration, if available), Verification gate (recorded declaration, if available) | nobody thought of it the first time |
| A recorded `blocked_reason` | Plan record | a judgement was made and needs explaining |

Each one is a record of something that actually went wrong or was actually
decided. That is the entire admission test, and it is what stops the quiz
becoming "what does this change do" - a question whose answer is in the diff,
which tests nothing and passes always.

The rule stands whatever the source. What the "held where" column changes is
its reach: only a `blocked_reason` can be cited **durably**, because only the
plan record survives the session. The other two kinds are citable while this
session still holds them, and a question built on one of them cannot be
re-checked by the next reader. Say which kind a question is, so the next
reader knows whether they can go back to the entry or only to your account
of it.

- Carry the citation with the question: the entry kind and the entry's own
  identifier - finding id, check name, or the item the reason hangs on.
- Answer from the deep guide only. **A question the deep guide cannot answer is
  a hole in the deep guide.** Record it as a gap and fix the guide. Do not
  soften the question, and do not answer it from memory of the session.
- One question per admissible entry, and no padding. Two findings, no failed
  checks and nothing blocked is a two-question quiz, and two is the right
  answer rather than a thin one.

**Zero questions is the ordinary outcome, not a clean bill of health.** Three
of the four sources vanish with the session, the plan record is opt-in, and
one written by another session is unlinked after a day. So an empty quiz never
says "nothing went wrong". Report the basis instead, one of:

- `entries_observed`
- `sources_read_no_entries`
- `session_sources_lost`
- `plan_record_absent`
- `unknown_or_missing`

That is the distinction `omh-paper-learning` draws with its own source states,
where "not observed" and "observed and absent" are different answers. Only
`sources_read_no_entries` is a statement about the change; the rest are
statements about what could be read.

## Boundary

The three artifacts are prepared retained knowledge. They are not execution,
verification, review, CI, merge-readiness, or merge evidence. A deep guide
restating a PASS verdict has not re-proved it, and writing all three closes
nothing that was not already closed.

One sentence about why this page is scoped the way it is, so the next reader
does not take the scope for a preference: OMH asks a model to produce
verification verdicts, review findings, and QA evidence, and persists none of
them, so only the plan record can be cited after the session ends. Whether
that changes is a product question filed separately; until it does, write
these artifacts against what is actually readable and say what was not.
