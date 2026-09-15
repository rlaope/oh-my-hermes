# Changelog

All notable changes will be documented here.

## Unreleased

- **The plugin risk audit says what a declared hook would actually do.**
  `omh ops plugin-risk-audit` reported one aggregate `hermes_hook_capability`
  category decided by a regex holding three hook names, so a policy gate that
  can block a tool and a best-effort observer read identically, and a plugin
  declaring only `post_tool_call` was reported with no hook capability at all.
  The audit now reads a root `plugin.yaml` as structured data and classifies
  every hook it declares against one pinned Hermes contract revision: what the
  host does with the return (policy gate, prompt/context contributor, result
  transformer, lifecycle callback, observer), where the callback runs (bounded,
  caller thread, queued worker), and what a timeout does (fail closed, fail
  open, not applicable). `pre_tool_call` is the only hook whose timeout blocks
  the action; a `pre_verify` gate is bounded and fail-open, so a hung gate lets
  the turn finish -- the distinction the aggregate hid. Nothing is imported,
  registered, installed or executed, so hook registration, execution, timeout
  enforcement and failure handling are each reported `not_observed`, and a
  declaration is never evidence that a hook ran. A manifest the audit could not
  understand -- unreadable, malformed, outside the reader's bounded subset,
  requiring an unsupported host revision, naming a hook the contract does not
  contain, or absent entirely -- reports `undetermined_hook_contract` in the
  summary rather than a clean result. The mapping is a hand-transcribed snapshot
  of Hermes 0.21.1 and cannot detect upstream drift;
  `docs/PLUGIN-HOOK-CONTRACT.md` says so, and says what to do when a hook
  classifies `unknown`.
- **Loop is a native tool, and the CLI now speaks through the same
  service.** `omh_loop` registers one session-bound plugin tool over eight
  workflow-critical lifecycle actions -- `assess`, `start`, `status`,
  `feedback`, `permit`, `run_once`, `goal_driver_observe`, `queue_observe` --
  so Hermes manages one durable `loop_cycle/v2` without assembling shell
  arguments or parsing command output. Every action runs through a new typed
  operation service (`omh.workflows.loop_operations`) whose manifest is the
  only place the Loop action vocabulary exists, and all twenty-two `omh loop`
  subcommands are now adapters over that same service, keeping their flags,
  exit codes, and JSON keys. Tool mutations bind to the configured OMH home
  and the host session id, refuse a caller-named store, and refuse an
  existing-loop write that does not submit the `record_revision` a read
  reported; failures return a stable code from one closed vocabulary. Every
  result carries prepared-versus-observed state: a successful call records an
  OMH transition and never implies dispatch, implementation, review, CI,
  merge readiness, or merge. Operator surfaces (tick, sticky rules, queue
  dispatch and recovery, driver binding and migration, handoffs, narration)
  stay on the CLI, and the Loop skill now names the tool first and the CLI as
  the fallback. Existing installs need `omh update` before the tool appears.
- **Every provider surface says which providers count.** With linked
  providers reordering chains on their own, the surfaces that describe
  providers now tell that truth. `omh doctor` gains a `provider_entitlements`
  check, grouped with `hermes_model_routing` under a new `model_routing`
  group: it names every provider counted with where it was found, the
  `providers.json` and `model-providers.json` statuses, the ids the record
  excludes, and warns (without flipping the exit code) when `providers.json`
  is invalid — its recorded kinds are dropped and any providers it excluded
  count again — or when a route names a provider neither recorded nor
  linked: an alias a chain names sorts behind the served entries of every
  chain naming it, while a dispatch-only route reorders nothing but sends a
  dispatch that pins it to a provider Hermes is not linked to.
  `omh model-chains show` prints the same ignored-record consequence, the
  routes document status when it is invalid, and both kinds of unknown-
  provider route (`routes_path`, `routes_status`, `unserved_routes` in the
  JSON, schema unchanged). Non-interactive `omh setup` (`--yes`,
  `--json`, a non-TTY) reports the counted providers and the record's status
  as an additive `providers` field and a printed line. The CLI picker and
  `/omh-model` show one row when `providers.json` is invalid. The interview
  copy in all four languages no longer claims that skipping keeps the
  built-in order, and two docs pages say "recorded or linked" where they
  framed the record as the only route.
- **A document plan fans out one unit per range.** `omh coding fanout
  prepare --from-document-plan <plan.json>` derives a fanout unit from every
  range of a `document_chunk_plan/v1` file: the unit's title is the plan's
  per-range brief, its file scope is that range's report file, and its new
  optional `input_budget` carries the plan's per-range character budget, a
  token estimate, and the range's `read_file` window as a source range. The
  budget is validated at freeze (bounded, typed, tokens consistent with
  chars, source estimates within the ceiling), rides the frozen unit only
  when declared, and the executor prompt states the ceiling and the ranges
  after the unit's boundary lines. A plan without ranges is refused with
  exit 2 and nothing is frozen; dispatch itself is unchanged and still
  opt-in.
- **Long documents get a chunk plan before they are read.** A new
  `omh_document_plan` plugin tool splits a document larger than one
  `read_file` window into numbered ranges from the numbers Hermes states
  after its first read (page count, `total_lines`, extracted length, an
  outline of section anchors): each range carries a page or character span,
  the sections it covers, an estimated character and token size, the
  `read_file` offset/limit window that reaches it, and a digest, and the
  plan is written to `$OMH_HOME/documents/<plan_id>/plan.json` with a
  covered / next / missing ledger that `mark` advances and `show` re-reads
  after conversation compression. Ranges snap to the outline and to the
  100k-character budget Hermes reads per call, and a plan of more than four
  ranges carries a `delegate_task` brief per range so the reading can fan
  out one child per range. OMH never opens the document: a local file
  contributes only its size and sha256, every count is labelled
  `caller_supplied`, and a covered mark is the caller's statement, not
  observed coverage. The paper-learning skill points to the tool when the
  paper exceeds one window.
- **Paper reading progress survives the session.** The `paper-learning` skill
  promised a `paper_learning_card/v1` under `.omh/paper-learning` "when a
  wrapper or CLI records it", and no command wrote there, so a long paper
  restarted from the abstract every session. `omh paper` is that command:
  `plan` records the card (a local source file is hashed for identity, never
  parsed), `progress <paper_id>` records one explained chunk as covered /
  next / missing plus a short note, `list` and `show` print where reading
  stopped so a resumed session continues from the recorded next section, and
  `validate` checks every card, ledger, and the index cache. The store is
  `$OMH_HOME/paper-learning/<paper_id>/card.json` plus an append-only
  `ledger.jsonl`; page counts, PDF extraction, and explanation correctness
  stay not observed until a host records them.
- **An unresolved memory decays to open, not to a verdict.** A record whose
  outcome is undecided used to be delivered like a settled fact until its
  review deadline, then go `stale` and leave recall — read as decided, then
  forgotten. `omh memory capture --unresolved` / `omh memory approve <id>
  --unresolved` now set `staleness.resolution: open`. Past its review
  deadline an open record is delivered as `open · N days unresolved`
  (pack items carry `resolution` and `resolution_marker`, each pack one
  `unresolved_delivered` count, the provider's record line the same marker)
  instead of being held back; expiry, a changed source, and an unreadable
  source still outrank it, and a non-open record keeps today's verdict byte
  for byte. Only `confirm` or `correct` writes `resolved`, `retire` ends it,
  and nothing else clears it — no timeout, no reminder, no batch confirm. An
  open record always carries a review deadline (durable records and episodes
  included), and `confirm` resolves an open record even when it has none.
  `open_max_days` (default 365, policy tunable) bounds every non-durable open
  record as `expired/unresolved_expired`, and `omh memory retire` names that
  reason so a question that died unanswered reads differently from a fact
  that aged out. The provider asks: one `omh reminder: "<summary>" (<id>)
  has been unresolved for N days — resolved, still open, or drop it?` line
  per pack once the deadline passes, then at most every `open_ask_days`
  (default 14); `omh memory keep-open <id>` is the "still open" answer that
  resets the clock and touches nothing else, `omh memory retire <id>` the
  "drop it" answer. The ask is recorded only when the pack is actually
  served and disclosed in the prefetch receipt (`reminder`) and
  `latest_open_reminder()`. `omh memory status` gains `counts.unresolved`
  and a bounded oldest-first `open_records` list; `omh doctor` warns about
  open records older than half the ceiling. Issue #1528.
- **DeepSeek V4.1 Flash override measured and revised.** On the first day a
  served route existed (`og` added `deepseek/deepseek-flash`), the
  `deepseek-v4.1-flash` high-effort override ran the #1463 five-arm pair on
  `benchmarks/live-model-tools/v1`: pass rate tied within noise, but the
  original wording cost 25% more tokens than the inherited `deepseek` block
  (+21,663 per instance, CI95 [+6,550, +42,944]), re-running checks on tasks
  the model was not going to pass. The two phrases that asked the reply to
  carry "the verification output" and the blocker report "the observed
  output" are gone and the family block's "verify once, and stop" is back;
  the revised block measures at the family block's cost with the fewest tool
  calls and API turns of any arm. Numbers in `MODEL_OPTI.md` and the
  benchmark README; records archived outside git. Closes #1463.
- **The bundled plugin declares its Hermes runtime range.** OMH admits
  Hermes `>=0.21.1,<0.22.0` before plugin registration and rejects unsupported
  hosts with the required and running versions. Missing or invalid declarations
  fail local conformance; release readiness also checks the tested-host matrix.
  Existing installs should run `omh update` to refresh the managed bundle.
- **A very large PDF is read in page ranges, not truncated.** The new
  `long-document-reading` skill owns "summarize this 300-page contract",
  "read this manual", and the bare "summarize this document" (which used to
  land in file packaging): it probes the page count and scanned flags with
  Hermes' built-in `pdf` scripts, plans page ranges sized to the `read_file`
  budget (about 60 pages per 100,000-character call), extracts each range
  with page selection so every claim keeps a page anchor, delegates ranges
  to `delegate_task` children above four, and closes each range with
  covered / next / missing so a compacted or resumed session continues from
  the ledger. `long_document_card/v1` is the metadata contract; page count,
  extraction, scanned-page OCR, and delegation stay unobserved until a tool
  result records them. Papers stay with `paper-learning`, produced files
  with `materials-package`. `docs/LONG-DOCUMENT-READING.md` answers "how do I
  process a very large PDF with Hermes?" in terms of Hermes' measured limits.
- **A document handed to a coding owner is gated like an image.** A PDF or
  office file now reaches the coding-lane media handoff as a declared
  `raw_media:document` (or `local_file_reference:document`) input: files
  attached to an `--event-json` message are declared from their name and
  media type (Discord `attachments`, Slack `files`, Telegram
  `message.document`; bytes, URLs, and names never enter the payload),
  `omh coding delegate --input-representation` declares one explicitly, and
  `omh chat interact` derives the same declaration from its event. The
  decision matches `input_modality_document` route evidence exactly the way
  `input_modality_image` is matched — fresh, `host_observed`, same provider,
  wire model, and endpoint mode — and image evidence never stands in for it.
  Every fail-closed verdict now carries a modality-specific
  `remaining_user_action` and an `alternative_representations` list: for a
  document, `extracted_text` (text Hermes already read out of the file, for
  example with `read_file`) or `ocr_output` with an observed OCR
  transformation; for an image, `ocr_output`; for audio or video,
  `transcript`. Fanout dispatch refusals state that action beside the reason.
  `--transformation-json` supplies the observed-transformation record an
  `ocr_output` or `transcript` handoff needs. The demo decision set gains the
  document path, and the action names no coding owner. Three gaps found in
  review are closed in the same change: the route the evidence is scoped to
  is now real (`omh coding delegate` binds the same resolved Hermes model
  recommendation the chat lane binds, and a recommendation that names no
  endpoint mode binds `default` instead of no route at all), a handoff with
  no resolved provider and wire model reports `route_unresolved` rather than
  asking for evidence of an empty route, a fanout unit any capability gate
  refuses carries `failure_kind: capability_gate` so a batch refused
  entirely exits non-zero (with a `record_capability_evidence_then_redispatch`
  row in the cause-specific recovery table), and every attachment on a
  message is classified, so a PDF listed after any number of text files is
  still declared.
- **Providers linked to Hermes are recognized on their own.** OMH now reads
  which providers Hermes is already linked to — a `hermes auth` login in
  `auth.json` (the pool rows Hermes itself counts, never a credential
  borrowed from another CLI), a `providers:` entry or `model.provider` in
  `config.yaml` (a loopback endpoint left out), an API-key variable name in
  `$HERMES_HOME/.env` — and counts them the way a recorded `providers.json`
  answer counts: chains reorder so served entries lead, `omh model-chains
  show`, the CLI picker, and `/omh-model` list the providers counted with
  where each was found, and `omh_delegate_route` refuses the same
  known-wrong pins. Only ids and variable names are read, never a key or a
  token, and nothing is invoked. The `omh setup` interview offers the same
  rows pre-ticked (a login row says so), its recorded kinds win for an id
  both name, and a linked row you untick is written as `excluded_providers`
  and stops counting; the record is no longer the only way a machine's
  providers reach routing.
- **Model chains get a picker.** Bare `omh model-chains` (alias `omh model`)
  on a terminal opens an arrow-key editor: one row per mixture category with
  its head model, effort bar, origin and whether this machine's providers
  serve it; left/right step the head model through the aliases chains name
  today, `-`/`+` step its effort, `d` restores the shipped default, Enter
  writes through the same validated document `omh model-chains set` writes
  and `q` writes nothing. Off a terminal the bare form prints `show`. The
  chain rules live in the plugin bundle so the Modern-TUI widget can walk the
  same rows.
- **`/omh-model` in the Modern TUI.** The OMH widget registers the same
  picker as a modal app: `/omh-model` opens it over the transcript with the
  keys the CLI picker uses, reads and saves through the installed plugin
  bundle, and shows the written path on save. Hermes' own `/model` keeps its
  name and its job (the session model); the two edit different things. A host
  whose widget SDK lacks the overlay primitives keeps the docks and the CLI
  picker.
- **The HUD says when another model answered.** A delegation child's row now
  carries a `model_attestation` verdict comparing the model the run was routed
  to against the model Hermes recorded as having answered it
  (`session_model_usage.model`, written per call). Nothing compared the two
  before: the row reader preferred the recorded route and never read the
  answering model, which hid a substitution in exactly the case one happened.
  Both sides resolve through the alias table the mixture-category label
  already uses, so a vendor pointer answered by its exact contract id, a base
  answered by a dated snapshot of itself, or two speed tiers of one model read
  as agreement rather than a false alarm — and a newly declared pointer alias
  moves the verdict with no second table to update. `unknown` is a first-class
  verdict: a child that switched models mid-run, one with no usage row, and
  one nothing recorded a request for each say so with the reason, never a
  silent agreement. The payload states the limit it covers — delegation
  children only, since a main session is named by `sessions.model` alone with
  no per-call answering model to attest against.
- **Rehearse an unattended batch against your rules before it starts.**
  `omh ops permission-rehearse --plan <file>` runs the `(tool, args)` pairs a
  cron entry or unattended run intends to issue through the same matcher the
  enforcing `pre_tool_call` hook uses, and returns a per-call table: `refused`
  names the rule that would block the call, and everything else is `unknown`
  with the reason. The third tier is deliberately not claimed — "needs
  approval" lives in Hermes' per-tool approval declarations, which OMH has no
  reader for — so the summary counts `planned`, `refused`, and `unknown` and
  has no allowed bucket an unknown could be folded into. The payload carries
  the observed approval-bypass state alongside, because a rehearsal run under
  an active bypass describes a policy nobody is currently applying, and it
  reports when the rules file is present but defective, because "nothing
  refused" from a policy the hook never loaded is not a green light. The
  rehearsal executes nothing and writes nothing; exit `1` means a planned call
  is refused, `3` that the rules file is defective, and `0` only that no rule
  refuses these calls — never that they are allowed.
- **A configured profile can move to another machine.** `omh setup-profile
  export` serializes this install's `setup_profile/v1` -- coding owner,
  operating model, memory mode, selected categories -- plus the capability
  policy, the recorded MCP host recipe and the Hermes model aliases into one
  local JSON pack with a content-addressed manifest, and `omh setup-profile
  apply --from <pack.json> --apply` writes it back through `omh setup`'s own
  writers. Redaction reuses the `RAW_OR_HIDDEN_KEYS` and `metadata_safety`
  primitives every record store already screens against: a credential-shaped
  value or a machine-local path never enters the artifact, and every field
  withheld is named with its reason rather than dropped in silence. Apply is
  a dry run until `--apply`, reports each field as applied or not applied
  with the reason, refuses a pack from a newer OMH whole rather than writing
  a partial profile, and hands back the exact `omh setup` commands for the
  two surfaces it will not write unasked -- Hermes model aliases, which need
  their own digest-bound confirmation, and the MCP host config, which is
  written only under `--with-mcp`. Transport stays out: export writes a local
  file, apply reads a local file, and moving one between machines is your own
  git or file copy.

## 2.0.3 - 2026-09-12

Everything merged since the 2.0.2 tag (2026-09-07). Highlights, grouped:

- **A dispatched unit that stops working now says so.** A session limit read as
  `crash`, a batch whose every unit failed exited 0, a worker alive for 36
  minutes retrying one git workaround read as progress, and a plan with open
  items sat unchanged while each turn ended on a status report. That whole
  chain is closed. Provider refusals classify as limit-shaped, and any unit
  carrying a `failure_kind` makes the command exit non-zero (a derived gate
  fails any future exit-code mapper that maps failed work to 0). A unit's
  execution state is named apart from its process: `running` requires new
  evidence, and a live process without it is `progress_stalled`, beside
  `awaiting_input`, `permission_blocked`, `account_limit`, `data_missing`,
  `failed`, and `verified` — the only success state, which requires a validated
  result record. Progress is read from the unit's own output, including the
  same failure line repeating while bytes still grow. The status board, the
  plugin reader, the TUI widget, and `omh coding fanout status --json` all
  report that state with its reason and how long output has been still, and the
  roster answers the supervisor's own question with `all_units_terminal` and
  `stuck_units`.
- **A unit is refused before the spawn when its workspace cannot take the
  work.** File write, git index write, the objects the work needs actually
  present (including a partial clone whose promisor fetch is forbidden), and
  case-only filename collisions on a case-insensitive filesystem, all probed in
  the unit's own isolation with no network call. A failing check ends the unit
  as `workspace_blocked` before any CLI starts. Executor readiness stops
  claiming more than it saw: a passing `--version` is `binary_version_only`.
- **Recovery matches the cause.** A permission denial re-probes the workspace,
  a limit checks the account and its reset before any retry, missing objects
  are supplemented and verified before one unit resumes, and a stall is only
  re-run with changed conditions or from a checkpoint. A live in-flight marker
  on a scope outranks every cause: no second worker is added to work already
  running. The account a CLI is configured with is recorded as a redacted
  one-way tag so a limit can be told apart from the account that hit it.
- **The plan drives the work.** Open items mean the plan is not finished: the
  per-turn reminder says to advance the next item rather than end on a status
  report, and it stops when every item is done or one is recorded blocked with
  its reason. A plan that stops moving is a finding even while tool calls keep
  running. A finished dispatch arrives as an event with the verb it owes —
  verify, record, then recover or advance — and a continuation announced with
  nothing started is reported back.
- **Fixed: a grown `--help` page silently disabled the structured-session
  lane.** The help probe was capped at 16 KiB; `claude --help` reached 21,401
  bytes with `--verbose` past the cut, so the negotiation refused a protocol
  the CLI does support, the spawn omitted `--output-format stream-json`, and
  every Claude unit ran with no token counts and no session id to steer with —
  visible only as an empty column. The help probe now gets a document-sized
  budget, a truncated read still answers the question when every flag was found
  in what was read, and a refusal states its reason.
- **Setup and routing.** Provider entitlements are asked as one plain ticked
  list with detected providers pre-ticked; the native-lane chain interview is
  offered during setup; `capable`, `simple-work`, and `deep-work` join the model
  categories. DeepSeek V4.1 Flash onboarded with superseded generations retired
  from the shipped chains, and a vendor's dated snapshot id is recognized as the
  base alias it is a snapshot of.
- **Memory and HUD.** Past-session history routes to the session store rather
  than a record; reviewed records and consolidation briefs reach the Hermes turn
  with the host saying so; store containment is decided lexically instead of by
  two resolves. A lane routed to the parent's own model keeps its category and
  says `=parent`; a gateway child the host could not price is approximated with
  its provenance.
- **Install and update.** An `omh update` survives a symlinked plugin
  directory; a Hermes profile registered at any OMH-managed skills path counts
  as registered and opting out removes every one; the pre-pointer skills home is
  a managed registration on managed installs too.
- **Windows fixes found through "flaky" tests.** A sharing-denial retry for the
  store write that silently dropped a record, and containment decided without a
  resolve race. Both Windows shards now run to completion, and a process-global
  interrupt flag is restored after every test that sets it, which was showing up
  as a CI-only failure in whichever test ran next.
- **Docs and gates.** Public documentation structure is gated by an offline
  navigation check, the shipped chain table in `docs/INSTALLATION.md` is
  generated and gated, and the two traps that cost a day of diagnosis (the stale
  editable install, and concluding a platform fact settles a call site) are
  written into `CLAUDE.md`.

Entries recorded during the cycle, in full:

- Added bounded GPT-6 Astra mode/service-tier contract inheritance and a deterministic `model_contract_coverage/v1` audit CLI for local model inventories, preserving exact-versus-declared provenance without treating catalog rows as provider availability or execution evidence.
- Added a read-only shape view for one selected work artifact. The common facade supports registered handoff, plan, status, and review source schemas; the persisted wrapper path projects prompt/runtime handoffs plus every recorded `coding_briefing/v1` artifact through `omh runtime artifacts show-shape --artifact-id <id> --lens flow --json`, retaining the exact source schema rather than relabeling it. The lens vocabulary is `flow`, `structure`, `change`, `state`, and `ownership`, with each source family exposing only the lenses its fields can support, and every node and edge carries the source refs it was projected from. `ascii` is the default format, `tree` and `diff` are the other text formats (`diff` requires the `change` lens), and `mermaid` stays unavailable until a Mermaid capability is observed rather than inferred from a flag. An unknown artifact id, an unrecorded source, an unsupported lens or schema, unsafe content, or an exhausted render budget all come back as an explicit `unavailable` result with a named reason and an empty body. People keep asking Hermes about the work in plain language; the projection is a wrapper-facing selected action, and the command above is the observed operator/agent path into it. Showing a shape never advances the session, and it is not dispatch, execution, verification, review, CI, merge-readiness, or merge evidence.
- Added `omh coding paired-run dispatch --decision <paired_run_decision/v1>` as an explicit operator/maintainer boundary for an already-committed paired-run decision. `--dry-run` prints the inert plan and launches nothing. Without `--dry-run`, dispatch refuses unless `--confirm-dispatch` is typed. A confirmed Hermes matrix requires one digest-matching `--task-file` per frozen task, an exact repository revision, and a provider; it reuses the sanctioned Hermes-child bridge, passes task bytes over stdin, runs independent cells with a derived concurrency ceiling of two in detached worktrees under an atomically unique invocation-owned parent, verifies the signed evaluation binding, removes only paths reserved by that invocation, and persists no task body. The paired path opts into that bounded scheduler while the child bridge remains single-dispatch by default for every other caller. A timed-out Git worktree command becomes one `crashed` cell with explicit partial-cleanup evidence rather than aborting the matrix. Executors without a receipt-capable adapter are refused without substitution, while caller-injected adapters remain the executor-neutral extension seam. The plan carries the isolation mode, shared-resource keys, launch waves, and the global/per-executor/per-provider concurrency and cost/time budgets derived from the frozen decision, never from CLI overrides. Execution evidence closes back into a decision only through an authenticated receipt fan-in: a missing, stale, mismatched, unauthenticated, partial, timed-out, cancelled, crashed, or rate-limited cell blocks the decision instead of degrading it, and behavior verdicts stay explicit request values rather than being read off exit codes or process output. Confirmed cells also write bounded metadata-only queue/start/finish and cleanup events, so `omh runtime health-summary --run-id <decision-id>` projects evaluation critical-path health directly.
- Added an optional post-GREEN diagnostic pass to fanout dispatch behind `--diagnostics` (`--no-diagnostics` is the default). The explicit operator path now discovers only the closed local `pyright`, `basedpyright`, and `ruff` command set from `PATH`; caller-injected engines remain the executor-neutral extension seam. Providers run over detached baseline/end revision worktrees with fixed argv templates, bounded global/per-provider concurrency, serialized stateful providers, process-group timeout/cancellation, an allowlisted environment, hard-capped output, and mandatory cleanup. The complete owned provider process group/tree is terminated and reaped after every leader exit, including exit zero, and unproved cleanup cannot become clean evidence. Windows providers start suspended, enter a kill-on-close Job Object before executing, and require zero active job processes before clean evidence. Only normalized severity/code/relative-position metadata reaches compatible `language_diagnostic_evidence/v1` records; messages, source, absolute paths, stderr, and raw provider payloads are discarded. Diagnostics still run only after producer verification GREEN at fixed revisions, and a missing provider, process failure, dirty/moved checkout, or non-clean outcome becomes `held` without changing the unit's verification ladder.
- Added `--health-events` to fanout dispatch (off unless typed) and a matching read path, `omh runtime health-summary --run-id <fanout-id>`. Enabled dispatch appends bounded metadata-only lifecycle events to the run's own `critical_path_health_events.jsonl`; the health summary reads it through fixed byte/line/record ceilings and projects it into a committed `critical_path_health/v1` section, upgrading the record to `run_health_summary/v2`. Same-millisecond zero-duration spans remain valid. Without that journal, the projector falls back to existing observation-journal evidence, and a lifecycle it cannot reconcile (a dependency cycle, an out-of-order dependency, or an over-limit journal) reports explicit evidence gaps with null metrics instead of a plausible number. `--input` still reads a `run_health_input/v1` or `/v2` file.
- Added immutable concurrent final-review lanes for integrated fanout work. The four lenses use the fixed reporting order `requirement`, `quality`, `safety`, `real_surface`, execute concurrently within the configured limits, and bind read-only to one 40-hex integrated revision. The explicit `omh coding fanout dispatch --final-review` path reuses the sanctioned Hermes-child boundary after integration GREEN, requires the clean integrated worktree/revision and named provider/model, and parses only an exact closed verdict token; caller-injected engines remain the extension seam. Every built-in lane runs in its own detached fixed-revision checkout with filesystem writes denied, rechecks that disposable tree before accepting the verdict, and removes it in `finally`, so a bypassed write is contained and blocks without touching the integrated checkout. The fanout hook also proves the integrated tree is clean and unchanged before/after execution and requires one matching observed execution ref per lane, so a silent complete-looking engine result cannot become `PASS`. The wave reduces to a deterministic `PASS`, `HOLD`, or `BLOCK`: `HOLD` when integration is not green or producer evidence is missing, `BLOCK` when a revision is not immutable or a lane drifted off the bound revision, mutated, lacked an execution observation, or went missing, and `PASS` only when every lane completed at that exact revision. A review verdict remains review evidence only, never merge evidence.
- Put the offline live-model benchmark framework in every static CI shard lane. Its upstream cases live outside `tests/`, so statically declared delegators expose each one to the sharding inventory, with an AST parity check that fails loudly when an upstream case is added, removed, or renamed. The delegated cases run the real upstream implementation with no paid-live authorization. Each test id is assigned exactly once to a shard or quarantine by the shared plan, then that assignment is executed by each applicable Linux or Windows version lane and reconciled by `aggregate`.

## 2.0.2 - 2026-09-07

Everything merged since the 2.0.1 tag (2026-09-05).

- **Fix: `omh update` rolled back at `post_activation` on installer-managed machines.** The staged transaction rendered the candidate workflow pack into its own generation, then re-entered the update against the real home, whose manifest still recorded the active generation's pack; every skill the catalog had changed since the last install was judged a "local modification", the re-entry refused without `--force`, and the whole update rolled back with only the phase name printed. The installer now applies its local-modification and orphan-prune guards only to the directory the manifest actually records, the summary line names the failing phase's reason and the rollback target, and the re-entered update's stderr is captured for that reason and replayed. A transaction-level regression test drives the real CLI through the smoke and re-entry against an older-manifest home, and a companion test proves the guard is what prevents the refusal. (#1377)
- **Release and update.** A release cut ends with the owner machine synced, and a bare `omh` announces its Auto Update; `omh --version` and `omh doctor` expose a verifiable build identity; the cut stages the site badge it rewrites.
- **Coding and fanout.** Fanout dispatch runs under an OS write fence proven per run, with the confined owner CLI still able to write its own state; workspace targets are declared by path shape, glued and encoded spellings of a target token are declared, and decoding runs to a fixpoint before a containment slot is charged; long-running waits bind to the host's completion signal; `cancelled` is a first-class observed terminal state; an explicit user merge directive survives the delegation boundary; delegation continuity is recorded as a goal-ledger obligation.
- **Routing and models.** Claude Mythos 5.1 leaves the shipped recommendation chains; the Codex Maestro defaults name the GPT generation the CLI serves; the Astra round's measured lessons join the onboarding loop.
- **Install and memory.** The PowerShell installer reads the redirect Location header through a capability probe, proven on both PowerShell versions; memory credential boundaries are hardened.
- **Skills and docs.** llm-app-dev treats public-board communication as public disclosure; Apple visual production and 3D examples; README showcase, demo grid, and a Quick Start that takes the same shape in every language.

## 2.0.1 - 2026-09-05

Everything merged since the 2.0.0 tag (2026-08-29). Highlights, grouped:

- **Models.** Onboarded GPT-6 Astra with an exact-model contract (documented effort ladder with a `low` floor, Responses-only tool calling, list pricing), exact-model calibration overrides resolved before the family block, and both-lane routing with GPT-5.6 Sol as fall-through; measured the Astra override against the block it replaced on the live benchmark and revised its wording on the number. Onboarded Claude Fable 5.1 / Mythos 5.1 with 5.1-aware calibration, the GLM 5.3 generation with chains and speed-tier projection, and MiniMax family recognition. Token prices moved into a config document with a cited source per rate.
- **Routing.** A deterministic request-complexity scorer feeds a model-class recommendation; an exhaustive-search signal lifts "find every reference / all usages" requests to the standard tier on their own. Trigger language packs make any input language addable; Korean bare-name delegation and generic delivery cues route to the coding lane; a vagueness gate holds heavy modes back; a dispatch that would inherit a provider which cannot serve it is refused. The provider-entitlement interview reorders chains per machine.
- **Coding and fanout.** Single-run Maestro dispatch with explicit owner override and per-run `--model` / `--effort`; operator category→model chains (`category-maestro`) surfaced through setup; revision-bound, tiered, reusable verification plans with an explicit post-integration gate; resumable fanout via a terminal-state run journal; adaptive provider-pressure admission; capped recursion depth and spawn ceiling; retry classification gated on replay safety; preflight blocks for doomed Hermes child spawns; dispatch-failure classification, repair, and interview; shared build artifacts symlinked into unit worktrees; a completion-integrity gate that refuses fake completion.
- **Observability and HUD.** Live mid-run token telemetry and Claude Code-style aligned token columns on subagent rows; Hermes-native cost provenance in the HUD (confirmed zero vs unknown vs approximated); honest-unknown elapsed time; the plan todo scoped to the session that declared it; selectable TUI themes and `omh theme repair`; a copy/export manifest for the current work artifacts.
- **Skills.** New workflows: adversarial-consensus, llm-app-dev, backend/rust/native-debugging domain pack, codebase-uml (with `omh codegraph uml`), frontend-refactor, refactor-plan, inference-serving, instrumentation ladder, tech-debt-audit, decision records, a11y rule IDs, web-vitals budgets, self-evaluation loops, award-bar-score, model-optimization, omh-docs, GitHub issue intake, and memory-sync interviews. Existing skills gained a slop taxonomy (ai-slop-cleaner), a spec-conformance axis (code-review), and split web-lookup and audience-aware briefings (ulw-research). A skill upstream-sources registry records reconstruction provenance.
- **Quality gates.** Instruction-density and shared-prompt budgets sized for the smallest model in the fleet; denominator hygiene for every self-reported rate; cross-surface duplicate-content detection; prompt/schema overlap classification; adversarial-regression rule before a guard deletion; evidence freshness bound to the git tree hash; the routing corpus calibrated against recorded decisions.
- **Security.** A named strict posture via `OMH_SECURITY`, an approval-tier resolver that centralizes confirm/refuse decisions, and a verification lane that escalates on sensitive path touches.
- **Benchmarks.** A live cross-harness lane that executes what it submits, ternary live verdicts with baseline comparison, manifest-aware analysis for targeted family runs, a `family` condition that measures an exact-model override against the block it replaced, and the offline framework tests running inside the sharded CI suite.
- **CI and release.** The unit-test suite is sharded by measured duration with a serial quarantine and exact-once aggregation; the landing page's version badge is parity-gated and bumped with the other version surfaces.
- **Fixes.** `plugins.enabled` list items level with their key are read and written correctly; the fanout admission tests and the cross-harness crash fixture no longer flake on loaded runners; a zero cost renders only with the provenance that earns it; HUD row identity keeps its parentheses; the context dash the header could never fill is gone.

## 1.0.6 - 2026-08-13

- Made `omh update` installation-aware: Homebrew, Bun, npm, curl, and PowerShell installs now update their owning command package first, re-enter the updated CLI, and then refresh managed skills, the installed plugin bundle, and existing Hermes registration.
- Added the Hermes dock-bottom OMH activity HUD, fresh-install TUI selection, and an all-in-one agent install protocol with approval-gated model aliases; recommendation resolution now reports `owner_default` through `model_recommendation_resolution/v2` and completes setup without a model-config write when no confirmed candidate matches.
- Added typed unit-result sidecars for fan-out dispatch: `fanout_unit_result/v1` schema with structured process status, command evidence, and reporter-vs-observer provenance marks out exactly what was dispatched, what it reported, and what the dispatcher verified independently — replacing the exit-0 overclaim with a four-state vocabulary (`process_succeeded`, `result_schema_valid`, `unit_verification_observed`, `integration_ready`) that reflects the actual evidence ladder.
- Hardened worktree creation with runtime base-SHA validation, unique-branch enforcement, and crash-cleanup receipts logged to the observation journal.
- Unified dispatch-profile capability metadata into `executor_capability_snapshot/v1`: edit formats, persistent eval, tool reentry, and code-mode batching now use the same observation-backed source as owner fit, with bounded evidence and `unknown` defaults. Briefing and fanout receipts project that snapshot without independently selecting or ranking an owner.
- Fanout preparations now freeze deterministic owner capability evidence in `fanout_contract/v2` with closed local provenance. Direct v1 dispatch is retired: maintainers use `omh coding fanout migrate-legacy` to validate or explicitly confirm the exact legacy payload and freeze it as v2 first. Dispatch preflight rejects goal, safety, schema, merge-order, owner, or snapshot drift before Git, discovery, readiness, or executor activity.
- Added `omh coding fanout status` read-only roster command that projects dispatch journal events into a unit-level summary table.
- Strengthened delegation guidance in the skill catalog with five bounded blocks: code-mode batching (capability-conditional), edit-format steering, resource-reference idiom, review-verdict format (P0-P3 priority framework), and commit-planning discipline.
- Added orchestration patterns documentation: boundary-policy rules with retry-from-checkpoint, and async advisor-as-reviewer contract with explicit severity gates.
- Added benchmark fixture discipline guidance: seeded deterministic mutations, fresh sessions, exact-equality grading, raw transcript retention, and first-party authored measurement labels.
- Added capability-shape parity documentation linking OMH-native schema contracts to the oh-my-pi designs that inspired them.
- Strengthened memory documentation: durability-receipt state vocabulary (`candidate_persisted`, `approved_record_persisted`, `indexes_refreshed`, `replay_ready`) and explicit learned-skill candidate-gate wording.

## 1.0.5 - 2026-08-08

- Added a message gate: every coding delegation now shows which skill ran, which executor and model it ran on, what evidence class the answer belongs to, and a digest of the prompt behind it, rendered by OMH as exact lines instead of asked for in skill prose. The composed Hermes order ships as its own follow-on message, bounded and fenced.
- Replaced the raw evidence vocabulary in everything a person reads. `prepared_not_observed` now renders as `Plan · not run`, `completed` as `Code · reported done`, and `worktree_failed` as `Setup · failed`, across chat, the status board, the route summary, the menu bar, and the README. The wire values are unchanged, so anything parsing them keeps working.
- Separated an executor's own claim from a checked result: a unit that reported itself finished no longer renders identically to one that passed a gate.
- Added `omh goal status --text`, so a goal ledger can be read as lines instead of escaped JSON.
- Added a coding handoff safety boundary, a single safety preflight with an opt-in organization rule source, a task authority envelope, and risky-action classification with run-bound approval receipts.
- Added external effect receipts, a normalized owner-progress vocabulary, safe blocked-work records with a decision history, and one shared append-only store with stale-update rejection.
- Made unit prompts skill-aware: fan-out work discovers, arranges, and interviews the skills available to the executor it is handed to.
- Gated follow-on engine starts on explicit user confirmation, and taught the delegate rules the real Claude Code permission-grant and session-resume mechanics.
- Made the capability policy changeable and enforced rather than advisory.
- Brought Windows to parity: the full suite runs on `windows-latest` in CI, journal lines stay LF, atomic replaces retry under sharing denials, and the installer path was fixed.
- Added CI gates for roles, capability families, and whitespace, plus a catalog deference gate covering the sibling relationships the catalog writes in prose.
- Bound observed workflows to snapshot evidence, and narrowed the plugin awareness markers to the routes they actually support.

## 1.0.4 - 2026-08-01

- Overhauled Hermes memory into a governed lifecycle: admission, evaluation, retention, expiry, and retirement policies, write-replay hardening, migration with reactivation for legacy stores, rollup signals, peer-perspective records, and record fusion, plus recall packs with freshness, budget, and conflict-aware sibling controls.
- Added a reviewed domain-intelligence store with an operator-controlled capture, review, approve, replace, and retire lifecycle, backed by descriptor-bound fail-closed snapshot validation and lineage, rejection, and retirement audit trails.
- Added domain-aware clarification: after a project-local domain profile is approved, an unresolved chat question can ask the exact catalog-owned expert question (English or Korean) for eight specialist workflows, while every already-resolved route, dispatch, and protected body stays byte-identical.
- Added eight specialist domain skills (sales development, finance analysis, legal compliance review, curriculum design, localization review, people ops, product brief, support operations) with domain-affinity ranking in the picker.
- Added model inventory routing: setup captures which coding agents and models are actually installed, and routing, main-agent composition, and dispatch recommendations follow that inventory instead of assuming a fixed owner.
- Added a research depth dial with declared shallow and deep chains, research-role routing, and a bounded executor prompt contract for prepared coding handoffs.
- Reworked dispatch ergonomics: choice-required dispatch when several owners fit, a unit verification protocol for fan-out work, delegation-protocol guidance across surfaces, and session follow-up handoffs that keep context across turns.
- Tightened routing quality with an accuracy program, overroute audits, picker-completion fixes, and clearer skill names and descriptions across the catalog.
- Made `omh update` report package-version and content movement explicitly, refresh every installed surface, and bust stale caches.
- Refreshed the README family with workflow GIFs, highlights, a uniform demo grid, and community links, and froze per-skill Korean copy behind explicit opt-in.

## 1.0.3 - 2026-07-26

- Added a `/omh` meta-router gateway skill with live-catalog routing, four Hermes setup-guide skills, and a generated full-catalog index reference so Hermes can discover the workflow surface from chat.
- Added an `omh-` display prefix to generated skill frontmatter, so a Hermes status line shows `omh-ultrawork` instead of a bare name that could belong to any skill, and made echo-back of those display names route correctly.
- Bounded the deep interview: every question now carries a `Round {n}/6` header with a clarity percentage over three fixed dimensions, and the interview stops on resolution, an explicit user stop, or the round budget.
- Reworked coding delegation around request-led states: coding route next actions split into four states, named coding-agent delivery takes precedence over advisor and feedback lanes, and setup asks one question with usage-time owner delegation.
- Added an opt-in local dispatch bridge that executes fan-out contracts in parallel against a deterministic merge contract, plus executor-scoped handoff validation.
- Made messenger rendering honor the render-profile contract on the chat route-hint path, which is the only limited-rendering path for the Hermes platforms that are not named individually, and made a present-but-unsafe body warn instead of passing silently.
- Surfaced wrapper degradation to chat users instead of dropping it at the wrapper, and taught progress reporting to detect claim/observation mismatches rather than only exempting them.
- Added an `omh doctor` advisory lane for the costliest Hermes misconfigurations, including noticing when the plugin is installed but disabled.
- Added a pinned Ruff static-analysis gate to CI and contributor docs, and a self-checking broad-exception policy gate.
- Cut repeated common-rail context in generated skills and bounded prompt, capability, stdout, and status payload budgets so shared context does not become prompt bloat.
- Defaulted skill-pack install to a core profile with opt-in full, and added a reconcile path from full back to core.
- Defaulted all setup and CLI output to English; localization is explicit opt-in through `--language` or `OMH_LANG`.
- Retired OMH worktree creation in favor of native Hermes and Git tooling.

## 1.0.2 - 2026-07-01

- Added stronger Hermes chat routing, workflow picker, direct-answer, file-lookup, and operator fast paths for common English and Korean requests.
- Added localized chat-card framing and release gates for localized copy, router fast paths, Hermes UX quality, routing precision, context brief coverage, route-hint alignment, and release evidence bundles.
- Added richer plugin, MCP, menu bar, codegraph, workflow-learning, source-finder, paper-learning, and worktree/session observation surfaces while preserving metadata-only evidence boundaries.
- Modernized the public site, README workflow presentation, docs, generated skill guidance, role context, and release readiness instructions around the Hermes-native wrapper contract.

## 1.0.0 - 2026-06-09

- Added the initial `omh` installer and Hermes skill workflow pack.
- Added a direct `src/` package layout for future growth.
- Added generated routing catalog and rendered skill content.
- Added open-source project operations files and GitHub templates.
