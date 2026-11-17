//! bin/의 엔진 실행 파일이 지금 소스로 만든 것인지 (오래된 실행 파일을 싣지 않게, 요구 이력 69·73).
//! 이 컴퓨터용은 돌려서 지문과 dev 명령 없음을 보고, 다른 플랫폼용은 지문 글자가 들어 있는지만 본다
//! (다른 플랫폼용 파일은 실행하지 않는다).
include!("../src/source_hash.rs");

const SHIPPED: [&str; 3] = ["nunchi-engine", "nunchi-engine-linux-x86_64", "nunchi-engine-linux-aarch64"];

fn host_binary() -> Option<&'static str> {
    if cfg!(target_os = "macos") {
        Some("nunchi-engine")
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        Some("nunchi-engine-linux-x86_64")
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        Some("nunchi-engine-linux-aarch64")
    } else {
        None
    }
}

#[test]
fn shipped_binaries_match_the_sources() {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let want = source_hash(&dir);
    for name in SHIPPED {
        let shipped = dir.join("../../bin").join(name);
        if !shipped.exists() {
            continue; // 아직 만들지 않았다
        }
        let bytes = std::fs::read(&shipped).unwrap();
        assert!(bytes.windows(want.len()).any(|w| w == want.as_bytes()),
                "bin/{name}이 옛 소스로 만든 것(지금 소스 {want}). scripts/build-engine.sh로 다시 만들 것");
        if Some(name) != host_binary() {
            continue;
        }
        let out = std::process::Command::new(&shipped).arg("--version").output().expect("bin 엔진 실행");
        let text = String::from_utf8_lossy(&out.stdout).to_string();
        assert!(text.contains(&format!("(src {want})")), "bin/{name}이 옛 소스로 만든 것: {text:?}, 지금 소스 {want}");
        let dev = std::process::Command::new(&shipped).arg("dev").output().unwrap();
        assert_eq!(dev.status.code(), Some(2), "bin/{name}에 시험용 dev 명령이 들어 있다 (--no-default-features로 만들 것)");
    }
}
