#!/bin/sh
# nunchi 관제 화면 설치·갱신·삭제 스크립트.
# 훅과 분석기, 세션 안 패널(mod)은 Claude Code 플러그인이 설치한다 (docs/GUIDE.md).
#
#   curl -fsSL https://raw.githubusercontent.com/JeanTracker/nunchi/main/install.sh | sh
#   ./install.sh                 # 저장소를 직접 받아 둔 경우 (그 폴더에 그대로 설치)
#   ./install.sh --uninstall     # 삭제
#
# 자세한 내용은 docs/GUIDE.md. 옵션은 --help.
set -eu

REPO_URL=${NUNCHI_REPO:-https://github.com/JeanTracker/nunchi.git}
BRANCH=${NUNCHI_BRANCH:-main}
CLONE_DIR=${NUNCHI_HOME:-$HOME/.local/share/nunchi}
BIN_DIR=${NUNCHI_BIN:-$HOME/.local/bin}
SETTINGS=${NUNCHI_CLAUDE_SETTINGS:-$HOME/.claude/settings.json}
DATA_DIR=${CONTROL_TUI_HOME:-$HOME/.claude-control}
LINK="$BIN_DIR/nunchi"
BEGIN_MARK='# >>> nunchi >>>'
END_MARK='# <<< nunchi <<<'
MANAGED_MARK='.git/nunchi-managed'   # 이 스크립트가 클론한 폴더 표시 (삭제 때 지워도 되는지)
VENV_MARK='.venv/.nunchi-installer'  # 이 스크립트가 만든 venv 표시

ASSUME_YES=0
SKIP_HOOKS=0
MODE=install

say()  { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
warn() { printf '경고: %s\n' "$*" >&2; }
die()  { printf '오류: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
nunchi 설치 스크립트

  install.sh [옵션]

옵션
  (없음)         설치 또는 갱신: 내려받기, 파이썬 환경, 명령 연결, PATH, Claude Code 설정 정리
  --link         $LINK 링크만 다시 만든다
  --path         PATH만 확인하고, 빠져 있으면 셸 설정 파일에 넣는다
  --settings     Claude Code 설정만 정리한다: 예전에 넣은 훅을 빼고(훅은 플러그인이 맡음) 상태 표시줄을 감싼다
  --hooks        플러그인 없이 쓸 때: Claude Code 훅을 settings.json에 넣는다
                 (플러그인과 함께 두면 기록이 두 번 남는다)
  --uninstall    삭제: 이 폴더의 훅과 상태 표시줄, 링크, 셸 설정 블록, 내려받은 폴더
  --no-hooks     설치할 때 Claude Code 설정을 건드리지 않는다
  -y, --yes      묻지 않고 진행한다 (~/.claude/settings.json 변경 포함)
  -h, --help     이 도움말

curl로 받을 때는 옵션을 'sh -s --' 뒤에 쓴다:
  curl -fsSL .../install.sh | sh -s -- --uninstall

환경변수
  NUNCHI_HOME              내려받을 폴더 (기본 ~/.local/share/nunchi)
  NUNCHI_BIN               명령을 둘 폴더 (기본 ~/.local/bin)
  NUNCHI_RC                PATH를 넣을 셸 설정 파일 (기본은 \$SHELL로 고름)
  NUNCHI_REPO              저장소 주소 (기본 $REPO_URL)
  NUNCHI_BRANCH            브랜치 (기본 main)
  NUNCHI_PYTHON            쓸 파이썬 (3.11 이상)
  NUNCHI_CLAUDE_SETTINGS   Claude Code 설정 파일 (기본 ~/.claude/settings.json)
EOF
}

while [ $# -gt 0 ]; do
  case $1 in
    --link) MODE=link ;;
    --path) MODE=path ;;
    --hooks) MODE=hooks ;;
    --settings) MODE=settings ;;
    --uninstall) MODE=uninstall ;;
    --no-hooks) SKIP_HOOKS=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "모르는 옵션: $1" ;;
  esac
  shift
done

# ---------- 공통 도우미 ----------

# 묻기. curl | sh 로 실행되면 stdin이 파이프이므로 /dev/tty에서 읽는다.
confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  if ( : </dev/tty ) 2>/dev/null; then
    printf '%s [y/N] ' "$1" >/dev/tty
    read -r answer </dev/tty || return 1
    case $answer in y|Y|yes|YES) return 0 ;; esac
  fi
  return 1
}

# 이 스크립트가 받아 둔 저장소 안에서 실행됐으면 그 폴더를 돌려준다.
script_checkout() {
  case $0 in */install.sh|install.sh) ;; *) return 1 ;; esac
  [ -f "$0" ] || return 1
  dir=$(cd "$(dirname "$0")" && pwd)
  [ -f "$dir/pyproject.toml" ] && [ -d "$dir/control_tui" ] && [ -f "$dir/bin/nunchi" ] || return 1
  printf '%s\n' "$dir"
}

# 링크를 따라가 실제 파일 경로를 돌려준다 (macOS 옛 readlink에는 -f가 없다).
resolve_link() {
  target=$1
  while [ -L "$target" ]; do
    next=$(readlink "$target")
    case $next in /*) target=$next ;; *) target=$(dirname "$target")/$next ;; esac
  done
  printf '%s\n' "$target"
}

# 고친 파일 목록. 실행 권한 차이(chmod)는 고친 것으로 치지 않는다.
changed_files() {
  git -C "$1" -c core.fileMode=false status --porcelain 2>/dev/null
}

python_ok() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

find_python() {
  if [ -n "${NUNCHI_PYTHON:-}" ]; then
    python_ok "$NUNCHI_PYTHON" || die "NUNCHI_PYTHON=$NUNCHI_PYTHON 은 파이썬 3.11 이상이 아닙니다."
    printf '%s\n' "$NUNCHI_PYTHON"; return
  fi
  for cand in python3.13 python3.12 python3.11 python3.14 python3; do
    if command -v "$cand" >/dev/null 2>&1 && python_ok "$cand"; then
      command -v "$cand"; return
    fi
  done
  die "파이썬 3.11 이상이 필요합니다. 예: brew install python@3.13 (설치 후 다시 실행)"
}

rc_file() {
  if [ -n "${NUNCHI_RC:-}" ]; then printf '%s\n' "$NUNCHI_RC"; return; fi
  case $(basename "${SHELL:-sh}") in
    zsh) printf '%s\n' "$HOME/.zshrc" ;;
    bash)
      if [ "$(uname -s)" = Darwin ]; then printf '%s\n' "$HOME/.bash_profile"
      else printf '%s\n' "$HOME/.bashrc"; fi ;;
    *) printf '%s\n' "$HOME/.profile" ;;
  esac
}

# 셸 설정 파일에서 nunchi 블록만 지운다. 파일 권한과 링크는 그대로 둔다.
strip_block() {
  f=$1
  [ -f "$f" ] || return 0
  grep -qF "$BEGIN_MARK" "$f" || return 0
  tmp=$(mktemp)
  awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
    $0 == b { skip = 1; next }
    $0 == e { skip = 0; next }
    !skip { print }' "$f" >"$tmp"
  cat "$tmp" >"$f"
  rm -f "$tmp"
  say "  $f 에서 nunchi 블록을 지웠습니다."
}

# ---------- 설치 단계 ----------

check_env() {
  step "환경 확인"
  [ "$(uname -s)" = Darwin ] || warn "nunchi는 macOS + iTerm2 기준입니다. 다른 환경에서는 패널에 글을 보낼 수 없습니다."
  if [ -d /Applications/iTerm.app ] || [ -d "$HOME/Applications/iTerm.app" ]; then
    say "  iTerm2: 있음"
  else
    warn "iTerm2를 찾지 못했습니다. https://iterm2.com 에서 설치하세요."
  fi
  if command -v claude >/dev/null 2>&1; then
    say "  claude: $(command -v claude)"
  else
    warn "claude 명령이 PATH에 없습니다. 세션 기록은 되지만 분석 기능은 동작하지 않습니다."
  fi
  command -v git >/dev/null 2>&1 || die "git이 필요합니다. xcode-select --install 로 설치하세요."
  PY=$(find_python)
  say "  파이썬: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"
}

get_source() {
  step "소스 준비"
  # 직접 받아 둔 저장소에서 실행하면 그 폴더에 그대로 설치한다 (갱신은 사용자가 git pull).
  # 이 스크립트가 내려받은 폴더의 install.sh를 다시 실행한 경우는 아래 갱신 경로로 간다.
  if SRC=$(script_checkout) && [ -z "${NUNCHI_HOME:-}" ]; then
    if [ ! -f "$SRC/$MANAGED_MARK" ]; then
      say "  받아 둔 저장소에 그대로 설치합니다: $SRC (갱신은 git pull 후 다시 실행)"
      return
    fi
  else
    SRC=$CLONE_DIR
  fi
  if [ -d "$SRC/.git" ]; then
    if [ -n "$(changed_files "$SRC")" ]; then
      warn "$SRC 에 고친 파일이 있어 갱신하지 않고 그대로 씁니다."
    else
      say "  갱신: $SRC"
      git -C "$SRC" pull --ff-only --quiet origin "$BRANCH" || warn "갱신하지 못했습니다. 지금 버전으로 계속합니다."
    fi
  elif [ -e "$SRC" ]; then
    die "$SRC 가 이미 있지만 git 저장소가 아닙니다. 옮기거나 NUNCHI_HOME으로 다른 곳을 고르세요."
  else
    say "  내려받기: $REPO_URL → $SRC"
    mkdir -p "$(dirname "$SRC")"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$SRC" \
      || die "내려받지 못했습니다. 저장소 접근 권한(비공개 저장소면 git 로그인)을 확인하세요."
    : >"$SRC/$MANAGED_MARK"
  fi
}

setup_venv() {
  step "파이썬 환경 (.venv)"
  venv="$SRC/.venv"
  if [ -x "$venv/bin/python" ] && python_ok "$venv/bin/python"; then
    say "  있는 환경을 씁니다: $venv"
  else
    if [ -d "$venv" ] && [ ! -f "$SRC/$VENV_MARK" ]; then
      die "$venv 가 망가졌거나 3.11 미만입니다. 직접 만든 환경이라 지우지 않습니다. 정리한 뒤 다시 실행하세요."
    fi
    rm -rf "$venv"
    "$PY" -m venv "$venv"
    : >"$SRC/$VENV_MARK"
    say "  만들었습니다: $venv"
  fi
  say "  의존성 설치 중 (textual)..."
  "$venv/bin/python" -m pip install --quiet --disable-pip-version-check -e "$SRC" \
    || die "pip 설치에 실패했습니다. 네트워크를 확인하고 다시 실행하세요."
}

do_link() {
  step "명령 연결: $LINK"
  want="$SRC/bin/nunchi"
  chmod +x "$want"
  mkdir -p "$BIN_DIR"
  if [ -L "$LINK" ]; then
    rm -f "$LINK"
  elif [ -e "$LINK" ]; then
    die "$LINK 가 일반 파일이라 건드리지 않습니다. 직접 옮긴 뒤 다시 실행하세요."
  fi
  ln -s "$want" "$LINK"
  say "  $LINK → $want"
}

do_path() {
  step "PATH 확인"
  case ":$PATH:" in
    *":$BIN_DIR:"*) say "  $BIN_DIR 가 이미 PATH에 있습니다."; return ;;
  esac
  rc=$(rc_file)
  if [ -f "$rc" ] && grep -qF "$BEGIN_MARK" "$rc"; then
    say "  $rc 에 이미 넣어 두었습니다. 새 터미널을 열면 적용됩니다."
    return
  fi
  # 블록 앞에 빈 줄을 넣지 않는다. 그래야 삭제 뒤 파일이 설치 전과 똑같다.
  if [ -s "$rc" ] && [ "$(tail -c 1 "$rc")" != "" ]; then printf '\n' >>"$rc"; fi
  {
    printf '%s\n' "$BEGIN_MARK"
    printf 'export PATH="%s:$PATH"\n' "$BIN_DIR"
    printf '%s\n' "$END_MARK"
  } >>"$rc"
  say "  $rc 에 PATH를 넣었습니다. 새 터미널을 열거나: source $rc"
}

hook_python() {
  if [ -x "$SRC/.venv/bin/python" ]; then printf '%s\n' "$SRC/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then command -v python3
  else return 1; fi
}

# $1: 비우면 settings.json에 훅 등록, --plugin이면 옛 훅을 빼고 상태 표시줄만, --remove면 제거
do_hooks() {
  action=${1:-}
  case $action in
    "") step "Claude Code 훅 등록 ($SETTINGS)" ;;
    --plugin) step "Claude Code 설정 정리 ($SETTINGS): 훅은 플러그인이 맡고, 여기는 상태 표시줄만" ;;
    *) step "Claude Code 훅 제거 ($SETTINGS)" ;;
  esac
  hp=$(hook_python) || { warn "파이썬이 없어 훅을 처리하지 못했습니다."; return 0; }
  script="$SRC/scripts/install_hooks.py"
  set +e
  "$hp" "$script" --settings "$SETTINGS" $action --check
  rc=$?
  set -e
  [ $rc = 0 ] && return 0
  [ $rc = 1 ] || { warn "훅 확인에 실패했습니다 (종료 코드 $rc)."; return 0; }
  say ""
  say "위 diff대로 $SETTINGS 를 바꿉니다. 바꾸기 전에 같은 폴더에 백업을 만듭니다."
  if confirm "적용할까요?"; then
    out=$("$hp" "$script" --settings "$SETTINGS" $action --apply) || die "훅 적용에 실패했습니다."
    printf '%s\n' "$out" | grep -E '^(백업|적용 완료):' | sed 's/^/  /' || true
  else
    say "  바꾸지 않았습니다. 나중에 적용하려면:"
    case $action in
      "") say "    $SRC/install.sh --hooks" ;;
      --plugin) say "    $SRC/install.sh --settings" ;;
      *) say "    $hp $script $action --apply" ;;
    esac
    HOOKS_PENDING=1
  fi
}

plugin_installed() {
  f="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json"
  [ -f "$f" ] && grep -q '"nunchi@nunchi"' "$f"
}

# 플러그인은 ~/.claude를 바꾸므로 이 스크립트가 설치하지 않고 명령만 보여 준다.
plugin_hint() {
  if plugin_installed; then
    say "  플러그인 nunchi@nunchi: 설치됨 (갱신: claude plugin marketplace update nunchi && claude plugin update nunchi@nunchi)"
  else
    say "  플러그인이 아직 없습니다. 세션 기록과 분석은 플러그인이 하므로, 없으면 세션이 화면에 나타나지 않습니다."
    say "  Claude Code 안에서:  /plugin install nunchi --marketplace JeanTracker/nunchi"
  fi
}

install_all() {
  HOOKS_PENDING=0
  check_env
  get_source
  setup_venv
  do_link
  do_path
  if [ "$SKIP_HOOKS" = 1 ]; then
    step "Claude Code 설정 건너뜀 (--no-hooks). 나중에: $SRC/install.sh --settings"
  else
    do_hooks --plugin
  fi
  step "완료"
  say "  iTerm2 패널 하나에서 'nunchi' 를 실행하세요. 사용법: $SRC/docs/GUIDE.md"
  plugin_hint
  say "  이미 열려 있던 Claude Code 세션은 한 번 다시 시작해야 연결됩니다."
  return 0
}

# ---------- 삭제 ----------

uninstall_all() {
  step "설치 위치 찾기"
  SRC=""
  if [ -L "$LINK" ]; then
    target=$(resolve_link "$LINK")
    case $target in */bin/nunchi) SRC=$(dirname "$(dirname "$target")") ;; esac
  fi
  if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
    if [ -d "$CLONE_DIR" ]; then SRC=$CLONE_DIR
    elif d=$(script_checkout); then SRC=$d
    else SRC=""; fi
  fi
  [ -n "$SRC" ] && say "  $SRC" || say "  내려받은 폴더가 없습니다. 남은 링크와 셸 설정만 정리합니다."

  if [ -n "$SRC" ] && [ -f "$SRC/scripts/install_hooks.py" ]; then
    HOOKS_PENDING=0
    do_hooks --remove
    if [ "$HOOKS_PENDING" = 1 ]; then
      die "훅을 빼지 않으면 Claude Code가 지워진 파일을 계속 부릅니다. 폴더는 지우지 않고 멈춥니다."
    fi
    if [ -f "$SETTINGS" ] && grep -qF "$SRC/hooks/statusline.py" "$SETTINGS"; then
      die "statusLine이 아직 $SRC/hooks/statusline.py 를 부릅니다. $SETTINGS 의 statusLine을 직접 고친 뒤 다시 --uninstall 하세요. 폴더는 지우지 않고 멈춥니다."
    fi
  elif [ -f "$SETTINGS" ] && grep -qE 'hooks/emit\.(py|sh)' "$SETTINGS"; then
    warn "$SETTINGS 에 nunchi 훅이 남아 있습니다. 같은 위치에 다시 설치한 뒤 --uninstall 하거나, 'hooks/emit.sh'·'hooks/emit.py'·'hooks/statusline.py' 항목을 직접 지우세요."
  fi

  step "명령 링크 정리"
  if [ -L "$LINK" ]; then
    target=$(resolve_link "$LINK")
    if [ ! -e "$target" ] || { [ -n "$SRC" ] && [ "$target" = "$SRC/bin/nunchi" ]; }; then
      rm -f "$LINK"; say "  $LINK 를 지웠습니다."
    else
      warn "$LINK 가 다른 곳($target)을 가리켜 그대로 둡니다."
    fi
  else
    say "  링크가 없습니다."
  fi

  step "셸 설정 정리"
  for f in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc" "$HOME/.profile" ${NUNCHI_RC:+"$NUNCHI_RC"}; do
    strip_block "$f"
  done

  if [ -n "$SRC" ]; then
    step "폴더 정리"
    if [ -f "$SRC/$MANAGED_MARK" ]; then
      if [ -n "$(changed_files "$SRC")" ]; then
        warn "$SRC 에 고치거나 새로 만든 파일이 있어 지우지 않습니다. 확인 후 직접 지우세요."
      else
        rm -rf "$SRC"; say "  $SRC 를 지웠습니다."
      fi
    else
      if [ -f "$SRC/$VENV_MARK" ]; then
        rm -rf "$SRC/.venv"; say "  설치 때 만든 $SRC/.venv 를 지웠습니다."
      fi
      say "  $SRC 는 직접 받아 둔 저장소라 남겨 둡니다."
    fi
  fi

  step "삭제 완료"
  if [ -d "$DATA_DIR" ]; then
    say "  세션 기록과 설정($DATA_DIR)은 남겨 두었습니다. 필요 없으면: rm -rf $DATA_DIR"
  fi
  say "  열려 있는 Claude Code 세션은 다시 시작하면 훅 없이 돕니다."
}

case $MODE in
  install) install_all ;;
  link)
    SRC=$(script_checkout) || SRC=$CLONE_DIR
    [ -f "$SRC/bin/nunchi" ] || die "$SRC 에 nunchi가 없습니다. 먼저 설치하세요."
    do_link ;;
  path) do_path ;;
  hooks)
    HOOKS_PENDING=0
    SRC=$(script_checkout) || SRC=$CLONE_DIR
    [ -f "$SRC/scripts/install_hooks.py" ] || die "$SRC 에 nunchi가 없습니다. 먼저 설치하세요."
    do_hooks ;;
  settings)
    HOOKS_PENDING=0
    SRC=$(script_checkout) || SRC=$CLONE_DIR
    [ -f "$SRC/scripts/install_hooks.py" ] || die "$SRC 에 nunchi가 없습니다. 먼저 설치하세요."
    do_hooks --plugin
    plugin_hint ;;
  uninstall) uninstall_all ;;
esac
