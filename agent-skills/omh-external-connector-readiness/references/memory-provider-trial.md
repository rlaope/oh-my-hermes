# Trialling Memory Providers on Your Own Corpus

A provider's declared posture says what it promises; a trial says what it did
with your material. This is the `connector_trial_manifest/v1` pattern applied
to a memory provider - a provider is a connector with a declared posture, and
the trial records what was observed against it.

## The trial is one corpus and one query set

Every candidate gets the same documents and the same queries. A provider
evaluated on its own sample is evaluated on the sample it was chosen for, which
is the one comparison that cannot be wrong. Freeze both before the first
candidate runs, and record their identity - a digest, a document count, a query
count - never their content. Extending the corpus mid-trial invalidates every
result already collected; start over rather than compare across two corpora.

## Three dimensions, each separately reportable

| Dimension | What the host reports | What it is not |
| --- | --- | --- |
| Retrieval quality | per query: which expected items came back, at what rank | a model's opinion of the answer |
| Latency | per query: the provider's own round trip, and whether it was measured warm or cold | end-to-end chat latency |
| Cost | per trial: the provider's billed or quoted units for the run | an extrapolated monthly figure |

A dimension nobody measured is `not_observed`. It is never `0`, never a
default, and never inferred from another dimension: a provider with no cost
figure is not free, and one with no quality figure has not scored zero. A
comparison table where one cell is `not_observed` and another is a number is
still useful; one where the gap was filled with a plausible value is not.

OMH makes no network calls, so every figure here arrives from the host,
connector, or operator that ran the queries. Record the reporter alongside the
figure.

## Migration is not finished until the rollback has run

Choosing a provider is reversible only if the reverse has been done. In the
trial, before any production data moves:

1. Export from the current provider and record what the export contained -
   counts and identifiers, not content.
2. Import into the candidate and record what arrived; a count that does not
   match the export is the finding, not a rounding difference.
3. **Run the rollback.** Point back at the original provider, re-run the query
   set, and record whether the original results returned.
4. Record what the rollback did *not* restore. Writes made against the
   candidate during the trial, derived indexes, and anything the candidate
   generated are the usual answers.

A rollback that was described but not executed is `prepared_not_observed`. Say
so in those words rather than calling the migration reversible.

## What the record holds

Provider identity, corpus and query-set identity, per-provider figures with
their reporters, the unmeasured dimensions marked `not_observed`, the migration
counts, and the rollback observation. Corpus content, query text, and retrieved
documents stay out: the record is metadata about the trial, and a memory corpus
is exactly the material that should not be copied into a readiness card.

## Boundary

A trial comparison is prepared adoption evidence. It is not provider
installation, credential validation, a completed migration, a production
cutover, or proof that the chosen provider behaves the same way on material the
trial did not include.
