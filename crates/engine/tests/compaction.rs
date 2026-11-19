//! 압축(compact)을 넘는 대화 기록 읽기 (요구 이력 94). Claude Code는 압축해도 기록 파일 앞부분을 지우지 않고
//! 경계 줄과 요약 줄을 덧붙인다. 요약 줄은 턴이 아니고, 응답 도중 압축되면 그 턴의 답은 압축 뒤에도 이어진다.

use nunchi_engine::transcript;
use serde_json::{json, Value};

fn user(text: &str, ts: &str) -> Value {
    json!({"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts})
}
fn answer(text: &str, ts: &str) -> Value {
    json!({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, "timestamp": ts})
}
fn tool(ts: &str) -> Vec<Value> {
    vec![json!({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}, "timestamp": ts}),
         json!({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}, "timestamp": ts})]
}
fn boundary(ts: &str) -> Vec<Value> {
    vec![json!({"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted", "timestamp": ts}),
         json!({"type": "user", "isCompactSummary": true, "isVisibleInTranscriptOnly": true,
                "message": {"role": "user", "content": "This session is being continued from a previous conversation that ran out of context."}, "timestamp": ts})]
}

fn parse(name: &str, rows: Vec<Value>) -> Vec<transcript::Turn> {
    let d = std::env::temp_dir().join(format!("nunchi-compact-{}-{name}", std::process::id()));
    let _ = std::fs::create_dir_all(&d);
    let p = d.join("t.jsonl");
    std::fs::write(&p, rows.iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
    let t = transcript::parse_turns(&p, "").unwrap();
    let _ = std::fs::remove_dir_all(&d);
    t
}

#[test]
fn a_compaction_mid_answer_keeps_the_answer_after_it() {
    let mut rows = vec![user("긴 작업을 해줘", "2026-01-01T00:00:10.000Z"), answer("시작합니다.", "2026-01-01T00:00:20.000Z")];
    rows.extend(tool("2026-01-01T00:00:30.000Z"));
    rows.extend(boundary("2026-01-01T00:00:40.000Z"));
    rows.push(answer("작업을 마쳤습니다. 결과는 이렇습니다.", "2026-01-01T00:00:50.000Z"));
    let t = parse("mid", rows);
    assert_eq!(t.len(), 1, "요약 줄은 턴이 아니다");
    assert!(t[0].response.contains("작업을 마쳤습니다"), "압축 뒤의 답이 빠졌다: {:?}", t[0].response);
    assert!(t[0].final_response.contains("작업을 마쳤습니다"));
}

#[test]
fn a_compaction_between_answers_keeps_every_turn_numbered_from_the_start() {
    let mut rows = vec![user("설치 확인해줘", "2026-01-01T00:00:10.000Z"), answer("설치돼 있습니다.", "2026-01-01T00:00:20.000Z"),
                        user("문서도 봐줘", "2026-01-01T00:00:30.000Z"), answer("문서를 봤습니다.", "2026-01-01T00:00:40.000Z")];
    rows.extend(boundary("2026-01-01T00:00:50.000Z"));
    rows.push(user("이어서 고쳐줘", "2026-01-01T00:01:00.000Z"));
    rows.push(answer("고쳤습니다.", "2026-01-01T00:01:10.000Z"));
    let t = parse("idle", rows);
    assert_eq!(t.iter().map(|x| (x.index, x.request.as_str())).collect::<Vec<_>>(),
               vec![(1, "설치 확인해줘"), (2, "문서도 봐줘"), (3, "이어서 고쳐줘")]);
    assert_eq!(t[1].response, "문서를 봤습니다.", "압축 요약이 앞 턴의 답에 붙지 않는다");
}
