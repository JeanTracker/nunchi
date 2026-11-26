//! 버린 항목 기록 (요구 이력 102).
//! 엔진이 모델 출력에서 근거가 맞지 않아 버린 요청·질문 항목을 그 턴의 단계에 남긴다.
//! 버리는 기준은 그대로이고, 무엇을 왜 버렸는지만 적는다.

use nunchi_engine::flow;
use nunchi_engine::transcript::Turn;
use serde_json::{json, Value};

fn turn(index: i64, request: &str, response: &str) -> Turn {
    Turn { index, time: String::new(), request: request.into(), response: response.into(), final_response: response.into(), added: vec![] }
}

fn turns() -> Vec<Turn> {
    vec![
        turn(1, "끄기 기능 만들어줘", "끄기를 만들까요, 상태도 함께 만들까요? 다른 세션에서 한 번 입력해 보시면 확인해 드리겠습니다."),
        turn(2, "둘 다 만들어줘", "끄기와 상태를 모두 만들었습니다. 다른 세션 문제는 앞서 설명한 경우였습니다."),
    ]
}

fn run_one(flow_in: &Value, t: &Turn, out: Value) -> Value {
    let ts = turns();
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(flow_in, &ts, t, &mut run, 1).unwrap()
}

/// 첫 턴을 지난 흐름: 요청 R1(끄기 기능, open), 질문 Q1·Q2
fn after_first() -> Value {
    let ts = turns();
    run_one(&flow::empty(), &ts[0], json!({
        "turn": {"index": 1, "label": "시작", "summary": "끄기 기능", "quote": "끄기 기능 만들어줘", "agent_summary": "물음",
                 "agent_quote": "끄기를 만들까요", "title": ""},
        "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "first_goal": "끄기 기능 만들기",
        "digest": "끄기 기능을 요청함",
        "requests_new": [{"summary": "끄기 기능", "quote": "끄기 기능 만들어줘", "state": "open"}],
        "asks_new": [{"summary": "끄기만 만들지 함께 만들지", "quote": "끄기를 만들까요, 상태도 함께 만들까요?", "kind": "결정"},
                     {"summary": "다른 세션에서 입력해 보기", "quote": "다른 세션에서 한 번 입력해 보시면", "kind": "확인"}]}))
}

fn second(extra: Value) -> Value {
    let mut o = json!({"turn": {"index": 2, "label": "구체화", "summary": "둘 다", "quote": "둘 다 만들어줘", "agent_summary": "만듦",
                       "agent_quote": "끄기와 상태를 모두 만들었습니다", "title": ""},
                       "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "digest": "끄기와 상태를 만듦"});
    for (k, v) in extra.as_object().unwrap() {
        o[k] = v.clone();
    }
    run_one(&after_first(), &turns()[1], o)
}

fn step2(f: &Value) -> Value {
    f["steps"].as_array().unwrap().iter().find(|s| s["index"] == 2).cloned().unwrap()
}

fn request(f: &Value, id: &str) -> Value {
    f["requests"].as_array().unwrap().iter().find(|r| r["id"] == id).cloned().unwrap()
}

#[test]
fn an_update_whose_evidence_is_not_in_the_answer_is_dropped_and_recorded() {
    let f = second(json!({"requests_update": [{"id": "R1", "state": "addressed", "agent_quote": "끄기를 완성해 배포했습니다"}]}));
    assert_eq!(request(&f, "R1")["state"], "open");   // 버리는 기준은 그대로
    assert_eq!(step2(&f)["dropped"], json!([
        {"what": "request_update", "id": "R1", "why": "agent_quote_not_in_answer", "quote": "끄기를 완성해 배포했습니다"}]));
}

#[test]
fn an_unknown_id_and_a_bad_state_are_recorded_with_their_reason() {
    let f = second(json!({"requests_update": [
        {"id": "R9", "state": "addressed", "agent_quote": "끄기와 상태를 모두 만들었습니다"},
        {"id": "R1", "state": "done", "agent_quote": "끄기와 상태를 모두 만들었습니다"},
        "R1"]}));
    assert_eq!(request(&f, "R1")["state"], "open");
    assert_eq!(step2(&f)["dropped"], json!([
        {"what": "request_update", "id": "R9", "why": "unknown_id", "quote": "끄기와 상태를 모두 만들었습니다"},
        {"what": "request_update", "id": "R1", "why": "bad_state", "quote": "끄기와 상태를 모두 만들었습니다"},
        {"what": "request_update", "why": "not_object"}]));
}

#[test]
fn a_new_request_quoting_words_the_user_did_not_say_is_recorded() {
    let f = second(json!({"requests_new": [
        {"summary": "상태 표시", "quote": "상태도 보여줘", "state": "open"},
        {"summary": "둘 다", "quote": "둘 다 만들어줘", "state": "addressed", "agent_quote": "모두 배포했습니다"}]}));
    assert_eq!(f["requests"].as_array().unwrap().len(), 1);
    assert_eq!(step2(&f)["dropped"], json!([
        {"what": "request_new", "why": "quote_not_in_user_text", "quote": "상태도 보여줘"},
        {"what": "request_new", "why": "agent_quote_not_in_answer", "quote": "모두 배포했습니다"}]));
}

#[test]
fn dropped_question_items_are_recorded_too() {
    let f = second(json!({
        "asks_new": [{"summary": "없는 질문", "quote": "어느 쪽으로 할까요?", "kind": "결정"}],
        "asks_reask": ["Q9"],
        "asks_update": [{"id": "Q1", "state": "answered", "quote": "하나만 만들어"}]}));
    assert_eq!(step2(&f)["dropped"], json!([
        {"what": "ask_new", "why": "quote_not_in_answer", "quote": "어느 쪽으로 할까요?"},
        {"what": "ask_reask", "id": "Q9", "why": "unknown_or_closed"},
        {"what": "ask_update", "id": "Q1", "why": "quote_not_found", "quote": "하나만 만들어"}]));
}

#[test]
fn question_updates_say_which_check_failed() {
    let f = second(json!({
        "asks_new": ["어느 쪽으로 할까요?"],
        "asks_update": [{"id": "Q9", "state": "answered", "quote": "둘 다 만들어줘"},
                        {"id": "Q1", "state": "maybe", "quote": "둘 다 만들어줘"},
                        "Q1"]}));
    assert_eq!(step2(&f)["dropped"], json!([
        {"what": "ask_new", "why": "not_object"},
        {"what": "ask_update", "id": "Q9", "why": "unknown_id", "quote": "둘 다 만들어줘"},
        {"what": "ask_update", "id": "Q1", "why": "bad_state", "quote": "둘 다 만들어줘"},
        {"what": "ask_update", "why": "not_object"}]));
}

#[test]
fn a_turn_with_nothing_dropped_has_no_dropped_field() {
    let f = second(json!({"requests_update": [{"id": "R1", "state": "addressed", "agent_quote": "끄기와 상태를 모두 만들었습니다"}]}));
    assert_eq!(request(&f, "R1")["state"], "addressed");
    assert!(step2(&f).get("dropped").is_none() && step2(&f).get("dropped_total").is_none());
    assert!(after_first()["steps"][0].get("dropped").is_none());
}

#[test]
fn at_most_twenty_dropped_items_are_kept_and_quotes_and_ids_are_cut() {
    let long = "가".repeat(120);
    let f = second(json!({"asks_reask": ["Q".repeat(100)]}));
    assert_eq!(step2(&f)["dropped"][0]["id"].as_str().unwrap().chars().count(), 40);
    let many: Vec<Value> = (0..25).map(|i| json!({"id": format!("R{}", 100 + i), "state": "addressed", "agent_quote": long})).collect();
    let f = second(json!({"requests_update": many}));
    let d = step2(&f)["dropped"].as_array().unwrap().clone();
    assert_eq!(d.len(), 20);
    assert_eq!(step2(&f)["dropped_total"], 25);   // 상한을 넘으면 총수를 함께 남긴다
    assert_eq!(d[0]["id"], "R100");
    assert_eq!(d[0]["quote"].as_str().unwrap().chars().count(), 80);
}
