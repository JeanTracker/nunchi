#!/bin/sh
# 배포용 엔진 실행 파일을 만든다 (요구 이력 68·73, BUILD_PLAN §4.13).
#   bin/nunchi-engine                 애플 실리콘과 인텔 맥용을 합친 것 (lipo, Xcode 개발 도구 필요)
#   bin/nunchi-engine-linux-x86_64    리눅스 musl 정적 빌드 (링커 rust-lld, .cargo/config.toml)
#   bin/nunchi-engine-linux-aarch64
# 맥에서는 세 개 모두, 리눅스에서는 그 CPU용 하나만 만든다. 필요한 rustup 대상은 아래 목록.
# Cargo.lock 그대로(--locked) 만든다. 실행 파일의 지문(--version)이 소스와 같은지는 cargo test가 확인한다.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
build() {
  cargo build --release --locked --no-default-features -p nunchi-engine --bin nunchi-engine --target "$1"
}
mkdir -p bin
case $(uname -s) in
  Darwin)
    for t in aarch64-apple-darwin x86_64-apple-darwin; do build "$t"; done
    lipo -create -output bin/nunchi-engine \
      target/aarch64-apple-darwin/release/nunchi-engine target/x86_64-apple-darwin/release/nunchi-engine
    lipo -info bin/nunchi-engine
    linux="x86_64 aarch64"
    ;;
  Linux)
    case $(uname -m) in
      x86_64 | amd64) linux=x86_64 ;;
      aarch64 | arm64) linux=aarch64 ;;
      *) echo "이 CPU($(uname -m))용 엔진은 만들지 않습니다." >&2; exit 1 ;;
    esac
    ;;
  *) echo "맥과 리눅스에서만 만듭니다." >&2; exit 1 ;;
esac
for a in $linux; do
  build "$a-unknown-linux-musl"
  cp "target/$a-unknown-linux-musl/release/nunchi-engine" "bin/nunchi-engine-linux-$a"
done
chmod 755 bin/nunchi-engine*
ls -l bin/nunchi-engine*
# 이 컴퓨터용만 실행해 본다 (다른 플랫폼용 파일은 셸이 스크립트로 읽으려 할 수 있어 실행하지 않는다)
host=bin/nunchi-engine
[ "$(uname -s)" = Linux ] && host=bin/nunchi-engine-linux-$linux
"$host" --version
