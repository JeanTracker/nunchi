//! 작업 중에 덧붙인 요청과 질문 창에서 고른 답 (요구 이력 81, BUILD_PLAN §4.15).
//! 둘 다 그 턴의 사용자 말로 읽고, 턴 번호와 요청 글(지문)은 바꾸지 않는다.

use nunchi_engine::{flow, transcript};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

fn tmp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("nunchi-added-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

fn write_lines(path: &Path, rows: &[Value]) {
    std::fs::write(path, rows.iter().map(|r| r.to_string() + "\n").collect::<String>()).unwrap();
}

fn user(text: &str, ts: &str) -> Value {
    json!({"type": "user", "timestamp": ts, "origin": {"kind": "human"}, "message": {"role": "user", "content": text}})
}

fn answer(text: &str, ts: &str) -> Value {
    json!({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}})
}

fn tool_use(id: &str, name: &str, input: Value, ts: &str) -> Value {
    json!({"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": id, "name": name, "input": input}]}})
}

fn tool_result(id: &str, result: Value, is_error: bool, ts: &str) -> Value {
    json!({"type": "user", "timestamp": ts, "toolUseResult": result,
           "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": id, "content": "done", "is_error": is_error}]}})
}

/// Claude Code가 작업 중 입력을 남기는 모양 (2.1.322~2.1.327 기록에서 본 것)
fn queued(prompt: &str, kind: &str, ts: &str) -> Value {
    json!({"type": "attachment", "timestamp": ts,
           "attachment": {"type": "queued_command", "prompt": prompt, "commandMode": "prompt", "origin": {"kind": kind}}})
}

fn parse(name: &str, rows: &[Value]) -> Vec<transcript::Turn> {
    let d = tmp(name);
    let tr = d.join("t.jsonl");
    write_lines(&tr, rows);
    let turns = transcript::parse_turns(&tr, "").unwrap();
    let _ = std::fs::remove_dir_all(&d);
    turns
}

#[test]
fn a_request_typed_while_the_agent_works_joins_that_turn() {
    let turns = parse("queued", &[
        user("패널 펼치기를 버튼으로 바꿔줘", "2026-11-18T01:00:00.000Z"),
        tool_use("t1", "Bash", json!({}), "2026-11-18T01:00:05.000Z"),
        tool_result("t1", json!({"stdout": "ok"}), false, "2026-11-18T01:00:06.000Z"),
        queued("단축키는 ] 펼치기 [ 줄이기로 해줘", "human", "2026-11-18T01:00:07.000Z"),
        queued("<task-notification>done</task-notification>", "task-notification", "2026-11-18T01:00:08.000Z"),
        queued("<agent-message from=\"a1\">report</agent-message>", "peer", "2026-11-18T01:00:09.000Z"),
        answer("버튼과 단축키를 바꿨습니다", "2026-11-18T01:00:30.000Z"),
        user("좋아", "2026-11-18T01:01:00.000Z"),
        answer("네", "2026-11-18T01:01:05.000Z"),
    ]);
    assert_eq!(turns.len(), 2, "덧붙인 요청이 새 턴을 만들지 않는다");
    assert_eq!(turns[0].request, "패널 펼치기를 버튼으로 바꿔줘", "요청 글(지문)은 그대로");
    assert_eq!(turns[0].added, vec!["(작업 중에 덧붙인 요청) 단축키는 ] 펼치기 [ 줄이기로 해줘".to_string()]);
    assert!(turns[1].added.is_empty());
    assert!(turns[0].said().contains("단축키는 ] 펼치기"));
}

#[test]
fn a_request_typed_after_the_turn_closed_reopens_it_so_the_reply_joins() {
    // 363fc5ef: 응답이 끝난 뒤 작업 알림이 에이전트를 다시 깨우고, 그 사이 사람이 요청을 넣었다.
    // 턴을 다시 열어야 그 요청에 대한 응답이 붙고(응답이 자라) 마지막 턴을 다시 분석한다. 턴 번호는 그대로
    let notice = json!({"type": "user", "timestamp": "2026-11-18T01:00:40.000Z", "origin": {"kind": "task-notification"},
                        "message": {"role": "user", "content": "<task-notification>build done</task-notification>"}});
    let turns = parse("reopen", &[
        user("빌드 돌려줘", "2026-11-18T01:00:00.000Z"),
        answer("빌드를 시작했습니다", "2026-11-18T01:00:30.000Z"),
        notice,
        answer("빌드가 끝났습니다", "2026-11-18T01:00:45.000Z"),
        queued("분석중 문구도 넣어줘", "human", "2026-11-18T01:00:50.000Z"),
        answer("분석중 문구를 넣었습니다", "2026-11-18T01:01:10.000Z"),
    ]);
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0].added, vec!["(작업 중에 덧붙인 요청) 분석중 문구도 넣어줘".to_string()]);
    assert!(turns[0].response.ends_with("분석중 문구를 넣었습니다"), "{}", turns[0].response);
}

#[test]
fn a_sidechain_or_meta_queued_command_is_not_the_users() {
    let mut side = queued("하위 에이전트 쪽 글", "human", "2026-11-18T01:00:07.000Z");
    side["isSidechain"] = json!(true);
    let mut meta = queued("시스템이 넣은 글", "human", "2026-11-18T01:00:08.000Z");
    meta["attachment"]["isMeta"] = json!(true);
    let turns = parse("queued-side", &[user("고쳐줘", "2026-11-18T01:00:00.000Z"), side, meta, answer("고쳤습니다", "2026-11-18T01:00:30.000Z")]);
    assert!(turns[0].added.is_empty(), "{:?}", turns[0].added);
}

#[test]
fn the_answer_picked_in_a_question_dialog_joins_that_turn() {
    let q = "글자가 겹칩니다. 어떻게 고칠까요?";
    let input = json!({"questions": [{"question": q, "header": "고칠 방법", "multiSelect": false,
                                      "options": [{"label": "iTerm 설정 바꾸기"}, {"label": "앱에서 기호 뒤 한 칸 띄우기"}]}]});
    let result = json!({"questions": input["questions"], "answers": {q: "앱에서 기호 뒤 한 칸 띄우기"},
                        "annotations": {q: {"notes": "Claude Code 화면은 그대로 둬"}}});
    let turns = parse("dialog", &[
        user("글자 겹침 고쳐줘", "2026-11-18T01:00:00.000Z"),
        tool_use("q1", "AskUserQuestion", input.clone(), "2026-11-18T01:00:05.000Z"),
        tool_result("q1", result, false, "2026-11-18T01:00:20.000Z"),
        // Esc로 닫은 창: 답이 아니다
        tool_use("q2", "AskUserQuestion", input, "2026-11-18T01:00:21.000Z"),
        tool_result("q2", json!("User declined to answer questions"), true, "2026-11-18T01:00:22.000Z"),
        answer("기호 뒤에 한 칸을 띄우게 했습니다", "2026-11-18T01:00:30.000Z"),
    ]);
    assert_eq!(turns.len(), 1);
    assert_eq!(turns[0].added, vec![format!("(질문 창에서 고름) 고칠 방법: {q} → 앱에서 기호 뒤 한 칸 띄우기 (메모: Claude Code 화면은 그대로 둬)")]);
    assert_eq!(turns[0].response, "기호 뒤에 한 칸을 띄우게 했습니다", "도구 결과는 응답이 되지 않는다");
}

#[test]
fn the_prompt_shows_the_additions_under_the_request_and_the_head_explains_them() {
    let turns = parse("prompt", &[
        user("패널 펼치기를 버튼으로 바꿔줘", "2026-11-18T01:00:00.000Z"),
        queued("단축키는 ] 펼치기 [ 줄이기로 해줘", "human", "2026-11-18T01:00:07.000Z"),
        answer("바꿨습니다", "2026-11-18T01:00:30.000Z"),
    ]);
    let p = flow::build_prompt(&flow::empty(), &turns, &turns[0]);
    assert!(p.contains("[턴 1] 요청: 패널 펼치기를 버튼으로 바꿔줘\n  (작업 중에 덧붙인 요청) 단축키는 ] 펼치기 [ 줄이기로 해줘\n  응답: 바꿨습니다"), "{p}");
    let head = &p[..p.find("=== 지난 흐름 ===").unwrap()];
    assert!(head.contains("(작업 중에 덧붙인 요청)") && head.contains("(질문 창에서 고름)"));
}

#[test]
fn quotes_may_come_from_the_additions() {
    let turns = parse("quote", &[
        user("패널 펼치기를 버튼으로 바꿔줘", "2026-11-18T01:00:00.000Z"),
        queued("단축키는 ] 펼치기 [ 줄이기로 해줘", "human", "2026-11-18T01:00:07.000Z"),
        answer("버튼으로 바꿨습니다. 단축키는 아직입니다.", "2026-11-18T01:00:30.000Z"),
    ]);
    let out = json!({"turn": {"index": 1, "label": "시작", "summary": "버튼과 단축키", "quote": "패널 펼치기를 버튼으로", "agent_summary": "버튼만 바꿈",
                              "agent_quote": "버튼으로 바꿨습니다", "title": "", "decision": ""},
                     "topic_shift": false, "current_goal": "패널 펼치기", "goal_turn": 1, "goal_quote": "패널 펼치기를 버튼으로", "first_goal": "패널 펼치기", "digest": "버튼",
                     "requests_new": [{"summary": "버튼으로", "quote": "패널 펼치기를 버튼으로", "state": "addressed", "agent_quote": "버튼으로 바꿨습니다", "pending_quote": ""},
                                      {"summary": "단축키 ] [", "quote": "단축키는 ] 펼치기 [ 줄이기로", "state": "open", "agent_quote": "", "pending_quote": ""}]}).to_string();
    let got = flow::parse_step(&out, &flow::empty(), &turns, &turns[0]).unwrap_or_else(|_| panic!("덧붙인 요청에서 따온 인용도 원문이다"));
    assert!(got.to_string().contains("단축키 ] ["), "덧붙인 요청이 요청 기록에 남는다: {got}");
}

#[test]
fn the_fingerprint_does_not_change_so_old_flows_stay_valid() {
    let plain = parse("fp-a", &[user("패널 펼치기를 버튼으로 바꿔줘", "2026-11-18T01:00:00.000Z"), answer("바꿨습니다", "2026-11-18T01:00:30.000Z")]);
    let with = parse("fp-b", &[user("패널 펼치기를 버튼으로 바꿔줘", "2026-11-18T01:00:00.000Z"),
                               queued("단축키도", "human", "2026-11-18T01:00:07.000Z"), answer("바꿨습니다", "2026-11-18T01:00:30.000Z")]);
    assert_eq!(flow::fingerprint(&plain[0]), flow::fingerprint(&with[0]));
}
