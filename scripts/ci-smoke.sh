#!/bin/sh
# 배포할 엔진 실행 파일 하나를 실제로 돌려 본다 (요구 이력 73, BUILD_PLAN §4.13, 릴리스의 리눅스 작업이 부름).
#   scripts/ci-smoke.sh ENGINE [RUNNER]
# --version이 지금 소스의 지문을 내는지, 시험용 dev 명령이 없는지(종료 2), 훅 한 번이 기록을 남기는지 본다.
# RUNNER(예: qemu-aarch64-static)가 없으면 이 컴퓨터용으로 보고 hooks/emit.sh를 거쳐 부른다
# (emit.sh가 이 파일을 고르는지까지). RUNNER가 있으면 엔진을 직접 부른다(emit.sh는 이 컴퓨터용을 고르므로).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
engine=${1:?usage: ci-smoke.sh ENGINE [RUNNER]}
runner=${2:-}
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT

version=$($runner "$engine" --version)
echo "$version"
case $version in "nunchi-engine $(sed -n 's/^version = "\(.*\)"/\1/p' "$root/crates/engine/Cargo.toml") (src "*) ;; *) echo "버전이 다름" >&2; exit 1 ;; esac

set +e
$runner "$engine" dev >/dev/null 2>&1
code=$?
set -e
[ "$code" = 2 ] || { echo "dev 명령이 들어 있음 (종료 $code)" >&2; exit 1; }

event='{"session_id":"smoke","hook_event_name":"UserPromptSubmit","cwd":"/work","transcript_path":"/none.jsonl","prompt":"hello"}'
if [ -z "$runner" ]; then
  plugin="$home/plugin"
  mkdir -p "$plugin/hooks" "$plugin/bin"
  cp "$root/hooks/emit.sh" "$plugin/hooks/"
  cp "$engine" "$plugin/bin/"
  printf '%s' "$event" | CONTROL_TUI_HOME="$home/control" sh "$plugin/hooks/emit.sh"
else
  printf '%s' "$event" | CONTROL_TUI_HOME="$home/control" $runner "$engine" hook
fi
log="$home/control/sessions/smoke/events.jsonl"
grep -q '"prompt": "hello"' "$log" || { echo "훅 기록이 없음: $log" >&2; ls -R "$home" >&2; exit 1; }
[ ! -s "$home/control/errors.log" ] || { cat "$home/control/errors.log" >&2; exit 1; }
echo "ok: $(head -c 200 "$log")"
