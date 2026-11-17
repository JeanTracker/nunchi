//! 정답 시나리오 다시 돌리기 (`cargo test --features dev`).
//!
//! tests/scenarios/*.json의 단계를 러스트 엔진으로 돌리고, 관제 홈에 남은 파일을 tests/golden/*.json과 비교한다.
//! 정답은 지운 파이썬 엔진이 만든 결과다(옛 tests/test_conformance.py). 파이썬이 없어진 뒤에도 같은 동작을 지킨다.
//! 단계 실행과 자리표 바꾸기는 그 비교 시험과 같다.
//! 동작을 일부러 바꿨으면 NUNCHI_UPDATE_GOLDEN=1 cargo test로 정답을 다시 쓰고, 바뀐 내용을 diff로 확인한다.
#![cfg(feature = "dev")]

use nunchi_engine::{clock, py};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const ENGINE: &str = env!("CARGO_BIN_EXE_nunchi-engine");
const FAKE: &str = env!("CARGO_BIN_EXE_fake-claude");

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn transcript_lines(session: &str, turns: &[Value], cwd: &str) -> String {
    let base = 1_767_225_600i64; // 2026-01-01T00:00:00Z
    let mut out = String::new();
    let mut k = 0i64;
    fn rec(out: &mut String, k: &mut i64, base: i64, session: &str, cwd: &str, kind: &str, content: Value) {
        *k += 1;
        let ts = format!("{}.000Z", clock::stamp(base + *k * 10));
        let r = json!({"type": kind, "message": {"role": kind, "content": content}, "timestamp": ts,
                       "uuid": format!("u{k}"), "sessionId": session, "cwd": cwd});
        out.push_str(&py::dumps(&r));
        out.push('\n');
    }
    for turn in turns {
        rec(&mut out, &mut k, base, session, cwd, "user", turn["req"].clone());
        for item in turn["resp"].as_array().unwrap() {
            if let Some(text) = item.as_str() {
                rec(&mut out, &mut k, base, session, cwd, "assistant", json!([{"type": "text", "text": text}]));
            } else {
                let tid = format!("tu{k}");
                rec(&mut out, &mut k, base, session, cwd, "assistant", json!([{"type": "tool_use", "id": tid, "name": item["tool"], "input": {}}]));
                rec(&mut out, &mut k, base, session, cwd, "user", json!([{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]));
            }
        }
    }
    out
}

struct Bench {
    w: PathBuf,
    home: PathBuf,
    proj: PathBuf,
}

impl Bench {
    fn new(w: PathBuf, sc: &Value) -> Bench {
        let (home, proj) = (w.join("home"), w.join("proj"));
        for d in [home.clone(), proj.join("docs"), w.join("transcripts"), w.join("fakebin"), w.join("fake")] {
            std::fs::create_dir_all(d).unwrap();
        }
        std::os::unix::fs::symlink(FAKE, w.join("fakebin/claude")).unwrap();
        if let Some(docs) = sc["docs"].as_object() {
            for (name, text) in docs {
                std::fs::write(proj.join("docs").join(name), text.as_str().unwrap()).unwrap();
            }
        }
        let b = Bench { w, home, proj };
        b.write_fake(sc.get("fake").cloned().unwrap_or(json!({})));
        b
    }

    fn write_fake(&self, script: Value) {
        std::fs::write(self.w.join("fake/script.json"), py::dumps(&script)).unwrap();
    }

    fn cmd(&self, exe: &str, extra: &Map<String, Value>) -> Command {
        let mut c = Command::new(exe);
        for (k, _) in std::env::vars() {
            if k.starts_with("CONTROL_TUI_") || k.starts_with("FAKE_CLAUDE_") {
                c.env_remove(k);
            }
        }
        let path = format!("{}:{}", self.w.join("fakebin").display(), std::env::var("PATH").unwrap_or_default());
        c.env("PATH", path).env("CONTROL_TUI_HOME", &self.home).env("CONTROL_TUI_ANALYZE", "1").env("CONTROL_TUI_WORKER", "0")
            .env("CONTROL_TUI_RETRY_SECONDS", "1").env("CONTROL_TUI_REPLY_WAIT", "0.3").env("ITERM_SESSION_ID", "w0t0p0:FAKE")
            .env("FAKE_CLAUDE_SCRIPT", self.w.join("fake/script.json")).env("FAKE_CLAUDE_STATE", self.w.join("fake"));
        for (k, v) in extra {
            c.env(k, v.as_str().unwrap());
        }
        c
    }

    fn tpath(&self, s: &str) -> PathBuf {
        self.w.join("transcripts").join(format!("{s}.jsonl"))
    }

    fn hook(&self, stdin: &str, env: &Map<String, Value>) {
        use std::io::Write;
        let mut child = self.cmd(ENGINE, env).arg("hook").stdin(Stdio::piped()).stdout(Stdio::null()).spawn().unwrap();
        child.stdin.take().unwrap().write_all(stdin.as_bytes()).unwrap();
        assert!(child.wait().unwrap().success());
    }

    fn write(&self, rel: &str, text: &str) {
        let p = self.home.join(rel);
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(p, text).unwrap();
    }

    fn step(&self, st: &Value) {
        let (kind, a) = st.as_object().unwrap().iter().next().unwrap();
        let s = |k: &str| a[k].as_str().unwrap_or("").to_string();
        match kind.as_str() {
            "transcript" => std::fs::write(self.tpath(&s("session")), transcript_lines(&s("session"), a["turns"].as_array().unwrap(), &self.proj.to_string_lossy())).unwrap(),
            "want" => self.write(&format!("sessions/{}/want", s("session")), &py::dumps(&json!({"at": "2026-06-01T00:00:00Z", "by": "test", "on": a["on"]}))),
            "file" => self.write(&s("path"), &if a.get("text").is_some() { s("text") } else { py::dumps(&a["json"]) }),
            "config" => self.write("config.json", &py::dumps(a)),
            "fake" => self.write_fake(a.clone()),
            "queue" => self.write(&format!("queue/{}.json", s("session")), &py::dumps(&json!({
                "session_id": s("session"), "transcript_path": self.tpath(&s("session")).to_string_lossy(),
                "source_ts": "2026-06-01T00:00:00.000Z", "force": a["force"], "queued_at": "2026-06-01T00:00:00.000000Z", "by": a["by"]}))),
            "hook" => {
                let mut p = json!({"session_id": a["session"], "hook_event_name": a["event"], "cwd": self.proj.to_string_lossy(),
                                   "transcript_path": self.tpath(&s("session")).to_string_lossy()});
                if let Some(extra) = a["extra"].as_object() {
                    for (k, v) in extra {
                        p[k] = v.clone();
                    }
                }
                self.hook(&py::dumps(&p), &Map::new());
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
            "hook_raw" => self.hook(&s("stdin"), a["env"].as_object().unwrap_or(&Map::new())),
            "worker" => {
                let st = self.cmd(ENGINE, &Map::new()).args(["worker", "--home"]).arg(&self.home).status().unwrap();
                assert!(st.success());
            }
            other => panic!("모르는 단계 {other}"),
        }
    }
}

fn is_iso(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() < 19 || !s.is_char_boundary(19) {
        return false;
    }
    let digit = |i: usize| b[i].is_ascii_digit();
    let shape = (0..4).all(digit) && b[4] == b'-' && digit(5) && digit(6) && b[7] == b'-' && digit(8) && digit(9)
        && b[10] == b'T' && digit(11) && digit(12) && b[13] == b':' && digit(14) && digit(15) && b[16] == b':' && digit(17) && digit(18);
    if !shape {
        return false;
    }
    let mut rest = &s[19..];
    if let Some(r) = rest.strip_prefix('.') {
        let n = r.bytes().take_while(|c| c.is_ascii_digit()).count();
        if n == 0 {
            return false;
        }
        rest = &r[n..];
    }
    rest.is_empty() || rest == "Z" || (rest.len() == 6 && (rest.starts_with('+') || rest.starts_with('-')) && rest.as_bytes()[3] == b':'
        && [1, 2, 4, 5].iter().all(|&i| rest.as_bytes()[i].is_ascii_digit()))
}

struct Norm {
    w: String,
    names: HashMap<String, String>,
}

impl Norm {
    fn v(&mut self, v: &Value, key: &str) -> Value {
        match v {
            Value::Object(o) => Value::Object(o.iter().map(|(k, x)| (k.clone(), self.v(x, k))).collect()),
            Value::Array(a) => Value::Array(a.iter().map(|x| self.v(x, "")).collect()),
            _ if key == "pid" => json!("<pid>"),
            Value::String(s) => {
                if ["at", "since", "analyzed_at", "queued_at"].contains(&key) {
                    return json!("<time>");
                }
                if is_iso(s) && !s.starts_with("2026-01-01") && !s.starts_with("2026-06-01") {
                    let n = self.names.len() + 1;
                    return json!(self.names.entry(s.clone()).or_insert_with(|| format!("<ts{n}>")).clone());
                }
                json!(s.replace(&self.w, "<W>"))
            }
            other => other.clone(),
        }
    }
}

fn files(dir: &Path, out: &mut Vec<PathBuf>) {
    for e in std::fs::read_dir(dir).unwrap().flatten() {
        let p = e.path();
        if p.is_dir() { files(&p, out) } else { out.push(p) }
    }
}

fn snapshot(w: &Path) -> Value {
    let home = w.join("home");
    let mut all = Vec::new();
    files(&home, &mut all);
    // 파이썬 Path 정렬: 경로 조각끼리 비교
    all.sort_by(|a, b| a.components().map(|c| c.as_os_str().to_owned()).cmp(b.components().map(|c| c.as_os_str().to_owned())));
    let mut n = Norm { w: w.to_string_lossy().into_owned(), names: HashMap::new() };
    let mut out = Map::new();
    for p in all {
        let rel = p.strip_prefix(&home).unwrap().to_string_lossy().into_owned();
        let text = || std::fs::read_to_string(&p).unwrap();
        let name = p.file_name().unwrap().to_string_lossy().into_owned();
        let v = if name.ends_with(".lock") {
            json!("<lock>")
        } else if rel == "errors.log" {
            json!({"lines": py::splitlines(&text()).len()})
        } else if name == "events.jsonl" {
            Value::Array(py::splitlines(&text()).iter().map(|l| n.v(&serde_json::from_str(l).unwrap(), "")).collect())
        } else if name.ends_with(".json") || name == "want" {
            n.v(&serde_json::from_str(&text()).unwrap(), "")
        } else {
            n.v(&json!(text()), "")
        };
        out.insert(rel, v);
    }
    let log = w.join("fake/log");
    let calls: Vec<Value> = std::fs::read_to_string(log).map(|t| py::splitlines(&t).iter().map(|l| json!(l)).collect()).unwrap_or_default();
    json!({"files": out, "claude_calls": calls})
}

#[test]
fn engine_matches_golden_scenarios() {
    let scen = root().join("tests/scenarios");
    let mut names: Vec<String> = std::fs::read_dir(&scen).unwrap().flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned()).filter(|n| n.ends_with(".json")).collect();
    names.sort();
    assert!(names.len() >= 10, "시나리오가 너무 적다");
    let tmp = std::env::temp_dir().join(format!("nunchi-golden-{}", std::process::id()));
    let mut failed = Vec::new();
    for name in &names {
        let sc: Value = serde_json::from_str(&std::fs::read_to_string(scen.join(name)).unwrap()).unwrap();
        let w = tmp.join(name.trim_end_matches(".json"));
        let b = Bench::new(w.clone(), &sc);
        for st in sc["steps"].as_array().unwrap() {
            b.step(st);
        }
        let got = snapshot(&w);
        let gpath = root().join("tests/golden").join(name);
        if std::env::var("NUNCHI_UPDATE_GOLDEN").as_deref() == Ok("1") {
            std::fs::write(&gpath, py::dumps_indent_n(&got, 1) + "\n").unwrap();
        }
        let golden: Value = serde_json::from_str(&std::fs::read_to_string(&gpath).unwrap()).unwrap();
        // 키 순서까지 같아야 한다
        if py::dumps(&got) != py::dumps(&golden) {
            eprintln!("--- {name}\n got:    {}\n golden: {}", py::take(&py::dumps(&got), 3000), py::take(&py::dumps(&golden), 3000));
            failed.push(name.clone());
        }
    }
    let _ = std::fs::remove_dir_all(&tmp);
    assert!(failed.is_empty(), "정답과 다른 시나리오: {failed:?}");
}
