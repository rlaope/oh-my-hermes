# Vim char-search — shipment verification evidence

## Task disposition

- **2.2 checked:** `evidence/char-apply/candidate-manifest.json` binds accepted word parent `d71173ca59246a1c5351fddeb49372d903e7ae10`, concrete candidate root, source/accepted-artifact hashes, owned patch SHA-256 `e713616776648daf4faeeec66ad3cae1eb034d745c0f80286ca4bf2ef54aac97` and fresh environment digest `4c399faf61af8bf573915003672cc731506146fd1bf0b57e276dfe0b490a8adc`. `evidence/qa-char-search-independent/binding.json` independently binds that candidate and patch; its manifests/restore checks preserve original tests and exclude undeclared source changes. Final identity/input hashes and replay above rebind the repaired/archived candidate; no stale pre-feature digest substitutes for that evidence.
- **3.1 checked:** all acceptance assertions/subcases independently replayed with zero skips/placeholders; sibling/original regression suites pass subject to the one explicitly disclosed, unchanged platform skip. `evidence/qa-char-search-independent/` records all 19 control definitions: 14 actual semantic reversals, four inherited discriminating fixtures, one conditional unavailable-reversal fallback. Do not relabel this as 19 actual reversals.
- **3.2 remains unchecked:** strict validation, planning audit, behavioral QA, branch-delta review/targeted repairs and current Human release/archive permission are evidenced. Native admission/closure was not run, so the composite lifecycle task is not marked complete.

## Candidate and independent results

- Base: `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`.
- Word implementation: `bc6066a3c3cdbf4650762dd5b7fd276a3fc5663f`; preserved plans: `d71173ca59246a1c5351fddeb49372d903e7ae10`.
- Search implementation: `a168ea2415efcf2e1d698ca4f62e7c802b60a866`; R1/R2 repair: `6392f5de5a2b468e6451e9a53b4c59e4fabd9ed0`.
- Independently verified archive candidate: `96fbb4487a131b1da35687f0cceffd9685947149` (authoritative Git identity; the earlier archive handoff's full SHA was incorrect).
- Final independent replay: 25 acceptance methods / 547 successful subTests (WO: 211; CS: 336), zero acceptance skips/errors/failures; 201 focused tests pass; 3558 full TUI tests, OK with one unchanged Windows-only skip. Both strict specs pass. This reconciliation changes documentation only, so these are existing observed results, not newly executed Python tests.
- Cross-slice branch-delta review initially requested R1/R2 changes on the search commit. Both findings were independently closed on the archive candidate after repair; no second broad review or new approval verdict is invented.

## Portable evidence coordinates

Evidence paths below are relative to the preserved run root `tui-vim-apply-20261104/` (outside the Git checkout). Raw logs are retained there, not embedded or falsely advertised as committed attachments:

| Evidence | Observed result / binding |
| --- | --- |
| `final/delivery-summary.md` | Technical PASS; SHA-256 `3d59c4109db98aae44db8390f572968b0e505697a30f89b95e1437d0128c1985`; contains exact commands, environments and raw-log hash ledger |
| `final/requirements-evidence-map.json`, `final/acceptance-results.json` | Every WO-1..7 / CS-1..7 acceptance method and declared subcase mapped and replayed |
| `final/source-identity.json`, `final/input-hashes.json`, `final/command-index.json` | Candidate, source/plan/input hashes and exact execution coordinates; not a native controller manifest |
| `final/acceptance.log` | Exit 0; SHA-256 `c81c232e8b4e7fcf1c35d0ac4731272d3d3b1589df19d2f4acb681270a9a8128` |
| `final/focused.log` | Exit 0; SHA-256 `232f2e3fa232970ce61491d94b0470a5d7e5a15740088a64acf0a3d65af51b7a` |
| `final/full-tui.log`, `final/skip-inventory.json` | Exit 0; SHA-256 `172c3c77629cb9d72b339b98e621d3571368c145353e194854e359493830d6dc`; sole skip is the Windows-only doctor message test |
| `final/negative-result.json`, `final/negative-semantic.log`, `final/negative-restored-five.log` | App precedence reversal: 96 intended assertion failures, then exact restoration and all five new App regressions pass |

## Human decision and limits

The current shipment request explicitly conveys Human **SHIP IT** after technical PASS / lifecycle HOLD. Record that as present delivery/publication approval and reconciliation of release/archive permission, not as a claim that approval existed before `archive -y`, a merge decision, a completed publication, or native READY. The earlier final report remains an immutable historical snapshot taken before that decision.

Native controller sidecar, READY, admission, amendment, observation and closure remain **NON_RUN**. Mechanical archive and zero active changes prove directory/schema state only. Original commits are preserved and their missing DCO/Lore trailers are not retroactively certified. No source/tests/runtime change, push, PR, merge or installation is performed by this reconciliation.
