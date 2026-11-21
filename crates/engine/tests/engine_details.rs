//! 파이썬 엔진 단위 시험이 지키던 세부 동작 (요구 이력 68 R2: 그 시험들을 지우기 전에 옮김).
//! test_worker(대기열 합치기), test_analyzer_v2(claude 부르는 모양·설정·마지막 글 기다리기),
//! test_hooks(훅 속도), test_request_check(슬래시 명령 턴).

use nunchi_engine::{store, transcript, worker};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");
const FAKE: &str = env!("CARGO_BIN_EXE_fake-claude");

fn tmp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("nunchi-details-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_lines(path: &Path, rows: &[Value]) {
    std::fs::write(path, rows.iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
}

fn user(text: &str, ts: &str) -> Value {
    json!({"type": "user", "timestamp": ts, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}})
}

fn meta(text: &str, ts: &str) -> Value {
    json!({"type": "user", "timestamp": ts, "isMeta": true, "message": {"role": "user", "content": text}})
}

fn answer(text: &str, ts: &str) -> Value {
    json!({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}})
}

fn tool(ts: &str) -> Value {
    json!({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}})
}

// ---------- 대기열 ----------

#[test]
fn enqueue_merges_to_the_latest_answer_and_keeps_force() {
    let d = tmp("enqueue");
    worker::enqueue(&d, "s1", "/t.jsonl", "2026-11-16T00:00:02.000Z", true, "hook").unwrap();
    worker::enqueue(&d, "s1", "/t2.jsonl", "2026-11-16T00:00:01.000Z", false, "control").unwrap(); // 더 옛 응답은 덮지 않는다
    let v: Value = serde_json::from_str(&std::fs::read_to_string(d.join("queue/s1.job")).unwrap()).unwrap(); // 새 엔진의 요청은 옛 분석기가 읽지 않는 .job (요구 이력 93)
    assert_eq!((v["source_ts"].as_str(), v["transcript_path"].as_str(), v["force"].as_bool()),
               (Some("2026-11-16T00:00:02.000Z"), Some("/t.jsonl"), Some(true)));
    assert_eq!(v["by"], "control"); // 관제가 한 번이라도 넣었으면 관제 요청 (요구 이력 62)
    let _ = std::fs::remove_dir_all(&d);
}

// ---------- 설정 ----------

#[test]
fn settings_defaults_and_bad_values() {
    let d = tmp("settings");
    let s = store::load_settings(&d);
    assert_eq!((s.analyze_model.as_str(), s.analyze_workers), ("", 1));
    std::fs::write(d.join("config.json"), r#"{"analyze_model": " haiku ", "analyze_workers": "2", "unknown": 1}"#).unwrap();
    let s = store::load_settings(&d);
    assert_eq!((s.analyze_model.as_str(), s.analyze_workers), ("haiku", 2));
    std::fs::write(d.join("config.json"), r#"{"analyze_workers": 9}"#).unwrap();
    assert_eq!(store::load_settings(&d).analyze_workers, 2);
    std::fs::write(d.join("config.json"), r#"{"analyze_workers": "x"}"#).unwrap();
    assert_eq!(store::load_settings(&d).analyze_workers, 1);
    std::fs::write(d.join("config.json"), r#"{"analyze_model": "#).unwrap();
    assert_eq!(store::load_settings(&d).analyze_model, "");
    let _ = std::fs::remove_dir_all(&d);
}

// ---------- 분석기 ----------

struct Run {
    d: PathBuf,
}

impl Run {
    fn new(name: &str, rows: &[Value]) -> Run {
        let d = tmp(name);
        for p in ["home/sessions/s1", "fakebin", "fake"] {
            std::fs::create_dir_all(d.join(p)).unwrap();
        }
        std::os::unix::fs::symlink(FAKE, d.join("fakebin/claude")).unwrap();
        write_lines(&d.join("t.jsonl"), rows);
        std::fs::write(d.join("home/sessions/s1/want"), r#"{"on": true}"#).unwrap();
        worker::enqueue(&d.join("home"), "s1", &d.join("t.jsonl").to_string_lossy(), "2026-11-09T01:03:00.500Z", false, "hook").unwrap();
        Run { d }
    }
    fn worker(&self, reply_wait: &str) -> std::process::Child {
        Command::new(ENGINE).args(["worker", "--home"]).arg(self.d.join("home"))
            .env("PATH", format!("{}:{}", self.d.join("fakebin").display(), std::env::var("PATH").unwrap()))
            .env("CONTROL_TUI_REPLY_WAIT", reply_wait).env("FAKE_CLAUDE_STATE", self.d.join("fake"))
            .env_remove("FAKE_CLAUDE_SCRIPT").env_remove("CONTROL_TUI_ANALYZER")
            .stdin(Stdio::null()).spawn().unwrap()
    }
    fn first_prompt(&self) -> String {
        std::fs::read_to_string(self.d.join("fake/last_prompt.txt")).unwrap_or_default()
    }
}

impl Drop for Run {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.d);
    }
}

#[test]
fn claude_runs_with_tools_off_the_model_detached_and_unrecorded() {
    let r = Run::new("claude-args", &[user("기능을 고쳐줘", "2026-11-09T01:00:00.000Z"), answer("고쳤습니다", "2026-11-09T01:00:10.000Z")]);
    std::fs::write(r.d.join("home/config.json"), r#"{"analyze_model": " haiku "}"#).unwrap();
    assert!(r.worker("0").wait().unwrap().success());
    let call: Value = serde_json::from_str(&std::fs::read_to_string(r.d.join("fake/last_call.json")).unwrap()).unwrap();
    let args: Vec<&str> = call["args"].as_array().unwrap().iter().map(|a| a.as_str().unwrap()).collect();
    let after = |flag: &str| args.iter().position(|a| *a == flag).map(|i| args[i + 1]);
    assert_eq!(after("--tools"), Some("")); // 도구 모두 끔
    assert_eq!(after("--model"), Some("haiku"));
    assert_eq!(after("--output-format"), Some("json"));
    for flag in ["-p", "--no-session-persistence", "--disable-slash-commands", "--"] {
        assert!(args.contains(&flag), "{flag} 없음: {args:?}");
    }
    assert!(!args.contains(&"--disallowedTools"));
    assert_eq!(call["analyzer_env"], "1", "분석기 자신의 claude -p는 훅이 기록하지 않게 표시한다");
    assert_eq!(call["own_session"], true, "관제 패널의 터미널과 떼어 띄운다 (setsid)");
    assert_eq!(call["stdin_empty"], true);
}

#[test]
fn waits_for_the_last_text_written_after_stop() {
    let rows = [user("요청 1", "2026-11-09T01:00:00.000Z"), answer("응답 1", "2026-11-09T01:00:10.000Z"),
                user("요청 2", "2026-11-09T01:02:00.000Z"), tool("2026-11-09T01:02:10.000Z")];
    let r = Run::new("late-text", &rows);
    let mut child = r.worker("5");
    std::thread::sleep(Duration::from_millis(600)); // Claude Code가 마지막 글을 늦게 적는 사이
    let mut all = rows.to_vec();
    all.push(answer("응답 2", "2026-11-09T01:03:00.000Z"));
    write_lines(&r.d.join("t.jsonl"), &all);
    assert!(child.wait().unwrap().success());
    let p = r.first_prompt();
    assert!(p.contains("응답: 응답 2") || p.contains("응답 2"), "늦게 적힌 마지막 글이 프롬프트에 없음");
    assert!(!p.ends_with("응답: (없음)\n"));
}

#[test]
fn turn_without_text_goes_on_after_the_wait() {
    let rows = [user("요청 1", "2026-11-09T01:00:00.000Z"), tool("2026-11-09T01:00:10.000Z")];
    let r = Run::new("no-text", &rows);
    let t = Instant::now();
    assert!(r.worker("0.3").wait().unwrap().success());
    assert!(t.elapsed() < Duration::from_secs(5));
    assert!(r.first_prompt().ends_with("응답: (없음)\n"));
}

// ---------- 훅 ----------

#[test]
fn hook_is_fast() {
    let d = tmp("speed");
    let payload = json!({"session_id": "s1", "hook_event_name": "PreToolUse", "cwd": "/w", "transcript_path": "/none", "tool_name": "Read"}).to_string();
    let mut times = Vec::new();
    for _ in 0..15 {
        let t = Instant::now();
        let mut c = Command::new(ENGINE).arg("hook").env("CONTROL_TUI_HOME", &d).stdin(Stdio::piped()).spawn().unwrap();
        use std::io::Write;
        c.stdin.take().unwrap().write_all(payload.as_bytes()).unwrap();
        assert!(c.wait().unwrap().success());
        times.push(t.elapsed());
    }
    times.sort();
    // 목표 50ms (BUILD_PLAN §2.2). 공용 실행기에서도 흔들리지 않게 중앙값만 본다
    assert!(times[times.len() / 2] < Duration::from_millis(50), "중앙값 {:?}", times[times.len() / 2]);
    let _ = std::fs::remove_dir_all(&d);
}

// ---------- 대화 기록 (슬래시 명령, 요청 34) ----------

#[test]
fn command_with_args_becomes_a_turn_and_its_expansion_is_not_a_request() {
    let d = tmp("cmd-args");
    let tr = d.join("t.jsonl");
    write_lines(&tr, &[
        user("<command-message>design</command-message>\n<command-name>/design</command-name>\n<command-args>대화 화면을 고쳐줘</command-args>", "2026-11-10T00:00:00.000Z"),
        meta("`/design` was invoked: Call the Artifact tool …", "2026-11-10T00:00:01.000Z"),
        answer("시안을 만들었습니다", "2026-11-10T00:00:30.000Z"),
    ]);
    let turns = transcript::parse_turns(&tr, "").unwrap();
    assert_eq!(turns.iter().map(|t| t.request.as_str()).collect::<Vec<_>>(), vec!["/design 대화 화면을 고쳐줘"]);
    assert_eq!(turns[0].response, "시안을 만들었습니다");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn builtin_command_output_and_commands_without_args_are_not_turns() {
    let d = tmp("cmd-builtin");
    let tr = d.join("t.jsonl");
    write_lines(&tr, &[
        user("<command-name>/model</command-name>\n<command-message>model</command-message>\n<command-args>sonnet</command-args>", "2026-11-10T00:00:00.000Z"),
        user("<local-command-stdout>Set model to sonnet</local-command-stdout>", "2026-11-10T00:00:01.000Z"),
        user("<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>", "2026-11-10T00:00:02.000Z"),
        user("가격표 만들어줘", "2026-11-10T00:00:03.000Z"),
        answer("만들었습니다", "2026-11-10T00:00:30.000Z"),
    ]);
    let turns = transcript::parse_turns(&tr, "").unwrap();
    assert_eq!(turns.iter().map(|t| (t.index, t.request.as_str())).collect::<Vec<_>>(), vec![(1, "가격표 만들어줘")]);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn meta_before_the_reply_does_not_cut_the_turn() {
    let d = tmp("meta-before");
    let tr = d.join("t.jsonl");
    write_lines(&tr, &[
        user("이 레포를 적용할 수 있어?", "2026-11-10T00:00:00.000Z"),
        meta("시스템 안내 …", "2026-11-10T00:00:01.000Z"),
        answer("적용은 되지만 목적에는 맞지 않습니다", "2026-11-10T00:00:30.000Z"),
    ]);
    let turns = transcript::parse_turns(&tr, "").unwrap();
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0].response, "적용은 되지만 목적에는 맞지 않습니다");
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn skill_expansion_in_the_middle_of_a_reply_does_not_cut_the_turn() {
    let d = tmp("cmd-skill");
    let tr = d.join("t.jsonl");
    write_lines(&tr, &[
        user("테마를 정리해줘 /design", "2026-11-10T00:00:00.000Z"),
        answer("먼저 살펴봅니다", "2026-11-10T00:00:10.000Z"),
        meta("스킬 본문 …", "2026-11-10T00:00:11.000Z"),
        answer("캔버스를 만들었습니다", "2026-11-10T00:00:30.000Z"),
    ]);
    let turns = transcript::parse_turns(&tr, "").unwrap();
    assert_eq!(turns.len(), 1);
    assert!(turns[0].response.contains("캔버스를 만들었습니다"));
    let _ = std::fs::remove_dir_all(&d);
}
