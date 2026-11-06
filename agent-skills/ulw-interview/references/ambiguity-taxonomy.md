# Ambiguity Taxonomy

`deep-interview` asks one question at a time and stops on clarity. This says how
to decide which questions are worth a round, and where the answers go so the
next lane reads them instead of the transcript. Load it before the first
question.

Scanning is free and asking is not. Score the whole taxonomy first, then spend
the round budget on the categories that scored worst.

## Score every category before asking anything

Ten categories. Mark each one `Clear`, `Partial`, or `Missing` against the
material already in hand.

| Category | What it covers |
| --- | --- |
| Scope and behavior | the outcome, what is explicitly out of scope, who the actors are |
| Domain and data | entities, identity and uniqueness, state transitions, expected volume |
| Interaction flow | the critical path, and the error, empty, and loading states |
| Quality attributes | latency and throughput targets, availability, observability |
| Security and privacy | authentication, authorization, data handling, threat assumptions |
| Integration surface | external services, their failure modes, formats, version assumptions |
| Edge cases | negative paths, limits and throttling, concurrent-change resolution |
| Constraints and tradeoffs | fixed technical choices, and alternatives already rejected |
| Terminology | the canonical term for each concept, and the synonyms to stop using |
| Completion signals | how acceptance is decided, and by what observable |

`Clear` means the material answers it. `Partial` means it is addressed and would
still admit two incompatible builds. `Missing` means nothing addresses it.

The scored map is working state, not output. Report it only when no question
will be asked, where it is the evidence for asking nothing.

## Which gaps earn a question

A `Partial` or `Missing` category is a candidate, not a question. Promote it only
when a different answer would change what gets built, how it is tested, or
whether it is accepted. Drop it when it is a matter of implementation technique,
a choice the executing lane can make and reverse cheaply, or already answered
somewhere in the material.

Rank the survivors by impact times uncertainty and ask in that order. Five
questions is the ceiling for the whole session. Spend them on the worst
unresolved categories rather than clearing several cheap ones - two low-impact
answers and an unresolved security posture is a worse session than one question.

## Question shape

One question per round, and the round advances only on an accepted answer.

- Lead with a complete interrogative that ends in a question mark and stands on
  its own. A topic label, a section heading, or a bare requirement id is not a
  question; a reader who has not seen the spec must be able to answer from the
  question line.
- An id may follow the question mark in parentheses. Never before it.
- Follow with one plain sentence on what the answer changes. A question whose
  stake cannot be stated in one sentence has not earned a round.
- Offer two to five mutually exclusive options, or constrain a short answer to a
  few words. Name which option is recommended and why, in one line, so the
  answerer can accept rather than adjudicate.
- Never show the queue. A visible queue invites answering ahead, which collapses
  several rounds into one unattributable paragraph.

A clarifying exchange within one question is part of that question. It does not
consume another round.

## Write the answer back

An answer that stays in the transcript is lost at the next compaction. Integrate
each accepted answer before asking the next one, into whichever artifact the
session is clarifying.

- Append the exchange to a dedicated clarifications section of that artifact,
  one line per accepted answer, question and answer together.
- Then apply the answer where it belongs: a behavior answer into the requirement
  text, a quality answer as a threshold replacing the adjective it resolves, an
  edge case as its own entry, a terminology answer normalized across every
  mention.
- Replace the statement the answer invalidates. Leaving both makes the artifact
  contradict itself, which is worse than the original ambiguity because it now
  reads as decided.
- Do not reorder or reformat anything the answer did not touch.

If no artifact exists to write into, say so before the first question and name
where the answers will land. An interview with no write-back target produces a
transcript, not a clarified brief.

## Stopping

Stop at the first of: every high-impact category resolved, the person says to
stop, or five questions asked. Then report the outcome and, when the budget ran
out first, list the categories still `Partial` or `Missing` and say what was
assumed for each. A named unresolved assumption is a usable result. A silent one
is the failure this whole pass exists to prevent.
