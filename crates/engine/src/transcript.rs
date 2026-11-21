//! Claude Code 대화 기록을 턴으로 묶는다 (control_tui/transcript.py `parse_turns`를 옮김).
//!
//! 엔진이 쓰는 것만 옮겼다: 턴 번호, 요청, 응답 전체, 최종 응답. 도구 성공·실패, 정보량, 단계는
//! 관제 화면이 쓰는 것이라 옮기지 않았다(관제 화면은 아직 파이썬, R3에서 옮긴다).

use crate::clock::ts_value;
use crate::py;
use serde_json::Value;
use std::path::Path;

const COMMAND_PREFIXES: [&str; 6] = [
    "<command-name>", "<command-message>", "<command-args>",
    "<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>",
];
const INTERRUPT_MARK: &str = "[Request interrupted by user";
const LOCAL_COMMAND_PREFIXES: [&str; 3] = ["<local-command-stdout>", "<local-command-stderr>", "<local-command-caveat>"];

#[derive(Debug, Clone, Default, PartialEq)]
pub struct Turn {
    pub index: i64,
    pub time: String,
    pub request: String,
    pub response: String,
    pub final_response: String,
    /// 그 턴에 사용자가 더 한 말 (요구 이력 81): 작업 중에 덧붙인 요청, 질문 창에서 고른 답.
    /// request와 따로 두어 지문(요청 앞 40자)과 턴 번호가 바뀌지 않는다
    pub added: Vec<String>,
}

impl Turn {
    /// 요청 인용을 찾을 글: 요청과 덧붙인 말
    pub fn said(&self) -> String {
        if self.added.is_empty() { self.request.clone() } else { format!("{}\n{}", self.request, self.added.join("\n")) }
    }
}

const ADDED_MARK: &str = "(작업 중에 덧붙인 요청) ";
const PICKED_MARK: &str = "(질문 창에서 고름) ";
const QUESTION_CUT: usize = 200;

/// 줄바꿈과 겹친 빈칸을 빈칸 하나로
fn one_line(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// 작업 중에 사람이 입력한 요청: 기록에는 대기 명령 첨부로만 남는다 (요구 이력 81).
/// 에이전트 메시지·작업 알림·다른 세션 메시지는 origin이 human이 아니다
fn queued_request(rec: &Value) -> Option<String> {
    let a = py::get(rec, "attachment")?;
    if py::get(a, "type") != Some(&Value::from("queued_command")) || py::opt_truthy(py::get(a, "isMeta")) {
        return None;
    }
    if py::get(a, "origin").and_then(|o| py::get(o, "kind")) != Some(&Value::from("human")) {
        return None;
    }
    let text = text_of(py::get(a, "prompt"))?;
    let text = py::strip(&text);
    if text.is_empty() || is_command_record(text) { None } else { Some(format!("{ADDED_MARK}{text}")) }
}

/// 질문 창에서 고른 답 (요구 이력 81): 도구 결과 줄의 toolUseResult.answers. 오류(Esc 등)나 답이 없으면 없음
fn picked_answers(rec: &Value, content: Option<&Value>) -> Vec<String> {
    let blocks = py::list(content);
    let results: Vec<&Value> = blocks.iter().filter(|b| py::get(b, "type") == Some(&Value::from("tool_result"))).collect();
    if results.is_empty() || results.iter().any(|b| py::opt_truthy(py::get(b, "is_error"))) {
        return vec![];
    }
    let Some(r) = py::get(rec, "toolUseResult") else { return vec![] };
    let Some(Value::Object(answers)) = py::get(r, "answers") else { return vec![] };
    let notes = py::get(r, "annotations").and_then(Value::as_object);
    let mut asked: Vec<(String, String)> = py::list(py::get(r, "questions"))
        .iter()
        .filter_map(|q| Some((py::get(q, "question")?.as_str()?.to_string(), py::get(q, "header").and_then(Value::as_str).unwrap_or("").to_string())))
        .collect();
    for k in answers.keys() {
        if !asked.iter().any(|(q, _)| q == k) {
            asked.push((k.clone(), String::new()));
        }
    }
    let mut out = vec![];
    for (q, header) in asked {
        let Some(a) = answers.get(&q).map(py::str_of).filter(|a| !py::strip(a).is_empty()) else { continue };
        let question = py::take(&one_line(&q), QUESTION_CUT);
        let head = if header.is_empty() { String::new() } else { format!("{header}: ") };
        let note = notes.and_then(|n| n.get(&q)).and_then(|n| py::get(n, "notes")).map(py::str_of).filter(|n| !py::strip(n).is_empty());
        let note = note.map(|n| format!(" (메모: {})", one_line(&n))).unwrap_or_default();
        out.push(format!("{PICKED_MARK}{head}{question} → {}{note}", one_line(&a)));
    }
    out
}

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Text,
    Tool,
}

fn starts_any(s: &str, prefixes: &[&str]) -> bool {
    prefixes.iter().any(|p| s.starts_with(p))
}

fn is_command_record(text: &str) -> bool {
    let head = py::lstrip(text);
    starts_any(head, &COMMAND_PREFIXES) || head.starts_with(INTERRUPT_MARK) || head.starts_with("<task-notification>")
}

fn is_from_human(rec: &Value) -> bool {
    match py::get(rec, "origin") {
        Some(Value::Object(o)) if o.get("kind").map(py::truthy).unwrap_or(false) => {
            o.get("kind") == Some(&Value::from("human"))
        }
        _ => true,
    }
}

/// 사용자 메시지에서 요청 글만. 도구 결과 묶음이면 None
fn text_of(content: Option<&Value>) -> Option<String> {
    match content {
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Array(blocks)) => {
            if blocks.iter().any(|b| py::get(b, "type") == Some(&Value::from("tool_result"))) {
                return None;
            }
            let texts: Vec<String> = blocks
                .iter()
                .filter(|b| b.is_object() && py::get(b, "type") == Some(&Value::from("text")))
                .map(|b| py::get(b, "text").and_then(Value::as_str).unwrap_or("").to_string())
                .collect();
            if texts.is_empty() { None } else { Some(texts.join("\n")) }
        }
        _ => None,
    }
}

/// `<command-args>(.*?)</command-args>`의 첫 번째 것
fn command_args(text: &str) -> Option<&str> {
    let open = "<command-args>";
    let start = text.find(open)? + open.len();
    let end = text[start..].find("</command-args>")?;
    Some(&text[start..start + end])
}

/// `<command-name>\s*(/?[^<\s]+)\s*</command-name>`의 첫 번째 것
fn command_name(text: &str) -> Option<String> {
    let open = "<command-name>";
    let mut from = 0;
    while let Some(off) = text[from..].find(open) {
        let at = from + off;
        let rest = py::lstrip(&text[at + open.len()..]);
        let run: String = rest.chars().take_while(|c| *c != '<' && !py::is_space(*c)).collect();
        if !run.is_empty() {
            let after = py::lstrip(&rest[run.len()..]);
            if after.starts_with("</command-name>") {
                return Some(run);
            }
        }
        from = at + 1;
    }
    None
}

/// 슬래시 명령 뒤에 쓴 글: '/design 글'. 없으면 빈 글
fn command_with_args(text: &str) -> String {
    let head = py::lstrip(text);
    if !starts_any(head, &COMMAND_PREFIXES[..3]) {
        return String::new();
    }
    let args = match command_args(text) {
        Some(a) if !py::strip(a).is_empty() => py::strip(a),
        _ => return String::new(),
    };
    let mut cmd = command_name(text).unwrap_or_default();
    if !cmd.is_empty() && !cmd.starts_with('/') {
        cmd = format!("/{cmd}");
    }
    py::strip(&format!("{cmd} {args}")).to_string()
}

/// 턴 목록. until_ts가 있으면 그 뒤에 적힌 기록은 읽지 않는다. 파일이 UTF-8이 아니면 오류.
pub fn parse_turns(path: &Path, until_ts: &str) -> Result<Vec<Turn>, String> {
    if path.as_os_str().is_empty() || !path.exists() {
        return Ok(vec![]);
    }
    let bytes = std::fs::read(path).map_err(|_| "io".to_string())?;
    let text = String::from_utf8(bytes).map_err(|_| "not-utf8".to_string())?;   // 실패 이유는 코드 (요구 이력 76)
    let limit = if until_ts.is_empty() { 0.0 } else { ts_value(until_ts) };
    let mut turns: Vec<Turn> = Vec::new();
    let mut segments: Vec<Vec<(Kind, String)>> = Vec::new(); // turns와 같은 순서
    let mut current = false; // 마지막 턴이 지금 턴인지

    for line in py::splitlines(&text) {
        let rec: Value = match serde_json::from_str(line) {
            Ok(v @ Value::Object(_)) => v,
            _ => continue, // 파이썬은 사전이 아닌 JSON 줄에서 멈춘다. 여기서는 건너뛴다 (일부러 다름)
        };
        if py::opt_truthy(py::get(&rec, "isSidechain")) {
            continue;
        }
        if limit != 0.0 {
            if let Some(ts) = py::get(&rec, "timestamp").filter(|v| py::truthy(v)) {
                if ts_value(&py::str_of(ts)) > limit {
                    continue;
                }
            }
        }
        let kind = py::get(&rec, "type").and_then(Value::as_str).unwrap_or("");
        let content = py::get(&rec, "message").and_then(|m| m.as_object()).and_then(|m| m.get("content"));
        let is_meta = py::opt_truthy(py::get(&rec, "isMeta"));

        if kind == "attachment" {
            if let Some(text) = queued_request(&rec) {
                match turns.last_mut() {
                    Some(t) => {
                        // 응답이 끝났거나 알림이 끼어 닫힌 턴이면 다시 연다: 이 요청에 대한 응답이 그 턴에 붙어
                        // 응답이 자라고, 엔진이 마지막 턴을 다시 분석한다(grown). 턴 번호는 그대로
                        t.added.push(text);
                        current = true;
                    }
                    None => {
                        let time = py::get(&rec, "timestamp").filter(|v| py::truthy(v)).map(py::str_of).unwrap_or_default();
                        turns.push(Turn { index: 1, time, request: text[ADDED_MARK.len()..].to_string(), ..Default::default() });
                        segments.push(Vec::new());
                        current = true;
                    }
                }
            }
            continue;
        }
        if kind == "user" {
            let picked = picked_answers(&rec, content);
            if !picked.is_empty() {
                if let Some(t) = turns.last_mut() {
                    t.added.extend(picked);
                }
                continue;
            }
            let Some(text) = text_of(content) else { continue };
            let command_request = if is_from_human(&rec) && !is_meta { command_with_args(&text) } else { String::new() };
            if current {
                let cur = turns.last().unwrap();
                if cur.request.starts_with('/') && segments.last().unwrap().is_empty() {
                    if is_meta {
                        continue;
                    }
                    if starts_any(py::lstrip(&text), &LOCAL_COMMAND_PREFIXES) {
                        turns.pop();
                        segments.pop();
                        current = false;
                        continue;
                    }
                }
            }
            // 지금 턴에 끼어든 meta 기록(시스템 안내, 스킬 본문 등)은 사람이 쓴 말이 아니다. 답이 나오기 전이어도
            // 턴을 닫지 않는다: 닫으면 뒤따르는 답이 통째로 빠져 그 턴이 '응답 없음'이 됐다
            if is_meta && current {
                continue;
            }
            // 압축 요약 (요구 이력 94): 사람이 쓴 말이 아니라 건너뛰되 지금 턴은 닫지 않는다. 응답 도중 압축되면
            // 같은 요청의 답이 압축 뒤에도 이어지기 때문이다(닫으면 압축 뒤의 답이 모두 빠졌다)
            if py::opt_truthy(py::get(&rec, "isCompactSummary")) {
                continue;
            }
            let text = if !command_request.is_empty() {
                command_request
            } else if is_meta
                || !is_from_human(&rec)
                || is_command_record(&text)
            {
                if !py::lstrip(&text).starts_with(INTERRUPT_MARK) {
                    current = false;
                }
                continue;
            } else {
                text
            };
            let time = match py::get(&rec, "timestamp") {
                Some(v) if py::truthy(v) => py::str_of(v),
                _ => String::new(),
            };
            turns.push(Turn { index: turns.len() as i64 + 1, time, request: py::strip(&text).to_string(), ..Default::default() });
            segments.push(Vec::new());
            current = true;
        } else if kind == "assistant" && current {
            let seg = segments.last_mut().unwrap();
            for b in py::list(content) {
                let Some(o) = b.as_object() else { continue };
                match o.get("type").and_then(Value::as_str) {
                    Some("text") => {
                        let t = o.get("text").and_then(Value::as_str).unwrap_or("");
                        if !py::strip(t).is_empty() {
                            seg.push((Kind::Text, py::strip(t).to_string()));
                        }
                    }
                    Some("tool_use") => seg.push((Kind::Tool, String::new())),
                    _ => {}
                }
            }
        }
    }
    for (t, seg) in turns.iter_mut().zip(segments.iter()) {
        let texts: Vec<&str> = seg.iter().filter(|(k, _)| *k == Kind::Text).map(|(_, s)| s.as_str()).collect();
        t.response = texts.join("\n\n");
        match seg.iter().rposition(|(k, _)| *k == Kind::Tool) {
            None => t.final_response = t.response.clone(),
            Some(i) => {
                t.final_response = seg[i + 1..]
                    .iter()
                    .filter(|(k, _)| *k == Kind::Text)
                    .map(|(_, s)| s.as_str())
                    .collect::<Vec<_>>()
                    .join("\n\n")
            }
        }
    }
    Ok(turns)
}
