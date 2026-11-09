# route-hint-dedup / implement — DONE

Commit: a498a699473bc37a27e17cdf11e6e8f3b45bff42 on omh/route-hint-core (not pushed).

## What changed
- src/plugin_bundle/omh/awareness.py `awareness_route_hint_context_from_payload`: three render-only dedups
  1. per-hint `  adjacent_workflows=` omitted when it equals the top-level line (kept if it differs or there is no top-level line)
  2. `fallback_action_label=L; ` dropped when L == A.replace("_"," ")
  3. `next_action_label=L; ` on the `- selected=` line dropped under the same rule
  The payload, selection, first_response_shape (incl. dag-ulw override), not_evidence_yet and plan_todo are untouched.
- src/plugin_bundle/omh/turn_budget.py: PRE_LLM_CALL_CONTEXT_CHAR_LIMIT 5786 -> 5632, FALLBACK 7338 -> 7184, each with a dated history comment. Measured with budget_report(): live = limit, headroom 0. The -154 is the `handoff-guide` role render on the routed request: -81 from the adjacent line, -73 from the fallback label.
- tests/test_ai_job_search_context_budget.py: this pinned-limit test asserted the old 5786/7338. It is a pin fixture the change moves, so I updated it to the new values with reasons.
- tests/test_route_hint_dedup.py (new, 10 tests): each dedup both ways, plus first_response_shape, not_evidence_yet and plan_todo unchanged, plus a live routed request.
- CHANGELOG.md: one entry at the top of Unreleased.
- I left the fixtures at test_chat_router.py:448 and test_cli.py:864 alone. They are a route hint block pasted into the router's input, and nothing compares them to render output.
- release.py: drift named nothing, so I did not edit it.

## VERIFY (last lines)
- unittest (the 8 required modules + test_ai_job_search_context_budget): `Ran 392 tests in 282.405s` / `OK (skipped=2)`
- `uv run python -m omh.cli release drift`: `No drift. 29 checks passed.`
- `uv run --group lint ruff check src tests`: `All checks passed!`
- `git diff --check`: clean
- `git log -1`: a498a6994 "Drop repeated text from the rendered route hint", Lore trailers + Signed-off-by

## Open
- Nothing is blocked. I did not re-measure the 11.8% / 27,147-character figure; it is quoted from the spec.
