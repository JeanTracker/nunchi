//! 목표 흐름: 원문 고정 연쇄 (control_tui/flow.py를 옮김. 요청 40, BUILD_PLAN §4.3).
//!
//! 흐름은 파이썬과 같은 JSON 사전 그대로 다룬다(키 순서까지). 모델 출력은 인용을 원문과 대조하고,
//! 맞지 않으면 한 번 다시 묻고, 그래도 안 되면 요청 원문 앞부분으로 적는다.

use crate::py::{self, get, int_of, list, obj_or_empty, opt_truthy, str_or_empty, truthy};
use crate::transcript::Turn;
use serde_json::{json, Map, Value};

pub const VERSION: i64 = 3;
pub const RELATIONS: [&str; 8] = ["시작", "구체화", "재정의", "정정", "범위 축소", "문제 제기", "확정", "질문"];
const STATES: [&str; 5] = ["addressed", "open", "deferred", "superseded", "in_progress"];
const LEFT_STATES: [&str; 3] = ["open", "deferred", "in_progress"];
const DIGEST_CUT: usize = 90;
const ASKS_SHOWN: usize = 30;
const REQUESTS_SHOWN: usize = 80;
const DIRECTIONS: [&str; 3] = ["넓힘", "좁힘", "옮김"];
const QUOTE_MIN: usize = 2;
const REQUEST_CUT: usize = 3000;
const DOC_REQUEST_CUT: usize = 800;
const DOC_RESPONSE_TAIL: usize = 600;
const SIMILAR_DOCS: usize = 2;
const TITLE_CUT: usize = 16;
const FALLBACK_CUT: usize = 60;

pub const HEAD: &str = include_str!("flow_head.txt");

type Obj = Map<String, Value>;

pub struct FlowError(pub String);

fn err<T>(msg: &str) -> Result<T, FlowError> {
    Err(FlowError(msg.to_string()))
}

fn sq(v: Option<&Value>) -> String {
    py::squash(&str_or_empty(v))
}

/// `_one(text, limit)`
fn one(v: Option<&Value>, limit: usize) -> String {
    py::take(&py::join_ws(&str_or_empty(v)), limit)
}

fn one_s(s: &str, limit: usize) -> String {
    py::take(&py::join_ws(s), limit)
}

fn grams(s: &str) -> std::collections::HashSet<String> {
    let x: Vec<char> = py::squash(s).chars().collect();
    if x.is_empty() {
        return Default::default();
    }
    (0..std::cmp::max(1, x.len().saturating_sub(1)))
        .map(|i| x[i..std::cmp::min(i + 2, x.len())].iter().collect())
        .collect()
}

fn sim(a: &str, b: &str) -> f64 {
    let (ga, gb) = (grams(a), grams(b));
    if ga.is_empty() || gb.is_empty() {
        return 0.0;
    }
    ga.intersection(&gb).count() as f64 / ga.union(&gb).count() as f64
}

fn contains(quote: Option<&Value>, source: &str) -> bool {
    let q = sq(quote);
    py::char_len(&q) >= QUOTE_MIN && py::squash(source).contains(&q)
}

fn in_list(v: Option<&Value>, items: &[&str]) -> bool {
    matches!(v, Some(Value::String(s)) if items.contains(&s.as_str()))
}

fn s(v: &str) -> Value {
    Value::from(v)
}

/// 그 턴 응답을 분석할 때의 표시 (요구 이력 64)
pub fn response_mark(t: &Turn) -> String {
    let body = py::squash(&t.response);
    let hex = sha1_smol::Sha1::from(body.as_bytes()).digest().to_string();
    format!("{}:{}", py::char_len(&body), &hex[..10])
}

fn mark_len(v: &str) -> Option<i64> {
    py::strip(v.split(':').next().unwrap_or("")).parse().ok()
}

pub fn grown(flow: &Value, turns: &[Turn]) -> bool {
    let steps = list(get(flow, "steps"));
    let until = py::int_or(get(flow, "until"), 0).unwrap_or(0);
    let Some(lastst) = steps.last() else { return false };
    if !py::eq_int(get(lastst, "index"), until) || !opt_truthy(get(lastst, "resp")) || get(flow, "prev").is_none() {
        return false;
    }
    let Some(t) = turns.iter().find(|x| x.index == until) else { return false };
    match (mark_len(&response_mark(t)), mark_len(&py::str_of(get(lastst, "resp").unwrap()))) {
        (Some(a), Some(b)) => a > b,
        _ => false,
    }
}

/// 마지막 턴을 적기 전의 흐름 (그 턴을 다시 적으려고)
pub fn rewind(flow: &Value) -> Value {
    Value::Object(obj_or_empty(get(flow, "prev")))
}

pub fn fingerprint(t: &Turn) -> String {
    py::take(&py::squash(&t.request), 40)
}

fn int_field(v: Option<&Value>) -> Option<i64> {
    v.and_then(|x| if x.is_number() || x.is_boolean() { int_of(x) } else { None })
}

pub fn retrieve(flow: &Value, turns: &[Turn], t: &Turn) -> Vec<i64> {
    let k = t.index;
    if k <= 1 {
        return vec![];
    }
    let pick = |key: &str| -> Option<i64> {
        let v = get(flow, key).and_then(|g| get(g, "turn"));
        match v {
            Some(x) if truthy(x) => int_field(Some(x)),
            _ => Some(1),
        }
    };
    let mut picks: Vec<i64> = [pick("first_goal"), pick("current_goal"), Some(k - 1)].into_iter().flatten().collect();
    let mut older: Vec<(&Turn, f64)> = turns.iter().filter(|x| x.index < k - 1).map(|x| (x, -sim(&x.request, &t.request))).collect();
    older.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal));
    picks.extend(older.iter().take(SIMILAR_DOCS).map(|(x, _)| x.index));
    let mut out: Vec<i64> = Vec::new();
    for i in picks {
        if 1 <= i && i < k && !out.contains(&i) {
            out.push(i);
        }
    }
    out.sort();
    out
}

pub fn build_prompt(flow: &Value, turns: &[Turn], t: &Turn) -> String {
    let fg = obj_or_empty(get(flow, "first_goal"));
    let cg = obj_or_empty(get(flow, "current_goal"));
    let steps: Vec<Value> = list(get(flow, "steps"))
        .iter()
        .map(|st| {
            let mut o = Obj::new();
            for key in ["index", "label", "summary", "agent_summary"] {
                o.insert(key.into(), get(st, key).cloned().unwrap_or_else(|| s("")));
            }
            Value::Object(o)
        })
        .collect();
    let past = json!({
        "first_goal": fg.get("text").cloned().unwrap_or_else(|| s("")),
        "current_goal": cg.get("text").cloned().unwrap_or_else(|| s("")),
        "goal_turn": cg.get("turn").cloned().unwrap_or(json!(0)),
        "turns": steps,
    });
    let mut docs = Vec::new();
    for i in retrieve(flow, turns, t) {
        let Some(x) = turns.iter().find(|x| x.index == i) else { continue };
        let body = if x.final_response.is_empty() { &x.response } else { &x.final_response };
        let tail = py::last(&one_s(body, 100_000), DOC_RESPONSE_TAIL);
        docs.push(format!("[턴 {i}] 요청: {}\n  응답 끝부분: {tail}", one_s(&x.request, DOC_REQUEST_CUT)));
    }
    let reqs: Vec<&Value> = list(get(flow, "requests")).iter().filter(|r| get(r, "state") != Some(&s("superseded"))).collect();
    let reqs = &reqs[reqs.len().saturating_sub(REQUESTS_SHOWN)..];
    let past_requests: Vec<Value> = reqs
        .iter()
        .map(|r| {
            json!({"id": get(r, "id").cloned().unwrap_or(Value::Null), "from_turn": get(r, "from_turn").cloned().unwrap_or(Value::Null),
                   "summary": get(r, "summary").cloned().unwrap_or_else(|| s("")), "state": get(r, "state").cloned().unwrap_or(Value::Null)})
        })
        .collect();
    let asks: Vec<Value> = list(get(flow, "asks"))
        .iter()
        .filter(|a| get(a, "state") != Some(&s("answered")))
        .map(|a| {
            let turn = match get(a, "last_turn") {
                Some(v) if truthy(v) => v.clone(),
                _ => get(a, "turn").cloned().unwrap_or(Value::Null),
            };
            json!({"id": get(a, "id").cloned().unwrap_or(Value::Null), "turn": turn,
                   "summary": get(a, "summary").cloned().unwrap_or_else(|| s("")), "state": get(a, "state").cloned().unwrap_or(Value::Null)})
        })
        .collect();
    let asks = &asks[asks.len().saturating_sub(ASKS_SHOWN)..];
    let or_none = |v: String, empty: bool| if empty { "(없음)".to_string() } else { v };
    let response = py::strip(&t.response);
    format!(
        "{HEAD}\n=== 지난 흐름 ===\n{}\n\n=== 지난 묻는 것 (아직 답이 다 오지 않은 것) ===\n{}\n\n=== 지난 요청 기록 ===\n{}\n\n=== 찾아 온 원문 ===\n{}\n\n=== 새 턴 ===\n[턴 {}] 요청: {}\n  응답: {}\n",
        py::dumps(&past),
        or_none(py::dumps(&Value::Array(asks.to_vec())), asks.is_empty()),
        or_none(py::dumps(&Value::Array(past_requests.to_vec())), past_requests.is_empty()),
        or_none(docs.join("\n"), docs.is_empty()),
        t.index,
        py::take(py::strip(&t.request), REQUEST_CUT),
        if response.is_empty() { "(없음)" } else { response },
    )
}

/// 모델 출력을 검사한다. 원문과 맞지 않는 인용이 하나라도 있으면 FlowError
pub fn parse_step(text: &str, flow: &Value, turns: &[Turn], t: &Turn) -> Result<Value, FlowError> {
    let (Some(start), Some(end)) = (text.find('{'), text.rfind('}')) else { return err("JSON이 없습니다") };
    if end <= start {
        return err("JSON이 없습니다");
    }
    let o: Value = serde_json::from_str(&text[start..=end]).map_err(|e| FlowError(format!("JSON이 깨졌습니다: {e}")))?;
    if !o.is_object() {
        return err("형식이 다릅니다");
    }
    let tu = match get(&o, "turn") {
        Some(v @ Value::Object(_)) => v.clone(),
        _ => json!({}),
    };
    let label = get(&tu, "label").cloned().unwrap_or_else(|| s(""));
    if !in_list(Some(&label), &RELATIONS) {
        return err("관계 이름이 정해진 것이 아닙니다");
    }
    if !contains(get(&tu, "quote"), &t.request) {
        return err("요청 인용이 원문에 없습니다");
    }
    let mut agent_quote = match get(&tu, "agent_quote") {
        Some(v) if truthy(v) => v.clone(),
        _ => s(""),
    };
    if !py::strip(&t.response).is_empty() {
        if !contains(Some(&agent_quote), &t.response) {
            return err("응답 인용이 원문에 없습니다");
        }
    } else {
        agent_quote = s("");
    }
    let first = t.index == 1 || !opt_truthy(get(flow, "steps"));
    let shift = opt_truthy(get(&o, "topic_shift")) && !first;
    let mut goal_turn: Value = Value::from(py::int_or(get(&o, "goal_turn"), 0).unwrap_or(0));
    let prev_goal = obj_or_empty(get(flow, "current_goal"));
    if shift || first {
        goal_turn = Value::from(t.index);
    } else if !truthy(&goal_turn) {
        goal_turn = match prev_goal.get("turn") {
            Some(v) if truthy(v) => v.clone(),
            _ => Value::from(t.index),
        };
    }
    let gt = int_field(Some(&goal_turn));
    let Some(goal_src) = gt.and_then(|g| turns.iter().find(|x| x.index == g && py::eq(&goal_turn, &Value::from(x.index)))) else {
        return err("목표 근거 턴 번호가 맞지 않습니다");
    };
    if gt.unwrap() > t.index {
        return err("목표 근거 턴 번호가 맞지 않습니다");
    }
    let mut goal_quote = match get(&o, "goal_quote") {
        Some(v) if truthy(v) => v.clone(),
        _ => s(""),
    };
    if !contains(Some(&goal_quote), &goal_src.request) {
        if !shift && !first && opt_truthy(prev_goal.get("quote")) {
            goal_quote = prev_goal["quote"].clone();
        } else {
            return err("목표 인용이 원문에 없습니다");
        }
    }
    let mut step = Obj::new();
    step.insert("index".into(), Value::from(t.index));
    step.insert("label".into(), label.clone());
    step.insert("summary".into(), s(&one(get(&tu, "summary"), 200)));
    step.insert("quote".into(), s(&one(get(&tu, "quote"), 80)));
    step.insert("agent_summary".into(), s(&one(get(&tu, "agent_summary"), 200)));
    step.insert("agent_quote".into(), s(&one(Some(&agent_quote), 80)));
    step.insert("fp".into(), s(&fingerprint(t)));
    step.insert("grounded".into(), Value::Bool(true));
    step.insert("shift".into(), Value::Bool(shift));
    step.insert("title".into(), s(&one(get(&tu, "title"), TITLE_CUT)));
    step.insert("decision".into(), s(&if label == s("확정") { one(get(&tu, "decision"), 200) } else { String::new() }));
    let mut goal_text = s(&one(get(&o, "current_goal"), 200));
    if !shift && !first {
        if let Some(v) = prev_goal.get("text").filter(|v| truthy(v)) {
            goal_text = v.clone();
        }
    }
    if !truthy(&goal_text) {
        return err("지금 목표가 비었습니다");
    }
    if shift {
        let ch = match get(&o, "goal_change") {
            Some(v @ Value::Object(_)) => v.clone(),
            _ => json!({}),
        };
        if !in_list(get(&ch, "direction"), &DIRECTIONS) {
            return err("방향이 넓힘·좁힘·옮김이 아닙니다");
        }
        if !contains(get(&ch, "quote"), &t.request) {
            return err("방향 근거 인용이 원문에 없습니다");
        }
        step.insert("direction".into(), ch["direction"].clone());
        step.insert("how".into(), s(&one(get(&ch, "how"), 200)));
        step.insert("shift_quote".into(), s(&one(get(&ch, "quote"), 80)));
        step.insert("goal".into(), goal_text.clone());
        step.insert("prev_goal".into(), prev_goal.get("text").cloned().unwrap_or_else(|| s("")));
    }
    step.insert("digest".into(), s(&one(get(&o, "digest"), DIGEST_CUT)));
    let mut result = Obj::new();
    result.insert("step".into(), Value::Object(step));
    result.insert("current_goal".into(), json!({"text": goal_text, "turn": goal_turn, "quote": one(Some(&goal_quote), 80)}));
    result.insert("requests".into(), parse_requests(&o, flow, t));
    result.insert("asks".into(), parse_asks(&o, flow, t));
    if first {
        let mut fg = s(&one(get(&o, "first_goal"), 200));
        if !truthy(&fg) {
            fg = goal_text.clone();
        }
        result.insert("first_goal".into(), json!({"text": fg, "turn": t.index, "quote": one(Some(&goal_quote), 80)}));
    }
    Ok(Value::Object(result))
}

fn pending_quote(item: &Value, state: &str, t: &Turn) -> String {
    let pq = get(item, "pending_quote").filter(|v| truthy(v));
    match pq {
        Some(v) if state == "in_progress" && contains(Some(v), &t.response) => one(Some(v), 80),
        _ => String::new(),
    }
}

/// 파이썬 `x in known` (사전 키는 글 번호). 글이 아니면 없는 것
fn known_id<'a>(known: &'a [Value], id: Option<&Value>) -> Option<&'a Value> {
    let id = id?;
    if !id.is_string() {
        return None;
    }
    known.iter().rev().find(|r| get(r, "id") == Some(id))
}

fn iter_items(v: Option<&Value>) -> &[Value] {
    list(v)
}

pub fn parse_requests(o: &Value, flow: &Value, t: &Turn) -> Value {
    let known = list(get(flow, "requests"));
    let (mut new, mut updates, mut dropped) = (vec![], vec![], 0);
    for item in iter_items(get(o, "requests_new")) {
        if !item.is_object() {
            dropped += 1;
            continue;
        }
        let state = match get(item, "state") {
            Some(Value::String(x)) if ["addressed", "open", "deferred", "in_progress"].contains(&x.as_str()) => x.clone(),
            _ => "open".to_string(),
        };
        let aq = get(item, "agent_quote").filter(|v| truthy(v));
        if !contains(get(item, "quote"), &t.request) || (state != "open" && aq.is_some() && !contains(aq, &t.response)) {
            dropped += 1;
            continue;
        }
        let mut rec = Obj::new();
        rec.insert("summary".into(), s(&one(get(item, "summary"), 200)));
        rec.insert("quote".into(), s(&one(get(item, "quote"), 80)));
        rec.insert("state".into(), s(&state));
        rec.insert("agent_quote".into(), s(&if state != "open" { one(aq, 80) } else { String::new() }));
        let pq = pending_quote(item, &state, t);
        if !pq.is_empty() {
            rec.insert("pending_quote".into(), s(&pq));
        }
        new.push(Value::Object(rec));
    }
    for item in iter_items(get(o, "requests_update")) {
        let state = get(item, "state");
        if !item.is_object() || known_id(known, get(item, "id")).is_none() || !in_list(state, &STATES) {
            dropped += 1;
            continue;
        }
        let state = state.and_then(Value::as_str).unwrap().to_string();
        let aq = get(item, "agent_quote").filter(|v| truthy(v));
        if ["addressed", "deferred", "in_progress"].contains(&state.as_str()) && aq.is_some() && !contains(aq, &t.response) {
            dropped += 1;
            continue;
        }
        updates.push(json!({"id": item["id"], "state": state, "agent_quote": one(aq, 80),
                            "pending_quote": pending_quote(item, &state, t),
                            "superseded_by": if state == "superseded" { t.index } else { 0 }}));
    }
    json!({"new": new, "updates": updates, "dropped": dropped})
}

pub fn parse_asks(o: &Value, flow: &Value, t: &Turn) -> Value {
    let known = list(get(flow, "asks"));
    let (mut new, mut reask, mut updates, mut dropped) = (vec![], vec![], vec![], 0);
    for n in iter_items(get(o, "asks_new")) {
        if n.is_object() && contains(get(n, "quote"), &t.response) {
            let kind = match get(n, "kind") {
                Some(Value::String(k)) if ["결정", "확인", "정보"].contains(&k.as_str()) => k.clone(),
                _ => "확인".into(),
            };
            new.push(json!({"summary": one(get(n, "summary"), 60), "quote": one(get(n, "quote"), 80), "kind": kind}));
        } else {
            dropped += 1;
        }
    }
    for i in iter_items(get(o, "asks_reask")) {
        match known_id(known, Some(i)) {
            Some(a) if get(a, "state") != Some(&s("answered")) => reask.push(i.clone()),
            _ => dropped += 1,
        }
    }
    for u in iter_items(get(o, "asks_update")) {
        if u.is_object()
            && known_id(known, get(u, "id")).is_some()
            && in_list(get(u, "state"), &["answered", "partial"])
            && contains(get(u, "quote"), &t.request)
        {
            updates.push(json!({"id": u["id"], "state": u["state"], "quote": one(get(u, "quote"), 80),
                                "blanket": opt_truthy(get(u, "blanket"))}));
        } else {
            dropped += 1;
        }
    }
    json!({"new": new, "reask": reask, "updates": updates, "dropped": dropped})
}

fn obj_list(v: Option<&Value>) -> Vec<Obj> {
    list(v).iter().map(|x| x.as_object().cloned().unwrap_or_default()).collect()
}

fn find_last(out: &[Obj], id: &Value) -> Option<usize> {
    out.iter().rposition(|a| a.get("id") == Some(id))
}

pub fn apply_asks(asks: Option<&Value>, change: &Value, t: &Turn) -> Value {
    let mut out = obj_list(asks);
    let ids: Vec<Option<Value>> = out.iter().map(|a| a.get("id").cloned()).collect();
    let by_id = |id: &Value| ids.iter().rposition(|x| x.as_ref() == Some(id));
    for u in list(get(change, "updates")) {
        if let Some(i) = by_id(&u["id"]) {
            let a = &mut out[i];
            a.insert("state".into(), u["state"].clone());
            a.insert("answered_at".into(), Value::from(t.index));
            a.insert("answer_quote".into(), u["quote"].clone());
            a.insert("by_blanket".into(), u["blanket"].clone());
        }
    }
    for i in list(get(change, "reask")) {
        if let Some(k) = by_id(i) {
            if out[k].get("state") != Some(&s("answered")) {
                out[k].insert("last_turn".into(), Value::from(t.index));
            }
        }
    }
    for n in list(get(change, "new")) {
        let mut a = n.as_object().cloned().unwrap_or_default();
        a.insert("id".into(), s(&format!("Q{}", out.len() + 1)));
        a.insert("turn".into(), Value::from(t.index));
        a.insert("last_turn".into(), Value::from(t.index));
        a.insert("state".into(), s("open"));
        out.push(a);
    }
    Value::Array(out.into_iter().map(Value::Object).collect())
}

pub fn apply_requests(requests: Option<&Value>, change: &Value, t: &Turn) -> Value {
    let mut out = obj_list(requests);
    for u in list(get(change, "updates")) {
        let Some(i) = find_last(&out, &u["id"]) else { continue };
        let r = &mut out[i];
        let state = u["state"].as_str().unwrap_or("").to_string();
        r.insert("state".into(), s(&state));
        r.insert("by_turn".into(), Value::from(t.index));
        if opt_truthy(get(u, "agent_quote")) {
            r.insert("agent_quote".into(), u["agent_quote"].clone());
        }
        if opt_truthy(get(u, "pending_quote")) {
            r.insert("pending_quote".into(), u["pending_quote"].clone());
        } else if state != "in_progress" {
            r.shift_remove("pending_quote");
        }
        r.shift_remove("tool_failed");
        if state == "superseded" {
            r.insert("superseded_by".into(), u["superseded_by"].clone());
        }
    }
    for n in list(get(change, "new")) {
        let mut r = n.as_object().cloned().unwrap_or_default();
        r.insert("id".into(), s(&format!("R{}", out.len() + 1)));
        r.insert("from_turn".into(), Value::from(t.index));
        r.insert("by_turn".into(), Value::from(t.index));
        out.push(r);
    }
    Value::Array(out.into_iter().map(Value::Object).collect())
}

fn fallback(flow: &Value, t: &Turn) -> Value {
    let head = one_s(&t.request, FALLBACK_CUT);
    let step = json!({"index": t.index, "label": "", "summary": head, "quote": head, "agent_summary": "", "agent_quote": "",
                      "fp": fingerprint(t), "grounded": false, "shift": false});
    let mut result = Obj::new();
    result.insert("step".into(), step);
    if !opt_truthy(get(flow, "steps")) {
        result.insert("first_goal".into(), json!({"text": head, "turn": t.index, "quote": head}));
        result.insert("current_goal".into(), json!({"text": head, "turn": t.index, "quote": head}));
    }
    Value::Object(result)
}

pub fn empty() -> Value {
    json!({"version": VERSION, "first_goal": {}, "current_goal": {}, "steps": [], "requests": [], "asks": [], "until": 0})
}

/// 옛 형식(1·2) 흐름을 지금 형식으로 옮겨 담는다 (요구 이력 44·45)
pub fn migrate(flow: Option<&Value>, turns: &[Turn]) -> Option<Value> {
    let f = flow?;
    let version = get(f, "version");
    let old = [1, 2].iter().find(|v| py::eq_int(version, **v)).copied();
    let (Some(old), Some(o)) = (old, f.as_object()) else { return Some(f.clone()) };
    let start = py::int_or(o.get("until"), 0).unwrap_or(0) + 1;
    let mut moved = o.clone();
    moved.insert("version".into(), Value::from(VERSION));
    if old == 1 {
        moved.insert("requests".into(), json!([]));
        moved.insert("requests_from".into(), Value::from(start));
    }
    moved.insert("asks".into(), json!([]));
    moved.insert("asks_from".into(), Value::from(start));
    let moved = Value::Object(moved);
    Some(if valid_for(&moved, turns) { moved } else { f.clone() })
}

pub fn valid_for(flow: &Value, turns: &[Turn]) -> bool {
    if !flow.is_object() || !py::eq_int(get(flow, "version"), VERSION) {
        return false;
    }
    let until = match get(flow, "until") {
        Some(v) if truthy(v) => v.clone(),
        _ => Value::from(0),
    };
    if py::eq(&until, &Value::from(0)) {
        return true;
    }
    let Some(last) = int_field(Some(&until)).and_then(|u| turns.iter().find(|x| py::eq(&Value::from(x.index), &until) && x.index == u)) else {
        return false;
    };
    let steps = list(get(flow, "steps"));
    match steps.last() {
        Some(st) => get(st, "index").map(|i| py::eq(i, &until)).unwrap_or(false) && get(st, "fp") == Some(&s(&fingerprint(last))),
        None => false,
    }
}

/// 흐름에 턴 t를 이어 적은 새 흐름. runner는 프롬프트를 받아 모델 출력을 돌려준다(실패는 Err로 그대로 올린다)
pub fn advance<E>(flow: &Value, turns: &[Turn], t: &Turn, runner: &mut dyn FnMut(&str) -> Result<String, E>, tries: usize) -> Result<Value, E> {
    let base = if truthy(flow) && opt_truthy(get(flow, "steps")) { flow.clone() } else { empty() };
    let prompt = build_prompt(&base, turns, t);
    let mut got: Option<Value> = None;
    for _ in 0..tries {
        let text = runner(&prompt)?;
        if let Ok(v) = parse_step(&text, &base, turns, t) {
            got = Some(v);
            break;
        }
    }
    let mut got = match got {
        Some(g) => g,
        None => {
            let mut g = fallback(&base, t);
            g["step"]["fallback"] = Value::Bool(true);
            g
        }
    };
    got["step"]["resp"] = s(&response_mark(t));
    let empty_obj = json!({});
    let mut new = Obj::new();
    new.insert("version".into(), Value::from(VERSION));
    new.insert("first_goal".into(), Value::Object(obj_or_empty(get(&base, "first_goal"))));
    new.insert("current_goal".into(), Value::Object(obj_or_empty(get(&base, "current_goal"))));
    let mut steps: Vec<Value> = list(get(&base, "steps")).to_vec();
    steps.push(got["step"].clone());
    new.insert("steps".into(), Value::Array(steps));
    let reqs_change = get(&got, "requests").filter(|v| truthy(v)).unwrap_or(&empty_obj);
    new.insert("requests".into(), apply_requests(get(&base, "requests"), reqs_change, t));
    let asks_change = get(&got, "asks").filter(|v| truthy(v)).unwrap_or(&empty_obj);
    new.insert("asks".into(), apply_asks(get(&base, "asks"), asks_change, t));
    new.insert("until".into(), Value::from(t.index));
    if get(&got, "requests").is_none() {
        if let Some(Value::Array(st)) = new.get_mut("steps") {
            st.last_mut().unwrap()["requests_checked"] = Value::Bool(false);
        }
    }
    for key in ["requests_from", "asks_from"] {
        if let Some(v) = get(&base, key).filter(|v| truthy(v)) {
            new.insert(key.into(), v.clone());
        }
    }
    for key in ["first_goal", "current_goal"] {
        if let Some(v) = get(&got, key).filter(|v| truthy(v)) {
            new.insert(key.into(), v.clone());
        }
    }
    let prev: Obj = base.as_object().map(|o| o.iter().filter(|(k, _)| k.as_str() != "prev").map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
    new.insert("prev".into(), Value::Object(prev));
    Ok(Value::Object(new))
}

pub fn remaining(flow: &Value) -> Vec<Value> {
    list(get(flow, "requests")).iter().filter(|r| in_list(get(r, "state"), &LEFT_STATES)).cloned().collect()
}

pub fn shifts_count(flow: &Value) -> usize {
    list(get(flow, "steps")).iter().filter(|st| opt_truthy(get(st, "shift"))).count()
}
