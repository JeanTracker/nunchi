use nunchi_engine::{codex::EVENTS, transcript::parse_turns};
use serde_json::{json, Value};
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");

struct Probe(PathBuf);

impl Probe {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!("nunchi-codex-test-{}", std::process::id()));
        for run in ["run-a", "run-b"] {
            std::fs::create_dir_all(path.join(run)).unwrap();
        }
        Self(path)
    }

    fn event(&self, run: &str, payload: Value, analyzer: bool) {
        let mut command = Command::new(ENGINE);
        command
            .arg("codex-hook")
            .env("CONTROL_TUI_HOME", self.0.join("home"))
            .env("CONTROL_TUI_ANALYZE", "1")
            .env("CONTROL_TUI_WORKER", "0")
            .env("CONTROL_TUI_ANALYZER", if analyzer { "1" } else { "0" })
            .env_remove("CONTROL_TUI_CODEX_RUN");
        if !run.is_empty() {
            command.env("CONTROL_TUI_CODEX_RUN", self.0.join(run));
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .take()
            .unwrap()
            .write_all(payload.to_string().as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        assert!(out.status.success() && out.stdout.is_empty());
    }

    fn log(&self, sid: &str) -> PathBuf {
        self.0.join("home/sessions").join(sid).join(EVENTS)
    }
}

impl Drop for Probe {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn binds_each_launch_and_analyzes_only_its_completed_pairs_once() {
    let probe = Probe::new();
    let start = |sid: &str| json!({"session_id": sid, "hook_event_name": "SessionStart"});
    let prompt = |sid: &str, turn_id: &str| {
        json!({"session_id": sid, "turn_id": turn_id, "hook_event_name": "UserPromptSubmit",
               "prompt": "SQLite로 해줘".repeat(60)})
    };
    let stop = |sid: &str, turn_id: &str, reply: &str| {
        json!({"session_id": sid, "turn_id": turn_id, "hook_event_name": "Stop",
               "last_assistant_message": reply})
    };
    probe.event("", start("unlaunched"), false);
    probe.event("run-a", start("analysis-child"), true);
    assert!(!probe.log("unlaunched").exists());
    assert!(!probe.log("analysis-child").exists());
    probe.event("run-a", start("a"), false);
    probe.event("run-b", start("b"), false);
    probe.event("run-a", prompt("a", "interrupted"), false);
    probe.event("run-a", stop("a", "interrupted", ""), false);
    probe.event("run-a", prompt("a", "completed"), false);
    probe.event("run-a", stop("b", "completed", "wrong session"), false);
    probe.event("run-a", stop("a", "completed", "SQLite 확인"), false);
    probe.event("run-a", stop("a", "completed", "duplicate"), false);
    probe.event("run-a", start("a"), false); // Resume binds the saved session again.
    probe.event("run-a", prompt("a", "next"), false);
    probe.event("run-a", stop("a", "next", "다음 답"), false);
    let a = parse_turns(&probe.log("a"), "").unwrap();
    assert_eq!(a.len(), 2);
    assert_eq!(a[0].request, "SQLite로 해줘".repeat(60));
    assert_eq!(a[0].final_response, "SQLite 확인");
    assert_eq!(a[1].index, 2);
    assert!(parse_turns(&probe.log("b"), "").unwrap().is_empty());
    assert_eq!(
        std::fs::read_to_string(probe.0.join("run-a/session-id")).unwrap(),
        "a\n"
    );
    assert_eq!(
        std::fs::read_to_string(probe.0.join("run-b/session-id")).unwrap(),
        "b\n"
    );
    assert!(probe.0.join("home/queue/a.job").exists());
    assert!(!probe.0.join("home/queue/b.job").exists());
    let stops = std::fs::read_to_string(probe.log("a"))
        .unwrap()
        .lines()
        .filter(|line| line.contains(r#""event":"Stop""#))
        .count();
    assert_eq!(stops, 2);
}
