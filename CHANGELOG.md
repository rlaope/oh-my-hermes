# Changelog

All notable changes will be documented here.

## Unreleased

- **The delegation nudge counts distinct searches, and its budget survives a
  plugin-host restart.** It watched `search_files` and fired at five direct
  reads, counting CALLS -- so five different greps and one grep five times
  were the same event to it. In session `20260919_140745_db409e` the model
  issued 203 `search_files` calls, the large majority identical; the nudge
  spent its whole budget of two on the loop, said "delegate this", and was
  silent for the remaining ~180 calls. The session's actual problem was that
  it was repeating one search that returned nothing, and the only OMH
  mechanism watching searches had no way to know.

  The threshold now counts distinct `(tool, argument digest)` pairs, using the
  digest the repeat guard already computes for the same call at
  `pre_tool_call` rather than a second hashing path. Five identical searches
  do not fire it; five different ones still do; the pinned negative at four is
  unmoved; a hundred repeats followed by a real search pass still has its full
  budget. The text says "different search/read calls", because the number in
  it changed meaning.

  The budget also stops refilling itself. `MAX_ENGAGEMENT_NUDGES` is two per
  kind per SESSION and the counter lived in a per-PROCESS map, so a restart
  handed the session a fresh one: `db409e` received four delegation nudges in
  a 2+2 split bracketing a mid-session `omh update`, and `8da9b8` received
  three. The two counters that bound the spend and the two latches that end it
  are now written to a session-keyed store under the OMH home, read back once
  per session, under the same 64-row LRU bound the process map uses. The work
  counters stay in the process on purpose: losing them across a restart delays
  a nudge and never adds one, and persisting them would put a file write on
  every watched tool call rather than on the handful that spend something.

  What the data says about this nudge, stated because it bears on whether the
  budget is worth defending: across 140 intervention-to-next-assistant pairs
  in the 2026-09-19 audit, none was followed by an OMH tool call, including
  the eight delegation nudges. The one intervention with a visible effect is
  the route hint (`skill_view` follows it 37 times in 60). It is kept because
  a distinct-search pass is the case it was written for and that case was
  never actually reached before this change. Whether prose that changes
  nothing earns 668 characters a session is a product decision and is not
  taken here.

- **The HUD can tell forty different tool calls from the same call forty
  times.** The activity segment counts calls in flight, which is progress,
  and a loop is the opposite situation wearing the same number. Session
  `20260919_140745_db409e` issued 203 `search_files` calls, 185 of them
  refused by the host's own guard, for a pattern matching nothing in the
  repository; the person noticed only because the transcript's tool-call
  panel happened to be expanded. Collapsed, that panel is one chevron line
  reading `Tool calls (203)`, and the HUD was the only place left to see it.

  The status line and the TUI dock header now carry `repeat xN` whenever the
  repeat guard has a cycle for the reading session: muted while the guard is
  only watching, `repeat xN blocked` in the warn tone once it has actually
  refused a call, and `repeat xN approval` in the error tone once it has
  stopped answering the model and is asking a person. A cycle longer than one
  call says so (`repeat x8 cycle-of-2`), because the same call eight times
  and a pair of calls four times over are different things to look at.

  Three properties make the row trustworthy rather than decorative. It is
  scoped to the reading session, resolved the same way the plan block
  resolves it, so two sessions sharing one OMH home never add up. It rides
  the poll's existing ledger read -- one read already backed the parallel
  shot and the liveness block, and now backs this too -- so the two-second
  reader takes no new lock and no new file open; measured at the 64-session
  ceiling, the projection costs 0.006 to 0.018 ms more and the whole HUD read
  is unchanged inside noise. And the stage is the one the GATE recorded:
  `escalation_can_reach_a_person` reads process-global maps that the widget's
  freshly spawned interpreter does not have, where it would answer "attended"
  for every session, so `pre_tool_call` writes its own answer onto the row
  and the reader takes that. A row with no recorded answer withholds the
  escalation stage rather than assuming it.

  Metadata only, and narrower than the ledger: the projection is given no
  tool name and no argument digest, so the row says that a call repeated and
  never what it was. Asserted against the serialized payload with a sentinel
  in the arguments and in the results.

- **Fourteen skills stop telling the model to record a coding handoff for work
  that is not coding.** A skill body rendered "Preferred harness for this
  skill: `coding-handling`" and an `omh runtime record --harness
  coding-handling` command whenever the catalog had never assigned that skill
  a harness, because the renderer read `primary_harness_for_skill`, whose
  fallback exists so that routing, validation, and the structure lint always
  get a harness that resolves. Nineteen skills reached it that way, among them
  `achievements`, `buzz`, `capability-toggle`, `live-incident-response`,
  `meta-router`, `running-work-board`, and `todo-checklist`. The line sits in
  always-loaded context, so every one of those sessions carried a coding
  instruction for a skill that reads badges or shows a checklist.

  A skill the catalog declares no harness for now renders neither the line nor
  the command. `omh runtime record` requires `--harness`, so the alternative
  to omitting both is naming a harness nobody chose; saying nothing is the one
  answer that cannot be wrong. The renderer reads `declared_primary_harness`,
  which reports the absence instead of hiding it, and the routing fallback is
  left where its consumers still need it.

  Five of the nineteen genuinely are coding skills and now say so in the
  catalog rather than inheriting it: `backend`, `frontend-refactor`,
  `maestro`, `native-debugging`, and `rust`. Each is filed under the
  `delegate_coding_and_ship` capability family and does work the
  `coding-handling` harness names for itself -- write, modify, debug,
  refactor. Their rendered bodies are byte-identical; what changed is that a
  value nobody declared became one someone did. Three more that the family
  also files under coding were left undeclared on purpose, because a second
  harness competes for each and the catalog does not say which wins:
  `application-threat-model`, `llm-app-dev`, and `tech-debt-audit`.

  The always-loaded skill-body budget falls from 979,758 to 977,649
  characters.

- **A long line in a diff no longer makes every short line pay for it.** The
  full-width diff band pads painted `+`/`-` lines with trailing spaces out to
  the block's widest line, and that padded string is the tool result, so the
  spaces are read by the model as well as painted on screen. `MAX_BAND_CELLS`
  caps the band at 160 cells, but under the cap the widest line still sets it
  for everything else. A 3,310-char patch result with 118 short lines and one
  152-cell line became 18,682 chars, 5.6 times its own size, in whitespace.

  Padding is now bounded by `MAX_BAND_PADDING_RATIO`: it may not exceed the
  diff's own length in characters, so the transform can never more than double
  what it is handed. Over the budget the band steps down to the widest painted
  line whose padding fits, and the lines above it keep the unpadded right edge
  the cap already leaves on an outlier. The band only ever lands on a width
  some line actually has, because a band between two of them covers no line
  the lower one misses -- which is why the case above recovers to 3,562 chars,
  1.08x, rather than merely stopping at the budget.

  The band is a cell width, since that is what makes the rectangle uniform on
  screen, but the budget is characters, since that is what the result costs.
  Padding is spaces, one character and one cell each, so the spend is the same
  number in either unit; only the diff it is measured against differs, and a
  double-width line is two cells per character. A cell-denominated budget
  would therefore bound nothing the result is billed in: a CJK-heavy diff
  reaches 2.28x in characters under one.

  Diffs whose padding already fits the budget are untouched, byte for byte.
  Across 1,853 per-file diffs from this repository's last 300 commits, 1,531
  render identically and 322 lose padding, for 2.27 million fewer characters
  of trailing space in total. None loses its band entirely.

- **Seven skills gain the mechanism they only gestured at, for the cost of one
  line each.** `verification-gate` named which commands count as evidence and
  never mapped requirement to task to evidence. `deep-interview` asked one
  question at a time with no taxonomy to prioritise against and nowhere to
  write the answers. `ultrawork` split work into disjoint lanes and shipped no
  file-ownership manifest, the artifact that stops two lanes editing one file.
  `code-review` ran a single bug-first pass. `todo-checklist` tracked work and
  could not review whether requirements were fit to build from. `ai-slop-cleaner`
  was deletion-first for code and carried nothing for prose. `plan` had no place
  to put a rule that is not up for renegotiation.

  Each now carries a reference file with the procedure: stable `FR-###`/`SC-###`
  ids and a requirement-to-task-to-evidence map with a metrics block; a ten-category
  ambiguity taxonomy scored Clear/Partial/Missing with a five-question cap and a
  write-back target; a stream manifest with explicit file lists, a named owner for
  each shared interface, and a four-step overlap ladder whose last rung is that two
  streams never edit one file concurrently; five review lenses run as separate
  passes, including a verification-gap lens that asks whether anything would go red
  if the changed behaviour broke; a requirements-quality checklist whose generator
  may not tick its own boxes; a prose lexicon whose word tiers keep a wordiness fix
  from reading as an authorship accusation; and a project constitution where a
  conflict with a MUST principle is resolved by changing the plan.

  Reference files are measured outside `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT`, so
  the always-loaded cost is seven pointer lines: 978,380 to 979,758 characters,
  against a pre-retirement level of 992,659. The `ultrawork` pointer is the
  terse one deliberately -- that body had 89 bytes of headroom under the
  per-skill ceiling, and shortening a pointer was cheaper than raising a second
  ratchet.

  Every mechanism is reconstructed in OMH's own vocabulary from a studied
  upstream, each registered in `docs/SKILL-SOURCES.md` with the commit read and
  its closure receipt: github/spec-kit, automazeio/ccpm, wshobson/agents, and
  bmad-code-org/BMAD-METHOD, all MIT. Nothing here needs a model judge inside
  OMH, a network index, or ownership of the working tree; a coverage map is
  something a model fills and a person or CI checks, never evidence by itself.
- **What keeping a plan costs: one item per write, and a shorter block per
  turn.** Two costs measured against the real hooks. Ticking one item cost a
  whole-list write: `action=set` was `omh_todo`'s only write, so a ten-step
  plan paid one declaration plus ten re-sends of every item's text, state and
  phase, about 1.5 KB of arguments per advance and one chance per advance to
  drop or reword an item nobody meant to touch. And the per-turn plan block
  restated the drive in full on every turn for the life of a plan; a
  one-character message in the owner's own history carried 854 characters of
  it.

  `action=advance` changes one item's state: the item number, the start of
  that item's current text as a guard, and the new state, with
  `blocked_reason` riding along and `deferred_reason` behaving exactly as it
  does on a `set`. The reference is an index plus a guard rather than an id,
  because the record has no item id and needs none for anything else, and
  because what a bare index cannot do is refuse when the list moved
  underneath it -- a guard that no longer describes the text at that position
  is refused rather than applied. Out-of-range, a finished plan, an absent
  record, a bad state and a guard mismatch are each refused with the field
  named, and a refused call leaves the record byte-identical.

  It is the same write by a narrower route, and that is a test rather than a
  claim: a plan walked entirely through `advance` produces a record byte-equal
  to the same plan walked through `set`, under a fixed clock. There is one
  validator, one stamp and one schema, because the new path rebuilds the item
  list and hands it to `build_todo_record` like every other write. Every
  reader of "the plan changed" -- the reconciliation turn budget, the HUD's
  unchanged duration, the turn-end nudge budget -- sees it as it sees a `set`.
  The read-modify-write this introduced is serialized by a per-record lock
  that `set` now takes too, so a whole-list write can no longer be overwritten
  by a list read before it. It is the bundle's existing two-backend lock, the
  one `tool_bursts`, `approval_bypass` and `memory_open_reminders` already
  take, with the wait it allows made a parameter rather than a constant: that
  lock's own default is sized for telemetry that would rather drop a counter
  than delay a turn, and a plan write is the opposite trade. A copy here
  would have been the bundle's third, which is the shape that let a Windows
  host once take no lock at all while reading as though it had one.

  That is a new way for `set` to fail, and it did not have one before: it
  wrote through `os.replace` and took no lock. A writer that waits more than
  two seconds for the record is refused with `"status": "contended"` and an
  error naming the record, saying the write did not happen and to send the
  same call again. It is not `invalid_todo`, and the separate status is the
  point: a writer told its payload was invalid rewrites the list it just
  sent, which is the whole-list rewrite this change exists to stop, while the
  right response to a busy record is the identical call. The record is
  untouched either way, `TodoContendedError` subclasses `TodoStoreError` so
  every caller written before the lock still catches it, and `omh runtime
  todo set` reports the same status and still exits 1. Nothing counts or
  surfaces refusals: no reader has anywhere to put one.

  The block was then measured sentence by sentence for what each one does, and
  three places said one thing twice: the drive's premise and its imperative
  were two sentences for one ask, its stop criterion re-stated "an answer does
  not discharge the turn" one clause after the drive said it, the stall
  framing ended with the drive repeated, and "either finish the remaining
  items or say which stay open and why" is what the drive already asks, so it
  moved to the budgeted half of the reconciliation rule. Nothing was deleted
  from the full rule to move it. Per turn, driving `pre_llm_call` against a
  temp home: the drive variant falls from 694 to 654 characters on the turns
  that carry the full rule and from 541 to 435 after, the stalled variant from
  887 to 807 and from 734 to 588, and a 40-turn session with one plan pays
  18,057 characters instead of 22,099 on the drive variant and 24,177 instead
  of 29,819 on the stalled one. The answer-first and deferred rules were
  measured and left alone; the reasons are recorded beside them. What may not
  be shortened away is pinned per variant and past the budget: the drive
  clause and its stop criterion where the plan drives, the message ordering
  and the record-first way back where it does not.

- **OMH no longer routes on rows no person wrote.** Hermes opens turns for
  rows it writes itself -- a background process finishing, an async
  delegation batch, a model switch -- and each arrives as a `role="user"` row
  carrying real text. OMH's awareness rail and route hint read that text as a
  request. Measured in the owner's `state.db`: 282 of 1,869 user rows are
  host-synthesized, 259 of them `async_delegation_complete`, and 272 of the
  282 match the awareness vocabulary. One background-process notice drew
  `intent=meta_discussion; selected=workflow-learning` with 3,297 characters
  of routing behind it.

  On a turn the host opened for itself there is no request, so `pre_llm_call`
  now derives one value -- the message read AS a request -- and gives every
  routing surface absence on such a turn: no `[OMH Route Hint]`, no awareness
  vocabulary match, no structured route hint in the context brief, and the
  per-fingerprint claim ledger is not spent. That last one is the tail of the
  bug rather than its bulk: the ledger holds one route per session, so a
  claim spent on a notice silences the same hint later, when a person
  actually asks for it.

  The discriminator is `display_kind`, the record field Hermes stamps when
  the row is written, and never wording. `steer` is input typed for the
  renderer and routes exactly as an untyped row does; an absent or unreadable
  row keeps today's behaviour, because a plugin that cannot tell who wrote
  must not start claiming the host did. Measured on a completion-notice turn
  by driving the real hook: 3,484 characters before and 798 after for a
  `process_complete` notice, 3,852 before and 798 after for an async
  delegation batch. The identical text on an untyped row is unchanged at
  3,656 and 4,024.

  What is deliberately untouched is everything that reads the turn as an
  event rather than a request -- the plan drive, the dispatch outcome lines,
  the active-workflow line, the role marker -- because a completion notice is
  exactly the turn on which those matter. The first-turn primer is unchanged
  too, including when the opening row is a notice: Hermes computes
  `is_first_turn` as "no prior history", so withholding the primer there
  would drop it for the whole session rather than defer it, and the host
  replays it in `api_content` for the person's later turns anyway.

  The predicate #1739 introduced moved from `todo_reconciliation` to a
  neutral `turn_authorship` module, since a routing surface importing "who
  opened this turn" from the plan-checklist module reads wrong. The old
  import surface is re-exported unchanged.

- **A turn that starts remote work and arms nothing is told so, before it
  ends.** A Hermes session cannot wake itself: exactly two things start a
  turn, a person's message and the host's background-process completion
  notice. So "waiting for CI" is a real wait only when the turn armed a
  background process that exits when CI does. Measured on the reporter's own
  session history, of 48 turn endings that mentioned CI or a deploy and a
  wait, one had armed a waiter and was woken by it; the longest idle gap was
  168 minutes.

  A `terminal` call whose command starts work on a remote now gets a directive
  on its own result when nothing is armed. It names two honest exits and picks
  neither: arm the wait as a background process with `notify_on_complete=true`
  so Hermes delivers the completion notice and resumes the session, or tell
  the person plainly that this session has stopped and what they need to come
  back for. It says not to poll in the foreground, because OMH's repeat-call
  guard escalates a foreground poll to a human gate. A second sentence covers
  the other stall in the report: a command held at the human approval gate did
  not run, and a session cannot approve on anyone's behalf.

  Neither trigger reads the model's prose. "This turn started remote work" is
  the command the model passed to a tool with a schema, matched line by line
  on executable plus subcommand tokens after a shell-aware split, so a
  multi-line script counts while `git push --help`, `echo git push` and a
  heredoc body carrying the words are all misses. "Nothing is armed" is two
  host records: `processes.json` for liveness, since it carries only live
  processes and names each one's spawning session, and the background spawn's
  own tool result for whether a live process will notify at all. It takes two
  because Hermes writes the process checkpoint during the spawn and sets the
  notification fields afterwards, so the most recently armed process is
  always recorded without them. Anything the two cannot settle answers
  "unknown" and the directive stays silent: this may decline to speak, but it
  must never tell a session that armed something that it did not. A delegated
  child is never nudged, because it does not report to "the person" and the
  host says its watcher would not reach its parent.

  It is deliberately small and deliberately conditional, because it lands on
  very nearly every successful push: at the moment a push returns, a session
  has almost never armed anything yet. So the obligation is phrased as "if
  this turn will wait on that work", and a session observed arming a
  notifying background process, from its own tool arguments or from the
  process record, stops being reminded how. The directive is 436 characters
  and the approval sentence 233.

  The issue proposed acting in `pre_verify`, and that hook cannot reach the
  turn that matters. Hermes gates it on the turn having changed files and
  feeds that set from `write_file` and `patch` only, so a turn that pushes and
  opens a pull request has changed nothing and never reaches it. The directive
  rides `transform_tool_result` instead, which fires for every tool and lands
  while the model is still inside the turn loop, so both exits are reachable.
  At most one directive per turn per cause, latched on the host's own turn id.

- **The branded TUI collapses the transcript, and doctor names what bounds a
  runaway loop.** Two halves of the same question: whether a person can see a
  run going wrong.

  Hermes renders every tool call and every thinking block expanded. On a long
  run each call becomes its own row, the prompt scrolls out of sight, and the
  transcript is a wall. OMH's branded-TUI choice already set two display keys
  under one default-Yes confirmation, and `display.sections` now rides the
  same consent: `thinking`, `tools` and `subagents` collapsed, under the same
  rules as the other two. Only from the confirmation or `--yes`, never on a
  noncanonical YAML shape, and `--dry-run` never persists. Narrower than the
  other two in one way: every section key is unset-only, so an explicit
  `display.sections.tools: expanded` survives while the other two are still
  added. `collapsed` is not `hidden` -- counts stay visible and a click
  expands. The prompt's trigger is unchanged, so an install already branded
  before this existed takes the third key through `--yes` rather than being
  re-asked. What setup wrote is recorded in the apply result, so
  `omh uninstall` can reverse it later without guessing which values were the
  person's own.

  `omh doctor` gains two advisories in the read-only lane, which reports and
  never rewrites. The first names `agent.max_turns` when it is at or above
  200, the point where the turn budget rather than the host's loop detector
  is what a repeat loop runs into. It fires on Hermes' own default of 500,
  and says so, because the measured loop reached 409 tool calls under exactly
  that value. The second names `tool_loop_guardrails.hard_stop_enabled` when
  it is false or unset, which is the host default on an attended platform: in
  that state Hermes' loop detector only appends a note, and the model ignored
  185 of them in the measured session. Turning it on halts the turn at
  `no_progress_block_after`. OMH changes neither key.

- **`omh doctor` stops warning about work nobody can do, and starts seeing
  the tool-call hot path.** Two truthfulness defects on the same surface.

  The memory-consolidation warning could never clear. When Hermes' memory pack
  is over its headroom floor and nothing in it is provably redundant --
  measured on the owner machine at 14 entries, 67 chars of headroom against a
  floor of 300, `reclaimable_chars: 0`, no duplicate clusters -- the planner
  has nothing to propose and OMH cannot write Hermes memory by design. Doctor
  still said consolidation was "due" on every run, and a standing warning is
  how people learn to skip doctor. That state now reports what it is: the pack
  is full, nothing can be reclaimed automatically, and the move that does
  exist is shortening or removing an entry through Hermes' own memory tool. It
  no longer counts as a warning. A brief with a duplicate cluster keeps
  today's wording and today's severity, because there is a consolidation to
  run.

  Doctor could not see the tool-call hot path at all. A `toolcall-rules.json`
  is how somebody tells OMH to block a tool call, and the enforcing hook fails
  open: a wrong `schema_version` refuses the WHOLE document, a bad regex drops
  one rule, and either way nothing is reported. Doctor now runs the same
  validator `omh ops toolcall-rules-validate` runs, against the store it
  already inspects, and names the file, the loaded and skipped counts, and the
  first error. No rules file stays silent -- the file's presence is the
  opt-in. Doctor also reads the plugin host observation journal it already has
  and names a hook whose recorded calls did not come back observed.

  Inside `pre_tool_call`, the rule gate gained its own handler. A failure
  while evaluating somebody's rules used to escape to Hermes, which appends
  nothing, logs one WARNING and then DEBUG only -- so the person's blocks
  stopped running and nothing said so. The call is still allowed, which is the
  module's documented fail-open contract and avoids the #1674 shape where one
  broken state refuses every tool call in every session. What changes is that
  it is no longer silent: the failure is counted where doctor reads it, and
  doctor names the tool, the exception's type, and the fact that the call was
  allowed. The exception's message is deliberately not stored: it is free
  text from whatever raised, so it can quote the person's own rule pattern or
  a tool argument, and that ledger is metadata-only.

- **A delegation route now has a way back, so one lane's model stops being
  every later session's default.** `omh_delegate_route` writes
  `delegation.model` / `provider` / `reasoning_effort` into `config.yaml`
  because Hermes re-reads those keys per dispatch. Nothing put them back.
  Clearing was a sentence in the tool description rather than something the
  code did, so on the machine this was measured on, 28 of 32 recorded routes
  were never cleared and a route written for one lane two days earlier was
  what every delegation inherited -- including sessions that never called the
  tool.

  OMH now records, under the same lock as the route write, what the three
  keys held the first time it wrote over values it did not write. A key the
  file did not carry is recorded by being absent, so putting the baseline
  back removes the key rather than writing an empty string. The baseline is
  captured once and survives later routes; only a person's own edit between
  two routes re-captures it, because at that moment OMH is again writing over
  a value it did not write.

  A route is turn-local, and deliberately so. `on_session_end` is not a
  session boundary: Hermes fires it once per message from the turn
  finalizer. "Route the next dispatch" is a turn-local intent and a
  `delegate_task` is dispatched inside the turn that set the route. The
  recorded scope is the task rather than the turn because the host gives a
  plugin tool `task_id` but never `turn_id`.

  What a task is differs by flow, and both are ordinary. In TUI and CLI the
  host mints a fresh task per turn, so the scope is the turn; a restore that
  does not happen at its own turn end is then not retried until the next
  session start. On every gateway platform -- Slack, Discord, Telegram,
  Feishu, the API server -- `task_id` is the session id, so the scope is the
  session, a route survives later turns of it, and a missed restore is
  retried by the next turn end. That is the majority flow on the machine
  this was measured on.

  A recorded task decides on its own, without also requiring the session.
  That is what carries a restore through a compression split: the host
  reassigns the session id mid-turn when it splits a long transcript, and
  those long fan-out turns are the ones that route, while the task id is the
  same value at the tool and at the turn end on both sides of the split.

  Turn scope makes a leak short and bounded rather than impossible. A lock
  the turn end could not take within its budget leaves the route, as does a
  session killed mid-task; both then wait for the next session start and the
  liveness bound.

  Three paths put the previous values back: `action=clear`, the end of the
  task that wrote the route, and the start of a later session when the
  writing session is gone. Chain exhaustion restores the baseline instead of
  clearing. `action=fallback` legitimately runs a turn after the route was
  written, because a child that dies on HTTP 400 is reported later, so it
  now recovers its chain position from the route provenance record rather
  than from the live keys. Every restore is gated on the same recorded
  value, never on wording: OMH compares the file's current three keys with
  what it recorded writing, and a value someone else set is reported and
  left alone.

  The baseline is what the PERSON had, which is not the same as what the
  file holds. On the machine this issue came from the file already held a
  leaked OMH route, and capturing that as the baseline would have made the
  most expensive model in the chain a permanent restore target. Every route
  OMH writes is already recorded in `route-provenance.json`, so a candidate
  baseline that exactly matches the newest such record is recognised as
  OMH's own leftover and recorded as "keys absent" instead, with
  `baseline_origin` saying which of the two it was. Two consequences are
  stated rather than glossed: a person who pins by hand exactly the model,
  provider and effort OMH last wrote is indistinguishable from that leftover
  and their pin will not come back, and when provenance is missing or
  unreadable the check cannot run at all, which is reported as its own note
  instead of quietly falling back. The record also names the `config.yaml`
  it describes, because two Hermes profiles may share one OMH home and a
  record that named no file let one profile act on the other's route.

  The same provenance comparison now guards two more places. `action=fallback`
  reads the live keys as its chain position only when OMH can prove it wrote
  them, because after a turn-end restore those keys hold the person's own
  pinned model: reading that as the position made one failed lane report a
  whole exhausted chain, skip the candidate that would have worked, and then
  delete the pin. And the clear at the end of an exhausted chain will not
  remove a value OMH cannot prove it wrote.

  What comes back is the previous VALUES, not the previous bytes: the writer
  normalises quoting, emits the three keys in a fixed order, and drops an
  inline comment sitting on one of those lines. Every other byte is
  untouched.

  The session-start path exists because a session killed mid-task never
  reaches the turn end. It restores only a route whose recorded writer is not a
  live session, asked of that writer's own `state.db` row -- not of the
  live-TUI list, which is scoped to "which session is a person looking at"
  and so omits every writer on another surface by construction. Most writers
  are on another surface: on the owner's routing profile every route comes
  from a `slack` or `subagent` session, and the default home already has
  `desktop` routes beside its TUI ones.

  Only a row the host closed is an observation that the writer is gone. A row
  the host never closed -- what a killed TUI and most gateway sessions leave
  behind -- is not, so the route's own age decides instead, bounded at six
  hours. Each verdict is named so a reader can tell an observation from a
  bound. The cost is stated: a route left by a killed session can outlive it
  by up to six hours. That is the accepted side of the trade, because
  restoring under a live writer sends that writer's next child to the wrong
  model. Nothing available shortens it -- the host's lease registry records
  which surfaces are open, not whether their processes are alive. Turn scope
  makes it a narrow path: it now covers only a session killed mid-task.

  OMH registers `on_session_start` for this; it is the host's own first-turn
  lifecycle callback, bounded and fail-open.

  The turn-end restore is on the hot path of every turn of every session,
  including each delegated child's, so the case with nothing to restore
  costs one `stat` with no lock and no database read.

  Two sessions routing at once is ordinary on one machine, so the whole
  read-through-replace is inside the plugin's existing file lock. A writer
  that cannot take it returns a refusal the tool surfaces and never reports
  `routed`. The interleave that motivated the recorded writer -- A routes, B
  routes over it, A ends -- leaves B's route in place and B's session end
  restores the user's own baseline.

  A machine that already carries a route written before this change has no
  baseline record. OMH cannot know what those keys held, so the automatic
  paths report `no_baseline_recorded` and change nothing. An explicit
  `action=clear` still removes the keys, which is what it did before and the
  only way to settle a route nothing recorded.

- **`omh --resume <id>` works, and the terminal now names the `omh` way
  back.** Bare `omh` is documented as the same door as `hermes`, but the door
  opened one way only: the parser rejected `omh --resume <id>` as an invalid
  choice, and the one resume hint on screen when the TUI exited named the
  other binary, `hermes --tui --resume <id>`. Someone who came in through
  `omh` was told to come back through `hermes`.

  Three Hermes session flags now pass through on the bare launch --
  `-r/--resume`, `-c/--continue` and `-p/--profile` -- each value forwarded as
  its own argv element, in one fixed order, with nothing else added. No
  top-level OMH option claimed those short forms, so they carry over
  unchanged. Which terminal opens is still Hermes' `display.interface`
  decision: the launch has never forced `--tui` and still does not. Combining
  one of the three with a subcommand is an error that names the flag, because
  a dropped `-p` would run that subcommand against a profile the person
  believes they selected.

  After a clean exit, OMH prints one copyable line, `omh --resume <id>`, or
  `omh -p <profile> --resume <id>` when a profile was passed, since a profile
  has its own `state.db`. Hermes' own epilogue still prints first; suppressing
  it would mean capturing the child's stdout, which would break the TUI.

  OMH cannot read the id Hermes used -- Hermes creates its active-session file
  with `mkstemp` and unlinks it before returning -- so the id comes from the
  state database the TUI just wrote to. The TUI gateway stamps
  `sessions.ended_at` as the child exits when it owns the session's lifecycle,
  and the launch knows when its child started and stopped. Only the id and the
  columns that choose it are read: no title, no message content, no cwd, and
  cwd is not a filter either, because `hermes --resume` restores the session's
  own directory.

  The whole contract is when it declines, since this runs after the session
  has already ended and a wrong id is worse than no line. Nothing is printed
  when no TUI session ended inside the child's window, when the newest one did
  not end close to the child's exit, when a second session ended within the
  same tolerance (two terminals closing together), when the session holds no
  messages, when the database is missing, locked, corrupt or foreign, or on
  any exit code other than 0 and 130. A gateway-owned session is never ended
  by the TUI, so it produces no candidate and no line, which is the right
  outcome rather than a gap.
- **Three skills that were strict subsets of a stronger sibling now retire
  into it, and the always-loaded budget ratchets down instead of up.**
  `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` sat at exactly its own limit, so every
  new skill and every strengthened body needed a raise before it could land.
  Three of the installed skills were doing a job their sibling already did
  and more: `performance-goal` produced the same outputs as `ultraperf` minus
  the baseline record, the ranked hypotheses and the regression gate;
  `best-practice-research` answered the same question as `web-research` with
  three untyped outputs instead of two named schemas; and `autoresearch-goal`
  was a validator-gated wrapper around what `research` already does with a
  reference and six schemas. Each pair cost two always-loaded bodies for one
  job.

  The three are retired, not deleted, using the shape the four folded ULW
  engines already use: the contract stays in the catalog as a workflow
  reference, the body stops rendering, a stale label or tap path fails with a
  named migration error pointing at the target home, doctor reports a
  leftover install, and rollback is a one-row edit. What differs is where the
  intent went. An engine retired into a capability inside `ulw-work`; these
  retire into a whole sibling skill, so the migration error names the target
  home rather than a capability id, and the cue vocabulary folds into the
  target's own trigger table instead of routing through the engine alias
  resolver. That resolver returns an unconditional high-confidence dispatch
  on a contained cue, which is right for a distinctive engine name and wrong
  for a bare word like `benchmark`; folded triggers compete in ordinary
  scoring instead.

  Nothing anyone types stops working. Every trigger of the three still
  dispatches, now to the target home, and the two bare metric nouns another
  workflow already owned (`latency` to the observability card, `throughput`
  to the agent ops review) keep that owner. The negative-control corpus still
  reports zero over-routes with three new controls added for the everyday
  words the fold moved.

  The budget is ratcheted DOWN to the new measured value: the full-profile
  skill body from 992,659 to 978,380 characters, the full capability section
  from 430,308 to 422,526, and the standalone capability section from 120,089
  to 117,254. Installable skills go from 127 to 124.

- **OMH's per-turn context now arrives fenced, and stops over-asserting.**
  Hermes concatenates whatever `pre_llm_call` returns onto the API copy of the
  USER message (`compose_user_api_content`, `agent/turn_context.py`) with no
  role separation and no marker, so up to 6,678 characters of OMH imperatives
  were delivered as a continuation of what the person wrote. Hermes already
  fences its own memory channel for exactly this reason; OMH now does the
  same. Everything it injects goes inside `<omh-context>`, behind a note
  saying the block is automated OMH context rather than the person's words and
  that their message outranks it -- including the dispatch outcome lines and
  the running-work rows, which carry no `[OMH ...]` head of their own and so
  could never have been covered by a per-producer convention. A turn OMH has
  nothing to say on still injects exactly zero characters.

  The fence is sanitized, not merely wrapped. Most of what goes inside is text
  OMH did not author -- todo item text the model wrote, dispatch refs,
  workflow and lane names, role markdown, route-hint fields derived from the
  person's own message -- and a part carrying `</omh-context>` would close the
  fence early and hand everything after it to the model as the person's words
  again, reachable by whatever writes a todo item. Any `omh-context` tag is
  removed from the body first, matching the tolerance of the host's own
  `sanitize_context` (either tag, any case, whitespace inside the brackets).
  Stripped rather than escaped, because nothing un-escapes it and Hermes
  replays this turn's injection verbatim on every later turn. Removals are
  tallied in process for diagnostics; they are not a call failure, so they do
  not enter the degradation lane, whose claim boundary would then be false.

  Six rules that over-asserted were rewritten with it. `TODO_ANSWER_FIRST_RULE`
  now offers the record before the resume ("either record an omh_todo
  `deferred_reason`, if they steered the work elsewhere, or resume the plan"),
  because the gate that selects it is presence-only by design, so "stop,
  forget the plan" and "carry on" reach the identical sentence and resume-first
  made arguing the default reply to someone who had just said stop. Both
  options and the stop criterion are unchanged. On a turn that variant is
  selected the dispatch block is introduced as coming after the answer and the
  continuation-claim finding is held back entirely, so one obligation claims
  the turn instead of three. That finding no longer says "announced a
  continuation but nothing resumed ... A promise to continue is not a
  continuation" -- a verdict it delivered on ordinary narration like
  "continuing to read the router tests" -- and instead names the records that
  hold, with the count, and asks for the next step or a plain statement that
  the work is stopped and why. The delegation nudge stops saying "keep working
  while it runs", which was wrong about both tools it names: measured on
  hermes-agent 0.21.3, `omh_delegate_route` writes routing keys for the next
  dispatch and runs nothing, while `delegate_task` is always backgrounded for
  a top-level model call and the host's own schema says never to wait or poll
  on it. And the answer-first rule now needs a person, not merely a message.
  Hermes opens turns with rows it writes itself -- a background process
  finishing, an async delegation batch, a model switch, a crash-recovery note
  -- each a `role="user"` row carrying real text, so presence alone read them
  as somebody writing and the model was told to answer a person who did not
  exist. Measured in the owner's store: 282 of 1,869 user rows. The
  discriminator is the row's `display_kind`, which Hermes stamps at turn start
  and already uses for the same question in `split_user_originated_turn` and
  in the /rewind and /undo listing; absent or `steer` is a person, anything
  else is the host. A record field, never wording.

  And the plan line gains the off-switch every other injection already had.
  Code-mode latches once per session, engagement nudges cap at two, the board
  card claims once, the route hint claims per fingerprint, the repeat streak
  expires, dispatch outcomes age out; the 357-character reconciliation rule
  fired on every turn for as long as a plan existed. It now spends a
  three-turn budget per plan record and drops to its first clause after that,
  returning in full on every write to the record -- which is when a completion
  claim is most likely, since the model has just marked something done. Both
  inputs are records: the plan's own `updated_at` and a per-session turn count
  beside the other bounded maps in `hooks/nudge_budget`. A caller that is not
  a turn renders the rule whole and records nothing.

  Measured over 40 turns with one open plan, by driving the real hook rather
  than multiplying one turn: 29,259 characters before against 28,358 after
  when nothing writes the plan, and 62,229 against 57,491 on a session also
  carrying two unacknowledged dispatches. The fence costs 119 characters on
  every turn that injects anything and the budget returns 153 once it spends,
  so a session whose plan is written every other turn never reaches the saving
  and pays the fence in full -- 34,019 against 29,259. That trade is stated
  rather than tuned away: the marker is the fix for the root cause and its
  cost is per-turn by construction, because a fence explained only on the
  first turn would survive until a compaction dropped that turn.

  The decay is a small part of that plan block, not most of it: the block runs
  about 850 characters on a one-character message and the three-turn budget
  returns 153 of them. The rest is the drive wording, which this change leaves
  alone deliberately. Refs #1730, which stays open for that remainder and for
  the `omh_todo` single-item update.

  Nothing here claims to change what a model does. Every figure is a
  measurement of what the model is TOLD.

- **A question asked mid-plan is now answered before the plan resumes.**
  While an `omh_todo` plan has open items, every turn's context carried
  `TODO_CONTINUATION_RULE`, whose stop criterion ends "not when a turn has
  produced an answer". On a turn someone opened with a message that is the
  wrong sentence: it tells the model that answering does not discharge the
  turn, so the ask gets a cursory agreement and the session returns to its own
  next item. The observed run agreed that something "could be a model-level
  issue" having checked nothing, pivoted to "how shall we proceed?", and when
  challenged offered to fact-check if it were asked a second time.

  The per-turn line now reads one structural fact about the turn -- whether an
  inbound message opened it -- and carries `TODO_ANSWER_FIRST_RULE` in place
  of the drive when one did: answer it completely in this turn, investigate
  rather than defer, never agree with a claim you have not checked, then
  either record a `deferred_reason` or resume the plan (the entry above
  reorders those two branches, which shipped the other way round here).
  The drive is reordered, not dropped, which is what keeps this inside the
  stop-criterion contract rather than back at an observe-only reminder.

  That fact is an identity, not an interpretation. Hermes invokes
  `pre_llm_call` exactly once per turn, from `build_turn_context`, with the
  message that started it, and a turn the session drove onward by itself never
  re-enters that hook at all -- the host appends the `pre_verify` directive as
  a synthetic user-role row and re-enters the same turn loop. Nothing OMH
  wrote can arrive as this message, so presence is the whole test: two
  messages that mean opposite things produce the identical line, a blank or
  non-string message is absence, a host-labelled tracker event is an event and
  not someone writing, and a host that passes no message renders what it
  rendered before, byte for byte.

  Precedence is pinned alongside it. A recorded `deferred_reason` still wins
  over the message, being the more specific statement and the one that names
  what was asked for instead; a blocked next item still vetoes the deferral;
  and the stall observation goes with the drive, since "if nothing is blocking
  it, move it" would re-add in the same breath the ask this branch removes.
  The turn-end directive is unchanged and deliberately ungated: it fires after
  the answer it is handed as `final_response` exists, which is the moment the
  new rule itself asks the plan to resume, and Hermes passes it no message it
  could gate on.

- **The rule that keeps a retracted failure from outranking a live
  cancellation is now held by a test.** Runtime recap ranks the two terminal
  event groups by severity rather than arrival, so a `cancelled` appended
  after a `failed` does not erase the failure. That much was pinned. The case
  that keeps severity honest was not: a failure since retracted -- a second
  `failed` record written `not_observed` -- must yield to a live cancellation.
  The code gets this right only because per-type selection runs before the
  severity comparison, and nothing recorded that the two rules compose in one
  order and not the other. A change that compared the groups first, or that
  read `not_observed` as an absent record rather than a record, would have
  flipped it with every existing case green (#1554).

- **A Windows diagnostic-owner test no longer lets tempdir teardown replace
  the verdict it exists to report.** In
  `tests/test_local_diagnostic_process_cleanup.py`, both tests asserted their
  outcome after their `TemporaryDirectory` block had already closed, so a
  `PermissionError` from a still-exiting child holding the directory open
  came back as the whole failure and hid whether cleanup actually verified
  (#1644). Both tests now assert inside the `with` block, and
  `WindowsJobObjectOwner` records which of its two waits did not resolve --
  the Job Object never reporting empty, or the process handle not reporting
  exit once it did -- on a new `termination_diagnostic` attribute the test
  surfaces in its failure message, with no change to what `terminate()`
  returns. Separately, `_await_empty_job`'s 1.0s deadline was a correctness
  bound sized like a performance budget on a shared runner, the same class of
  defect as #1599/#1604; it is now its own named constant,
  `_JOB_EMPTY_DEADLINE_SECONDS = 30`. The Windows path itself is unverified
  from this change -- macOS cannot reach `WindowsJobObjectOwner` at all.

- **`omh ops plugin-risk-audit` can now bind its hook classification to the
  Hermes you would enable the plugin on.** The hook-semantics mapping is pinned
  to one host revision and the audit published that range, but it had no input
  or result field for the host an operator is actually running. A plugin on a
  newer or older Hermes still came back `classification_status: classified`,
  and the public documentation told the reader to compare the two versions by
  hand — so the one safety condition the audit describes sat outside the
  machine-readable verdict (#1597).

  `--hermes-version <x.y.z>` states the host; `--hermes-install <dir>` names
  one local installation and reads the `__version__` its version module
  declares. The two are mutually exclusive, so nothing ranks one host claim
  over another, and neither is inferred: the plugin's own `requires_hermes`
  says what the package asks for and is never read as an observation of an
  environment. Reading an installation goes through the bounded seam the TUI
  preflight already used, now shared rather than copied. It is a file read —
  Hermes is not imported, its binary is not run, no subprocess is spawned, no
  socket is opened, and no installation is discovered by scanning.

  `declared_hooks.host_contract.inspected_host` reports the version that was
  established, the method it came from, and one of four compatibilities.
  `incompatible` and `unreadable` hold the verdict at
  `classification_status: unknown` and put `undetermined_hook_contract` in
  `summary.risk_categories`, so a mapping that was never read against your host
  cannot render as an established contract. `not_observed` is the default when
  no host is named and is not a pass: the audit says so in a diagnostic
  whenever the plugin declares hooks. An explicit request that yielded nothing
  stays distinguishable from never having asked, because the method names the
  source that was selected either way.

  The three claims stay apart. A manifest that parsed cleanly keeps its
  `declaration_status`, its per-hook rows and its effects while the overall
  decision is held, and the declared range and the inspected host are separate
  fields that are tested not to substitute for one another. No operator path,
  installation path, or version string that failed to parse reaches the result.
  `hermes_host_execution` and `hermes_plugin_admission` join `not_observed`,
  because a compatible mapping is static pre-enable evidence and never proof
  that the host would admit, load, register or run the plugin.

- **`omh ops plugin-risk-audit` now says whether a plugin can replace its own
  installed code.** The audit reported dependencies, dynamic execution, hook
  capability, network requests, committed secrets and process execution as six
  independent categories, so an operator saw ordinary network and process
  findings without being told the package may also carry a second
  software-update authority beside the host's pinned plugin update path, with
  different pinning, rollback, consent and review guarantees (#1546).

  The result now carries a `self_update` block composed from signals the scan
  already collects rather than a parallel scanner: the file's own
  `network_request` category supplies retrieval, a write, copy, rename or
  replace call beside a code or manifest target name supplies replacement, and
  an archive unpacked or a self-directed upgrade command in a file that also
  spawns a process supply the remaining legs. Three named compositions classify
  `detected` and the matched one is reported, so the result says which signals
  produced the verdict. Neither ordinary leg passes alone, which is why an API
  client writing a cache file and a code generator with no network do not
  compose it. Retrieval beside dynamic execution is `needs_review`, because
  retrieved bytes can become code without a write to settle it either way. Both
  verdicts reach `summary.risk_categories`, as `self_update_or_code_replacement`
  and `undetermined_self_update_path`, so a wrapper reading only the summary
  cannot see a package with an unsettled replacement path as a clean one.
  Integrity verification is recorded under `mitigating_signals` and never turns
  a finding into a safe verdict.

  The scan stays what it was: bounded static text from one explicitly named
  local directory, with import, registration, execution, dependency
  installation and network access still `not_observed`, joined now by
  `plugin_code_replacement` and `plugin_self_update_execution`. No file name,
  remote target or matched source reaches the result; `signal_file_counts` is
  the bounded stand-in, because a file name is plugin-authored text. Absence is
  reported as absence of a match rather than absence of risk, in the block's own
  diagnostics and in the claim boundary. `docs/PLUGIN-SELF-UPDATE-AUDIT.md` is
  the public account of the signals, the compositions, the three states, and the
  two shapes worth knowing before acting on a result.

- **A plan item that records why it cannot proceed now says so on the
  checklist.** `blocked_reason` had one consumer, the turn-end continuation
  directive, which reads it and stops nudging. Nothing rendered it, so the
  person watching the TUI saw the item sitting in `active` with no sign it was
  waiting on anything -- which reads as stuck, the exact reading the stall
  finding exists to prevent (#1553). Both row-rendering surfaces now carry the
  reason: the text HUD line appends `(waiting: <reason>)`, and the TUI plan
  panel adds the same clause in its warn tone, ahead of the `(unchanged …)`
  hint on a row that carries both, because the reason is what explains the
  age. It renders on whatever row holds the field rather than on a chosen item
  state.

  The store's 200-character cap is not a row width, so each surface cuts the
  reason at 48 characters, the ellipsis included, and the panel gives back
  exactly the width the clause needs from the item text so that a long text
  cannot push the clause off the row. Truncation stays a render concern: the
  stop criterion and the projected `blocked_reason` field are untouched, and a
  recorded reason remains a declaration -- never evidence that something is
  actually blocking.

- **A coding CLI installed under a sensitive directory no longer dispatches
  without a write fence.** Fanout screened its sandbox read roots with
  `read_roots_are_safe`, while every fanout spawn passes
  `allow_broad_file_read=True`, which makes both backends ignore those roots
  for reads. The screen could therefore narrow nothing, and its one remaining
  effect was to answer a sensitive read root by leaving the run unconfined: an
  owner CLI at `~/.claude/local/claude`, a standard Claude Code install
  location, put `.claude` into a read root and the dispatch lost its write
  fence while still reading the whole host tree. The more sensitive the
  executable's location, the less confined the run (#1602).

  The fanout lane no longer runs that screen, with the reason recorded at the
  code, and its confinement receipt now says outright that reads are not part
  of the boundary it attests, so the record still states what was and was not
  confined. The strict cross-harness-adapter lane, where the same screen does
  narrow reads, is unchanged and still refuses an unsafe read root; the
  `~/.claude/local` shape is pinned there as a refusal. The fanout
  data-boundary row no longer names `read_roots_are_safe` as an enforcer,
  which moves the safety-profile revision.

- **A tool call the model has already made four times in a row is now
  refused, not just warned about.** A Hermes session searching a repo called
  `search_files` with one identical pattern more than 180 times in a row,
  identical arguments every time, each returning in ~0.0s. The tool itself
  printed `BLOCKED: You have run this exact search N times in a row` into the
  result, and the model read that and issued the same call again. The session
  burned its budget and never started the work it was asked to do. A warning
  inside a tool result is advice; the loop ends only when something refuses.

- **A tool call a session keeps repeating is now refused, and then put to
  the person.** Measured session 20260919_140745_db409e, 409 tool calls and
  2.12M input tokens: 203 `search_files` calls with identical arguments, 185
  of them refused by Hermes' own guard with its counter escalating past 99,
  and the model issued the same call again every time. The same session then
  repeated one `read_file` region 100+ times against the host's second guard.
  The session burned its budget and never started the work it was asked to
  do. So the loop is not a search quirk, and a refusal message is something
  this model demonstrably reads and ignores.

  `pre_tool_call` now counts consecutive identical calls per session, keyed by
  tool and by a digest of the arguments, and intervenes in two stages. Stage
  one, at the 8th identical call, returns a block directive whose message
  becomes the tool result. Stage two, after four of those blocks have been
  ignored, returns an approve directive instead, which Hermes routes to the
  same human-approval gate as a dangerous shell command; the host documents
  that gate as one the model cannot skip, and in a context with no human to
  ask it fails closed. The escalation carries an explicit
  `omh_repeat:<tool>:<digest>` rule key, so a person who answers "always" is
  answering about exactly that one call rather than about a key that changes
  with every prompt.

  Eight and twelve, not four, for two reasons. Hermes already refuses a
  repeated `search_files` at the 4th identical call, so a second refusal at
  that point is the same message in another voice; engaging four calls later
  engages on evidence the host's refusal did not produce, namely that it was
  ignored. The binding reason is the other one: an identical repeated call is
  not always a loop. Polling is the legitimate case, since `terminal` running
  `gh pr checks <n>` back to back while waiting on CI has byte-identical
  arguments every time, and OMH cannot tell it from a loop because the digest
  covers arguments and this code never sees a result. So the ladder leaves
  room for a poll: a short one passes under 8, a long one reaches a person at
  12 who can answer "always", and the digest-scoped rule key is what makes
  that answer cover exactly that poll and nothing else.

  Stage one is not a stronger mechanism than the host's, and the code says so:
  a block becomes the tool result exactly as the host's error did, and a model
  that ignores one can ignore the other. Four ignored blocks is where that
  stops being a model recovering and starts being a refusal nobody is reading,
  and the only response in the host's contract that a model cannot answer by
  itself is the person.

  Both messages say only what was measured, which is the arguments. Neither
  claims the results were the same or that another call cannot differ: that
  would be false for a status poll, for `web_search`, and for `read_file` on a
  file another process is writing, and OMH has no way to know. The host's
  guard can say "the file has NOT changed" because it sits inside the tool;
  this sits outside it. The block message says the call has been issued that
  many times with these arguments, says OMH compares arguments and not
  results, and then branches: if the same thing keeps coming back, including
  nothing, then what is being looked for is not there under that name, so read
  the file directly or list what it does define; if something is being waited
  on, do other work between checks instead of re-issuing the call back to
  back. It also never says "you already have this information", the host's
  wording, which was false in the measured case because the pattern named
  functions that do not exist.

  The guard clears itself. One call with different arguments or to a different
  tool resets both counters to nothing, and a streak whose last call is more
  than five minutes old stops counting. Calls that dispatched and calls this
  guard intercepted are counted in separate fields, which is also what makes
  stage two reachable at all: once stage one starts refusing, no further call
  runs, so a count of calls would freeze and only a count of ignored refusals
  can escalate. A reader function exposes both, and the stage, for a later HUD
  surface without changing what is stored.

  Telling a loop from a poll by digesting results is deliberately not built
  here; it is the right next step and is filed separately.

  Identifying a repeat needs the arguments, and the ledger still never holds
  them: they are canonicalized, capped at 8 KiB and stored as a 16-character
  BLAKE2b digest that says only "identical" or "different", which keeps the
  record inside the plugin's `privacy: metadata_only` contract. No argument
  text reaches the ledger, the block message, the approval prompt, or the rule
  key. Every path out of the positive case allows the call: no session id, no
  digest, an unreadable ledger, a malformed row, or a binding fault. That
  matters most at stage two, where an escalation in an unattended session
  waits for a human and then fails closed, and #1674 is what an over-broad
  `pre_tool_call` veto already cost once.

  What this does not claim: that the loop ends. Stage one is a refusal with
  the same mechanism as the two host refusals this model ignored 185 and 100+
  times. Stage two takes the decision away from the model, but no live Hermes
  session was run here, so the prompt rendering and a person's deny ending a
  real loop are untested.

- **`/omh-model` and the `omh` CLI now edit the store a bot profile
  dispatches from.** A Hermes bot profile may select its own OMH store with
  `plugins.entries.omh.settings.omh_home`, and its native plugin resolves that
  setting before any environment value. The two other surfaces that show "the
  chains" did not: the TUI widget forced `OMH_HOME` (or `~/.omh`) into every
  reader and writer it spawned, and the standalone CLI read the environment
  and never the file, even under `--hermes-home <profile>`. So a chain set
  from a Desktop bot chat landed in the profile's store and took effect there,
  while `/omh-model` in that bot's TUI and `omh model-chains show` read
  `~/.omh` and reported every category as `default` -- and a save from the
  picker went to a file the profile never read (#1679).

  The standalone lane now reads the same setting from the Hermes home's own
  `config.yaml` (by text scan, the block shape Hermes writes, last duplicate
  winning), then the legacy `OMH_HOME`, then `~/.omh`; an explicit
  `--omh-home` still wins. An inline `plugins:` section that names no
  `omh_home` reads as absent. A blank or null setting, an inline section
  that does name it, an alias or merge key it could be inherited through, a
  leaf a YAML loader would not hand back as one string, a tab-indented file,
  and a `$VAR` other than `$HERMES_HOME`/`$HOME` are binding errors rather
  than a substitute store -- the last because this lane has no secret scope
  to verify a variable against, where the native lane does. The widget names
  no store and lets the bundle resolve it from the Hermes home it names. The
  installer's profile sync keeps naming the primary's store for the managed
  skills, widget and skin every profile shares; the registration-only
  opt-out and the one-time legacy migration still find a registration
  written at the default store when the home has since selected its own.

  Two smaller things made the symptom unreadable and are fixed alongside: an
  override document the reader rejects (`invalid: …`) rendered in both
  pickers as twelve `default` rows with no warning, and now gets one row
  saying the file is there and why it is not in effect; and the TUI picker
  showed the file it edits only while a change was pending, and now shows it
  always.

- **A gateway session that no profile owns is no longer vetoed out of every
  tool call.** On a Hermes gateway with `multiplex_profiles` on, a session that
  reaches OMH with no home override is one OMH refuses to attribute to any
  profile -- it will not guess a store, and that refusal is correct. What was
  wrong is what `pre_tool_call` did with it: it returned `action: block`, so
  every tool call in every such session came back "OMH runtime binding
  unavailable; tool rules could not be checked", while TUI sessions and
  explicitly routed profiles kept working. The reporter measured 72 blocked
  calls in a day across their IM and cron sessions and confirmed the sessions
  recover as soon as the hook stops vetoing (#1674).

  The veto exists to protect user-authored toolcall rules, and those are opt-in
  by the presence of a file inside the session's own store. A session with no
  store has no rules file to leave unread, so the veto was protecting nothing
  and ending the session instead. That distinction is now carried by the signal
  rather than guessed by the handler: the two refusals that name no store raise
  `UnattributableSessionError`, and `pre_tool_call` degrades on it exactly as
  `post_tool_call` and `pre_llm_call` already did. Every other binding fault
  keeps the veto, because each of them named a store first -- a malformed
  setting, an unresolvable path, an unverified owner, a config read that failed
  -- and a rules file may be sitting in it.

  Profile isolation is untouched. Which sessions bind and which are refused is
  the same before and after; only the refused session's tool calls stop being
  vetoed. The narrower report that a configured `omh_home` cannot rescue this
  shape is real and left open: the refusal does precede the configured home, by
  design, and changing that is a profile-binding decision rather than a
  hook-posture one.

- **Each Hermes TUI's plan-todo panel now renders its own session's checklist,
  not the most recently active one's.** Reported with screenshots (#1672): with
  two TUIs open, both panels showed the same plan and whichever TUI moved last
  won both -- one session mid-run on that plan, the other on an unrelated
  topic, under a byte-identical header. Writes were already one record per
  declaring session; reads were not. The widget names its session from the
  host's per-TUI active-session file, which on `session.create` holds the
  gateway transport id (`ebe3eaaa`) while records and `state.db` rows are keyed
  on the durable session key (`20260917_132533_8da9b8`) -- a name no row or
  record carries, so the reference resolved to nothing and a fallback re-read
  with no identity at all, which answers with the most recently active TUI row.
  The two names meet in the host's own active-session lease registry
  (`$HERMES_HOME/runtime/active_sessions.json`), which records the durable key
  as `session_id` and the transport id as `metadata.live_session_id` against
  one lease, so a reference matching no live row is now resolved there before
  being taken at face value and a created TUI reads its own plan. The
  most-recently-active fallback is gone: an unpaired reference keeps its own
  identity and falls back to the home-wide record under the gates already in
  place, never to another session's record. Only `surface: 'tui'` leases
  answer. Because the host claims a lease on a session's first real turn rather
  than at creation, a TUI nobody has prompted in is named by no entry -- and
  has declared no plan either, so its panel is empty for the same reason. Read
  only, and no Hermes change: `session.create` does already return the durable
  key next to the transport id, so the host could write it into the file
  instead, but OMH does not patch Hermes and the registry answers the same
  question from our own side.

- **The three sibling engines can now put their own lanes on the board
  `ulw-work` learned in the entry below.** A `loop` iteration still died with
  the session: the chain of assess, act, verify, decide had no shape on the
  board, so a loop that had to survive a session end either stayed in-session
  and was lost, or went to the board as unordered rows a new session could
  only resume from memory. `ultraqa` had no way to run a destructive probe
  anywhere but the main workspace, and `ralplan` produced accepted lanes that
  `ultrawork` had to re-plan into node prompts before it could prepare a row.
  Each engine now carries one always-loaded clause, and for the two engines
  that go to the board the method lives in a reference outside the body
  budget. `ulw-loop/references/board-iteration.md` chains each iteration as a
  builder row whose `parents` is the previous verifier and a verifier row
  whose `parents` is its builder, so the board itself enforces builder,
  verifier, next builder and nothing runs out of order; a stop the constraint
  assessment owes the user is a `needs_input` block with the reason, never a
  silent retry, and a new session resumes from one `kanban_list` and one
  `kanban_show` per changed row, continuing from the last `done` verifier
  rather than from memory. There is no goal-mode root row, because the loop's
  real gate is the in-session verification it already requires.
  `ulw-qa/references/board-fanin.md` runs each adversarial scenario
  as its own probe row in a Hermes-owned worktree with a runtime budget, fans
  every probe into exactly one fixer row whose `parents` is all of them so it
  is promoted only after every probe reports, re-verifies through the native
  review lane (`request_review`, and `request_changes` with the reason on a
  failed re-check; a review claim is not merge evidence), returns findings only
  through the bounded, labelled readback as the worker's own report, and names
  the preserved worktree as the cleanup receipt. `ralplan` gains no reference
  and no board: its accepted plan now lists every lane in node-prompt shape
  (`TASK`, `DELIVERABLE`, `SCOPE`, `VERIFY`, `STOP WHEN`) with `depends_on`
  per lane, so `ultrawork` can prepare rows from the plan without re-planning
  while planning itself stays a bounded in-session lane. The create recipe,
  the main-session-only rule, the readback bounds, the provenance words, and
  the role table are not repeated; both references point at
  `ulw-work/references/kanban-lane.md`. No trigger changed, so the routing
  corpus is unchanged.
- **A ulw-work lane can now outlive the chat session, and the HUD shows it
  beside the delegate_task rows.** Until now every parallel lane was a
  `delegate_task` child: a daemon thread inside the TUI process that `/new`,
  a session end, or `kill -9` took with it, that Hermes marked `unknown` and
  never resumed, and that no second session could see. The Hermes Kanban
  board already had everything a durable lane needs (rows in `kanban.db`,
  parent edges that promote a child when every parent is `done`, a gateway
  dispatcher that claims a `ready` row and spawns the assignee profile as a
  detached OS process, a per-task worktree, a `session_id` stamp on rows an
  agent created), and OMH already had the prepare-only path to it,
  `omh_agent_board`. What was missing was the lane vocabulary on that path
  and any way to see the result. The prepared durable `create` now admits
  the per-task overlay the dispatcher reads — `body`, `skills`,
  `workspace_kind`, `workspace_path`, `priority`, `max_runtime_seconds` —
  each bounded before the host schema is consulted, with `parents` declared
  on the create itself because the dispatcher can claim a parentless
  `ready` row within one tick. The role is a contract rather than an
  instruction: a create that states `lane_role` has that lane's skill and
  workspace filled in from the role, and a verifier or reviewer declaring no
  parents is refused instead of landing as a fan-in row the dispatcher can
  claim before its inputs exist. OMH still executes nothing: the Hermes loop
  invokes the prepared `kanban_create`, the gateway runs the worker, and a
  board `done` is written as the worker's completion claim, never as
  verification, CI, review, or merge evidence.

  The HUD reads the board read-only through a bundle-local reader that
  resolves the board the way Hermes does (`HERMES_KANBAN_HOME`, the current
  board slug, the Hermes root with `profiles/<name>` stripped) and projects
  each open task as a lane row in the same activity list as the native
  rows, tagged `[bot]` where a delegate child reads `[sub]` (bold, three
  cells, in place of the per-row `[global]` / `[this chat]` scope word; the
  header line still states the scope), identified as `kanban/<assignee>(<model>:<effort>)` in the same
  shape as the native `category:name(model:effort)` and rendered as one
  accent-toned line, with a static dot for `queued`, a warn bang for a worker whose
  heartbeat stopped, and the native status word in the tail. The figures on
  that line are the worker's own: the board records no usage at all, so the
  model, turns, tool calls, tokens and cost are read from the worker's
  session in the assignee profile's `state.db` and summed the way the native
  rows sum them, so one token column means one thing down the whole list.
  Three rules link them, all matches on recorded fields: the
  `worker_session_id` a worker stamps onto its run the first time it calls
  `kanban_complete` or `kanban_request_review`; before that, the session
  whose title Hermes derived from the dispatcher's own opening prompt,
  `work kanban task <id>`, inside that run's dispatch window, which is what
  tells two workers one tick spawned apart; and failing both, the single
  kanban-source session opened inside the window. A window two untitled
  sessions answer identifies neither, so the
  row keeps the board's own facts and a blank token column rather than a
  borrowed figure. The header
  gains `board Nq Nr Nb` while the board holds lanes and `dispatcher not
  observed` when `ready` rows have waited past the dispatch window with no
  worker or claim anywhere — the one board fault the HUD can see, named as
  a verdict rather than a failure. A session that created board lanes is
  told once, on its next first turn, how many are still open.

  Board readback was the claim that did not survive review: `kanban_show`
  returns every run and comment uncapped, the message gate never sees a
  tool result, and the bridge discards the text. So a third annotating
  pass in `transform_tool_result` now bounds `kanban_show`,
  `kanban_list`, and `kanban_attachments` results per field and in total,
  drops the oldest comments and runs first while keeping the latest run,
  and prefixes one label line whose confidence words are a hand mirror of
  `src/evidence/labels.py`: a completed run is `reported done`, never
  observed or verified. The ultrawork body carries one clause pointing at
  `references/kanban-lane.md` (25,911 bytes by the structure lint's own
  measure, 11 over the 25,900 ceiling, ratcheted to 26,000 with the dated
  reason); the recipe, the
  main-session-only rule (delegate_task children never see `kanban_*`), the
  readback discipline, the provenance words, and the role table — profile
  is the permission envelope, role is the `skills` pin plus body plus model
  pin on the create, specialist titles are lane titles only — live in that
  reference, outside the budget. `docs/AGENT-BOARD.md` records the operator
  preconditions the board needs and OMH cannot create: the `kanban` toolset
  enabled for the platform plus a fresh chat, `hermes kanban init`, a
  running gateway with `kanban.dispatch_in_gateway`, an existing assignee
  profile with the lane's skills installed.
- **The plugin bundle no longer needs the `omh` package to load, and the
  tool-call hooks no longer die when a bundle module fails to.** Reported with
  a reproduction by @tonalenar (#1623): with `memory.provider: omh`, Hermes
  loads the copied bundle a second time as a memory provider and that lane
  execs every top-level `*.py` eagerly. Three modules -- `agent_board_bridge`,
  `activity_observer`, `native_activity_observer` -- imported `omh.*` at module
  scope, which cannot resolve from Hermes' interpreter under the documented
  `uv tool install` / `pip install --user` layouts, and Hermes keeps the
  half-initialized module in `sys.modules`. The lazy `from ..agent_board_bridge
  import pre_agent_board` in the hooks then failed on the NAME rather than the
  module, so `error.name` was the bundle's own dotted path and never `omh`: the
  guard re-raised, and every tool call logged a hook warning while the bridge
  was dead anyway. The three modules now guard those imports the way the rest
  of the bundle already did and report the absence where the feature is
  entered -- `omh_agent_board` answers `omh_agent_board_core_unavailable`, the
  board hooks stand down instead of refusing native `kanban_*` calls they have
  no prepared request for, and the observer raises at construction, which
  `register` turns into the existing `observer_setup_failed` status. The
  engines themselves stay in the `omh` package: a copy in the bundle would be a
  second set of rules for the same receipts. The report's first suggested fix,
  widening the guard to `except ImportError` while keeping the `omh.*` name
  check, was measured against the cached-stub case and does not hold -- the
  name is still not `omh`, so the hook would still re-raise; its own
  alternative, taking the bridge by attribute and skipping when it is absent,
  is what shipped. The gate that should have caught all of this loaded one
  module, `awareness`, so its real subject was whatever `awareness` happened to
  pull in; `tests/test_plugin_bundle_standalone.py` now imports every module
  under `src/plugin_bundle/omh/` with `omh` blocked and derives that list from
  the directory.

- **A sibling cell no longer reads the receipt integrity key while it is
  still empty.** One OMH home holds one key and every run directory under it
  signs with that key, so `load_or_create_observation_key` was reached
  concurrently: `execute_paired_run_plan` submits a wave's cells to a
  `ThreadPoolExecutor`, and the lock each cell holds is a
  `BoundedSemaphore(global_concurrency)` admitting N holders, not a mutex, so
  two cells on different executors and providers ran the function at the same
  moment. The key was created with `O_CREAT|O_EXCL` and filled by a separate
  `os.write`, so between those two calls the key path existed at length zero
  and a second caller read it short. What reached the reader was not a partial
  key but `Hermes child observation integrity key is invalid` -- a message
  naming the key when the key was whole and the reader had merely arrived
  mid-write, which is the wrong diagnosis rather than only the wrong timing.
  The key is now drawn into a private temporary file in the same directory and
  published with `os.link`, so the key name appears only once it already holds
  all 32 bytes. `os.link` was chosen over the `os.rename`/`os.replace` the
  issue proposed because those publish atomically but overwrite: two creators
  would each install a different key, and the one that had already signed a
  receipt would stop verifying. `os.link` fails with `FileExistsError` for
  every creator but the first, which is the same single-creator election
  `O_EXCL` made on the key path itself, and the losers then read the key that
  actually landed. A retry loop on a short read was rejected: it converts a
  race into a slower race and leaves the failure mode intact. The two faults
  that shared the `is invalid` message are now separate -- a key that cannot be
  read says so, and a key of the wrong size reports the size it read, which
  post-fix can only mean the file itself is damaged.

- **There is now a skill for the plan checklist itself, for people who are not
  running a delivery engine.** `omh_todo` is registered on every session, and
  until now nothing in the skill surface named it: 131 skills, none with `todo`
  in the name, and 2 of 126 rendered bodies mentioning the tool at all — both
  delivery engines. A user who wanted a checklist went looking for `/omh-todo`
  and found nothing. `omh-todo-checklist` answers that, in an ordinary session,
  with the body carrying only what is wrong to discover late: items are
  declarations and never execution evidence, exactly one item stays active, and
  `action=set` replaces the whole list so a partial write silently drops what it
  leaves out. The shaping rules, the `blocked_reason` versus `deferred_reason`
  distinction — an item that cannot proceed, versus a person steering the
  session elsewhere — and the guidance on when a checklist is not worth
  declaring live in an on-demand reference, outside the always-loaded budget.

  It is not called `omh-todo`, and the reason is measured. A one-word name
  matches any sentence containing that word through the scorer's `name:` credit,
  and `todo` is among the commonest words in a coding session. A two-word name
  needs both words, which is what makes holding the bare token in
  `_WHOLE_PHRASE_ONLY_TRIGGER_TOKENS` sufficient rather than decorative. Typing
  `/omh-todo` still finds it, because Hermes slash completion is prefix-based.
  Holding the tokens then cost the complete phrases their edge — "declare a plan
  checklist" routed to the planning workflow — so the phrases that name the
  checklist carry an explicit-phrase boost, with the bare nouns `todo` and
  `checklist` deliberately excluded from it.

  `docs/ADDING-A-SKILL.md` gained the two required surfaces it was missing.
  Without a `_WORKFLOW_OPERATIONS_CHAT_CARDS` entry a new skill has no card of
  its own; without `_DIRECT_WORKFLOW_SKILLS` membership the router selects it
  correctly and then renders a generic plan card, which reads as a routing bug
  and is not one. It also gained the rule that a `do_not_use_when` line must not
  repeat the deferring skill's own trigger vocabulary — otherwise the sentence
  written to send work to a sibling makes the deferrer outrank it.
- **`ulw plan` reaches the plan engine.** `docs/INSTALLATION.md` tells users to
  invoke a workflow as `ulw work …`, and only the hyphenated label routed: `ulw`
  on its own is an `ultrawork` trigger at score 12, so it took the whole request
  and the second word was never read. `ulw plan` reached `ultrawork`, `ulw qa`
  did too, and `ulw research` likewise -- the opposite of what the reader asked
  for, with nothing on the reply to say so. Routing now joins `ulw <suffix>`
  into the label it means before matching, for suffixes the catalog actually
  renders as a `ulw-` skill; every spaced form now routes exactly where its
  hyphenated twin does. `ulw` alone still means the delivery engine, and a
  second word that is not a rendered label is left alone rather than joined
  into a skill name that does not exist. Both halves are pinned in
  `ROUTING_INTERVENTION_CASES`, because a join measured only on what it fixes
  is "improved" until it swallows every sentence starting with those three
  letters.

- **The gate against hidden dynamic imports was matching nothing at all.**
  INVARIANT 1 of the handoff safety contract claimed to forbid reaching a
  module by name, on the grounds that a name resolves against the interpreter
  search path and could reach `subprocess` invisibly. It inspected two AST
  shapes, `__import__` as a bare name and `import_module` as an attribute, and
  neither occurs anywhere in `src/`. The spelling this repo actually uses is
  `from importlib import import_module` followed by a bare call, which is an
  `ast.Name` the check never looked at: 15 such calls across 5 files, two of
  them passing a variable rather than a literal. The same mutation — a bare
  `import_module(name)` dropped into an unrelated module — passes on `main` and
  fails now. Issue #1637 asked whether the check's silence about
  `importlib.util.spec_from_file_location` was deliberate scope or a gap, and
  the answer turned out to be that the premise was wrong on both sides. A path
  is not the bounded alternative to a name: `spec_from_file_location` plus
  `exec_module` executes a file that lives outside `src/`, so
  `_source_modules()` never parses it and the loaded file may import whatever
  it likes — which is verbatim what the invariant's own failure message says
  makes a dynamic import dangerous. What actually makes the live call sites
  acceptable is that each confines which module it can reach, and confinement
  is a property of the call site, not of the spelling. So both families are now
  allowlisted the way `subprocess` already was, each entry naming the
  confinement: a closed four-entry literal table, host modules that a wrapper
  declaring no dependency on Hermes cannot import normally, a computed managed
  plugin directory, a `checked_path` root refusal. Coverage extends past
  `spec_from_file_location` to `module_from_spec`, `exec_module`, the
  `SourceFileLoader` and `runpy` spellings, and builtin `exec`/`eval`, so the
  gate does not simply move to the next spelling; what stays deliberately
  uninspected — string indirection, `importlib.reload`, `sys.path` mutation —
  is written down with its reason rather than left to be inferred. Three path
  sites, not the four the issue counted, and one of them is the documentation
  claims prober, which is not a plugin path at all. No path load was reaching a
  spawn capability, and the existing plugin readiness tiers are unchanged; the
  comment in `plugin_pack.py` that justified them dropped its claim that the
  loaded file is hash-pinned, because the doctor tier runs against the
  installed bundle even when the manifest was already recorded invalid.

- **Saying a plan is fine no longer starts the plan again.** `the plan is
  fine, just ship it` dispatched `plan` and emitted a 10,572-character planning
  artifact -- goals, non-goals, decision drivers, options, rejection rationale,
  acceptance criteria -- for a sentence whose content is "yes, go", while
  `the design is fine, just ship it` one word away clarified.
  `ENGINE_ENTRY_CONFIRMATION_RULE` already said an accepted plan is planning
  evidence and not permission; the router contradicted it. It was never a
  `plan` problem: 18 of the catalog's 19 single-word names dispatch on their
  own name in that sentence shape, from `loop` at 45 to `maestro` at 9, because
  a name is at once the skill's name phrase, its phase, its metadata and a
  trigger. The gate keys on the SENTENCE instead of the name, which is what
  makes it finishable -- a list of which catalog names are ordinary words in
  every language the router accepts cannot be completed, and a word missing
  from it would leave the defect live inside a fix that claimed to handle it,
  where an approval phrasing this misses simply leaves today's behaviour. Two
  conditions gate it: the message approves, matched at word boundaries, and the
  winning skill's whole case rests on its own name -- computed by erasing the
  name and re-scoring rather than by listing which evidence labels count.
  Sigilled invocations (`$plan`, `/plan`, `use omh plan`) stay outside it; a
  bare leading name does not, since `plan is fine, ship it` is one article from
  the reported sentence. A compound approval clarifies rather than routing its
  remainder: re-scoring those remainders was measured, and the one that would
  have dispatched confidently is `ultrawork` on "now implement the retry
  handler", which is exactly the automatic continuation the rule forbids.
  English and Korean; Japanese and Chinese are deliberately absent rather than
  guessed at. The corpus gained 8 negative controls and 6 interventions, a case
  shape it had never contained.

- **The briefing now says when there is nothing left to do.** Reported as "할 일
  없다고 유저한테 공지해주는 게 부족함": a finished run announced itself only by
  going quiet. `signal` carried three values and `running` meant both "still
  moving" and "done", so the sole evidence a run was over was that the
  `Remaining:` line had stopped appearing — an absence, which is the one thing
  a glance does not register. A fourth value, `complete`, is withheld until
  every outstanding list the briefing keeps is empty: `pending_gaps` alone is
  not enough, because the runtime ladder reports separately in
  `runtime_milestone_gaps` and a prepared team path can sit at an unobserved
  rung with no progress step pending. The finished state also catches the
  headline's fall-through: those branches learn about a merge only from a
  runtime observation event or a lifecycle token, never from
  `runtime_status["merge"]`, so a run whose every step was complete could still
  be headed "is handling the coding work" — present tense, under a ✅ mark. It
  catches rather than outranks, which is the opposite of the standing rule for
  a stop and deliberate: a stop contradicts those branches, while a finished
  run agrees with them and they say more, so "work is recorded as merged" keeps
  its headline. The `Action:` line reads `none` in that state rather than
  echoing whatever `next_action` was written last, since nothing requires a producer to
  clear it on the way out. The sentence is translated in all seven locales the
  table carries, and an adapter that only knows the original three values keeps
  working: `complete` is the case it previously received as `running`.
- **A chat reply now names the workflow you asked for, in the spelling you can
  type back.** Two separate faults made the first line of a reply disagree with
  the router that produced it.

  The catalog keeps `ralplan`, `ultrawork`, `ultraqa`, `research`, `loop`,
  `maestro`, `context`, `deep-interview` and `ultraperf` as internal keys
  because triggers, capability maps and lifecycle rows are built from them,
  while the installed skills answer to `ulw-plan`, `ulw-work`, `ulw-qa` and so
  on. `public_workflow_identifier` exists to make that swap on the way out and
  its docstring calls itself "the one place" it happens — but the wrapper's
  explanation and usage-trace payloads never called it, so `ralplan` reached
  `label`, `visible_prefix`, `route_recommended_reply`,
  `route_primary_action_label` and `route_primary_action_hint` while
  `why_this_workflow` on the same payload said `ulw-plan`. One reply named the
  same workflow two ways. A `next_action` token that embeds its own skill
  (`prepare_ultraperf_loop`) put the key back into the sentence even after
  every field was corrected, so rendered prose now goes through
  `with_public_skill_names`; the tokens and ids themselves are untouched.

  Separately, a dispatched workflow that answers with the card it starts with
  lost its name entirely. `ultrawork` on a request that names no target keeps
  its plan card by design, and the prefix then read `[omh] plan` — so a user
  who typed `ulw-work` saw no trace of what they asked for, while
  `route.selected_skill` still said `ultrawork` two keys away. The prefix,
  label and `usage_trace.selected_workflow` now name the routed workflow on a
  `dispatch`; `state.selected_workflow` still reports the card that was
  actually rendered, because that is what a consumer reading it has always
  been told.

  `tests/test_public_workflow_name_exposure.py` derives the legacy set from the
  display rule rather than listing it, so a later relabel moves the guard with
  it, and fails if that set is ever empty — a guard over nothing passes without
  proving anything.

- **A minted memory id can no longer read back as a leaked credential.**
  `secrets.token_urlsafe(18)` draws 24 characters from the base64url alphabet,
  so a token occasionally comes out shaped like a real API key — `sk-`, `hf_`,
  `gh[oprsu][_-]`, `AIza`, `xox-` and the separator-split variant all fire, at
  a measured one id in 25,000. When such a token became a block's own
  `review_id`, the admission walk classified the block's own identifier as a
  secret and omitted the approved block from its own render with
  `safety_blocked_in_admission.review_id`. Nothing was lost and nothing said
  so; it surfaced as a CI failure costing a full diagnosis each time it landed.
  `_opaque_id` now redraws until the token classifies safe, and `_validate_block`
  checks the shape of `review_id` rather than only its presence — the guard its
  sibling `_memory_review_path` has had all along. Pinned by forced colliding
  draws, one per firing pattern, taken from real generator output (#1641).

- **OMH now engages on an ordinary prompt, and the trigger is what the model
  does rather than what the user typed.** Four measured causes of one report
  ("거의 todo나 에이전트 호출을 하지 않더라"). The plugin bundle's invocation
  vocabulary had drifted behind the router's: a bare `ulw` was a clean explicit
  dispatch on `public_chat_route_payload` and a zero-length context from
  `awareness_route_hint`, and so were the historical `omh-loop` and
  `omh-research` labels, because the pre-ULW alias was only added inside the
  display-name override branch. The bundle runs in a live session while the
  routing corpora measure `src/routing/`, so every routing test stayed green
  over a dead surface; a parity test now re-derives both vocabularies and fails
  on divergence. A route hint for a workflow whose run *is* a checklist now
  says to declare one — six workflows, not `ulw-context` or `ulw-interview`,
  which are engines that produce one card or one question. Awareness was gated
  on the user's message already containing OMH vocabulary, so six of eight
  ordinary work requests got nothing; the session's first turn now carries the
  primer unconditionally (897 characters, once), deliberately not on a task-size
  test, since the largest request in that set was one of the misses.
  None of that makes a plain session declare a plan, so two behaviour-triggered
  nudges ride `transform_tool_result`: one on the third `write_file`/`patch`
  result with no plan record, one on the fifth direct search/read with nothing
  routed. Both latch off permanently on a record — the plan record, or the tool
  name the host handed the hook — never on a string the model wrote, and both
  are bounded at two per session (worst case 1,418 characters). `subagent_start`
  is registered so a delegated child, which runs under its own session id on a
  seam carrying no agent identity, is never asked to declare its parent's
  checklist. Known boundary shared with #1549: the gate is `write_file`/`patch`,
  not "edited code", so a session that edits through the shell is never nudged.

- **An `ultrawork` run now meets its "declare the plan first" instruction
  before it starts, not after it has finished.** The one sentence telling the
  engine to initialize its phase todo was the sixth bullet of a ninety-line
  list under a heading named `Catalog Metadata`, near the bottom of a
  26,705-byte body — a section a model reads as machine-readable bookkeeping,
  reached only once the run is already underway. Strip that block from
  `skills/ulw-work/SKILL.md` and the word `todo` did not appear anywhere else
  in the document, `Completion Checklist` included; a real run performed the
  whole task with the HUD checklist empty. The directive is unchanged text
  that moved: workflow bodies gained a `## First Steps` section, rendered
  directly under `## Why This Exists` from a new `opening_steps` catalog field,
  and `ultrawork` and `ralplan` carry their todo-initialization there. Each
  also gained one `Completion Checklist` line, because the section a model
  follows to decide it is done covered lane disjointness, ACK, review, CI and
  integration and said nothing about whether a plan was ever declared — so a
  run that declared none still read as complete. The Agent Skills projection
  buried its own host-neutral copy of the same directive in the same place and
  moved with it. The seven remaining `ulw-*` skills are unchanged: six mention
  a todo only through the shared interjection rule, which re-reads one *when
  one is active*, and `ulw-interview` mentions none — a conditional reference
  is not a misplaced instruction, and giving them an obligation they never had
  is a different change.

  Because the cause is structural rather than an authoring slip -- `quality_bar`
  is a `SkillDefinition` field and every field it holds renders under
  `## Catalog Metadata` -- all 126 rendered bodies were then swept for `omh_*`
  directives living only inside that span. It found the same shape twice more,
  and both are now stated where a run decides it is done. `ulw-maestro` is told
  to close with the localized `omh_run_summary` text and its checklist said
  nothing about the close, so a run could end with no summary and nothing in
  the document contradicted it. `ultrawork` is told to route every
  Hermes-native lane with `omh_delegate_route` before dispatch and its
  checklist said nothing about routing, so a run that dispatched every lane
  inherit-labeled passed its own completion contract -- which is the second
  half of the same user report, the run that declared no todo also routed no
  lane. Each is one line restating an obligation the quality bar already
  carried; no new behavior text.

- **The coding status board reports how much a lane did, not only how long it
  ran.** A lane at twelve minutes and two tool calls and a lane at twelve
  minutes and sixty are different situations, and an elapsed time alone reports
  them identically — which is the reading a person has to make when deciding
  whether a quiet lane is working or stuck. `tool_count` was already observed
  and recorded in `ROUTING_METRIC_SIGNAL_KEYS`, and
  `_compact_event_projection` already folded it into the progress event; it had
  no field on the board row to travel in. There is now a `TOOLS` column on the
  aligned board and a `N tool calls` part in the bullet profile.

  Zero and unobserved render differently, deliberately. Zero is a real answer —
  an executor that made no tool calls made none — so an unobserved count shows
  `unknown` rather than `0`, which a reader would take as the executor having
  done nothing. `True` is refused as a count for the same reason it is refused
  elsewhere in this module: it is an `int` in Python and `1 tool call` would be
  a fiction.

- **Each lane on the coding status board now wears its model vendor's glyph.**
  Three running lanes are three rows of near-identical text, and the model is
  the field that differs and the field a reader scans for; a glyph is read
  before the word beside it is. The mapping is per vendor, not per model —
  `claude-opus-5` and `claude-fable-5-1` share 🟠, because eleven glyphs are
  already at the edge of what anyone holds and one per model generation is not.
  The traffic lights are reserved: 🟢 🟡 🔴 mean whether a run needs the reader,
  so a vendor wearing red would read as a stopped lane, and
  `tests/test_model_vendor_glyphs.py` fails if the two sets ever intersect.
  Every glyph is two display cells, also pinned, because a one- or three-cell
  glyph looks fine in bullets and shifts every column after it in the aligned
  block. A model the table has not seen renders ⬜ rather than nothing, since an
  unlabelled row among labelled ones reads as a rendering fault.

  Vendor resolution handles the shapes the board actually carries rather than
  the aliases OMH chooses: a bare product name (`fable-5 high` — Anthropic's
  names arrive without the family prefix), a provider-prefixed id
  (`openrouter/qwen-3.5-coder`, where the vendor is the model's and not the
  gateway's), and a generation-numbered token (`qwen3-coder`, which is why the
  token table is written out instead of matched by prefix). The first two were
  found by existing board tests, not by the new guard, which had been derived
  from the shipped chain table alone.

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

- **A `providers.<id>` block now says what it serves, and a machine that
  cannot say is told so.** Such a block is the operator's own endpoint behind
  their own `base_url`, and detection recorded every one of them as `gateway`.
  That kind is multi-vendor, so `alias_is_served` counted every alias as served
  and `entitlement_shaped_chain` was a no-op: the chain reordering did nothing
  at all, and `omh model-chains show` said only `Linked Hermes providers:
  custom (config)`, which reads as confirmation that the providers are being
  counted. Free-tier users reach OpenRouter and similar through exactly such a
  block, so the feature was dark for the population whose chains most need
  shaping. Detection now reads the block's `base_url` host, which it already
  parsed to decide whether the endpoint was a local model server: a host that
  is a vendor's documented API endpoint (`ENDPOINT_HOST_FAMILIES` — exact
  hosts, never a substring) carries that vendor's family, so a `custom` block
  pointed at `api.deepseek.com` reorders the chains like a `deepseek` provider.
  An id that already names a family is never overruled by its URL, and a
  private relay of the operator's own stays unresolved rather than being
  renamed after a vendor whose name happens to appear in its URL. For that
  remaining case — a gateway no host can identify — `omh model-chains show`
  says so and names the one way to record what it serves:
  `omh model-chains provider set <id> <kind>` / `clear <id>`. It is the only
  way, measured rather than assumed — a detected `providers.<id>` row arrives
  ticked at the kind detection gave it, re-entering the same id after the list
  is refused as already recorded, and a `--yes`, `--json`, or non-TTY
  `omh setup` asks no provider question at all. It writes the same
  `providers.json`
  through the same validation the interview now also routes through — one
  producer, `write_provider_entitlements` — refuses a kind outside the
  vocabulary by naming the accepted values, refuses to overwrite a record it
  cannot read, and is idempotent. The line is said only when every provider
  resolves to no family and no category actually came out reordered, so a
  machine holding `openrouter` (which does serve every family) and one whose
  routes shape a chain are both left alone; the `--json` payload carries the
  same fact as `unplaced_providers`.

- **`omh doctor` now says when the installed profile cannot reach the workflow
  engines, and names the command that fixes it.** `install_skill_pack` adds
  only what the recorded profile names and otherwise refreshes what is already
  on disk, and none of the nine canonical ULW engines is in
  `CORE_PROFILE_SKILLS` — so on a core install `ulw-work` is in neither set and
  no number of `omh update` runs will ever add it. That ADD/REFRESH rule is
  deliberate and unchanged; what was missing was the consequence, which nothing
  restated after `--core`'s help text stated it at the moment of choosing. A
  user who invoked an engine found nothing and had no way to learn why. The new
  `workflow_engine_reach` entry names the absent engines and the profile on
  record, and points at `omh update --full`. It lives in the read-only advisory
  lane rather than among the doctor checks because core is a legitimate,
  recommended profile — a fact with a consequence, not a health failure — so it
  cannot move the doctor status or exit code. It is derived from which engines
  are absent and never from the profile label, so an install that holds them
  stays silent whatever it recorded.

- **`doctor`'s staleness finding reports what it actually measured.** The
  `skill_freshness` check is a content comparison, and its message printed two
  package versions: on the preview channel, where catalog content moves without
  a version bump, that read `installed by omh 2.0.3, but this omh is 2.0.3` — a
  sentence contradicting itself while asserting a real problem, with nothing in
  it a reader could act on. It now reports catalog revisions, the identifier
  `guidance_projection` already names, so the two checks describe one condition
  in one vocabulary. A revision pair has the same failure mode, so it is
  printed only when there are two revisions to print: a manifest that records
  the current revision over files that do not match it is reported as that
  disagreement rather than as one digest quoted against itself.

- **A load-bearing comment in `guidance_projection` no longer states a false
  reason.** `_projection_state` measures completeness against the install
  manifest rather than the catalog, and justified that by asserting `omh setup`
  installs a core subset by default. The default is `full` and has been for
  some time. The measurement is still right — a user can be on core, and
  catalog-based completeness would then call that correct install missing — so
  the behaviour stands and the reason is now stated without naming a default at
  all. `GuidanceProjectionProfileTests` computes both halves instead.

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
- Clamped the TUI plan dock to the terminal it renders in. The panel capped
  items at eight but nothing capped rows, and each distinct phase adds a
  header of its own, so eight items could be twenty rows above the composer at
  any terminal height. On a 24-row terminal that left three lines of
  transcript and pushed the session banner off entirely. The dock-top render
  now reads the `rows` the host already passes it (the same RenderCtx both
  docks get, `stdout.rows`) and takes at most a third of it, the split shared
  with the transcript and with the bottom dock plus composer. The window
  shrinks outward from the active item, an item and the phase header it
  introduces leave together, and whatever leaves is counted on the existing
  earlier/later fold lines. A terminal too short even for that gets the
  header-and-rule summary the panel already had rather than a truncated
  checklist. From 60 rows up the budget covers the tallest frame the renderer
  can produce, so a roomy terminal is unchanged. (#1727)

- **A refused re-read of a TRUNCATED file now names the offset instead of
  claiming the model already has the content.** Measured in session
  20260919_140745_db409e: a model that needed line 2318 of a 9,172-line file
  called `read_file(path)` with no `offset`. The read returned lines 1-1666
  with `truncated: true` and `next_offset: 1667`, and the model kept calling
  it with the same arguments. After three full results the host answered
  twice with a `status: unchanged` stub and then with 117 distinct `BLOCKED`
  refusals saying "the content from your earlier read_file result in this
  conversation is still current. Proceed with your task using the information
  you already have." For a truncated read that is false in the way that
  matters: line 2318 was in no result. Neither the stub nor the refusal
  mentions `offset`, and the one place it appeared was the `hint` field of
  the successful read, which the model had already ignored three times.

  A fifth pass in the composed `transform_tool_result` seam records what a
  truncated `read_file` returned, keyed on the session, the path, and the
  window the read started from, all taken from the call's own arguments. A
  later refusal or stub whose own call asked for that same window gains one
  bounded note: that read returned lines 1 to 1666 of 9,172 and stopped there,
  lines past the stop were not in that result, and another region needs
  `offset`. Every decision reads a structured field and never the refusal's
  wording -- `truncated`, `next_offset` and `total_lines` on the way in,
  `already_read`, `status == "unchanged"` and `guardrail_refusal` on the way
  out -- so a host that rewrites the sentence keeps working, and a host too old
  to send `guardrail_refusal` (the measured one) is recognised by the other
  two. The window start is half the key rather than payload: a truncated read
  from `offset=5000` says nothing about lines 1-4999, so keying on the path
  alone would have annotated a first-window refusal with a mid-file read's
  numbers. That key is also the whole gate, replacing a literal "the offset is
  1" test with the fact it stood in for, and a model looping on any other
  offset now gets the same note with its own numbers. The window start itself
  is derived through the host's own `max(1, int(offset))` clamp, so it
  describes the read that happened. The map is bounded at 64 sessions and 16
  windows each, evicting oldest first.

  Neither half of the defect is OMH's. The model ignored an explicit
  `Use offset=1667 to continue` three times, and the host wrote the refusal;
  OMH has the one seam that sees both. What this does not claim: that any
  model follows the note. That needs a live run, and none was done. The note
  is prepared instruction, never evidence that a region was read. (#1723)

- **The menu bar helper stops spawning a Python CLI every 8 seconds to learn
  that nothing changed.** The macOS helper ran `omh menubar status
  --observe-local-processes --json` on a flat 8 s timer under launchd, about
  10,800 times a day, whether or not a session existed. One reading measures
  0.69 s wall and 0.53 s user; profiled, that is about 0.46 s of interpreter
  start plus importing the CLI, 0.24 s of the `ps` scan, and 4 ms for every
  file the payload reads put together. It was the largest steady-state cost
  on the owner machine.

  The helper now backs off while the menu is not changing. Each consecutive
  reading that renders the same menu doubles the gap -- 8 s, 16 s, 32 s, then
  a 60 s ceiling -- and any change drops straight back to the active
  interval. `--interval` still means the active cadence, and the ceiling
  never polls faster than an operator who asked for something slower.
  Measured side by side against the old helper for 25 minutes with nothing
  changing: 190 readings became 27, or 456 an hour to 65. A machine whose
  Hermes agent count actually moves restarts the ladder each time and lands
  nearer 4x, which is the intended behaviour rather than a shortfall.

  What it compares is the rendered `display`, not the payload. Comparing
  payloads was the obvious design and does not work: `hermes_processes`
  stamps `observed_at` and the process overlay recomputes `age_seconds` on
  every reading, so two readings of an untouched machine are never equal and
  the ladder would have sat on rung 0 forever.

  The ceiling would otherwise cost lateness, so the payload now names its own
  `watch_paths` and the helper stats them on a 2 s tick, spawning nothing
  unless one moved. Those paths come from the module that opens them rather
  than a list kept by hand, and they include the write-ahead log: Hermes runs
  `state.db` in WAL mode, so a session write lands in the sidecar and leaves
  the database's own mtime untouched until a checkpoint -- on the owner
  machine the two stamps were four minutes apart. What the ceiling does still
  cost is a change only the `ps` scan can see, such as a Hermes process that
  has not touched its session store: that waits for the next scheduled
  reading.

  That wake is floored at the active interval, and the floor is not a detail.
  Hermes writes its session store every few seconds while a session is live,
  so waking on any moved stamp reads far more often than the rung allows.
  Measured over 15 minutes against a home with one live session writing once
  a second: unfloored 169 readings, the flat 8 s timer it replaces 102,
  floored 93. Without the floor this change would have cost two thirds more
  than the timer it removes, precisely when the machine is busiest. A
  reading woken by a moved file also restarts the ladder at the active rung,
  so it cannot climb through a live session.

  A failed reading steps the ladder too. A machine where `omh` cannot be run
  was spawning the failure 450 times an hour; the attention mark still
  arrives on the third consecutive failure. (#1726)
- **The repeat guard can see a cycle, and can tell a loop from a poll.** It
  counted CONSECUTIVE identical calls, so an A,B,A,B alternation reset the
  streak on every call and the guard sat armed and silent through the whole
  failure -- which is the loop the reporting session actually burned its turn
  on, two `terminal` commands alternating to the end. And it compared
  arguments only, so a status poll and a stuck loop looked the same from
  outside, which is why its ladder had to leave room for the poll and its
  message had to hedge about the result.

  Both are one defect, and the fix is one mechanism. A bounded per-session
  history of recent calls replaces the single counter, and a repeating cycle
  of period 1 to 4 replaces the streak -- period 1 IS the streak, so there is
  one detector, not a second one bolted beside it. The periods are the host's
  own (`agent/tool_guardrails.py`), matched deliberately: two detectors that
  disagreed about what a cycle is would refuse different sequences and a
  person comparing the two notes could not tell which was wrong.

  A call now counts toward the ladder only when its ARGUMENTS and its RESULT
  both repeat. `post_tool_call` digests the result under the same privacy
  rule as the arguments -- a length and a bounded one-way hash, never the
  text -- so a poll whose output is changing never reaches a stage however
  long it runs, and the block message may now say the results were identical,
  and says it only when they were compared. A result this seam cannot digest
  leaves the call unknown, which falls back to the argument comparison that
  shipped before and to the message that claims nothing about results.

  Two things the host does that a simpler reading of those seams misses, both
  found by driving the ladder through a worker pool rather than one call at a
  time. Hermes fires `post_tool_call` for a BLOCKED call too, with the
  refusal as the result -- OMH's own message, on OMH's own blocks -- and that
  digest was landing in the history of a sibling call that really ran, which
  broke the cycle chain and restarted the ladder; the host marks that post
  `status="blocked"`, so the structured field is read and the refusal is not
  digested. And a call still in flight has no result yet, which the
  comparison was reading as "no evidence, fall back to arguments" -- so an
  eight-wide poll with a different answer every call was blocked at call 9.
  The ladder is now computed over the calls that have returned, with the
  fallback kept for the host it was written for: one that fires no
  `post_tool_call` at all, where nothing has a result and the guard is the
  argument-only one it has always been.

  Stated limit, unchanged and now plainer: a result carrying a timestamp, an
  elapsed duration or a progress percentage never repeats byte-for-byte, so
  it reads as progress forever. A single-call loop whose output is
  timestamped -- a `terminal` loop returning `1 failed in 0.4Ns` -- was
  blocked at call 9 before this change and is not caught now. That is the
  price of telling a poll from a loop by its output, and OMH does not
  normalize result text to avoid it: deciding which bytes of a result do not
  count is wording inference.

  What the ladder costs, per period: 8 calls at period 1 (unchanged), 8 at
  period 2, 9 at period 3, 12 at period 4. Counting laps alone would have
  given a period-4 cycle 32 calls before anyone noticed, four times a
  period-1 streak's budget, bought by padding the loop.

  Dispatch width shifts where the rungs land, because a call in flight is not
  yet evidence. For a period-1 loop of 24 identical calls, allowed `.`,
  blocked `B`, escalated `A`:

  ```
  width 1: ........BBBBAAAAAAAAAAAA
  width 2: .........BBBBAAAAAAAAAAA
  width 8: ...............BBBBAAAAA
  ```

  The same poll at every width is `........................`.

  A tool the host exempts from its own identical-call notice is exempt here
  too, by the host's predicate rather than a second list: `process_manage`
  and any tool ending `_poll` or `_get_result`
  (`agent/tool_guardrails.py`). Result-awareness covers a poll whose output
  moves; it does not cover the case the host actually names, a status poll
  returning the same line, which is the tool a model is told to use while it
  waits. A cycle that only partly polls is still a loop.

  Stage two, the human-approval gate, is withheld where no person can answer.
  Measured at `tools/approval.py`, an unattended context does not park on a
  card -- at the `approvals.unattended_mode` default of `deny` it returns the
  host's own block text, losing OMH's advice, and at `approve` it returns
  `_approved()`, running the very call stage one was refusing.

  Which lanes those are is the approval layer's question, and the answer is
  taken from the code that decides it (`tools/approval_context.py`): the
  three programmatic platforms whose adapters can neither raise a card nor
  receive an `/approve` reply, plus a single-query (`-q`) process. Every chat
  gateway escalates, because a person can answer there. So does an unknown
  platform, which is the host's own answer for a surface added later. The
  platform comes from `pre_llm_call`, the one hook OMH registers that is
  passed one; `pre_tool_call` is not. A delegated child is withheld too, by
  choice rather than by measurement: its card names a session the person did
  not start.

  **Cron cannot be detected from a plugin, so a cron turn escalates.**
  `HERMES_CRON_SESSION` is a ContextVar name and never a process variable --
  the in-process ticker binds it through `gateway.session_context`, the
  detached worker's environment is built without it, and Hermes' own
  regression test asserts the process environment stays clean after a job --
  and a plugin cannot read a host ContextVar. An earlier draft read the
  variable anyway and claimed the dedicated-process case worked; that was a
  gate frozen on a state the host never produces, and it is gone rather than
  kept as a line that cannot fire. The cost is bounded and is not a
  regression, since every lane escalated before this: at the
  `approvals.cron_mode` default of `deny` the host resolves the escalation as
  a block, so the loop still stops with the host's wording instead of OMH's
  advice; at `approve` it auto-approves the looping call. Single-query is
  different and does work, because Hermes exports that marker on both of its
  entry paths.

  The projection a surface reads (`repeat_call_streak`, which #1687's HUD row
  will be the first caller of) requires the attendance answer as an argument
  with no default, so a caller cannot render an escalation the gate is
  withholding by omitting it.

  The escalation's `[a]lways` key is derived from the cycle's elements in
  their lexicographically smallest rotation, so A,B,A,B and B,A,B,A are one
  key and a person who answered once is not re-prompted by a key that moved.

  Once a cycle is engaged, every call belonging to it is refused, not only
  the one the cycle would run next. Driving the ladder through the two
  registered hooks found the difference: a blocked call never runs, so the
  cycle's phase does not advance, and a model that answered the block by
  issuing the OTHER element got eight more calls before the guard re-armed.
  The observed ladder for a period-2 cycle is now calls 1-8 allowed, 9-12
  blocked, 13 escalated -- the same shape a period-1 streak has. A call that
  is not in the cycle still clears the guard, which is the only thing that
  ever did.

  The refusal the model reads says that now. It used to end "any different
  tool call clears the guard immediately", which was true while the guard
  watched a single repeated call and false the moment membership replaced
  position: under a cycle the other element IS a different tool call and is
  refused, so the message was telling the model to do the one thing this
  change made it stop doing. It now names a call outside the cycle.

  Hook cost, measured before and after on the same machine with the ledger at
  its caps, median of three back-to-back passes, both hooks. At 64
  simultaneously live sessions `pre_tool_call` goes from 3.11 ms to 3.89 ms
  p50 and `post_tool_call` from 2.28 ms to 2.96 ms, with the ledger growing
  from 57.8 KiB to 119.6 KiB. At the everyday two-session shape both hooks
  are unchanged and the ledger SHRINKS, from 47.1 KiB to 33.4 KiB. Four
  things hold the ceiling down: a session that is not repeating anything is
  trimmed to the shortest window a cycle can be found in, the gate reads one
  session's row instead of rebuilding every row, a write carries other
  sessions' rows through untouched, and this one ledger is now written
  without the pretty-printing every other OMH ledger keeps -- it is rewritten
  on every tool call and nothing reads it as text. (#1719, #1706)

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
