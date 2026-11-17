//! 분석 언어 (요구 이력 76, BUILD_PLAN §4.14): 세션마다 처음 분석할 때 정해 흐름에 남기고, ko면 지금과 한 글자도 다르지 않게,
//! 다른 언어면 프롬프트 끝에 출력 언어 블록을 붙이고 claude -p의 language 설정을 그 언어로 덮어쓴다.

use nunchi_engine::{flow, worker};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::process::{Command, Stdio};

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");
const FAKE: &str = env!("CARGO_BIN_EXE_fake-claude");

fn tmp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("nunchi-lang-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn user(text: &str, ts: &str) -> Value {
    json!({"type": "user", "timestamp": ts, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}})
}

fn answer(text: &str, ts: &str) -> Value {
    json!({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}})
}

fn two_turns() -> Vec<Value> {
    vec![user("설정 키 이름을 mod_language로 바꿔줘", "2026-11-17T01:00:00.000Z"), answer("키 이름을 바꿨습니다. 테스트도 통과했습니다.", "2026-11-17T01:00:10.000Z"),
         user("안내 문서에도 그 키를 적어줘", "2026-11-17T01:02:00.000Z"), answer("안내 문서에 적었습니다. 영문과 한글 둘 다 맞췄습니다.", "2026-11-17T01:02:10.000Z")]
}

struct Run {
    d: PathBuf,
}

impl Run {
    fn new(name: &str, rows: &[Value], want: Value) -> Run {
        let d = tmp(name);
        for p in ["home/sessions/s1", "fakebin", "fake"] {
            std::fs::create_dir_all(d.join(p)).unwrap();
        }
        std::os::unix::fs::symlink(FAKE, d.join("fakebin/claude")).unwrap();
        let r = Run { d };
        r.transcript(rows);
        std::fs::write(r.d.join("home/sessions/s1/want"), want.to_string()).unwrap();
        r
    }
    fn transcript(&self, rows: &[Value]) {
        std::fs::write(self.d.join("t.jsonl"), rows.iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
    }
    fn analyze(&self, ts: &str) {
        worker::enqueue(&self.d.join("home"), "s1", &self.d.join("t.jsonl").to_string_lossy(), ts, false, "hook").unwrap();
        let ok = Command::new(ENGINE).args(["worker", "--home"]).arg(self.d.join("home"))
            .env("PATH", format!("{}:{}", self.d.join("fakebin").display(), std::env::var("PATH").unwrap()))
            .env("CONTROL_TUI_REPLY_WAIT", "0").env("FAKE_CLAUDE_STATE", self.d.join("fake"))
            .env_remove("FAKE_CLAUDE_SCRIPT").env_remove("CONTROL_TUI_ANALYZER")
            .stdin(Stdio::null()).status().unwrap().success();
        assert!(ok);
    }
    fn flow(&self) -> Value {
        let v: Value = serde_json::from_str(&std::fs::read_to_string(self.d.join("home/sessions/s1/analysis.json")).unwrap()).unwrap();
        v["flow"].clone()
    }
    fn settings_arg(&self) -> Value {
        let call: Value = serde_json::from_str(&std::fs::read_to_string(self.d.join("fake/last_call.json")).unwrap()).unwrap();
        let args: Vec<&str> = call["args"].as_array().unwrap().iter().map(|a| a.as_str().unwrap()).collect();
        let i = args.iter().position(|a| *a == "--settings").expect("--settings 없음");
        serde_json::from_str(args[i + 1]).unwrap()
    }
    fn prompt(&self) -> String {
        std::fs::read_to_string(self.d.join("fake/last_prompt.txt")).unwrap_or_default()
    }
}

impl Drop for Run {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.d);
    }
}

#[test]
fn language_values_are_cleaned_and_ko_is_never_written() {
    assert_eq!(flow::empty_in("ko").get("lang"), None);
    assert_eq!(flow::empty_in("").get("lang"), None);
    assert_eq!(flow::empty_in(" EN ")["lang"], "en");
    assert_eq!(flow::empty_in("Japanese")["lang"], "japanese");
    assert_eq!(flow::lang_of(&flow::empty()), "ko");
    assert_eq!(flow::clean_lang("ja\"pan\\ese\n"), "japanese");
    assert_eq!(flow::clean_lang(&"x".repeat(80)).len(), 40);
    assert_eq!(flow::settings_language("ko"), "한국어");
    assert_eq!(flow::settings_language("en"), "English");
    assert_eq!(flow::settings_language("japanese"), "japanese");
}

#[test]
fn a_korean_session_keeps_todays_prompt_and_says_korean_to_claude() {
    let r = Run::new("ko", &two_turns(), json!({"on": true}));
    r.analyze("2026-11-17T01:02:10.500Z");
    let f = r.flow();
    assert_eq!(f["until"], 2);
    assert_eq!(f.get("lang"), None, "ko 흐름에는 lang 키를 적지 않는다");
    assert!(!r.prompt().contains("=== 출력 언어 ==="));
    assert_eq!(r.settings_arg(), json!({"language": "한국어"}));
}

#[test]
fn an_english_session_adds_the_output_block_and_keeps_its_language() {
    let r = Run::new("en", &two_turns(), json!({"on": true, "lang": "en"}));
    r.analyze("2026-11-17T01:02:10.500Z");
    let f = r.flow();
    assert_eq!(f["until"], 2);
    assert_eq!(f["lang"], "en", "두 턴을 지나도 언어가 남는다 (첫 턴의 빈 흐름 경로 포함)");
    assert_eq!(f["prev"]["lang"], "en", "다시 적기(rewind)용 앞 흐름에도 남는다");
    let p = r.prompt();
    assert!(p.contains("=== 출력 언어 ===") && p.contains("English로 쓴다"), "{p}");
    assert!(p.trim_end().ends_with("자 안."), "블록은 맨 끝");
    assert_eq!(r.settings_arg(), json!({"language": "English"}));
    let steps = f["steps"].as_array().unwrap();
    assert!(steps.iter().all(|s| s.get("fallback").is_none()), "가짜 claude가 블록을 응답으로 읽지 않는다: {steps:?}");
}

#[test]
fn without_a_language_in_want_the_session_lang_file_decides() {
    let r = Run::new("file", &two_turns()[..2], json!({"on": true}));
    std::fs::write(r.d.join("home/sessions/s1/lang"), "japanese\n").unwrap();
    r.analyze("2026-11-17T01:00:10.500Z");
    assert_eq!(r.flow()["lang"], "japanese");
    assert!(r.prompt().contains("japanese로 쓴다"));
    assert_eq!(r.settings_arg(), json!({"language": "japanese"}));
}

#[test]
fn a_session_already_analyzed_keeps_its_language_when_the_choice_changes() {
    let rows = two_turns();
    let r = Run::new("fixed", &rows[..2], json!({"on": true}));
    r.analyze("2026-11-17T01:00:10.500Z");
    assert_eq!(r.flow()["until"], 1);
    std::fs::write(r.d.join("home/sessions/s1/want"), json!({"on": true, "lang": "en"}).to_string()).unwrap();
    r.transcript(&rows);
    r.analyze("2026-11-17T01:02:10.500Z");
    let f = r.flow();
    assert_eq!(f["until"], 2);
    assert_eq!(f.get("lang"), None, "한 세션 안에서 언어가 섞이지 않는다");
    assert_eq!(r.settings_arg(), json!({"language": "한국어"}));
}

fn parsed_title(lang: &str, title: &str) -> String {
    let d = tmp(&format!("cut-{lang}"));
    let t = d.join("t.jsonl");
    std::fs::write(&t, [user("설정 키 이름을 mod_language로 바꿔줘", "2026-11-17T01:00:00.000Z"), answer("키 이름을 바꿨습니다. 테스트도 통과했습니다.", "2026-11-17T01:00:10.000Z")]
        .iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
    let out = json!({"turn": {"index": 1, "label": "확정", "summary": "rename", "quote": "설정 키 이름을 mod_language로", "agent_summary": "renamed",
                              "agent_quote": "키 이름을 바꿨습니다", "title": title, "decision": "rename the key"},
                     "topic_shift": false, "current_goal": "rename the key", "goal_turn": 1, "goal_quote": "설정 키 이름을 mod_language로",
                     "first_goal": "rename the key", "digest": "x".repeat(300)}).to_string();
    let case = json!({"flow": flow::empty_in(lang), "transcript": t, "until": "", "turn": 1, "outputs": [out]});
    let mut child = Command::new(ENGINE).args(["dev", "flow"]).stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
    std::io::Write::write_all(child.stdin.as_mut().unwrap(), (case.to_string() + "\n").as_bytes()).unwrap();
    let res: Value = serde_json::from_slice(&child.wait_with_output().unwrap().stdout).unwrap();
    let _ = std::fs::remove_dir_all(&d);
    let step = &res["parse"]["step"];
    assert!(step.is_object(), "{res}");
    format!("{}|{}", step["title"].as_str().unwrap().chars().count(), step["digest"].as_str().unwrap().chars().count())
}

#[test]
fn titles_and_digests_get_more_room_outside_korean() {
    let long = "Agreed to rename the setting key everywhere";
    assert_eq!(parsed_title("ko", long), "16|90");
    assert_eq!(parsed_title("en", long), "32|180");
}

