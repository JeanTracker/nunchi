//! 번호 풀이 (control_tui/glossary.py를 옮김. 요구 이력 51).
//!
//! 응답에 나온 기획 번호(R17, §4.5, Phase 4c, 요구 이력 41)를 세션 폴더의 docs/*.md에서 찾아 원문으로 풀어 준다.
//! 파이썬 정규식(뒤 보기 포함)을 손으로 옮겼다. 숫자는 ASCII 숫자만 본다(파이썬은 유니코드 숫자도 본다. 일부러 다름).

use crate::py;
use serde_json::{json, Value};
use std::path::Path;

const LIMIT: usize = 5;
const MEAN_CUT: usize = 90;
const DOC_HINTS: [(&str, &str); 6] = [
    ("화면", "화면구성"), ("SCREEN", "화면구성"), ("구현", "구현 계획"), ("BUILD_PLAN", "구현 계획"),
    ("요구사항", "요구사항"), ("REQUIREMENTS", "요구사항"),
];

fn one(text: &str) -> String {
    let t = py::join_ws(&text.replace("**", "").replace("~~", ""));
    if py::char_len(&t) <= MEAN_CUT { t } else { format!("{}…", py::take(&t, MEAN_CUT - 1)) }
}

fn alnum(c: Option<char>) -> bool {
    c.map(|c| c.is_ascii_alphanumeric()).unwrap_or(false)
}

fn digits(s: &[char], i: usize) -> usize {
    s[i..].iter().take_while(|c| c.is_ascii_digit()).count()
}

fn starts(s: &[char], i: usize, word: &str) -> bool {
    let w: Vec<char> = word.chars().collect();
    s.len() >= i + w.len() && s[i..i + w.len()] == w[..]
}

/// 한 자리에서 ID_RE를 맞춰 본다: (키, 끝 자리)
fn match_at(s: &[char], i: usize) -> Option<(String, usize)> {
    let at = |k: usize| s.get(k).copied();
    // (?<![A-Za-z0-9])(R\d{1,2})(?:~(R?\d{1,2}))?(?![0-9A-Za-z])
    if at(i) == Some('R') && !(i > 0 && alnum(at(i - 1))) {
        let n1 = digits(s, i + 1).min(2);
        for l1 in (1..=n1).rev() {
            let e1 = i + 1 + l1;
            let r: String = s[i..e1].iter().collect();
            if at(e1) == Some('~') {
                let rp = if at(e1 + 1) == Some('R') { vec![1, 0] } else { vec![0] };
                for r_len in rp {
                    let d0 = e1 + 1 + r_len;
                    let n2 = digits(s, d0).min(2);
                    for l2 in (1..=n2).rev() {
                        let e2 = d0 + l2;
                        if !alnum(at(e2)) {
                            let to: String = s[e1 + 1..e2].iter().collect();
                            return Some((format!("{r}~R{}", to.trim_start_matches('R')), e2));
                        }
                    }
                }
            }
            if !alnum(at(e1)) {
                return Some((r, e1));
            }
        }
    }
    // §\s?(\d+(?:\.\d+)*)
    if at(i) == Some('§') {
        let mut j = i + 1;
        if at(j).map(py::is_space).unwrap_or(false) && digits(s, j + 1) > 0 {
            j += 1;
        }
        let n = digits(s, j);
        if n > 0 {
            let mut e = j + n;
            while at(e) == Some('.') && digits(s, e + 1) > 0 {
                e += 1 + digits(s, e + 1);
            }
            return Some((format!("§{}", s[j..e].iter().collect::<String>()), e));
        }
    }
    // Phase\s?(\d+[a-z]?)(?![0-9A-Za-z])
    if starts(s, i, "Phase") {
        let mut j = i + 5;
        if at(j).map(py::is_space).unwrap_or(false) && digits(s, j + 1) > 0 {
            j += 1;
        }
        let n = digits(s, j);
        if n > 0 {
            let e = j + n;
            if at(e).map(|c| c.is_ascii_lowercase()).unwrap_or(false) && !alnum(at(e + 1)) {
                return Some((format!("Phase {}", s[j..e + 1].iter().collect::<String>()), e + 1));
            }
            if !alnum(at(e)) {
                return Some((format!("Phase {}", s[j..e].iter().collect::<String>()), e));
            }
        }
    }
    // (?:요구 이력|요청) (\d+)(?![0-9])
    for word in ["요구 이력 ", "요청 "] {
        if starts(s, i, word) {
            let j = i + word.chars().count();
            let n = digits(s, j);
            if n > 0 {
                return Some((format!("요구 이력 {}", s[j..j + n].iter().collect::<String>()), j + n));
            }
        }
    }
    None
}

fn hint(s: &[char], start: usize) -> String {
    let before: String = s[start.saturating_sub(20)..start].iter().collect();
    DOC_HINTS.iter().find(|(w, _)| before.contains(w)).map(|(_, l)| l.to_string()).unwrap_or_default()
}

/// 응답에 나온 번호를 처음 나온 순서로 (같은 번호는 한 번): (키, 앞에 적힌 문서 이름)
pub fn find(text: &str) -> Vec<(String, String)> {
    let s: Vec<char> = text.chars().collect();
    let mut out: Vec<(String, String)> = Vec::new();
    let mut i = 0;
    while i < s.len() {
        match match_at(&s, i) {
            Some((key, end)) => {
                if !out.iter().any(|(k, _)| *k == key) {
                    out.push((key, hint(&s, i)));
                }
                i = end;
            }
            None => i += 1,
        }
    }
    out
}

/// 줄 처음 자리들 (re.M의 ^)
fn line_starts(text: &str) -> Vec<usize> {
    std::iter::once(0).chain(text.match_indices('\n').map(|(i, _)| i + 1)).filter(|i| *i <= text.len()).collect()
}

/// `[^|]+\|`: from부터 다음 `|`까지(줄을 넘을 수 있다). (뜻, 맞춘 끝 자리)
fn cell(text: &str, from: usize) -> Option<(&str, usize)> {
    let bar = text[from..].find('|')?;
    if bar == 0 {
        return None;
    }
    Some((&text[from..from + bar], from + bar + 1))
}

fn ascii_digits(s: &str) -> usize {
    s.bytes().take_while(|b| b.is_ascii_digit()).count()
}

/// re.finditer처럼 훑는다: 줄 처음마다 맞춰 보고, 맞으면 맞춘 끝 뒤부터 다시 본다
fn scan<'a>(text: &'a str, mut at: impl FnMut(&'a str, usize) -> Option<(String, &'a str, usize)>) -> Vec<(String, &'a str)> {
    let mut out = Vec::new();
    let mut next = 0;
    for ls in line_starts(text) {
        if ls < next {
            continue;
        }
        if let Some((key, mean, end)) = at(text, ls) {
            out.push((key, mean));
            next = end;
        }
    }
    out
}

fn add(terms: &mut Vec<(String, Vec<String>)>, key: String, mean: &str) {
    let mean = one(mean);
    if mean.is_empty() {
        return; // 파이썬은 뜻이 비면 키도 만들지 않는다 (`mean and ... setdefault`)
    }
    match terms.iter_mut().find(|(k, _)| *k == key) {
        Some((_, list)) => {
            if !list.contains(&mean) {
                list.push(mean);
            }
        }
        None => terms.push((key, vec![mean])),
    }
}

/// 프로젝트 폴더의 docs/*.md로 '번호 → 뜻 목록' 사전
pub fn build(cwd: &str) -> Vec<(String, Vec<String>)> {
    let root = Path::new(if cwd.is_empty() { "." } else { cwd });
    let mut files: Vec<std::path::PathBuf> = match std::fs::read_dir(root.join("docs")) {
        Ok(rd) => rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| {
                let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                name.ends_with(".md")
            })
            .collect(),
        Err(_) => vec![],
    };
    files.sort_by(|a, b| a.to_string_lossy().cmp(&b.to_string_lossy()));
    let mut terms: Vec<(String, Vec<String>)> = Vec::new();
    for f in files {
        let Ok(bytes) = std::fs::read(&f) else { continue };
        let Ok(text) = String::from_utf8(bytes) else { continue };
        let text = text.replace("\r\n", "\n").replace('\r', "\n"); // 파이썬 read_text의 줄바꿈 맞춤
        let title = text
            .split('\n')
            .find_map(|l| l.strip_prefix("# ").filter(|t| !t.is_empty()))
            .map(|t| py::strip(t.split(':').next().unwrap_or("")).to_string())
            .unwrap_or_else(|| f.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string());
        // 파이썬은 정규식 종류별로 문서 전체를 훑는다. 같은 순서로 네 번 훑는다
        // `^\| (R\d+) \| ([^|]+)\|`
        for (key, mean) in scan(&text, |t, ls| {
            let r = t[ls..].strip_prefix("| R")?;
            let n = ascii_digits(r);
            let rest = r[n..].strip_prefix(" | ").filter(|_| n > 0)?;
            let from = t.len() - rest.len();
            let (mean, end) = cell(t, from)?;
            Some((format!("R{}", &r[..n]), mean, end))
        }) {
            add(&mut terms, key, mean);
        }
        // `^\| (\d+)(?:~(\d+))? \| ([^|]+)\|`
        for (key, mean) in scan(&text, |t, ls| {
            let r = t[ls..].strip_prefix("| ")?;
            let n = ascii_digits(r);
            if n == 0 {
                return None;
            }
            let mut rest = &r[n..];
            let mut b = &r[..n];
            if let Some(x) = rest.strip_prefix('~') {
                let m = ascii_digits(x);
                if m > 0 && x[m..].starts_with(" | ") {
                    b = &x[..m];
                    rest = &x[m..];
                }
            }
            let rest = rest.strip_prefix(" | ")?;
            let from = t.len() - rest.len();
            let (mean, end) = cell(t, from)?;
            Some((format!("{}~{}", &r[..n], b), mean, end))
        }) {
            let (a, b) = key.split_once('~').unwrap();
            let (Ok(a), Ok(b)) = (a.parse::<i64>(), b.parse::<i64>()) else { continue };
            if b - a <= 20 {
                for n in a..=b {
                    add(&mut terms, format!("요구 이력 {n}"), mean);
                }
            }
        }
        // `^\| (\d+[a-z]?)\. ([^|]+)\|`
        for (key, mean) in scan(&text, |t, ls| {
            let r = t[ls..].strip_prefix("| ")?;
            let n = ascii_digits(r);
            if n == 0 {
                return None;
            }
            let mut e = n;
            if r.as_bytes().get(e).map(|b| b.is_ascii_lowercase()).unwrap_or(false) && r.as_bytes().get(e + 1) == Some(&b'.') {
                e += 1;
            }
            let rest = r[e..].strip_prefix(". ")?;
            let from = t.len() - rest.len();
            let (mean, end) = cell(t, from)?;
            Some((format!("Phase {}", &r[..e]), mean, end))
        }) {
            add(&mut terms, key, mean);
        }
        let lines: Vec<&str> = text.split('\n').collect();
        for l in &lines {
            // `^#{2,3} (\d+(?:\.\d+)*)\.? (.+)$`
            let hashes = l.bytes().take_while(|b| *b == b'#').count();
            if !(2..=3).contains(&hashes) || l.as_bytes().get(hashes) != Some(&b' ') {
                continue;
            }
            let rest = &l[hashes + 1..];
            let b = rest.as_bytes();
            let mut e = b.iter().take_while(|c| c.is_ascii_digit()).count();
            if e == 0 {
                continue;
            }
            while b.get(e) == Some(&b'.') && b.get(e + 1).map(|c| c.is_ascii_digit()).unwrap_or(false) {
                e += 1 + b[e + 1..].iter().take_while(|c| c.is_ascii_digit()).count();
            }
            let num = &rest[..e];
            let mut after = &rest[e..];
            if after.starts_with(". ") && after.len() > 2 {
                after = &after[1..];
            }
            let Some(title_part) = after.strip_prefix(' ').filter(|t| !t.is_empty()) else { continue };
            add(&mut terms, format!("§{num}"), &format!("{title}: {title_part}"));
        }
    }
    terms
}

/// {"items": [{"id", "means"}], "total"}
pub fn explain(text: &str, cwd: &str) -> Value {
    let ids = find(text);
    if ids.is_empty() {
        return json!({"items": [], "total": 0});
    }
    let terms = build(cwd);
    if terms.is_empty() {
        return json!({"items": [], "total": 0});
    }
    let mut items = Vec::new();
    for (key, hint) in ids.iter().take(LIMIT) {
        let means: Vec<String> = if key.contains('~') && key.starts_with('R') {
            let (a, b) = key.split_once('~').unwrap();
            vec![format!("요구사항 {a}부터 {b}까지 전체")]
        } else {
            let all: Vec<String> = terms.iter().find(|(k, _)| k == key).map(|(_, v)| v.clone()).unwrap_or_default();
            let picked: Vec<String> = all.iter().filter(|x| !hint.is_empty() && x.starts_with(&format!("{hint}:"))).cloned().collect();
            if picked.is_empty() { all } else { picked }
        };
        items.push(json!({"id": key, "means": means}));
    }
    json!({"items": items, "total": ids.len()})
}
