# Project Bootstrap Pass

**A project that outlives the session earns its management files at birth, not on a later cleanup pass.** Load this reference when the app delivery loop opens on a directory that is empty, freshly `git init`-ed, or missing the base file set below. Skip it, explicitly, for a throwaway script or a scratch experiment that is not expected to survive the session - naming the skip is the decision; silence is not.

This is bootstrap territory only. A repository that already has history, a README, and a working build belongs to onboarding and refactor work, not this pass.

## The six-step order

Run the steps in this order; each carries its own verify line, and a step whose verify was not actually run is `prepared_not_observed` - say so instead of claiming it.

1. **Git and .gitignore.** Initialize version control before anything else touches the tree.
   - `git init` if no repository exists yet.
   - Build `.gitignore` from the toolchain actually observed in the project (language, package manager, editor artifacts) - never paste in an unrelated kitchen-sink template. Always include the local-only files: `.env*` (with a committed `.env.example` holding names only), key and certificate files, and OS and editor files. Turn on secret scanning or push protection on the remote before the first push.
   - Commit the empty or near-empty tree as the first commit so later history has a clean root.
   - Wrong: a Python project ignoring `node_modules/` it will never create. Right: a `.gitignore` whose every line maps to a file this project's own build actually produces.
   - Self-test: does every line in `.gitignore` correspond to a byproduct this project's own toolchain generates or to a local-only file (`.env*`, keys, OS and editor files), with no line unrelated to either?
   - Verify: `git status --short` shows no generated or vendor noise after a build runs.

2. **LICENSE.** One canonical file, one declared identifier, everywhere that identifier appears.
   - Ask the owner which license applies; the choice is theirs. With one stated, write the matching `LICENSE` file at the repository root and use its single SPDX identifier. With none stated, add no open-source license: write no `LICENSE` (or a proprietary notice), set the metadata license field to the `UNLICENSED` value, and record the open question.
   - Match that identifier everywhere a license gets declared: package metadata, README license line, plugin or extension manifests.
   - Never declare a license in metadata without committing the file it names - license-declared-but-no-file is a named drift class, not a cosmetic gap, because it leaves a legal claim with nothing backing it.
   - Treat a license change as a decision requiring the same review as any other file it touches; do not silently swap identifiers between files.
   - Self-test: does grep for the SPDX identifier return a hit in the LICENSE file itself and every metadata site that names it, with none disagreeing?
   - Verify: the LICENSE file exists AND every declared SPDX identifier in the project matches it byte-for-byte.

3. **README.md.** Sections in a fixed order, and every command in it has actually been run.
   - What it is: one paragraph, plain description, no marketing language.
   - Quickstart: copy-pasteable commands, each one proven by execution before it is written down.
   - Build and test commands: the exact commands the project uses, not a framework's generic default.
   - Project layout: only when the layout is non-obvious: a flat single-file project earns no layout section.
   - License line: the one-line pointer to LICENSE, using the same SPDX identifier as step 2.
   - Length discipline: when a section would run longer than roughly one screen, it moves to `docs/` and the README keeps a one-line pointer instead of the full text.
   - Wrong: a README quickstart copied from a template with commands nobody ran against this project. Right: every quickstart line pasted from a terminal that actually executed it and produced the output claimed.
   - Self-test: has every command in this README been executed, with its observed output matching what the README claims?
   - Verify: every command in the README was executed and its observed output matches what the README claims; a command that was only reasoned about, not run, is `prepared_not_observed` and must not be presented as proven.

4. **Agent context file.** `AGENTS.md` as the behavioral contract, with a `CLAUDE.md` pointer or symlink when the host expects that name.
   - Write it as a contract, not a description: exact build, test, and lint commands; code-style rules that differ from the language's own defaults; testing conventions; boundaries naming what agents must not touch; commit and PR conventions.
   - Keep the always-loaded layer lean - roughly 150 lines - and push anything longer into `docs/` references the context file points to.
   - Cache-stable: zero volatile bytes. No dates, no counts, no status lines - anything that changes between sessions belongs in a message, not in this file. See `omh-context-budget-review/references/cache-placement.md` for the full placement discipline behind this rule.
   - Posture: write it as a base layer a team extends, not a finished specification - state assumptions the team is expected to override, rather than presenting every choice as final.
   - Wrong: "This project uses good testing practices." Right: "Run `npm test` before every commit; new modules require a colocated `*.test.ts` file."
   - Self-test: could an agent given only this file run build and test successfully, with no other context?
   - Verify: an agent given only this file runs build and test successfully.

5. **CI skeleton.** One workflow, running the commands the README and context file already named.
   - Wire the CI job to call the exact same commands documented in the README and the agent context file - never a hand-typed variant that quietly drifts.
   - Add a build matrix only when the project genuinely targets more than one runtime or platform; a matrix for a single-target project is a speculative option - drop it until a second target exists.
   - Keep the first workflow small enough to read in one pass: lint, test, and the project's own build step, nothing speculative.
   - Self-test: run `diff` in your head between the CI step commands and the README/context-file commands - do they match exactly?
   - Verify: the first CI run is green, and the CI commands are string-identical to the documented ones - not merely equivalent.

6. **docs/ seed.** Created only when there is real overflow to hold.
   - Create `docs/` only once three or more topics have already overflowed the README under the length-discipline rule in step 3.
   - An empty `docs/` directory scaffolded "for later" is speculative structure with nothing in it; skip it explicitly instead.
   - When `docs/` is created, each file replaces one README section that pointed to it, keeping the single-source rule below intact.
   - Self-test: can you name the three-plus README sections that just overflowed into this directory?
   - Verify: every file under `docs/` is the target of a README pointer, and no file sits unreferenced.

## Cross-cutting bars

- **Single source of truth.** Build, test, and lint commands appear once, in the agent context file, and every other surface - README, CI - references or repeats that same string. README/CI/context-file divergence is a named failure class: the moment two of these three disagree, one of them is wrong and both need reconciling, not just the one that got noticed.
- **Generated-file honesty.** A bootstrap file whose claims were not executed - a README command never run, a CI workflow never triggered - stays `prepared_not_observed` until it is. Say so plainly rather than implying the pass is finished.
- **No self-promotion.** No persona branding, no badges that do not carry a real, checked status behind them.
- **English by default.** Bootstrap output follows the repository's English-by-default contract unless the project's own audience and existing content are already localized.

## When to skip

Explicitly say so instead of silently doing nothing: a quick scratch script or a throwaway spike that is not expected to survive the session skips this pass entirely. The disclaimer itself - "skipping the bootstrap pass; this is throwaway work" - is the deliverable in that case, not a missing step.

## Attribution

The six-step ordering and per-step verify format adapt general, publicly documented conventions: the community `agents.md` standard for agent-facing context files (setup, build, test, style, and PR sections; nearest-file-wins resolution) and the SPDX license-identifier convention for machine-readable license declarations. No text is reproduced from either source; the wording, ordering, and verify contract above are OMH's own.
