#!/usr/bin/env sh
set -eu

OMH_REPO_ARCHIVE_ROOT="${OMH_REPO_ARCHIVE_ROOT:-https://github.com/rlaope/oh-my-hermes-agent/archive/refs}"
OMH_CHANNEL="${OMH_CHANNEL:-preview}"
OMH_VERSION="${OMH_VERSION:-}"
OMH_PACKAGE_URL="${OMH_PACKAGE_URL:-}"
OMH_PYTHON="${OMH_PYTHON:-python3}"
OMH_PIP_ARGS_WAS_SET="${OMH_PIP_ARGS+x}"
OMH_PIP_ARGS="${OMH_PIP_ARGS:-}"
OMH_INSTALL_MODE="${OMH_INSTALL_MODE:-venv}"
OMH_HOME_DIR="${HOME:-}"
if [ -z "${OMH_VENV_DIR+x}" ]; then
  if [ -n "${XDG_DATA_HOME:-}" ]; then
    OMH_VENV_DIR="$XDG_DATA_HOME/omh/venv"
  elif [ -n "$OMH_HOME_DIR" ]; then
    OMH_VENV_DIR="$OMH_HOME_DIR/.local/share/omh/venv"
  else
    OMH_VENV_DIR=""
  fi
fi
if [ -z "${OMH_BIN_DIR+x}" ]; then
  if [ -n "$OMH_HOME_DIR" ]; then
    OMH_BIN_DIR="$OMH_HOME_DIR/.local/bin"
  else
    OMH_BIN_DIR=""
  fi
fi
OMH_LINK_COMMAND="${OMH_LINK_COMMAND:-1}"
OMH_FORCE_LINK="${OMH_FORCE_LINK:-0}"
OMH_AUTO_APPLY="${OMH_AUTO_APPLY:-1}"
OMH_RUN_DOCTOR="${OMH_RUN_DOCTOR:-1}"
OMH_WITH_PLUGIN="${OMH_WITH_PLUGIN:-0}"
OMH_PROFILE_PACKS="${OMH_PROFILE_PACKS:-}"
OMH_SETUP_PROFILES="${OMH_SETUP_PROFILES:-}"
OMH_SETUP_ARGS="${OMH_SETUP_ARGS:-}"
OMH_RUNTIME_PYTHON="$OMH_PYTHON"
OMH_COMMAND_HINT=""

say() {
  printf '%s\n' "$*"
}

run_omh() {
  "$OMH_RUNTIME_PYTHON" -m omh.cli "$@"
}

find_omh_command() {
  if [ -n "$OMH_COMMAND_HINT" ] && [ -e "$OMH_COMMAND_HINT" ]; then
    printf '%s\n' "$OMH_COMMAND_HINT"
    return 0
  fi
  if command -v omh >/dev/null 2>&1; then
    command -v omh
    return 0
  fi
  "$OMH_RUNTIME_PYTHON" - "$OMH_BIN_DIR" "$OMH_VENV_DIR/bin" <<'PY'
import os
import shutil
import site
import sys
import sysconfig

found = shutil.which("omh")
if found:
    print(found)
    raise SystemExit(0)

names = ["omh.exe"] if os.name == "nt" else ["omh"]
schemes = [sysconfig.get_default_scheme()]
schemes.append("nt_user" if os.name == "nt" else "posix_user")

dirs = []
for directory in sys.argv[1:]:
    if directory and directory not in dirs:
        dirs.append(directory)

for scheme in schemes:
    try:
        path = sysconfig.get_path("scripts", scheme)
    except Exception:
        path = ""
    if path and path not in dirs:
        dirs.append(path)

user_base = getattr(site, "USER_BASE", "")
if user_base:
    user_bin = os.path.join(user_base, "Scripts" if os.name == "nt" else "bin")
    if user_bin not in dirs:
        dirs.append(user_bin)

for directory in dirs:
    for name in names:
        candidate = os.path.join(directory, name)
        if os.path.exists(candidate):
            print(candidate)
            raise SystemExit(0)
PY
}

link_omh_command() {
  if [ "$OMH_LINK_COMMAND" != "1" ]; then
    return 0
  fi
  if [ -z "$OMH_BIN_DIR" ]; then
    say "omh installer: OMH_BIN_DIR is not set, so no omh command link was created."
    return 0
  fi
  OMH_SOURCE_COMMAND="$OMH_VENV_DIR/bin/omh"
  if [ ! -e "$OMH_SOURCE_COMMAND" ]; then
    return 0
  fi
  mkdir -p "$OMH_BIN_DIR"
  OMH_TARGET_COMMAND="$OMH_BIN_DIR/omh"
  if [ -e "$OMH_TARGET_COMMAND" ] || [ -L "$OMH_TARGET_COMMAND" ]; then
    OMH_EXISTING_LINK="$(readlink "$OMH_TARGET_COMMAND" 2>/dev/null || true)"
    if [ "$OMH_EXISTING_LINK" = "$OMH_SOURCE_COMMAND" ]; then
      OMH_COMMAND_HINT="$OMH_TARGET_COMMAND"
      return 0
    fi
    if [ "$OMH_FORCE_LINK" = "1" ]; then
      ln -sf "$OMH_SOURCE_COMMAND" "$OMH_TARGET_COMMAND"
      OMH_COMMAND_HINT="$OMH_TARGET_COMMAND"
      return 0
    fi
    say "omh installer: $OMH_TARGET_COMMAND already exists, so it was not replaced."
    say "Set OMH_FORCE_LINK=1 to replace it, or use: $OMH_SOURCE_COMMAND"
    OMH_COMMAND_HINT="$OMH_SOURCE_COMMAND"
    return 0
  fi
  ln -s "$OMH_SOURCE_COMMAND" "$OMH_TARGET_COMMAND"
  OMH_COMMAND_HINT="$OMH_TARGET_COMMAND"
}

install_into_venv() {
  if [ -z "$OMH_VENV_DIR" ]; then
    say "omh installer: HOME or XDG_DATA_HOME is required for default venv install."
    say "Set OMH_VENV_DIR to an explicit directory and retry."
    exit 1
  fi
  say "Creating isolated Python environment at $OMH_VENV_DIR..."
  if ! "$OMH_PYTHON" -m venv "$OMH_VENV_DIR"; then
    say "omh installer: failed to create a virtual environment with '$OMH_PYTHON -m venv'."
    say "Install Python venv support or set OMH_INSTALL_MODE=python with explicit OMH_PIP_ARGS."
    exit 1
  fi
  OMH_RUNTIME_PYTHON="$OMH_VENV_DIR/bin/python"
  say "Installing OMH package..."
  # Intentional shell splitting: OMH_PIP_ARGS is an advanced operator escape hatch.
  # shellcheck disable=SC2086
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$OMH_RUNTIME_PYTHON" -m pip install --disable-pip-version-check -q --force-reinstall $OMH_PIP_ARGS --upgrade "$OMH_PACKAGE_URL"
  OMH_COMMAND_HINT="$OMH_VENV_DIR/bin/omh"
  link_omh_command
}

install_into_python() {
  OMH_DIRECT_PIP_ARGS="$OMH_PIP_ARGS"
  if [ -z "$OMH_PIP_ARGS_WAS_SET" ]; then
    OMH_DIRECT_PIP_ARGS="--user"
  fi
  say "Installing OMH package..."
  # Intentional shell splitting: OMH_DIRECT_PIP_ARGS is an advanced operator escape hatch.
  # shellcheck disable=SC2086
  PIP_DISABLE_PIP_VERSION_CHECK=1 "$OMH_PYTHON" -m pip install --disable-pip-version-check -q --force-reinstall $OMH_DIRECT_PIP_ARGS --upgrade "$OMH_PACKAGE_URL"
  OMH_RUNTIME_PYTHON="$OMH_PYTHON"
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
        say "omh installer: OMH_CHANNEL=stable requires OMH_VERSION, for example OMH_VERSION=1.0.0."
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
case "$OMH_INSTALL_MODE" in
  venv)
    install_into_venv
    ;;
  python)
    install_into_python
    ;;
  *)
    say "omh installer: unsupported OMH_INSTALL_MODE '$OMH_INSTALL_MODE' (expected venv or python)."
    exit 1
    ;;
esac

OMH_COMMAND_PATH="$(find_omh_command || true)"
if [ -n "$OMH_COMMAND_PATH" ]; then
  say "Installed omh command: $OMH_COMMAND_PATH"
  if ! command -v omh >/dev/null 2>&1; then
    OMH_COMMAND_DIR="$(dirname "$OMH_COMMAND_PATH")"
    say "omh installer: '$OMH_COMMAND_DIR' is not on PATH for this shell."
    say "Add it with: export PATH=\"$OMH_COMMAND_DIR:\$PATH\""
    say "Until then, use: $OMH_COMMAND_PATH doctor"
  fi
else
  say "omh installer: installed the package, but could not locate the omh command."
  say "Use '$OMH_RUNTIME_PYTHON -m omh.cli doctor' as a fallback and check the selected Python scripts directory."
fi

set -- setup --channel "$OMH_CHANNEL" --package-url "$OMH_PACKAGE_URL"

if [ "$OMH_CHANNEL" = "local" ] && [ -d "$OMH_PACKAGE_URL" ]; then
  set -- "$@" --source "$OMH_PACKAGE_URL"
fi

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
if command -v omh >/dev/null 2>&1; then
  say "Open Hermes Agent and use the installed OMH skills. Run 'omh doctor' for health checks or 'omh setup' to reapply Hermes registration."
elif [ -n "$OMH_COMMAND_PATH" ]; then
  say "Open Hermes Agent and use the installed OMH skills. Run '$OMH_COMMAND_PATH doctor' for health checks or add its directory to PATH."
else
  say "Open Hermes Agent and use the installed OMH skills. Run '$OMH_PYTHON -m omh.cli doctor' for health checks."
fi
