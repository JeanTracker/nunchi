#!/bin/sh
# 배포용 엔진 실행 파일을 만든다: 애플 실리콘과 인텔 맥용을 합친 bin/nunchi-engine (요구 이력 68, BUILD_PLAN §4.13).
# 필요: rustup, 두 대상(rustup target add aarch64-apple-darwin x86_64-apple-darwin), Xcode 개발 도구(lipo).
# Cargo.lock 그대로(--locked) 만든다. 실행 파일의 지문(--version)이 소스와 같은지는 cargo test가 확인한다.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
for t in aarch64-apple-darwin x86_64-apple-darwin; do
  cargo build --release --locked -p nunchi-engine --bin nunchi-engine --target "$t"
done
mkdir -p bin
lipo -create -output bin/nunchi-engine \
  target/aarch64-apple-darwin/release/nunchi-engine target/x86_64-apple-darwin/release/nunchi-engine
chmod 755 bin/nunchi-engine
lipo -info bin/nunchi-engine
bin/nunchi-engine --version
