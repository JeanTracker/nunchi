//! `/nunchi build` (요구 이력 93): 지금까지 대화를 지금 분석한다. 분석이 없거나 옛 엔진 형식이면 처음부터,
//! 아니면 아직 분석하지 않은 응답만. 새 엔진의 대기 요청은 옛 분석기가 읽지 않는 `.job`에 둔다.

use nunchi_engine::flow;
use nunchi_engine::transcript::Turn;
use nunchi_engine::worker;
use serde_json::{json, Value};

fn turn(index: i64, request: &str, response: &str) -> Turn {
    Turn { index, time: String::new(), request: request.into(), response: response.into(), final_response: response.into(), added: vec![] }
}

fn turns(n: i64) -> Vec<Turn> {
    (1..=n).map(|i| turn(i, &format!("요청 {i} 해줘"), &format!("요청 {i}을 했습니다."))).collect()
}

/// 지금 엔진으로 첫 턴까지 분석한 흐름
fn new_flow(ts: &[Turn]) -> Value {
    let out = json!({"turn": {"index": 1, "label": "시작", "summary": "요청 1", "quote": "요청 1 해줘", "agent_summary": "함",
                     "agent_quote": "요청 1을 했습니다", "title": "", "decision": "", "decision_by": ""},
                     "topic_shift": false, "current_goal": "요청 처리", "goal_turn": 1, "goal_quote": "요청 1 해줘", "first_goal": "요청 처리",
                     "digest": "요청 1", "requests_new": [], "asks_new": []});
    let mut it = vec![out.to_string()].into_iter();
    let mut run = |_: &str| it.next().ok_or(());
    flow::advance(&flow::empty(), ts, &ts[0], &mut run, 1).unwrap()
}

#[test]
fn a_session_never_analyzed_is_analyzed_from_the_start() {
    let p = worker::build_plan(None, &turns(5));
    assert_eq!(p, json!({"total": 5, "done": 0, "todo": 5, "fresh": true}));
}

#[test]
fn a_flow_by_the_current_engine_only_adds_the_answers_not_analyzed_yet() {
    let ts = turns(4);
    let f = new_flow(&ts);
    assert!(f["steps"][0].get("decisions").is_some(), "지금 엔진은 단계마다 결정 목록을 적는다");
    let p = worker::build_plan(Some(&json!({"flow": f})), &ts);
    assert_eq!(p, json!({"total": 4, "done": 1, "todo": 3, "fresh": false}));
}

#[test]
fn an_up_to_date_flow_has_nothing_to_do() {
    let ts = turns(1);
    let p = worker::build_plan(Some(&json!({"flow": new_flow(&ts)})), &ts);
    assert_eq!(p, json!({"total": 1, "done": 1, "todo": 0, "fresh": false}));
}

#[test]
fn a_flow_written_by_the_old_engine_is_rebuilt_from_the_start() {
    // 0.5.0 엔진의 단계에는 결정 목록·빠뜨림 판정이 없다 (이 세션의 #1~#44가 그랬다)
    let ts = turns(3);
    let mut f = new_flow(&ts);
    let st = f["steps"][0].as_object_mut().unwrap();
    st.remove("decisions");
    st.remove("checks");
    let p = worker::build_plan(Some(&json!({"flow": f})), &ts);
    assert_eq!(p, json!({"total": 3, "done": 0, "todo": 3, "fresh": true}));
}

#[test]
fn new_requests_go_to_job_files_the_old_analyzer_does_not_read() {
    let d = std::env::temp_dir().join(format!("nunchi-build-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    worker::enqueue(&d, "s1", "/t.jsonl", "2026-11-19T00:00:02.000Z", true, "nunchi").unwrap();
    assert!(d.join("queue/s1.job").exists() && !d.join("queue/s1.json").exists()); // 옛 훅의 .json을 새 분석기가 읽는 것은 worker_rules가 본다
    let _ = std::fs::remove_dir_all(&d);
}
