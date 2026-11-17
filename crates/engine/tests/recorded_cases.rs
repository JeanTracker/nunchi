//! 파이썬 엔진 단위 시험에서 모은 흐름·번호 풀이 사례를 러스트 엔진으로 다시 돌린다 (tests/record_engine_cases.py).
//! 같은 입력에 키 순서까지 같은 결과가 나와야 한다. 동작을 일부러 바꿨으면 NUNCHI_UPDATE_GOLDEN=1로 결과 칸을 다시 쓴다.

use nunchi_engine::transcript::Turn;
use nunchi_engine::{flow, glossary, py};
use serde_json::{json, Value};

fn turn(v: &Value) -> Turn {
    Turn {
        index: v["index"].as_i64().unwrap_or(0),
        time: String::new(),
        request: v["request"].as_str().unwrap_or("").into(),
        response: v["response"].as_str().unwrap_or("").into(),
        final_response: v["final_response"].as_str().unwrap_or("").into(),
    }
}

fn path(name: &str) -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden").join(name)
}

fn cases(name: &str) -> Vec<Value> {
    std::fs::read_to_string(path(name)).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect()
}

fn update() -> bool {
    std::env::var("NUNCHI_UPDATE_GOLDEN").as_deref() == Ok("1")
}

fn save(name: &str, all: &[Value]) {
    std::fs::write(path(name), all.iter().map(|c| py::dumps(c) + "\n").collect::<String>()).unwrap();
}

fn run_flow(c: &Value) -> Value {
    let turns: Vec<Turn> = c["turns"].as_array().map(|a| a.iter().map(turn).collect()).unwrap_or_default();
    let f = &c["flow"];
    let t = turn(&c["t"]);
    match c["fn"].as_str().unwrap() {
        "build_prompt" => json!(flow::build_prompt(f, &turns, &t)),
        "retrieve" => json!(flow::retrieve(f, &turns, &t)),
        "grown" => json!(flow::grown(f, &turns)),
        "valid_for" => json!(flow::valid_for(f, &turns)),
        "migrate" => flow::migrate(if f.is_null() { None } else { Some(f) }, &turns).unwrap_or(Value::Null),
        "parse_step" => match flow::parse_step(c["text"].as_str().unwrap(), f, &turns, &t) {
            Ok(v) => v,
            Err(_) => json!({"flow_error": true}),
        },
        "advance" => {
            let outs: Vec<String> = c["outputs"].as_array().unwrap().iter().map(|o| py::str_of(o)).collect();
            let mut it = outs.into_iter();
            let mut runner = |_: &str| it.next().ok_or(());
            match flow::advance(f, &turns, &t, &mut runner, c["tries"].as_u64().unwrap_or(2) as usize) {
                Ok(v) => v,
                Err(()) => Value::Null, // 실행기가 실패했다 (파이썬도 예외로 끝남)
            }
        }
        other => panic!("모르는 함수 {other}"),
    }
}

#[test]
fn flow_cases_recorded_from_python_tests() {
    let mut all = cases("flow_cases.jsonl");
    assert!(all.len() > 100);
    if update() {
        for c in all.iter_mut() {
            c["result"] = run_flow(c);
        }
        save("flow_cases.jsonl", &all);
    }
    let mut bad = Vec::new();
    for (i, c) in all.iter().enumerate() {
        let got = run_flow(c);
        if py::dumps(&got) != py::dumps(&c["result"]) {
            bad.push(format!("#{i} {}: got {} want {}", c["fn"], py::take(&py::dumps(&got), 300), py::take(&py::dumps(&c["result"]), 300)));
        }
    }
    assert!(bad.is_empty(), "{} / {} 다름:\n{}", bad.len(), all.len(), bad.join("\n"));
}

#[test]
fn glossary_cases_recorded_from_python_tests() {
    let mut all = cases("glossary_cases.jsonl");
    let tmp = std::env::temp_dir().join(format!("nunchi-gloss-{}", std::process::id()));
    let mut bad = Vec::new();
    for i in 0..all.len() {
        let c = all[i].clone();
        let dir = tmp.join(i.to_string());
        std::fs::create_dir_all(dir.join("docs")).unwrap();
        for (name, text) in c["docs"].as_object().unwrap() {
            std::fs::write(dir.join("docs").join(name), text.as_str().unwrap()).unwrap();
        }
        let text = c["text"].as_str().unwrap().to_string();
        let got = glossary::explain(&text, &dir.to_string_lossy());
        let found: Vec<Value> = glossary::find(&text).into_iter().map(|(k, h)| json!([k, h])).collect();
        if update() {
            all[i]["result"] = got.clone();
            all[i]["find"] = json!(found);
        }
        let c = &all[i];
        if py::dumps(&got) != py::dumps(&c["result"]) || py::dumps(&json!(found)) != py::dumps(&c["find"]) {
            bad.push(format!("#{i}: got {} want {}", py::dumps(&got), py::dumps(&c["result"])));
        }
    }
    let _ = std::fs::remove_dir_all(&tmp);
    if update() {
        save("glossary_cases.jsonl", &all);
    }
    assert!(bad.is_empty(), "{}", bad.join("\n"));
}
