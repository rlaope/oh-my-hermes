# Changelog

All notable changes will be documented here.

## Unreleased

- **A narrow table keeps its columns on Slack, and provenance stopped taking
  the notification preview.** Messenger profiles turned every markdown table
  into bullets, which is right for a wide one and wrong for the shape people
  actually send — a list of issues or PRs, two or three short columns, which
  reads as a table and loses its alignment as bullets. Limited profiles now
  render such a table as an aligned block inside a code fence, the one shape
  Slack and Telegram keep, and fall back to bullets above three columns, above
  a 56-cell rendered width, or below two data rows. Each limit answers a
  different failure: a wrapped monospace row no longer lines up with the row
  above it, and a fence around a single row costs more than the columns save.
  Rich profiles are unchanged and keep the markdown table.

  Column width is now measured in display cells rather than characters.
  `len("이슈")` is 2 while the string occupies four columns, so padding by
  length is how a Korean or Japanese board comes out ragged inside the fence
  that exists to keep it straight — which the coding status board had been
  doing all along, and `src/commands/setup.py` had been getting right in its
  own copy. `src/system/display_width.py` is now the one home for both.

  Separately, the message gate's five provenance bullets became one line, and
  on limited profiles it follows the body instead of leading it. Five lines of
  "which skill, which model, which prompt" above the answer spend the whole of
  a phone's notification preview on who did the work rather than on what they
  found. The field labels stay: dropping them would leave
  `ulw-goal — active — sha256:…`, where only the digest identifies itself. Rich
  profiles keep the aligned card above the body, where there is room for it.

- **A coding briefing now opens by saying whether it needs you.** The first
  line carries 🔴 / 🟡 / 🟢 — stopped, waiting on you, running — which is what
  a phone notification shows when it shows sixty characters and nothing else.
  The signal is computed from observed state (a standing blocker, then whether
  dispatch was ever observed), never from `next_action`: that token is free
  text from an open set of producers, and whether a reader has to get up must
  not depend on wording someone else chose. It also ships as `signal` in
  `coding_briefing/v1` so an adapter with its own chrome can ask the question
  without parsing a sentence. `headline` now consults the blockers too, so a
  cancelled run can no longer be headed "reported completion" beneath a red
  glyph — the contradiction the previous entry left open. The remaining
  internal tokens left the screen with it: the `Stopped:` / `Remaining:` /
  `Action:` labels are translated, runtime milestone ids are named in words,
  and `next_action` is rendered as what the reader should do
  (`surface_runtime_failure:ci` → "look at the failure on CI"). That last one
  is an open set, so unrecognized values render "check the current status"
  rather than the token — the failure mode being fixed is a token reaching a
  chat bubble, and doing it only for rare values would have made it harder to
  notice rather than rarer. Every identifier stays in the payload for anything
  that parses it. `tests/test_briefing_line_shape.py` sweeps eight run states
  across four locales for twenty-one known internal tokens.

- **The coding briefing stopped printing its own step ids at the reader.**
  `Still missing evidence: workspace_isolation, verification, review, ci` named
  five internal keys; a key is a stable identifier, not a word anyone outside
  this repository knows. Step and blocker names now come from
  `src/catalogs/briefing_vocabulary.py`, which answers in all seven locales
  either locale set can ask for, and `build_coding_briefing` takes a `locale`
  for the rendered lines only — ids, `next_action`, and every machine-readable
  value keep their one spelling so a parser never has to know the reader's
  language. The same module supplies the status board's copy, which had been an
  `if korean:` pair inside the renderer: five of the seven locales could not be
  rendered no matter what a caller passed, and `status_board_messenger_body`
  took no locale at all, hardcoding `korean=False` at each of its three call
  sites — so a messenger board was English regardless of configuration. Both
  now take a locale. The Korean truncation line also gains the unit total it
  alone omitted, which had left a reader to add two numbers to learn how much
  work there was. `tests/test_briefing_vocabulary.py` derives the required keys
  from `_progress_steps` and `_BLOCKER_KINDS` rather than from a list kept
  beside them, and fails on a row that answers fewer locales than a caller can
  ask for. The `Stopped:` and `Not reached yet:` labels themselves are still
  English; they belong with the line structure, not with the names.

- **A stopped coding run no longer reads as an early one.** The coding briefing
  listed everything that had not happened under a single `Still missing
  evidence:` heading, so a step the runtime had failed, blocked, or cancelled
  appeared as one more name beside steps nothing had reached yet — and a reader
  had no way to tell which. The distinction was not recoverable from the
  payload either: `_state` spells an unmet prerequisite `blocked`, and
  `_runtime_event_state` spells an observed runtime failure with the same word,
  while a cancelled milestone reached no briefing surface at all even though
  `build_runtime_observation` had tracked it separately all along.
  `coding_briefing/v1` now carries `blockers[]` beside `pending_gaps[]`, each
  entry naming the step, its kind (`failed`, `blocked`, or `cancelled`), and the
  runtime event behind it, read from the runtime observation rather than
  re-derived from a state word. The rendered lines lead with `Stopped:` and no
  longer repeat a stopped step under what is now `Not reached yet:`, and the
  narrative leads with the stop instead of with what the run is waiting on.
  `pending_gaps[]` keeps its meaning, its ordering, and its consumers; the
  headline still reports the executor's own result and does not yet consult
  `blockers[]`.

- **Fanout's write fence now works on Linux.** `omh coding fanout dispatch`
  confines the owner CLI and its verification commands with `sandbox-exec` on
  macOS, but the Linux `bwrap` path had never run, and on a real host (Fedora
  44, bubblewrap 0.11.0) it never could: its `--tmpfs /` root mounted only each
  executable's directory, so the dynamic loader was missing and even the
  preflight's `/usr/bin/true` failed with `execvp /usr/bin/true: No such file
  or directory`. Every Linux dispatch therefore ran unconfined, recorded as
  `sandbox_preflight_failed`, even with a trusted bwrap installed. The fanout
  layout is now the Linux counterpart of the macOS policy. The host tree is
  mounted read-only, so a write outside the worktree and the owner's state
  fails with `EROFS` instead of landing in a private tmpfs; `/dev` and `/proc`
  are fresh; toolchain `TMPDIR` points into the worktree's ignored
  `.omh/confinement-tmp`; the spawning environment is inherited rather than
  cleared, so per-command verification overrides reach the child; and
  `/run/user/<uid>` is replaced by an empty read-only mount, because from a
  read-only host tree `systemd-run --user touch <path>` otherwise asks the
  user's service manager to write outside the fence. The preflight and the
  probe run under that same layout. macOS keeps its probe policy unchanged and
  the cross-harness adapter lane keeps its strict layout. A Linux host with no
  trusted bwrap now reports `sandbox_backend_unavailable` instead of a failed
  preflight. The real-sandbox tests that ran only on macOS now also run on
  Linux hosts with a working trusted bwrap (and skip elsewhere, including CI),
  four backend-independent tests left the macOS-only class, and the
  `docs/FANOUT.md` note that dispatch provides no filesystem confinement is
  corrected. (#1356)

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
- **A wrong memory source now has a blast radius.** `omh memory sources`
  indexes reviewed records by the source recorded on them, and `--source
  <label>` returns that source's records so they can be piped into the
  primitives that already shipped -- `lineage`, `retire`, `prune`, `correct`,
  `recall-suite` -- every one of which takes a record id the operator
  previously had no way to produce. Two record fields are source axes and one
  record can carry both (`source`, the admission channel, and `source_ref`,
  the document the memory was taken from), so a record admitted from two
  sources is indexed under both and reports both under `matched_axes` rather
  than only the first. The report is a read: it quarantines, retires and
  deletes nothing. A record that recorded no source is listed as
  `indeterminate`, never assumed clean, alongside any record file that would
  not parse, and an empty selection names which of the three empties it is
  (`empty_store`, `source_never_recorded`, `no_records_for_source`) because
  they are three different answers. `memory-sync` gains one pointer to a new
  `references/source-recovery.md` carrying the quarantine-first sequence and
  the rule that completion evidence is a recall report over this store showing
  the records absent -- never the retire command's exit code, and never
  `recall-suite`, which seeds its own fixture corpus in a temporary store.
- **The evaluation lane scores the path, checks the corpus, and qualifies the
  judge.** Three gaps let a number out of this lane with nothing behind it.
  `agent-evaluation` scored quality, correctness, time, cost, tool coverage,
  verification and review gaps separately but never the order the run took, so
  a run that reached the right answer by skipping verification scored the same
  as one that did not; it now carries a trajectory dimension scored beside the
  outcome and never folded into one total, asking whether the run searched
  before it asserted, took approval before an irreversible side effect, used an
  available tool instead of guessing, and verified before claiming done.
  `llm-app-dev`'s `references/eval-harness.md` specified the golden-set shape
  but not its hygiene, so a leaking corpus produced a quotable score; it gains
  a corpus-hygiene section covering answer leakage, duplicates and
  near-duplicates, fixtures mutated until a case passes, a holdout contaminated
  by the tuning that chose the threshold, and per-case provenance, with the
  rule that the corpus state is reported above the score and an unchecked set
  is labelled unchecked. The catalog ranked judges below executable checks but
  never said how to qualify one you have no choice but to use, so
  `agent-evaluation`'s `references/self-evaluation-loops.md` gains the
  qualification procedure -- a hand-labeled sample, a blind judge pass with the
  grader model ID pinned, agreement measured against the human labels with a
  chance-corrected statistic beside raw agreement, and every disagreement read
  -- plus the table saying what each agreement band licenses. A judge with no
  measured agreement is unqualified, and that verdict is a safety rule in the
  always-loaded body rather than a reference note, because a judge is used
  while comparing executors and the existing reference pointer fires only for
  self-evaluation.
- **Three reported misroutes reach the skill that owns the question.** A
  filling context window ("context window is almost full, save decisions and
  hand off to a new session") returned the project-terminology workflow at high
  confidence because the message opens with the word `context`, which is that
  workflow's whole name; `context-budget-review`, which owns the must-keep
  pack, the summarization checkpoint plan and the overflow recovery route, did
  not place. The budget sense of `context` -- `window`, `limit`, `compaction`,
  `overflow` alongside the `budget` already carved out -- now stops that word
  carrying explicit-invocation weight, and the lane gains the overflow
  phrasings it had no trigger for. A Korean continuous watch ("계속 감시해줘")
  reached nothing, and so did its English form ("keep watching this", "keep
  monitoring the build"): every phrasing `automation-blueprint` recognised
  named a cadence or the word automation itself, so the intent was missing in
  every language rather than only in Korean, and the English base corpus, the
  `ko.json` pack, and new `ja.json`/`zh.json` entries all ship together. And a
  memory-provider comparison ("compare memory providers on my own data for
  retrieval quality and latency") reached the operations telemetry card,
  because it reads as telemetry word for word, while the skill that declares
  `memory_provider_posture/v1` -- and that `memory-sync` explicitly defers
  provider questions to -- did not place at all; the noun phrase now reaches
  `external-connector-readiness`, its declared owner. Every generic word these
  triggers are built from (`window`, `hand`, `off`, `keep`, `watch`, `monitor`
  and the rest) is held back from its skill's trigger tokens and pinned by a
  negative control in the sense it does not mean, so an ordinary sentence
  routes exactly as it did before.
- **An application threat-model request no longer gets the agent's threat
  surface.** `security-safety-review` emits `threat_surface_map/v1` over the
  AGENT's own prompts, tools, files, dependencies and credentials, so asking
  Hermes to "build a threat model for our payment service architecture" did not
  merely miss -- it would have answered confidently with the wrong artifact
  under a near-identical name. That phrasing returned `deep-interview`,
  `build-failure-triage` and `model-setup`; it now opens the new
  `application-threat-model` workflow, and an agent-surface phrasing still
  opens `security-safety-review`, both pinned in the routing corpora. The
  workflow models a real system: an asset register with a data class and one
  named loss each, trust boundaries stating what crosses and what authenticates
  the crossing, attack scenarios derived per boundary, one decision per scenario
  from a closed vocabulary (mitigate, transfer, accept, eliminate) with an
  owner, and a security test per mitigating control naming the observable that
  fails when the control is removed. Its artifact is `application_threat_model/v1`
  -- it shares no word of structure with `threat_surface_map/v1`, names the
  application as its subject, and is never a surface map. A control is
  `unverified` until observed configuration or a passing test says otherwise,
  the workflow never writes exploit code, and the model is not a scan, a
  penetration test, or a compliance attestation. The six STRIDE prompts, the
  asset/loss table and the per-control test shapes live in
  `references/threat-model-method.md`, measured outside the always-loaded body
  budget.
- **A reviewed skill draft can be installed, through the promotion lifecycle
  that already shipped.** `omh learning skill-draft` produced a draft a person
  could approve and then do nothing with: the boundary said an approved draft
  is "a proposal a person or Hermes Agent `/learn` acts on - never an install".
  One lane over, `omh web-qa promotion` already did exact-byte diff review,
  reviewer-bound approval receipts, a single visibility commit, retained
  generations, rollback, removal and crash-safe retry -- and reached exactly one
  kind of source, because every entry point took a browser `trace_id`. The
  parameter is now a promotion source id and the same seven subcommands are
  mounted a second time as `omh learning promotion ... --source-id sd-<id>`,
  calling the same functions: nothing about the lifecycle was reimplemented, and
  a browser-derived promotion still renders byte-identically, which is why the
  `browser_*` schema names and the receipt's `trace_*` field names were kept
  rather than widened. A draft installs only after `skill-draft review
  --decision approve`, only from this project's own draft store, and only past a
  pattern risk scan of its instruction text that reuses the `plugin-risk-audit`
  detectors and refuses naming the category it matched. A review later changed
  to `revise` or `reject` deactivates the entry it approved on the next
  `status`. `skill_pattern_risk_review/v1`, whose own docstring said its only
  caller was its test file, is now reachable as `omh ops
  skill-pattern-risk-review`; it cites the scan and decides nothing, because a
  clean scan is not an approval. A promotion status meaning the entry is not
  live -- `stale`, `quarantined`, `unverified_managed_state` -- no longer exits
  `0`.

- **Two more pinned fixtures say their own order out loud.** Every committed
  fixture was read against the assertion that consumes it, asking what the
  parse discards. Two maintain an order no assertion could fail:
  `routing_precision_subset_at_c.json` keeps 237 pinned case ids sorted while
  both consumers turn the list into a set, and `ulw_alias_baseline.json` keeps
  84 cue keys sorted while the baseline is compared as a dict -- in each case a
  re-derive in producer order rewrites the whole file, buries the row that
  moved, and passes CI. Both orders are now asserted, and the second also
  pins the `sorted()` inside `ulw_alias_corpus()` that supplies it, since
  removing it makes the cue order hash-dependent without failing anything.
  The rest of the sweep is recorded as not depending on a maintained property:
  hand-authored inputs no producer rewrites, frozen historical captures,
  single-line compact files no diff can bury a change in, and artifacts already
  held byte-exact by an existing gate. (#1615)
- **An incident that is still open now has an owner.** The catalog held every
  piece of live incident work and no skill that ran one: severity and the
  customer reply in `support-operations`, health signals and the rollback gate
  in `deploy-and-monitor`, retrospective synthesis in `reliability-review`,
  readiness in `production-audit`. `support-operations` explicitly routed an
  active incident to `reliability-review`, whose own `use_when` is "review
  incident notes, SLOs, error budgets" -- so the one skill that saw the request
  handed a running outage to a postmortem. Measured on the deciding surface
  (`build_chat_interaction_payload`), "we have a production outage right now,
  declare severity and assign an incident commander" was a clarification with
  no owner, and "the checkout service is down right now, start the incident
  timeline" dispatched to `reliability-review`. The new
  `live-incident-response` workflow owns the open incident end to end: severity
  declared as live state with the observation that set it, a named commander
  plus operations, communications, and scribe, an append-only timeline where a
  correction appends an entry naming the one it corrects and never rewrites it,
  every mitigation marked temporary or permanent with what removes it, recovery
  verified against a named signal at its healthy value rather than inferred
  from a mitigation being applied, and the customer notice drafted. Paging,
  status-page updates, and customer sends are effects OMH cannot perform: they
  route to `connector-operator` and are recorded observed only when the
  connector returns a result, with prepared and observed kept as separate
  states in the record. The boundary closes in every direction rather than one
  -- `reliability-review` and `deploy-and-monitor` each gain their first
  `do_not_use_when` statement pointing back at the live lane, and
  `support-operations`'s single active-incident statement splits so the live
  half reaches the live lane and only the retrospective half stays with the
  review. The method detail (the severity ladder, the four roles, the three
  timeline entry types and their fields, the communication ledger, handover and
  closing) is `skills/omh-live-incident-response/references/incident-command-method.md`,
  measured outside the always-loaded body budget. Seven negative controls pin
  the other senses of "incident", "commander", "severity", "outage",
  "production" and "war room", and eight interventions pin the live phrasings
  plus the three siblings keeping their own requests. (#1563)

- **Sensitive work can be kept off models whose data policy nobody has read.**
  Nothing recorded how a model's provider handles the data sent to it, so the
  only exclusion available was `excluded_providers` at provider granularity and
  a per-machine reorder of `model-chains.json` — neither grounded in a policy.
  `MODEL_CONTRACTS` now carries a `data_handling` axis with two closed
  vocabularies (`training_use`, `retention`) plus the account scope that keeps
  it out of account-level claims, exactly as `rollout` already does: the value
  is the vendor's documented default for the surface the contract was read
  from, and tier, region, and a negotiated agreement move it in both
  directions. `omh model-chains show --sensitive` declares the work sensitive
  as a field — never inferred from message text, which
  `src/quality/safety_preflight.py` forbids outright — and drops every model
  whose contract does not document a permitting default, naming each exclusion
  with its own reason: the policy conflicts, the axis is undeclared, the policy
  was never read, or no contract resolves at all. A model of unknown policy is
  excluded and named, never silently kept and never silently omitted; the
  command exits 1 when a category is left with nothing to route to. Both
  shipped contracts declare the axis as `not_recorded`, because neither
  vendor's data-usage page is among their sources and inventing a value there
  would be the claim this axis exists to stop — so every shipped chain empties
  today, which is the honest state and is now visible rather than assumed. The
  coverage audit reports the axis as its own dimension, derived from the same
  verdict the gate acts on so the two cannot disagree. (#1560)

- **`doctor` now proves the plugin enforces, not only that it registered.**
  The checklist already refused to collapse install, import/register smoke, and
  Hermes runtime load into one claim, but nothing asked the installed bundle to
  decide anything: a plugin that loads, registers every tool and hook, and
  returns `None` for every tool call passed all three tiers. A fourth tier,
  `plugin_enforcement_smoke`, calls the installed bundle's own
  `toolcall_rule_directive` in-process against a temporary rules home and
  reports the decision it got back. Two probes, because one cannot tell
  enforcement from a stuck answer: a scoped probe the rule names must come back
  blocked, an unscoped one must proceed. A bundle that decides neither, or
  blocks both, fails this tier while the import and register tiers keep
  passing, and the report says so in those words. A bundle whose seam cannot be
  reached at all reports `unknown` and still does not pass. The probe is
  harmless by construction rather than by choice of a realistic command: both
  tool names are fabricated, appear in no host and in `PROVIDED_TOOLS`, the
  arguments carry one marker and no path, command, or content, the rule is
  `repeat: always` so no once-per-session claim is consumed, and the rules file
  lives in a temporary directory that is the probe's entire OMH home. (#1561)

- **Two profiles can be checked for isolation instead of discovered to leak.**
  `CONTEXT.md` states "Exactly one home is active per invocation" as an
  invariant and nothing verified it, so a leak between two profiles surfaced as
  behaviour rather than as a finding. `omh doctor --profile-isolation
  '<omh-home>[,<hermes-home>]' '<omh-home>[,<hermes-home>]'` compares two
  profile references across config, cache, plugin state, files, and env, one
  verdict per surface over named artifacts rather than a tree diff. It reports
  a shared path as leaked and names the path, catches the two shapes a string
  comparison misses — two homes symlinked to one target, and one home nested
  inside the other — and reports `unknown`, never `isolated`, for a surface it
  could not inspect, which is what a profile reference with no Hermes home
  produces. The env surface names the ambient `OMH_HOME` or `HERMES_HOME` that
  pins one of the two profiles for every invocation that forgets a flag. Exit 1
  on a leak, 3 when nothing leaked but a surface was not inspected, 0 only when
  every surface was inspected and none leaked. The ordinary `omh doctor` run is
  unchanged: the sub-check fires only for the operators who pass the flag.
  (#1562)
- **A crashed paired-run cell now records what raised it.** `_execute_cell`
  contains an exception so one cell's failure cannot take the matrix down, and
  the containment is correct -- but it discarded the reason. A
  `ReceiptVerificationError` naming a short integrity key reached the caller as
  an opaque CRASHED cell, and the fan-in blocker then described the shape of
  the result (`crashed execution state`) rather than the cause. On #1592 that
  cost a full diagnosis cycle: the first hypothesis drawn from the surviving
  evidence was coherent and wrong. The `except` clauses are unchanged; what
  they record is wider. Every contained failure -- workspace, runner, unexpected
  runner error, and cleanup -- now carries a `PairedRunCrashReason` on the
  outcome, and the fan-in blocker reads `crashed execution state:
  ReceiptVerificationError: Hermes child observation integrity key is invalid`.
  A runner that already crashed owns the cause, so a later cleanup failure does
  not overwrite it. The record reaches a metadata artifact, so it carries a
  bounded exception type and a message that is path-redacted, control-stripped,
  capped at 200 characters, and withheld whole when it matches a secret marker;
  `withheld` and `empty` stay distinct states so a reader can tell a screened
  message from an exception that carried none. (#1619)

- **The ja/zh confidence tier is now a recorded decision, not an unpinned
  artifact.** A Japanese or Chinese trigger phrase reaches its skill one tier
  below the English equivalent: a CJK sentence is one routing token, so a pack
  phrase inside a longer sentence earns the phrase credit but not the token
  credit an exact-message match adds, and lands at clarify-with-candidate where
  English dispatches. Measured over every shipped pack rather than the two
  phrases the report named: 84 of 91 ja phrases and 81 of 88 zh phrases
  dispatch at high when sent bare and clarify at medium once a sentence
  surrounds them, while ko -- space-segmented and NFKD-folded -- barely moves,
  895 of 962 bare against 899 wrapped. `RoutingInterventionCase` gains
  `expected_confidence`, so a case pinned at `clarify` can state which tier it
  reached instead of passing at any tier below dispatch, and four cases record
  the gap: a ja and a zh phrase inside a sentence at clarify/medium with the
  skill still named, and one zh phrase pinned bare at dispatch/high beside the
  same phrase inside a question at clarify/medium. The scoring half is
  deliberately not taken here: lifting CJK credit would move roughly 165 pack
  phrases in one change, and it now has cases to move deliberately. (#1607)

- **The judge agreement bands now say they are unverified here.**
  `agent-evaluation`'s `references/self-evaluation-loops.md` tells a reader
  where an LLM judge's usable thresholds sit -- unmeasured is unqualified,
  below 0.4 unusable, 0.4 to 0.6 relative comparison only, above 0.6 absolute
  scoring. Those bands are the conventional reading of a chance-corrected
  agreement statistic and were measured on no judge this repository uses, so a
  reader who applied the section's own rule correctly still read their figure
  against a table nobody checked. Measuring them here needs a judge already
  used in an OMH evaluation lane and a hand-labeled sample from its own
  distribution, and neither exists: OMH's evaluation lanes score with
  deterministic predicates against frozen corpora, there is no grader model,
  and there is no human-labeled sample. So the table now states its own
  provenance rather than carrying an invented measurement or losing the
  guidance: the bands are the starting default, the first row is a rule rather
  than a calibration and holds whatever a measurement shows, and a sample too
  small to separate 0.4 from 0.6 is itself the reportable result. The
  measurement remains open. (#1612)

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
