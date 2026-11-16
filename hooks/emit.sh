#!/bin/sh
# 플러그인 훅의 입구 (요구 이력 67, BUILD_PLAN §4.12).
# 쓸 수 있는 python3(3.9 이상)가 있으면 emit.py로 넘긴다. 없으면 세션 시작 때 한 번,
# 사용자에게는 설치 방법을, 에이전트에게는 설치를 도와주라는 안내를 내고, 다른 훅은 조용히 끝낸다.
# 셸 내장 기능만 쓴다 (PATH가 비어 있어도 돌도록 dirname·cat 같은 바깥 명령을 쓰지 않는다).

here=${0%/*}
py=$(command -v python3 2>/dev/null || true)
# 개발 도구가 없는 맥의 /usr/bin/python3는 설치 창을 띄우는 껍데기라 부르지 않는다.
if [ "$py" = /usr/bin/python3 ] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
  py=""
fi
if [ -n "$py" ] && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
  exec "$py" "$here/emit.py"
fi

input=""
while IFS= read -r line || [ -n "$line" ]; do input="$input$line"; done
case $input in
  *'"hook_event_name":"SessionStart"'* | *'"hook_event_name": "SessionStart"'*) ;;
  *) exit 0 ;;
esac
while IFS= read -r line; do printf '%s\n' "$line"; done <<'JSON'
{"systemMessage": "눈치: python3(3.9 이상)를 찾지 못해 이 세션을 기록·분석하지 못합니다. 설치: xcode-select --install (또는 brew install python), 그다음 세션을 다시 시작하세요.", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin could not find python3 (3.9 or later) on PATH, so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help install it (on macOS `xcode-select --install` opens Apple's installer for the Command Line Tools, or `brew install python` if Homebrew is present), then restart the session. Do not install anything unless the user agrees. Mention it only once."}}
JSON
exit 0
