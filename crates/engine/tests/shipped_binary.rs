//! 저장소에 커밋된 bin/nunchi-engine이 지금 소스로 만든 것인지 (오래된 실행 파일을 싣지 않게).
include!("../src/source_hash.rs");

#[test]
fn shipped_binary_matches_the_sources() {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let shipped = dir.join("../../bin/nunchi-engine");
    if !shipped.exists() {
        return; // 아직 실어 보내지 않았다
    }
    let out = std::process::Command::new(&shipped).arg("--version").output().expect("bin/nunchi-engine 실행");
    let text = String::from_utf8_lossy(&out.stdout).to_string();
    let want = source_hash(&dir);
    assert!(text.contains(&format!("(src {want})")), "bin/nunchi-engine이 옛 소스로 만든 것: {text:?}, 지금 소스 {want}. scripts/build-engine.sh로 다시 만들 것");
    let dev = std::process::Command::new(&shipped).arg("dev").output().unwrap();
    assert_eq!(dev.status.code(), Some(2), "배포용 실행 파일에 시험용 dev 명령이 들어 있다 (--no-default-features로 만들 것)");
}
