//! Codex CLI 0.169.0 lifecycle hooks. The paired hooks supply the complete
//! user prompt and final reply without depending on the rollout file format.
use crate::{clock, hook, store, transcript::Turn};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs::OpenOptions;
use std::io::{self, Read, Write};
use std::os::unix::{
    fs::{DirBuilderExt, OpenOptionsExt},
    io::AsRawFd,
};
use std::path::Path;

pub const EVENTS: &str = "codex-events.jsonl";
const PROVIDER: &str = "codex-analysis-provider.json";

fn provider_from_env() -> Value {
    if std::env::var("CONTROL_TUI_CODEX_PROVIDER").as_deref() == Ok("claude") {
        return json!({"provider": "claude"});
    }
    let model = std::env::var("CONTROL_TUI_CODEX_MODEL").unwrap_or_default();
    json!({"provider": "codex", "model": model.trim()})
}

/// A session owns its provider so any worker sharing the queue can process it.
pub fn analysis_model(dir: &Path) -> Result<Option<String>, String> {
    if !dir.join(EVENTS).exists() {
        return Ok(None);
    }
    let mut config = Value::Object(store::read_obj(&dir.join(PROVIDER)));
    if config.as_object().is_some_and(|o| o.is_empty()) {
        config = provider_from_env();
    }
    if config["provider"] == "claude" {
        return Ok(None);
    }
    config["model"]
        .as_str()
        .filter(|m| !m.is_empty())
        .map(|m| Some(m.to_owned()))
        .ok_or_else(|| "codex-model-missing".to_owned())
}

fn events(text: &str) -> impl Iterator<Item = Value> + '_ {
    text.lines()
        .filter_map(|line| serde_json::from_str(line).ok())
}

pub fn turns(text: &str, until: &str) -> Vec<Turn> {
    let mut submitted = HashMap::new();
    let mut completed = HashSet::new();
    let mut turns = Vec::new();
    for event in events(text) {
        let (Some(id), Some(ts)) = (event["data"]["turn_id"].as_str(), event["ts"].as_str()) else {
            continue;
        };
        if !until.is_empty() && ts > until {
            continue;
        }
        match event["event"].as_str() {
            Some("UserPromptSubmit") => {
                if let Some(prompt) = event["data"]["prompt"]
                    .as_str()
                    .filter(|s| !s.trim().is_empty() && !completed.contains(id))
                {
                    submitted
                        .entry(id.to_owned())
                        .or_insert_with(|| (ts.to_owned(), prompt.to_owned()));
                }
            }
            Some("Stop") => {
                let Some(reply) = event["data"]["last_assistant_message"]
                    .as_str()
                    .filter(|s| !s.trim().is_empty())
                else {
                    continue;
                };
                if let Some((time, request)) = submitted.remove(id) {
                    completed.insert(id.to_owned());
                    turns.push(Turn {
                        index: turns.len() as i64 + 1,
                        time,
                        request,
                        response: reply.to_owned(),
                        final_response: reply.to_owned(),
                        ..Turn::default()
                    });
                }
            }
            _ => {}
        }
    }
    turns
}

fn record(payload: &Value, run: &Path) -> io::Result<()> {
    let Some(sid) = payload["session_id"].as_str().filter(|s| {
        !s.is_empty()
            && s.bytes()
                .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
    }) else {
        return Ok(());
    };
    let event = payload["hook_event_name"].as_str().unwrap_or_default();
    if !matches!(event, "SessionStart" | "UserPromptSubmit" | "Stop") {
        return Ok(());
    }
    if event != "SessionStart"
        && std::fs::read_to_string(run.join("session-id"))
            .ok()
            .as_deref()
            .map(str::trim)
            != Some(sid)
    {
        return Ok(());
    }
    let home = store::home_dir();
    let dir = home.join("sessions").join(sid);
    std::fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&dir)?;
    let path = dir.join(EVENTS);
    let mut file = OpenOptions::new()
        .read(true)
        .append(true)
        .create(true)
        .mode(0o600)
        .open(&path)?;
    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let mut data = json!({"model": payload["model"], "source": payload["source"]});
    let mut ts = clock::now_us();
    if event != "SessionStart" {
        let Some(turn_id) = payload["turn_id"].as_str().filter(|s| !s.is_empty()) else {
            return Ok(());
        };
        data["turn_id"] = json!(turn_id);
        let key = if event == "UserPromptSubmit" {
            "prompt"
        } else {
            "last_assistant_message"
        };
        let Some(message) = payload[key].as_str().filter(|s| !s.trim().is_empty()) else {
            return Ok(());
        };
        data[key] = json!(message);
        let mut history = String::new();
        file.read_to_string(&mut history)?;
        let mut submitted = false;
        for row in events(&history).filter(|row| row["data"]["turn_id"] == turn_id) {
            if row["event"] == "UserPromptSubmit" {
                submitted = true;
            }
            if row["event"] != event {
                continue;
            }
            // Retry queue publication after an interrupted hook, keeping the original timestamp.
            return hook::request_analysis(row.as_object().unwrap());
        }
        if event == "Stop" && !submitted {
            return Ok(());
        }
        ts = clock::now_us();
    }
    let rec = json!({"ts": ts, "session_id": sid, "event": event, "cwd": payload["cwd"],
                     "transcript_path": path, "rollout_path": payload["transcript_path"], "data": data});
    writeln!(file, "{rec}")?;
    if event == "SessionStart" {
        store::write_compact(&dir.join(PROVIDER), &provider_from_env())?;
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join("want"))
        {
            Ok(mut f) => f.write_all(b"{\"on\":true}")?,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
            Err(e) => return Err(e),
        }
        let tmp = run.join(format!("session-id.{}.tmp", std::process::id()));
        std::fs::write(&tmp, format!("{sid}\n"))?;
        std::fs::rename(tmp, run.join("session-id"))?;
    }
    hook::request_analysis(rec.as_object().unwrap())
}

pub fn main() -> i32 {
    if std::env::var("CONTROL_TUI_ANALYZER").as_deref() == Ok("1") {
        return 0;
    }
    let Some(run) =
        std::env::var_os("CONTROL_TUI_CODEX_RUN").filter(|d| Path::new(d).is_absolute())
    else {
        return 0;
    };
    let mut input = String::new();
    let result = io::stdin()
        .read_to_string(&mut input)
        .and_then(|_| serde_json::from_str(&input).map_err(io::Error::from))
        .and_then(|value| record(&value, Path::new(&run)));
    if let Err(err) = result {
        hook::log_error(&format!("Codex hook: {err}"));
    }
    // Empty output lets the hook proceed without adding context to the conversation.
    0
}
