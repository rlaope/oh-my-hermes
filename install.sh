#!/usr/bin/env sh
set -eu

OMH_REPO_ARCHIVE_ROOT="${OMH_REPO_ARCHIVE_ROOT:-https://github.com/rlaope/oh-my-hermes/archive/refs}"
OMH_REPO_ASSET_ROOT="${OMH_REPO_ASSET_ROOT:-https://github.com/rlaope/oh-my-hermes/releases/download}"
OMH_REPO_LATEST_URL="${OMH_REPO_LATEST_URL:-https://github.com/rlaope/oh-my-hermes/releases/latest}"
# Stable installs the ~2.7 MB release wheel; preview installs the ~44 MB branch
# archive, which GitHub generates per request rather than serving from a CDN.
# Defaulting to the newest release is the contract every package manager
# honours; preview stays available for tracking main.
OMH_CHANNEL="${OMH_CHANNEL:-stable}"
OMH_VERSION="${OMH_VERSION:-}"
OMH_PACKAGE_URL="${OMH_PACKAGE_URL:-}"
OMH_SOURCE_REF="${OMH_SOURCE_REF:-}"
OMH_PYTHON_WAS_SET="${OMH_PYTHON:+x}"
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
OMH_RUN_SETUP="${OMH_RUN_SETUP:-0}"
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
# `sh -s -- omher@beta` opts into the desktop path: Hermes when it is missing
# (its official installer, non-interactive), OMH, `omh setup` when this machine
# had no OMH or no Hermes, then the omher desktop app. With no argument this
# installer does exactly what it did before the argument existed.
OMH_WITH_HERMES="${OMH_WITH_HERMES:-1}"
OMH_WITH_DESKTOP="${OMH_WITH_DESKTOP:-1}"
OMH_APP_DIR="${OMH_APP_DIR:-}"
OMH_OMHER_BETA=0
# `sh -s -- --uninstall [--purge] [--dry-run]` removes OMH instead of installing
# it: it finds the installed command and runs `omh uninstall`, and never
# downloads or installs anything. --purge and --dry-run only mean something with
# --uninstall.
OMH_UNINSTALL=0
OMH_UNINSTALL_PURGE=0
OMH_UNINSTALL_DRY_RUN=0
omh_usage() {
  printf 'omh installer: %s\n' "$1" >&2
  printf 'Usage:\n' >&2
  printf '  install   curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh\n' >&2
  printf '  desktop   curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- omher@beta\n' >&2
  printf '  remove    curl -fsSL https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh | sh -s -- --uninstall [--purge] [--dry-run]\n' >&2
  exit 2
}
for omh_arg in "$@"; do
  case "$omh_arg" in
    omher@beta) OMH_OMHER_BETA=1 ;;
    --uninstall) OMH_UNINSTALL=1 ;;
    --purge) OMH_UNINSTALL_PURGE=1 ;;
    --dry-run) OMH_UNINSTALL_DRY_RUN=1 ;;
    *)
      omh_usage "unknown argument '$omh_arg'. The arguments are omher@beta (adds Hermes when missing, and the omher desktop app) and --uninstall [--purge] [--dry-run] (removes OMH)."
      ;;
  esac
done
if [ "$OMH_UNINSTALL" = "1" ] && [ "$OMH_OMHER_BETA" = "1" ]; then
  omh_usage "--uninstall cannot be combined with omher@beta."
fi
if [ "$OMH_UNINSTALL" = "0" ] && [ "$OMH_UNINSTALL_PURGE" = "1" ]; then
  omh_usage "--purge only works together with --uninstall."
fi
if [ "$OMH_UNINSTALL" = "0" ] && [ "$OMH_UNINSTALL_DRY_RUN" = "1" ]; then
  omh_usage "--dry-run only works together with --uninstall."
fi
OMH_HERMES_INSTALL_URL="https://hermes-agent.nousresearch.com/install.sh"
OMH_OMHER_RELEASES_URL="https://api.github.com/repos/rlaope/oh-my-hermes/releases?per_page=10"
OMH_OMHER_RELEASE_PAGES=5
OMH_OMHER_SITE_URL="https://omher.app/"
# The 512 px app icon for the Linux app menu entry (the same image the app bundles).
OMH_OMHER_ICON_URL="https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/apps/omher/src-tauri/icons/icon.png"

# Hermes runs a profile with HERMES_HOME=<root>/profiles/<name>, and its venv
# lives under <root>. A home whose parent is `profiles` and whose root holds its
# own config.yaml resolves to that root, the rule the omher bridge uses
# (hermes_root_of). Without it a profile shell looked for Hermes inside the
# profile folder and installed a second Hermes there.
hermes_root_of() {
  omh_root_home="${1%/}"
  omh_root_parent="${omh_root_home%/*}"
  case "$omh_root_parent" in
    */profiles)
      omh_root_dir="${omh_root_parent%/profiles}"
      if [ -n "$omh_root_dir" ] && [ -f "$omh_root_dir/config.yaml" ]; then
        printf '%s\n' "$omh_root_dir"
        return 0
      fi
      ;;
  esac
  printf '%s\n' "$1"
}

OMH_HERMES_DIR="${HERMES_HOME:-}"
if [ -n "$OMH_HERMES_DIR" ]; then
  OMH_HERMES_DIR="$(hermes_root_of "$OMH_HERMES_DIR")"
elif [ -n "$OMH_HOME_DIR" ]; then
  OMH_HERMES_DIR="$OMH_HOME_DIR/.hermes"
fi

# Hermes' own Python, where Hermes' installer puts it. The same places the
# omher app looks (apps/omher/src-tauri/src/bridge.rs).
hermes_python() {
  [ -n "$OMH_HERMES_DIR" ] || return 1
  for omh_hermes_venv in venv .venv; do
    if [ -x "$OMH_HERMES_DIR/hermes-agent/$omh_hermes_venv/bin/python" ]; then
      printf '%s\n' "$OMH_HERMES_DIR/hermes-agent/$omh_hermes_venv/bin/python"
      return 0
    fi
  done
  return 1
}

hermes_present() {
  command -v hermes >/dev/null 2>&1 || hermes_python >/dev/null
}

omh_present() {
  if [ -n "$OMH_VENV_DIR" ] && [ -x "$OMH_VENV_DIR/bin/omh" ]; then
    return 0
  fi
  command -v omh >/dev/null 2>&1
}

OMH_HAD_OMH=0
OMH_HAD_HERMES=0
OMH_INSTALL_HERMES=0
OMH_OMHER_APP_PATH=""
if [ "$OMH_OMHER_BETA" = "1" ]; then
  if omh_present; then
    OMH_HAD_OMH=1
  fi
  if hermes_present; then
    OMH_HAD_HERMES=1
  elif [ "$OMH_WITH_HERMES" != "0" ]; then
    OMH_INSTALL_HERMES=1
  fi
  # Connect OMH to Hermes when either side is new here. An existing OMH on an
  # existing Hermes is only upgraded, the way a plain install upgrades it.
  if [ "$OMH_HAD_OMH" = "0" ] || [ "$OMH_INSTALL_HERMES" = "1" ]; then
    if [ "$OMH_HAD_HERMES" = "1" ] || [ "$OMH_INSTALL_HERMES" = "1" ]; then
      OMH_RUN_SETUP=1
    fi
  fi
fi

OMH_RUNTIME_PYTHON="$OMH_PYTHON"
OMH_COMMAND_HINT=""
OMH_INSTALL_STEP_COUNT=2
if [ "$OMH_INSTALL_MODE" = "python" ]; then
  OMH_INSTALL_STEP_COUNT=1
fi
OMH_EXPOSE_STEP=$((OMH_INSTALL_STEP_COUNT + 1))
OMH_SETUP_STEP=$((OMH_EXPOSE_STEP + 1))
OMH_DOCTOR_STEP=$((OMH_SETUP_STEP + 1))
OMH_TOTAL_STEPS=$OMH_EXPOSE_STEP
if [ "$OMH_RUN_SETUP" = "1" ]; then
  OMH_TOTAL_STEPS=$OMH_DOCTOR_STEP
fi

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

step_label() {
  printf '[%s/%s]' "$1" "$OMH_TOTAL_STEPS"
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
    ko:installer_subtitle) printf '시스템 Python 패키지를 건드리지 않고 oh-my-hermes를 설치합니다.' ;;
    ko:channel) printf '채널' ;;
    ko:mode) printf '모드' ;;
    ko:step_create_venv) printf '격리된 Python 환경 생성:' ;;
    ko:step_install_package) printf 'OMH 패키지 설치' ;;
    ko:step_install_python) printf '선택한 Python에 OMH 패키지 설치' ;;
    ko:step_expose_command) printf 'omh 명령어 연결' ;;
    ko:step_setup) printf '관리 Hermes 스킬 설정(명시적 선택)' ;;
    ko:step_doctor) printf '설치 확인' ;;
    ko:done) printf '완료' ;;
    ko:installed) printf 'oh-my-hermes 설치가 완료되었습니다.' ;;
    ko:next_path) printf '다음: '\''omh setup'\''으로 Hermes에 연결한 뒤, '\''omh doctor'\''로 확인하세요.' ;;
    ko:next_command_path) printf '다음: '\''%s setup'\''으로 Hermes에 연결한 뒤, '\''%s doctor'\''로 확인하세요. 또는 해당 디렉터리를 PATH에 추가하세요.' "$2" "$2" ;;
    ko:uninstall_not_found) printf 'omh installer: 설치된 omh 명령어를 찾지 못해 아무것도 제거하지 않았습니다. 찾아본 곳: %s' "$2" ;;
    ko:uninstall_left_over) printf 'OMH 홈과 Hermes 등록이 남아 있을 수 있습니다. 수동 제거 방법: docs/INSTALLATION.md#uninstall (https://github.com/rlaope/oh-my-hermes/blob/main/docs/INSTALLATION.md#uninstall)' ;;
    ja:installer_title) printf 'OMH インストーラー' ;;
    ja:installer_subtitle) printf 'システム Python パッケージを変更せずに oh-my-hermes をインストールします。' ;;
    ja:channel) printf 'チャンネル' ;;
    ja:mode) printf 'モード' ;;
    ja:step_create_venv) printf '分離された Python 環境を作成:' ;;
    ja:step_install_package) printf 'OMH パッケージをインストール' ;;
    ja:step_install_python) printf '選択した Python に OMH パッケージをインストール' ;;
    ja:step_expose_command) printf 'omh コマンドを公開' ;;
    ja:step_setup) printf '管理 Hermes スキルを設定（明示的に選択）' ;;
    ja:step_doctor) printf 'インストールを検証' ;;
    ja:done) printf '完了' ;;
    ja:installed) printf 'oh-my-hermes のインストールが完了しました。' ;;
    ja:next_path) printf '次に '\''omh setup'\'' で Hermes に接続し、'\''omh doctor'\'' で確認してください。' ;;
    ja:next_command_path) printf '次に '\''%s setup'\'' で Hermes に接続し、'\''%s doctor'\'' で確認してください。または、そのディレクトリを PATH に追加してください。' "$2" "$2" ;;
    ja:uninstall_not_found) printf 'omh installer: インストール済みの omh コマンドが見つからないため、何も削除していません。確認した場所: %s' "$2" ;;
    ja:uninstall_left_over) printf 'OMH ホームと Hermes の登録が残っている可能性があります。手動での削除手順: docs/INSTALLATION.md#uninstall (https://github.com/rlaope/oh-my-hermes/blob/main/docs/INSTALLATION.md#uninstall)' ;;
    zh:installer_title) printf 'OMH 安装器' ;;
    zh:installer_subtitle) printf '在不改动系统 Python 包的情况下安装 oh-my-hermes。' ;;
    zh:channel) printf '频道' ;;
    zh:mode) printf '模式' ;;
    zh:step_create_venv) printf '创建隔离 Python 环境:' ;;
    zh:step_install_package) printf '安装 OMH 包' ;;
    zh:step_install_python) printf '将 OMH 包安装到所选 Python' ;;
    zh:step_expose_command) printf '公开 omh 命令' ;;
    zh:step_setup) printf '设置托管 Hermes 技能（显式选择）' ;;
    zh:step_doctor) printf '验证安装' ;;
    zh:done) printf '完成' ;;
    zh:installed) printf 'oh-my-hermes 已安装。' ;;
    zh:next_path) printf '下一步：运行 '\''omh setup'\'' 连接 Hermes，然后运行 '\''omh doctor'\'' 验证。' ;;
    zh:next_command_path) printf '下一步：运行 '\''%s setup'\'' 连接 Hermes，然后运行 '\''%s doctor'\'' 验证；也可以把该目录加入 PATH。' "$2" "$2" ;;
    zh:uninstall_not_found) printf 'omh installer: 未找到已安装的 omh 命令，因此没有删除任何内容。已查找: %s' "$2" ;;
    zh:uninstall_left_over) printf 'OMH 主目录和 Hermes 注册可能仍然保留。手动卸载步骤: docs/INSTALLATION.md#uninstall (https://github.com/rlaope/oh-my-hermes/blob/main/docs/INSTALLATION.md#uninstall)' ;;
    *)
      case "$1" in
        uninstall_not_found) printf 'omh installer: no installed omh command was found, so nothing was removed. Looked in: %s' "$2" ;;
        uninstall_left_over) printf 'The OMH home and the Hermes registration may still be there. Manual steps: docs/INSTALLATION.md#uninstall (https://github.com/rlaope/oh-my-hermes/blob/main/docs/INSTALLATION.md#uninstall)' ;;
        installer_title) printf 'OMH installer' ;;
        installer_subtitle) printf 'Install oh-my-hermes without touching system Python packages.' ;;
        channel) printf 'Channel' ;;
        mode) printf 'Mode' ;;
        step_create_venv) printf 'Create isolated Python environment at' ;;
        step_install_package) printf 'Install OMH package' ;;
        step_install_python) printf 'Install OMH package into selected Python' ;;
        step_expose_command) printf 'Expose the omh command' ;;
        step_setup) printf 'Set up managed Hermes skills (explicit opt-in)' ;;
        step_doctor) printf 'Verify installation' ;;
        done) printf 'done' ;;
        installed) printf 'oh-my-hermes is installed.' ;;
        next_path) printf 'Next: run '\''omh setup'\'' to connect OMH to Hermes, then '\''omh doctor'\'' to verify.' ;;
        next_command_path) printf 'Next: run '\''%s setup'\'' to connect OMH to Hermes, then '\''%s doctor'\'' to verify, or add its directory to PATH.' "$2" "$2" ;;
        *) printf '%s' "$1" ;;
      esac
      ;;
  esac
}

# --uninstall: hand over to `omh uninstall`, which owns every removal rule. This
# runs before any step that downloads, builds a venv or picks a Python, so a
# removal never installs anything. It finds the command without relying on PATH
# alone: PATH, then where this installer puts it (OMH_BIN_DIR, the active
# generation's venv under the managed root, the installer's own venv).
omh_uninstall_probe() {
  [ -n "$1" ] || return 1
  OMH_UNINSTALL_PLACES="${OMH_UNINSTALL_PLACES:+$OMH_UNINSTALL_PLACES, }$1"
  if [ -f "$1" ] && [ -x "$1" ]; then
    OMH_UNINSTALL_COMMAND="$1"
    return 0
  fi
  return 1
}

find_omh_for_uninstall() {
  OMH_UNINSTALL_COMMAND=""
  OMH_UNINSTALL_PLACES="PATH"
  omh_on_path="$(command -v omh 2>/dev/null || true)"
  case "$omh_on_path" in
    /*) if [ -x "$omh_on_path" ]; then OMH_UNINSTALL_COMMAND="$omh_on_path"; return 0; fi ;;
  esac
  if [ -n "$OMH_BIN_DIR" ] && omh_uninstall_probe "$OMH_BIN_DIR/omh"; then return 0; fi
  if [ -n "${XDG_DATA_HOME:-}" ]; then
    omh_managed_root="$XDG_DATA_HOME/omh"
  elif [ -n "$OMH_HOME_DIR" ]; then
    omh_managed_root="$OMH_HOME_DIR/.local/share/omh"
  else
    omh_managed_root=""
  fi
  if [ -n "$omh_managed_root" ] && omh_uninstall_probe "$omh_managed_root/current/venv/bin/omh"; then return 0; fi
  if [ -n "$OMH_VENV_DIR" ] && omh_uninstall_probe "$OMH_VENV_DIR/bin/omh"; then return 0; fi
  return 1
}

run_uninstall() {
  if ! find_omh_for_uninstall; then
    printf '%s\n' "$(msg uninstall_not_found "$OMH_UNINSTALL_PLACES")" >&2
    printf '%s\n' "$(msg uninstall_left_over)" >&2
    exit 1
  fi
  set -- uninstall
  if [ "$OMH_UNINSTALL_PURGE" = "1" ]; then
    set -- "$@" --all
  fi
  if [ "$OMH_UNINSTALL_DRY_RUN" = "1" ]; then
    set -- "$@" --dry-run
  fi
  if [ "$OMH_LANG_WAS_SET" = "1" ]; then
    set -- "$@" --language "$OMH_LANG"
  fi
  if "$OMH_UNINSTALL_COMMAND" "$@"; then
    exit 0
  else
    exit "$?"
  fi
}

if [ "$OMH_UNINSTALL" = "1" ]; then
  run_uninstall
fi

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
  # Keep user-site packages visible for python mode, but ignore cwd/PYTHONPATH.
  "$OMH_RUNTIME_PYTHON" -P -E -m omh.cli "$@"
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
  "$OMH_RUNTIME_PYTHON" -I - "$OMH_BIN_DIR" "$OMH_VENV_DIR/bin" <<'PY'
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
  # -Im combines isolated mode and module execution in one Python option.
  run_step "$(step_label 1)" "$(msg step_create_venv) $OMH_VENV_DIR" "$OMH_PYTHON" -Im venv "$OMH_VENV_DIR"
  OMH_RUNTIME_PYTHON="$OMH_VENV_DIR/bin/python"
  run_step "$(step_label 2)" "$(msg step_install_package)" sh -c '
    # Intentional shell splitting: OMH_PIP_ARGS is an advanced operator escape hatch.
    # shellcheck disable=SC2086
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$1" -I -m pip install --disable-pip-version-check -q --no-cache-dir --force-reinstall $2 --upgrade "$3"
  ' sh "$OMH_RUNTIME_PYTHON" "$OMH_PIP_ARGS" "$OMH_PACKAGE_URL"
  OMH_COMMAND_HINT="$OMH_VENV_DIR/bin/omh"
  link_omh_command
}

install_into_python() {
  OMH_DIRECT_PIP_ARGS="$OMH_PIP_ARGS"
  if [ -z "$OMH_PIP_ARGS_WAS_SET" ]; then
    OMH_DIRECT_PIP_ARGS="--user"
  fi
  run_step "$(step_label 1)" "$(msg step_install_python)" sh -c '
    # -I disables the user site and breaks pip --user; -P -E excludes cwd/PYTHONPATH.
    # Intentional shell splitting: OMH_DIRECT_PIP_ARGS is an advanced operator escape hatch.
    # shellcheck disable=SC2086
    PIP_DISABLE_PIP_VERSION_CHECK=1 "$1" -P -E -m pip install --disable-pip-version-check -q --no-cache-dir --force-reinstall $2 --upgrade "$3"
  ' sh "$OMH_PYTHON" "$OMH_DIRECT_PIP_ARGS" "$OMH_PACKAGE_URL"
  OMH_RUNTIME_PYTHON="$OMH_PYTHON"
}

# The floor the wheel itself declares (`requires-python` in pyproject.toml).
# Raising one without the other turns a refusal a person can act on into a pip
# error several steps later.
OMH_MIN_PYTHON_MINOR=11
# What `uv python install` is asked for when it is the last resort. A concrete
# version rather than a range: uv resolves a range against what it already has,
# and the point of reaching here is that nothing on this machine qualifies.
OMH_UV_PYTHON_VERSION=3.12
# Declines the interpreter download; any other value leaves it available.
OMH_PROVISION_PYTHON="${OMH_PROVISION_PYTHON:-1}"
# Set when provisioning ran and still did not produce an interpreter, so the
# refusal can say that instead of repeating "none was found".
OMH_PROVISION_TRIED=0
OMH_INSTALL_SCRIPT_URL="https://raw.githubusercontent.com/rlaope/oh-my-hermes/main/install.sh"

python_two_part_version() {
  # Anchored on a whole line, because this is matched against arbitrary
  # interpreter output and a wrapper that prints a banner first would
  # otherwise satisfy it. `-I` keeps a stray PYTHONPATH or a user
  # site-packages out of the answer. A candidate that is not installed, or is
  # the Microsoft Store stub, prints nothing and is rejected by the emptiness.
  "$1" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null |
    awk '
      NR == 1 && /^[0-9]+\.[0-9]+$/ { version = $0 }
      END { if (NR == 1 && version != "") print version }'
}

python_version_supported() {
  [ -n "$1" ] || return 1
  printf '%s' "$1" | awk -F. -v minor="$OMH_MIN_PYTHON_MINOR" '
    { exit !($1 > 3 || ($1 == 3 && $2 >= minor)) }'
}

python_candidates() {
  # An interpreter the operator named is the only candidate. Quietly using a
  # different one would be the installer overruling a choice, and the reason
  # OMH_PYTHON exists is that the person knows something the search does not.
  if [ -n "$OMH_PYTHON_WAS_SET" ]; then
    printf '%s\n' "$OMH_PYTHON"
    return 0
  fi
  # The machine's own python3 first, then versioned commands newest-first:
  # the same order packaging/npm/lib/python.js probes, so the curl installer
  # and the npm launcher land on the same interpreter on one machine.
  printf '%s\n' python3 python3.14 python3.13 python3.12 python3.11 python
  # Interpreters a person installed and did not put first on PATH. This is the
  # case that produced the report: on macOS /usr/bin/python3 is 3.9 and stays
  # ahead of everything, while the Homebrew or python.org build is one
  # directory away. Order among these is not a preference -- every interpreter
  # that passes the probe runs OMH equally well -- so they are only places to
  # look, and the probe decides.
  for omh_python_candidate in \
    /opt/homebrew/bin/python3.[0-9] \
    /opt/homebrew/bin/python3.[0-9][0-9] \
    /usr/local/bin/python3.[0-9] \
    /usr/local/bin/python3.[0-9][0-9] \
    /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
    "$OMH_HOME_DIR"/.pyenv/versions/*/bin/python3 \
    "$OMH_HOME_DIR"/.local/share/uv/python/*/bin/python3
  do
    if [ -x "$omh_python_candidate" ]; then
      printf '%s\n' "$omh_python_candidate"
    fi
  done
  # uv's own interpreters, asked for BY PATH rather than located by layout.
  # The glob above covers uv's default directory only, and
  # `UV_PYTHON_INSTALL_DIR` or `XDG_DATA_HOME` moves it -- on such a machine a
  # perfectly good interpreter sits one directory away and the search reports
  # none. This listing is cwd-independent and prints `<key><spaces><path>`;
  # the key never contains a space, so everything past the first run of
  # whitespace is the path, which may. `uv python find` is deliberately NOT
  # used: it resolves a PROJECT environment first and is cwd-dependent, and
  # `curl ... | sh` runs wherever the person is standing, so from a checkout
  # it answers that checkout's `.venv` -- which passes the version probe and
  # would become the BASE of OMH's environment. `--managed-python` does not
  # prevent that either; measured on uv 0.12.5.
  if command -v uv >/dev/null 2>&1; then
    uv python list --managed-python --only-installed 2>/dev/null |
      sed -n 's/^[^[:space:]][^[:space:]]*[[:space:]][[:space:]]*//p'
  fi
  # omher@beta only: Hermes' own interpreter, last. On a machine that had no
  # Python 3.11+ until Hermes' installer brought one, it is the only candidate.
  if [ "$OMH_OMHER_BETA" = "1" ]; then
    hermes_python || true
  fi
}

select_python() {
  python_candidates | while IFS= read -r omh_python_candidate; do
    if python_version_supported "$(python_two_part_version "$omh_python_candidate")"; then
      printf '%s\n' "$omh_python_candidate"
      break
    fi
  done
}

report_rejected_pythons() {
  # Only interpreters that exist and answered. A candidate name that is not
  # installed at all is not a finding, and listing it would bury the one line
  # that explains the refusal.
  python_candidates | while IFS= read -r omh_python_candidate; do
    omh_python_version="$(python_two_part_version "$omh_python_candidate")"
    if [ -n "$omh_python_version" ]; then
      say "  $omh_python_candidate is Python $omh_python_version"
    fi
  done
}


resolve_python() {
  # Runs after the header so its one long case -- provisioning an
  # interpreter -- is announced under the same banner as every other step,
  # and so the refusal is the last thing on screen when there is one.
  OMH_SELECTED_PYTHON="$(select_python)"

  # Last resort, and only when the alternative is failing: uv is the person's own
  # tool and it installs a private interpreter under their data directory. It is
  # still a download of a language runtime, which is a kind of side effect this
  # script has never had -- until now it fetched only OMH's own wheel -- so it
  # says what it is about to do, shows uv's own output while it does it, and
  # `OMH_PROVISION_PYTHON=0` declines it without having to name an interpreter.
  if [ -z "$OMH_SELECTED_PYTHON" ] \
    && [ -z "$OMH_PYTHON_WAS_SET" ] \
    && [ "$OMH_PROVISION_PYTHON" != "0" ] \
    && command -v uv >/dev/null 2>&1; then
    say_note "No Python 3.$OMH_MIN_PYTHON_MINOR+ was found. Asking uv, which is already on this machine, for Python $OMH_UV_PYTHON_VERSION."
    say_note "This downloads an interpreter (~66 MB). Decline with OMH_PROVISION_PYTHON=0."
    if uv python install "$OMH_UV_PYTHON_VERSION"; then
      # Deliberately NOT `uv python find`: it resolves a PROJECT environment
      # before it considers uv's own interpreters and is cwd-dependent, and
      # `curl ... | sh` runs wherever the person is standing. From a checkout
      # with a `.venv` it answers that `.venv` -- which reports a supported
      # version, passes the probe, and would become the BASE of OMH's venv,
      # leaving it pointing at an interpreter that vanishes when that project
      # is rebuilt. `--managed-python` does not reliably prevent it either:
      # measured on uv 0.12.5, both forms still answered with the project's
      # `.venv`. So the search runs again instead, and it now reads uv's
      # managed interpreters by path from `uv python list`, cwd-independently.
      OMH_SELECTED_PYTHON="$(select_python)"
      if [ -z "$OMH_SELECTED_PYTHON" ]; then
        OMH_PROVISION_TRIED=1
      fi
    else
      OMH_PROVISION_TRIED=1
    fi
  fi

  if [ -z "$OMH_SELECTED_PYTHON" ]; then
    if [ -n "$OMH_PYTHON_WAS_SET" ] && ! command -v "$OMH_PYTHON" >/dev/null 2>&1; then
      # A typo is the likeliest way this variable goes wrong, and "not a usable
      # Python 3.11+" would send the person to look at the wrong thing.
      say "omh installer: OMH_PYTHON='$OMH_PYTHON' was not found."
    elif [ -n "$OMH_PYTHON_WAS_SET" ]; then
      say "omh installer: OMH_PYTHON='$OMH_PYTHON' is not a usable Python 3.$OMH_MIN_PYTHON_MINOR+."
    elif [ "$OMH_PROVISION_TRIED" = "1" ]; then
      say "omh installer: no Python 3.$OMH_MIN_PYTHON_MINOR+ was found, and asking uv for one did not produce a usable interpreter (uv's own output is above)."
    else
      say "omh installer: no Python 3.$OMH_MIN_PYTHON_MINOR+ was found, and oh-my-hermes requires one."
    fi
    report_rejected_pythons
    say "Install one, then run this installer again:"
    case "$(uname -s 2>/dev/null || printf 'unknown')" in
      Darwin) say "  brew install python@$OMH_UV_PYTHON_VERSION   (or https://www.python.org/downloads/)" ;;
      Linux) say "  your distribution's python3.$OMH_MIN_PYTHON_MINOR+ package, or https://www.python.org/downloads/" ;;
      *) say "  https://www.python.org/downloads/" ;;
    esac
    if [ -z "$OMH_PYTHON_WAS_SET" ]; then
      say "Already have one the search did not look in? Name it:"
      say "  OMH_PYTHON=/path/to/python$OMH_UV_PYTHON_VERSION sh -c \"\$(curl -fsSL $OMH_INSTALL_SCRIPT_URL)\""
    else
      say "Or point OMH_PYTHON at a Python 3.$OMH_MIN_PYTHON_MINOR+ and run it again."
    fi
    exit 1
  fi

  OMH_PYTHON="$OMH_SELECTED_PYTHON"
  OMH_RUNTIME_PYTHON="$OMH_PYTHON"
  OMH_SELECTED_PYTHON_VERSION="$(python_two_part_version "$OMH_PYTHON")"
}


omher_beta_plan() {
  if [ "$OMH_HAD_OMH" = "1" ] && [ "$OMH_HAD_HERMES" = "1" ]; then
    say_note "omher@beta: found Hermes and OMH. Upgrading OMH, then adding the omher app."
  elif [ "$OMH_HAD_HERMES" = "1" ]; then
    say_note "omher@beta: found Hermes without OMH. Installing OMH, connecting it with 'omh setup', then adding the omher app."
  elif [ "$OMH_INSTALL_HERMES" = "1" ] && [ "$OMH_HAD_OMH" = "1" ]; then
    say_note "omher@beta: found OMH without Hermes. Installing Hermes, upgrading OMH, connecting them with 'omh setup', then adding the omher app."
  elif [ "$OMH_INSTALL_HERMES" = "1" ]; then
    say_note "omher@beta: found neither Hermes nor OMH. Installing Hermes first, then OMH, 'omh setup', and the omher app."
  else
    say_note "omher@beta: Hermes is not installed and OMH_WITH_HERMES=0 skips it. Install Hermes yourself, then run 'omh setup'."
  fi
  if [ "$OMH_WITH_DESKTOP" = "0" ]; then
    say_note "omher@beta: OMH_WITH_DESKTOP=0, so the omher app is not installed."
  fi
}

omh_temp_dir() {
  mktemp -d "${TMPDIR:-/tmp}/omh-install.XXXXXX"
}

install_hermes() {
  say_step "[hermes]" "Install Hermes Agent with its official installer (non-interactive)"
  if ! command -v curl >/dev/null 2>&1 || ! command -v bash >/dev/null 2>&1; then
    say_fail "Installing Hermes needs curl and bash. Install Hermes from https://hermes-agent.nousresearch.com/ and run this again."
    exit 1
  fi
  OMH_HERMES_TMP="$(omh_temp_dir)"
  # Downloaded first rather than piped: a failed download piped into bash is
  # an empty script that exits 0, and Hermes would be reported as installed.
  if ! curl -fsSL -o "$OMH_HERMES_TMP/install.sh" "$OMH_HERMES_INSTALL_URL"; then
    rm -rf "$OMH_HERMES_TMP"
    say_fail "Could not download $OMH_HERMES_INSTALL_URL"
    exit 1
  fi
  if ! bash "$OMH_HERMES_TMP/install.sh" --non-interactive </dev/null; then
    rm -rf "$OMH_HERMES_TMP"
    say_fail "Hermes' installer failed (its output is above)."
    exit 1
  fi
  rm -rf "$OMH_HERMES_TMP"
  if ! hermes_present; then
    say_fail "Hermes' installer finished, but no Hermes was found under $OMH_HERMES_DIR."
    exit 1
  fi
  say_ok "Hermes Agent"
}

# The download URL of the newest omher release's asset whose name ends in $1.
# Pages through /releases ten at a time (newest first) and stops at the first
# omher-v* release that has the asset, so one install normally reads one small
# page. Never /releases/latest: that is the Python package's release, and omher
# releases are published with --latest=false. GITHUB_TOKEN, when set, is sent
# through curl's config on stdin, never on the command line.
# Status: 0 found (URL printed), 1 no omher release, 2 rate limited, 3 the API
# did not answer.
omher_release_asset_url() {
  omh_asset_suffix="$1"
  omh_page=1
  while [ "$omh_page" -le "$OMH_OMHER_RELEASE_PAGES" ]; do
    omh_page_file="$OMH_OMHER_TMP/releases-$omh_page.json"
    omh_http="$(
      if [ -n "${GITHUB_TOKEN:-}" ]; then
        printf 'header = "Authorization: Bearer %s"\n' "$GITHUB_TOKEN"
      fi | curl -sS --compressed --config - -o "$omh_page_file" -w '%{http_code}' \
        -H 'Accept: application/vnd.github+json' "$OMH_OMHER_RELEASES_URL&page=$omh_page" 2>/dev/null
    )" || omh_http="000"
    case "$omh_http" in
      200) ;;
      403|429) return 2 ;;
      *) return 3 ;;
    esac
    omh_url="$(tr -d '\r' <"$omh_page_file" |
      grep -o "\"browser_download_url\": *\"https://[^\"]*/releases/download/omher-v[^\"/]*/omher-[^\"/]*-$omh_asset_suffix\"" |
      head -n 1 |
      sed 's/.*"\(https:[^"]*\)"$/\1/')" || omh_url=""
    if [ -n "$omh_url" ]; then
      printf '%s\n' "$omh_url"
      return 0
    fi
    # A short page is the last one.
    if [ "$(grep -o '"tag_name"' "$omh_page_file" | grep -c .)" -lt 10 ]; then
      return 1
    fi
    omh_page=$((omh_page + 1))
  done
  return 1
}

# The SHA-256 of $1, with whichever tool this system has.
omh_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | sed 's/[[:space:]].*//'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | sed 's/[[:space:]].*//'
  else
    return 1
  fi
}

omher_app_failed() {
  say_fail "$1"
  say_note "Hermes and OMH are installed; only the app step failed. Download omher from $OMH_OMHER_SITE_URL"
  exit 1
}

# Linux x86_64: the release's AppImage, checked against SHA256SUMS.txt, becomes
# ~/.local/bin/omher (swapped in only once the download is whole), plus a
# .desktop entry and icon so it shows in the app menu. Other Linux machines
# (arm64) get Hermes and OMH only, with a note.
install_omher_appimage() {
  case "$(uname -a 2>/dev/null)" in
    *x86_64*|*amd64*) ;;
    *)
      say_step "[omher]" "Install the omher desktop app"
      say_note "omher has no Linux build for this processor yet (x86_64 only), so Hermes and OMH are set up without it."
      return 0
      ;;
  esac
  say_step "[omher]" "Install the omher desktop app (Linux x64 AppImage)"
  OMH_OMHER_TMP="$(omh_temp_dir)"
  OMH_OMHER_LOOKUP=0
  OMH_OMHER_IMG_URL="$(omher_release_asset_url "linux-x64\\.AppImage")" || OMH_OMHER_LOOKUP=$?
  case "$OMH_OMHER_LOOKUP" in
    0) ;;
    1)
      rm -rf "$OMH_OMHER_TMP"
      say_note "No omher release for Linux was found on GitHub yet."
      say_note "Hermes and OMH are installed. Get the app from $OMH_OMHER_SITE_URL when it is out."
      return 0
      ;;
    2)
      rm -rf "$OMH_OMHER_TMP"
      omher_app_failed "GitHub's API rate limit was reached (60 requests an hour per network without a token). Wait an hour, or set GITHUB_TOKEN, and run this again."
      ;;
    *)
      rm -rf "$OMH_OMHER_TMP"
      omher_app_failed "GitHub's API did not answer, so the omher release could not be looked up."
      ;;
  esac
  say_note "omher AppImage: $OMH_OMHER_IMG_URL"
  if ! curl -fsSL -o "$OMH_OMHER_TMP/omher.AppImage" "$OMH_OMHER_IMG_URL"; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not download $OMH_OMHER_IMG_URL"
  fi
  OMH_OMHER_SUMS_URL="${OMH_OMHER_IMG_URL%/*}/SHA256SUMS.txt"
  if ! curl -fsSL -o "$OMH_OMHER_TMP/SHA256SUMS.txt" "$OMH_OMHER_SUMS_URL"; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not download $OMH_OMHER_SUMS_URL to check the AppImage."
  fi
  OMH_OMHER_IMG_NAME="${OMH_OMHER_IMG_URL##*/}"
  OMH_OMHER_WANT="$(tr -d '\r' <"$OMH_OMHER_TMP/SHA256SUMS.txt" |
    awk -v name="$OMH_OMHER_IMG_NAME" '$2 == name || $2 == "*" name { print $1; exit }')"
  OMH_OMHER_GOT="$(omh_sha256 "$OMH_OMHER_TMP/omher.AppImage")" || OMH_OMHER_GOT=""
  if [ -z "$OMH_OMHER_WANT" ] || [ -z "$OMH_OMHER_GOT" ] || [ "$OMH_OMHER_WANT" != "$OMH_OMHER_GOT" ]; then
    rm -rf "$OMH_OMHER_TMP"
    [ -n "$OMH_OMHER_WANT" ] || OMH_OMHER_WANT="no entry for $OMH_OMHER_IMG_NAME"
    [ -n "$OMH_OMHER_GOT" ] || OMH_OMHER_GOT="no checksum tool"
    omher_app_failed "The downloaded AppImage does not match SHA256SUMS.txt (expected $OMH_OMHER_WANT, got $OMH_OMHER_GOT)."
  fi
  say_ok "SHA-256 matches SHA256SUMS.txt ($OMH_OMHER_IMG_NAME)"
  if [ -n "$OMH_APP_DIR" ]; then
    OMH_OMHER_DEST="$OMH_APP_DIR"
  else
    OMH_OMHER_DEST="$OMH_HOME_DIR/.local/bin"
  fi
  if ! mkdir -p "$OMH_OMHER_DEST"; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not create $OMH_OMHER_DEST."
  fi
  # Copied next to the target under a hidden name, made executable, then
  # renamed over it: a failed copy leaves an existing omher as it was, and a
  # running omher keeps its old file until it quits.
  OMH_OMHER_NEW="$OMH_OMHER_DEST/.omher.new.$$"
  rm -f "$OMH_OMHER_NEW"
  if ! cp "$OMH_OMHER_TMP/omher.AppImage" "$OMH_OMHER_NEW" || ! chmod 755 "$OMH_OMHER_NEW"; then
    rm -f "$OMH_OMHER_NEW"
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not copy the AppImage into $OMH_OMHER_DEST."
  fi
  rm -rf "$OMH_OMHER_TMP"
  if [ -e "$OMH_OMHER_DEST/omher" ]; then
    say_note "Replacing the omher that was already in $OMH_OMHER_DEST."
  fi
  if ! mv -f "$OMH_OMHER_NEW" "$OMH_OMHER_DEST/omher"; then
    rm -f "$OMH_OMHER_NEW"
    omher_app_failed "Could not move the new AppImage into $OMH_OMHER_DEST/omher."
  fi
  OMH_OMHER_APP_PATH="$OMH_OMHER_DEST/omher"
  say_ok "$OMH_OMHER_APP_PATH"
  # The app menu entry. The icon is the site's (the app's own icon, 512 px);
  # a failed icon download only leaves the entry with a generic icon.
  OMH_OMHER_DATA="${XDG_DATA_HOME:-$OMH_HOME_DIR/.local/share}"
  OMH_OMHER_ICON_DIR="$OMH_OMHER_DATA/icons/hicolor/512x512/apps"
  OMH_OMHER_DESKTOP_DIR="$OMH_OMHER_DATA/applications"
  if mkdir -p "$OMH_OMHER_DESKTOP_DIR" "$OMH_OMHER_ICON_DIR"; then
    curl -fsSL -o "$OMH_OMHER_ICON_DIR/omher.png" "$OMH_OMHER_ICON_URL" 2>/dev/null || rm -f "$OMH_OMHER_ICON_DIR/omher.png"
    {
      printf '[Desktop Entry]\n'
      printf 'Type=Application\n'
      printf 'Name=omher\n'
      printf 'Comment=Your Hermes bots in one window\n'
      printf 'Exec="%s" %%U\n' "$OMH_OMHER_APP_PATH"
      printf 'Icon=omher\n'
      printf 'Terminal=false\n'
      printf 'Categories=Office;Utility;\n'
      printf 'StartupWMClass=omher\n'
    } >"$OMH_OMHER_DESKTOP_DIR/omher.desktop" && say_ok "$OMH_OMHER_DESKTOP_DIR/omher.desktop"
    if command -v update-desktop-database >/dev/null 2>&1; then
      update-desktop-database "$OMH_OMHER_DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
  else
    say_note "Could not create $OMH_OMHER_DESKTOP_DIR; omher works, it just has no app menu entry."
  fi
}

install_omher_app() {
  case "$(uname -s 2>/dev/null || printf 'unknown')" in
    Darwin) ;;
    Linux)
      install_omher_appimage
      return $?
      ;;
    *)
      say_step "[omher]" "Install the omher desktop app"
      say_note "omher has no build for $(uname -s 2>/dev/null || printf 'this system') yet (macOS, Windows and Linux x86_64 only), so Hermes and OMH are set up without it."
      return 0
      ;;
  esac
  OMH_OMHER_ARCH="x64"
  # `uname -a` rather than the machine flag alone: the installer's isolation
  # test reads every `-m` as a Python module flag. sysctl catches a shell that
  # runs under Rosetta on Apple Silicon, where uname reports x86_64.
  case "$(uname -a 2>/dev/null)" in
    *arm64*) OMH_OMHER_ARCH="arm64" ;;
  esac
  if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
    OMH_OMHER_ARCH="arm64"
  fi
  say_step "[omher]" "Install the omher desktop app (macOS $OMH_OMHER_ARCH)"
  OMH_OMHER_TMP="$(omh_temp_dir)"
  OMH_OMHER_LOOKUP=0
  OMH_OMHER_DMG_URL="$(omher_release_asset_url "macos-$OMH_OMHER_ARCH\\.dmg")" || OMH_OMHER_LOOKUP=$?
  case "$OMH_OMHER_LOOKUP" in
    0) ;;
    1)
      rm -rf "$OMH_OMHER_TMP"
      say_note "No omher release was found on GitHub yet."
      say_note "Hermes and OMH are installed. Get the app from $OMH_OMHER_SITE_URL when it is out."
      return 0
      ;;
    2)
      rm -rf "$OMH_OMHER_TMP"
      omher_app_failed "GitHub's API rate limit was reached (60 requests an hour per network without a token). Wait an hour, or set GITHUB_TOKEN, and run this again."
      ;;
    *)
      rm -rf "$OMH_OMHER_TMP"
      omher_app_failed "GitHub's API did not answer, so the omher release could not be looked up."
      ;;
  esac
  say_note "omher image: $OMH_OMHER_DMG_URL"
  if ! curl -fsSL -o "$OMH_OMHER_TMP/omher.dmg" "$OMH_OMHER_DMG_URL"; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not download $OMH_OMHER_DMG_URL"
  fi
  # Checked against the release's SHA256SUMS.txt before anything is mounted.
  OMH_OMHER_SUMS_URL="${OMH_OMHER_DMG_URL%/*}/SHA256SUMS.txt"
  if ! curl -fsSL -o "$OMH_OMHER_TMP/SHA256SUMS.txt" "$OMH_OMHER_SUMS_URL"; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not download $OMH_OMHER_SUMS_URL to check the image."
  fi
  OMH_OMHER_DMG_NAME="${OMH_OMHER_DMG_URL##*/}"
  OMH_OMHER_WANT="$(tr -d '\r' <"$OMH_OMHER_TMP/SHA256SUMS.txt" |
    awk -v name="$OMH_OMHER_DMG_NAME" '$2 == name || $2 == "*" name { print $1; exit }')"
  OMH_OMHER_GOT="$(omh_sha256 "$OMH_OMHER_TMP/omher.dmg")" || OMH_OMHER_GOT=""
  if [ -z "$OMH_OMHER_WANT" ] || [ -z "$OMH_OMHER_GOT" ] || [ "$OMH_OMHER_WANT" != "$OMH_OMHER_GOT" ]; then
    rm -rf "$OMH_OMHER_TMP"
    [ -n "$OMH_OMHER_WANT" ] || OMH_OMHER_WANT="no entry for $OMH_OMHER_DMG_NAME"
    [ -n "$OMH_OMHER_GOT" ] || OMH_OMHER_GOT="no checksum tool"
    omher_app_failed "The downloaded image does not match SHA256SUMS.txt (expected $OMH_OMHER_WANT, got $OMH_OMHER_GOT)."
  fi
  say_ok "SHA-256 matches SHA256SUMS.txt ($OMH_OMHER_DMG_NAME)"
  mkdir -p "$OMH_OMHER_TMP/mnt"
  if ! hdiutil attach -nobrowse -readonly -noautoopen -quiet -mountpoint "$OMH_OMHER_TMP/mnt" "$OMH_OMHER_TMP/omher.dmg" </dev/null; then
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not open the downloaded disk image."
  fi
  if [ ! -d "$OMH_OMHER_TMP/mnt/omher.app" ]; then
    hdiutil detach -quiet "$OMH_OMHER_TMP/mnt" </dev/null || true
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "The disk image has no omher.app."
  fi
  if [ -n "$OMH_APP_DIR" ]; then
    OMH_OMHER_DEST="$OMH_APP_DIR"
  elif [ -w /Applications ]; then
    OMH_OMHER_DEST="/Applications"
  else
    OMH_OMHER_DEST="$OMH_HOME_DIR/Applications"
  fi
  if ! mkdir -p "$OMH_OMHER_DEST"; then
    hdiutil detach -quiet "$OMH_OMHER_TMP/mnt" </dev/null || true
    rm -rf "$OMH_OMHER_TMP"
    omher_app_failed "Could not create $OMH_OMHER_DEST."
  fi
  # Copied under a hidden temporary name in the same folder first, and swapped
  # in only once the copy is whole: a failed copy (disk full, permissions, the
  # image going away) leaves an existing omher.app as it was.
  OMH_OMHER_NEW="$OMH_OMHER_DEST/.omher.app.new.$$"
  OMH_OMHER_OLD="$OMH_OMHER_DEST/.omher.app.old.$$"
  rm -rf "$OMH_OMHER_NEW" "$OMH_OMHER_OLD"
  OMH_OMHER_COPY_OK=0
  if command -v ditto >/dev/null 2>&1; then
    ditto "$OMH_OMHER_TMP/mnt/omher.app" "$OMH_OMHER_NEW" && OMH_OMHER_COPY_OK=1
  else
    cp -R "$OMH_OMHER_TMP/mnt/omher.app" "$OMH_OMHER_NEW" && OMH_OMHER_COPY_OK=1
  fi
  hdiutil detach -quiet "$OMH_OMHER_TMP/mnt" </dev/null || true
  rm -rf "$OMH_OMHER_TMP"
  if [ "$OMH_OMHER_COPY_OK" != "1" ]; then
    rm -rf "$OMH_OMHER_NEW"
    omher_app_failed "Could not copy omher.app into $OMH_OMHER_DEST."
  fi
  if [ -e "$OMH_OMHER_DEST/omher.app" ]; then
    if ! mv "$OMH_OMHER_DEST/omher.app" "$OMH_OMHER_OLD"; then
      rm -rf "$OMH_OMHER_NEW"
      omher_app_failed "Could not move the existing omher.app in $OMH_OMHER_DEST aside."
    fi
    say_note "Replacing the omher.app that was already in $OMH_OMHER_DEST."
  fi
  if ! mv "$OMH_OMHER_NEW" "$OMH_OMHER_DEST/omher.app"; then
    if [ -e "$OMH_OMHER_OLD" ]; then
      mv "$OMH_OMHER_OLD" "$OMH_OMHER_DEST/omher.app" || true
    fi
    rm -rf "$OMH_OMHER_NEW"
    omher_app_failed "Could not move the new omher.app into $OMH_OMHER_DEST."
  fi
  rm -rf "$OMH_OMHER_OLD"
  # curl sets no quarantine flag, so Gatekeeper should not ask; cleared anyway
  # in case a browser download of the same image left one behind.
  xattr -dr com.apple.quarantine "$OMH_OMHER_DEST/omher.app" 2>/dev/null || true
  OMH_OMHER_APP_PATH="$OMH_OMHER_DEST/omher.app"
  say_ok "$OMH_OMHER_APP_PATH"
}

say_header "$(msg installer_title)" "$(msg installer_subtitle)"
if [ "$OMH_OMHER_BETA" = "1" ]; then
  omher_beta_plan
  if [ "$OMH_INSTALL_HERMES" = "1" ]; then
    install_hermes
  fi
fi
# The interpreter first, and before any network work. Resolving the release
# used to run ahead of it, so a machine with no usable Python and an
# unreachable GitHub reported the release failure -- burying the very
# diagnosis this step exists to surface, and losing the older
# "OMH_PYTHON was not found" one as well.
resolve_python
say_note "Python: $OMH_PYTHON ($OMH_SELECTED_PYTHON_VERSION)"
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
        # GitHub answers /releases/latest with a 302 whose Location carries the
        # newest tag, so "latest" costs one header read and no API token. Only
        # the redirect target is fetched, never the release page.
        OMH_LATEST_LOCATION=""
        if command -v curl >/dev/null 2>&1; then
          OMH_LATEST_LOCATION="$(curl -sSI "$OMH_REPO_LATEST_URL" 2>/dev/null | tr -d '\r' | awk 'tolower($1) == "location:" { print $2 }' | tail -1)"
        elif command -v wget >/dev/null 2>&1; then
          OMH_LATEST_LOCATION="$(wget -qS --max-redirect=0 -O /dev/null "$OMH_REPO_LATEST_URL" 2>&1 | tr -d '\r' | awk 'tolower($1) == "location:" { print $2 }' | tail -1)"
        fi
        case "$OMH_LATEST_LOCATION" in
          */releases/tag/v*) OMH_VERSION="${OMH_LATEST_LOCATION##*/releases/tag/v}" ;;
          *)
            say "omh installer: could not resolve the latest release from $OMH_REPO_LATEST_URL."
            say "omh installer: set OMH_VERSION to pin one, or OMH_CHANNEL=preview to track main."
            exit 1
            ;;
        esac
      fi
      case "$OMH_VERSION" in
        v*) OMH_TAG="$OMH_VERSION" ;;
        *) OMH_TAG="v$OMH_VERSION" ;;
      esac
      # The release workflow only accepts a vX.Y.Z tag and uploads a wheel
      # named from that version, so the asset URL is predictable. It is ~2.7 MB
      # against ~44 MB for the tag archive, which carries assets, tests, and
      # site that nothing needs to run omh. A version outside that shape has no
      # published asset to name, so it keeps the archive.
      OMH_RELEASE_VERSION="${OMH_TAG#v}"
      if printf '%s' "$OMH_RELEASE_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
        OMH_PACKAGE_URL="$OMH_REPO_ASSET_ROOT/$OMH_TAG/oh_my_hermes-$OMH_RELEASE_VERSION-py3-none-any.whl"
      else
        OMH_PACKAGE_URL="$OMH_REPO_ARCHIVE_ROOT/tags/$OMH_TAG.zip"
      fi
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
  say_step "$(step_label "$OMH_EXPOSE_STEP")" "$(msg step_expose_command)"
  say_ok "$OMH_COMMAND_PATH"
  if ! command -v omh >/dev/null 2>&1; then
    OMH_COMMAND_DIR="$(dirname "$OMH_COMMAND_PATH")"
    say_note "'$OMH_COMMAND_DIR' is not on PATH for this shell."
    say_note "Add it with: export PATH=\"$OMH_COMMAND_DIR:\$PATH\""
    say_note "Until then, use: $OMH_COMMAND_PATH setup"
  fi
else
  say "omh installer: installed the package, but could not locate the omh command."
  say "Use '$OMH_RUNTIME_PYTHON -P -E -m omh.cli setup' as a fallback and check the selected Python scripts directory."
fi

if [ "$OMH_RUN_SETUP" = "1" ]; then
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

  say_step "$(step_label "$OMH_SETUP_STEP")" "$(msg step_setup)"
  run_omh "$@"

  if [ "$OMH_RUN_DOCTOR" = "0" ]; then
    say_note "Skipped doctor check because OMH_RUN_DOCTOR=0."
  else
    say_step "$(step_label "$OMH_DOCTOR_STEP")" "$(msg step_doctor)"
    OMH_DOCTOR_STATUS=0
    if [ -n "$OMH_SCOPE" ]; then
      run_omh --scope "$OMH_SCOPE" doctor || OMH_DOCTOR_STATUS=$?
    else
      run_omh doctor || OMH_DOCTOR_STATUS=$?
    fi
    if [ "$OMH_DOCTOR_STATUS" != "0" ]; then
      if [ "$OMH_OMHER_BETA" != "1" ]; then
        exit "$OMH_DOCTOR_STATUS"
      fi
      # A Hermes installed a minute ago has no model chosen yet, and doctor
      # says so. That is the next step for the person, not a reason to stop
      # before the app.
      say_note "omh doctor reported problems (above). Fix them after the install; continuing with the omher app."
    fi
  fi
elif [ "$OMH_AUTO_APPLY" = "0" ] || [ "$OMH_WITH_PLUGIN" = "1" ] || [ "$OMH_WITH_MCP" = "1" ] || [ -n "$OMH_SCOPE" ] || [ -n "$OMH_PROFILE_PACKS" ] || [ -n "$OMH_SETUP_PROFILES" ] || [ -n "$OMH_DEFAULT_EXECUTOR" ] || [ -n "$OMH_SETUP_ARGS" ] || [ "$OMH_RUN_DOCTOR" = "0" ]; then
  say_note "Setup options were not applied because install.sh now installs the command only by default."
  say_note "Run 'omh setup' with those choices explicitly, or set OMH_RUN_SETUP=1 for advanced one-shot bootstrap."
fi

if [ "$OMH_OMHER_BETA" = "1" ]; then
  if [ "$OMH_WITH_DESKTOP" = "0" ]; then
    say_note "Skipped the omher app because OMH_WITH_DESKTOP=0."
  else
    install_omher_app
  fi
fi

printf '\n'
say "$(color '1;36' "$(msg installed)")"
if command -v omh >/dev/null 2>&1; then
  say "$(msg next_path)"
elif [ -n "$OMH_COMMAND_PATH" ]; then
  say "$(msg next_command_path "$OMH_COMMAND_PATH")"
else
  say "Next: run '$OMH_PYTHON -P -E -m omh.cli setup' to connect OMH to Hermes, then '$OMH_PYTHON -P -E -m omh.cli doctor' to verify."
fi
if [ "$OMH_OMHER_BETA" = "1" ]; then
  if [ "$OMH_INSTALL_HERMES" = "1" ]; then
    # With the app (installed now, or the app that runs this with
    # OMH_WITH_DESKTOP=0), the model is picked in the app, not in a terminal.
    if [ -n "$OMH_OMHER_APP_PATH" ] || [ "$OMH_WITH_DESKTOP" = "0" ]; then
      say "Hermes was installed without its setup wizard. Open omher and pick a model from the model menu at the top of the chat."
    else
      say "Hermes was installed without its setup wizard: run 'hermes setup' to choose a model."
    fi
  fi
  if [ -n "$OMH_OMHER_APP_PATH" ]; then
    case "$OMH_OMHER_APP_PATH" in
      *.app) say "omher is in $OMH_OMHER_APP_PATH. Open it from there or from Launchpad." ;;
      *) say "omher is in $OMH_OMHER_APP_PATH. Open it from your app menu, or run 'omher' when $(dirname "$OMH_OMHER_APP_PATH") is on your PATH." ;;
    esac
  fi
fi
