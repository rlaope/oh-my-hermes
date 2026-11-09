# route-hint-dedup / verify — DONE: PASS (with pre-existing failures named)

Worktree: route-hint-core, HEAD a498a6994 (base e98cfe616). No tracked files edited.

## (1) git show --stat HEAD
```
commit a498a699473bc37a27e17cdf11e6e8f3b45bff42
    Drop repeated text from the rendered route hint
 CHANGELOG.md                               |  10 +++
 src/plugin_bundle/omh/awareness.py         |  14 +++-
 src/plugin_bundle/omh/turn_budget.py       |  11 ++-
 tests/test_ai_job_search_context_budget.py |   4 +-
 tests/test_route_hint_dedup.py             | 125 +++++++++++++++++++++++++++++
 5 files changed, 157 insertions(+), 7 deletions(-)
```
(Lore trailers + Signed-off-by: rlaope present.)

## (2) Before/after render, 5 ROUTING_INTERVENTION_CASES producing [OMH Route Hint]
pre_llm_call on HEAD~1 (/tmp/rh-base worktree) vs HEAD; per-key line lists compared.
```
2390 -> 2264 first_response_shape same/2, not_evidence_yet same/2, plan_todo same/0, selected same/3, reason same/2  "Compare this HellaSwag log to the paper's rep"
1868 -> 1735 ... all same (1/1/0/2/1)  'Estimate TAM SAM SOM for US dental clinics us'
1609 -> 1476 ... all same             'Prepare a customer evidence analysis and JTBD'
1868 -> 1735 ... all same             'Can you do market sizing for dental clinics i'
1676 -> 1541 ... all same             'Make a product showcase video for a Japanese '
total 9411 -> 8751 -660 (7.0%)
removed: per-hint adjacent_workflows= lines (equal to top-level) and fallback_action_label=... lines whose label == action with spaces
```
- first_response_shape, not_evidence_yet, selected, reason: byte-identical (raw compare, no normalisation needed).
- plan_todo: 0 occurrences in these 5 samples -> identity NOT observed here (covered only by implementer's test_route_hint_dedup).
- No next_action_label dedup fired in these 5 (selected lines raw-identical).

## (3) VERIFY
### unittest (8 required modules), run in parallel with HEAD~1 under load avg ~40
HEAD tail:
```
Ran 812 tests in 1912.011s
FAILED (failures=7, skipped=2)
```
HEAD~1 (same 7 modules; test_route_hint_dedup does not exist there) tail:
```
Ran 802 tests in 1906.110s
FAILED (failures=6, skipped=2)
```
Six failures happen on both HEAD and HEAD~1, so they predate this commit and are not caused by it:
- tests.test_cli.CliTests.test_release_evidence_bundle_cli_packages_optional_write_artifact
- tests.test_cli.CliTests.test_release_evidence_bundle_verify_nonmatching_exits_one_in_json_and_human_output
- tests.test_cli.CliTests.test_release_product_readiness_cli_summarizes_product_story
- tests.test_cli.CliTests.test_uninstall_defaults_to_full_managed_cleanup_and_preserves_unrelated_hermes_files
- tests.test_plugin_distribution.PluginHermesAdmissionTests.test_real_admission_accepts_declared_range
- tests.test_plugin_distribution.PluginHermesAdmissionTests.test_real_admission_rejects_unsupported_version_before_register

One failure appeared only on HEAD: tests.test_cli.CliTests.test_release_evidence_bundle_verify_matching_exits_zero_in_json_and_human_output (`AssertionError: 1 != 0`, empty stderr). I re-ran it alone, twice on each side:
```
route-hint-core run1: OK
route-hint-core run2: OK
rh-base run1: FAILED (failures=1)
rh-base run2: FAILED (failures=1)
```
It passes on HEAD and fails on HEAD~1 when run alone, so it is flaky or depends on environment and was not caused by this commit.
All 10 test_route_hint_dedup tests and all test_route_hint_installed_skills, test_hook_manifest, test_dag_ulw_routing, test_chat_router and test_per_turn_budgets tests pass (none appear in the failure list).

An earlier serial HEAD-only run had 6 failures: `Ran 812 tests in 1279.538s / FAILED (failures=6, skipped=2)`.

### release drift
```
No drift. 29 checks passed.
```

## Run goal check
- The route hint drops repeated text: OBSERVED. On 5 cases, 9411 -> 8751 chars (-7.0%). The kept lines are byte-identical.
- Routing tests green: OBSERVED for the routing and dedup modules. Not fully green overall: the 6 test_cli/test_plugin_distribution failures above also fail on HEAD~1.
- Per-turn budgets green: OBSERVED. test_per_turn_budgets passes with the lowered limits.
- One commit ready for PR: one commit a498a6994 on top of e98cfe616, clean tree, not pushed. Because of the pre-existing failures, CI on this branch may be red for reasons that have nothing to do with this change.

## Not observed / open
- plan_todo= appears in none of the 5 sampled cases, so its byte-identity was not checked here. The only evidence is the implementer's test.
- The next_action_label= dedup (rule 3) did not fire in the 5 samples.
- I did not re-measure the 11.8% / 27,147 figure; the 5-sample saving is 7.0%.
- The implementer reported `392 OK`, but my run of the 8 required modules has 6 pre-existing failures. The implementer's module set seems to have been different (it included test_ai_job_search_context_budget and probably excluded test_cli and test_plugin_distribution).

## Files changed
Only this handoff file. /tmp/rh-base was created, then removed and pruned. Scratch scripts and logs are under ~/.hermes/profiles/kami/cache/scratch. Stray /tmp/rh-home-* and worktrees/rh-home-* dirs from my first render run were deleted.
