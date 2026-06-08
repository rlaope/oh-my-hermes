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
hermes skills install oh-my-hermes
```

Pinned stable install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_CHANNEL=stable OMH_VERSION=<version> sh
```

Preview install:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | sh
```

Custom archive:

```sh
curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes-agent/main/install.sh | OMH_PACKAGE_URL=https://github.com/rlaope/oh-my-hermes-agent/archive/refs/tags/v<version>.zip sh
```

## Required Checks

Run before tagging:

```sh
python3 -m unittest discover -s tests
python3 -m compileall src
python3 -m src.cli docs workflows --check
python3 -m src.cli harness validate
python3 -m src.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke install --dry-run --channel stable --version 0.1.0
python3 -m src.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --dry-run --channel stable --version 0.1.0
python3 -m src.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke setup --with-plugin --dry-run --channel stable --version 0.1.0
python3 -m src.cli --omh-home /tmp/omh-smoke --hermes-home /tmp/hermes-smoke probe
```

Runtime evidence smoke:

```sh
run_json="$(python3 -m src.cli --omh-home /tmp/omh-smoke runtime record --skill oh-my-hermes --harness coding-handling --status started)"
run_id="$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"]["run_id"])')"
python3 -m src.cli --omh-home /tmp/omh-smoke runtime delegate --run "$run_id" --requested --not-observed --result not_observed
python3 -m src.cli --omh-home /tmp/omh-smoke runtime wrapper --run "$run_id" --prompt-dispatched --response-observed --completion-status completed
python3 -m src.cli --omh-home /tmp/omh-smoke runtime validate --run "$run_id"
python3 -m src.cli --omh-home /tmp/omh-smoke runtime export --redacted
```

## Release Notes Must Include

- Release version and channel.
- Hermes skill tap/install wording and bootstrap install target used for smoke testing.
- Update path tested.
- Workflow docs generation status.
- Harness catalog validation status.
- Runtime validation status.
- Capability probe status.
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
