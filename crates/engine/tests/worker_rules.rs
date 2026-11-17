//! 분석기 자리·맡기 규칙과 깨우기 (`cargo test --features dev`).
#![cfg(feature = "dev")]

use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");
const FAKE: &str = env!("CARGO_BIN_EXE_fake-claude");

struct W {
    dir: PathBuf,
}

impl W {
    fn new(name: &str) -> W {
        let dir = std::env::temp_dir().join(format!("nunchi-rules-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        for d in ["home/queue", "home/sessions/s1", "fakebin", "fake"] {
            std::fs::create_dir_all(dir.join(d)).unwrap();
        }
        std::os::unix::fs::symlink(FAKE, dir.join("fakebin/claude")).unwrap();
        let t = dir.join("s1.jsonl");
        std::fs::write(&t, concat!(
            r#"{"type": "user", "message": {"role": "user", "content": "기능을 고쳐줘"}, "timestamp": "2026-01-01T00:00:10.000Z"}"#, "\n",
            r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "기능을 고쳤습니다."}]}, "timestamp": "2026-01-01T00:00:20.000Z"}"#, "\n")).unwrap();
        std::fs::write(dir.join("home/sessions/s1/want"), r#"{"on": true}"#).unwrap();
        W { dir }
    }
    fn home(&self) -> PathBuf {
        self.dir.join("home")
    }
    fn queue(&self) {
        let item = serde_json::json!({"session_id": "s1", "transcript_path": self.dir.join("s1.jsonl"), "source_ts": "2026-06-01T00:00:00.000Z",
                                      "force": false, "queued_at": "2026-06-01T00:00:00.000000Z", "by": "hook"});
        std::fs::write(self.home().join("queue/s1.json"), item.to_string()).unwrap();
    }
    fn cmd(&self) -> Command {
        let mut c = Command::new(ENGINE);
        c.env("PATH", format!("{}:{}", self.dir.join("fakebin").display(), std::env::var("PATH").unwrap()))
            .env("CONTROL_TUI_HOME", self.home()).env("CONTROL_TUI_REPLY_WAIT", "0").env_remove("CONTROL_TUI_WORKER")
            .env("FAKE_CLAUDE_STATE", self.dir.join("fake")).env_remove("FAKE_CLAUDE_SCRIPT").env_remove("CONTROL_TUI_ANALYZER");
        c
    }
    fn worker(&self) -> Duration {
        let t = Instant::now();
        assert!(self.cmd().args(["worker", "--home"]).arg(self.home()).status().unwrap().success());
        t.elapsed()
    }
    fn calls(&self) -> usize {
        std::fs::read_to_string(self.dir.join("fake/log")).map(|t| t.lines().count()).unwrap_or(0)
    }
    fn analyzed(&self) -> bool {
        self.home().join("sessions/s1/analysis.json").exists()
    }
}

impl Drop for W {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn lock(path: &Path) -> std::fs::File {
    let f = std::fs::OpenOptions::new().read(true).write(true).create(true).open(path).unwrap();
    assert_eq!(unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) }, 0);
    f
}

#[test]
fn worker_stands_down_while_the_slot_is_held() {
    let w = W::new("slot");
    w.queue();
    let held = lock(&w.home().join("analyzer-0.lock"));
    assert!(w.worker() < Duration::from_secs(2));
    assert_eq!(w.calls(), 0);
    assert!(w.home().join("queue/s1.json").exists());
    drop(held);
    w.worker();
    assert!(w.analyzed() && !w.home().join("queue/s1.json").exists());
}

#[test]
fn second_slot_is_used_when_two_workers_are_allowed() {
    let w = W::new("two");
    std::fs::write(w.home().join("config.json"), r#"{"analyze_workers": 2}"#).unwrap();
    w.queue();
    let _held = lock(&w.home().join("analyzer-0.lock"));
    w.worker();
    assert!(w.analyzed());
}

#[test]
fn live_claim_is_left_alone_and_dead_claim_is_taken_over() {
    let w = W::new("claim");
    w.queue();
    std::fs::write(w.home().join("queue/s1.claim"), std::process::id().to_string()).unwrap();
    assert!(w.worker() < Duration::from_secs(3));
    assert_eq!(w.calls(), 0);
    std::fs::write(w.home().join("queue/s1.claim"), "999999").unwrap();
    w.worker();
    assert!(w.analyzed());
    assert!(!w.home().join("queue/s1.claim").exists());
}

#[test]
fn stop_hook_wakes_a_detached_worker_that_finishes_and_exits() {
    let w = W::new("wake");
    let payload = serde_json::json!({"session_id": "s1", "hook_event_name": "Stop", "cwd": "/tmp",
                                     "transcript_path": w.dir.join("s1.jsonl")});
    let mut child = w.cmd().arg("hook").stdin(std::process::Stdio::piped()).spawn().unwrap();
    use std::io::Write;
    child.stdin.take().unwrap().write_all(payload.to_string().as_bytes()).unwrap();
    let t = Instant::now();
    assert!(child.wait().unwrap().success());
    assert!(t.elapsed() < Duration::from_secs(1), "훅은 분석을 기다리지 않고 바로 끝난다");
    let deadline = Instant::now() + Duration::from_secs(20);
    while !(w.analyzed() && !w.home().join("queue/s1.json").exists()) {
        assert!(Instant::now() < deadline, "깨운 분석기가 끝내지 못함");
        std::thread::sleep(Duration::from_millis(200));
    }
    // 분석기는 할 일이 없으면 스스로 끝난다: 자리 잠금이 곧 풀린다
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let f = std::fs::OpenOptions::new().read(true).write(true).open(w.home().join("analyzer-0.lock")).unwrap();
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
            break;
        }
        assert!(Instant::now() < deadline, "분석기가 끝나지 않고 자리를 쥐고 있음");
        std::thread::sleep(Duration::from_millis(200));
    }
}
