//! 응답이 이미 풀어 쓴 번호는 번호 풀이에서 뺀다 (요구 이력 82)
use nunchi_engine::glossary::{explain_shown, glossed};

fn docs(dir: &std::path::Path) {
    std::fs::create_dir_all(dir.join("docs")).unwrap();
    let mut req = String::from("| ID | 요청 | 근거 | 완료 기준 |\n| --- | --- | --- | --- |\n");
    for n in 1..=9 {
        req.push_str(&format!("| R{n} | 요구 {n} 뜻 | 1 | 기준 |\n"));
    }
    std::fs::write(dir.join("docs/REQUIREMENTS.md"), req).unwrap();
}

#[test]
fn hides_numbers_glossed_in_parentheses() {
    assert_eq!(glossed("세션 안에서 흐름을 빠르게 다시 확인하는 일(R1)"), vec!["R1"]);
    assert_eq!(glossed("목표와 흐름 보이기 (R2)와 남은 요청 보이기(R3)"), vec!["R2", "R3"]);
    assert_eq!(glossed("\"훅을 다시 거는 일\"(Phase 8b)"), vec!["Phase 8b"]);
    assert_eq!(glossed("**화면 규칙**(SCREEN §11)"), vec!["§11"]);
    assert_eq!(glossed("새 요건을 적었습니다(요구 이력 82)"), Vec::<String>::new());   // 문장 끝 인용
}

#[test]
fn keeps_lists_tables_code_and_bare_numbers() {
    assert!(glossed("두 요건(R1, R2)을 고쳤다").is_empty());       // 여러 번호를 묶은 괄호
    assert!(glossed("두 요건(R1·R2)을 고쳤다").is_empty());
    assert!(glossed("R4를 없애고 R3을 고쳤다").is_empty());       // 맨몸 번호
    assert!(glossed("| 항목 | 화면(R5) |").is_empty());            // 표 줄
    assert!(glossed("```\n화면(R5)\n```").is_empty());               // 코드 블록
    assert!(glossed("`화면(R5)` 를 보라").is_empty());               // 인라인 코드
    assert!(glossed("(R6)만 남김").is_empty());                     // 앞에 풀이 말이 없음
}

#[test]
fn hides_only_when_every_occurrence_is_glossed() {
    assert!(glossed("남은 요청 보이기(R8). 그리고 R8을 다시 본다").is_empty());
    assert_eq!(glossed("남은 요청 보이기(R8). 요청 기록(R8)"), vec!["R8"]);
}

#[test]
fn limit_and_total_count_after_hiding() {
    let dir = std::env::temp_dir().join(format!("nunchi-shown-{}", std::process::id()));
    docs(&dir);
    let cwd = dir.to_string_lossy().to_string();
    // R1·R2는 풀이가 있고 R3~R9는 맨몸: 5개는 맨몸 번호에서 고르고 남은 수는 7
    let text = "흐름 되짚기(R1), 목표 보이기(R2). 고친 것: R3 R4 R5 R6 R7 R8 R9";
    let got = explain_shown(text, &cwd);
    let ids: Vec<&str> = got["items"].as_array().unwrap().iter().map(|x| x["id"].as_str().unwrap()).collect();
    assert_eq!(ids, ["R3", "R4", "R5", "R6", "R7"]);
    assert_eq!(got["total"], 7);
    assert_eq!(got["hidden"], 2);
    // 모두 풀이가 있으면 항목이 비어 패널은 덩어리를 두지 않는다
    let all = explain_shown("흐름 되짚기(R1), 목표 보이기(R2)", &cwd);
    assert_eq!(all["items"].as_array().unwrap().len(), 0);
    assert_eq!(all["total"], 0);
    // 숨길 것이 없으면 hidden 칸을 두지 않는다 (예전 결과와 같은 모양)
    assert!(explain_shown("R3을 고쳤다", &cwd).get("hidden").is_none());
    let _ = std::fs::remove_dir_all(&dir);
}
