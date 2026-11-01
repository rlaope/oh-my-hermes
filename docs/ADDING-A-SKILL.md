# Adding a New Installable Skill

Checklist for adding a skill to the OMH catalog. Every surface below is
enforced by a test; skipping one fails CI with an actionable message naming
the file and structure to edit.

## 1. Define the skill (single registration point)

- Add the `SkillDefinition` to `src/skills/catalog_definitions.py`, which is
  where the definitions moved when the catalog was split; `src/skills/catalog.py`
  keeps the derivations that read them.
- Set `capability_family` **only** when the skill's user-facing family differs
  from its awareness-lane default, which is rare — a handful of skills set it.
  Leave it empty otherwise; the lane default governs.
- Set `path_globs` only when a file path names the skill's territory whatever
  words carry it (`iac-change` declares `*.tf`, `charts/**`, `k8s/**`). A
  matching path scores only beside one of the skill's own trigger words, so a
  path named in passing adds nothing; add a negative control for that sense.
- If the skill needs a recommendation policy, add its `_SKILL_POLICIES` entry
  in `src/routing/recommend.py`.
- Author `triggers` in English only. Every other language reaches the skill
  through its trigger language pack in `src/routing/trigger_packs/<lang>.json`,
  which merges into the catalog before anything reads it — so a non-English
  phrase in a `SkillDefinition` is a phrase one language got for free and the
  rest did not. See "Adding a trigger language pack" in
  `docs/routing-quality.md`.
- The `SkillDefinition.name` you pick is the canonical identifier (tap
  directory, install manifest, routing key, CLI arguments); the generated
  frontmatter `name` is a separate rendered display identifier that
  `omh_skill_display_name()` prefixes with `omh-` for the host status line, so
  never treat the two as interchangeable.
- The display form also reaches messenger-visible prose: skill-picker bodies,
  capability-family lines, route-hint copy, and `workflow_explanation` copy call
  `display_workflow_name()` in `src/wrapper/contract.py` at render time. Never
  store the `omh-` form in catalog data, routing fixtures, or state, and keep
  `./<name>` invocation strings, `--skill <name>` recipes, and
  `definition.triggers` canonical. Routing accepts the display form back through
  `canonical_display_mentions()` in `src/routing/display_names.py`, so a new
  skill gets echo-back for free; `tests/test_display_names.py` locks all three.
  A skill that joins `WORKFLOW_VOCABULARY` also needs a row in
  `WORKFLOW_DISPLAY_NAMES` (`src/plugin_bundle/omh/workflow_intent.py`): the
  bundle has no catalog to derive its labels from, and
  `tests/test_display_names.py` fails until the row is there.
- The skill's `hermes_role` also decides the directory it installs into:
  `hermes_skill_category()` in `src/skills/catalog.py` maps role to the Hermes
  dashboard category, and installs land at
  `<skills_dir>/<category>/<label>/SKILL.md`. Hermes reads a skill's banner
  group off that directory, not off frontmatter, so a new role is a new banner
  line — `tests/test_skill_install_layout.py` asserts the category set, and a
  category name may never collide with a skill label.
- Name a sibling in `do_not_use_when` or `handoff_policy` by its canonical
  name in backticks (`` use `research` ``). The renderer writes it as the
  label `skill_view` loads (`` `ulw-research` ``), and the `do_not_use_when`
  siblings fill the Hermes frontmatter's `metadata.hermes.related_skills`;
  `tests/test_loadable_sibling_names.py` holds both. When a skill Hermes
  bundles shares the new skill's job, add one `HermesSkillLine` to
  `do_not_use_when` saying which request belongs to the bundled skill; a
  `_feature_surface_skill` takes it in `extra_do_not_use_when`, because that
  shape's `do_not_use_when` replaces its generic lines. It renders wherever
  that skill's `## Do Not Use When` renders: the Hermes body, or for a
  progressive-disclosure skill only `references/full-contract.md`, since the
  compact body has no such section. The Agent Skills projection drops it.

## 2. Hand-authored surfaces (curated order and UX copy)

These cannot be derived from the catalog; each has a gate that fails with
paste-ready guidance:

| Surface | File / structure | Gate |
| --- | --- | --- |
| Awareness lane membership | `awareness_primer_payload()` lane `skills` lists in `src/plugin_bundle/omh/awareness.py` | `tests/test_capabilities.py` (lane coverage) |
| Workflow context card lane | `_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW` in the same file | `tests/test_capabilities.py` (context-card coverage) |
| Visible/ack wrapper actions | `VISIBLE_ACTIONS` + `_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION` in `src/wrapper/contract.py` | `tests/test_wrapper_contract.py` (visible-ack) |
| Next-action label | `NEXT_ACTION_LABELS` in `src/routing/action_copy.py` | `tests/test_wrapper_contract.py` (curated-label gate) |
| Dedicated non-ack chat card | a `*_CHAT_CARDS` entry or bespoke renderer in `src/wrapper/contract.py` | intervention harness + coverage-case gate |
| Coverage case | `ChatCardCoverageCase` in `src/quality/chat_card_coverage.py` or `RoutingInterventionCase` in `src/quality/routing_precision.py` | `tests/test_wrapper_contract.py` (coverage-case gate) |
| Dedicated card config | `_WORKFLOW_OPERATIONS_CHAT_CARDS` in `src/wrapper/contract.py` | rendered-card assertions in the intervention corpus |
| Direct-workflow membership | `_DIRECT_WORKFLOW_SKILLS` in `src/wrapper/contract.py` | intervention corpus `expected response kind` |

The curated-label and coverage-case gates carry frozen legacy allowlists; do
not extend the allowlists for a new skill — register the skill instead.

The last two rows are the ones that cost an afternoon, because their failure
does not look like a missing registration:

- Without a `_WORKFLOW_OPERATIONS_CHAT_CARDS` entry the skill has no card of its
  own to render.
- Without `_DIRECT_WORKFLOW_SKILLS` membership, `_resolve_mode()` falls through
  to `"plan"` — so the router **selects your skill correctly** and then renders
  a generic plan card. The routing is right and the response is wrong, which
  reads as a routing bug and is not one. The intervention corpus reports it as
  `expected response kind <yours>, observed plan`.

Registering a new `next_action` means a curated label in `NEXT_ACTION_LABELS`
(`src/routing/action_copy.py`) always, plus `VISIBLE_ACTIONS` and
`_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION` (both `src/wrapper/contract.py`) when the
action is a `_SKILL_POLICIES` next_action. The split is not style, it is which
reader looks the id up: `next_action_label()` reads the label table and every
producer reaches it, `_action()` reads `VISIBLE_ACTIONS` and only a rendered
button reaches it, and `_ack_actions_for_next_action()` reads the ack table for
a generic ack card, whose next_action is always a policy action.

`tests/test_wrapper_contract.py` derives that subject from the producers --
awareness route hints, generic-tool checkpoint routes, direct-workflow
invocations, routing policies and chat cards -- so an action registered in none
of the three fails by name, with the table, the file and the producer that
reaches it (issue #1643). A route hint's `fallback_action` and a capability
family's `next_action` are descriptive snake_case sentences authored for the
underscore-to-space rendering, not action ids: they are exempt from all three,
and a separate assertion fails if one is wired into `VISIBLE_ACTIONS` or the
ack table.

### A deference line must not repeat the deferring skill's own trigger vocabulary

A `do_not_use_when` line that hands a request to a sibling is itself routed
text. If it repeats the words your own skill triggers on, your skill outranks
the sibling on the very sentence meant to send the work away, and
`tests/test_catalog_deference_policy.py` reports the inversion. Name the
sibling's territory in the sibling's vocabulary. Reword the boundary rather than
recording the pair in `KNOWN_INVERSIONS`; an entry there preserves the defect
and documents it as intended.

## 3. Exact-count fixtures (contracts, updated in the same commit)

Adding a routing/intervention case moves exact-count assertions in
`tests/test_routing_precision.py`, `tests/test_cli.py`,
`tests/test_hermes_ux_quality.py`, and `tests/test_release_smoke.py`. Grep
those four for the old count.

Two more sites are not in `omh release drift`'s report, so a green drift run
does not clear them:

- `tests/test_catalog_deference_policy.py` — every `do_not_use_when` line that
  backticks a sibling skill adds a deference case, so a skill deferring to four
  siblings moves `EXPECTED_DEFERENCE_CASES`, `EXPECTED_DEFERENCE_PAIRS`, and
  `EXPECTED_DEFERRING_OWNERS` together.
- `tests/test_router_content.py` — asserts the `docs/README.md` skill count
  string, and `tests/test_routing_precision.py` additionally asserts
  `total_case_count` and `total_passing_count`, which are the negative and
  intervention corpora summed rather than either count alone.
- `tests/fixtures/agent_skills_hermes_digests.json` — a pinned sha256 per
  skill body, checked by `test_hermes_projection_byte_stable`. It is the only
  gate that sees a body CHANGE: the `docs ... --check` gates look for drift
  between a producer and its generated file, and an intended body edit moves
  both together, so they stay green. Editing a body therefore moves one
  digest, and the fixture is re-derived with
  `json.dumps(..., indent=2, sort_keys=True)` and committed alongside the
  edit. The failure names the skills whose digests moved, so confirm the list
  is exactly the bodies you meant to touch before re-deriving.

A new skill also needs corpus coverage of its own, which
`tests/test_skill_reach.py` checks per skill: at least one
`ROUTING_INTERVENTION_CASES` entry the router dispatches to it without the
message naming it, and at least one `ROUTING_PRECISION_CASES` entry that uses
its vocabulary in another sense and stays unrouted. The failure names the
skill. The two baselines in `src/quality/skill_reach.py` only shrink, so a new
skill cannot be listed there instead; remove an entry in the same commit that
adds the case covering it. For operators and agents,
`omh demo skill-reach --summary` prints the per-skill projection.

## Adapting an existing capability

Before accepting or dispatching an upstream adaptation, load the shared
[adaptation-quality procedure](../skills/omh-verification-gate/references/adaptation-quality.md).
It maps operative components and craft defaults to existing requirement/task/evidence
rows, requires reuse-first decisions and early/final same-task comparisons, and
separates technical from output-quality verdicts. Never silently substitute a
recipe or methods-only outcome for requested executable retention; record the
user-agreed exclusions. Missing execution or review remains unobserved. The
native capability structural gate does not evaluate output quality.

Keep the procedure on demand under its verification-gate owner; short conditional
pointers belong in planning, implementation, DAG and verification bodies. Review
portable overrides and the closed reference inventory, then regenerate both
projections. Contract tests prove those instructions are delivered, not that a
live agent followed them or that the resulting work has artistic quality.

## Optional companion support (separate from references)

Optional companions use the authoritative `builtin_skill_support_templates()`
inventory in `src/skills/support_files.py`. Show-reel's closed resource factory
is in `src/skills/show_reel_support.py`; the three domain science factories live
beside their canonical definitions and enumerate their own toolkit resources.
Consumers derive finite owners from that inventory and filter by owner; never
flatten relative paths across owners or create per-host resource maps.
Companion code is never imported/executed by discovery, routing, setup/update or doctor.
Do not disguise scripts as Markdown references, recursively copy arbitrary files,
bootstrap dependencies, or create a new core renderer command. Any expansion
needs reviewed paths/bytes/notices, unsafe-path and ownership tests, package-data,
native/local-source/portable/tap parity and a source-hidden built wheel proof.
Add portable paths explicitly; keep the one portable inventory, not per-host maps.
For show-reel, regenerate provenance after an audited change with
`python tools/render_skill_pack.py --write --refresh-provenance`; `--check`
checks the tap. Domain producers deliver separately validated provenance files;
that flag is not a domain-manifest writer. Explicit local-source imports require
all declared companion bytes and reject missing, edited, extra or linked files.
Support bytes are on-demand disk footprint, not eager prompt text.

## 4. Regenerate every generated artifact family

```sh
# skills/*/SKILL.md + references (short template-write loop; see CLAUDE.md)
uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md
uv run python -m omh.cli docs roles --output docs/ROLES.md
uv run python -m omh.cli docs capability-families
uv run python -m omh.cli docs skill-shortlist
uv run python -m omh.cli cases demo --all --json > examples/use-cases/g1-g10-demo-cards.json
```

Editing an existing skill instead of adding one: if the section you touched is
listed under the same definition's `portable_overrides`, the portable
projection replaces it and your line does not reach
`agent-skills/<skill>/SKILL.md`, and `tests/test_agent_skills_projection.py`
fails naming the section. Decide what the portable body should say, edit the
override in the same literal, then update that section's
`portable_override_shadows` digest to the value the failure prints. See "When a
replaced catalog section moves" in `docs/AGENT-SKILLS.md`.

## 5. Verify

Every added skill costs context twice. Its index line -- the name and the first
57 characters of its description -- is sent on every request of a `full`
install. Its body costs about 8k characters each time the model loads it, and a
loaded body stays in history until compaction. Check what it cost, and keep
shared policy in `skills/omh-routing/references/skill-common-rail.md` instead
of a new repeated section in `workflow_skill`:

```sh
uv run python -m omh.cli docs skill-context-cost
uv run python -m omh.cli release drift
```

`release drift` checks five budgets on text that can ride every request:
`skill_index_chars` and `skill_index_line_max_chars` (the index lines, rendered
with Hermes's 60-character description rule), `plugin_tool_schema_chars` (the
eager tool-schema ceiling, paid per request only when Hermes's
`tools.tool_search` is off), `pre_llm_call_context_chars_max`, and
`pre_llm_call_context_fallback_chars_max` (the same context for a session the
awareness system prompt section did not render for). A new skill moves the index budget by about one
line. The first words of the description are what a model reads to decide
whether to load the skill, so the structure lint rule
`SKILL_INDEX_OPENING_DISTINCT` fails when two installable skills open their
visible description (after `[omh] `) with the same three words; see
`src/skills/skill_index.py` for the reviewed exceptions.

Two more budgets read the skill bodies. Both are ceilings with standing
headroom, not exact-value ratchets, so an ordinary new skill fits under them
without a raise. `full_profile_skill_body_chars` is the install footprint of
every `full` `SKILL.md` body. `full_profile_skill_body_repeated_chars` counts
text repeated verbatim across bodies; every new skill moves it a little,
because the renderer stamps the lane's `## Workflow Lane` and the shared rail
lines into each body, and the headroom is sized for that. A skill that copies
another skill's own sections moves it by far more, and the fix is to move the
shared text into a reference. Each ceiling is derived from a recorded
producer measurement by the policy written beside
`FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` and
`FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT` in `src/maintenance/release.py`.
That measurement is also a floor: a change that shrinks either figure below it
re-measures and re-derives in the same commit, and the tests fail until it
does.
The per-skill body ceiling (`STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING` in
`src/skills/structure_lint.py`) still bounds what one load costs.

Density is the other half of that number; see §6.

```sh
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs roles --check
uv run python -m omh.cli docs capability-families --check
uv run python -m omh.cli docs skill-shortlist --check
git diff --check
PYTHONPATH=tests uv run python -m unittest discover -s tests
```

## 6. Authoring doctrine: the body carries instruction, the trigger carries phrasing

`FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` bounds the skill bodies, not the whole pack:
it is the install footprint of the `full` profile's `SKILL.md` files.
`_full_profile_skill_body_chars()` in `src/maintenance/drift.py` reads
`profile["skill_body"]["bytes"]`; `docs skill-context-cost` prints on-demand
references as a separate figure, and neither body budget reads it. A byte in the
body is therefore paid every time the skill is loaded, and stays in that
session's history until compaction; a byte in a `references/*.md` is paid only
when a reader opens it. Move optional detail out to a
reference instead of compressing it in place -- compression buys back a fraction
of one skill's body, relocation buys back all of it.

That limit cannot tell a body that grew a rule from a body that grew adjectives,
so `tests/test_skill_density.py` measures instruction density per skill from the
catalog producer. It fails naming the skill, the measured value, the threshold,
and the offending excerpt. Thresholds and the reviewed lists live in
`src/quality/skill_density.py`; `omh release drift` reports the filler count
alongside the byte budgets.

What it measures, and what each one asks of you:

| Signal | Threshold | What passes it |
| --- | --- | --- |
| `filler_hits` | 0 | No phrase from the reviewed `FILLER_PHRASES` list. Each is a connective whose deletion leaves the claim intact. |
| `repeated_share_percent` | < 5.0 | A body does not repeat its own sentences. The margin exists so the one most important rule may be restated at the end of a long body. |
| `payload_markers_per_1k` | > 9.0 | Prose that instructs: modals, negations and exceptions, conditionals, numeric bounds with units, and exact strings in backticks. |

Two rules the gate cannot check for you:

- **Never compress the trigger.** The frontmatter `description` and the routing
  signal list are retrieval surface matched against the user's own phrasing by
  `src/routing/`, so keyword-redundant alternatives are payload there even where
  a human reader needs one. The density measurement excludes both on purpose;
  trimming triggers to look tidy costs routing coverage, and
  `ROUTING_PRECISION_CASES` / `ROUTING_INTERVENTION_CASES` are what notice.
- **Declare what a rewrite drops.** Before compressing an existing body, run
  `compression_verdict(skill, before, after)`. It returns `keep_original` when
  the measured token delta is under 10%, when the retrieval surface moved, or
  when the draft dropped a never-delete marker — and it names each dropped
  claim, bound, or exact string rather than counting them. On already-dense
  text the remaining words are the payload; an undeclared loss is a silent
  regression, and a single-digit win is not worth re-reading every rule for.

## 7. Tool-facing text: a prune candidate is never a delete

The same question applies to the `src/plugin_bundle/omh/tools/` descriptions,
with a sharper test available: a JSON schema sits beside each one, so text a
reader could reconstruct from `(name, schema, blank outline)` is measurable
rather than argued. `tests/test_schema_overlap.py` runs that measurement over
every registered tool; the rules and the reviewed verdicts live in
`src/quality/schema_overlap.py`.

What the probe finds is a **prune candidate**, never an automatic delete:

| Bucket | Examples |
| --- | --- |
| Prune candidate | Parameter names and types. `required`. Value examples that only restate an enum. Clamp ranges already declared as `minimum` / `maximum`. |
| Keep, always | Defaults **and their direction** — `gitignore: true` does not say "respects gitignore". Routing and escalation rules. Exact output shape. Worked anti-patterns. Constraints the type system cannot express, such as a field required only for one action. |

Three rules the measurement cannot apply for you:

- **`git blame` the line before cutting it.** Much of what restates a schema is
  incident scar tissue: somebody added that sentence because a model got it
  wrong once, and the schema has not started saying it since.
- **One sample is noise.** A single overlap hit is a question for review, not a
  finding. The gate is that every hit carries a verdict, not that the count is
  zero.
- **Decide what ships before you compress it.** Scope first, density second; a
  tighter description of a parameter that should not exist is still a worse
  tool.

The gate fails when a finding has no reviewed verdict, and it fails with the
finding id and paste-ready instructions. Add the id to
`REVIEWED_OVERLAP_DECISIONS` with `keep — <which bucket>` or
`prune candidate — <what git blame showed>`. Self-documenting flag-style tools
prune heavily; DSL and capability tools barely, so most verdicts are `keep`.

## Acknowledgements

Domain taxonomy adapted from revfactory/harness (https://github.com/revfactory/harness), Apache License 2.0, Copyright 2025 robin.
