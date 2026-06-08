#!/usr/bin/env sh
set -eu

OMH_REPO_ARCHIVE_ROOT="${OMH_REPO_ARCHIVE_ROOT:-https://github.com/rlaope/oh-my-hermes-agent/archive/refs}"
OMH_CHANNEL="${OMH_CHANNEL:-preview}"
OMH_VERSION="${OMH_VERSION:-}"
OMH_PACKAGE_URL="${OMH_PACKAGE_URL:-}"
OMH_PYTHON="${OMH_PYTHON:-python3}"
OMH_PIP_ARGS="${OMH_PIP_ARGS:---user}"
OMH_AUTO_APPLY="${OMH_AUTO_APPLY:-1}"
OMH_RUN_DOCTOR="${OMH_RUN_DOCTOR:-1}"
OMH_WITH_PLUGIN="${OMH_WITH_PLUGIN:-0}"
OMH_PROFILE_PACKS="${OMH_PROFILE_PACKS:-}"
OMH_SETUP_PROFILES="${OMH_SETUP_PROFILES:-}"
OMH_SETUP_ARGS="${OMH_SETUP_ARGS:-}"

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

if [ -z "$OMH_PACKAGE_URL" ]; then
  case "$OMH_CHANNEL" in
    preview)
      OMH_PACKAGE_URL="$OMH_REPO_ARCHIVE_ROOT/heads/main.zip"
      ;;
    stable)
      if [ -z "$OMH_VERSION" ]; then
        say "omh installer: OMH_CHANNEL=stable requires OMH_VERSION, for example OMH_VERSION=0.1.0."
        exit 1
      fi
      case "$OMH_VERSION" in
        v*) OMH_TAG="$OMH_VERSION" ;;
        *) OMH_TAG="v$OMH_VERSION" ;;
      esac
      OMH_PACKAGE_URL="$OMH_REPO_ARCHIVE_ROOT/tags/$OMH_TAG.zip"
      ;;
    local)
      say "omh installer: OMH_CHANNEL=local requires OMH_PACKAGE_URL to point at a local archive or path accepted by pip."
      exit 1
      ;;
    *)
      say "omh installer: unsupported OMH_CHANNEL '$OMH_CHANNEL' (expected preview, stable, or local)."
      exit 1
      ;;
  esac
fi

say "Installing oh-my-hermes-agent from $OMH_CHANNEL channel..."
"$OMH_PYTHON" -m pip install $OMH_PIP_ARGS --upgrade "$OMH_PACKAGE_URL"

set -- setup --channel "$OMH_CHANNEL" --package-url "$OMH_PACKAGE_URL"

if [ "$OMH_AUTO_APPLY" = "0" ]; then
  set -- "$@" --skip-apply
fi

if [ -n "$OMH_VERSION" ]; then
  set -- "$@" --version "$OMH_VERSION"
fi

if [ "$OMH_WITH_PLUGIN" = "1" ]; then
  set -- "$@" --with-plugin
fi

if [ -n "$OMH_PROFILE_PACKS" ]; then
  for OMH_PROFILE_PACK in $(printf '%s' "$OMH_PROFILE_PACKS" | tr ',' ' '); do
    set -- "$@" --profile-pack "$OMH_PROFILE_PACK"
  done
fi

if [ -n "$OMH_SETUP_PROFILES" ]; then
  for OMH_SETUP_PROFILE in $(printf '%s' "$OMH_SETUP_PROFILES" | tr ',' ' '); do
    set -- "$@" --profile "$OMH_SETUP_PROFILE"
  done
fi

if [ -n "$OMH_SETUP_ARGS" ]; then
  # Intentional shell splitting: this is an advanced escape hatch for operators
  # who need to pass current omh setup flags before install.sh grows a stable
  # first-class environment variable for them.
  # shellcheck disable=SC2086
  set -- "$@" $OMH_SETUP_ARGS
fi

say "Setting up managed Hermes skills..."
run_omh "$@"

if [ "$OMH_RUN_DOCTOR" = "0" ]; then
  say "Skipped doctor check because OMH_RUN_DOCTOR=0."
else
  say "Verifying installation..."
  run_omh doctor
fi

say "oh-my-hermes-agent is installed."
say "Open Hermes Agent and use the installed OMH skills. Run 'omh doctor' for health checks or 'omh setup' to reapply Hermes registration."
