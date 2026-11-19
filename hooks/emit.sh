#!/bin/sh
# 플러그인 훅의 입구 (요구 이력 67·68·69·73, BUILD_PLAN §4.12·§4.13).
#
# 함께 실린 엔진 중 이 컴퓨터용을 골라 넘긴다. 배포용 브랜치(dist)에는 늘 실려 있다.
#   맥(/proc 없음)       bin/nunchi-engine (애플 실리콘·인텔 합친 것)
#   리눅스 x86_64·arm64  bin/nunchi-engine-linux-x86_64, bin/nunchi-engine-linux-aarch64
# 다른 플랫폼용 파일은 실행해 보지 않는다: 형식이 맞지 않으면 셸이 그 파일을 스크립트로 읽으려 할 수 있다.
# 엔진이 없거나(저장소 사본에서 아직 빌드하지 않음, 지원하지 않는 시스템) 돌지 못하면, 세션 시작 때 한 번
# 사용자에게 고칠 방법을, 에이전트에게는 그것을 알리고 도우라는 안내를 내고, 다른 훅은 조용히 끝낸다
# (훅마다 오류 줄이 쌓이지 않게). 맥에서는 셸 내장 기능만 쓴다 (PATH가 비어 있어도 돌도록).

here=${0%/*}
engine="$here/../bin/nunchi-engine"
arch=""
if [ -e /proc/self ]; then
  # 리눅스: CPU 이름은 /proc에서 셸 내장 read로, 없으면(옛 커널) uname으로 (PATH가 비어도 찾게 절대 경로도)
  if [ -r /proc/sys/kernel/arch ]; then read -r arch </proc/sys/kernel/arch; fi
  for u in uname /usr/bin/uname /bin/uname; do
    [ -n "$arch" ] && break
    arch=$("$u" -m 2>/dev/null)
  done
  case $arch in
    x86_64 | amd64) engine="$here/../bin/nunchi-engine-linux-x86_64" ;;
    aarch64 | arm64) engine="$here/../bin/nunchi-engine-linux-aarch64" ;;
    *) engine="" ;;
  esac
fi
# 다시 분석 (요구 이력 76): mod가 `emit.sh rebuild <세션 ID> <언어>`로 부른다. 엔진이 없으면 입력을 기다리지 않고 실패로 끝낸다
if [ "${1:-}" = rebuild ]; then
  if [ -n "$engine" ] && [ -x "$engine" ]; then exec "$engine" rebuild "${2:-}" "${3:-}"; fi
  exit 1
fi
# 지금까지 분석 (요구 이력 93): mod가 `emit.sh build <세션 ID> <언어> [--count]`로 부른다. 엔진이 한 줄 JSON을 낸다
if [ "${1:-}" = build ]; then
  if [ -n "$engine" ] && [ -x "$engine" ]; then exec "$engine" build "${2:-}" "${3:-}" ${4:+"$4"}; fi
  exit 1
fi
# 실행할 수 있는지 먼저 물어본다(약 5ms). 실행 권한이 있어도 못 도는 파일이면 exec가 실패해 훅 오류가 되기 때문이다.
if [ -n "$engine" ] && [ -x "$engine" ] && "$engine" --version >/dev/null 2>&1; then
  exec "$engine" hook
fi

input=""
while IFS= read -r line || [ -n "$line" ]; do input="$input$line"; done
case $input in
  *'"hook_event_name":"SessionStart"'* | *'"hook_event_name": "SessionStart"'*) ;;
  *) exit 0 ;;
esac
if [ -z "$engine" ]; then
  printf '%s\n' "{\"systemMessage\": \"눈치: 이 시스템(리눅스 ${arch:-CPU 모름})용 기록 엔진이 없어 이 세션을 기록·분석하지 못합니다. 눈치는 맥과 리눅스 x86_64·arm64에서 돕니다.\", \"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"The nunchi plugin has no engine for this system (Linux ${arch:-unknown CPU}); it runs on macOS and on Linux x86_64 and arm64, so it cannot record or analyze this session. In your first reply, tell the user this in one sentence. Do not change anything unless the user agrees. Mention it only once.\"}}"
elif [ -e "$engine" ]; then
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'JSON'
{"systemMessage": "눈치: 함께 실린 기록 엔진을 실행하지 못해 이 세션을 기록·분석하지 못합니다. 플러그인을 갱신하거나 다시 설치한 뒤 세션을 다시 시작하세요: claude plugin update nunchi@nunchi", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin could not run its bundled engine (bin/nunchi-engine*), so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help: update or reinstall the plugin (`claude plugin update nunchi@nunchi`, or uninstall and install it again), then restart the session. Do not change anything unless the user agrees. Mention it only once."}}
JSON
else
  while IFS= read -r line; do printf '%s\n' "$line"; done <<'JSON'
{"systemMessage": "눈치: 기록 엔진(bin/nunchi-engine*)이 없어 이 세션을 기록·분석하지 못합니다. 받아 둔 저장소라면 scripts/build-engine.sh로 엔진을 빌드하고, 아니면 플러그인을 다시 설치한 뒤 세션을 다시 시작하세요.", "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "The nunchi plugin has no engine binary for this system (bin/nunchi-engine*), so it cannot record or analyze this session. In your first reply, tell the user this in one sentence and offer to help: in a clone of the nunchi repository, build it with scripts/build-engine.sh (on macOS it needs rustup targets aarch64-apple-darwin, x86_64-apple-darwin, x86_64-unknown-linux-musl and aarch64-unknown-linux-musl; on Linux the musl target for its CPU); otherwise reinstall the plugin. Then restart the session. Do not change anything unless the user agrees. Mention it only once."}}
JSON
fi
exit 0
