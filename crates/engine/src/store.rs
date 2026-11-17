//! 관제 홈의 파일들: 설정, 분석 결과, 분석 상태 (control_tui/settings.py, analyzer.py의 파일 부분을 옮김).

use crate::{clock, py};
use serde_json::{Map, Value};
use std::path::{Path, PathBuf};

pub const FORMAT: i64 = 2;
pub const STATUS_FILE: &str = "analysis_status.json";

pub fn home_dir() -> PathBuf {
    match std::env::var_os("CONTROL_TUI_HOME") {
        Some(h) => PathBuf::from(h),
        None => PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".claude-control"),
    }
}

/// 파일을 JSON 사전으로. 없거나 깨졌거나 사전이 아니면 빈 사전 (`_read`)
pub fn read_obj(path: &Path) -> Map<String, Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// 쓰는 도중의 파일을 읽지 않도록 임시 파일에 쓰고 한 번에 바꾼다
fn replace(path: &Path, tmp: &Path, text: &str) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    std::fs::write(tmp, text)?;
    std::fs::rename(tmp, path)
}

/// `_write_json`: indent=2, 임시 이름은 확장자 .json을 .json.tmp로
pub fn write_json(path: &Path, v: &Value) -> std::io::Result<()> {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("x");
    let tmp_name = match name.rfind('.') {
        Some(i) if i > 0 => format!("{}.json.tmp", &name[..i]),
        _ => format!("{name}.json.tmp"),
    };
    replace(path, &path.with_file_name(tmp_name), &py::dumps_indent(v))
}

/// 대기열 파일 쓰기 (`worker._write`): 한 줄 JSON, 임시 이름은 <이름>.<pid>.tmp
pub fn write_compact(path: &Path, v: &Value) -> std::io::Result<()> {
    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("x");
    replace(path, &path.with_file_name(format!("{name}.{}.tmp", std::process::id())), &py::dumps(v))
}

// ---------- 설정 ----------

pub struct Settings {
    pub analyze_model: String,
    pub analyze_workers: i64,
}

/// config.json (settings.load + normalized에서 엔진이 쓰는 것만)
pub fn load_settings(home: &Path) -> Settings {
    let data = std::fs::read_to_string(home.join("config.json")).ok().and_then(|t| serde_json::from_str::<Value>(&t).ok());
    let data = match data {
        Some(Value::Object(o)) => o,
        _ => Map::new(),
    };
    let int_in = |key: &str, default: i64, lo: i64, hi: i64| match data.get(key) {
        None => default,
        Some(v) => py::int_of(v).map(|n| n.clamp(lo, hi)).unwrap_or(default),
    };
    Settings {
        analyze_model: py::strip(&py::str_or_empty(data.get("analyze_model"))).to_string(),
        analyze_workers: int_in("analyze_workers", 1, 1, 2),
    }
}

// ---------- 분석 결과와 상태 ----------

/// 형식이 옛것(2 미만)이면 없는 것으로 본다
pub fn read_analysis(dir: &Path) -> Option<Value> {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(dir.join("analysis.json")).ok()?).ok()?;
    let fmt = match py::get(&v, "format") {
        None => 1,
        Some(x) => py::int_of(x).unwrap_or(1),
    };
    if !v.is_object() || fmt < FORMAT {
        return None;
    }
    Some(v)
}

/// state: queued·running·idle·failed. 쓰기에 실패해도 분석은 이어 간다
pub fn write_status(dir: &Path, state: &str, turn: i64, extra: &[(&str, Value)]) {
    let mut data = Map::new();
    data.insert("state".into(), Value::from(state));
    data.insert("turn".into(), Value::from(turn));
    data.insert("at".into(), Value::from(clock::now_us()));
    data.insert("pid".into(), Value::from(std::process::id()));
    for (k, v) in extra {
        if !(v.is_null() || v == &Value::from("")) {
            data.insert((*k).into(), v.clone());
        }
    }
    let _ = write_json(&dir.join(STATUS_FILE), &Value::Object(data));
}

pub fn write_analysis(dir: &Path, result: Map<String, Value>, source_ts: &str, changes: Value, last_turn: i64) -> std::io::Result<()> {
    let mut payload = result;
    payload.insert("format".into(), Value::from(FORMAT));
    payload.insert("source_ts".into(), Value::from(source_ts));
    payload.insert("last_turn".into(), Value::from(last_turn));
    payload.insert("changes".into(), if py::truthy(&changes) { changes } else { Value::Object(Map::new()) });
    payload.insert("analyzed_at".into(), Value::from(clock::now_us()));
    write_json(&dir.join("analysis.json"), &Value::Object(payload))
}
