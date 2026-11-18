#!/bin/sh
# 배포용 브랜치(dist)에 올릴 플러그인 폴더를 만든다 (요구 이력 69·73, BUILD_PLAN §4.13).
# 플러그인이 쓰는 파일과 엔진 실행 파일(맥, 리눅스 x86_64·arm64)만 담는다: 소스, 시험은 넣지 않는다.
#
#   scripts/build-engine.sh && scripts/make-dist.sh OUT
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: make-dist.sh OUT}
engines="bin/nunchi-engine bin/nunchi-engine-linux-x86_64 bin/nunchi-engine-linux-aarch64"
for e in $engines; do
  [ -f "$root/$e" ] || { echo "$e이 없습니다. 맥에서 scripts/build-engine.sh를 먼저 돌리세요." >&2; exit 1; }
done
rm -rf "$out"
mkdir -p "$out"
cd "$root"
# mod 모듈은 시험(*.test.tsx)만 빼고 모두: register.tsx가 부르는 본문(body.tsx)과 줄 그리기(rows.tsx)도 함께 (요구 이력 75)
mods=""
for m in mod/nunchi/hooks/*.tsx; do
  if [ "${m%.test.tsx}" = "$m" ]; then mods="$mods $m"; fi
done
for f in .claude-plugin/plugin.json hooks/hooks.json hooks/emit.sh \
         $mods mod/nunchi/types/index.d.ts mod/nunchi/tsconfig.json \
         LICENSE README.md docs/GUIDE.md $engines; do
  mkdir -p "$out/$(dirname "$f")"
  cp -p "$f" "$out/$f"
done
# README의 화면 그림 (README가 docs/images/를 상대 경로로 가리킨다)
if [ -d docs/images ]; then cp -Rp docs/images "$out/docs/"; fi
chmod 755 "$out/hooks/emit.sh"
for e in $engines; do chmod 755 "$out/$e"; done
echo "dist: $(cd "$out" && find . -type f | sort | tr '\n' ' ')"
