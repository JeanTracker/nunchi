//! 의사결정·지나간 질문·결과 없음 (요구 이력 86, BUILD_PLAN §4.16).
//! 의사결정은 관계와 상관없이 정해진 요건·방침이고, 질문은 답이 없어도 지나가면 닫히며,
//! 조사는 했으나 원인을 못 찾은 요청은 남은 요청이 아니다.

use nunchi_engine::flow;
use nunchi_engine::transcript::Turn;
use serde_json::{json, Value};

fn turn(index: i64, request: &str, response: &str) -> Turn {
    Turn { index, time: String::new(), request: request.into(), response: response.into(), final_response: response.into(), added: vec![] }
}

fn turns() -> Vec<Turn> {
    vec![
        turn(1, "끄기 기능 만들어줘", "끄기를 만들까요, 상태도 함께 만들까요? 다른 세션에서 한 번 입력해 보시면 확인해 드리겠습니다."),
        turn(2, "둘 다 만들어줘", "끄기와 상태를 모두 만들었습니다. 다른 세션 문제는 앞서 설명한 경우였습니다. 흔들리는 시험은 재현되지 않았습니다."),
    ]
}

/// 첫 턴을 지난 흐름으로 만든다: 질문 Q1(끄기만/함께), Q2(다른 세션 입력)
fn after_first() -> Value {
    let ts = turns();
    let out = json!({"turn": {"index": 1, "label": "시작", "summary": "끄기 기능", "quote": "끄기 기능 만들어줘", "agent_summary": "물음",
                     "agent_quote": "끄기를 만들까요", "title": "", "decision": "", "decision_by": ""},
                     "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "first_goal": "끄기 기능 만들기",
                     "digest": "끄기 기능을 요청함",
                     "requests_new": [{"summary": "끄기 기능", "quote": "끄기 기능 만들어줘", "state": "open", "agent_quote": "", "pending_quote": ""}],
                     "asks_new": [{"summary": "끄기만 만들지 함께 만들지", "quote": "끄기를 만들까요, 상태도 함께 만들까요?", "kind": "결정"},
                                  {"summary": "다른 세션에서 입력해 보기", "quote": "다른 세션에서 한 번 입력해 보시면", "kind": "확인"}]});
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(&flow::empty(), &ts, &ts[0], &mut run, 1).unwrap()
}

fn second(out: Value) -> Value {
    let ts = turns();
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(&after_first(), &ts, &ts[1], &mut run, 1).unwrap()
}

fn base_turn2(extra: Value) -> Value {
    let mut o = json!({"turn": {"index": 2, "label": "구체화", "summary": "둘 다", "quote": "둘 다 만들어줘", "agent_summary": "만듦",
                       "agent_quote": "끄기와 상태를 모두 만들었습니다", "title": "", "decision": "", "decision_by": ""},
                       "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "digest": "끄기와 상태를 만듦"});
    for (k, v) in extra.as_object().unwrap() {
        if k == "turn" {
            for (tk, tv) in v.as_object().unwrap() {
                o["turn"][tk] = tv.clone();
            }
        } else {
            o[k] = v.clone();
        }
    }
    o
}

fn step(f: &Value, i: i64) -> Value {
    f["steps"].as_array().unwrap().iter().find(|s| s["index"] == i).cloned().unwrap()
}

#[test]
fn decisions_are_a_list_kept_outside_a_confirmed_turn_with_who_decided() {
    let f = second(base_turn2(json!({"decisions": [
        {"text": "끄기와 상태를 함께 만든다", "by": "user", "quote": "둘 다 만들어줘"},
        {"text": "끄면 분석도 멈춘다", "by": "agent", "quote": "만들어줘"}]})));
    let s = step(&f, 2);
    assert_eq!(s["label"], "구체화");                       // 관계가 확정이 아니어도
    assert_eq!(s["decisions"], json!([
        {"id": "D2-1", "text": "끄기와 상태를 함께 만든다", "by": "user", "quote": "둘 다 만들어줘", "replaces": [], "from": "", "to": ""},
        {"id": "D2-2", "text": "끄면 분석도 멈춘다", "by": "agent", "quote": "만들어줘", "replaces": [], "from": "", "to": ""}]));
    assert!(s.get("decision").is_none() && s.get("decision_by").is_none());   // 한 줄짜리 옛 칸은 쓰지 않는다
}

#[test]
fn a_decision_needs_who_decided_and_the_users_words_and_at_most_four_stay() {
    let f = second(base_turn2(json!({"decisions": [
        {"text": "누가 정했는지 모름", "by": "someone", "quote": "둘 다 만들어줘"},   // 모르는 값은 사용자로 채우지 않고 버린다
        {"text": "근거가 응답에만 있음", "by": "user", "quote": "끄기와 상태를 모두 만들었습니다"},   // 근거는 사용자 말에서
        {"text": "", "by": "user", "quote": "둘 다 만들어줘"}]})));
    assert_eq!(step(&f, 2)["decisions"], json!([]));
    let many: Vec<Value> = (1..=6).map(|i| json!({"text": format!("요건 {i}"), "by": "user", "quote": "둘 다"})).collect();
    let f = second(base_turn2(json!({"decisions": many})));
    assert_eq!(step(&f, 2)["decisions"].as_array().unwrap().len(), 4);
    let f = second(base_turn2(json!({})));
    assert_eq!(step(&f, 2)["decisions"], json!([]));         // 없으면 빈 목록 (칸은 늘 있다: 옛 흐름과 가르는 표시)
}

#[test]
fn a_question_closes_when_the_conversation_moved_past_it_with_a_quote_from_the_answer() {
    let f = second(base_turn2(json!({"asks_update": [
        {"id": "Q1", "state": "closed", "quote": "끄기와 상태를 모두 만들었습니다"},          // 응답에서 근거
        {"id": "Q2", "state": "closed", "quote": "앞서 설명한 경우였습니다"}]})));
    let asks = f["asks"].as_array().unwrap();
    assert_eq!(asks[0]["state"], "closed");
    assert_eq!(asks[1]["state"], "closed");
    assert_eq!(asks[0]["answered_at"], 2);
    // 답(answered)은 지금처럼 사용자 말에서만 근거를 받는다
    let f = second(base_turn2(json!({"asks_update": [{"id": "Q1", "state": "answered", "quote": "끄기와 상태를 모두 만들었습니다"}]})));
    assert_eq!(f["asks"][0]["state"], "open");
    // 근거가 어디에도 없으면 닫지 않는다
    let f = second(base_turn2(json!({"asks_update": [{"id": "Q1", "state": "closed", "quote": "지어낸 근거"}]})));
    assert_eq!(f["asks"][0]["state"], "open");
}

#[test]
fn a_closed_question_leaves_the_prompt_and_cannot_be_asked_again() {
    let f = second(base_turn2(json!({"asks_update": [{"id": "Q1", "state": "closed", "quote": "끄기와 상태를 모두 만들었습니다"}]})));
    let ts = vec![turns()[0].clone(), turns()[1].clone(), turn(3, "다음", "끄기만 만들까요?")];
    let p = flow::build_prompt(&f, &ts, &ts[2]);
    let asks = p.split("=== 지난 묻는 것").nth(1).unwrap().split("=== 지난 요청 기록").next().unwrap();
    assert!(!asks.contains("\"Q1\""), "{asks}");
    assert!(asks.contains("\"Q2\""), "{asks}");
    let out = json!({"turn": {"index": 3, "label": "질문", "summary": "다음", "quote": "다음", "agent_summary": "물음", "agent_quote": "끄기만 만들까요?",
                     "title": "", "decision": ""}, "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘",
                     "digest": "이어 물음", "asks_reask": ["Q1", "Q2"]});
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    let g = flow::advance(&f, &ts, &ts[2], &mut run, 1).unwrap();
    assert_eq!(g["asks"][0]["last_turn"], 1);                // 닫힌 질문은 다시 물어도 열지 않는다
    assert_eq!(g["asks"][1]["last_turn"], 3);
}

#[test]
fn an_investigation_without_a_result_is_not_a_remaining_request() {
    let f = second(base_turn2(json!({"requests_new": [
        {"summary": "흔들리는 시험 원인 찾기", "quote": "둘 다 만들어줘", "state": "no_result", "agent_quote": "흔들리는 시험은 재현되지 않았습니다", "pending_quote": ""}]})));
    let r: Vec<&Value> = f["requests"].as_array().unwrap().iter().filter(|r| r["summary"] == "흔들리는 시험 원인 찾기").collect();
    assert_eq!(r.len(), 1);
    assert_eq!(r[0]["state"], "no_result");
    assert_eq!(r[0]["agent_quote"], "흔들리는 시험은 재현되지 않았습니다");
    assert!(flow::remaining(&f).iter().all(|x| x["state"] != "no_result"));
    // 앞 요청을 결과 없음으로 바꿀 수도 있다
    let f = second(base_turn2(json!({"requests_update": [{"id": "R1", "state": "no_result", "agent_quote": "흔들리는 시험은 재현되지 않았습니다"}]})));
    assert_eq!(f["requests"][0]["state"], "no_result");
}

#[test]
fn the_rules_name_the_new_states() {
    for want in ["no_result", "closed", "decisions", "설계 요건", "결과물이 지켜야 할 것", "'좋아' 같은 승인 말 자체"] {
        assert!(flow::HEAD.contains(want), "{want}");
    }
}

/// 첫 턴에 결정 "상태 답은 다섯 줄로 한다"(D1-1)를 둔 흐름
fn with_first_decision() -> Value {
    let mut f = after_first();
    f["steps"][0]["decisions"] = json!([{"id": "D1-1", "text": "상태 답은 다섯 줄로 한다", "by": "user", "quote": "끄기 기능 만들어줘", "replaces": [], "from": "", "to": ""}]);
    f
}

fn second_on(base: &Value, out: Value) -> Value {
    let ts = turns();
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(base, &ts, &ts[1], &mut run, 1).unwrap()
}

#[test]
fn a_decision_that_replaces_an_earlier_one_records_what_changed_and_the_old_one_leaves_the_prompt() {
    let base = with_first_decision();
    let ts = turns();
    let p = flow::build_prompt(&base, &ts, &ts[1]);
    assert!(p.contains("=== 지난 의사결정 (유효한 것) ===") && p.contains("D1-1") && p.contains("상태 답은 다섯 줄로 한다"), "{p}");
    let f = second_on(&base, base_turn2(json!({"decisions": [
        {"text": "상태 답은 여섯 줄로 한다", "by": "user", "quote": "둘 다", "replaces": ["D1-1", "D9-9"], "from": "다섯 줄", "to": "여섯 줄"}]})));
    let d = &step(&f, 2)["decisions"][0];
    assert_eq!(d["replaces"], json!(["D1-1"]));              // 모르는 번호는 버린다
    assert_eq!((d["from"].as_str(), d["to"].as_str()), (Some("다섯 줄"), Some("여섯 줄")));
    assert!(flow::active_decisions(&f).iter().all(|a| a["id"] != "D1-1"));   // 바뀐 결정은 더는 유효하지 않다
    assert_eq!(step(&f, 1)["decisions"][0]["text"], "상태 답은 다섯 줄로 한다");   // 옛 단계는 고쳐 쓰지 않는다
    let ts3 = vec![ts[0].clone(), ts[1].clone(), turn(3, "다음", "다음 일")];
    assert!(!flow::build_prompt(&f, &ts3, &ts3[2]).split("=== 지난 의사결정").nth(1).unwrap().split("=== 지난 요청 기록").next().unwrap().contains("D1-1"));
}

#[test]
fn what_changed_is_dropped_when_it_is_not_in_the_old_and_new_text() {
    let base = with_first_decision();
    let f = second_on(&base, base_turn2(json!({"decisions": [
        {"text": "상태 답은 여섯 줄로 한다", "by": "user", "quote": "둘 다", "replaces": ["D1-1"], "from": "네 줄", "to": "여섯 줄"}]})));
    let d = &step(&f, 2)["decisions"][0];
    assert_eq!(d["replaces"], json!(["D1-1"]));
    assert_eq!((d["from"].as_str(), d["to"].as_str()), (Some(""), Some("")));   // 대조 실패면 비워 "바뀜"만 보인다
}

fn third_on(base: &Value, response: &str, out: Value) -> Value {
    let ts = vec![turns()[0].clone(), turns()[1].clone(), turn(3, "다음 일 해줘", response)];
    let mut o = json!({"turn": {"index": 3, "label": "구체화", "summary": "다음", "quote": "다음 일 해줘", "agent_summary": "함", "agent_quote": response.chars().take(8).collect::<String>(), "title": ""},
                       "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "digest": "이어 함"});
    for (k, v) in out.as_object().unwrap() { o[k] = v.clone(); }
    let mut it = vec![o.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(base, &ts, &ts[2], &mut run, 1).unwrap()
}

#[test]
fn a_broken_decision_needs_a_quote_from_the_answer_and_stays_open_until_fixed_or_replaced() {
    let base = second_on(&with_first_decision(), base_turn2(json!({})));
    // 근거 구절이 응답에 없으면 남지 않는다
    let f = third_on(&base, "상태 답을 여섯 줄로 늘렸습니다.", json!({"decision_checks": [{"id": "D1-1", "kind": "어김", "what": "여섯 줄로 늘림", "quote": "지어낸 구절"}]}));
    assert!(flow::open_checks(&f).is_empty());
    let f = third_on(&base, "상태 답을 여섯 줄로 늘렸습니다.", json!({"decision_checks": [
        {"id": "D1-1", "kind": "어김", "what": "여섯 줄로 늘림", "quote": "여섯 줄로 늘렸습니다"},
        {"id": "D9-9", "kind": "어김", "what": "없는 결정", "quote": "여섯 줄로 늘렸습니다"},
        {"id": "D1-1", "kind": "고침", "what": "열리기 전 고침", "quote": "여섯 줄로 늘렸습니다"}]}));
    assert_eq!(step(&f, 3)["checks"], json!([{"id": "D1-1", "kind": "어김", "what": "여섯 줄로 늘림", "quote": "여섯 줄로 늘렸습니다"}]));
    let open = flow::open_checks(&f);
    assert_eq!((open.len(), open[0]["turn"].as_i64()), (1, Some(3)));
    let ts = vec![turns()[0].clone(), turns()[1].clone(), turn(3, "다음 일 해줘", "상태 답을 여섯 줄로 늘렸습니다."), turn(4, "고쳐줘", "다섯 줄로 되돌렸습니다.")];
    let p = flow::build_prompt(&f, &ts, &ts[3]);
    assert!(p.split("=== 열린 빠뜨림 ===").nth(1).unwrap().split("=== 지난 요청 기록").next().unwrap().contains("D1-1"));
    // 다음 턴 응답이 고쳤다고 말하면 닫힌다
    let mut o = json!({"turn": {"index": 4, "label": "정정", "summary": "고침", "quote": "고쳐줘", "agent_summary": "되돌림", "agent_quote": "다섯 줄로 되돌렸습니다", "title": ""},
                       "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "digest": "고침"});
    o["decision_checks"] = json!([{"id": "D1-1", "kind": "고침", "what": "다섯 줄로 되돌림", "quote": "다섯 줄로 되돌렸습니다"}]);
    let mut it = vec![o.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    let g = flow::advance(&f, &ts, &ts[3], &mut run, 1).unwrap();
    assert!(flow::open_checks(&g).is_empty());
}

#[test]
fn replacing_the_decision_closes_its_open_omission() {
    let base = second_on(&with_first_decision(), base_turn2(json!({})));
    let f = third_on(&base, "상태 답을 여섯 줄로 늘렸습니다.", json!({"decision_checks": [{"id": "D1-1", "kind": "어김", "what": "여섯 줄로 늘림", "quote": "여섯 줄로 늘렸습니다"}]}));
    let ts = vec![turns()[0].clone(), turns()[1].clone(), turn(3, "다음 일 해줘", "상태 답을 여섯 줄로 늘렸습니다."), turn(4, "여섯 줄로 바꾸자", "여섯 줄로 두겠습니다.")];
    let mut o = json!({"turn": {"index": 4, "label": "확정", "summary": "바꿈", "quote": "여섯 줄로 바꾸자", "agent_summary": "둠", "agent_quote": "여섯 줄로 두겠습니다", "title": ""},
                       "topic_shift": false, "current_goal": "끄기 기능 만들기", "goal_turn": 1, "goal_quote": "끄기 기능 만들어줘", "digest": "바꿈"});
    o["decisions"] = json!([{"text": "상태 답은 여섯 줄로 한다", "by": "agent", "quote": "여섯 줄로 바꾸자", "replaces": ["D1-1"], "from": "다섯 줄", "to": "여섯 줄"}]);
    o["decision_checks"] = json!([{"id": "D1-1", "kind": "어김", "what": "또", "quote": "여섯 줄로 두겠습니다"}]);   // 같은 턴에 바꾼 결정은 판정하지 않는다
    let mut it = vec![o.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    let g = flow::advance(&f, &ts, &ts[3], &mut run, 1).unwrap();
    assert_eq!(step(&g, 4)["checks"], json!([]));
    assert!(flow::open_checks(&g).is_empty());                // 바뀐 결정의 빠뜨림은 닫힌다
}

#[test]
fn a_replaced_value_in_the_goal_follows_the_new_decision() {
    let mut base = with_first_decision();
    base["current_goal"]["text"] = json!("상태 답을 다섯 줄로 만들기");
    let mut out = base_turn2(json!({"decisions": [
        {"text": "상태 답은 여섯 줄로 한다", "by": "user", "quote": "둘 다", "replaces": ["D1-1"], "from": "다섯 줄", "to": "여섯 줄"}]}));
    out["current_goal"] = json!("상태 답을 다섯 줄로 만들기");
    let f = second_on(&base, out);
    assert_eq!(f["current_goal"]["text"], "상태 답을 여섯 줄로 만들기");   // 대상이 같아 지난 목표를 써도 옛 값은 바뀐다
    let mut out = base_turn2(json!({"decisions": [
        {"text": "상태 답은 여섯 줄로 한다", "by": "user", "quote": "둘 다", "replaces": ["D1-1"], "from": "네 줄", "to": "여섯 줄"}]}));
    out["current_goal"] = json!("상태 답을 다섯 줄로 만들기");
    assert_eq!(second_on(&base, out)["current_goal"]["text"], "상태 답을 다섯 줄로 만들기");   // 대조에 실패한 값은 쓰지 않는다
}

/// 앞 턴들의 단계: 각 턴의 fp만 있으면 된다 (다시 보냄 판정, 요구 이력 96)
fn steps_of(ts: &[Turn]) -> Value {
    Value::Array(ts.iter().map(|t| json!({"index": t.index, "fp": flow::fingerprint(t)})).collect())
}

fn rows(v: &Value) -> Vec<(String, String, i64)> {
    v.as_array().unwrap().iter()
        .map(|r| (r["id"].as_str().unwrap().to_string(), r["state"].as_str().unwrap_or("").to_string(), r["by_turn"].as_i64().unwrap_or(0)))
        .collect()
}

#[test]
fn a_resent_request_continues_the_earlier_one() {
    // 1턴: 응답 없이 끊긴 요청 → open. 2턴: 같은 글을 다시 보내 답을 받음
    let t1 = turn(1, "이 프로젝트에 적용할 수 있어?", "");
    let t2 = turn(2, "이 프로젝트에  적용할 수 있어?", "적용은 됩니다");
    let first = flow::apply_requests(None, &json!({"new": [
        {"summary": "적용 검토", "quote": "이 프로젝트에 적용할 수 있어?", "state": "open", "agent_quote": ""}]}), &t1, None);
    let resent = json!({"new": [
        {"summary": "적용 가능한지", "quote": "이 프로젝트에  적용할 수 있어?", "state": "addressed", "agent_quote": "적용은 됩니다"},
        {"summary": "다른 요청", "quote": "패널도 고쳐줘", "state": "open", "agent_quote": ""}]});
    let got = flow::apply_requests(Some(&first), &resent, &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 2), ("R2".into(), "open".into(), 2)]);   // 같은 요청은 새 줄을 만들지 않는다
    assert_eq!(got[0]["from_turn"], 1);                                // 처음 말한 턴은 그대로
    assert_eq!(got[0]["agent_quote"], "적용은 됩니다");
}

#[test]
fn a_resent_request_that_is_still_open_keeps_one_row() {
    let t1 = turn(1, "로그 정리해줘", "");
    let t2 = turn(2, "로그 정리해줘", "");
    let first = flow::apply_requests(None, &json!({"new": [{"summary": "로그 정리", "quote": "로그 정리해줘", "state": "open"}]}), &t1, None);
    let got = flow::apply_requests(Some(&first), &json!({"new": [{"summary": "로그", "quote": "로그 정리해줘", "state": "open"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "open".into(), 1)]);
}

#[test]
fn two_requests_split_in_one_turn_stay_two() {
    // 실제 사례: 한 발화를 둘로 나눈 요청이 같은 구절을 쓴다. 같은 배치끼리는 합치지 않는다
    let t = turn(11, "1,2번부터 확인해줘.", "1번은 확인했고 2번은 원인을 못 찾았습니다");
    let got = flow::apply_requests(None, &json!({"new": [
        {"summary": "명령 즉시 실행 확인", "quote": "1,2번부터 확인해줘.", "state": "addressed", "agent_quote": "1번은 확인했고"},
        {"summary": "흔들리는 시험 원인 찾기", "quote": "1,2번부터 확인해줘.", "state": "no_result", "agent_quote": "2번은 원인을 못 찾았습니다"}]}), &t, None);
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 11), ("R2".into(), "no_result".into(), 11)]);
}

#[test]
fn resending_requests_split_in_one_turn_continues_each_row() {
    // 앞 턴에 한 발화를 둘로 나눈 요청이 둘 다 진행 중이고, 같은 글을 다시 보내 둘 다 다뤄짐
    let t1 = turn(1, "기획 및 GUI 반영해줘", "");
    let t2 = turn(2, "기획 및 GUI 반영해줘", "둘 다 반영했습니다");
    let first = flow::apply_requests(None, &json!({"new": [
        {"summary": "기획 반영", "quote": "기획 및 GUI 반영해줘", "state": "in_progress"},
        {"summary": "GUI 반영", "quote": "기획 및 GUI 반영해줘", "state": "in_progress"}]}), &t1, None);
    let got = flow::apply_requests(Some(&first), &json!({"new": [
        {"summary": "기획 반영", "quote": "기획 및 GUI 반영해줘", "state": "addressed", "agent_quote": "둘 다 반영했습니다"},
        {"summary": "GUI 반영", "quote": "기획 및 GUI 반영해줘", "state": "addressed", "agent_quote": "둘 다 반영했습니다"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 2), ("R2".into(), "addressed".into(), 2)]);
}

#[test]
fn the_same_short_request_on_another_topic_is_a_new_row() {
    // 실제 사례: 같은 짧은 말로 다른 대상을 시킴. 앞 줄이 열려 있어도 발화 첫머리가 다르면 새 줄
    let t1 = turn(28, "로그인 고쳤어. advisor 리뷰해줘.", "");
    let t2 = turn(30, "결제 화면 고쳤어. advisor 리뷰해줘.", "");
    let first = flow::apply_requests(None, &json!({"new": [{"summary": "로그인 리뷰", "quote": "advisor 리뷰해줘.", "state": "in_progress"}]}), &t1, None);
    let got = flow::apply_requests(Some(&first), &json!({"new": [{"summary": "결제 리뷰", "quote": "advisor 리뷰해줘.", "state": "open"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "in_progress".into(), 28), ("R2".into(), "open".into(), 30)]);
}

#[test]
fn a_request_asked_again_after_it_was_done_is_a_new_row() {
    // 실제 사례: 다룬 명령을 20턴 뒤에 일부러 다시 시킴. 발화가 같아도 앞 줄이 끝났으면 새 줄
    let t1 = turn(39, "플러그인 업데이트 해줘", "업데이트했습니다");
    let t2 = turn(59, "플러그인 업데이트 해줘", "");
    let first = flow::apply_requests(None, &json!({"new": [{"summary": "업데이트", "quote": "플러그인 업데이트 해줘", "state": "addressed"}]}), &t1, None);
    let got = flow::apply_requests(Some(&first), &json!({"new": [{"summary": "다시 업데이트", "quote": "플러그인 업데이트 해줘", "state": "open"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 39), ("R2".into(), "open".into(), 59)]);
}

#[test]
fn an_update_in_the_same_turn_wins_over_a_resent_copy() {
    let t1 = turn(1, "테스트 고쳐줘", "");
    let t2 = turn(2, "테스트 고쳐줘", "고쳤습니다");
    let first = flow::apply_requests(None, &json!({"new": [{"summary": "테스트", "quote": "테스트 고쳐줘", "state": "open"}]}), &t1, None);
    let got = flow::apply_requests(Some(&first), &json!({
        "updates": [{"id": "R1", "state": "addressed", "agent_quote": "고쳤습니다"}],
        "new": [{"summary": "테스트", "quote": "테스트 고쳐줘", "state": "in_progress", "agent_quote": "고치는 중"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 2)]);
    assert_eq!(got[0]["agent_quote"], "고쳤습니다");
}

#[test]
fn merging_a_resent_request_clears_tool_failed() {
    let t1 = turn(1, "빌드 돌려줘", "");
    let t2 = turn(2, "빌드 돌려줘", "빌드했습니다");
    let first = json!([{"id": "R1", "summary": "빌드", "quote": "빌드 돌려줘", "state": "open", "from_turn": 1, "by_turn": 1, "tool_failed": true}]);
    let got = flow::apply_requests(Some(&first), &json!({"new": [{"summary": "빌드", "quote": "빌드 돌려줘", "state": "addressed", "agent_quote": "빌드했습니다"}]}), &t2, Some(&steps_of(&[t1])));
    assert_eq!(rows(&got), vec![("R1".into(), "addressed".into(), 2)]);
    assert!(got[0].get("tool_failed").is_none());
}

#[test]
fn the_prompt_says_not_to_repeat_a_known_request() {
    assert!(flow::HEAD.contains("아직 다루지 않았거나 진행 중인 같은 요청을 다시 보낸 것"));
    assert!(flow::HEAD.contains("이미 다룬 요청을 사용자가 다시 시키면 새 요청으로 넣는다"));
}
