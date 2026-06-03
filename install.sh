#!/usr/bin/env sh
set -eu

OMH_PACKAGE_URL="${OMH_PACKAGE_URL:-https://github.com/rlaope/oh-my-hermes-agent/archive/refs/heads/main.zip}"
OMH_PYTHON="${OMH_PYTHON:-python3}"
OMH_PIP_ARGS="${OMH_PIP_ARGS:---user}"
OMH_AUTO_APPLY="${OMH_AUTO_APPLY:-1}"
OMH_RUN_DOCTOR="${OMH_RUN_DOCTOR:-1}"

say() {
  printf '%s\n' "$*"
}

run_omh() {
  "$OMH_PYTHON" -m omh.cli "$@"
}

if ! command -v "$OMH_PYTHON" >/dev/null 2>&1; then
  say "omh installer: '$OMH_PYTHON' was not found."
  say "Set OMH_PYTHON to a Python 3.11+ executable and retry."
  exit 1
fi

say "Installing oh-my-hermes-agent..."
"$OMH_PYTHON" -m pip install $OMH_PIP_ARGS --upgrade "$OMH_PACKAGE_URL"

say "Installing managed Hermes skills..."
run_omh install

if [ "$OMH_AUTO_APPLY" = "0" ]; then
  say "Skipped Hermes config registration because OMH_AUTO_APPLY=0."
else
  say "Registering managed skill directory with Hermes..."
  run_omh apply
fi

if [ "$OMH_RUN_DOCTOR" = "0" ]; then
  say "Skipped doctor check because OMH_RUN_DOCTOR=0."
else
  say "Verifying installation..."
  run_omh doctor
fi

say "oh-my-hermes-agent is installed."
say "Run 'omh list' to inspect installed skills."
