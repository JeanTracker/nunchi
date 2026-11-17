#!/bin/sh
# 플러그인 훅의 입구 (요구 이력 67·68·69, BUILD_PLAN §4.12·§4.13).
#
# 1. 함께 실린 엔진(bin/nunchi-engine)이 돌면 그것에 넘긴다. 배포용 브랜치(dist)에는 늘 실려 있고 파이썬이 필요 없다.
# 2. 엔진이 없는 저장소 사본(개발 중, 아직 scripts/build-engine.sh를 돌리지 않음)이면 파이썬 기록기 emit.py로 넘긴다.
# 3. 둘 다 안 되면 세션 시작 때 한 번, 사용자에게 고칠 방법을, 에이전트에게는 그것을 알리고 도우라는 안내를 내고,
#    다른 훅은 조용히 끝낸다 (훅마다 오류 줄이 쌓이지 않게).
# 셸 내장 기능만 쓴다 (PATH가 비어 있어도 돌도록 dirname·cat 같은 바깥 명령을 쓰지 않는다).

here=${0%/*}
engine="$here/../bin/nunchi-engine"
# 실행할 수 있는지 먼저 물어본다(약 5ms). 실행 권한이 있어도 못 도는 파일이면 exec가 실패해 훅 오류가 되기 때문이다.
if [ -x "$engine" ] && "$engine" --version >/dev/null 2>&1; then
  exec "$engine" hook
fi

if [ -f "$here/emit.py" ]; then
  py=$(command -v python3 2>/dev/null || true)
  # 개발 도구가 없는 맥의 /usr/bin/python3는 설치 창을 띄우는 껍데기라 부르지 않는다.
  if [ "$py" = /usr/bin/python3 ] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    py=""
  fi
  if [ -n "$py" ] && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$py" "$here/emit.py"
  fi
fi

input=""
while IFS= read -r line || [ -n "$line" ]; do input="$input$line"; done
case $input in
  *'"hook_event_name":"SessionStart"'* | *'"hook_event_name": "SessionStart"'*) ;;
  *) exit 0 ;;
esac
if [ -e "$engine" ]; then
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'JSON'
{"systemMessage": "눈치: 기록 엔진(bin/nunchi-engine)을 실행하지 못해 이 세션을 기록·분석하지 못합니다. 플러그인을 갱신하거나 다시 설치한 뒤 세션을 다시 시작하세요: claude plugin update nunchi@nunchi", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin could not run its bundled engine (bin/nunchi-engine), so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help: update or reinstall the plugin (`claude plugin update nunchi@nunchi`, or uninstall and install it again), then restart the session. Do not change anything unless the user agrees. Mention it only once."}}
JSON
else
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'JSON'
{"systemMessage": "눈치: python3(3.9 이상)를 찾지 못해 이 세션을 기록·분석하지 못합니다. 설치: xcode-select --install (또는 brew install python), 그다음 세션을 다시 시작하세요.", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin could not find python3 (3.9 or later) on PATH, so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help install it (on macOS `xcode-select --install` opens Apple's installer for the Command Line Tools, or `brew install python` if Homebrew is present), then restart the session. Do not install anything unless the user agrees. Mention it only once."}}
JSON
fi
exit 0
