//! 플러그인 구성과 훅 입구 hooks/emit.sh (요구 이력 63·67·69·70, BUILD_PLAN §4.12·§4.13).
//! 예전 파이썬 시험 tests/test_emit_sh.py·test_plugin_engine.py를 옮겼다.
//!
//! emit.sh는 저장소의 것을 임시 플러그인 폴더로 복사해서 돌린다: 개발 중 빌드한 bin/nunchi-engine에 휩쓸리지 않게.
//! PATH는 비워 둔다 (sh는 /bin/sh 절대 경로로 부른다). 셸 내장 기능만으로 돌아야 한다.

use serde_json::{json, Value};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const EVENTS: [&str; 10] = ["SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                            "PostToolUseFailure", "Stop", "Notification", "PreCompact", "PostCompact"];

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize().unwrap()
}

fn json_file(rel: &str) -> Value {
    serde_json::from_str(&std::fs::read_to_string(repo().join(rel)).unwrap()).unwrap()
}

#[test]
fn plugin_hooks_cover_every_event_once_and_point_at_files_that_exist() {
    let plugin = json_file(".claude-plugin/plugin.json");
    let hooks = json_file("hooks/hooks.json");
    let market = json_file(".claude-plugin/marketplace.json");
    assert!(repo().join(plugin["types"].as_str().unwrap()).is_file());
    let modules: Vec<&str> = hooks["modules"].as_array().unwrap().iter().map(|m| m.as_str().unwrap()).collect();
    assert_eq!(modules.len(), 1);
    assert!(repo().join("hooks").join(modules[0]).is_file());
    let mut events: Vec<&str> = hooks["hooks"].as_object().unwrap().keys().map(String::as_str).collect();
    events.sort();
    let mut want = EVENTS.to_vec();
    want.sort();
    assert_eq!(events, want);
    for groups in hooks["hooks"].as_object().unwrap().values() {
        let cmds: Vec<&str> = groups.as_array().unwrap().iter()
            .flat_map(|g| g["hooks"].as_array().unwrap().iter().map(|h| h["command"].as_str().unwrap())).collect();
        assert_eq!(cmds, vec![r#"sh "${CLAUDE_PLUGIN_ROOT}/hooks/emit.sh""#]);
    }
    // 플러그인은 엔진 실행 파일이 함께 실린 배포용 브랜치에서 받는다 (요구 이력 69)
    let entries: Vec<(Value, Value)> = market["plugins"].as_array().unwrap().iter().map(|p| (p["name"].clone(), p["source"].clone())).collect();
    assert_eq!(entries, vec![(plugin["name"].clone(), json!({"source": "github", "repo": "JeanTracker/nunchi", "ref": "dist"}))]);
}

struct Plugin {
    dir: PathBuf,
}

impl Plugin {
    fn new(name: &str) -> Plugin {
        let dir = std::env::temp_dir().join(format!("nunchi-emitsh-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("hooks")).unwrap();
        std::fs::create_dir_all(dir.join("empty-path")).unwrap();
        std::fs::copy(repo().join("hooks/emit.sh"), dir.join("hooks/emit.sh")).unwrap();
        Plugin { dir }
    }
    fn engine(&self, body: &str) {
        std::fs::create_dir_all(self.dir.join("bin")).unwrap();
        let p = self.dir.join("bin/nunchi-engine");
        std::fs::write(&p, format!("#!/bin/sh\n{body}")).unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
    }
    fn run(&self, event: &str, spaced: bool) -> (i32, String, String) {
        let payload = json!({"session_id": "s1", "hook_event_name": event, "cwd": "/work/a", "transcript_path": "/none.jsonl"});
        let text = if spaced { serde_json::to_string_pretty(&payload).unwrap().replace('\n', " ") } else { payload.to_string() };
        let mut c = Command::new("/bin/sh").arg(self.dir.join("hooks/emit.sh")).env_clear().env("PATH", self.dir.join("empty-path"))
            .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn().unwrap();
        c.stdin.take().unwrap().write_all(text.as_bytes()).unwrap();
        let out = c.wait_with_output().unwrap();
        (out.status.code().unwrap_or(-1), String::from_utf8_lossy(&out.stdout).into(), String::from_utf8_lossy(&out.stderr).into())
    }
}

impl Drop for Plugin {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

#[test]
fn hands_over_to_the_engine() {
    let p = Plugin::new("hand");
    let called = p.dir.join("called");
    p.engine(&format!("[ \"$1\" = --version ] && exit 0\nread -r line\nprintf '%s|%s' \"$1\" \"$line\" > '{}'\n", called.display()));
    assert_eq!(p.run("Stop", false), (0, String::new(), String::new()));
    let got = std::fs::read_to_string(called).unwrap();
    assert!(got.starts_with("hook|{") && got.contains(r#""hook_event_name":"Stop""#), "{got}");
}

#[test]
fn engine_that_cannot_run_tells_once_at_session_start() {
    // 실행 권한이 있어도 --version에 답하지 못하면(다른 OS, 깨진 파일) exec하지 않는다 (요구 이력 69)
    for spaced in [false, true] {
        let p = Plugin::new(&format!("broken-{spaced}"));
        p.engine(&format!(": > '{}'\nexit 126\n", p.dir.join("ran").display()));
        let (code, out, err) = p.run("SessionStart", spaced);
        assert_eq!((code, err.as_str()), (0, ""));
        let v: Value = serde_json::from_str(&out).unwrap();
        let msg = v["systemMessage"].as_str().unwrap();
        assert!(msg.contains("실행하지 못해") && msg.contains("claude plugin update nunchi@nunchi"));
        assert_eq!(v["hookSpecificOutput"]["hookEventName"], "SessionStart");
        assert!(v["hookSpecificOutput"]["additionalContext"].as_str().unwrap().contains("Do not change anything unless the user agrees"));
    }
}

#[test]
fn missing_engine_tells_how_to_build_or_reinstall() {
    let p = Plugin::new("missing");
    let (_, out, _) = p.run("SessionStart", false);
    let v: Value = serde_json::from_str(&out).unwrap();
    let msg = v["systemMessage"].as_str().unwrap();
    assert!(msg.contains("없어") && msg.contains("scripts/build-engine.sh"));
    assert!(v["hookSpecificOutput"]["additionalContext"].as_str().unwrap().contains("Do not change anything unless the user agrees"));
}

#[test]
fn other_hooks_end_quietly_without_a_working_engine() {
    for with_engine in [false, true] {
        for event in ["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SessionEnd"] {
            let p = Plugin::new(&format!("quiet-{with_engine}-{event}"));
            if with_engine {
                p.engine("exit 1\n");
            }
            assert_eq!(p.run(event, false), (0, String::new(), String::new()), "{event} with_engine={with_engine}");
        }
    }
}
