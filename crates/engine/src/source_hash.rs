// 엔진 소스 지문: src 아래 모든 파일(경로와 내용, 경로 순) + crates/engine/Cargo.toml + 맨 위 Cargo.lock.
// build.rs가 실행 파일에 넣고(--version), 시험이 저장소에 커밋된 실행 파일이 지금 소스로 만든 것인지 확인한다.
// build.rs와 시험이 include!로 같이 쓴다.

fn source_files(dir: &std::path::Path, out: &mut Vec<std::path::PathBuf>) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() { source_files(&p, out) } else { out.push(p) }
        }
    }
}

/// crate 폴더(crates/engine)를 받아 12자리 지문
pub fn source_hash(crate_dir: &std::path::Path) -> String {
    let mut files = Vec::new();
    source_files(&crate_dir.join("src"), &mut files);
    files.sort();
    files.push(crate_dir.join("Cargo.toml"));
    files.push(crate_dir.join("../../Cargo.lock"));
    let mut h = sha1_smol::Sha1::new();
    for f in &files {
        let rel = f.strip_prefix(crate_dir).unwrap_or(f).to_string_lossy().replace('\\', "/");
        h.update(rel.as_bytes());
        h.update(&[0]);
        h.update(&std::fs::read(f).unwrap_or_default());
        h.update(&[0]);
    }
    h.digest().to_string()[..12].to_string()
}
