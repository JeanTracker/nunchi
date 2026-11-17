//! 시험용 가짜 `claude -p` (`--features dev`). 프롬프트의 '새 턴'에서 원문을 따 와 근거가 맞는 답을 낸다.
//!
//! FAKE_CLAUDE_SCRIPT: {"default": 모드, "turns": {"3": 모드}} 파일. 모드:
//!   ok, shift, progress(진행 중), ask(묻기), blanket(앞 물음 통째 승인), garbage(JSON 아님),
//!   fail(종료 코드 1), fail_once(그 턴 첫 호출만 1), garbage_once, slow(3초 뒤 ok)
//! FAKE_CLAUDE_STATE: 호출 기록 폴더. log에 '턴 모드 프롬프트해시'를 한 줄씩 남긴다.

use serde_json::{json, Value};
use std::io::Write;

fn take(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

fn section<'a>(p: &'a str, head: &str) -> &'a str {
    let Some(i) = p.find(head) else { return "" };
    let rest = &p[i + head.len()..];
    rest.split("\n\n=== ").next().unwrap_or("").trim()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let prompt = args.iter().position(|a| a == "--").and_then(|i| args.get(i + 1)).cloned().unwrap_or_default();
    let new_turn = prompt.rsplit("=== 새 턴 ===\n").next().unwrap_or("");
    let (head, resp) = new_turn.split_once("\n  응답: ").unwrap_or((new_turn, ""));
    let resp = resp.strip_suffix('\n').unwrap_or(resp);
    let (num, req) = head.trim_start_matches("[턴 ").split_once("] 요청: ").unwrap_or(("0", ""));
    let n: i64 = num.parse().unwrap_or(0);

    let script: Value = std::env::var("FAKE_CLAUDE_SCRIPT").ok()
        .and_then(|p| std::fs::read_to_string(p).ok()).and_then(|t| serde_json::from_str(&t).ok()).unwrap_or(json!({}));
    let mut mode = script["turns"][n.to_string()].as_str().or(script["default"].as_str()).unwrap_or("ok").to_string();
    let state = std::env::var("FAKE_CLAUDE_STATE").unwrap_or_default();
    if !state.is_empty() {
        let _ = std::fs::create_dir_all(&state);
        for once in ["fail_once", "garbage_once"] {
            if mode == once {
                let mark = format!("{state}/{once}-{n}");
                mode = if std::path::Path::new(&mark).exists() { "ok".into() } else {
                    let _ = std::fs::write(&mark, "");
                    once.trim_end_matches("_once").into()
                };
            }
        }
        // 부른 모양을 남긴다: 인자, 기록 끔 표시, 새 세션(setsid)인지, 표준 입력이 비었는지, 마지막 프롬프트
        let own_session = unsafe { libc::getsid(0) == libc::getpid() };
        let mut probe = [0u8; 1];
        let stdin_empty = std::io::Read::read(&mut std::io::stdin(), &mut probe).map(|n| n == 0).unwrap_or(false);
        let call = json!({"args": args[1..].to_vec(), "analyzer_env": std::env::var("CONTROL_TUI_ANALYZER").ok(),
                          "own_session": own_session, "stdin_empty": stdin_empty});
        let _ = std::fs::write(format!("{state}/last_call.json"), call.to_string());
        let _ = std::fs::write(format!("{state}/last_prompt.txt"), &prompt);
        let hash = sha1_smol::Sha1::from(prompt.as_bytes()).digest().to_string();
        if let Ok(mut f) = std::fs::OpenOptions::new().append(true).create(true).open(format!("{state}/log")) {
            let _ = writeln!(f, "{n} {mode} {}", &hash[..12]);
        }
    }
    if mode == "slow" {
        std::thread::sleep(std::time::Duration::from_secs(3));
        mode = "ok".into();
    }
    if mode == "fail" {
        std::process::exit(1);
    }
    let q = take(req.trim(), 12);
    let aq = if resp == "(없음)" { String::new() } else { take(resp.trim(), 12) };
    let past_reqs: Vec<Value> = serde_json::from_str(section(&prompt, "=== 지난 요청 기록 ===\n")).unwrap_or_default();
    let past_asks: Vec<Value> = serde_json::from_str(section(&prompt, "=== 지난 묻는 것 (아직 답이 다 오지 않은 것) ===\n")).unwrap_or_default();
    let shift = mode == "shift";
    let first = past_reqs.is_empty() && n == 1;
    let state_new = match mode.as_str() { "progress" => "in_progress", _ if n % 3 == 0 => "open", _ => "addressed" };
    let mut out = json!({
        "turn": {"index": n, "label": if first { "시작" } else if n % 4 == 0 { "확정" } else { "구체화" },
                 "summary": format!("턴 {n} 요청 요약"), "quote": q, "agent_summary": format!("턴 {n} 응답 요약"),
                 "agent_quote": aq, "title": if shift { "새 주제" } else { "" }, "decision": format!("턴 {n}에서 정함")},
        "topic_shift": shift,
        "goal_change": {"direction": "옮김", "how": "앞 목표에서 새 대상으로", "quote": q},
        "current_goal": format!("목표 {n}"), "goal_turn": if shift || first { n } else { 0 }, "goal_quote": q,
        "first_goal": format!("처음 목표 {n}"), "digest": format!("턴 {n}까지의 흐름"),
        "requests_new": [{"summary": format!("요청 {n}"), "quote": q, "state": state_new, "agent_quote": aq, "pending_quote": aq}],
        "requests_update": past_reqs.iter().filter(|r| r["state"] == "open").take(1)
            .map(|r| json!({"id": r["id"], "state": "addressed", "agent_quote": aq})).collect::<Vec<_>>(),
        "asks_new": if mode == "ask" { json!([{"summary": format!("물음 {n}"), "quote": aq, "kind": "결정"}]) } else { json!([]) },
        "asks_reask": [],
        "asks_update": if mode == "blanket" {
            past_asks.iter().map(|a| json!({"id": a["id"], "state": "answered", "quote": q, "blanket": true})).collect::<Vec<_>>()
        } else { vec![] },
    });
    if mode == "garbage" {
        out = json!("설명만 있고 JSON이 아닌 답");
    }
    let text = if out.is_string() { out.as_str().unwrap().to_string() } else { out.to_string() };
    println!("{}", json!({"type": "result", "result": text}));
}
