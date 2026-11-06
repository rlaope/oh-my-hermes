# LLM Feature Eval Harness

Load this reference when the work is the eval suite: the golden set, the hygiene checks that decide whether its numbers mean anything, the validators, and the comparison that decides whether a prompt or model swap ships.

This is a prepared contract. OMH runs no eval and observes no result. A designed comparison is not a comparison that happened.

## The Deliverables

- **golden set**
- **task-level validators**
- **baseline-vs-candidate comparison**

They are artifacts committed beside the code, not activities described in a chat log. "We tested it and it looked better" is the state this workflow exists to replace.

## 1. The Golden Set

A golden set is a small, committed collection of task inputs with their expected outcomes.

- **Seed it from real failures.** The cases worth keeping are the ones that already broke: the invoice with two dates, the question the retriever missed, the input that produced a confidently wrong answer. A golden set written from imagination measures the imagination.
- **Keep it small and adversarial.** Twenty cases that each isolate a distinct failure beat five hundred that all exercise the happy path. The cost of the set is paid on every run.
- **Store it as data.** A JSON/CSV/YAML file under version control, with a stable case ID per row, so a result can name which cases moved.
- **Grow it on every escape.** Any defect found in production becomes a case before it is fixed. This is the only mechanism that keeps the set aimed at what actually breaks.

## 2. Corpus Hygiene

A score from a leaking corpus is not a score. Run these checks on the committed set before any number taken from it is quoted, and report the result beside the number rather than when someone asks:

- **Answer leakage.** No case's input may contain its own expected output, and no fixture, system prompt, few-shot example, or retrieved document the case restores may carry the answer the case exists to elicit. Check it by searching each expected value in that case's own input and in every fixture it restores. A case that leaks measures copying, and it measures it at the top of the score.
- **Duplicates and near-duplicates.** The same input twice weights one behavior twice and moves the aggregate without anyone deciding to. Deduplicate on a normalized input hash, then review the near-duplicates by hand; keep a pair only when the two cases isolate genuinely different failures, and record which failure each one owns.
- **Mutated fixtures.** A fixture edited until the case passes converts a regression into a green run. Fixture bytes are versioned with the case, a fixture change lands in the same commit as the reason for it, and a comparison whose two sides restored different fixture versions is not a comparison.
- **Contaminated holdout.** A case used to tune a prompt, pick a threshold, or choose a model may never also report the result. Split the set before the first tuning pass, record which side every case is on, and quote the held-out number: a tuning-set number is a fit, not a measurement.
- **Case provenance.** Each case records where it came from - a production escape, a hand-written probe, a generated variant - and, for a generated case, which model generated it. A set generated and graded by the same model measures that model's agreement with itself.

Report the corpus state above the score: item count, duplicates removed, leakage hits, fixture version, and the tuning/holdout split. A set that has never been checked is reported as unchecked, and every number taken from it carries that label until it is.

## 3. The Validator Ladder

Prefer the most deterministic validator the task allows, and climb only when the rung below genuinely cannot express the check:

1. **Exact or normalized match** - the output is a field, an ID, a label, a number. Compare it. This is a boolean, not a similarity score.
2. **Schema and constraint checks** - the output parses, every required field is present, values are in range, referenced IDs exist. Cheap, deterministic, and catches the majority of real regressions.
3. **Programmatic property checks** - the citation resolves to a real chunk, the summary contains no entity absent from the source, the SQL parses and runs against a fixture.
4. **Model-graded rubric** - only for genuinely open outputs, and only with a fixed rubric, a pinned grader model ID, and a human-labeled sample confirming the grader agrees with people. A model-graded score with an unpinned grader is a moving ruler.

A task-level verdict is pass or fail per case. Aggregate scores hide which case broke; keep the per-case results.

Grade with code wherever a field decides correctness: the arguments a write tool received, the business state after the run, and the identifiers and order of what was rendered. A rubric is for the semantic remainder. Pin a specific tool call or ordering only when it is part of the contract, such as a grounding read that must precede a write or an authorization check that must precede a side effect; otherwise accept any route that reaches the required outcome without breaking a safety invariant.

## 4. Stateful Fixtures

A case is a message list plus the state that made the decision. A stateless model API does not make the feature stateless, and a transcript alone must never be able to recreate authority.

Each case restores, as committed fixture data with a fixture version:

- the messages;
- the record provenance in scope, meaning which records entered through which authorized read, under which principal and tenant, at which version;
- the identity, tenant, and current permissions of the caller;
- approval records and pending staged changes with their target versions;
- stored user facts, their versions, and the current deletion generation;
- the latest presentation receipt: the final visible ordering, the acknowledged revision, and omitted items.

Restore these together, so no fixture grants a record the transcript mentions but the provenance store does not. Inject busy, long, or contradictory preconditions directly into the state rather than replaying turns to build them up, unless carrying state across turns is itself the behavior under test. A simulated conversation is a way to discover a failure; the committed case is the controlled reduction of it.

For a feature that loaded `references/stateful-contracts.md`, the golden set contains these contract cases:

- **Record access.** An invented ID, an ID copied from another session, an ID the caller saw before a permission was revoked, an ID that has expired from scope, and an ID that only a read-only delegate read. Each exercises a separate check, and no case may grant a write because the record was once visible. The only passing path is the parent's own scoped read followed by a current authorization check.
- **Rendered references.** "The second one" after the host filtered an unauthorized record, after the client re-sorted, and after pagination. The expected answer is the item at that position in the acknowledged final order, with the authoritative fields and required disclosures that were rendered. With the receipt stale or missing, the expected behavior is a refresh or a clarifying question, never a positional guess.
- **Resulting-state limits.** Two sequential requests each under the cap that together exceed it; two concurrent workers targeting the same resource; a staged change applied after the target moved; a staged change applied after the approval expired. Each must end in a conflict or limit result with no partial mutation, and the fixture asserts the final business state, not the tool's reply.
- **Memory lifecycle.** A user assertion that is stored; a tool result, a retrieved document, and a third-party claim the assistant repeated, each rejected; the same fact requested from a different person on a shared account and from a different tenant, each isolated; a correction that supersedes; a deletion that removes the fact from every read path; a retention expiry; and a delayed extractor whose window predates a deletion or a newer correction, which must be fenced rather than applied.

## 5. Paired And Cross-Capability Cases

Every required behavior gets a neighbor where the behavior must be absent: serve beside refuse, act beside ask, load a skill beside skip it, save a fact beside reject one. A suite of only required behaviors rewards a feature that always acts; the pair is what catches it.

Add cases that span two contracts in one request and assert both obligations in one outcome: a positional reference to a rendered item followed by a write against it, a stored preference that changes which record is recommended, a limit check on a record that entered scope through a delegate. Separate suites for records, limits, and memory can each pass while a single request that crosses them fails at the seam.

## 6. The Comparison Record

Run the regression **before** the swap, not after it.

- **Same set, same validators, both sides.** Baseline and candidate run against the identical golden set. A comparison whose two sides ran different cases is not a comparison.
- **Pin both sides.** Record the exact model ID, the prompt version, the tool bundle, and the fixture version for baseline and for candidate. This is the reason both rails exist.
- **Capture tokens and cost per run.** Prompt tokens, completion tokens, and cost belong in the record, because a candidate that is two points better and four times more expensive is a decision, not a win.
- **Cost is per successful task.** When comparing models or effort settings, divide total cost including failed attempts by tasks that passed; a cheaper call that fails more often is not cheaper. Report time to first useful rendered output and full-task latency separately, with tail percentiles beside the median, and report difficult-task failures on their own line instead of averaging them away.
- **Configuration first, then calibrated prompts.** Hold the harness and prompt fixed to isolate a model or effort change; only afterward allow comparable prompt tuning per candidate on separate tuning cases, and report the held-out result with each prompt version. Keeping the two comparisons distinct stops a prompt fitted to one model from settling the selection.
- **Account for run-to-run variance.** A model call is not deterministic. Record the decoding settings on both sides, run each case at least three times (or at temperature 0 where the provider supports it, and say so), and report pass counts per case. A change smaller than the baseline's own run-to-run spread is reported as no difference, and the case count is stated beside every pass rate.
- **Report per-case movement.** Which cases newly pass, which newly fail. A net-positive run that broke a case someone reported last month is not an improvement. A failing case names its class -- validation failure, truncation at the output cap, refusal, timeout -- so a candidate that only truncates more is not read as one that reasons worse.
- **Missing telemetry stays null.** If the harness did not report tokens, latency, or cost, the field is null and the report says the harness did not report it. Never reconstruct a token count from a pricing table or a character count; an estimate presented beside observed numbers reads as observed.

## 7. What A Result Is Not

- A designed comparison is not a result.
- A committed fixture is not a run. Restoring runtime state proves the case is replayable, not that it was replayed. Until the run happened and its output was observed, every number is absent, not zero.
- A passing eval is not implementation, review, CI, or merge evidence.
- A golden-set pass rate is a statement about the golden set. It bounds the claim to the cases in the file, and the honest report says so.

## Anti-Patterns

| Pattern | Why it fails |
| --- | --- |
| Eyeballing a few outputs after a prompt edit | The sample is chosen after the change, by the person who wants it to work. |
| One aggregate quality score | It cannot say which case regressed, so it cannot block a swap. |
| Model-graded everything | An unpinned grader drifts, and a rubric nobody validated against human labels measures the grader. |
| Golden set written up front, never grown | It ossifies around the failures imagined on day one and misses every real one. |
| Comparing a candidate against a remembered baseline | The baseline was a different prompt, a different model, or a different day. Re-run it. |
| Estimating cost from a pricing page | An estimate placed beside observed metrics is read as observed. Leave it null. |
| Fixtures that restore messages only | The transcript recreated authority the provenance store never granted, so the case passes for the wrong reason. |
| Required behaviors with no paired absence | A feature that always acts passes every "should act" case and fails every user it should have asked. |
| Comparing per-call price | Failed attempts are free in that arithmetic; cost per successful task is the number that decides. |
| A case whose input contains its own answer | The score measures copying, and it measures it as the highest-confidence case in the set. |
| Tuning a prompt on the set that reports the result | The number is a fit to the cases that shaped it, so it cannot predict the next input. |
| Editing a fixture until the case goes green | The regression is still there; only the evidence of it was removed. |
