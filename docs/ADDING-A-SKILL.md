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
- The skill's `hermes_role` also decides the directory it installs into:
  `hermes_skill_category()` in `src/skills/catalog.py` maps role to the Hermes
  dashboard category, and installs land at
  `<skills_dir>/<category>/<label>/SKILL.md`. Hermes reads a skill's banner
  group off that directory, not off frontmatter, so a new role is a new banner
  line — `tests/test_skill_install_layout.py` asserts the category set, and a
  category name may never collide with a skill label.

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

The curated-label and coverage-case gates carry frozen legacy allowlists; do
not extend the allowlists for a new skill — register the skill instead.

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

## 4. Regenerate every generated artifact family

```sh
# skills/*/SKILL.md + references (short template-write loop; see CLAUDE.md)
uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md
uv run python -m omh.cli docs roles --output docs/ROLES.md
uv run python -m omh.cli docs capability-families
uv run python -m omh.cli cases demo --all --json > examples/use-cases/g1-g10-demo-cards.json
```

## 5. Verify

Every added skill grows the always-loaded prompt body of a `full` install.
Check what it cost, and keep shared policy in
`skills/omh-routing/references/skill-common-rail.md` instead of a new
repeated section in `workflow_skill`:

```sh
uv run python -m omh.cli docs skill-context-cost
uv run python -m omh.cli release drift
```

Density is the other half of that number; see §6.

```sh
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs roles --check
uv run python -m omh.cli docs capability-families --check
git diff --check
PYTHONPATH=tests uv run python -m unittest discover -s tests
```

## 6. Authoring doctrine: the body carries instruction, the trigger carries phrasing

`FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` bounds the always-loaded skill body, not the
whole pack. `_full_profile_skill_body_chars()` in `src/maintenance/drift.py` reads
`profile["skill_body"]["bytes"]`; `docs skill-context-cost` prints on-demand
references as a separate figure, and the ratchet never reads it. A byte in the
body is therefore paid in every context window of a `full` install, and a byte in
a `references/*.md` only when a reader opens it. Move optional detail out to a
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
