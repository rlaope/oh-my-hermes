# Changelog

All notable changes will be documented here.

## Unreleased

- **CI runs the Windows unit tests in four shards.** Each of the two
  `test-windows` shards ran about 7,200 tests in roughly 35 minutes, against
  about 13 minutes for a Linux shard, so Windows set the wall clock of every
  run. The `plan` job now also writes `plan-windows.json`, a 4-shard plan over
  the same inventory, timing history and quarantine; the Linux lanes keep their
  2-shard `plan.json`, so the run needs only two more jobs. `aggregate.py`
  takes `--lane-plan LANE=PATH`, checks each lane against the plan that lane
  ran, and fails when a lane plan covers different tests or a different
  quarantine, or when any shard of a lane's own plan is missing.

- **Hermes turns name the skills a work request may fit.** On a turn whose
  request reads as work, the plugin adds one line naming up to three
  installed skills with the situation each serves, and the model may load
  one with `skill_view`. The candidates come from the same BM25 ranking the
  router's shortlist uses, shipped to the plugin as a generated index
  (`omh docs skill-shortlist`, checked byte-for-byte). The line needs a
  catalog-rare word from a skill's own situations or triggers, and stays
  away from greetings, factual questions, jokes, recommendations, personal
  advice, a workflow the person named, and messages with no ASCII words. A
  session sees the same candidate set once. The awareness primer also says
  which requests OMH skills are for. Measured on a live model (GPT-6 Luna,
  one Hermes turn per message, one run per arm), the intended skill loaded
  for 90% of a 150-request work set (78% on main). The everyday target was
  missed: 32.5% of an 80-message everyday set still loaded an OMH skill
  (38.8% on main), against a 10% target. Most of those loads had no
  candidate line; the model picked the skill from the host's skill index.
  Requests written without ASCII words get no line.
- **Shortlist first: the router dispatches only on strong evidence and
  otherwise hands Hermes the shortlist.** A confident score dispatches only
  on an explicit or named invocation, the winner's own trigger phrase (unless
  another skill said an equal phrase), or a trusted intent guard.
  The pinned canonical requests without a phrase of their own ("the CI build
  is failing on main", "review PR 1234", "deploy the app to production") ask,
  with the intended skill first on the shortlist, for Hermes or the user to
  confirm; paraphrases of them ("restyle the settings screen", "look over this
  merge request") are not guaranteed the same order. Every guard is classified in
  `GUARD_DISPATCH_TRUST`, trusted only where its predicate is intent-shaped
  and its measured record supports it; guard fast paths answer to the same
  table. Everything else -- trigger tokens, a one-word name, a context-only
  guard -- clarifies with reason `weak_dispatch_evidence`. The clarify
  carries up to four candidates: the declined winner first, scored skills
  with evidence of their own, then a BM25 ranking over each skill's name,
  triggers, situations, description, and use_when. The clarify card tells the
  model to pick the workflow whose situation matches, naming each by the
  situation its description opens on; `route_question` asks the same
  shortlist. Guards and fast paths that fired on a word used in passing were
  narrowed with vocabulary-level rules and negative cases (failure-outcome
  words, check verbs, a cadence of a frequency word before a time, code-unit
  nouns, own-skill inventory questions, system memory, bare verb names before
  a plain noun), and single words that only mean a skill inside its phrase
  are held back so they stop deciding which skill leads the shortlist. Measured in-sample on the 501-message tuning set these rules
  were checked against: wrong dispatch 30.9% -> 9.8%, intended skill
  dispatched or shortlisted 34.3% -> 62.7% (English: 7.9% and 69.5%). On the
  owner's held-out English set, before the follow-up that removed
  tuning-probe wording from the predicates, wrong dispatch went 40.4% ->
  25.3% and reach 43.2% -> 62.2%; the reach target of 85% is not met.

- **Every installable skill is checked for routing reach, and a skill the
  corpora never reach fails CI by name.** `omh demo skill-reach` (operators
  and agents) projects the two routing-precision corpora per skill on the
  deciding surface: intervention cases that dispatch to it without an explicit
  invocation, cases that reach it only when addressed, and negative controls
  that enter its territory and stay unrouted. `tests/test_skill_reach.py`
  fails naming each skill with no natural dispatch case or no negative
  control, unless it is in a shrink-only baseline whose reason is re-measured
  on every run: `corpus_gap` holds only while one of the skill's own non-name
  triggers dispatches to it, and `addressed_by_design` (the `/omh` sigil and
  the Jev skills) only while an addressed case reaches it and no non-name
  trigger does. A baseline entry for a skill that became reachable fails too.
  Measured at landing: 130 installable skills, 88 with natural positive reach
  and 42 without (35 corpus gaps, 7 addressed by design); 113 with a negative
  control and 17 without. A case where the router asks with the skill first
  is shown as `shortlist_first_cases` and not counted as reach. No trigger
  or routing behavior changed.
- **A fanout unit's "done" can include the tests its own changes reach.** A
  unit may declare `task_linked_test_runner` (for example
  `PYTHONPATH=tests python -m unittest`). Under `--run-verification` the
  dispatcher reads the committed diff it observed, selects every test module
  that directly imports a changed file through the local codegraph, and runs
  the runner on them as one more dispatcher-observed check, so its exit status
  decides the unit the way every declared check does; the prompt's criterion
  names the same rule. A failing check now records `unit_state_reason:
  verification_failed` instead of `verification_not_observed`, and an earlier
  attempt's journaled pass no longer outlives a failure in the current one. A
  change no test imports adds nothing, and an unreadable diff fails closed. The
  product A/B bench's gate runs the same rule over the candidate's diff (the
  task's own test files excluded), so it no longer only re-runs the criteria
  the model already ran green.
- **`omh update` says what changed for you.** After the new generation is
  installed, the update prints a short "What changed for you" block: skills
  added (with what each is for), removed, or given new instructions; skills
  that now pick up different requests (the trigger phrases gained or lost);
  and the model chains on this machine whose shipped default moved, shaped by
  this machine's providers -- or "your own chain for it still applies" where
  the user overrides that category. The comparison reads only OMH's own
  records (the managed manifest's per-skill checksums and a new
  `runtime/update-baseline.json`), so a user's config edits never appear as
  an OMH change. A first install says there is nothing to compare, and an
  update that changed nothing prints nothing. The note is kept at
  `runtime/update-change-note.json`, and `omh_status` returns it as
  `last_update_change_note`, so asking Hermes "what changed in OMH?" answers
  from the record; nothing is added to the per-turn context. English by
  default; `--language` / `OMH_LANG` localize it.
- **Asking "how much did this task cost?" in chat gets a receipt.**
  `omh_run_summary` now returns a `cost_receipt` (`omh_cost_receipt/v1`) that
  sums the calling conversation's recorded spend: its session rows and
  compression continuations, every delegated Hermes child below it, and fanout
  units that recorded the conversation as their origin. `omh coding fanout
  dispatch` stamps that origin (`origin_session_id`) from the
  `HERMES_SESSION_ID` Hermes gives terminal commands. Observed cost, usage with
  no recorded price, and records with no usage stay apart; nothing is
  estimated, and every receipt names what it does not cover. Operators get the
  same text from `omh quality-evidence cost-receipt --session <id>` (`--json`
  for the payload).
- **"Continue what I was doing" works across Hermes surfaces.** A new
  read-only plugin tool, `omh_resume`, returns the person's recent OMH work
  from their other sessions in the same profile: the plan todo each session
  declared (last 24 hours) and the completion checkpoints it froze (last 30
  days), joined to Hermes' own session rows for the surface, timing, tool-call
  count, repository name and branch. Plain text is the default rendering, in
  the `text` field. Who counts as the same person comes only from `state.db`:
  every local surface (`cli`, `tui`, `desktop`, `acp`) is the profile's user,
  and a chat-platform user counts only in a direct message (`source` +
  `user_id`, `chat_type` `dm`), so one Slack user never sees another's plan,
  the local user never sees theirs, and a group channel or thread, where
  anyone can ask and everyone reads the answer, is refused. Hermes
  records no link between a platform user and the local user, so that
  crossing is not made; a surface that names no person (webhook, cron, a
  delegated subagent session) is shown nothing. A session another profile's `state.db` lists is never read,
  even when the profiles share one OMH home. Metadata only: no session title,
  activity description, deferral reason or transcript. Nothing is added to
  `pre_llm_call` or the primer; the tool schema raises
  `PLUGIN_TOOL_SCHEMA_CHAR_LIMIT` 59258 -> 60678.

- **The plugin admits a Hermes git checkout by the release it resolves, not
  the install stamp's placeholder.** Released Hermes through 0.21.5 hard-codes
  `hermes_cli.__version__`; hermes-agent main now serves it from the install
  stamp only, so a checkout without one -- a source install, and the
  plugin-catalog CI that clones Hermes to run `hermes plugins validate` --
  reports `0.0.0`, and OMH refused to register there. The bundle now reads
  `hermes_cli.version_info.get_version_info().base_version` when the host has
  it, the value Hermes' own `requires_hermes` gate compares, and falls back to
  `__version__` on released hosts. An unsupported or unknown release is still
  refused.

- **Skill descriptions open on the user's situation.** Hermes shows a model
  each skill's name and the first 57 characters of its description; on the
  previous catalog half of those windows began "Hermes ..." and most spent
  characters on the word "workflow". Every installable description now reads
  "<situation the user is in>: <what the skill produces>" (for example
  "Remember a fact for future sessions: ..."), and no two skills share a
  three-word opening. `SkillDefinition` gains `situations`, 5-10 plain English
  phrases per skill in the words a user would use; the lexical shortlist
  reads it and nothing scores or renders it. Routing results on both
  precision corpora are unchanged.
- **Skill openings name the work context a model needs to tell them from
  private life.** Many situation openings also described private life: a
  weekend plan, a personal budget, a performance review, a book club
  meeting. A live model loaded them for everyday chat. 26 openings now put
  the work context inside the visible window, for example "Company hiring or
  HR process to structure", "Upcoming work meeting that lacks an agenda" and
  "Support ticket your team must answer or escalate". On a 120-message
  everyday-chat set (GPT-6 Luna, one Hermes turn each, two runs per side),
  the share that loaded an OMH skill fell from 69% to 44%. That is still far
  above the 10% target. `omh-live-info` alone accounts for about 19 of
  those loads, whatever its opening says. On a 130-request work set the
  intended skill loaded in 67.0% of runs, against 70.8% on main.
  Routing results on both precision corpora are unchanged.
- **The plugin bundle passes `hermes plugins validate`, and a plugin Hermes
  installed is left to Hermes.** The Hermes install scanner read the dict-key
  constant `PRIVATE_TOKEN = "__omh_egress_attempt_token"` as a hardcoded
  secret (`dangerous`), which fails a curated-catalog entry; it is now
  `PRIVATE_ARGUMENT_KEY`, and a test applies the scanner's own
  `hardcoded_secret` pattern to every bundle file. `omh setup` and
  `omh update` read Hermes' install records (`plugins/.install-metadata.json`,
  the `.hermes-catalog.json` sidecar): a `plugins/omh` that
  `hermes plugins install` wrote, and OMH did not write after it, is reported
  as host-managed and not overwritten, `--force` included, while skills and
  config are still managed, and a bot profile's row says `host_managed`
  instead of `refreshed`. `omh uninstall` keeps that tree, `--force`
  included, and names `hermes plugins remove omh`. `omh doctor` reports it as
  installed by Hermes, says whether its files match the installed OMH
  package, and reports a hook whose bytes differ from the package's reviewed
  digest as version skew (a warning naming `hermes plugins update omh`), not
  tampering; the hook-integrity record is read only by doctor, so nothing
  changed at runtime. A directory with neither OMH's manifest nor a Hermes
  record is still refused.
  The documented install is unchanged.
- **The OMH awareness primer now lives in the session's system prompt, not in
  the first user message.** Hermes 0.20.2 (tag v2026.8.16) added
  `register_system_prompt_section`: text rendered once per new session and
  frozen into its system prompt. Every Hermes the plugin admits (0.21.1 and
  later) has it. The plugin registers the primer (1,044 chars, the same text
  for every session) as the `omh.awareness` section, under the host's
  4,000-char per-section cap. `pre_llm_call` no longer carries it for a
  session the section rendered for. Before, the primer went into the fenced
  user-message context on the first turn and again after a compaction dropped
  it. A session keeps the old per-turn path, and can carry the primer twice,
  unless its own first turn confirms the section: a routed background-review
  fork renders under its parent's session id, so a render alone is not
  trusted, and a fork runs with the parent's history, so its turn is never a
  first turn. The fallback cases: a host without the API or a section the
  host refuses; an unconfirmed record (a parent resumed after a restart whose
  first review fork renders the section); a
  session resumed after a restart, where the host restores the section
  without calling the plugin; a legacy compaction that rotates the session
  id, where Hermes rebuilds the prompt before assigning the new id
  (`conversation_compression.py`); and an id evicted from the plugin's
  1,024-session record (least recently used first). "Never zero" has two
  stated gaps: a section the host drops past its shared budget (below), and
  a review fork of a parent with no history at all, which would pass as a
  first turn. The largest measured `pre_llm_call` context on a
  section host drops from 6,260 to 5,214 chars
  (`PRE_LLM_CALL_CONTEXT_CHAR_LIMIT`); the fallback keeps its own gate at
  6,260 (`PRE_LLM_CALL_CONTEXT_FALLBACK_CHAR_LIMIT`, scenario
  `all_surfaces_without_section`). Everything else the hook sends depends on
  the turn and stays where it was. Every prompt Hermes builds now carries the
  primer, including `hermes prompt-size` inspection builds and routed
  background-review forks. `omh doctor` counts a section delivery once per
  session, on the first `pre_llm_call` that leaves the primer to a confirmed
  section,
  so a working install does not read as zero deliveries; a render with no
  turn behind it (prompt-size, a review fork) counts nothing, and an install
  with neither still warns. Known limit: Hermes renders sections in sorted-id
  order against an 8,000-char budget shared by every plugin, so a plugin whose
  id sorts before `omh.awareness` spends it first; a section dropped past that
  budget is dropped after rendering, with no signal a plugin can read. Such a
  session gets no primer (the host logs a warning) and is still counted as
  delivered.

- **The product A/B lane measures honestly where it contradicted itself.**
  `benchmarks/product-ab/v1` gave the OMH arm a file scope (`src/`, `tests/`)
  that forbade the completion file its own contract required, and one model
  declined two of five tasks over that conflict without a tool call; the scope
  now names the file and `doctor` fails when it stops doing so. Each
  verification criterion is rendered by the function that builds the gate's
  argv, so the model reads `PYTHONPATH=tests python3 -m unittest …` rather
  than a command that failed as written. The transport filter is derived from
  a sentinel check, so a criterion the protocol adds before the unit's checks
  is no longer dropped silently. Records (`omh_product_ab_run/v2`) say the gate
  never runs the hidden validator and passes on an untouched checkout; the
  gate reads the restored regression modules the grader reads; the report
  counts absent and blocked claims per arm, prints the gate disclosure under
  the table, lists PR-914 as a known corpus defect, and records unreported
  usage as `null` rather than `0.0`. Both arms now read one sentence resolving
  "commit what passes" against "do not commit". No `src/` change.

- **Cached-input calls on GLM 5.3 (and its Ultrafast tier) now price at the
  vendor's own cache-hit ratio instead of the generic tenth.** `glm-5.3` and
  `glm-5.3-ultrafast` were priced in `APPROX_PRICE_PER_MTOK` but absent from
  `APPROX_CACHE_READ_RATIO`, so a cached-input token on either id fell
  through to the 0.1 default. Z.ai lists GLM 5.3 cached input at $0.26
  against $1.4 input, and GLM-5.3-Flash cached input at $0.03 against $0.15
  input (docs.z.ai pricing, read 2026-09-24); both `glm-5.3` and
  `glm-5.3-ultrafast` now carry the 0.26/1.4 ratio (rounded to 0.186, at the
  same precision as the neighbouring Fable and DeepSeek rows), and
  `glm-5.3-flash` carries the exact 0.03/0.15 ratio (0.2). No routing or
  list-price change.

- **Claude Opus 5.5 in the shared last resort now names `medium` effort
  (editorial, unmeasured).** The `last_resort.any` entry carried no effort,
  so fanout dispatch passed no effort flag (claude-code `--effort`, codex
  `model_reasoning_effort`) and the executor CLI's own default applied, and a
  prepared route carried none. It now names `medium`, which reaches fanout
  dispatch and prepared routes; the Hermes `delegate_task` path is unchanged.
  Anthropic's Opus 5.5 guidance is to set effort explicitly
  (https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5.md),
  and `medium` is the rung Opus 5.5 already carries in `unspecified-high` and
  `capable`. No calibration block fires at `medium`; the vendor order is
  unchanged. Named follow-up: bench arm O4 (Opus 5.5 at `medium` on
  `benchmarks/live-model-tools/v1`).

- **Opus 5.5 subagent block and GPT-6 Luna's `low` placement are now
  measured (2026-09-24).** `MODEL_OPTI.md` records two new benchmark
  results, both from `.omc/research/opus55-luna-bench-2026-09-24/`: the
  Claude subagent calibration block on Opus 5.5 at `xhigh` costs +4,023
  tokens/task over no block, within its own +5,439 same-text drift, at the
  same 18/30 pass rate — kept, though `xhigh` is not a shipped Opus 5.5
  setting; and OMH's `low` effort for `gpt-6-luna` costs +13.9% more tokens
  than the vendor-default `medium` for the same 15/30 pass rate and the same
  list price, so `low` saves nothing measured on this corpus. A third arm
  shows the `gpt-5.6-luna` → `gpt-6-luna` generation swap at `low` dropping
  pass from 18 to 15 (not significant, all three losses in `PREDICATE`) for
  a 67% list-cost cut; `gpt-6-luna` stays in the `quick` and `simple-work`
  chain slots (owner decision), with `PREDICATE` flagged as a known weakness
  to re-check on a larger corpus. No routing, pricing, or contract change.
  Correction (2026-09-24, observed from the run transcripts): the three
  `PREDICATE` losses are a `kind` vocabulary mismatch, not a search miss —
  every `gpt-6-luna` run found the functions and wrote a task-derived `kind`
  label where the grader expects `function`. Named follow-up: bench arm L6
  (`gpt-6-luna` at `low` on the three `PREDICATE` tasks with the `kind`
  vocabulary stated).

- **Runs on the GLM 5.3 and DeepSeek V4.1 Flash Ultrafast tiers now report a
  cost.** `glm-5.3-ultrafast` and `deepseek-v4.1-flash-ultrafast` are served
  by an OpenAI-compatible gateway next to the base ids the shipped chains
  name, but neither appeared in the plugin's price table, so a machine-level
  chain override naming one reported no cost at all. Neither vendor publishes
  a separate rate for the tier, so each row carries its base model's
  documented list price rather than an invented discount: GLM 5.3 at 1.4 / 4.4
  per million tokens (docs.z.ai), V4.1 Flash at the peak 0.30 / 1.20 with its
  0.02 cache-hit ratio (api-docs.deepseek.com). `docs/MODEL-ONBOARDING.md` §5
  now states that rule. Neither tier gains a provider-family row, a contract
  row, or a shipped-chain slot, so provider verdicts stay unknown. Because the
  interview offers a member's `-ultrafast` variant only when that id is
  priced, `omh model-chains interview` now also offers `glm-5.3-ultrafast` for
  chains that name `glm-5.3`.

- **Adding an ordinary skill no longer forces a raise of the skill-body
  budget.** `full_profile_skill_body_chars`, the install footprint of every
  `full` `SKILL.md` body, was a zero-slack ratchet that each new skill had to
  raise to the exact value it measured, and it could not see growth in what
  reaches every request. It is now a ceiling with standing headroom: the
  producer-measured total (1,044,180 chars) plus 10%, rounded up to the next
  50,000, which is 1,150,000 and holds about thirteen average bodies. A test
  keeps the ceiling equal to that derivation. The per-request budgets (skill
  index, tool schemas, `pre_llm_call` context) stay zero-slack ratchets, and
  the per-skill body ceiling in the structure lint is unchanged. A new budget,
  `full_profile_skill_body_repeated_chars`, bounds text repeated verbatim
  across bodies (104,214 chars measured, 9.98%) by the same policy, rounded up
  to the next 10,000: 120,000. Every lane member carries renderer-stamped rail
  sections, so an ordinary new skill adds about 1,450 repeated chars and the
  headroom holds about ten of them, while a skill that copies another's own
  sections or a rail sentence stamped into every body still fails. Both
  measurements are floors as well: a change that shrinks either figure lowers
  its measurement and ceiling in the same commit.

- **`omh_capabilities` answers with the summary when no action is given.** The
  default was `export`, the full capability manifest (over 800k characters),
  which Hermes writes to a file, showing the model only a short preview.
  `action=export` still returns it when asked for by name, and a call that
  names only a `section` still gets that export section. The `omh_todo` and
  `omh_loop` tool schemas drop prose that restated another field or explained
  a rule rather than stating it (7,752 and 7,230 chars, from 9,827 and 7,812);
  every parameter, enum, required field and stop/continue rule is kept. The
  longer phase, `blocked_reason`/`deferred_reason` and checkpoint explanations
  are in the `todo-checklist` skill's references.
  `plugin_tool_schema_chars` ratchets from 57,968 to 55,468.

- **The release budgets now watch what can reach the model on every request.**
  `omh release drift` gains four ratchets, each measured by a producer: the
  full-profile skill index Hermes renders (`skill_index_chars`, 10,894 chars,
  one line per skill with the description cut to Hermes's 60 characters, plus a
  100-char per-line ceiling), the plugin bundle's registered tool schemas
  (`plugin_tool_schema_chars`, 57,968 chars across 19 tools, measured by running
  the bundle's own `register()` against a recording context; an eager ceiling,
  paid on every request only when Hermes's `tools.tool_search` is off, since
  under its default bridge the plugin tools are deferred behind a listing), and
  the largest fenced `pre_llm_call` context over a named scenario set
  (`pre_llm_call_context_chars_max`, 6,260 chars when a routed first turn, a
  role marker, an active workflow and a full running-work board coincide; the
  parts no scenario seeds are listed beside the producer). The
  skill-body total keeps its value and its enforcement and is relabelled for
  what it is: the install footprint, each body loaded on demand. The wording
  that called a skill body "always loaded" is corrected in the installer
  warning, `omh setup --core` help, `docs skill-context-cost`, the doctor
  skill-weight advisory, the structure-lint ceiling message, the adding-a-skill
  guide and the installation guide: a body costs about 8k chars per load and
  stays in history until compaction; only its index line rides every request.
  A new structure-lint rule, `SKILL_INDEX_OPENING_DISTINCT`, fails when two
  installable skills open their visible description with the same three words
  (casefolded, punctuation around a word ignored); the two groups that do
  today ("Hermes adaptation for", "Policy overlay for") are recorded with
  reasons rather than rewritten here.

- **GPT-6 Sol takes every shipped slot both GPT-5.6 tiers held.** `gpt-6-sol`
  replaces `gpt-5.6-sol` in the shared last-resort order (at `medium`) and in
  the Codex Maestro rows, and replaces `gpt-5.6-terra` at the head of `deep`
  and in the `main` role suggestion (both at `high`), in both lanes. The
  Codex `deep` chain is now Sol alone at `high`. The Codex options gain a
  Sol row, and both GPT-5.6 rows stay with their ladders unchanged, so an
  explicit `--model gpt-5.6-sol` or `--model gpt-5.6-terra` override still
  has its effort adjudicated; the 5.6 Sol label no longer claims to be the
  Codex CLI default (the served Codex catalog ranks Astra first). Every slot
  keeps its previous effort. Both GPT-5.6 ids leave the shipped chains and
  stay recognized, priced, and provider-mapped; GPT-5.6 Sol's 2026-09-11
  frontier-slot retirement is widened to every shipped chain. Terra has no
  GPT-6 counterpart, and the Codex client repository's model catalog names
  Sol as the upgrade for both 5.6 tiers (the served catalog does not push it
  yet); Sol's list price ($2 / $10) is at or below Terra's on every
  documented rate. The placement is editorial and unmeasured; the 5.6 Sol vs
  6 Sol pair at `medium`, the Terra vs Sol pair at `high`, and `main` at its
  effort are the follow-up.

  `gpt-6-sol` gains an exact contract read from the vendor's pages: the
  route sends a no-reasoning request as `none`, its documented rung, whether
  it was spelled `none` or `off`, and raises `minimal` to `low`. The Codex
  client's ladder is recorded beside the API ladder without `none` and
  without the Codex-only `ultra` rung, which no OMH ladder or chain names. No
  calibration text changed: Sol receives the GPT family block until a
  measured pair argues for an exact one, and the Codex Sol prompt's sentence
  telling the model to continue without ending the turn is not imported.
  The `gpt_sol_codex_handoff` overlay keeps applying to GPT-6 Sol as a Codex
  main agent, now pinned by a test that names it.

- **OMH can ask Jev itself, when the user asks for it (#1795).** A new
  `omh_jev_ask` plugin tool sends typed questions (yes/no, pick-one, scored) to
  Jev with the user's own key and returns probabilities, and six
  default-installed skills use it: `omh-jev-ask`, `omh-jev-route` (answers an
  undecidable route question and records it as `answered_by: omh_jev_ask`),
  `omh-jev-failure-triage`, `omh-jev-review-gate`, `omh-jev-action-check`, and
  `omh-jev-done-check`. The last four call versioned presets whose rule ladders
  run in OMH code and can only add a hold, a flag, or an objection; a failed
  ask is labelled `not_answered:<status>` and never reads as Jev's answer. This
  is the second scoped exception to "OMH makes no network calls", and it is
  narrow on purpose: the tool opens no socket unless the person's own message
  for that turn names Jev (`consent_not_observed` otherwise; text the host adds,
  such as a quoted reply to the bot's own offer, channel history, an image
  description, an inlined attachment, or a file or page an `@`-reference
  pulled in, does not count, and a reply or channel-history turn that also
  carries an `@`-reference expansion does not consent at all, since a quote
  can spell the expansion's header line; only an allowlisted
  platform a person types into can consent, never a webhook, API, cron,
  subagent, batch, single-query, or kanban-worker turn; on a messaging
  platform only the first line of the message counts and a photo or file
  caption or a voice message does not, because Hermes merges other senders'
  text and clips into the first sender's message -- a native-vision turn, which reaches the hook as a
  content list with image parts, counts as a media turn by its parts; in a
  shared chat only the participant who opened the session can, and a session
  a compaction started names no owner; and the consent is bound to its own
  turn, so a background fork of the session cannot spend it, and while a
  fork's call overlaps the main turn's, neither is sent). A forwarded
  message, a WeCom quote, or a forwarded voice transcript reads as the
  forwarding user's own words, since no chat app marks a forward, and after
  `/new` or a `/stop` whoever speaks first owns the next session's consent;
  both are documented in the skills' rail. The gate cannot tell a bot from a
  person, since the host's bot flag never reaches `pre_llm_call`, so on a
  profile that admits bot messages a bot's words consent like a person's;
  that residual is documented too. A credential in a field name or a
  question id is refused like one in a value, and so is any 8-character piece
  of either configured route key, in any case and with whitespace removed. Only a
  `TYPESAFE_API_KEY` enables it by itself (the OpenRouter route also needs
  `{"openrouter_route": true}` in `<omh_home>/jev/settings.json`, a local-trust
  opt-in), the route table is two fixed HTTPS hosts, redirects are refused,
  only 429, 503, and 529 are retried (any other 5xx and every timeout, a
  gateway's 504 or 524 included, may have been billed and are reported), the
  deadline bounds each read as well as the connect, and no key, `state`,
  question text, or reply is stored; any 8-character piece of a key echoed
  back by the server, in any case or JSON-escaped, is scrubbed from every path,
  and an echo that spaces the key's characters apart blanks the whole excerpt.
  An `answered_by: omh_jev_ask` record is accepted only for an ask this OMH
  process itself sent and Jev answered, never on a ledger row alone, and only
  with the request text, from which the question is re-derived: the ask must
  have sent exactly that question, and a verified digest refuses a Choice
  outside its options whoever answered. The skills
  declare `requires_tools: [omh_jev_ask]`, so Hermes leaves them out of the
  skill index where the tool is not registered (code-read, not observed live),
  for callers that pass a tool set; a caller that passes none shows them.
  Routing reaches a Jev skill only when a message addresses Jev ("ask jev",
  "use jev", "have jev", a skill name in its invocation form); sentences that
  only mention Jev, decline it, name it among options, or explicitly invoke a
  different OMH skill keep their owner, pinned by new corpus cases. `omh doctor`'s `plugin_jev_sidekick`
  line now also reports the tool's route by variable name, its ledger, and what
  it sends. No live Jev call was made; every wire fact is documented, not
  observed.

- **Setup and execution guidance now agree with their existing boundaries.**
  Setup workflows use secure native or user-side credential entry and redacted
  approval previews instead of requesting secrets in chat or promising that
  chat input is never retained. Maestro distinguishes choosing an executor
  from authorizing it to run, while an explicit owner-and-execute request can
  supply both without a second confirmation. Ultrawork excludes conflicting
  parallel writers, not its supported single-owner or ordered execution modes.
  These are generated-guidance corrections; no routing, dispatch mechanism,
  public skill name, configuration option or runtime permission gate changes.

- **The Claude subagent calibration no longer tells the model to keep
  working.** The high-effort `claude` block said "No one is watching this
  unit in real time: proceed on every reversible action inside the boundary
  without asking, and if your last paragraph is a plan, a question, or a
  promise, do that work now", which breaks the rule that no calibration
  sentence may push the model to keep working. That sentence is removed and
  nothing else in the block changes. Measured on `og` /
  `anthropic/claude-fable-5-1` at `xhigh` over the 30-instance evaluation
  split of `benchmarks/live-model-tools/v1`: 18 / 30 before and after, the
  same instances, and 2,641,559 harness tokens against 2,760,212 and
  2,955,008 for two runs of the old text. The per-instance delta against
  their mean is −7,202, CI95 [−15,422, −47]. The composer block loses its
  two sentences of the same kind, "keep working while delegated units run"
  and "If your closing paragraph is a dispatch you could run, run it before
  closing"; that deletion is unmeasured, because the benchmark runs one agent
  with no fanout and never reaches the composer path (#1836 tracks one).

- **The Jev plugin posture follows the `hermes-jev` rename to `nerve`, and
  knows `jev-curator`.** An open upstream catalog change (hermes-agent #119045,
  read at its head on 2026-09-23, not merged) renames the community plugin
  `hermes-jev` to `nerve` and its `jev_*` tools to `nerve_*`. Once that lands,
  neither signal OMH classified on would fire -- the name was not in the table
  and the tools no longer carry the `jev_` prefix -- so `plugin_jev_sidekick`
  would report the plugin absent and the `jev_plugin` answerer rung would
  disappear from route questions. `nerve` is now a known record, labelled as
  read from the open PR, and its `nerve_` prefix counts as Jev-class for that
  name alone; another plugin's `nerve_` tool does not classify that plugin. The observed
  tier, which sees a dispatched tool name without its plugin, counts only the
  exact `nerve_` names the entry declares. `hermes-jev` stays known for
  machines that have not updated. `jev-curator` (plugin-catalog, added
  2026-09-21) now reports `known: true` with its catalog disclosure instead of
  `known: false`. The routing-questions benchmark README says how an operator
  drives an installed Jev plugin over the exported corpus to produce an
  external arm; OMH still never calls one.

- **Claude Opus 5.5 and GPT-6 Luna take their predecessors' shipped slots.**
  `claude-opus-5-5` replaces `claude-opus-5` in `unspecified-high`,
  `unspecified-low`, `capable`, the `main` role suggestion, and the shared
  last-resort order, and `gpt-6-luna` replaces `gpt-5.6-luna` in `quick` and
  `simple-work`, each at the same position and effort. The Claude vendor order
  stays Fable 5.1 before Opus. Both superseded ids leave the shipped chains and
  stay recognized, priced, and provider-mapped, so a machine whose provider
  serves only the older id keeps it with `omh model-chains set`. The placement
  is editorial and unmeasured; the old-vs-new pairs are the follow-up.

  Both ids gain exact contracts read from the vendors' pages, the first for a
  Claude model: Luna's route sends a no-reasoning request as `none`, its
  documented rung, whether it was spelled `none` or `off`, and
  `omh coding model-route` raises a no-thinking request for Opus 5.5 to
  `low` because the API rejects disabling thinking, which
  `omh_delegate_route` now refuses for it as it does for Fable. The Hermes
  lane's named-model branch now applies every exact contract's floor, so GPT-6
  Astra asked for `off`, `none`, or `minimal` there is raised to `low` on
  record, as the catalog lane already did. New price
  rows follow the documented lists, and three stale GPT-5.6 rows are
  corrected to the vendor pages: Luna to $0.20 / $1.20, Terra to $2 / $12,
  and Sol to $4 / $20, which OpenAI labels promotional through at least
  2026-11-21 with no later price published. No calibration text
  changed: neither shipped placement reaches the subagent high-effort tier,
  and the Claude blocks stay byte-stable.

  The loop itself was corrected where it contradicted its own rule. The
  `model-optimization` skill still told a runner that an older generation
  stays as fall-through; it now states the superseded-generation rule and the
  four source labels. The shared-final-order sentences in the installation,
  architecture, and model-routing docs are now checked against the catalog,
  and each retirement records its own decision date and is checked out of both
  lanes. The Maestro docs note that Claude Code's `opus` alias reaches Opus 5.5
  only from v2.1.280 and resolves to Opus 4.6 on Microsoft Foundry.

- **A stop now ends the turn with the next action offered, not with a
  refusal.** Runs on the executing engines closed with sentences like "I will
  not merge or force-push here": the follow-up authority rule said to describe
  a follow-up and wait for approval, but not how to close, and the closing
  brief rule listed "follow-up declarations" among the bookkeeping not to
  narrate, so the model stated what it would not do and the person saw no
  next move. The follow-up authority rule now ends the turn by naming the next
  action and asking whether to take it, as one question carrying the choices
  the user has; the closing brief rule ends a boundary stop with that offered
  action and states what was left undone as the option it leaves open; every
  generated skill's tail carries the same sentence beside its stop condition,
  and the common rail has a Turn Ending section with the before-and-after.
  The wrapper copy for the file-lookup and direct-answer states is reordered
  in every locale so it ends on the action rather than on "does not start an
  OMH workflow". The per-skill byte ceiling moves 26,000 -> 26,500 for
  `ultrawork`, with the reason at the entry.


- **A Hermes child now receives its prompt.** `omh coding hermes-child
  dispatch` spawned `hermes --oneshot -` and wrote the prompt to stdin, but
  Hermes' `-z/--oneshot` takes the prompt as its positional value and reads no
  stdin, so the child answered the literal prompt `-` with a greeting, exited
  0, and billed the routed model for it. The child is now
  `hermes chat --query-file - --quiet`, the one Hermes transport that reads a
  prompt from stdin; the prompt still never enters argv, and `--quiet` keeps
  a completed turn's stdout to the final response as `-z` did. A start Hermes
  refuses before the turn, because the child sees no provider, now prints
  Hermes' first-run guidance on stdout and exits 1 where `-z` printed one
  stderr line; the child's exit code and the literal verdict tags are what
  callers read, so that text is a failed dispatch, never a result. Hermes
  writes its `--usage-file` report for `-z` alone, so the observation's
  `usage` is empty on this transport rather than a number it did not measure;
  paired-run, final-review, and the live-model-tools isolated-child arm reuse
  the same child and inherit both changes, and the docs of each say so. The
  test fakes now model the real CLI (`--oneshot` reads argv, never stdin), so
  the old argv fails the suite instead of passing it (#1824).

- **Setup no longer writes a `plugins.enabled` Hermes cannot read.** A config
  carrying `enabled: '[]'` is a string to YAML and no plugins to Hermes, and
  setup inserted `    - omh` under it, which YAML refuses (`did not find
  expected key`); the same insert under `enabled: null` or a plain word folds
  the item into the string, so Hermes loaded nothing and said nothing. Setup
  now classifies the value first: a null or a quoted `[]` carries no member and
  is normalized to a block list, an inline list is expanded as before, and any
  other scalar stops setup with the file untouched and `hermes plugins enable
  omh` named as the repair. The line reader stops attributing items under a
  scalar to the key, and `omh doctor` reports a file already in that state as
  the file it is rather than as an enabled plugin. A new
  `hermes_config_plugins_enabled` check carries the same sentence setup
  refuses with, so a home where setup stopped before installing the bundle
  still names the cause instead of only its side effects (#1825).

- **A board readback is now measured after it is serialized, and is no longer
  run through diff padding.** The ceiling that keeps `kanban_show`,
  `kanban_list` and `kanban_attachments` inside the context budget was applied
  to the record before it became JSON, so a board whose text needed escaping
  crossed the budget by whatever the escaping added. It is measured on the
  bytes the host actually receives, and a readback that is cut says so, with
  the fields it dropped named rather than silently absent.

  The same records were also passing through the diff band-padding path, which
  splits on line boundaries and writes literal newlines back. A board carrying
  a Unicode line separator therefore split inside a JSON string and came back
  as invalid JSON. Kanban records are excluded from that padding, which is what
  the padding was always for: diffs, not structured results.


- **An engagement nudge now counts what a tool call did, not that it was
  made.** The counters behind the plan and delegation nudges were incremented
  from the fact of a watched tool call, so a write that the host refused, a
  patch that applied nothing, and a write that landed all moved the same
  threshold by the same amount. `_mutation_effect` now classifies a file
  mutation as `landed`, `partial` or `unknown` from the same two facts Hermes'
  own `file_mutation_result_landed` reads, and only `landed` advances the
  threshold; the other two are counted under their own fields so the difference
  stays readable rather than disappearing.

  The read side gains the same distinction. A pre-dispatch refusal is not
  search effort, so a `blocked` status no longer bumps the direct-read counter,
  and a call whose arguments could not be fingerprinted is declined by name as
  `unknown_read_identity` rather than counted as a new distinct read.

  The classification runs at two seams because one is not enough on the real
  host: the executor suppresses the inner post-tool hook for a delegated call
  while `transform_tool_result` still fires inside it, so a design that watched
  only the post hook would have seen nothing for exactly the calls a delegation
  nudge is about.


- **Accepted native work can be resumed from a bounded scope checkpoint, with
  durable verification, review and QA declarations.** `omh_todo` adds
  `checkpoint`, `record` and `recall`; no new engine or router state lookup is
  introduced. A checkpoint freezes the owning session's accepted todo items
  and separately records rejected ideas. Later sessions in the same profile
  and logical project can read it without changing a checklist or resuming work.
  Result rows preserve claimed source, revision/environment, findings and
  existing `verification_receipt/v1` references without turning a model claim
  into an observed result. Missing, stale, malformed and declared-empty sources
  remain distinct. Storage is capped; full stores refuse rather than evict.
  Existing close/verification/review/QA guidance now exposes this callable path
  to Hermes model selection, without adding language-specific triggers or a
  mandatory story template. Offline native fixtures cover registry, bridge,
  lifecycle, storage and the composed #1794 approval boundary; live semantic
  model adoption remains untested. No edit approval, receipt issuer, CI
  observer, merge authority or new task execution runtime is added.

- **Hermes replies under OMH are written in the user's words and the host's
  own voice.** People were reading OMH's record vocabulary back in chat ("this
  is an evidence-bounded surface", "prepared_not_observed", "wrapper",
  "handoff", "evidence boundary"), and nothing told the model that those terms
  belong to records and tool calls rather than to the sentence a person reads,
  or that the host's `SOUL.md` owns the voice. Every generated skill's tail now
  says so in one sentence, the common rail gains a Reply Language And Host
  Voice section with plain substitutes ("prepared, not run yet", "not checked",
  "handing the coding work to X", "this shows X and does not show Y") and the
  rule that awareness lines, route hints, and first-response shapes are
  instructions never quoted to the user, both awareness primers carry the same
  line, the closing brief rule leads "in the user's words", and the shared
  purpose line of the operator skills ("a structured, evidence-bounded OMH
  operating surface instead of ad hoc narration") becomes "a structured,
  checkable answer instead of an improvised one". Budgets move with the reason
  at each entry: the compact primer 900 -> 1,050, the markdown primer
  3,210 -> 3,400, the per-skill ceiling 26,500 -> 26,800, and the full-profile
  ratchets re-derived from their producers.
- **A hand-written portable override now learns when the catalog section it
  replaces has moved.** `PORTABLE_OVERRIDES` (12 skills, 28 sections) replaces
  catalog sections wholesale for the Agent Skills projection, which is the
  right mechanism -- a Hermes-shaped line has to be rewritten by a person -- but
  no test read the table, so a line added to an overridden section was absent
  from `agent-skills/<skill>/SKILL.md` with every gate green and nothing
  recording that a decision was owed. `docs agent-skills --check` cannot see it:
  it compares shipped bytes against a projection that already applied the
  override, so it agrees with the override by construction. Two producers in
  `src/skills/catalog_portable.py` now report a sha256 per replaced catalog
  section and the entries that no longer resolve, pinned by
  `tests/fixtures/portable_override_source_digests.json` and asserted in
  `tests/test_agent_skills_projection.py`. A moved section fails naming the
  `<skill>::<section>` entries, so the author re-reads that decision instead of
  diffing 28 tuples; re-pinning without editing the override is the valid
  outcome that records a deliberate choice not to mirror a line. The failure for
  an entry that stops resolving carries its reason, because the two halves
  behave differently at projection time: a dropped skill is looked up by display
  name and silently misses, while a renamed section raises an `AttributeError`
  out of rendering that names only the field. No override text and no projected
  byte changes.

- **A bounded Kanban readback no longer contradicts itself.** The label line is
  the first thing a model reads, and it printed a bare 64-character prefix of an
  oversized task id while the JSON beside it listed that same id under
  `omitted_fields` -- the second identity `docs/KANBAN-READBACK-CEILING.md`
  promises is never manufactured. Label values now carry `...[truncated by omh]`
  inside the 64-character cut, and a field the projection omitted is named
  `<omitted: too long>` rather than quoted as a prefix of itself, with the
  `kanban_show` label read off the projected records instead of the originals.
  A row list that is not a list of objects is reported as one: it is named in
  the new `omh_readback.malformed_rows` and in the label (`tasks not read
  (malformed row list)`), it is not counted as dropped, and a projection leaves
  the key out rather than writing `[]`, which rendered 62 host rows as an empty
  board under a `0 of 0 tasks shown` label. A `kanban_show` whose `runs` cannot
  be read says so instead of reading as a task that never ran; an empty list and
  an explicit `null` stay ordinary absence. Both projection tiers are now
  measured after rendering rather than the core one being returned unmeasured,
  and a core projection that does not fit falls to an identity tier
  (`projection = "identities_only"`: root `ok`/`error`/`task_id`, the task's id
  and status, the latest run's id/outcome/status, no rows) whose size is fixed
  by its field sets rather than by the input -- measured at 3,556 characters
  against the 24,000 ceiling at the worst escaping the 256-character scalar cap
  admits. The row-drop accounting gains its own tests: the tracked size no
  longer subtracts a list separator for the last row, which put it below the
  payload it stands for, and the dropped prefix leaves in one slice rather than
  one `pop(0)` per row. None of this is reachable from the shapes the pinned
  Hermes host emits today; it is the last-resort path the ceiling falls back to.

- **A `plugins` node written on its key line no longer reads as "nothing is
  enabled".** `plugin_enablement` entered Hermes' `plugins` node on one
  condition, a top-level line whose text was exactly `plugins:`, so the flow
  mapping `plugins: {enabled: [hermes-jev]}` and a `plugins:` line carrying a
  comment both left the same empty lists a config enabling nothing leaves.
  Every caller then stated "not enabled" about a plugin the host loads. One
  classifier now answers for that node and the reader follows both forms
  Hermes loads; a corpus of fourteen readable nodes is pinned against the
  answers Hermes' own PyYAML gives them. A node outside those forms -- an
  alias, an anchored block, a repeated key, a file YAML refuses -- reports
  unread rather than empty: `omh doctor` returns `plugin_enabled_in_hermes`
  as an unobserved warning naming the node instead of telling the operator to
  enable a plugin that is already on, and the uninstall report says
  `plugins.enabled` was kept rather than absent. Setup gains one refusal to
  match the remover, which already declines every `plugins` node that is not
  the plain block: it used to find no `plugins:` line under a flow mapping and
  append a second top-level `plugins:` block, and a duplicate top-level key
  resolves to its last value, so the operator's own list was dropped with no
  error anywhere. The plugin bundle's routing-tier reader is unchanged and
  still under-reads the flow form by one tier; it cannot import the core
  reader, and it states no enablement.
- **A reply lint turns the reply rules into checkable evidence.**
  `omh quality-evidence reply-lint` reads the sentence a person read (a file,
  stdin, or the trailing replies of a Hermes session, opened read-only) and
  reports `record_term_leak` (the rail's record vocabulary plus the Korean
  renderings read in live replies, `표면` and `레인`), `awareness_line_quoted`
  (`[OMH Awareness]`, `Boundary:`, `Route hint:` lines), `refusal_closer` (the
  closing paragraph declares what will not be done and offers no question), and
  `decision_without_question`. A term the user named is carved out, only the
  closing paragraph decides the closing findings, and a finding exits 1. The
  `reply_lint/v1` payload carries its own claim boundary: a clean result is not
  evidence that the reply was correct or in the host's own voice.

- **Wrapper cards now say what they hold and what they leave out, in the
  reader's own words.** All 79 `ChatCopy` headline/body entries in the
  localized card table are rewritten across their seven locales (en, ko, ja,
  zh, es, fr, de): no first-person voice competing with the host's `SOUL.md`,
  no OMH record vocabulary (`workflow`, `picker`, `handoff`, `lane`,
  `wrapper`, `observed`, `prepared`), and each evidence limit stated as "this
  shows X and does not show Y" instead of as a refusal to claim. The two cards
  whose bodies were instructions addressed to Hermes rather than sentences for
  the reader -- the file-or-text lookup and the direct answer -- now describe
  what the card does and what the reader can supply, and both now reach an
  English reader at all: their English body came from the router's constant
  fallback clarification, so the sentence Discord and Slack printed was
  "Answer this as a file or text lookup..." rather than any card copy. Those
  two cards render their copy in every locale now, and the Hermes-facing
  instruction keeps the `routing_instruction` and route-explanation fields it
  already had. `card_copy_voice_violations` re-derives both rules from the
  table itself, so a card added later is checked without anyone enrolling it:
  run against the
  table as it stood before this change it reports 173 violations spread over
  all twelve cards and all seven locales, and none after. The first-person
  half is a regression list rather than a grammar checker, and says so at the
  list: four of the seven languages drop the subject pronoun, so what gives
  the speaker away is a verb inflection, and no short list of inflections is
  complete. Two headlines change on the wire and their pins move with them:
  the direct-answer card reads "This can be answered directly in the chat."
  and the research card "Source-backed research can ground this.".
  Wrapper-facing text produced elsewhere -- the operating-brief cards and
  inline headlines in `omh.wrapper.contract`, the session ladder in
  `omh.wrapper.sessions` -- is outside this change and still carries the
  shapes the new rule rejects. The routing-inertness fixture is re-pinned
  with the rewritten headlines: 103 of its 237 pinned rows move and
  `observed.plain_headline` is the only field that differs on any of them,
  so `observed_digest` moves for the first time without a verdict moving.
  That corrects a claim beside it -- the projection was described as carrying
  only the router's output, and it also carries the card's headline and
  boundary, which a card picks after the route.
- **`observed_check_results/v1` is declared once, and every surface renders
  it.** `verification-gate` stated the row's shape twice in its own body and
  the two disagreed: a quality-bar line asking for command/source, freshness,
  exit status and scope, and an artifact expectation asking for command,
  timestamp/source, exit status, summary and a stale-output flag. `omh-wiki`'s
  handover table named two of the fields, and a fourth restatement was written
  before review caught it. Nothing could fail, because nothing was derived; a
  consumer recorded whichever copy it read, and the field that went missing was
  freshness, the gate's own guard against reporting a stale output as evidence.
  `src/evidence/observed_check_results.py` is now the one declaration. The
  reconciliation keeps both disputed fields rather than picking a list: `scope`
  (what that run covered) and `summary` (what the output said) both stay,
  `freshness` is the single name for what was freshness on one line and a
  stale-output flag on the other, and `source` becomes a field of its own,
  because the same command proves different things run in this checkout, in a
  CI job, and in a person's report. Each field a reader cannot infer renders
  with its meaning beside it, so a surface quoting the row cannot quote a name
  without its definition. The gate's artifact expectation, its quality-bar line
  (which now points at that expectation instead of listing the fields a second
  time), the `omh-wiki` and `todo-checklist` handover tables, and `ulw-qa`'s
  manual test guide all render from it. `tests/test_observed_check_results.py`
  scans every rendered body and reference that names the row, fails a line that
  enumerates the fields without rendering them, and runs the two drifted lines
  through that same scan to show it fires. Budgets move with the reason at each
  entry: the full capability section 422,817 -> 422,908 and the full-profile
  skill bodies 1,029,426 -> 1,029,724, both re-derived from their producers.
- **Session usage shows which Hermes surfaces OMH actually reaches.**
  `omh quality-evidence session-usage` reads Hermes' own `state.db` read-only
  and reports, per `sessions.source` tag (`tui`, `cli`, `desktop`, `oneshot`,
  ...), sessions, tool calls, `omh_*` tool calls, sessions with at least one,
  `skill_view` loads and OMH skill loads, with the per-name breakdowns. Every
  count is over distinct `tool_call_id` per session, because a compaction
  re-persists tool rows under new ids; the OMH-skill signal is the catalog's
  `[omh] ` description prefix in the `skill_view` result rather than the
  `omh-` display name, since the `ulw-*` skills are OMH skills too, and a
  name-only result (a reference-file load, a compaction placeholder) counts
  when it names a catalog skill. Archived and hidden sessions are included,
  `--since` takes an ISO-8601 timestamp or epoch seconds, `--source` keeps
  one surface (`(none)` the untagged sessions), and an empty window exits 0
  as an observation while a missing database exits 2. The `session_usage/v1`
  payload carries its own claim boundary: it is not execution, review, CI, or
  merge evidence. `reply-lint --hermes-session` gains the same `--source`
  filter: `latest` resolves to the most recent session with that tag, an
  explicit id whose tag differs or cannot be checked is an error rather than
  a silently ignored flag, and the payload records `source_filter`.
- **The plugin bundle ships a Hermes Desktop half.** The OMH status line and
  plan todo rendered only in the modern TUI, through the widget Hermes Desktop
  does not load; the app's extension point is a unified plugin package. The
  bundle now carries `dashboard/plugin_api.py`, which Hermes' web server
  imports by path inside the gateway process and mounts at
  `/api/plugins/omh/hud` while `omh` is in its `plugins.enabled` (the
  registration `omh setup` and `omh update` write); it answers with the same
  `omh_hud/v1` payload the widget renders, read for the gateway's own Hermes
  home and the session the app names, a reader failure as a 200 error record
  the pane can label rather than a raise it could not tell from a transport
  failure, and concurrent first polls share one load under a lock. Beside it,
  `desktop/plugin.js` is an uncompiled ESM plugin written for the app's
  disk-plugin loader: it polls that route every 5 s while the gateway is open
  and draws the payload as a structured `omh` pane and a compact status-bar
  item (see the entry below), never a value the reader did not produce; it
  ships off, as the app requires of unified-package halves, and the switch is
  under Capabilities -> Plugins. `dashboard/manifest.json` is also read by the
  browser dashboard (`hermes dashboard`), which registers a tab for every
  manifest, so it is marked `tab.hidden` and the browser dashboard gets no
  `omh` tab. Observed: a live `hermes serve` logged the mount and answered 200
  on the route, and node drove the renderer file with the SDK shims replaced
  by recording fakes, and the built Hermes Desktop app, launched against an
  isolated home with the renderer file placed by hand as a standalone disk
  plugin, showed `[omh] vunknown | plugin:ready | coding-agent:not-selected`
  in its status bar; the app's own copy into `desktop-plugins/omh/` and the
  rendered pane are by construction from Hermes' loader source, not observed.
  `pyproject.toml` ships the three files (the backend as a `dashboard`
  subpackage, the renderer file as package data, so no Python package marker
  lands in the folder the app copies), `omh update` refreshes them through the
  existing bundle manifest, and `omh doctor` gains a non-blocking
  `plugin_desktop_half` check that warns an older bundle toward `omh update`
  and never claims the half is enabled.
- **A Hermes home registered at the pre-pointer skills path is migrated to
  the generation pointer instead of keeping both.** A bot profile registered
  at `~/.omh/skills` before the command install moved to its shared
  generation pointer was carried forward by `omh update`, which added the
  pointer beside the older entry and retired nothing. Hermes refuses a bare
  skill name that resolves to two different files across
  `skills.external_dirs`, and every generation refresh made the two copies
  differ, so after each update every OMH skill present in both failed to
  load by name in that bot (#1857; on the owner machine `profiles/miku`
  recorded `Ambiguous skill name 'omh-model-setup'`). `_apply_result` run
  from the installer-managed command now retires every other OMH-managed
  entry in the same config write that registers the pointer, so the home
  ends registered at exactly one managed path. Entries are matched by real
  path, the rule Hermes resolves them by and the one the readers below
  count by, so an older entry spelled through `~`, a trailing slash or a
  symlink is retired too rather than reported as an ambiguity `omh update`
  could never clear. A directory the person registered themselves is never
  touched, a home naming no managed directory stays opted out, and a
  command that is not the installer-managed one (a checkout, a pip or uv
  tool install) stays additive and never retires the pointer, so it cannot
  move a machine backwards. The apply step and every profile row carry
  `registration` (`migrated`, `added`, `unchanged`) with the entries
  retired, and update prints one line per home that moved. `omh doctor`
  gains `external_dir_ambiguity` for the primary home and one row per
  affected bot profile: a warning naming both paths and the consequence,
  counting only directories present on disk (Hermes skips a missing one),
  with `run \`omh update\`` promoted to doctor's headline next action.
  Update re-reads every home after the write and prints the same sentence
  as a warning line for one it could not retire; that residual state does
  not move the update's exit code. The pre-pointer copy on disk is not
  deleted: no manifest records it, and on a managed install it backs the
  always-retained `bootstrap-legacy` generation (the self-update rollback
  target), which only `omh uninstall` collects. Doctor reports it as
  unregistered but retained (`external_dir_unregistered_copy`) and calls
  it safe to delete, with its directory mtime, only when no home registers
  it and no generation links it. Update also names the gateways whose last
  recorded start precedes this update, from Hermes' own files: a
  `gateway.pid` record for the home plus a `gateway-starts.log` last start
  earlier than the bundle manifest's `installed_at` (rewritten by every
  update) prints `Hermes gateway for <home>: last recorded start <ISO>
  precedes this bundle's install (<ISO>); run \`hermes [--profile <name>]
  gateway restart\``. The pid record's `start_time` is Hermes' PID-reuse
  fingerprint (psutil `create_time() * 100` on macOS, `/proc/<pid>/stat`
  field 22 on Linux), never a wall clock, and is pinned as not read; a
  ledger line that is not a finite positive number, or bytes that are not
  UTF-8, yield no hint rather than a traceback. No signal, no process
  listing, no subprocess.
- **The Hermes Desktop pane draws the HUD the way the TUI widget does, in the
  app's own language.** The first pane dumped `display.widget_lines` and
  `display.todo_lines` as monospace text: no colour, wrapped mid-token, and
  no word on which model any agent ran, which the owner set beside the
  modern-TUI widget and rejected. `desktop/plugin.js` now renders the
  structured payload: a header with the `⚚ OMH` mark, the version badge and
  the widget's state label (`ready`, `3 agents · 2 running · 1 blocked`); the
  main session's model and usage from the app's own state (the payload names
  a model only per subagent row); the widget's header chips (repeat guard,
  board counts, `dispatcher not observed`, open tools, yolo, summed tokens)
  as badges (the parallel-shot badge among them); a full-width hairline;
  a PLAN section (`PLAN`, the title, `done/total`, a progress bar, the TUI's
  eight-item window with earlier/later folds, each phase as its own bold
  header row with its own `done/total` -- the current phase in the label
  colour -- and its items hanging under it behind a left rule: `●`/`✓`/`○`
  glyph, the text wrapping under its own start, done items struck through,
  `waiting: …`/`skipped: …` in warn and `unchanged …` in quaternary each on
  their own line); a hairline; an AGENTS section that up to 480 px of pane
  width stacks three lines per agent (state glyph, `sub`/`bot`/`main` tag,
  8-char id, the action title on one line with an absolute path shortened
  to `…/last/two` and the full text in a tooltip; the route identity in the
  widget's own shapes -- `category:architect(model:effort)`,
  `inherit(model:effort)`, `(codex/maestro model)`, `kanban/assignee` -- with
  the state word; elapsed · tokens · cost) and past it lays the same cells
  out as one aligned grid under a row of column labels, 26 px rows with an
  alternating band; rate, `cache N%`, ctx, `turn N (M tools)` and fallback
  live in the row's tooltip; the plan column is capped at 640 px; the DAG block
  while a graph is active; and a quiet footer notice: a reader error record
  replaces the body with it, a transport failure keeps the last payload
  under it.
  The status-bar item is compact -- `⚚ 3 agents · 2 running · 1 blocked ·
  3/6`, `⚚ ready` when idle, the detail in its tooltip -- and reveals the
  pane on click; it renders nothing before the first answer, like the Kanban
  count. Every colour is a theme token through a stylesheet the plugin
  appends on register and removes on dispose (Tailwind never scans a disk
  plugin), and the mono cells (ids, route identity, chips, version badge)
  name the app's bundled JetBrains Mono ahead of the theme's mono stack;
  the route identity wraps only at its grammar's seams, never
  inside a model name; the formatters (`tokenCountText`, `elapsedText`,
  `costSegmentText`, `routeIdentity`, `hudStateLabel`) are the widget's,
  ported and pinned against its examples; the poll keeps the previous answer
  while refetching. Observed: node drove the file with the SDK, React and
  JSX shims replaced by recording fakes, and the built Hermes Desktop app,
  launched against an isolated home whose recorded session held a six-item
  plan declared for it, one running delegation child seeded from the
  recorded one, and a two-task board another teammate had placed there,
  showed the structured pane at 330, 667 and 900 px and the status-bar
  count with no boundary error.
- **The README and site demos show an ultrawork run on both surfaces.** The
  Hermes Desktop tile now plays a real session: the prompt goes in, the plan is
  declared, three lanes fan out, and the OMH pane lists each lane's route
  (`category:writing(kimi-k3:medium)`, `category:deep(gpt-6-sol:medium)`,
  `category:capable(claude-fable-5-1:medium)`) beside two `bot` rows the
  kanban board dispatched to a bot profile. The Hermes CLI tile plays the same
  prompt in the modern TUI, with the `[Plan]` dock above and the HUD rows below.
  The site's CLI card, which played `omh setup`, now plays the TUI run, and
  its Desktop card plays the new Desktop session; the `omh setup` video files
  under `site/assets/` are removed since nothing referenced them any more.
  Captions on both surfaces (and their ko/ja/zh strings) say what the clips
  show. The clips were recorded on 2026-09-25 against an isolated Hermes home
  with the owner's provider; the Fable and Sol routes in the Desktop clip were
  chosen by the category chains and then re-dispatched on the served model,
  which the session narrates on screen.
- **A Hermes child on the chat transport reports its tokens and cost again.**
  Since #1830 the child spawned by `omh coding hermes-child dispatch` runs as
  `hermes chat --query-file - --quiet`, and Hermes writes its `--usage-file`
  report for `-z/--oneshot` alone, so the observation carried `usage: {}` and
  paired-run cells and `--final-review` lenses showed no tokens or cost. The
  numbers were never lost: every API call of the turn queues its token deltas,
  priced cost, `cost_status` and `cost_source` into the child's `sessions` row
  of `HERMES_HOME/state.db`, drained when the turn finalizes and again when
  the quiet CLI exits, and the dispatcher hands each child a disposable home of
  its own. After the child exits and before that home is removed, the
  dispatcher now reads every `sessions` row there, read-only, and sums them
  into the `-z` report's vocabulary (`input_tokens`, `output_tokens`,
  cache and reasoning counts, `total_tokens`, `api_calls`, `model`,
  `provider`, `estimated_cost_usd`, `cost_status`, `cost_source`), which the
  observation builder already turns into `tokens`, `cost_usd`, `cost_status`
  and `cost_source`. `--format stream-json` was measured and not chosen: its
  terminal record carries tokens but no cost, and every tool result of the
  turn would land on stdout ahead of it. The prompt still never enters argv,
  nothing beyond the final response is read from stdout, and `usage` stays
  empty, never zero, when the ledger records no API call or the file is
  missing, not a database, or shaped differently; text columns are bounded
  and screened the way the removed usage-file reader screened them. The
  coupling is recorded in `CONTEXT.md` (Host surfaces OMH reads) beside the
  lease registry. The test fakes now leave a real SQLite `sessions` row in
  the disposable home, so the dispatch suite proves the numbers travel end to
  end and the CLI observation carries them (#1831).

- **`omh codegraph tests --changed <paths...>` names the tests a change
  reaches.** Picking "the smallest test that proves the claim" was left to
  judgment, and this repo's own notes record a hand-picked subset missing a
  gate four times in one session. The new subcommand walks the
  `imports_internal` edges the codegraph scanner already builds backwards from
  each changed path and lists every `test*.py` module under a tests directory
  that those recorded edges reach, with the import distance, as text or
  `--json` (`codegraph_test_selection/v1`). A changed package `__init__.py` is
  credited with the importers of every scanned file under its directory, since
  importing any of them executes the `__init__` and the scanner records no
  edge for that. A module nothing imports is reported as such rather than
  expanded into the whole suite; a non-Python, directory, deleted, or
  unscanned path is classified, not dropped; each entry keeps the caller's
  spelling with the resolved path beside it, naming a symlink or case-variant
  spelling; the non-test files in the closure and the scanner's own warnings
  are listed so a hub explains a wide selection and an unparseable test is not
  silently absent. Exit status is 0 whenever the graph builds and every path
  resolves inside the repository. Every payload carries a fixed `blind_spots`
  block (dynamic imports, fixtures loaded by path, generated artifacts gated
  by byte comparison, helpers importable only through an extra `PYTHONPATH`
  root, package roots that extend `__path__`, spawned commands, non-Python
  changes) and a `claim_boundary` saying the subset is a starting point and
  never a substitute for the full suite. Pure traversal: nothing is imported,
  executed, or spawned. `docs/CODEGRAPH.md` now lists OMH's own `omh codegraph`
  subcommands and is linked from the README, so it leaves the navigation
  exemption list. Deriving a fanout unit's `verification_commands` from its
  `file_scope` through this selection is a named follow-up (#1697).
- **A diagnostic request queued behind a busy provider no longer holds a
  global execution slot while it waits.** `DiagnosticExecutionEngine._observe`
  took the global slot before the provider slot, so when two overlapping
  requests both reached pyright first, the two global slots were held by one
  pyright runner and one pyright waiter and ruff could not start although
  nothing ran in its place. The engine now takes the provider slot first, so a
  global slot is only ever held by a runner that is executing. This is the
  fault behind the bounded-execution test that failed three times and was
  answered each time with a wider deadline (#1599, #1755, then at 60s on
  Linux): the overlap it waits for is now guaranteed rather than scheduled, a
  new test forces the interleaving that hung, the deadline is unchanged, and a
  failure reports the observed `active` map instead of `False is not true`;
  it also releases the runners on failure, so a broken engine reports at one
  deadline rather than after every queued runner has waited out its own
  (#1790). Observed: with the interleaving forced, the previous order hung to
  the deadline 3/3 with `active={'pyright': 1}` and the new order overlapped
  5/5; the unmodified test, run 30 times on a loaded macOS host, failed once
  before the change (360s, the same traceback as CI) and the new test against the
  previous order failed 1/1 at the deadline naming the observation.

- **A verdict one session declares can be read by a later one, from the
  command line, as the declaration it is.** `verification-gate` was told to
  issue `claim_verdict/v1` as PASS, HOLD or BLOCK and never where it goes; the
  completion store #1818 added (`omh_todo action=record` / `recall`,
  `native_completion/v1`) is that place, and the wrapper guidance for
  `verification-gate`, `code-review` and `ultraqa` now names it in one shared
  sentence, so a model that reaches a verdict, a ranked finding set or a QA
  result is told to persist it under the scope checkpoint with its
  `claimed_evidence_state` kept as written; `code-review`'s policy is derived
  from the review category's entry plus that sentence, never a pasted copy.
  Nothing read that store from outside a Hermes session;
  `omh runtime verdict show [--session] [--checkpoint] [--revision
  --environment]` does, through one reader in the store module. Its
  `native_completion_read/v1` payload carries `standing: model_declaration`
  and the claim boundary at the top level on every status and keeps every row
  at `standing: model_declaration`, `observed: false`; separates a store that is
  `absent` from one that is `empty` from one that is `present`; and reports
  each kind as `absent`, `stale`, `declared_no_findings` or
  `declared_findings`, so no record and a record that declared nothing found
  never read alike. Freshness is judged only against a binding the reader
  states -- `current` or `stale` for that exact revision and environment
  inside the 30-day cap, with the `completion` projection beside it -- and is
  `unbound` with no completion judgment when none is stated; a half binding
  is refused. A store that cannot be read is `malformed` and exits 1; a
  missing one exits 0. The tool's `recall` renders through the same
  projection unchanged. `docs/HARNESS_QUALITY.md` gains a Declared Verdicts
  section and `CONTEXT.md` a Completion dossier entry. Observed: one handler
  session wrote a PASS claimed observed, a HOLD with one finding claimed
  prepared and a QA PASS, then cleared its plan; the CLI read them bound and
  unbound with the claimed states intact, and a second session's `recall`
  agreed with the bound read field for field (#1782).

## 2.0.5 - 2026-09-22

- **The cut now asks for the site rebuild its own push cannot start.** A cut
  pushes with `GITHUB_TOKEN`, and GitHub does not create workflow runs from
  events that token caused. Pages listens for a push to main touching
  `site/**`, and the version bump always rewrites `site/index.html` and
  `site/i18n.js` — so the one push that changes the advertised version was
  the one push Pages never saw. Observed on the v2.0.4 cut: `Distribution
  Release`, dispatched explicitly, was the only run on that commit, with no
  Pages run and no CI push run beside it.

  The public badge therefore kept the previous version until some later merge
  happened to touch a path Pages watches, which left the page advertising a
  release as the last surface still naming the one before it. The cut now
  dispatches `pages.yml` next to the distribution dispatch it already makes
  for the same reason. No new permission — the job already holds
  `actions: write`. That step carries `continue-on-error: true`: by the time
  it runs the tag, the release and the distribution dispatch have all
  happened, and a site rebuild that fails for a reason of its own must not
  repaint a finished cut as a failed one. It still goes red on its own row.
  The distribution dispatch above is deliberately not treated this way —
  if that one fails nothing publishes, and red is true.

- **A release body is now bounded by what the surface it is published to
  accepts.** The 2.0.4 cut tagged and pushed, ran its gates green, and then
  failed at publication: `HTTP 422 Validation Failed / body is too long
  (maximum is 125000 characters)` against a 228,212-byte section. Nothing was
  released, and the npm and Homebrew steps after it were skipped, so the
  version existed as a tag with no installable artifact. The bound that
  existed, `MAX_NOTES_BYTES`, is 262,144 — twice the limit of the surface the
  artifact is published to, which is not a bound at all, and it grew more
  likely to fire with every release that shipped more work than the last.

  `omh release notes` now trims an oversized section to whole entries plus one
  trailer stating how many it kept, how many remain, and where they are; a
  section already inside the bound is returned byte for byte, so an ordinary
  release publishes exactly its authored notes as before. The CHANGELOG stays
  the record and is never rewritten — the bounded body is a view of it. The
  length is counted in UTF-16 code units rather than code points, because
  GitHub says "characters" without saying which and the UTF-16 count is the
  larger of the two readings. A single entry that cannot fit raises rather
  than truncating inside it, since half a sentence published as a whole claim
  is worse than a refusal a person can act on.

- **A route OMH cannot decide now carries the question it could not answer,
  and an answer to it can be recorded and measured.** When the deterministic
  router reaches an undecidable route -- a script its trigger tables do not
  cover, a near-tie between two candidates, or a low-confidence score -- it
  already hands the shortlist to model selection. It now also types that
  shortlist as a question: one relative Choice over the candidates plus `none`,
  and one absolute yes/no per candidate, built by the same builder the routing
  corpora are exported with, from the handoff's own candidates so the two
  cannot name different shortlists. `omh chat route`, `omh chat interact`, `omh
  chat route-hint` (as a new top-level key of `chat_route_hint/v1`) and the
  `omh_interact` plugin tool carry it. `omh_recommend`, `omh_context` and the
  awareness rail do not, and that is a statement about wiring rather than
  policy: those three build their own payload from the awareness hint and never
  see the core route.

  Nothing about the route changes. A decidable route carries no question at
  all, an unanswered question leaves the deterministic route in force, and a
  recorded answer does not re-route anything either. What an answer is FOR is
  measurement: `omh_route_answer` writes one `route_question_answer/v1` per
  session and question under the OMH home, embedding the same
  `routing_question_answers/v1` row that `omh chat route-questions score
  --answers <dir>` already reads, so an answerer is scored against OMH's own
  corpora instead of writing into a ledger nothing reads. An answer whose
  digest names a different question is refused rather than recorded, because a
  record joined to the wrong question measures the wrong thing.

  The record names the request it answers for, not only the question. It
  carries `message_sha256` over the raw request and repeats it on the embedded
  row, so a row read out of a JSONL file still identifies its own request and a
  scorer can join on it. A caller sends the request and OMH derives the hash,
  or sends the hash when the text is not at hand; sending both with different
  values is refused, because they name different requests and choosing one
  would record the answer against a request nobody meant.

  `confidence_source` is derived from who answered, never taken as an argument
  and never called calibrated: `self_reported` when the host model answered
  about itself, `answerer_declared` when a plugin reported a number OMH did not
  observe. OMH sees only which answerer the caller named -- not the request,
  not the response, not whether anything was called at all -- and a field
  asserting a vendor's calibration would be a claim about a model written from
  a tool argument.

  The answerer ladder reports what could answer the question on this machine,
  one provable tier at a time: a Jev-class plugin whose manifest declares a
  `jev_` tool is `installed`, one Hermes' own config also enables is `enabled`,
  and one whose tool has reached dispatch here at least once is `observed`.
  That last tier is a durable timestamp in the burst ledger rather than a scan
  of it, because the entry ring holds 200 calls and a scan would report a
  plugin as never used after 200 unrelated ones. Every tier under-claims by
  construction: a config shape the bundle's reader cannot follow reports
  `installed` rather than `enabled`, and an unreadable plugins directory drops
  the rung instead of inventing one.

  The ladder is a report and never a recommendation. No text OMH injects into a
  turn names a third-party tool, and no rail was added for this: OMH warning
  about a plugin's egress in `omh doctor` while nominating it in the prompt
  would be the same product saying two things. A test pins that the prompt
  context is byte-identical to the awareness text it was always built from.

  One rollout note: the HUD reads its required tool list from the bundle's own
  `PROVIDED_TOOLS`, so an install that has not run `omh update` will report the
  new tool as missing until it does.


- **The cases that gate OMH's router are now questions anything can answer, so
  a second opinion can be measured on the same ground.** `omh chat
  route-questions export` projects both shipped routing corpora into typed
  questions: one relative Choice over the router's own candidate shortlist plus
  `none`, and one absolute yes/no per candidate. The two are deliberately
  separate questions. The Choice picks WHICH workflow and always returns one of
  its options, which is why `none` has to be one of them; each yes/no decides
  WHETHER that one workflow is what the request asks for, answerable without
  reference to the others. An answerer may pick a candidate and still say no to
  every fit, and the scorer reports that as it stands rather than repairing it.

  `omh chat route-questions score` reads answers and always includes the
  deterministic arm, so no arm is ever reported alone. It takes a JSONL file of
  `routing_question_answers/v1` rows or a directory of `route_question_answer/v1`
  records, which join a corpus item by question digest. A malformed row is
  counted and named by its line, never dropped: an arm that answered badly and
  an arm that did not answer are different results, and only one of them may be
  excluded from a denominator. Every rate is a `reported_rate` payload naming
  what it divided, so an arm with nothing to score reports `percent: null`
  rather than a confident zero.

  The deterministic arm's verdicts are the routing-precision corpus's own, read
  through two new accessors rather than re-derived. That is the whole load-
  bearing decision here. `clarify` with a named candidate is a PASS in the
  negative corpus -- the router asks one question instead of opening a workflow,
  picker, or handoff -- and the EXPECTED intervention in the positive one, so a
  single re-invented predicate cannot serve both. A measured draft that used one
  reported the shipped router as over-routing on more than a third of the
  negative controls, on a corpus this repository gates at zero, which would have
  put two OMH surfaces on record disagreeing about OMH's own router with the
  benchmark holding the wrong number. A test
  now pins the projection against `build_routing_precision_demo` case by case,
  and shows the pin failing when the verdict is replaced. That corpus's pass
  verdict on each case is also read rather than only carried: a score report
  fails by name when the corpus records a case the routing-precision gate
  fails, so a report cannot read clean while the gate reads red.

  A recorded answer joins back to its question by digest, and the digest names
  the request rather than the shortlist it produced. A digest over the question
  block alone is shared by every request the router shortlists the same way,
  which on these corpora is most of them, so a reader joining by digest would
  have scored an answer against whatever the first case behind it expected --
  an arm that answered correctly recorded as having hijacked a negative
  control. The digest covers the request and its candidates, and where a digest
  still reaches more than one case, which is where the two corpora record the
  same request verbatim, the record is reported as ambiguous and scored against
  none of them.

  The message is the join key, and the digest reports the shortlist. A question
  digest covers the candidate list as well as the request, and the candidate
  list is cut per surface -- a route hint asks about two candidates where a
  full route asks about three -- so the same request asked on two surfaces
  produces two digests and a digest-only join would drop the answer. A recorded
  answer joins by message first; the digest then says whether the shortlist was
  the same one, reported per answer as `digest_match` and counted per arm as
  `digest_mismatch`. A mismatch is scored, because the answer is about that
  request; it is reported, because an arm asked about a shorter list was not
  asked quite the same question.

  A corpus question is now built from the same place a live route builds one.
  A live route attaches a question only where it could not decide, and it
  builds it from the undecidable route's candidate handoff; the projection read
  the route's public recommendations instead, which drop each candidate's
  description and carry the route's prose reason rather than the handoff's
  machine codes. The two questions therefore never shared a digest, and an
  answer recorded on a live route scored as having answered nothing. Both sides
  now call one builder with one set of inputs. The cases a live route never
  questions -- the ones it decided -- still carry a question for the offline
  arms, and an arm answering recorded live routes is denominated on the
  undecidable cases alone, with the rest named `not_live_joinable` in each
  rate's excluded list rather than counted as questions it failed to answer.

  An answers file is written by a model or by whoever ran an external arm, so
  it is read as untrusted input. Every file is bounded before it is read whole,
  every string that reaches a report line is stripped of control characters and
  capped, because a report is an artifact somebody attaches to a PR and an
  embedded newline in an arm name forges a line in it. A row claiming the
  reserved `deterministic` arm name is refused by name rather than merged into
  a tally the report then replaces.

  No routing case was added. The projection reads the two tuples and adds
  nothing to either, because their lengths are pinned across several test files
  and a benchmark is not a reason to move a gate. The expected answer for each case
  comes from the case's own record, including the one intervention case whose
  correct answer is to open nothing and the clarify cases that pin no candidate;
  both map to `none`, which the corpora say and the projection does not decide.

  `benchmarks/routing-questions/v1` is the lane. It answers batches through
  `omh coding hermes-child dispatch --confirm-dispatch`, with the prompt on
  stdin and the answers collected from a file the prompt names, because that
  boundary reports usage metadata and never model text. It is offline by
  default and refuses a live run without `--allow-paid-live`,
  `--max-paid-calls` and `--confirm`, with a second refusal inside the library
  so importing it and calling a harmless-sounding function cannot spend
  anything. It never imports `omh`: the lane measures the product a person
  installed, through its executable, not the checkout it happens to sit in. The
  arm that runs the operator's own authenticated Hermes rather than the
  isolated child has its process directory and its `TERMINAL_CWD` both pinned
  to the batch workspace, so a model with the file toolset resolves relative
  paths there and not in the checkout the lane was launched from. Answers are
  written as each batch returns, so a run that stops partway keeps every answer
  it has already paid for, and a model-written row is narrowed to the
  documented answer keys before it is persisted. No live arm has been run, and
  running one is an operator's call.


- **`omh doctor` now says which Jev-class plugins a machine holds, and what
  each one's catalog entry declares.** Jev (TypeSafe System One) is a
  non-generative decision model: it answers typed questions and cannot write
  code, so OMH never routes it and never calls it. Community Hermes plugins do
  call it, and several ask for hooks the OMH bridge also registers — most
  sharply `pre_llm_call`, where OMH injects its route hint while a Jev skill
  router nominates a skill, so one message can reach the model carrying two
  nominations. Nothing in the CLI said that was happening.

  The new `plugin_jev_sidekick` check is appended on every run, in both
  branches: a machine with no signal reports `optional: no Jev-class plugin
  installed`, and a machine with one reports the tier reached — installed,
  enabled, or credential name present — plus one note per plugin naming the
  tools and hooks its manifest declares, the hooks it shares with the OMH
  bridge, and, verbatim, whatever its catalog entry discloses about what
  leaves the machine. Every note says "declares" and carries the artifact and
  date OMH read it from, because a catalog description is its author's
  statement and a `plugin.yaml` is whoever installed it: neither is evidence
  that the plugin ran or that any request left the machine. `omh doctor
  --json` carries the full `jev_sidekick_posture/v1` payload.

  Three local reads and nothing else: the plugin directories under
  `$HERMES_HOME/plugins`, Hermes' `plugins.enabled` list, and the variable
  NAMES in `$HERMES_HOME/.env`. Manifests go through the existing bounded
  subset reader, so a construct it does not model is reported as unread
  rather than guessed at — an unread `provides_hooks` leaves the hook overlap
  unestablished, which the check says instead of reporting no overlap, and an
  unread plugin directory stops the check from reporting absence at all. The
  credential scan reaches its names through a new `allowed` parameter on
  `env_key_names` rather than by enrolling them in `HERMES_ENV_KEY_PROVIDERS`,
  which feeds provider entitlements and would reorder mixture chains around a
  model that can never be a chain member. No value is read, anywhere.

  A read that did not happen is reported as itself everywhere, not only for
  hooks. Enablement is `enabled`, `not enabled`, or `unknown` with the reason
  attached: Hermes' `plugins` node written as a flow mapping is valid YAML
  Hermes loads and a form the shared block reader walks past, and it produces
  the same empty list a config that enables nothing produces, so the check
  says which of the two it read rather than asserting the commoner one. A
  manifest that declares a name OMH could not read is classified on its
  `jev_` tools alone, because the directory name is then a guess and a guess
  that lands on a catalog entry would attach that maintainer's verbatim
  egress disclosure to this install.

  Everything the sweep reads is bounded and untrusted. A symlinked
  `plugin.yaml` is refused and named for the reason the symlinked-directory
  guard already states, the manifest cap is taken at the read rather than
  from a preceding `stat` that a zero-length file walks past, Hermes' config
  is bounded like the manifests beside it, and a directory name — which
  passes no reader and is chosen by whoever created the directory — is
  stripped of control characters and length-capped before it reaches a
  payload field or a report line an operator pastes elsewhere.

  `ok` stays `True` in every branch, including the warning one: a third-party
  plugin an operator installed deliberately is not an OMH install failure and
  must not flip the doctor exit code. The next action is built from the
  branches that fired and names the `.env` path OMH read rather than a
  default spelling of it, and it describes an overlap as the declaration it
  is: the bridge registers eight hooks, only one of which is the nomination
  surface, so what a shared hook supports is "declares the same hook OMH
  registers" and not a sentence about what the plugin does. The check groups
  into `optional_surfaces` by its `plugin_` prefix. `Check` gains an optional
  `detail` payload, `None` for every check that carries no structured
  finding, so `observed` keeps its one meaning as a boolean.


- **OMH now recognizes a model class it cannot route coding work to, and
  refuses that work by name instead of preparing it.** TypeSafe's Jev answers
  a typed Choice, Score, or Noul over options the caller supplies and its own
  jaggedness page states it "is not trained to generate text". Until now
  `jev-1.13.0` fell to family `unknown`, inherited generic prompt discipline,
  and would have been routed an implementation unit like any other id, with
  the failure arriving from the provider rather than from OMH.

  The class is `model_class()`, read off the family, with `generative` as the
  default so every model the catalog has never met routes exactly as it did
  before. `non_generative` is refused at each surface that would hand a model
  work to write: `omh coding model-route --model jev…` answers
  `status: model_refused` and prepares no model, no effort, and no chain;
  `omh model-chains set` exits 2 and writes nothing; the operator
  category-maestro config rejects such an entry by name on read and on write;
  and a chain entry that reaches the resolver anyway, from a hand-edited chain
  document or an operator recommendation document, is skipped with a record
  naming the class while the next generative entry takes the head — on the
  catalog lane and on the Hermes editorial lane alike. The refusal of a
  requested id is decided before any catalog is consulted, so neither lane
  can route around it.

  This narrows one stated invariant and the docstring that carried it moved
  in the same commit: an explicitly requested model still wins over every
  catalog and is still never adjudicated on quality, but it is now refused
  when its class cannot do the work at all. The refusal payload carries a
  `refusal` record with the id and the kind, so a JSON consumer never parses
  a sentence to learn what happened, and the key is present only on a refused
  route, leaving every payload that routes today byte-identical.

  Recognition is the rest of the onboarding, done honestly rather than
  skipped. `jev-1.13.0` is an exact contract read from docs.typesafe.ai on
  2026-09-21, with `jev-latest` and `jev-preview` as declared alias rows
  because both move on the next release. It carries no effort ladder, and
  `model_class`, `question_types`, `max_choice_options`, and `rate_limits`
  are optional keys that do not move `model_contract/v1`, on the same terms
  `served_ids` and `limits_note` joined it. `max_output_tokens` is `0` rather
  than absent: output is typed answers billed at zero, which is also why the
  price row is `(0.042, 0.0)` — a zero is a published rate, and a missing row
  would make every run on the model report no cost at all. The bare word
  `jev` is recognized as a family, because TypeSafe sends it in the `model`
  field and a gateway spells it `typesafe/jev`, but it inherits no contract:
  no vendor page describes that spelling. Both classifier surfaces read the
  bare word the same way, so a dynamic workflow spec that names `jev`
  describes a model target rather than an agent.

  The coverage dimensions that stay `missing` for reasons of this class are
  `effort`, `category_projection`, and `provider_eligibility`, and a test pins
  that reading. `effort` is missing because there is no effort parameter;
  `category_projection` and `provider_eligibility` are missing because the
  model is in no shipped chain, which is the decision rather than an
  oversight. The only levers that would turn them green are an invented rung,
  an invented chain entry, or an `intentional_exclusion` row that would claim
  OMH deliberately does not cover a model it does cover. The same row also
  reports `data_handling` as `missing`, which is not about this model —
  every contracted model in the catalog reads the same way — and reports
  `calibration` as `covered` through the generic fallback, which records that
  the generic discipline applies rather than claiming a model that takes no
  prompt was calibrated.


- **The HUD route label drops its parent-equality token.** A lane the tool
  routed to the model the parent session itself runs rendered as
  `category:deep(deepseek-flash:high =parent)`. The token said the dispatch
  cost what the parent costs, but it compared the model named on the row
  against the parent's model, which no row on that screen shows — so the
  reader could not check the claim against anything in front of them, and on
  the owner's `deep` chain, whose head IS the session's model, it rode every
  child row. The lane now reads `category:deep(deepseek-flash:high)`: the
  category names the lane, the parentheses name the model that ran, and the
  state tokens that remain (`fallback`, `inherit`) each name an EVENT in the
  route rather than a comparison. Nothing about which model ran is lost —
  that was always the model name itself. The `read_omh_hud` payload still
  reports `same_as_parent` for a caller that holds both models; the widget no
  longer reads it, and the widget-pack gate now pins that absence.


- **A planning run that starts editing now asks the person first, instead of
  being told not to.** Give `ralplan` a prompt with implementation intent
  folded in — "ralplan implement the refactor now and open the PR" — and it
  implements. Its skill has refused that in prose since it shipped: one line
  routes a full delivery cycle to `ultrawork`, a worked example is built from
  that exact sentence and answers "stop at the reviewed plan", and a third
  says to start a follow-on engine "only on the user's explicit go-ahead".
  Routing is not what failed either; measured on
  `build_chat_interaction_payload`, the sentence dispatches to `ralplan` at
  score 12 with `next_action: present_plan`. The message reaches the right
  skill and the skill's own rule is then read past, so a fourth sentence was
  not the fix.

  `plan_stage_gate` is the enforcement that was missing. A planning run stamps
  its checklist `plan_stage: awaiting_acceptance` when it declares it
  (`omh_todo`, a new closed-vocabulary field on `omh_todo/v1`), and while that
  holds, a `write_file` or `patch` in the owning session is escalated from
  `pre_tool_call` to the host's human-approval gate. That gate is the only
  directive the hook offers that a model cannot decline — `block` becomes a
  tool result, and one measured session read 185 host refusals and repeated
  the call anyway, while `approve` is resolved by
  `tools/approval.py::request_tool_approval` and never returns to the model as
  text at all. It is also, literally, somewhere to put the question, and the
  question is the feature: *this session declared a plan and has not recorded
  you accepting it, and this call edits a file. Approving implements now;
  denying stops at the reviewed plan.*

  Nothing reads anybody's prose. Two fields decide it — the stamp, and the
  plan projection's own `established` verdict, reused rather than re-derived
  so the gate cannot disagree with the HUD about whose plan a record is or
  when it went stale. This repository has already paid for the alternative:
  the plan's stop criterion used to be matched out of item text and read
  "verify the retry is not blocked on the session limit" as blocked while
  missing "waiting on the owner's review", wrong in both directions on
  ordinary input. The guard against its return is a mutation table rather than
  an assertion about today's wording: the same call is made twice over records
  whose every word argues the opposite of what the field says, and the verdict
  follows the field.

  The approval gate is the strongest thing OMH can do to a person's turn, so
  every state the records cannot settle is silence. No record, a record this
  session does not own, a stale one, a finished plan, an unreadable home, a
  stamp this build cannot classify, a call the host named no session for, and
  every tool that is not one of the host's two file-mutating ones all return
  nothing — the discipline #1738 landed for the unarmed-wait directive,
  applied to a stronger action.

  Ownership is asked separately from freshness, and the separation is a
  correction rather than a flourish. The renderer's `established` verdict
  does not answer "whose plan is this": its identity rule reads an
  unattributable plan as BELONGING, deliberately, so a real checklist is
  never hidden from its owner on missing evidence. A gate that stops a
  person's turn needs the opposite default — and a home-wide stamped record,
  which the chat writer produces whenever the host names no session on the
  same call that carries the stamp, projects as `established` for every
  session id that asks. Reusing the renderer's verdict as ownership armed
  this gate for three unrelated sessions under review. The projection now
  states the raw fact, `own_record`, decided after transport ids are
  translated to durable keys so a comparison of raw ids cannot refuse a
  record the session does own; the gate reads that first. A stamped record
  with no owner is unattributable by construction, and refusing it loses
  nothing. Absence of the field is unknown rather than "not accepted",
  so a delivery checklist, a CLI write, and a record predating the field are
  all ungated; reading absence the other way would put this in front of every
  edit anyone makes with a todo list open.

  **An unattended run is not gated at all, and that is a decision rather than
  an oversight.** `request_tool_approval` fails CLOSED with no person present,
  so escalating on `hermes chat -q`, a webhook, or a delegated child would not
  ask anything — it would refuse the edit with the host's wording for a rule
  nobody can answer, which is how a gate meant to protect a person becomes the
  reason their automation stopped. The predicate is the one the repeat guard's
  stage two already uses, and the fallback is deliberately not the repeat
  guard's `block`: a loop that keeps running is worse than one that is
  stopped, while a session doing ordinary work is not. Cron is the stated
  exception and cannot be closed from a plugin — `HERMES_CRON_SESSION` is a
  ContextVar, never a process variable — so a cron turn reads as attended; at
  the `approvals.cron_mode` default of `deny` the edit is refused with the
  host's wording, and only a cron job that both stamps the field and then
  edits files reaches it at all.

  The `[a]lways` allowlist grain is set explicitly to the constant
  `omh_plan_stage_edit`, and the reason is not the one `request_tool_approval`
  documents for itself. That function hashes the reason into a key when it is
  given none, but a plugin directive never reaches that branch —
  `_resolve_block_from_details` calls it as `rule_key or tool_name` — so an
  omitted key is the TOOL name, and what a person's `[a]lways` would store is
  `plugin_rule:write_file`. That grain is wrong twice: it re-asks at the next
  `patch` what a `write_file` prompt already settled, and being named after
  the tool rather than the rule it would permanently allowlist that tool for
  every OMH rule that ever escalates it, including ones that do not exist yet.
  A key carrying the session, the file, or a digest of the plan would instead
  leave a dead entry in their own `command_allowlist` per session, or re-prompt
  somebody who had already answered. One line in their config, visible and
  removable, covering both file-mutating tools with one answer.

  Two honest limits. The stamp is written by the run, at declaration time, so
  a planning run that never stamps is not gated — the enforcement binds once
  the record exists, and what makes that worth building is that stamping
  happens at the compliant start of the run rather than at the tempted middle
  of it. And a run can record `accepted` without being told to; that is a
  deliberate, recorded declaration in a record a reviewer can read, which is
  what the prose rule never produced.
## 2.0.4 - 2026-09-21

- **A prepared route now names the session that prepared it, so the HUD label
  it exists to upgrade finally reaches the HUD.** `omh_delegate_route` records
  every route it writes in `~/.omh/routing/route-provenance.json`, and the
  reader uses that record to say a lane was ROUTED to the parent's own model
  rather than merely inheriting it — the shape the owner's `deep` chain
  produces, since its head is the model the session itself runs. The reader
  threw the whole history away in session scope, on the correct observation
  that a record carrying no owner cannot be claimed by one conversation. The
  TUI widget always reads session-scoped, so the upgrade had never once fired
  on screen: three children observably routed to `deep` rendered as
  `inherit(deepseek-flash:high)`, twenty seconds after the record that said
  otherwise.

  The row's LABEL came back the same way, from the one source that can prove
  it. The title column renders a dispatch goal, and it had been reading the
  host manifest — which names no session, so session scope drops it and the
  row went out blank beside its id. A child's first user row is inside that
  child's own session, so attributing it is a primary key rather than a
  timestamp guess, and the sentence is the same sentence: the manifest's
  `goal` IS the dispatch prompt, so nothing new in kind reaches the screen.
  The manifest stays unattributable and stays dropped; the fallback never
  outranks a goal that was attributed.

  The fix is the owner the record was missing, not a scope exemption. The
  tool handler already reads the dispatching session from the host keyword
  (`host_session_id(kwargs)`, the durable id `state.db` names) to scope the
  route-restore baseline, and now stamps the same id on the provenance
  record; session scope filters the history by that owner using the same
  conversation set it already selects children with, so a record another
  conversation prepared still cannot label this one's lanes.

  The field is additive-optional inside `delegation_route_provenance/v1` and
  the schema version does not move, on the same terms `session_ref` and
  `deferred_reason` joined `omh_todo/v1`: the key is written only when
  non-empty, so a writer that cannot name its session produces the record it
  produced before, and a reader that predates the field ignores it. Bumping
  the version would have been the harmful choice — every existing reader
  discards a document whose `schema_version` it does not recognise, so a
  rollback would lose the global-scope labels that work today. An ownerless
  record stays unclaimed in session scope, which is exactly what it did
  before, so no install gets a worse label than it has; global scope is
  unchanged and still reads every record, because it makes no ownership
  claim about the children it lists either. A malformed owner refuses its
  record like any other malformed field, which the loader turns into "no
  provenance" — provenance only ever upgrades a label and still never gates
  routing.

- **A change nobody can prove with a command now has a page for the guide a
  person follows instead.** `VI. Manual test guide` is a phase of the
  `code-story` plan template, and the repository owned that artifact only for
  RENDERED surfaces: `omh-visual-qa` covers listing pages, states, and
  viewports and scopes out everything else on purpose. A CLI flag, a
  migration, a config change, a daemon restart, an install on a real machine
  — none of those had a page saying what to write. The new
  `skills/ulw-qa/references/manual-test-guide.md` is that page, reached from
  one `ultraqa` quality-bar line, because `ultraqa`'s declared subject is
  test scenarios and its required inputs (changed behavior, acceptance
  criteria, known risk areas) are already the guide's inputs.

  The rule the page is built around is the one the tree already held in one
  place and nowhere else: `skills/ulw-work/references/tdd-red-green.md`
  refuses manual testing as a way to close a tests-first lane, because a
  manual check leaves no output to paste and no command to rerun. A manual
  test guide is a handover artifact and never evidence — a finished guide is
  `prepared_not_observed`, and only a run moves anything out of that state.
  Stated in `verification-gate` vocabulary so there is one vocabulary and not
  two: a written step is a `verification_matrix/v1` row with no result, and a
  person who runs it can supply an `observed_check_results/v1` row. The page
  does not restate that row's fields — it renders `verification-gate`'s own
  declaration of them, because three places in the repository already
  enumerate that row in prose and no two agree, and the field a fourth copy
  would most likely lose is freshness, which is precisely the field a manual
  run most needs and most often loses. A report of "looks fine" supplies none
  of the fields and meets the refusal the gate already applies to `works as
  expected`. The row is also where the evidence stops: OMH persists no
  verification output (#1782), so it lives in the session and nowhere else,
  the same thing `handover-artifacts.md` marks with its "Held where" column.
  `done` on the phase therefore says the guide exists, never that anyone
  followed it, and a claim citing it earns HOLD or BLOCK with the manual
  checks listed not-run.

  What the page carries beyond the boundary: the four-field step shape
  (setup, do, expect, broken — `broken` meaning the near-miss, the wrong
  result that reads like the right one), a closed list of four reasons a step
  may stay manual at all, so a step that could have been a test is named as
  one rather than accumulating in a document somebody re-runs by hand every
  release, and the `enumerate, do not sample` rule generalized off
  `visual-qa`. Sources follow `omh-wiki/references/handover-artifacts.md`
  rather than restating it: the plan record is the only one that outlives the
  session.

  `tests/test_manual_test_guide_reference.py` holds what is machine-checkable
  — the body pointer and the reference exist together, the named artifacts
  survive a rewrite, the row shape is still the gate's live declaration, the
  page points at the source table instead of copying a paragraph of it, and
  neither the page nor `tdd-red-green.md` can delete the refusal they share.
  Two limits are stated rather than implied, in the test's own docstring as
  well as here: the rule's wording is prose and no gate checks it, and the
  shared-refusal test is deletion-only — a rewrite that keeps the word
  `unobserved` and reverses the sentence around it passes, because catching
  that needs a matcher over prose and this repository does not match prose.

- **Closing a story has an owner.** The `code-story` plan template stamps ten
  phases and the last of them, `X. Close`, was the only one nothing answered
  for. `verification-gate` owns the evidence a claim needs BEFORE completion
  or merge; `todo-checklist` says a done mark is a declaration;
  `github-event-ops` labels an issue and never closes one. Nobody owned the
  act of closing.

  It belongs to `todo-checklist` now, through
  `references/closing-a-story.md`, because a close judgement that reads
  records can read the plan record and nothing else.
  `observed_check_results/v1` and `claim_verdict/v1` are instruction text:
  nothing writes them, nothing reads them, there is no store, and the same
  holds for ranked review findings and QA pass/fail. So the page is scoped to
  what survives -- `state`, `phase` and `blocked_reason` under
  `$OMH_HOME/runtime/todos/<session key>.json` -- and its source table is
  rendered from the same `HANDOVER_RECORD_SOURCES` the `wiki` handover page
  uses, so the two cannot come to disagree about which of the four is a
  record. A verdict still in this conversation is cited as a declared output
  of this session, never as something the next reader can go back to.

  What the page will not let a close claim is the part worth reading twice.
  Every phase `done` means every phase was DECLARED done; a phase `done`
  carrying a `blocked_reason` was skipped on purpose and the template refuses
  to let it leave the list; no `blocked_reason` anywhere means nothing was
  RECORDED as blocked, which is not evidence that nothing was. Landing the
  change happens outside OMH, which makes no network calls and never watches
  anything merge, so a close report names who observed the merge commit or
  the CI conclusion, or says it has none.

  **A run reaches the page through the phase template, not by asking in
  plain words, and that gap is open.** A chat trigger was built, measured and
  withdrawn. Built from `close`, `story` and a finishing word as an unordered
  token set, it dispatched nine sentences at high confidence that have
  nothing to do with a plan -- a bedtime story, a closing ceremony, a
  newspaper layout, a Jira ticket, an incident -- including two that were its
  own negative controls with one word added. As a closed phrase list it still
  matched inside "close the story book", because `phrase_is_spoken` enforces
  a right edge only for single-word phrases. And it missed four of the six
  natural phrasings of the real request, `close this story` among them. A
  trigger that is simultaneously too wide and too narrow is measuring the
  wrong thing, so none of it shipped. The measured corpus, and the two
  reasons reading a record instead cannot be the discriminator either, are
  filed as #1789.

- **The bare word `close` no longer names an accounting workflow.** A
  multi-word trigger is also scored as its separate tokens, so
  `finance-analysis`'s phrase "month-end close" handed it `close` -- a
  connection, a modal, a file handle, an estimate near a number -- and made
  it the top candidate on every sentence containing the word, including
  "close this story, it is done" at a score of 4. The token is held back now.

  An accounting request that spells the cue is untouched: "month-end close"
  is a domain trigger worth +54 through `domain:`, and the three phrasings
  carrying it hold at 54. An accounting request that does not spell it loses
  the 3 points the loose token was giving it -- "variance analysis for the
  monthly close" keeps its dispatch at 9, but "we need to close the books for
  September" and "reconcile the ledger before the close" lose the top slot in
  a clarify, and two more drop from medium to low. No accounting sentence
  lost a dispatch, which is why this is priced as acceptable rather than
  described as untouched.

- **The gate that catches a skill body change now says which body changed.**
  Editing a skill body moves a pinned sha256 in
  `tests/fixtures/agent_skills_hermes_digests.json`, and until now the failure
  was a bare dict compare over 124 keys: `Diff is 11220 characters long`, the
  elided preview lining up two unrelated skills because the produced dict is
  in catalog order and the fixture is sorted, and the edited skill's name
  nowhere on screen. It now reports `moved=[...] added=[...] removed=[...]`
  and says to re-derive the fixture sorted-key in the same commit.

  The reason this matters is that no other gate sees a body change at all.
  The ten `docs ... --check` gates compare a producer against its generated
  file, so they find DRIFT; an intended body edit moves both sides together
  and every one of them stays green. That is correct behaviour for a drift
  gate and is not a gap in them — the digest fixture is a pin, and it fired
  exactly as it should. What was missing was that the pin was undocumented in
  both places a person doing this work looks, `CLAUDE.md` and
  `docs/ADDING-A-SKILL.md`, and that its failure named nothing. Both are now
  written down, with the distinction between a drift gate and a pin stated
  where it is needed.

- **Interactive `omh setup` now asks whether OMH should watch for its own
  updates, so the capability stops being invisible.** `omh update-check set
  --mode off|notify|auto` has shipped for a while and runs from the launch
  path, but the only way to find it was to already know its name. The wizard
  now asks once, as its last question — every other group configures how the
  assistant behaves, this one configures how the install maintains itself,
  and the apply phase right after it is the answer's first reader
  (`_release_source_commit_for_state` returns early while the mode is `off`,
  so an opt-in recorded here is in effect for the same run).

  The shipped default is unchanged. `off` is the pre-selected option, read
  from `DEFAULT_UPDATE_CHECK_MODE` rather than written beside it as a
  literal, so Enter through the wizard lands exactly where `--yes` lands and
  cannot drift from it: pressing Enter must not be how a machine starts
  making network requests. `--yes`, `--json`, `--no-interactive`, and every
  run without a terminal never see the question and write nothing at all —
  the key stays absent, which is what keeps it askable later.

  Asked once, then never again, including when the answer was `off`. That
  needed a distinction `read_update_check_policy` cannot make: it normalizes
  an absent record to the shipped `off`, so "never asked" and "answered off"
  come back identical and a predicate reading it would re-ask on every
  interactive run forever. The new `update_check_policy_recorded()` reads the
  stored record instead, which is the only place the two differ, and every
  answer — `off` included — is written, so the record is the answer rather
  than the deviation from the default. A corrupt or hand-edited value reads
  as unanswered, matching what the policy reader already does with it.

  The question states both consequences it is asking consent for, in all four
  languages: `notify` and `auto` each contact GitHub at most once per 24-hour
  interval, and `auto` additionally runs `omh update`. The policy lives at
  `$OMH_HOME/setup-profile.json`, inside OMH's own home, so the default `omh
  uninstall` — which removes that home — takes it back with everything else;
  nothing is left under a host-owned root for uninstall to reverse
  explicitly.

- **The three artifacts that close a long piece of work — a deep guide, an
  ELI5 pass, and a quiz — now have written guidance, on `wiki`.** A coverage
  pass over all 124 shipped skills found these late stages unowned: `docs`
  says outright that it is not a generic documentation writer, and
  `materials-package` routes code documentation away to "the docs/wiki
  workflow", which leaves the wiki half of that pointer as the only live
  destination. `paper-learning` already had the level vocabulary and a
  coverage ledger, but its input is a supplied paper, not the change you just
  shipped. Nothing at all matched `quiz`, `flashcard`, or `exam`.

  The load-bearing rule in the new `wiki/references/handover-artifacts.md` is
  that all three are assembled from what is readable, never from what you
  remember. By the time they get written the early reasoning is out of
  context — compaction took it — and a model asked to explain a decision it
  can no longer see reconstructs a fluent, diff-consistent, invented one that
  nothing downstream can tell from the real reason. This is the rule the
  repository already applies to stop criteria, one stage later —
  `blocked_reason` exists as a field because inferring it from item text was
  wrong in both directions.

  What "readable" means is stated per source, because only one of the four is
  a record. The plan record is persisted under
  `$OMH_HOME/runtime/todos/<session key>.json` and read with
  `omh runtime todo show`: it carries `state`, `phase`, and `blocked_reason`,
  and it outlives the session. The verification, review, and QA names —
  `observed_check_results/v1`, `claim_verdict/v1`, ranked findings, pass/fail
  evidence — are declared outputs that OMH asks a model to produce and
  stores nowhere, so they live in the session's own context and are subject
  to the same compaction as the reasoning above. The page says so in a "held
  where" column rather than presenting four equal records, and tells the
  writer to record which sources were actually readable instead of
  reconstructing what is gone.

  The quiz is a completeness check on the deep guide, not a study aid, and
  its admission rule is what keeps it from degenerating into "what does this
  PR do": **every question cites one record entry, and a question that cannot
  cite one is not written.** Only three entry kinds qualify — a review
  finding, a failed check, or a `blocked_reason` — because each is a record
  of something that actually went wrong or was actually decided. A question
  the deep guide cannot answer is a hole in the deep guide, which is what the
  quiz is for. The rule's reach is stated too: only a `blocked_reason` can be
  cited durably, because only the plan record survives the session.

  An empty quiz does not claim a clean run. With three sources unstored,
  `omh_todo` opt-in, and another session's record unlinked after a day, zero
  entries is the ordinary outcome, so the quiz reports a basis drawn from
  `HANDOVER_QUIZ_BASIS` — modelled on `PAPER_LEARNING_SOURCE_STATES`, next
  door to the level vocabulary it already borrows — where "could not read it"
  and "read it and found nothing" stay different answers. Only
  `sources_read_no_entries` says anything about the change itself.

  The guidance is a reference file, so it loads on demand and costs the
  always-loaded skill pack nothing; only the pointer section on `wiki`'s body
  is paid for, and `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` moves by that section
  alone. The ELI5 pass is written at level `very_easy`, reusing
  `paper-learning`'s word rather than coining a second name for one idea, and
  `tests/test_handover_artifacts.py` re-derives every citation from the
  surface that declares it — the todo validator for the plan-record fields,
  each skill's own declared outputs for the rest. A citation also names a
  word its own declaration must carry, so swapping
  `observed_check_results/v1` for the sibling `verification_matrix/v1` fails
  rather than quietly turning observed into prepared, and the quiz's table of
  admissible entries is generated from a closed producer so no hand-written
  row can admit a source nothing declares.

- **A code story now has a shape OMH ships, and a stage it does not do stays
  on the list.** `omh_todo` takes a new optional `template`, whose
  one value is `code-story`: send it with `action=set` and the plan is
  declared with the ten phases of a code story — `I. Story`, `II. Implement`,
  `III. Review`, `IV. QA`, `V. Fix`, `VI. Manual test guide`,
  `VII. Deep guide`, `VIII. ELI5`, `IX. Quiz`, `X. Close` — in delivery
  order, one pending item each. The phases come out of the new
  `todo_templates` module rather than out of whatever the model invents that
  day, and the name is stored on the record (`template`) and projected into
  the HUD payload, so "is this a story plan" is a field a reader reads rather
  than phase labels matched back out of prose.

  The stamp is enforcement, not decoration. Every later write to a stamped
  record — a whole-list `set`, or a single-item `advance`, which now carries
  the stored name back through the same builder — is held to the same
  coverage: all ten phases present, each first appearing in template order,
  every item inside one of them. A phase this change does not need therefore
  cannot leave the list; dropping it is refused by name. The way to not do a
  phase is to carry it as `state=done` with a `blocked_reason` saying why it
  does not apply. That reason is a convention the tool description and the
  refusal text ask for, not a rule any validator can hold — a phase that was
  genuinely worked is also `done` with no reason, so what the record enforces
  is the phase's presence and nothing more. `done` rather than a fourth item
  state, for the reason the store recorded when it chose a `blocked_reason`
  field over a `blocked` state: the counts, the projection and the widget
  keep reading three states. `done` is also the only state that lets the plan
  finish — a `pending` item carrying a reason is the plan's own stop
  criterion and would halt the run at the skipped phase with every later
  phase unreached.

  A skipped phase now says so on the surfaces a person reads. The checklist
  row opens its recorded reason with `skipped:` instead of `waiting:` when
  the item is closed — nobody is waiting on a phase nobody will do — and the
  HUD payload carries a derived `counts.skipped`, the items that are `done`
  and carry a reason. Both plan headers name it: a running story reads
  `Todo · story   5/10 (3 skipped)` and a finished one
  `Todo · story ✓ 6/10 (4 skipped)` rather than `✓ 10/10`. That mattered
  because the finished panel drops every item row: the reasons disappeared at
  exactly the moment anyone would look for them, and the number asserted ten
  phases of work for a six-phase story. Only the finished line subtracts —
  the running header's numerator sits above item rows a person can count, so
  it keeps `done` — and the clause is on both so the step between them is
  something the reader has been watching rather than something that appears
  at the end. Nothing new is written to disk and no item state was added: the
  count is derived from two fields the item already has, and a plan with no
  skips renders both headers exactly as before.

  A stamped plan that runs out of item budget is told which bound it hit. The
  template declares ten of the twenty items `omh_todo` allows, so ten are left
  for work of the plan's own; the twenty-first is refused rather than
  truncated, nothing partial lands, and the refusal now appends the arithmetic
  a caller cannot do for itself — what the template holds, what is left, and
  that nothing was written. A plan that named no template reads the plain
  `todo items are capped at 20` it always read.

  Nothing detects a story from what a person typed. The declaration is the
  `template` argument on the call and nothing else, so a one-line question
  gets no phases, and a plan declared without the field is byte-identical to
  what this store wrote before the field existed — the additive-optional
  contract `session_ref` and `deferred_reason` already follow.
  `tests/test_story_template.py` pins the stamp, the coverage refusals, the
  skip, the unchanged plain write, and that an older reader still gets every
  field it knew.

- **The setup keyboard menus stop throwing away keys you pressed while the
  menu was redrawing, and read a whole keypress instead of its first three
  bytes.** `_read_tui_key()` called `tty.setraw(fd)`, whose default is
  `TCSAFLUSH` — the same call as `TCSADRAIN` except that it also DISCARDS
  input not yet read. Because it ran once per keypress rather than once per
  menu, every read began by destroying whatever had been typed in the
  meantime. Measured on a pty: a Down arrow queued before the read survives
  `TCSANOW` and `TCSADRAIN`, and is gone after `TCSAFLUSH`. Nothing wanted
  that flush — discarding on entry is a technique for dropping a terminal's
  unsolicited reply, and setup never queries the terminal, so the entry mode
  is now `TCSADRAIN`, which differs from the old one in exactly the discard
  and in nothing else, including where it can block.

  The two halves had to ship together, because fixing the flush alone makes a
  worse bug reachable. The read took a fixed two characters after an ESC, so
  a keypress longer than three bytes — a modified arrow such as Ctrl+Left
  (`ESC [ 1 ; 5 D`), a mouse report — left its tail in the queue. The flush
  used to destroy that tail. Without the flush and without this second fix,
  the tail is read as separate keypresses, and measured on a pty the menu
  then sees `;`, then `5` — which is a menu choice, so one Ctrl+Left silently
  selects option 5 and returns — and then leaks `D` onto the next prompt.
  `_read_escape_tail()` now consumes a CSI through its final byte (`@`–`~`)
  and an SS3 through its one byte, so no fragment of a keypress can arrive as
  another. A complete sequence always starts with ESC and so can never equal
  a single-character menu choice: the silent selection is unreachable by
  construction rather than merely unlikely.

  Reading to a terminator needs a bound, and a hang in an installer prompt is
  worse than the bug being fixed, so there are two. The tail reads use
  `VMIN=0`/`VTIME=1`, so a lone Esc — a real key — returns after a tenth of a
  second instead of waiting forever for a sequence that is not coming (the
  old fixed two-character read hung there). The CSI loop also stops at 16
  characters, past every sequence a keyboard sends, so an unterminated
  parameter run cannot hold it. `tests/test_setup_keyboard_input.py` drives
  all of this against a real pty; the existing menu tests patch
  `_read_tui_key` and so could never see any of it.

- **Arrow keys pressed into a free-text setup prompt are no longer answered,
  scolded, and echoed back as raw escape bytes.** The provider question runs
  an arrow-key multi-select and then asks "Add another provider by name
  (Enter to skip)" as free text. An operator who kept pressing the arrows had
  their escape sequences returned by `input()` as if typed, and the observed
  line read `? Add another provider by name (Enter to skip) []: ^[[B^[[A^[[B^[[
  is already recorded or is not a plain identifier; skipped.` Nothing was
  typed, so nothing should have been rejected -- and printing the raw
  sequences back sends control codes to the terminal and makes the message
  unreadable.

  `_ask`, the primitive under every free-text prompt in setup, now strips
  terminal control input before trimming whitespace: complete CSI
  (`ESC [ … final`) and SS3 (`ESC O x`) sequences, a sequence the submitting
  Enter cut short (the reported line ended `^[[`, and dropping only its ESC
  leaves `[` standing as an answer), and any remaining C0/C1 control
  character or DEL. A line of nothing but arrow keys therefore reads as
  empty, which every call site already treats as Enter, and no caller can
  echo a control byte back because none reaches it. The fix sits at the
  primitive rather than at the one prompt that was reported, so the yes/no
  fallback and both menu fallbacks get it too. `readline` was not imported to
  make the arrows editable: it is absent on stock Windows Python and would
  change the editing model of every prompt in setup.

  The rejection message is also split in two. `provider_add_rejected` ORed
  two different reasons, so it could not tell an operator which had happened,
  and only one of them is worth retyping. A duplicate now gets
  `provider_add_duplicate` ("already recorded"), a malformed id keeps
  `provider_add_rejected` and now names what a plain identifier is. Both keys
  are present in all four language tables (en/ko/ja/zh).
- **Uninstall no longer leaves the sections it created behind as empty keys.**
  On an install made before the write record existed, `omh uninstall` reversed
  the keys it can attribute without a record and left

  ```yaml
  skills:
    external_dirs:

  plugins:
  ```

  in the person's `config.yaml`. Two causes, both of them about WHEN a
  container is read. The scope decides which containers OMH may drop by asking
  which ones it emptied, and it asked on text from which uninstall had already
  stripped the managed skills directories -- so `skills.external_dirs` read as
  a container the person kept empty and was spared. And the candidate set was
  fixed before the removals ran, so `plugins:`, which becomes childless only
  once `plugins.enabled:` is gone, was never a candidate at all.

  The baseline is now the config as it stood before the uninstall removed
  anything, and the candidate set is every managed container at once: the
  removal pass already re-reads the text after each deletion and works deepest
  first, so a parent leaves with its last child in the same pass.

  Which container OMH may drop is answered by the write record where there is
  one, and only guessed where there is not. The two are not equal, and the gap
  costs a person a key: a container they already had, EMPTY, before setup, and
  which setup then filled, has children at uninstall time — so "was it empty
  before?" says no and the guess concludes OMH created it. `containers_created`
  says otherwise and is right. An install with a record therefore consults the
  record alone; the guess is what the no-record lane has, and its
  by-construction argument holds for what it covers.

  That also repairs two containers the previous behaviour already lost on a
  recorded install: a pre-existing empty `memory:`, and a pre-existing empty
  nested `display:` / `sections:`. Both now round-trip byte-exactly, as
  `skills:`, `display:` and `plugins:` continue to.

  `omh uninstall --registration-only` drops the section its registration was
  the only occupant of, by the same rule and reading the same record, and
  keeps everything else it kept before. `docs/INSTALLATION.md` said that scope
  "removes the registration and nothing else"; it now says what it does.
- **The universal installer picks a Python the wheel can be installed into.**
  Reported from a second machine: `curl ... install.sh | sh` created the virtual
  environment out of `/usr/bin/python3`, and pip then refused with `Package
  'oh-my-hermes' requires a different Python: 3.9.6 not in '>=3.11'`. The venv
  was left behind, no `omh` command existed, and the next line the person typed
  was `omh setup` into `command not found`. install.sh checked only that its
  interpreter EXISTED -- `install.ps1` had probed the version since it shipped,
  and said in its own docstring that install.sh had no such probe.

  It has one now, and the same floor the wheel declares. The search runs
  `python3` first, then the versioned commands newest-first, which is the order
  `packaging/npm/lib/python.js` already used so the two distribution surfaces
  land on the same interpreter; then the places an interpreter hides when it is
  not first on PATH, which is the macOS case exactly: Homebrew, python.org
  frameworks, pyenv and uv. A candidate is accepted on what it reports, not on
  where it was found, and the report has to be one line that is only a version
  -- a wrapper that prints a banner first is refused rather than read past. An
  interpreter named in `OMH_PYTHON` stays the only candidate, because the
  variable exists for a person who knows something the search does not.

  With nothing found and `uv` already on the machine, the installer has uv
  install Python 3.12, shows uv's own output while it does, and then runs its
  own search again rather than asking `uv python find` — that command resolves
  a PROJECT environment first and is cwd-dependent, and `curl … | sh` runs
  wherever the person is standing, so from a checkout it answers that
  checkout's `.venv`. A `.venv` reports a supported version and would sail
  through the probe, and as the BASE of OMH's environment it is strictly worse
  than the interpreter uv was just asked for: rebuild that project and `omh`
  breaks. `--managed-python` does not reliably prevent it either, measured on
  uv 0.12.5. The search instead reads uv's managed directory from
  `uv python dir`, which is cwd-independent and also finds interpreters on a
  machine where `UV_PYTHON_INSTALL_DIR` or `XDG_DATA_HOME` has moved it.
  Downloading a language runtime is a kind of side effect this script has never
  had, so it is announced before it starts and `OMH_PROVISION_PYTHON=0`
  declines it without having to name an interpreter instead. `install.ps1`
  gains the same last resort and honors the same variable — the two installers
  are one documented interface and a parity gate holds them to it — and asks uv
  for its interpreters BY PATH (`uv python list --managed-python
  --only-installed`), so neither script needs to know where uv puts them on
  either platform.

  With neither, it stops before creating anything and names every version it
  did find, and says so differently when the interpreter was one the person
  named: a path that is not there reports "was not found" rather than a verdict
  on the version of a file that does not exist. Interpreter resolution runs
  before the release lookup, so a machine with no usable Python and an
  unreachable GitHub gets the interpreter diagnosis rather than a release
  error. Every run prints the interpreter it chose.

- **The interactive setup wizard says where you are in the questions.** The
  apply phase has narrated itself since it shipped (`[1/5] Installing OMH
  workflows...`); the question phase that runs before it printed a header and
  then fired the display question, the coding-delegation question and the
  provider list back to back with nothing between them. Each question group
  now carries the same `[k/n] <what this decides>` heading in the same style,
  localized in all four languages.

  The total is derived, not declared. Several groups skip themselves -- a
  config that is already TUI plus an OMH skin, no external coding CLI on PATH,
  nothing to offer as a provider, no terminal, no `--with-mcp` -- so a fixed
  `[1/5]` would over-count on most machines. Each group's "will I ask?"
  condition is now a named predicate that the group itself returns early on,
  and the wizard builds the list of groups that will speak before printing the
  first heading. A group that stays silent gets no number and the numbering
  stays contiguous. No question's wording, order, default, or behaviour
  changed, and non-interactive runs (`--yes`, `--json`, no terminal) print
  none of it.

  The heading renders through the apply phase's own `_HumanProgress.step`, so
  the line is identical, but without its 40ms settle. That settle makes a line
  readable when more output lands on top of it at once; a heading over a
  question is followed by a prompt that waits for a person, and `_read_tui_key`
  flushes the input queue on every read (#1778), so delay added before a menu's
  first read is a window in which a keypress is silently discarded.

- **The HUD header stops naming the scope when the rows already carry it.**
  The state label had a word in front of it -- `[this chat]`, `[global]`, or
  `[this chat + global]` -- written before the activity rows had tags of their
  own. They have had them since the board lanes landed: `[sub]` for a delegate
  child, `[bot]` for a board worker. The entry for that work recorded that
  "the header line still states the scope"; that no longer holds. On a
  session-only list the header word repeated what every row below it already
  said, and it did so in 12 cells of a `truncate-end` line where a segment's
  position is its priority.

  The header now carries one marker for one fact: `[global] ` when rows from
  outside this conversation are in the list, and nothing when they are not. An
  entirely unowned list and a mixed one read the same deliberately -- what the
  header owes the reader is that the totals beside it are not all theirs, and
  which row belongs to whom is the rows' own job. It is the word the DAG block
  has always used for the same fact, so the HUD now has one vocabulary for it
  rather than two. A payload naming no scope still says nothing, unless a
  Maestro row is itself global: absence is not a scope and does not become a
  claim here.

  `⚚ [OMH] v2.0.3 │ [this chat] 9 done` now reads `⚚ [OMH] v2.0.3 │ 9 done`.
  Measured on one busy header (version, repeat chip, board counts, cost, ctx,
  open tool calls, yolo) rendered through the shipped widget: at 80 columns
  the session line used to cut after `repeat x8 cycle-of-2 blocked` and now
  reaches `· board 1q`, and the mixed line used to cut mid-chip at
  `cycle-of-` and now clears the chip and its separator. At 120 columns the
  session line's open-tool-call segment (`• 2 tools · 41s`) fits whole where
  it was cut. The global line is unchanged at every width.

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

- **The per-turn fanout scan stops growing with the machine's history, a
  dropped ledger tick is counted, and an unchanged approval-bypass flag is no
  longer rewritten on every hook call.** Three costs on the path every turn
  and every tool call takes, measured together because they share a harness.

  `pre_llm_call` read the fanout root twice -- the running-work board and the
  unacknowledged-dispatch reminder -- and the board opened four JSON files for
  every fanout directory the machine had ever created. Nothing prunes that
  root, so the cost only ever grew: 0.8 ms on a fresh home, 147 ms on one with
  a thousand fanouts. Both readers now keep the eight most recently active
  directories and open only those, which takes the same turn to 7.2 ms at a
  thousand and 2.0 ms at the dozen a working home has.

  The bound is by recency and not by name, which matters more than it looks: a
  fanout id is `fanout-<sha256(goal)[:12]>`, a content hash carrying no order
  at all, so sorting the names and slicing would have kept an arbitrary eight
  of a thousand and silently dropped running units. The running-work board
  orders by when a fanout's in-flight markers last changed, because that is the
  stamp its own question moves; the dispatch reminder keeps ordering by when a
  summary was written. The board reports how many directories the bound passed
  over, so a truncated scan cannot read as a complete one. Pruning that root is
  still nothing's job, and a bounded scan is what makes that survivable rather
  than fixed.

  The tool-bursts ledger's three writers are best-effort and must stay that way
  -- a hook that raised would vanish into the host's own try/except-and-log
  wrapper -- but the lock's `TimeoutError` is an `OSError`, so a write lost to
  contention left no trace at all. An entry left open then read identically
  whether the call was still running or its close had been dropped. The swallow
  is unchanged in width; what it now does before returning is count the drop,
  classified as a lock timeout or a write error, folded into the ledger by the
  next write that does take the lock and reported beside the liveness it
  bounds. Measured: eight concurrent writers lose nothing at all, twenty-four
  lose 477 of 9,648 writes, and the counter reads back 477. It is a lower bound
  by construction, and says so.

  `record_approval_bypass` took a lock, wrote a temp file and renamed it on
  every hook call -- twice per tool call, once per turn -- for a boolean that
  changes when a person presses Shift+Tab. It now writes only when the
  observation is news: 0.201 ms to 0.020 ms. The timestamp is load-bearing in
  exactly one place, the six-hour staleness cut in `latest_approval_bypass`, so
  an unchanged value is still refreshed every half hour and can never age into
  that cut while the hooks are still observing it. No other reader reads the
  stamp: the widget renders the state and the flag, and the permission
  rehearsal reads the same two.
- **Three shipped skills can be reached by the phrasing a person uses.** Each
  lost its own home turf for a different reason, and an unreachable skill is
  always-loaded context nobody can spend.

  `live-incident-response` shipped for #1563 and lost the sentence it exists
  for. `we have an incident open right now, the checkout API is down`
  dispatched to `browser-operator` at 48, with the incident lane third at 7.
  The browser guard fires on a context token plus an action token, and both
  sets are ordinary English: `checkout` names a payment page and also the
  service that takes payments, `open` opens a tab and also describes an
  incident that has not been closed. A guard boost of 42 cannot be outscored
  by trigger evidence, so the ordering is the only place this can be decided:
  a message declaring a live incident now blocks that guard, the way a visual
  QA request already does. The skill also carried `open incident` but not
  `incident open`, the order people say it in.

  `inference-serving` never surfaced for `serve a 7B model at 50 requests per
  second`. It carries `serve this model` and `serve the model`, and a person
  names the size, which puts it between the two words. The rule is now a
  serving verb plus a model noun, with the model on the object side of the
  verb: `serve a 7B model` matches and `which model should we use to serve
  our support customers` does not. A blocker list could not hold that second
  shape, for the same reason the trigger could not hold the first.

  `refactor-plan` was dropped before any trigger could score on `this 900
  line function needs to be broken up`. It offers itself only when the
  message carries restructuring vocabulary AND planning vocabulary, and a
  decided refactor described the way people describe one uses neither word.
  Split vocabulary now stands in for the restructuring half, the way the
  dependency-upgrade phrases already do, and it needs a unit of software
  beside it so that a crowd broken up by police is not a refactor.

  Each row gains a positive case and each generic word it introduces gains a
  negative control: the negative corpus grows from 277 to 280 cases and the
  positive corpus from 425 to 429, both at zero overroutes and zero missed
  interventions. Twelve sentences using `serve`, `function`, `down`, `open`,
  `incident`, `broken up`, and `split` in an unrelated sense score
  identically before and after.

- **One bad byte in a profile config no longer blocks every tool call in the
  home.** `pre_tool_call` resolves the session's store before anything else,
  and every binding fault except a session no profile owns came back as
  `action: block`. Fault injection confirmed all four shapes: an unresolvable
  variable in the configured home, a blank home, a NUL in the path, and a bad
  Hermes home. In a native host that path re-validates the profile
  `config.yaml` on every call, and the installed host validator raises on a
  config carrying a control character. It raises on every call, for as long
  as the byte is there, so the cost of one such byte was every tool of every
  session in that home. (Separately measured, on the healthy path: that
  validator is an uncached YAML parse costing 0.417 ms per tool call against
  a real 3,463-byte config.) It has never fired in practice:
  the block message appears zero times across the whole history of both of
  the owner's `state.db` files. It is fixed because the failure, when it
  comes, is total.

  The veto's recorded reason was that a rules file may exist in the named
  store and may be blocking this very tool. That reasoning does not survive
  the case one level down. When the store DOES resolve and the rules file
  cannot be read -- malformed, permission-denied, or raising something the
  gate never anticipated -- the call is allowed, every time. That is
  `toolcall_rules`' documented fail-open contract, and the rule-gate handler
  added alongside the doctor hot-path checks rejected blocking on a rule-gate
  failure by name. So OMH allowed the case where it knew exactly which rules
  file it had failed to read, and refused the case where it could not locate
  one at all: the harsher response to the weaker signal.

  Every binding fault on `pre_tool_call` now degrades, the posture the other
  hooks already took. A rules file that loads and matches still blocks, with
  its own message, so what the narrowing removes is the veto that fired when
  there was no rules file to consult, not the one a person wrote. The
  trade-off is restated at the handler rather than dropped: while a home
  cannot bind, no tool call in it is checked against that person's rules.
  That window is real, it is the same window a malformed rules file already
  opens, and it is not a defence against an actor who can write the profile
  config in the first place.

  On this hook the degraded call is silent, which is worth saying rather than
  glossing. Nothing is written to a store, because a binding fault means
  there is no store to write to. The returned payload is not a record
  either: Hermes reads a `pre_tool_call` result's `action` and skips every
  other shape, and a hook result's context text is read on the `pre_llm_call`
  path only. Two things do still surface the same fault. `pre_llm_call`
  returns the same degradation and its context IS injected into the turn,
  once per turn, and it now names the exception type -- the only thing left
  separating a session no profile owns from a store that was named and could
  not be read. And for the config-fault class the host reports itself, with a
  backup copy of the broken file and a stderr warning naming the parse error
  and its position.

  No retry: of the writers that can leave that config unreadable, only a
  person's editor saving in place is transient, and Hermes and OMH both
  replace the file atomically and cannot produce the state at all.

- **One discipline for every OMH write of Hermes' `config.yaml`.** OMH wrote
  that file from two families that did not know about each other. The
  delegation route writer read, compared a file signature and replaced
  atomically, and since #1737 held a lock; `write_config` rewrote the whole
  file with no lock and no compare, reached by `omh setup`, `omh theme`,
  `omh memory`, self-update's external-dirs registration and
  `system/targets`. One of those could read the file, have a route land, and
  write back its stale copy. The route was erased, and the restore record
  then saw a value it had not written and dropped the person's baseline as a
  foreign edit. Before #1737 that needed somebody running a CLI command
  during a routed dispatch; with restores running at turn and session
  boundaries the window is met far more often.

  Every one of the seven call sites now goes through `update_config`, which
  reads, runs the caller's mutation against the text it just read, checks the
  signature again immediately before the replace, retries when the file
  moved, and refuses rather than writing after three rounds. The retry is
  what keeps both updates: the second attempt derives its change from the
  other writer's file. Where the OMH home is known and exists the CLI takes
  the SAME lock the route writer holds, so the two families serialize instead
  of merely detecting each other. `system/targets` is the one place that may
  write a config belonging to a Hermes home this invocation is not bound to,
  and there the signature compare stands alone; it is marked as such.

  The replacement also carries the destination's file mode, which the old
  path did not: a rename installs the temp file's mode, so a config somebody
  had chmodded to 0600 widened on every OMH write. The mode is read before
  the temp file exists, which is also what leaves nothing but the rename
  between the signature check and the replace.

  `--dry-run` takes no lock. A preview writes nothing, so it has nothing to
  serialize against, and taking the lock regardless made a read-only command
  create a `routing/` directory and a lock file inside it, force that
  directory to 0700, and acquire a five-second wait plus a way to exit 2.

  Four source-derived gates keep the discipline from drifting back. They fail
  on a bare `write_config` call anywhere in `src/`, on a renamed import of it,
  on a write whose destination expression names `hermes_config_path` and goes
  to `atomic_write_text`, `write_text` or `open` a level lower, and on a
  mutation that never names the text it was handed. The third sees the
  spelling every write in this repo uses at the point of the call; a path
  bound to a local first needs dataflow, not a name, and stays a reviewer's
  job. That last one is not hypothetical: converting
  `cmd_uninstall` reintroduced exactly that shape and it passed every other
  test. It is also the limit of what a syntactic gate can do -- a mutation
  that mentions its argument and still returns precomputed bytes is the same
  lost update and is indistinguishable from a correct one, so the tests say
  so rather than implying otherwise.

  A refusal now names its own cause. An unreadable or symlinked config raises
  `ConfigUnwritable`, a real race raises `ConfigConcurrentUpdate` and a
  mutation that times out raises `ConfigMutationFailed`, all under one
  `ConfigWriteRefused`; before, a permission error surfaced as an exception
  whose name claimed a race that had not happened.

  A symlinked `config.yaml` is refused before the read, on every round,
  rather than left to the reader. The reader refuses one by opening with
  `O_NOFOLLOW` and catching the error, and `os.O_NOFOLLOW` is Unix-only: on
  Windows the flag is a no-op, so the open followed the link and the refusal
  never fired. The compare's two sides then stopped describing one file --
  the read stamps `fstat` on the followed descriptor, the guard stamps
  `lstat` on the path -- so every round mismatched and the command failed
  with "kept changing during 3 update attempts" instead of naming the
  symlink. Only the final component is checked: the temp file is created in
  the config's own directory and renamed within it, so a symlinked parent
  cannot produce the link-destruction this prevents, and people do symlink
  dotfile directories.

- **`omh uninstall` now reverses every `config.yaml` key setup wrote, not one
  of seven.** Setup's apply step writes `skills.external_dirs`,
  `auxiliary.compression.fallback_chain`, `plugins.enabled`,
  `display.interface`, `display.skin`, `display.sections` and
  `memory.provider`. Uninstall reversed the registration and left the rest, so
  a machine kept `plugins.enabled: - omh` and `memory.provider: omh` naming a
  bundle that was gone.

  Observed against Hermes 0.21.3 in a temp home with the bundle removed: a
  leftover `memory.provider: omh` makes agent init call
  `load_memory_provider("omh")`, get nothing, and then look the provider up
  in the plugin catalogue before warning that it is neither installed nor in
  it; `hermes doctor` reports it as `omh plugin not found`. The lookup is
  cached for six hours per home and skipped when
  `security.allow_lazy_installs` is off, so the recurring cost is the
  warning rather than a request per start. The stale `plugins.enabled` entry
  and `display.skin: omh` are silent -- discovery simply never finds them.

  Setup now records what it added, as the difference between the reading
  before its pass and the reading after it, which is the same test #1750
  applied to `display.sections`. Uninstall reverses a key only while the
  current value is still the recorded one, so somebody who moved
  `memory.provider` to honcho keeps honcho and the report names the key it
  left alone. A value consent let OMH migrate them off -- `display.interface`
  and `display.skin` are the only two -- is put back rather than removed.

  Installs made before the record get the honest subset. `display.skin: omh`,
  `plugins.enabled` containing `omh` and `memory.provider: omh` name OMH by
  construction and are reversed. `display.interface: tui`, the
  `display.sections` children and the compression fallback chain are values a
  person can legitimately hold, so they are kept and the uninstall output
  says which and why.

  `--registration-only` keeps its narrow meaning and reverses nothing else.
  `--dry-run` lists every key it would reverse and leaves the file
  byte-identical.

  The record is keyed by config path, because every Hermes bot profile
  shares the primary's OMH home and one `omh setup` therefore writes the
  same `runtime/state.json` once per home. A single slot would end the run
  holding the last profile's record, and the primary -- the home somebody is
  most likely to uninstall -- would silently fall back to the no-record
  subset.

  Bot profiles are reversed the same way the primary is, and through the
  same function, because setup writes the same seven keys to each of them
  (`_sync_hermes_profiles` calls the apply pass once per profile home). A
  profile that still holds a key is reported as `partially_cleared` with the
  keys named, rather than as `cleared` over a config that still says `omh`.

  Every remover now takes the same refusal its forward writer takes. The
  display removers always did; the memory, plugin and compression removers
  took none of it, and two of those shapes were not merely untouched. On a
  config carrying both a dotted `memory.provider: omh` and a `memory:`
  block, the owner check read the dotted value and the mutator then deleted
  the block's `provider: honcho`, leaving OMH's marker and losing the
  person's provider. On a config with `enabled: &plist`, the display path
  refused over the anchor while the plugin path emptied the list the anchor
  names, so every `*plist` alias resolved to null. A quoted inline
  `plugins.enabled` is also left alone now, because the list parser splits on
  commas before it strips quotes and `["a,b", omh]` would come back as two
  entries.

  A row's status is read off the config rather than matched against its own
  English message. The old substring test reported a key that was present
  and deliberately untouched as "nothing here", and coupled the
  absent/kept distinction to the wording of six messages. The case that
  separates the two: OMH wrote `display.sections.tools`, the person deleted
  that line, and the remover answers "no display.sections child to remove",
  which reads like absence about a key the config still carries.

- **A skill whose name is an ordinary English word no longer claims every
  sentence that happens to spell it.** `pods stuck in CrashLoopBackOff after
  helm upgrade` dispatched to the `loop` goal engine at high confidence, in
  English and in Korean; `a user asked us to delete all their data` reached
  the external-advisor `ask` skill; `should I hire a backend engineer or a
  DevOps person first` reached the `backend` coding lane. A wrong confident
  dispatch is worse than a question, because the person gets a goal engine
  for a Kubernetes problem and has no reason to suspect the router.

  Two mechanisms, both now closed. Matching was plain containment, so a name
  fired INSIDE a longer word -- `loop` in `CrashLoopBackOff`, `ask` in
  `asked`. Trigger and name matching go through `phrase_is_spoken`, which
  rejects a match that starts or continues mid-word. Its two edges differ on
  purpose: a phrase that starts mid-word is never the phrase, while a
  multi-word phrase extended on the right is the same phrase inflected, so
  `attack scenarios` still matches the `attack scenario` trigger and `asked`
  still does not match `ask`. The left-edge test is ASCII-only because
  Japanese and Chinese are written without spaces.

  Separately, one occurrence of a one-word name was credited four times: the
  `name:` phrase at +5, the identically-spelled trigger phrase at +6, that
  trigger's token at +3, and the same token again from the metadata fold at
  +1. Fifteen points for one word clears the high-confidence bar on its own,
  and four labels in the evidence list read as four independent findings when
  they are one. The three duplicates are dropped; the word scores once, as
  the name it is, which is worth a clarifying question rather than a
  dispatch. Every invocation form is untouched: `$loop`, a leading `loop`,
  `use omh loop`, and `use the loop skill` all still dispatch, and so does a
  Korean particle welded to the name (`loop로`), which marks the token as the
  name rather than the English word.

  Three lanes had been carried by that inflation and now have the phrasing a
  person actually types: `plan` gains "make a plan", "write a plan", and
  "write the plan"; `frontend` gains the locative "in / on / to the
  frontend"; and `deep-interview` trades its bare `interview` trigger -- every
  hiring loop and user study in the language -- for "interview me". The verbs
  `make` and `write`, and two ordinary words `research` reached only through
  complete phrases (`before`, `open`), are held to whole-phrase-only scoring.

  Measured on the deciding surface over the 94-ask survey in the issue: 41
  dispatch / 43 clarify / 10 fallback becomes 35 / 48 / 11. Nine asks moved.
  Six were the wrong confident dispatches above; one was corrected in place
  (`review this terraform plan before I apply it` now reaches `code-review`,
  not the planning workflow); two were clarifications whose top candidate
  changed once a substring artifact stopped scoring. One previously correct
  dispatch became a clarification that still names the same workflow. The
  negative-control corpus grows from 265 to 277 cases and the
  positive-intervention corpus from 424 to 425, both at zero overroutes and
  zero missed interventions.

  The always-loaded skill-body budget rises from 977,649 to 977,773
  characters for the six added trigger phrases.

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
