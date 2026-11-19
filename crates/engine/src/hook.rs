//! 모든 Claude Code 훅이 부르는 기록기 (hooks/emit.py를 옮김. BUILD_PLAN §2.1, §2.2).
//!
//! - stdin JSON을 한 줄로 줄여 `<홈>/sessions/<세션>/events.jsonl`에 덧붙인다.
//! - 늘 0으로 끝난다. 실패는 errors.log에만. 세션을 막지 않는다.
//! - CONTROL_TUI_ANALYZER=1이면 아무것도 하지 않는다 (분석기 자신의 claude -p).
//! - 응답이 끝나면(Stop) 분석 대상 세션을 대기열에 넣고 분석기를 깨운다.

use crate::store::home_dir;
use crate::{clock, py, worker};
use serde_json::{Map, Value};
use std::io::{Read, Write};
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
use std::path::Path;

const TRUNC: usize = 500;
const KEYS: [&str; 8] = ["prompt", "tool_name", "tool_use_id", "notification_type", "trigger", "compact_summary", "source", "permission_mode"];

pub fn log_error(msg: &str) {
    let d = home_dir();
    let _ = std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&d);
    if let Ok(mut f) = std::fs::OpenOptions::new().append(true).create(true).open(d.join("errors.log")) {
        let _ = writeln!(f, "{} {msg}", clock::now_iso());
    }
}

/// 긴 값은 앞 500자로. 글이 아니면 JSON 글로 바꾼 뒤 자른다
fn cut(v: &Value) -> Value {
    let text = match v {
        Value::String(s) => s.clone(),
        other => py::dumps(other),
    };
    Value::from(py::take(&text, TRUNC))
}

fn build_record(payload: &Map<String, Value>) -> Map<String, Value> {
    let mut data = Map::new();
    // 도구는 이름과 호출 ID만 남긴다. 입력·결과·오류는 저장하지 않는다 (요구 이력 48)
    for key in KEYS {
        if let Some(v) = payload.get(key).filter(|v| !v.is_null()) {
            data.insert(key.into(), if key == "prompt" || key == "compact_summary" { cut(v) } else { v.clone() });
        }
    }
    let or_empty = |k: &str| payload.get(k).cloned().unwrap_or_else(|| Value::from(""));
    let mut rec = Map::new();
    rec.insert("ts".into(), Value::from(clock::now_ms()));
    rec.insert("session_id".into(), or_empty("session_id"));
    rec.insert("event".into(), or_empty("hook_event_name"));
    rec.insert("cwd".into(), or_empty("cwd"));
    rec.insert("transcript_path".into(), or_empty("transcript_path"));
    rec.insert("iterm_session_id".into(), Value::from(std::env::var("ITERM_SESSION_ID").unwrap_or_default()));
    rec.insert("data".into(), Value::Object(data));
    rec
}

/// /nunchi 표시: 켬 Some(true), 끔 Some(false), 없음 None (분석 코드를 읽지 않는 가벼운 판단)
fn want_state(path: &Path) -> Option<bool> {
    if !path.exists() {
        return None;
    }
    let v = std::fs::read_to_string(path).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok());
    Some(!matches!(v, Some(Value::Object(ref o)) if o.get("on") == Some(&Value::Bool(false))))
}

/// 응답이 끝나면 분석 대상 세션의 분석을 대기열에 넣고 분석기를 깨운다 (요구 이력 52·53·62)
fn request_analysis(rec: &Map<String, Value>) -> std::io::Result<()> {
    if rec.get("event") != Some(&Value::from("Stop")) || std::env::var("CONTROL_TUI_ANALYZE").as_deref() == Ok("0") {
        return Ok(());
    }
    let home = home_dir();
    let sid = py::str_of(&rec["session_id"]);
    let cfg = match std::fs::read_to_string(home.join("config.json")).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok()) {
        Some(Value::Object(o)) => o,
        _ => Map::new(),
    };
    let s = |k: &str, d: &str| cfg.get(k).cloned().unwrap_or_else(|| Value::from(d));
    if s("analyze_scope", "selected") == Value::from("off") || s("analyze_when", "auto") == Value::from("manual") {
        return Ok(());
    }
    let want = want_state(&home.join("sessions").join(&sid).join("want"));
    if want == Some(false) || (want.is_none() && cfg.get("analyze_scope") != Some(&Value::from("all"))) {
        return Ok(()); // /nunchi off로 끈 세션은 설정이 all이어도 넣지 않는다
    }
    let tp = rec.get("transcript_path").filter(|v| py::truthy(v)).map(py::str_of);
    let Some(tp) = tp else { return Ok(()) };
    worker::enqueue(&home, &sid, &tp, &py::str_of(&rec["ts"]), false, "hook")?;
    let workers = match cfg.get("analyze_workers") {
        None => 1,
        Some(v) => py::int_of(v).unwrap_or(1),
    };
    worker::wake(&home, workers);
    Ok(())
}

fn run() -> Result<(), String> {
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw).map_err(|e| format!("emit 실패: {e}"))?;
    let payload = if py::strip(&raw).is_empty() {
        Value::Object(Map::new())
    } else {
        serde_json::from_str(&raw).map_err(|e| format!("emit 실패: JSONDecodeError: {e}"))?
    };
    let Value::Object(payload) = payload else { return Err("emit 실패: AttributeError: 사전이 아닌 입력".into()) };
    if !payload.get("session_id").map(py::truthy).unwrap_or(false) {
        return Err("session_id 없음".into());
    }
    let rec = build_record(&payload);
    let session_dir = home_dir().join("sessions").join(py::str_of(&rec["session_id"]));
    let fail = |e: std::io::Error| format!("emit 실패: OSError: {e}");
    std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&session_dir).map_err(fail)?;
    let line = py::dumps(&Value::Object(rec.clone())) + "\n";
    let mut f = std::fs::OpenOptions::new().append(true).create(true).mode(0o600).open(session_dir.join("events.jsonl")).map_err(fail)?;
    f.write_all(line.as_bytes()).map_err(fail)?;
    // 압축 직전 기록 사본은 남기지 않는다 (요구 이력 95): Claude Code가 압축해도 기록 파일 앞부분을 지우지 않아
    // 압축 전 원문은 기록 파일에 그대로 있고, 사본을 읽는 곳도 없었다
    request_analysis(&rec).map_err(fail)?;
    Ok(())
}

/// 늘 0을 돌려준다
pub fn main() -> i32 {
    if std::env::var("CONTROL_TUI_ANALYZER").as_deref() == Ok("1") {
        return 0;
    }
    let t0 = std::time::Instant::now();
    if let Err(msg) = run() {
        log_error(&msg);
    }
    if std::env::var("CONTROL_TUI_TIMING").as_deref() == Ok("1") {
        log_error(&format!("elapsed_ms={:.1}", t0.elapsed().as_secs_f64() * 1000.0));
    }
    0
}
