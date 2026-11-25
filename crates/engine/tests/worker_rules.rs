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

// 한 세션의 요청이 옛 훅의 .json과 새 엔진의 .job으로 나뉘어도 (요구 이력 93) 옛 시각 요청 때문에 흐름을
// 처음부터 다시 만들지 않는다. 실제로 /nunchi build의 옛 시각 요청을 뒤에 맡아 46턴을 다시 분석한 일이 있었다
#[test]
fn an_older_request_in_the_other_queue_file_does_not_restart_the_flow() {
    let w = W::new("split");
    std::fs::write(w.dir.join("s1.jsonl"), concat!(
        r#"{"type": "user", "message": {"role": "user", "content": "기능을 고쳐줘"}, "timestamp": "2026-01-01T00:00:10.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "기능을 고쳤습니다."}]}, "timestamp": "2026-01-01T00:00:20.000Z"}"#, "\n",
        r#"{"type": "user", "message": {"role": "user", "content": "문서도 고쳐줘"}, "timestamp": "2026-01-01T00:00:30.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "문서도 고쳤습니다."}]}, "timestamp": "2026-01-01T00:00:40.000Z"}"#, "\n")).unwrap();
    let item = |ts: &str, force: bool, q: &str| serde_json::json!({"session_id": "s1", "transcript_path": w.dir.join("s1.jsonl"), "source_ts": ts,
                                                                  "force": force, "queued_at": q, "by": "hook"}).to_string();
    std::fs::write(w.home().join("queue/s1.json"), item("2026-01-01T00:00:40.000Z", false, "2026-06-01T00:00:01.000000Z")).unwrap();
    w.worker();
    let flow = |w: &W| -> serde_json::Value { serde_json::from_str::<serde_json::Value>(&std::fs::read_to_string(w.home().join("sessions/s1/analysis.json")).unwrap()).unwrap()["flow"].clone() };
    assert_eq!(flow(&w)["until"], 2);
    let before = w.calls();
    // 옛 시각(첫 턴만 끝난 때)의 .job과 지금 시각의 .json이 함께 있다
    std::fs::write(w.home().join("queue/s1.job"), item("2026-01-01T00:00:20.000Z", true, "2026-06-01T00:00:02.000000Z")).unwrap();
    std::fs::write(w.home().join("queue/s1.json"), item("2026-01-01T00:00:40.000Z", false, "2026-06-01T00:00:03.000000Z")).unwrap();
    w.worker();
    assert_eq!(flow(&w)["until"], 2);
    assert!(w.calls() - before <= 1, "흐름을 처음부터 다시 만들지 않는다: 호출 {}번", w.calls() - before);
    assert!(!w.home().join("queue/s1.job").exists() && !w.home().join("queue/s1.json").exists());
}

// 이미 더 최신 응답까지 분석했으면 지난 요청은 맡지 않고 버린다 (force여도: build가 남긴 옛 시각 요청)
#[test]
fn a_request_older_than_the_analysis_is_dropped() {
    let w = W::new("stale");
    two_turns(&w);
    std::fs::write(w.home().join("queue/s1.json"), item(&w, "2026-01-01T00:00:40.000Z", false, "2026-06-01T00:00:01.000000Z")).unwrap();
    w.worker();
    assert_eq!(flow(&w)["until"], 2);
    let before = w.calls();
    std::fs::write(w.home().join("queue/s1.job"), item(&w, "2026-01-01T00:00:20.000Z", true, "2026-06-01T00:00:02.000000Z")).unwrap();
    w.worker();
    assert_eq!(w.calls(), before, "지난 요청으로 흐름을 다시 만들지 않는다");
    assert_eq!(flow(&w)["until"], 2);
    assert!(!w.home().join("queue/s1.job").exists());
}

// 두 파일을 합친 요청은 옛 분석기가 읽지 않는 .job에만 남는다 (살아 있는 다른 분석기가 맡고 있어 이 분석기는 맡지 않음)
#[test]
fn merged_requests_stay_in_the_job_file_only() {
    let w = W::new("merge");
    two_turns(&w);
    std::fs::write(w.home().join("queue/s1.job"), item(&w, "2026-01-01T00:00:20.000Z", true, "2026-06-01T00:00:02.000000Z")).unwrap();
    std::fs::write(w.home().join("queue/s1.json"), item(&w, "2026-01-01T00:00:40.000Z", false, "2026-06-01T00:00:03.000000Z")).unwrap();
    std::fs::write(w.home().join("queue/s1.claim"), std::process::id().to_string()).unwrap();
    w.worker();
    assert_eq!(w.calls(), 0);
    assert!(!w.home().join("queue/s1.json").exists());
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(w.home().join("queue/s1.job")).unwrap()).unwrap();
    assert_eq!((v["source_ts"].as_str(), v["force"].as_bool(), v["queued_at"].as_str()),
               (Some("2026-01-01T00:00:40.000Z"), Some(true), Some("2026-06-01T00:00:02.000000Z")));
}

fn two_turns(w: &W) {
    std::fs::write(w.dir.join("s1.jsonl"), concat!(
        r#"{"type": "user", "message": {"role": "user", "content": "기능을 고쳐줘"}, "timestamp": "2026-01-01T00:00:10.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "기능을 고쳤습니다."}]}, "timestamp": "2026-01-01T00:00:20.000Z"}"#, "\n",
        r#"{"type": "user", "message": {"role": "user", "content": "문서도 고쳐줘"}, "timestamp": "2026-01-01T00:00:30.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "문서도 고쳤습니다."}]}, "timestamp": "2026-01-01T00:00:40.000Z"}"#, "\n")).unwrap();
}

fn item(w: &W, ts: &str, force: bool, q: &str) -> String {
    serde_json::json!({"session_id": "s1", "transcript_path": w.dir.join("s1.jsonl"), "source_ts": ts, "force": force, "queued_at": q, "by": "hook"}).to_string()
}

fn flow(w: &W) -> serde_json::Value {
    serde_json::from_str::<serde_json::Value>(&std::fs::read_to_string(w.home().join("sessions/s1/analysis.json")).unwrap()).unwrap()["flow"].clone()
}

// 백그라운드 작업 알림 뒤에 온 답 (요구 이력 101, #6): 알림은 턴을 닫지 않으므로 뒤의 답이 마지막 턴의 응답을 늘리고,
// 다음 Stop 요청 때 그 턴을 다시 분석한다 (요구 이력 64). 예전에는 답이 버려져 다시 분석하지 않았다
#[test]
fn an_answer_after_a_task_notification_gets_the_last_turn_analyzed_again() {
    let w = W::new("tasknote");
    let first = concat!(
        r#"{"type": "user", "message": {"role": "user", "content": "테스트 돌려서 결과 알려줘"}, "timestamp": "2026-01-01T00:00:10.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "백그라운드로 돌렸습니다. 끝나면 알려드릴게요"}]}, "timestamp": "2026-01-01T00:00:20.000Z"}"#, "\n");
    std::fs::write(w.dir.join("s1.jsonl"), first).unwrap();
    std::fs::write(w.home().join("queue/s1.json"), item(&w, "2026-01-01T00:00:20.000Z", false, "2026-06-01T00:00:01.000000Z")).unwrap();
    w.worker();
    assert_eq!(flow(&w)["until"], 1);
    let before = w.calls();
    let resp = |w: &W| flow(w)["steps"][0]["resp"].clone();
    let resp_before = resp(&w);
    std::fs::write(w.dir.join("s1.jsonl"), format!("{first}{}", concat!(
        r#"{"type": "user", "origin": {"kind": "task-notification", "producer": "session-task"}, "message": {"role": "user", "content": "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n</task-notification>"}, "timestamp": "2026-01-01T00:01:00.000Z"}"#, "\n",
        r#"{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "테스트 94개 모두 통과했습니다"}]}, "timestamp": "2026-01-01T00:01:05.000Z"}"#, "\n"))).unwrap();
    std::fs::write(w.home().join("queue/s1.json"), item(&w, "2026-01-01T00:01:05.000Z", false, "2026-06-01T00:00:02.000000Z")).unwrap();
    w.worker();
    assert!(w.calls() > before, "늘어난 마지막 턴을 다시 분석한다");
    assert_eq!(flow(&w)["until"], 1, "알림은 새 턴이 아니다");
    assert_ne!(resp(&w), resp_before, "다시 분석한 단계는 늘어난 응답을 본 것으로 적힌다");
}
