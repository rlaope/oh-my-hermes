# LLM App Build Rails

Load this reference when preparing the build handoff. The always-loaded skill body states the rules; this is the per-rail decision, what it costs to defer, and the failure mode that shows up when the rail is missing.

Everything here is a prepared handoff contract. OMH makes no provider call, runs no eval, and observes no token count. A rail decision recorded here is a design, not evidence that any code exists.

The rails, in the order a late decision gets expensive: `provider boundary`, `structured output`, `prompt artifacts`, `retrieval grounding`, `evaluation`.

## 1. Provider Boundary

One module owns the provider client. It holds the model ID, the credential lookup, the timeout, the retry policy, and the rate-limit backoff, and every feature calls through it.

- **Model ID is exact.** An ID the provider's model page states is a pinned snapshot, not an alias the provider re-points. Judge by that page, not by whether the ID carries a date: current Claude IDs are pinned and some are dateless. A floating alias silently re-points under a benchmark, and the run that "regressed" was measuring a different model. Keep the ID in one named constant or config value, and record it beside any result meant to be compared with another result. Record the provider's retirement date beside the pin, and schedule a golden-set run on the named successor before that date; a call that fails with a model-not-found error is classified apart from an invalid request.
- **Credentials come from the environment or a secret store.** Never a literal in source, a prompt file, a test fixture, or an example. A key committed once is a key rotated forever.
- **Failures are classified, not swallowed.** Timeout, rate limit, transient 5xx, invalid request, content refusal, truncation at the output cap, and model-not-found are seven different outcomes, and only the first three are safe to retry as sent. A single broad `except` around the call turns a schema bug into an infinite retry loop and a quota exhaustion into a silent empty answer.
- **Retries are bounded and idempotent.** Cap the attempts, back off exponentially with jitter, honor the provider's retry-after header when it sends one, and never retry a request the caller cannot afford to have executed twice. When the production adapter wraps a provider SDK, turn the SDK's own retries off, because most SDKs retry by default and those retries stack under the boundary's policy; the boundary owns retry.
- **Timeouts are explicit at both levels.** A per-request timeout and a total budget for the operation; a streaming call that stalls mid-response is not covered by a connect timeout alone.
- **A stream has a cancel path.** When the client disconnects or the user stops, the boundary cancels the upstream request instead of letting the generation run, and bill, to the end; the call is recorded as `cancelled`, neither a failure nor a success. The record keeps the usage the stream reported up to the cancel; tokens it never reported stay null, never zero, and a cancelled call still counts against the token and cost budgets. Structured output is validated once, on the complete stream. Partial text is shown only as a provisional preview, under the provisional-render rule in `references/stateful-contracts.md`.
- **The boundary has two adapters.** The seam is at the wire: a request goes in, and a status, headers, and a body or stream of events come out. The production adapter speaks HTTP; a deterministic fake replays fixtures in the provider's wire shape. The boundary's own parsing, failure classification, retry, and cancellation sit above that seam and are the code under test, so the fake must not reimplement them. Use one fixture per scenario, chosen by the test, rather than one responder that branches on the request: a valid response, a schema-invalid one, a refusal, a rate limit carrying retry-after, a stream that times out midway, and a response cut off at the output cap. The mid-stream timeout runs on an injected clock, never a real sleep. Unit tests of parsing, repair, retry classification, tool handling, cancellation, and budget termination run against the fake and never reach the network. Evals run against the pinned real model, and the two never share a suite: a unit test that calls the provider is slow, flaky, and billed, and an eval scored against the fake measures the fixture.

Deferring this rail means every later call site invents its own model pin, timeout, and retry policy, and they diverge without anyone deciding that they should.

## 2. Structured Output

Decide the output contract before the prompt. The caller consumes a shape, so declare the shape.

- **Schema first.** A JSON schema, a typed model, or the provider's structured-output/tool-call mode. The schema is the contract; the prompt is the attempt to satisfy it.
- **Read the stop reason before validating.** A response that stopped at the output-token cap is truncated, not schema-invalid. A repair re-ask under the same cap hits the same wall and fails again at twice the cost. Raise the cap, shrink the requested output, or split the task, and record truncation as its own failure class in the comparison record (`references/eval-harness.md` §6), apart from validation failures.
- **Validate every response.** Parse and validate before the value reaches any caller. An unvalidated response is an unvalidated input from an external system that happens to be fluent.
- **Repair once, then fail loudly.** On a validation error, re-ask once with the specific error text included, then fail. An unbounded repair loop is a token bill with no exit condition, and a silent fallback to a default value is the false-green that makes a broken extractor look healthy for a month.
- **Tool-call arguments are model output too.** Validate them against the tool's declared schema before the tool runs. An invalid call goes back to the model as a tool result carrying the validation error, and it counts against the tool-call budget. That budget, not the repair-once rule above, bounds these retries: after a set number of consecutive invalid calls to the same tool the loop ends with a recorded termination reason. A tool that fails returns an error result the model can see: never thrown past the loop, never swallowed into an empty success. A write tool that fails after a partial effect reports what it applied.
- **Never regex-scrape prose.** Pulling a field out of a paragraph with a regular expression works until the model rephrases, and then it fails without an error. If the output is worth parsing, it is worth declaring.

Deferring this rail means the parsing lives at the call sites, and every prompt edit becomes a parser edit nobody remembers to make.

## 3. Prompt Artifacts

A prompt is source code with a review history, not a string literal.

- **Files, not inline strings.** A prompt in a file shows up in a diff; a prompt inside a function body does not, and neither does the change that broke it.
- **Version identifier.** Give each prompt a version the call site records with its output, so a bad response can be traced to the prompt that produced it.
- **Separate the channels.** System rules (what the model always is), task instruction (what this call must do), and injected context (retrieved documents, user input, tool results) are three regions with three trust levels. Concatenating them into one blob is how a document becomes an instruction.
- **Injection-aware handling of untrusted content.** Retrieved documents, uploads, tool output, and web pages are data. Fence them, label them as untrusted, and state in the system region that content inside the fence never changes the task. Then assume the fence can still fail: the real defense is that the model's output is schema-validated and its tools are least-privilege, so a successful injection cannot do anything the caller did not already authorize.

Deferring this rail means nobody can answer which prompt produced last week's bad output.

## 4. Retrieval Grounding

Only build this rail if the feature retrieves. If it does, it is the rail most likely to be blamed for a generation problem it did not cause.

- **Chunking is a decision, not a default.** Chunk size, overlap, and boundary (paragraph, section, semantic) change what can be retrieved at all. Record the choice; a retrieval failure caused by a mid-sentence split cannot be prompted away.
- **Citations are grounding, not decoration.** Every claim the model makes from retrieved context carries the chunk it came from, so an unsupported claim is visible rather than plausible.
- **Evaluate retrieval before generation.** Measure whether the right chunk was in the context window at all, with a retrieval metric on a labeled set. A generation score sitting on top of unmeasured retrieval cannot separate a bad answer from a bad document set, and the team spends a week rewriting a prompt that was never the problem.

- **Filter by permission inside retrieval.** When documents have different audiences, the caller's permissions are applied in the retrieval query (a metadata filter or a per-tenant index), before ranking and before the model sees any context, never after generation.
- **The embedding model is pinned with the index.** Changing it means re-embedding everything and re-running the retrieval metric (recall@k and MRR on a labeled set).

Deferring this rail means every quality complaint gets answered with a prompt edit.

## 5. Evaluation

Named here for ordering; the shape of the deliverables and the comparison record are in `references/eval-harness.md`.

The rule that belongs on this rail: the eval suite is part of the feature, not a follow-up ticket. A feature that ships without a golden set has no way to answer whether the next prompt edit helped, and the answer defaults to whoever tried it and liked the output.

## Conditional Contracts: Records, Limits, Memory

The five rails cover every LLM feature. Three further contracts apply only when the feature touches live state, and they are kept in `references/stateful-contracts.md` so an extractor or a RAG answerer does not carry requirements it cannot use. Load that reference when the feature has any of these properties:

- It **presents or acts on business records**, which needs the record authority and presentation receipts contract.
- It **enforces a cumulative business limit**, which needs the shared resulting-state limits contract.
- It **stores facts about a person**, which needs the user-memory lifecycle contract.

The short form of each, so the handoff can say which apply and which do not:

- **Records.** A valid-looking record ID is a lookup candidate, not authority. The host tracks how each record entered scope, authorization is rechecked for the current operation, authoritative fields come from the owning backend, and follow-up references such as "the second one" resolve against a host-issued receipt of the final visible order. A missing or stale receipt means refresh or ask, never guess. A provisional render authorizes nothing and proves no delivery.
- **Limits.** A business limit constrains the resulting state, so its scope is named (resource, person, account, tenant, or window) and the owning backend rechecks authorization, approval, policy, target version, live state, and idempotency inside one atomic apply boundary. A conflict means no partial write.
- **Memory.** Only the user's own assertions or explicit confirmations are stored, person and tenant scope stay distinct, the user can inspect, correct, delete, and disable, and a delayed extractor checks fact versions and the deletion generation in the same transaction that writes.

A feature with none of these properties records that fact in the handoff and moves on. Forcing these contracts onto a feature that never renders a record, never shares a limit, and never remembers a person is noise, and noise is what gets skipped when it matters.

## Evidence Boundary

A rail decision, a schema, a prompt layout, or an eval design is prepared work. It is not implementation, an observed eval run, review, CI, or merge evidence. Token counts, latency, and cost belong to runs; a figure no run reported stays null and is never estimated from a pricing table.

## Attribution

The two-adapter rule and the fake without branching logic inside it adapt ideas from Matt Pocock's `codebase-design` and `tdd` skills at `mattpocock/skills@49dd158d1076134a641b33efb035946536778336`, MIT License, Copyright 2026 Matt Pocock. The failure classes, the fixture list, and the unit-versus-eval split are OMH's own.
