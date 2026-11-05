# Triage

Mode: triage; planning only. Apply authorized: false.
Actor / pain: Vim-mode composer users cannot operate on the complete word under the caret with `diw`, `ciw`, or `yiw`.
Outcome: an auditable, bounded plan for `iw`/`aw` with `d`, `c`, `y`; execution remains unapproved.
CTQs: every normative scenario has an acceptance assertion; zero implementation changes; every implementation task unchecked; strict OpenSpec validation passes.
Scope IN: existing Composer normal parser, object ranges, d/c/y integration, boundary/count/cancellation tests, surgical rollback.
Scope OUT: implementation during this run; f/F/t/T search; repeat search; punctuation-class Vim words; visual mode; dependencies; key constants; application leader changes; commits and PRs.
Profile: design-and-verify. Lanes: [base].
Appetite: one minimal parser/range slice, bounded to composer.py and related existing tests after separate Human apply authorization; no elapsed-time budget invented.
Largest uncertainty: whether users prefer existing motion `.isspace()` semantics or the requested WORD_BREAKS model for new objects.
Falsifier / stop condition: required semantics need a modal rewrite or alter existing motions/leader behavior; reshape instead of expanding this slice.
Evidence gaps: target object behavior is UNPROVEN because this is planning-only; future implementer clears it using acceptance-plan.md before claiming delivery.
Human decisions: planning request approved; proposed exact semantics in specs await acceptance; apply and release unapproved. No prototype exception is represented as implemented behavior.
