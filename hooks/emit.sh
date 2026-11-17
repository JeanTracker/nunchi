#!/bin/sh
# 플러그인 훅의 입구 (요구 이력 67·68·69, BUILD_PLAN §4.12·§4.13).
#
# 함께 실린 엔진(bin/nunchi-engine)이 돌면 그것에 넘긴다. 배포용 브랜치(dist)에는 늘 실려 있다.
# 엔진이 없거나(저장소 사본에서 아직 빌드하지 않음) 이 맥에서 돌지 못하면, 세션 시작 때 한 번
# 사용자에게 고칠 방법을, 에이전트에게는 그것을 알리고 도우라는 안내를 내고, 다른 훅은 조용히 끝낸다
# (훅마다 오류 줄이 쌓이지 않게). 셸 내장 기능만 쓴다 (PATH가 비어 있어도 돌도록).

here=${0%/*}
engine="$here/../bin/nunchi-engine"
# 실행할 수 있는지 먼저 물어본다(약 5ms). 실행 권한이 있어도 못 도는 파일이면 exec가 실패해 훅 오류가 되기 때문이다.
if [ -x "$engine" ] && "$engine" --version >/dev/null 2>&1; then
  exec "$engine" hook
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
{"systemMessage": "눈치: 기록 엔진(bin/nunchi-engine)이 없어 이 세션을 기록·분석하지 못합니다. 받아 둔 저장소라면 scripts/build-engine.sh로 엔진을 빌드하고, 아니면 플러그인을 다시 설치한 뒤 세션을 다시 시작하세요.", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin has no engine binary (bin/nunchi-engine), so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help: in a clone of the nunchi repository, build it with scripts/build-engine.sh (needs rustup with the aarch64-apple-darwin and x86_64-apple-darwin targets); otherwise reinstall the plugin. Then restart the session. Do not change anything unless the user agrees. Mention it only once."}}
JSON
fi
exit 0
