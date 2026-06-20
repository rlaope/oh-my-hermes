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

## Release Notes Must Include

- Release version and channel.
- Hermes skill tap/install wording and bootstrap install target used for smoke testing.
- Update path tested.
- Workflow docs generation status.
- Harness catalog validation status.
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
