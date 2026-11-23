//! Codex 세션의 분석 경로 (`cargo test --features dev`): 가짜 `codex exec`로 분석기가 Codex를 부르고,
//! 답이 JSON이 아니면 대체 단계를 적지 않고 실패로 남기며, 모델이 정해지지 않았으면 부르지 않는다.
#![cfg(feature = "dev")]

use nunchi_engine::codex::EVENTS;
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::Command;

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");
const FAKE: &str = env!("CARGO_BIN_EXE_fake-claude");

struct W {
    dir: PathBuf,
}

impl W {
    /// provider: 세션의 분석 설정 (codex-analysis-provider.json), script: 가짜 답 모드
    fn new(name: &str, provider: Value, script: &str) -> W {
        let dir = std::env::temp_dir().join(format!("nunchi-codex-analysis-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        for d in ["home/queue", "home/sessions/s1", "fakebin", "fake"] {
            std::fs::create_dir_all(dir.join(d)).unwrap();
        }
        // codex만 둔다: Claude로 잘못 가면 claude를 찾지 못해 실패한다
        std::os::unix::fs::symlink(FAKE, dir.join("fakebin/codex")).unwrap();
        let s = dir.join("home/sessions/s1");
        let rows = [
            json!({"ts": "2026-01-01T00:00:10.000000Z", "session_id": "s1", "event": "SessionStart", "data": {}}),
            json!({"ts": "2026-01-01T00:00:11.000000Z", "session_id": "s1", "event": "UserPromptSubmit", "data": {"turn_id": "t1", "prompt": "기능을 고쳐줘"}}),
            json!({"ts": "2026-01-01T00:00:20.000000Z", "session_id": "s1", "event": "Stop", "data": {"turn_id": "t1", "last_assistant_message": "기능을 고쳤습니다."}}),
        ];
        std::fs::write(s.join(EVENTS), rows.iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
        std::fs::write(s.join("codex-analysis-provider.json"), provider.to_string()).unwrap();
        std::fs::write(s.join("want"), r#"{"on": true}"#).unwrap();
        std::fs::write(dir.join("script.json"), json!({"default": script}).to_string()).unwrap();
        let item = json!({"session_id": "s1", "transcript_path": s.join(EVENTS), "source_ts": "2026-01-01T00:00:20.000000Z",
                          "force": false, "queued_at": "2026-01-01T00:00:21.000000Z", "by": "hook"});
        std::fs::write(dir.join("home/queue/s1.json"), item.to_string()).unwrap();
        W { dir }
    }
    fn worker(&self) {
        let ok = Command::new(ENGINE).args(["worker", "--home"]).arg(self.dir.join("home"))
            .env("PATH", format!("{}:/usr/bin:/bin", self.dir.join("fakebin").display()))
            .env("CONTROL_TUI_HOME", self.dir.join("home")).env("CONTROL_TUI_REPLY_WAIT", "0").env("CONTROL_TUI_RETRY_SECONDS", "0").env_remove("CONTROL_TUI_WORKER")
            .env("FAKE_CLAUDE_STATE", self.dir.join("fake")).env("FAKE_CLAUDE_SCRIPT", self.dir.join("script.json"))
            .env_remove("CONTROL_TUI_ANALYZER").env_remove("CONTROL_TUI_CODEX_MODEL").env_remove("CONTROL_TUI_CODEX_PROVIDER")
            .status().unwrap().success();
        assert!(ok);
    }
    fn read(&self, name: &str) -> Value {
        std::fs::read_to_string(self.dir.join("home/sessions/s1").join(name)).ok()
            .and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(Value::Null)
    }
    fn calls(&self) -> usize {
        std::fs::read_to_string(self.dir.join("fake/log")).map(|t| t.lines().count()).unwrap_or(0)
    }
}

impl Drop for W {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

fn steps(a: &Value) -> Vec<Value> {
    a["flow"]["steps"].as_array().cloned().unwrap_or_default()
}

#[test]
fn a_codex_session_is_analyzed_by_codex_exec_with_its_model() {
    let w = W::new("ok", json!({"provider": "codex", "model": "test-model"}), "ok");
    w.worker();
    let a = w.read("analysis.json");
    let st = steps(&a);
    assert_eq!(st.len(), 1);
    assert_eq!(st[0]["index"], 1);
    assert!(st[0].get("fallback").is_none(), "{st:?}");
    assert_eq!(st[0]["quote"], "기능을 고쳐줘");
    let call = w.read("../../../fake/last_call.json");
    let args: Vec<String> = call["args"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
    assert_eq!(args[0], "exec");
    let m = args.iter().position(|x| x == "--model").unwrap();
    assert_eq!(args[m + 1], "test-model");
    assert!(args.iter().any(|x| x == "--output-last-message"));
    assert_eq!(call["analyzer_env"], "1");                       // 분석기 자신의 codex는 훅이 기록하지 않는다
    assert_eq!(w.read("analysis_status.json")["state"], "idle");
}

#[test]
fn output_that_is_not_json_fails_instead_of_writing_a_fallback_step() {
    let w = W::new("garbage", json!({"provider": "codex", "model": "test-model"}), "garbage");
    w.worker();
    assert!(steps(&w.read("analysis.json")).is_empty());
    let status = w.read("analysis_status.json");
    assert_eq!((status["state"].as_str(), status["error"].as_str()), (Some("failed"), Some("output")));
    assert!(w.calls() >= 2);                                     // 한 턴에 두 번 묻고 나서 실패한다
}

#[test]
fn a_codex_session_without_a_model_is_not_analyzed() {
    let w = W::new("nomodel", json!({"provider": "codex", "model": ""}), "ok");
    w.worker();
    let status = w.read("analysis_status.json");
    assert_eq!((status["state"].as_str(), status["error"].as_str()), (Some("failed"), Some("codex-model-missing")));
    assert_eq!(w.calls(), 0);
}
