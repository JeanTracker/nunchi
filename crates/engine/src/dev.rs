//! 시험용 하위 명령 (`--features dev`에서만). 파이썬 엔진과 결과를 맞춰 보는 데 쓴다.

use crate::{flow, glossary, transcript};
use serde_json::{json, Value};
use std::path::Path;

fn turns_json(path: &str, until: &str) -> Value {
    match transcript::parse_turns(Path::new(path), until) {
        Ok(turns) => Value::Array(
            turns
                .iter()
                .map(|t| json!({"index": t.index, "request": t.request, "response": t.response, "final_response": t.final_response, "added": t.added}))
                .collect(),
        ),
        Err(e) => json!({"error": e}),
    }
}

pub fn main(args: &[String]) -> i32 {
    match args.first().map(String::as_str) {
        // 여러 기록을 한 번에: 한 줄에 경로 하나(탭 뒤에 until_ts) → 한 줄에 JSON 하나
        Some("parse-turns") => {
            let mut input = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut input).ok();
            for line in input.lines() {
                let (path, until) = line.split_once('\t').unwrap_or((line, ""));
                println!("{}", turns_json(path, until));
            }
            0
        }
        // 한 줄에 사례 하나: {"flow", "transcript", "until", "turn", "outputs"?} → 한 줄에 결과 하나
        Some("flow") => {
            let mut input = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut input).ok();
            for line in input.lines() {
                let case: Value = serde_json::from_str(line).unwrap_or(Value::Null);
                println!("{}", flow_case(&case));
            }
            0
        }
        // 한 줄에 {"text", "cwd"} → explain 결과와 find 결과
        Some("glossary") => {
            let mut input = String::new();
            std::io::Read::read_to_string(&mut std::io::stdin(), &mut input).ok();
            for line in input.lines() {
                let c: Value = serde_json::from_str(line).unwrap_or(Value::Null);
                let text = c["text"].as_str().unwrap_or("");
                let found: Vec<Value> = glossary::find(text).into_iter().map(|(k, h)| json!([k, h])).collect();
                println!("{}", json!({"explain": glossary::explain(text, c["cwd"].as_str().unwrap_or("")), "find": found}));
            }
            0
        }
        _ => {
            eprintln!("dev: parse-turns | flow | glossary");
            2
        }
    }
}

fn flow_case(case: &Value) -> Value {
    let path = case["transcript"].as_str().unwrap_or("");
    let until = case["until"].as_str().unwrap_or("");
    let turns = match transcript::parse_turns(Path::new(path), until) {
        Ok(t) => t,
        Err(e) => return json!({"error": e}),
    };
    let idx = case["turn"].as_i64().unwrap_or(0);
    let Some(t) = turns.iter().find(|x| x.index == idx) else { return json!({"error": "no turn"}) };
    let f = &case["flow"];
    let migrated = flow::migrate(if f.is_null() { None } else { Some(f) }, &turns);
    let mut out = json!({
        "prompt": flow::build_prompt(f, &turns, t),
        "grown": flow::grown(f, &turns),
        "valid": flow::valid_for(f, &turns),
        "migrated": migrated,
        "mark": flow::response_mark(t),
        "retrieve": flow::retrieve(f, &turns, t),
    });
    if let Some(outputs) = case["outputs"].as_array() {
        let mut it = outputs.iter();
        let mut runner = |_: &str| -> Result<String, String> {
            it.next().and_then(Value::as_str).map(String::from).ok_or_else(|| "runner exhausted".to_string())
        };
        out["advance"] = match flow::advance(f, &turns, t, &mut runner, 2) {
            Ok(v) => v,
            Err(e) => json!({"error": e}),
        };
        out["parse"] = match outputs.first().and_then(Value::as_str).map(|o| flow::parse_step(o, f, &turns, t)) {
            Some(Ok(v)) => v,
            Some(Err(e)) => json!({"flow_error": e.0}),
            None => Value::Null,
        };
    }
    out
}
