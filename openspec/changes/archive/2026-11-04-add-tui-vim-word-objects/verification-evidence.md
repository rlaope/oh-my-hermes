# Vim word-objects — shipment verification evidence

## Task disposition

- **3.1 checked:** exact final-candidate independent acceptance plus full regression replay is observed. The documented isolated interpreter substituted for the original Homebrew full-suite command; both identity and fixture boundary are disclosed in the final report. The Windows-only regression skip is not an acceptance skip or a hidden test exemption.
- **3.2 remains unchecked:** branch-delta review and the current Human delivery decision are satisfied; native amendment/observation/closure evidence is absent. Separate word/search implementation commits and separate specification packages remain intact even though the parent will publish one cohesive PR. No native closure is inferred.
- Earlier checked tasks remain supported by independent word QA/control evidence at `evidence/qa-word-independent/` and producer rollback evidence at `evidence/word-gates/`; planning baseline output alone is not used as feature proof.

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
