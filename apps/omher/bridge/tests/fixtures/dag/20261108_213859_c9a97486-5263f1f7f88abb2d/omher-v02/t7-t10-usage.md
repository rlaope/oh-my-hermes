# T7 + T10 handoff (lane acct, wt v02-acct, branch feat/omher-v02-acct)

Status: DONE. Every VERIFY passes. Commits are signed off and not pushed.

## Commits
- `17c11dfa8` feat(omher): agent marks - AgentIcon and 22 logos
- `fe8398d6f` feat(omher): usage meters - usage.read and sidebar rings

## T7: logos
- `apps/omher/src/assets/agents/`: 22 files copied unedited from scratch/omher-plan/logos (19 Lobe SVGs, pi.svg, omp.svg, omh.png).
- `apps/omher/src/ui/AgentIcon.tsx`:
  - `agentIcon(id)` and `<AgentIcon>` import the SVGs via `?raw` and draw them inline. Ids are prefixed per mark so gradients never clash.
  - Monochrome marks get `fill=currentColor`; colour marks keep their own fills; omh is an `<img>`.
  - Vendor aliases (claudecode, githubcopilot, kilocode, roocode, geminicli…) map in, and the lookup ignores case.
  - Unknown ids get a letter mark.
  - `AGENT_IDS` has 22 entries: the 20 from the brief plus `openai` and `gemini-app` for the two extra Lobe files.
  - Exported from `src/ui/index.ts`.
- `apps/omher/src/ui/agentIcon.test.ts`: every id maps, aliases work, unknown ids get a letter, the mono/colour split holds, and no `<title>` or duplicate id appears.
- `apps/omher/e2e/agents.html` + `agents-grid.tsx`: a test-only grid page served by the vite dev server, not part of the app build.
- `apps/omher/README.md`: new "Credits" section (Lobe Icons MIT, pi-mono MIT (checked with `gh api`: MIT), omp official mark, OMH kami mark).

## T10: usage meters
- Bridge `usage.read` → `read_usage()` in `bridge/omher_bridge.py`:
  - Codex: newest `rate_limits` event across the newest 5 rollout files, reading the last 512 KB of each. `primary`/`secondary` become windows (300 → "5 hours", 10080 → "Weekly", else `<n>h`/`<n>d`). It also returns `plan_type`. State is near at ≥70 and limited at ≥100 or when `rate_limit_reached_type` is set.
  - Claude: newest `rate_limit_info` (nested under `apiErrorParams` in real files; found by key search) across the newest 5 `projects/*/*.jsonl`. `rejected` gives limited, `resetsAt` sets the window reset, `five_hour`/`seven_day` give the label. It never returns a %.
  - Grok/Gemini: this Mac has no `~/.grok*` or `~/.gemini` and neither CLI is on PATH. So the code returns `connected` only when `which(cli)` finds one, and omits the provider otherwise.
  - A window whose `resets_at` has passed gets `stale: true` and loses `used_percent`. If every window is stale, the provider is `stale`.
  - No new subprocess (`shutil.which` only), no writes, no auth files.
- Real-data smoke run of `read_usage()` on this Mac: Codex Weekly 21% pro, ok. Claude's last rejection (`seven_day`) has already reset, so it shows stale.
- `bridge/tests/test_bridge.py` class `Usage` (7 tests) uses copied, redacted real lines:
  - Codex 15% weekly pro → `Weekly 15%`, with resets_at.
  - Claude rejected/seven_day → limited, no %.
  - Also covers the newest event across files, the 5 hours/Weekly windows, stale, connected/omitted, the tail read dropping a cut line, and no write or auth names in the reader.
- Protocol/store/mock:
  - `UsageProvider` types in `src/lib/protocol.ts`; `usage()` action in `src/state/store.ts`.
  - `e2e/mock-bridge.mjs`: `usage.read` fixture (codex 73/60 near, claude limited, grok connected), plus a test-control op `mock.usage {fixture:"stale"}`.
- UI:
  - `src/sidebar/Usage.tsx` sits in the sidebar foot above the user row. It shows a 26px button per provider: a 14px AgentIcon with an SVG ring at the max live % (gray <70, amber 70–90, red >90), or a state dot when there is no %. A limited provider gets a red dot.
  - Hover or focus opens the card; click pins it; Escape or an outside click closes it. The card has radius 8 and 12px text and shows provider + plan, then `5 hours  73%  resets in 1h 47m`, `Limited until Tue 00:15`, `stale`, or `Connected · no usage record`.
  - It refreshes every 60 s while the bridge is open.
  - Pure rules live in `src/sidebar/usageFormat.ts`, tested by `usageFormat.test.ts`.
- `e2e/usage.spec.ts` (5 tests): marks render above the user row; amber ring vs no ring; the hover card text; Claude shows "Limited until" and no %; the stale fixture shows "stale" with no number or ring; plus the screenshots.
- BOUNDARY: new rule 11 in `docs/OMHER-BOUNDARY.md` (reads only the CLIs' own usage records, never auth/tokens, no writes, sends nothing). `tests/test_omher_boundary.py` pins the sentence, and the rule cap went from 10 to 12 with a reason comment. That edit is outside apps/omher; it was needed because rule 11 broke the old 6–10 cap.

## VERIFY (literal tails, final run on HEAD fe8398d6f; log ~/.hermes/profiles/kami/cache/scratch/omher-v02/t7t10-verify.log)
```
== typecheck+test
 Test Files  5 passed (5)
      Tests  43 passed (43)
rc=0
== bridge
Ran 59 tests in 0.756s
OK
rc=0
== e2e   (OMHER_PORT=5431 OMHER_MOCK_PORT=5432 lockf … playwright test e2e/usage.spec.ts)
  5 passed (6.0s)
rc=0
== boundary   (PYTHONPATH=tests … unittest tests.test_omher_boundary)
Ran 8 tests in 3.368s
OK
rc=0
== diff-check   (git diff --check 8a6d72016 HEAD)
rc=0
```

## Screenshots (~/.hermes/profiles/kami/cache/scratch/omher-v02/)
- T7-agents-dark.png (vision 8.5/10), T7-agents-light.png (8/10): the 22 marks plus the `zed` letter fallback, at 22px and 16px.
- T10-usage-codex-dark.png (8.5/10), T10-usage-codex-light.png (7.5 before the margin fix; the fix was then confirmed on the dark shot).
- T10-usage-claude-dark.png (7 before the margin fix), T10-usage-claude-light.png (8/10 after the fix).
- Vision found and I fixed: a translucent card in the screenshots (the fade-in was captured, so screenshots now run with animations disabled); the no-% row overflowing (that row now has two columns); the card sitting flush against the sidebar divider (it now spans left:0/right:0 of the footer column).

## Open / notes
- Leftover vision nitpicks I did not act on: the pi and Kilo Code marks lose detail at 16px (the marks are unedited by rule); the omp tile has low contrast on dark (it is the official tile); there is no caret on the card.
- AgentIcon is not yet wired into the SESSIONS `+` menu, which belongs to another lane.
- Grok/Gemini adapters are state-only, because no local usage record format exists on this machine.
