# Release Process

This project ships a conservative Hermes skill layer. A release is ready only
when install behavior, generated workflow docs, runtime evidence validation, and
public claims are all checked.

## Channels

| Channel | Purpose | Install target |
| --- | --- | --- |
| `stable` | Pinned user installs and support reproduction | Hermes skill tap plus published Git tag archive such as `v<version>` |
| `preview` | Latest `main` for early testing | Hermes skill tap plus `main` branch archive |
| `local` | Maintainer smoke tests from local fixtures | Explicit local source or package URL |

Hermes-native skill install:

```sh
hermes skills tap add rlaope/oh-my-hermes
hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes
```

Pinned stable install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

Preview install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh
```

Preview update with an auditable source ref:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_SOURCE_REF=main@<sha> sh
```

Custom archive:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_PACKAGE_URL=https://github.com/rlaope/oh-my-hermes/archive/refs/tags/v<version>.zip sh
```

Advanced one-shot setup compatibility smoke:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | OMH_RUN_SETUP=1 OMH_PROFILE_PACKS=cto-loop OMH_RUN_DOCTOR=0 sh
```

## Required Checks

Run before tagging:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m omh.cli docs workflows --check
python3 -m omh.cli harness validate
python3 -m omh.cli release checklist --json
python3 -m omh.cli release skill-content-smoke --json
python3 -m omh.cli release product-readiness --version 1.0.1 --json
python3 -m omh.cli release evidence-bundle --version 1.0.1 --write --json
python3 -m omh.cli cases demo --all --json
python3 -m omh.cli cases artifact --all --json
python3 -m omh.cli cases replay --json
python3 -m omh.cli cases readiness --json
python3 -m omh.cli demo routing-precision --json
python3 -m omh.cli demo router-fast-path --json
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke learning review --all
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke install --dry-run --channel stable --version 1.0.1
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --dry-run --channel stable --version 1.0.1
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke probe
python3 -m omh.cli release hermes-smoke
python3 -m omh.cli release install-smoke
omh release install-smoke --live --repo-root "$PWD" --install-script "$PWD/install.sh"
omh --help
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --install-path setup --omh-command omh --include-command-smoke
uv build
python3 -m venv /tmp/omh-wheel-smoke
/tmp/omh-wheel-smoke/bin/python -m pip install --upgrade dist/oh_my_hermes-1.0.1-py3-none-any.whl
/tmp/omh-wheel-smoke/bin/omh --help
/tmp/omh-wheel-smoke/bin/omh release skill-content-smoke --json
/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home release hermes-smoke --install-path setup --omh-command /tmp/omh-wheel-smoke/bin/omh --include-command-smoke
/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home setup --dry-run --channel stable --version 1.0.1
OMH_PYTHON=/tmp/omh-wheel-smoke/bin/python OMH_PACKAGE_URL=file://$PWD/dist/oh_my_hermes-1.0.1-py3-none-any.whl OMH_VENV_DIR=/tmp/omh-installer-venv OMH_BIN_DIR=/tmp/omh-installer-bin sh install.sh
/tmp/omh-installer-bin/omh --omh-home /tmp/omh-installer-home --hermes-home /tmp/omh-installer-hermes setup --dry-run
```

The checklist command renders the same release gates as a deterministic
`release_readiness_checklist/v1` contract:

```sh
omh release checklist --version 1.0.1
omh release checklist --version 1.0.1 --json
```

It is plan-only: it does not run checks, mutate Hermes, create tags, or publish
GitHub releases. Treat it as the operator-facing index of the evidence that must
be attached before a stable tag.

The checklist also gates the G1-G10 use-case demo cards through
`omh cases demo --all --json`. That proves OMH can render wrapper-safe
use-case projections with route, action, status-card, and evidence-boundary
metadata. It is not evidence that cron, connectors, files, memory updates,
executors, reviews, CI, merges, or delivery actually ran.

It also gates the G1-G10 use-case artifact bundle through
`omh cases artifact --all --json`. That proves OMH can render local prepared
runbooks with operator steps and proof surfaces for each use case. It is not
evidence that those runbooks were accepted, executed, delivered, reviewed,
verified, merged, or billed by any runtime.

The same gate replays G1-G10 natural-language use-case fixtures through
`omh cases replay --json`. That proves deterministic routing for the checked-in
synthetic English/Korean operator corpus. It is not evidence that a live Hermes
profile selected the route in chat or that any connector, executor, review, CI,
merge, delivery, or billing event happened.

The readiness rollup, `omh cases readiness --json`, combines the catalog,
demo-card, artifact-bundle, replay, and optional local artifact-store states
into one operator-readable card. It should be ready before a release, but it
still proves only local deterministic contracts, not live Hermes selection or
runtime execution.

The grounded routing score checks representative operator requests end to end:

```sh
omh demo grounded-score --json
```

It should report every scenario at `10/10`. This catches regressions where a
realistic operator message still routes somewhere, but the selected skill,
response kind, next action, playbook recommendation, coding boundary, or
prepared-vs-observed wording no longer matches the product contract. It remains
local deterministic contract-compliance evidence only: it does not prove live
Hermes chat rendering, executor execution, review, CI, merge, delivery, or
plugin loading.

The wrapper chat-card gate checks the user-facing card corpus:

```sh
omh demo chat-card-coverage --json
```

It should report every representative workflow route as a dedicated chat card
with generic ack count `0`. This catches regressions where Hermes would answer a
real operator request with a vague acknowledgement instead of an actionable
workflow card. It is still local deterministic wrapper-contract evidence only:
it does not prove live Hermes rendering, platform delivery, executor execution,
review, CI, merge, or plugin loading.

The route-hint alignment gate checks the same public story from the
Hermes-awareness side:

```sh
omh demo route-hint-alignment --json
```

It should report every grounded-score and chat-card scenario with a primary
plugin awareness hint that matches the router-selected workflow. This catches
regressions where the chat router chooses the right skill, but the plugin hint
returns `no_hint` or points the wrapper at a different workflow. It remains
local deterministic router/hint agreement evidence only: it does not prove live
Hermes chat rendering, platform delivery, executor execution, review, CI, merge,
or plugin loading.

The context-brief coverage gate checks the first-turn Hermes mental model that
is shown before generic image, file, search, chat, or coding tools:

```sh
omh demo context-brief-coverage --json
```

It should report representative visual-summary, catalog-picker, feedback,
GitHub issue, paper-learning, source-finder, safe-feature, and web-research
prompts with a metadata-only `omh_context_brief/v1`, matching route hint or
picker hint, generic-tool checkpoint, bounded prompt context, and evidence
boundary. It is local context-contract evidence only: it does not prove live
Hermes chat rendering, plugin load, generic tool invocation, source retrieval,
image generation, executor dispatch, review, CI, merge, or delivery.

The routing precision gate checks both sides of the router boundary:
negative-control prompts where OMH should not open a workflow, and expected
intervention prompts where OMH should route to a workflow, picker, or bounded
context brief:

```sh
omh demo routing-precision --json
```

It should report ordinary file lookup and general-help prompts as direct file
lookup or direct chat answers with overroute count `0`, catalog picker count
`0`, and generic acknowledgement count `0`. It should also report OMH-shaped
requests with missed intervention count `0`, including safe feature planning,
source acquisition, image-card preparation, feedback triage, workflow catalog
opening, and OMH usage context. This catches regressions where OMH feels pushy
for ordinary questions or too passive for requests that should use OMH. It is
local routing-boundary evidence only: it does not prove live Hermes chat
rendering, source retrieval, file inspection, executor dispatch, review, CI,
merge, or plugin loading.

The localized chat-copy gate checks common non-English operator prompts:

```sh
omh demo localized-chat-copy --json
```

It should report every localized card case passing across the supported local
copy fixtures. This catches regressions where a Japanese, Chinese, Spanish,
French, German, or Korean user prompt still routes correctly but falls back to
English framing, loses the expected card kind, or changes the next action. It is
local copy-contract evidence only: it does not prove live Hermes chat rendering,
translation quality, platform delivery, source retrieval, executor dispatch,
review, CI, merge, or plugin loading.

The router fast-path gate checks common chat turns where perceived latency is
most visible:

```sh
omh demo router-fast-path --json
```

It should report picker, status, direct-answer, file-lookup, setup health,
product issue, coding progress, image-card, scheduled-ops, paper-learning, and
source-finder prompts as staying on explicit fast-path route markers. This is a
deterministic route-contract guard, not a wall-clock benchmark. It catches
regressions where frequent chat turns accidentally fall back to slower full
workflow scoring or drift into the wrong next action.

The Hermes UX quality rollup checks the chat-first user experience across the
routing, card, hint, context, precision, localized-copy, and fast-path rails:

```sh
omh demo hermes-ux-quality --json
```

It should report all UX gates passing: grounded natural-language routing,
dedicated wrapper cards with generic acknowledgements at zero, route hints
aligned with the router, first-turn context briefs with catalog picker coverage,
negative-control prompts that stay out of OMH workflows, expected intervention
prompts that still enter the right workflow surface, and common non-English
operator prompts that keep local card framing, and frequent requests that stay
on deterministic fast paths. It is local UX-contract evidence only: it does not
prove live Hermes chat rendering, plugin load, platform
delivery, generic tool invocation, executor dispatch, review, CI, merge, or
delivery.

The product readiness rollup sits one level above use cases:

```sh
omh release product-readiness --version 1.0.1 --json
```

It checks the generated skill content, G1-G10 readiness, grounded routing score,
wrapper chat-card coverage, route-hint alignment, context-brief coverage,
routing precision, router fast-path quality, Hermes UX quality, parity matrix,
and release checklist shape in one operator-readable card. It is useful for
release notes and maintainer handoff, but it is still local deterministic evidence only: it does
not run the checklist, mutate Hermes, dispatch executors, review code, pass CI,
merge, deliver messages, or spend provider budget.

When the local release story is ready, write an attachable evidence bundle:

```sh
omh release evidence-bundle --version 1.0.1 --write --json
```

The bundle writes `omh_release_evidence_bundle/v1` under
`.omh/runtime/release-evidence/` with the checklist, product readiness,
skill-content smoke, use-case readiness, grounded score, chat-card coverage,
route-hint alignment, context-brief coverage, routing precision, Hermes UX
quality, and parity snapshots. It is useful for release PRs and notes, but it is
still local deterministic evidence only; live Hermes smoke, CI, review, merge,
delivery, and GitHub release publication must be observed separately.

## Hermes CLI Install Smoke

The release gate includes a deterministic smoke plan for the real Hermes CLI
path. Plan mode is safe for CI because it does not touch the current Hermes
profile:

```sh
python3 -m omh.cli release hermes-smoke
```

The installer gate separately checks the user-facing `curl ... | sh` entry
point without depending on curl or GitHub. Plan mode reports the isolated target
and remains unobserved:

```sh
python3 -m omh.cli release install-smoke
```

Live mode executes the local `install.sh` in a temporary HOME with an isolated
OMH virtual environment and bin directory. It installs from the local checkout,
does not run setup through the installer, and then runs installed-command
smoke. It does not mutate the operator's real Hermes profile or prove a later
Hermes chat selected OMH:

```sh
omh release install-smoke --live --repo-root "$PWD" --install-script "$PWD/install.sh"
```

The plan includes two release-contract subchecks:

- `installed_command_smoke`: first resolves the installed `omh` command path,
  then proves the console script can run `omh --help` and render the setup-path
  smoke plan.
- `first_use_status_smoke`: documents the first Hermes chat/status path and
  locks that pre-handoff status cards do not expose executor open/result
  actions.

Run the installed command smoke in CI or a release shell after installing OMH:

```sh
command -v omh
omh --help
omh release skill-content-smoke --json
omh release product-readiness --version 1.0.1 --json
omh release evidence-bundle --version 1.0.1 --write --json
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --install-path setup --omh-command omh --include-command-smoke
```

`release skill-content-smoke` is non-mutating package-content evidence. It
checks that the command package can render the router awareness primer and the
generated workflow context rails that keep direct skill invocation inside the
broader OMH model. It also checks all-skill awareness lane coverage, full
capability manifest context, bundled role context, standalone plugin capability
fallback coverage, playbook capability context, fallback routing/context/boundary
fields, bounded prompt context budgets, and bounded capability payload budgets so
the shared OMH mental model stays present without becoming prompt bloat or
manifest bloat. It does not prove Hermes loaded those skills or selected them in
chat.
In short, this gate preserves bounded context budgets while still giving Hermes
enough OMH workflow context to route well.

For release candidates, run exactly one live smoke against the target Hermes
profile and paste the JSON result into the release note. Use the native tap
path when Hermes skill taps are available:

```sh
omh release hermes-smoke --live --install-path tap --target-confirmed
```

Use the bootstrap path when validating the installer-managed `skills.external_dirs`
route instead:

```sh
omh release hermes-smoke --live --install-path setup --target-confirmed
```

For an isolated smoke profile, bind the target home explicitly instead of
confirming the ambient default profile:

```sh
omh --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke release hermes-smoke --live --install-path setup
```

The live smoke runs the selected Hermes install path plus:

```sh
hermes skills tap list
hermes skills list --enabled-only
hermes skills check oh-my-hermes
hermes skills inspect rlaope/oh-my-hermes/skills/oh-my-hermes
```

Passing the tap smoke means Hermes CLI install/list/check/inspect commands
succeeded for the target profile. Passing the setup smoke means OMH managed
skill setup, Hermes list/check visibility, and `omh doctor` succeeded for the
target profile. It still does not prove a later Hermes chat session selected
OMH unless that chat response is observed separately.

Runtime evidence smoke:

```sh
run_json="$(python3 -m omh.cli --omh-home /tmp/omh-smoke runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
python3 -m omh.cli --omh-home /tmp/omh-smoke runtime delegate --run "$run_id" --requested --not-observed --result not_observed
python3 -m omh.cli --omh-home /tmp/omh-smoke runtime wrapper --run "$run_id" --prompt-dispatched --response-observed --completion-status completed
python3 -m omh.cli --omh-home /tmp/omh-smoke runtime validate --run "$run_id"
python3 -m omh.cli --omh-home /tmp/omh-smoke runtime export --redacted
```

Source-checkout console smoke:

```sh
uv run --no-editable omh recommend "risky refactor" --limit 1 --json
```

Use `uv run python -m omh.cli ...` for fast module-level development checks.
Use `uv run --no-editable omh ...` when the release question is whether the
packaged `omh` console script imports and runs from a source checkout. This
check is local command importability only; it is not Hermes chat visibility,
plugin load, executor dispatch, review, CI, merge, or delivery evidence.

## Release Notes Must Include

- Release version and channel.
- Hermes skill tap/install wording and bootstrap install target used for smoke testing.
- Update path tested.
- Workflow docs generation status.
- Harness catalog validation status.
- Source-checkout console script smoke status.
- Runtime validation status.
- Workflow learning review queue status when workflow-learning contracts changed.
- Capability probe status.
- Install script smoke status, including whether it was plan-only or live.
- Hermes CLI install smoke status, including whether it was plan-only or live.
- Plugin bundle status when `omh setup` changed.
- GitHub Pages workflow status when public site copy changed.
- Known manual Hermes checks that could not be automated.
- Any public claim that depends on wrapper evidence rather than Hermes-native
  capability evidence.

## Known Gap Language

Use explicit proof-boundary language:

- "Prompt-level routing guidance" when only installed skills are involved.
- "Wrapper-observed" when evidence comes from a bot or shell wrapper.
- "Not observed" when specialist delegation metadata is unavailable.

Do not claim native Hermes runtime use from plugin installation alone.
`plugin_distribution_ready` means the local bundle exists and passed local
import/register smoke; `native_integration_claim_ready` still requires observed
Hermes active runtime-load, hook/tool-use, or status-query evidence. Session-end
and plugin-unload observations are historical evidence only.
