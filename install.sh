#!/usr/bin/env sh
set -eu

OMH_REPO_ARCHIVE_ROOT="${OMH_REPO_ARCHIVE_ROOT:-https://github.com/rlaope/oh-my-hermes-agent/archive/refs}"
OMH_CHANNEL="${OMH_CHANNEL:-preview}"
OMH_VERSION="${OMH_VERSION:-}"
OMH_PACKAGE_URL="${OMH_PACKAGE_URL:-}"
OMH_SOURCE_REF="${OMH_SOURCE_REF:-}"
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
OMH_WITH_MCP="${OMH_WITH_MCP:-0}"
OMH_PROFILE_PACKS="${OMH_PROFILE_PACKS:-}"
OMH_SETUP_PROFILES="${OMH_SETUP_PROFILES:-}"
OMH_DEFAULT_EXECUTOR="${OMH_DEFAULT_EXECUTOR:-}"
OMH_SCOPE="${OMH_SCOPE:-}"
OMH_SETUP_ARGS="${OMH_SETUP_ARGS:-}"
OMH_LANG_RAW="${OMH_LANG:-${OMH_LANGUAGE:-}}"
OMH_LANG_WAS_SET=0
if [ -n "$OMH_LANG_RAW" ]; then
  OMH_LANG_WAS_SET=1
fi
OMH_RUNTIME_PYTHON="$OMH_PYTHON"
OMH_COMMAND_HINT=""

say() {
  printf '%s\n' "$*"
}

use_color() {
  [ -t 1 ] && [ -z "${NO_COLOR:-}" ]
}

color() {
  if use_color; then
    printf '\033[%sm%s\033[0m' "$1" "$2"
  else
    printf '%s' "$2"
  fi
}

say_header() {
  printf '%s\n' "$(color '1;36' "$1")"
  if [ -n "${2:-}" ]; then
    printf '%s\n' "$2"
  fi
  printf '\n'
}

say_step() {
  printf '%s %s\n' "$(color '1;36' "$1")" "$2"
}

say_ok() {
  printf '      %s %s\n' "$(color '1;32' '[ok]')" "$1"
}

say_note() {
  printf '      %s %s\n' "$(color '1;33' '[note]')" "$1"
}

say_fail() {
  printf '      %s %s\n' "$(color '1;31' '[failed]')" "$1"
}

normalize_omh_lang() {
  OMH_LANG_KEY="$(printf '%s' "$1" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz')"
  case "$OMH_LANG_KEY" in
    ""|en|eng|english)
      printf 'en'
      ;;
    ko|kr|kor|korean)
      printf 'ko'
      ;;
    ja|jp|jpn|japanese)
      printf 'ja'
      ;;
    zh|cn|zho|chi|chinese)
      printf 'zh'
      ;;
    *)
      printf 'omh installer: unsupported OMH_LANG %s (expected en, ko, ja, or zh).\n' "$1" >&2
      exit 1
      ;;
  esac
}

OMH_LANG="$(normalize_omh_lang "$OMH_LANG_RAW")"

msg() {
  case "$OMH_LANG:$1" in
    ko:installer_title) printf 'OMH 설치 관리자' ;;
    ko:installer_subtitle) printf '시스템 Python 패키지를 건드리지 않고 oh-my-hermes-agent를 설치합니다.' ;;
    ko:channel) printf '채널' ;;
    ko:mode) printf '모드' ;;
    ko:step_create_venv) printf '격리된 Python 환경 생성:' ;;
    ko:step_install_package) printf 'OMH 패키지 설치' ;;
    ko:step_install_python) printf '선택한 Python에 OMH 패키지 설치' ;;
    ko:step_expose_command) printf 'omh 명령어 연결' ;;
    ko:step_setup) printf '관리 Hermes 스킬 설정' ;;
    ko:step_doctor) printf '설치 확인' ;;
    ko:done) printf '완료' ;;
    ko:installed) printf 'oh-my-hermes-agent 설치가 완료되었습니다.' ;;
    ko:next_path) printf 'Hermes Agent를 열고 설치된 OMH 스킬을 사용하세요. 상태 확인은 '\''omh doctor'\'', 재설정은 '\''omh setup'\''을 실행하세요.' ;;
    ko:next_command_path) printf 'Hermes Agent를 열고 설치된 OMH 스킬을 사용하세요. 상태 확인은 '\''%s doctor'\''를 실행하거나 해당 디렉터리를 PATH에 추가하세요.' "$2" ;;
    ja:installer_title) printf 'OMH インストーラー' ;;
    ja:installer_subtitle) printf 'システム Python パッケージを変更せずに oh-my-hermes-agent をインストールします。' ;;
    ja:channel) printf 'チャンネル' ;;
    ja:mode) printf 'モード' ;;
    ja:step_create_venv) printf '分離された Python 環境を作成:' ;;
    ja:step_install_package) printf 'OMH パッケージをインストール' ;;
    ja:step_install_python) printf '選択した Python に OMH パッケージをインストール' ;;
    ja:step_expose_command) printf 'omh コマンドを公開' ;;
    ja:step_setup) printf '管理 Hermes スキルを設定' ;;
    ja:step_doctor) printf 'インストールを検証' ;;
    ja:done) printf '完了' ;;
    ja:installed) printf 'oh-my-hermes-agent のインストールが完了しました。' ;;
    zh:installer_title) printf 'OMH 安装器' ;;
    zh:installer_subtitle) printf '在不改动系统 Python 包的情况下安装 oh-my-hermes-agent。' ;;
    zh:channel) printf '频道' ;;
    zh:mode) printf '模式' ;;
    zh:step_create_venv) printf '创建隔离 Python 环境:' ;;
    zh:step_install_package) printf '安装 OMH 包' ;;
    zh:step_install_python) printf '将 OMH 包安装到所选 Python' ;;
    zh:step_expose_command) printf '公开 omh 命令' ;;
    zh:step_setup) printf '设置托管 Hermes 技能' ;;
    zh:step_doctor) printf '验证安装' ;;
    zh:done) printf '完成' ;;
    zh:installed) printf 'oh-my-hermes-agent 已安装。' ;;
    *)
      case "$1" in
        installer_title) printf 'OMH installer' ;;
        installer_subtitle) printf 'Install oh-my-hermes-agent without touching system Python packages.' ;;
        channel) printf 'Channel' ;;
        mode) printf 'Mode' ;;
        step_create_venv) printf 'Create isolated Python environment at' ;;
        step_install_package) printf 'Install OMH package' ;;
        step_install_python) printf 'Install OMH package into selected Python' ;;
        step_expose_command) printf 'Expose the omh command' ;;
        step_setup) printf 'Set up managed Hermes skills' ;;
        step_doctor) printf 'Verify installation' ;;
        done) printf 'done' ;;
        installed) printf 'oh-my-hermes-agent is installed.' ;;
        next_path) printf 'Open Hermes Agent and use the installed OMH skills. Run '\''omh doctor'\'' for health checks or '\''omh setup'\'' to reapply Hermes registration.' ;;
        next_command_path) printf 'Open Hermes Agent and use the installed OMH skills. Run '\''%s doctor'\'' for health checks or add its directory to PATH.' "$2" ;;
        *) printf '%s' "$1" ;;
      esac
      ;;
  esac
}

run_step() {
  OMH_STEP_PREFIX="$1"
  OMH_STEP_LABEL="$2"
  shift 2
  say_step "$OMH_STEP_PREFIX" "$OMH_STEP_LABEL"
  if OMH_STEP_OUTPUT="$("$@" 2>&1)"; then
    say_ok "$(msg done)"
    return 0
  fi
  say_fail "$OMH_STEP_LABEL"
  if [ -n "$OMH_STEP_OUTPUT" ]; then
    printf '%s\n' "$OMH_STEP_OUTPUT" | sed 's/^/      /'
  fi
  exit 1
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
  run_step "[1/5]" "$(msg step_create_venv) $OMH_VENV_DIR" "$OMH_PYTHON" -m venv "$OMH_VENV_DIR"
  OMH_RUNTIME_PYTHON="$OMH_VENV_DIR/bin/python"
  run_step "[2/5]" "$(msg step_install_package)" sh -c '
    # Intentional shell splitting: OMH_PIP_ARGS is an advanced operator escape hatch.
    # shellcheck disable=SC2086
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$1" -m pip install --disable-pip-version-check -q --force-reinstall $2 --upgrade "$3"
  ' sh "$OMH_RUNTIME_PYTHON" "$OMH_PIP_ARGS" "$OMH_PACKAGE_URL"
  OMH_COMMAND_HINT="$OMH_VENV_DIR/bin/omh"
  link_omh_command
}

install_into_python() {
  OMH_DIRECT_PIP_ARGS="$OMH_PIP_ARGS"
  if [ -z "$OMH_PIP_ARGS_WAS_SET" ]; then
    OMH_DIRECT_PIP_ARGS="--user"
  fi
  run_step "[1/5]" "$(msg step_install_python)" sh -c '
    # Intentional shell splitting: OMH_DIRECT_PIP_ARGS is an advanced operator escape hatch.
    # shellcheck disable=SC2086
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$1" -m pip install --disable-pip-version-check -q --force-reinstall $2 --upgrade "$3"
  ' sh "$OMH_PYTHON" "$OMH_DIRECT_PIP_ARGS" "$OMH_PACKAGE_URL"
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
      if [ -z "$OMH_SOURCE_REF" ]; then
        OMH_SOURCE_REF="main"
      fi
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
      if [ -z "$OMH_SOURCE_REF" ]; then
        OMH_SOURCE_REF="$OMH_TAG"
      fi
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
elif [ -z "$OMH_SOURCE_REF" ]; then
  case "$OMH_CHANNEL" in
    local) OMH_SOURCE_REF="local" ;;
    stable)
      if [ -n "$OMH_VERSION" ]; then
        case "$OMH_VERSION" in
          v*) OMH_SOURCE_REF="$OMH_VERSION" ;;
          *) OMH_SOURCE_REF="v$OMH_VERSION" ;;
        esac
      else
        OMH_SOURCE_REF="custom-url"
      fi
      ;;
    preview) OMH_SOURCE_REF="main" ;;
    *) OMH_SOURCE_REF="custom-url" ;;
  esac
fi

say_header "$(msg installer_title)" "$(msg installer_subtitle)"
say_note "$(msg channel): $OMH_CHANNEL"
say_note "Source ref: $OMH_SOURCE_REF"
say_note "$(msg mode): $OMH_INSTALL_MODE"
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
  say_step "[3/5]" "$(msg step_expose_command)"
  say_ok "$OMH_COMMAND_PATH"
  if ! command -v omh >/dev/null 2>&1; then
    OMH_COMMAND_DIR="$(dirname "$OMH_COMMAND_PATH")"
    say_note "'$OMH_COMMAND_DIR' is not on PATH for this shell."
    say_note "Add it with: export PATH=\"$OMH_COMMAND_DIR:\$PATH\""
    say_note "Until then, use: $OMH_COMMAND_PATH doctor"
  fi
else
  say "omh installer: installed the package, but could not locate the omh command."
  say "Use '$OMH_RUNTIME_PYTHON -m omh.cli doctor' as a fallback and check the selected Python scripts directory."
fi

set -- setup --channel "$OMH_CHANNEL" --package-url "$OMH_PACKAGE_URL" --source-ref "$OMH_SOURCE_REF" --command-package-updated

if [ "$OMH_LANG_WAS_SET" = "1" ]; then
  set -- "$@" --language "$OMH_LANG"
fi

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

if [ "$OMH_WITH_MCP" = "1" ]; then
  set -- "$@" --with-mcp
fi

if [ -n "$OMH_SCOPE" ]; then
  set -- "$@" --scope "$OMH_SCOPE"
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

if [ -n "$OMH_DEFAULT_EXECUTOR" ]; then
  set -- "$@" --default-executor "$OMH_DEFAULT_EXECUTOR"
fi

if [ -n "$OMH_SETUP_ARGS" ]; then
  # Intentional shell splitting: this is an advanced escape hatch for operators
  # who need to pass current omh setup flags before install.sh grows a stable
  # first-class environment variable for them.
  # shellcheck disable=SC2086
  set -- "$@" $OMH_SETUP_ARGS
fi

say_step "[4/5]" "$(msg step_setup)"
run_omh "$@"

if [ "$OMH_RUN_DOCTOR" = "0" ]; then
  say_note "Skipped doctor check because OMH_RUN_DOCTOR=0."
else
  say_step "[5/5]" "$(msg step_doctor)"
  if [ -n "$OMH_SCOPE" ]; then
    run_omh --scope "$OMH_SCOPE" doctor
  else
    run_omh doctor
  fi
fi

printf '\n'
say "$(color '1;36' "$(msg installed)")"
if command -v omh >/dev/null 2>&1; then
  say "$(msg next_path)"
elif [ -n "$OMH_COMMAND_PATH" ]; then
  say "$(msg next_command_path "$OMH_COMMAND_PATH")"
else
  say "Open Hermes Agent and use the installed OMH skills. Run '$OMH_PYTHON -m omh.cli doctor' for health checks."
fi
