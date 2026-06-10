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
hermes skills tap add rlaope/oh-my-hermes-agent
hermes skills install rlaope/oh-my-hermes-agent/skills/oh-my-hermes --yes
```

Pinned stable install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

Preview install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

Preview update with an auditable source ref:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_SOURCE_REF=main@<sha> sh
```

Custom archive:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_PACKAGE_URL=https://github.com/rlaope/oh-my-hermes-agent/archive/refs/tags/v<version>.zip sh
```

Optional plugin/profile bootstrap smoke:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_WITH_PLUGIN=1 OMH_PROFILE_PACKS=cto-loop OMH_RUN_DOCTOR=0 sh
```

## Required Checks

Run before tagging:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m omh.cli docs workflows --check
python3 -m omh.cli harness validate
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke install --dry-run --channel stable --version 1.0.0
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --dry-run --channel stable --version 1.0.0
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --with-plugin --dry-run --channel stable --version 1.0.0
python3 -m omh.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke probe
python3 -m omh.cli release hermes-smoke
uv build
python3 -m venv /tmp/omh-wheel-smoke
/tmp/omh-wheel-smoke/bin/python -m pip install --upgrade dist/oh_my_hermes_agent-1.0.0-py3-none-any.whl
/tmp/omh-wheel-smoke/bin/omh --help
/tmp/omh-wheel-smoke/bin/omh --omh-home /tmp/omh-wheel-home --hermes-home /tmp/hermes-wheel-home setup --dry-run --channel stable --version 1.0.0
OMH_PYTHON=/tmp/omh-wheel-smoke/bin/python OMH_PACKAGE_URL=file://$PWD/dist/oh_my_hermes_agent-1.0.0-py3-none-any.whl OMH_VENV_DIR=/tmp/omh-installer-venv OMH_BIN_DIR=/tmp/omh-installer-bin OMH_SETUP_ARGS="--dry-run" OMH_RUN_DOCTOR=0 sh install.sh
```

## Hermes CLI Install Smoke

The release gate includes a deterministic smoke plan for the real Hermes CLI
path. Plan mode is safe for CI because it does not touch the current Hermes
profile:

```sh
python3 -m omh.cli release hermes-smoke
```

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

The live smoke runs install/setup plus:

```sh
hermes skills tap list
hermes skills list --enabled-only
hermes skills check oh-my-hermes
hermes skills inspect rlaope/oh-my-hermes-agent/skills/oh-my-hermes
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
- Capability probe status.
- Hermes CLI install smoke status, including whether it was plan-only or live.
- Optional plugin bundle status when `omh setup --with-plugin` changed.
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
Hermes runtime-load or hook/tool-use evidence.
