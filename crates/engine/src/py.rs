//! 파이썬과 똑같이 동작해야 하는 작은 도구들 (BUILD_PLAN §4.13 약속).
//!
//! 엔진은 파이썬 코드를 그대로 옮긴 것이라, 프롬프트와 결과 파일이 같으려면
//! 공백 나누기·줄 나누기·참 거짓·`str()`·`int()`·`json.dumps`가 파이썬과 같아야 한다.

use serde_json::{Map, Value};

// ---------- 글 ----------

/// 파이썬 `str.isspace()`와 같은 공백. 러스트의 공백에 정보 구분 문자(0x1c~0x1f)를 더한 것.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.split()` (인자 없음)
pub fn split_ws(s: &str) -> Vec<&str> {
    s.split(is_space).filter(|p| !p.is_empty()).collect()
}

/// `" ".join(s.split())`
pub fn join_ws(s: &str) -> String {
    split_ws(s).join(" ")
}

/// `"".join(s.split())`
pub fn squash(s: &str) -> String {
    split_ws(s).concat()
}

pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(is_space)
}

/// `s[:n]` (글자 단위)
pub fn take(s: &str, n: usize) -> String {
    s.chars().take(n).collect()
}

/// `s[-n:]` (글자 단위)
pub fn last(s: &str, n: usize) -> String {
    let count = s.chars().count();
    s.chars().skip(count.saturating_sub(n)).collect()
}

pub fn char_len(s: &str) -> usize {
    s.chars().count()
}

/// `str.splitlines()`: \n \r \r\n \v \f \x1c \x1d \x1e \x85    에서 나눈다. 끝의 빈 줄은 없다.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let brk = matches!(c, '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}');
        if !brk {
            continue;
        }
        out.push(&s[start..i]);
        let mut end = i + c.len_utf8();
        if c == '\r' {
            if let Some(&(j, '\n')) = it.peek() {
                it.next();
                end = j + 1;
            }
        }
        start = end;
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

// ---------- 값 ----------

/// 파이썬의 참 거짓 (`if x:`)
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

pub fn opt_truthy(v: Option<&Value>) -> bool {
    v.map(truthy).unwrap_or(false)
}

/// `str(x)`
pub fn str_of(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => repr(other),
    }
}

/// `str(x or "")`
pub fn str_or_empty(v: Option<&Value>) -> String {
    match v {
        Some(x) if truthy(x) => str_of(x),
        _ => String::new(),
    }
}

/// 파이썬 `repr()` 꼴 (목록·사전 안의 값)
pub fn repr(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => number(n),
        Value::String(s) => repr_str(s),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter().map(|(k, v)| format!("{}: {}", repr_str(k), repr(v))).collect::<Vec<_>>().join(", ")
        ),
    }
}

fn repr_str(s: &str) -> String {
    let q = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::new();
    out.push(q);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == q => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || c as u32 == 0x7f => out.push_str(&format!("\\x{:02x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push(q);
    out
}

/// `int(x)`: 정수, 소수(버림), 참 거짓, 앞뒤 공백 있는 정수 글. 안 되면 None
pub fn int_of(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(*b as i64),
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().filter(|f| f.is_finite()).map(|f| f.trunc() as i64)),
        Value::String(s) => {
            let t = strip(s).replace('_', "");
            t.parse::<i64>().ok()
        }
        _ => None,
    }
}

/// `x or default` 꼴로 꺼낸 정수 (`int(x or 0)`)
pub fn int_or(v: Option<&Value>, default: i64) -> Option<i64> {
    match v {
        Some(x) if truthy(x) => int_of(x),
        _ => Some(default),
    }
}

/// 파이썬 `==` (숫자는 값으로, 참 거짓은 0·1로)
pub fn eq(a: &Value, b: &Value) -> bool {
    fn num(v: &Value) -> Option<f64> {
        match v {
            Value::Number(n) => n.as_f64(),
            Value::Bool(b) => Some(*b as i64 as f64),
            _ => None,
        }
    }
    match (num(a), num(b)) {
        (Some(x), Some(y)) => x == y,
        _ => a == b,
    }
}

pub fn eq_int(a: Option<&Value>, b: i64) -> bool {
    a.map(|v| eq(v, &Value::from(b))).unwrap_or(false)
}

pub fn get<'a>(v: &'a Value, key: &str) -> Option<&'a Value> {
    v.as_object().and_then(|o| o.get(key))
}

/// `(x or {})` 사전
pub fn obj_or_empty(v: Option<&Value>) -> Map<String, Value> {
    match v {
        Some(Value::Object(o)) if !o.is_empty() => o.clone(),
        _ => Map::new(),
    }
}

/// 목록 (`x or []`). 목록이 아니면 빈 목록
pub fn list<'a>(v: Option<&'a Value>) -> &'a [Value] {
    match v {
        Some(Value::Array(a)) => a,
        _ => &[],
    }
}

// ---------- json.dumps ----------

/// `json.dumps(v, ensure_ascii=False)` (사이 띄움 ", " ": ")
pub fn dumps(v: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, v, None, 0);
    out
}

/// `json.dumps(v, ensure_ascii=False, indent=2)`
pub fn dumps_indent(v: &Value) -> String {
    let mut out = String::new();
    write_value(&mut out, v, Some(2), 0);
    out
}

fn write_value(out: &mut String, v: &Value, indent: Option<usize>, level: usize) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
        Value::Number(n) => out.push_str(&number(n)),
        Value::String(s) => write_str(out, s),
        Value::Array(a) => {
            if a.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push('[');
            for (i, x) in a.iter().enumerate() {
                sep(out, i > 0, indent, level + 1);
                write_value(out, x, indent, level + 1);
            }
            close(out, indent, level);
            out.push(']');
        }
        Value::Object(o) => {
            if o.is_empty() {
                out.push_str("{}");
                return;
            }
            out.push('{');
            for (i, (k, x)) in o.iter().enumerate() {
                sep(out, i > 0, indent, level + 1);
                write_str(out, k);
                out.push_str(": ");
                write_value(out, x, indent, level + 1);
            }
            close(out, indent, level);
            out.push('}');
        }
    }
}

fn sep(out: &mut String, comma: bool, indent: Option<usize>, level: usize) {
    match indent {
        None => {
            if comma {
                out.push_str(", ");
            }
        }
        Some(n) => {
            if comma {
                out.push(',');
            }
            out.push('\n');
            out.push_str(&" ".repeat(n * level));
        }
    }
}

fn close(out: &mut String, indent: Option<usize>, level: usize) {
    if let Some(n) = indent {
        out.push('\n');
        out.push_str(&" ".repeat(n * level));
    }
}

fn write_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

/// 파이썬 숫자 표기: 정수는 그대로, 소수는 `repr(float)` (1e+16, 1e-05 꼴)
fn number(n: &serde_json::Number) -> String {
    if n.is_i64() || n.is_u64() {
        return n.to_string();
    }
    let f = n.as_f64().unwrap_or(0.0);
    if f.is_nan() {
        return "NaN".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    let exp = if f == 0.0 { 0 } else { f.abs().log10().floor() as i32 };
    if (-4..16).contains(&exp) {
        let s = format!("{f}");
        if s.contains('.') { s } else { format!("{s}.0") }
    } else {
        let s = format!("{f:e}");
        let (m, e) = s.split_once('e').unwrap_or((&s, "0"));
        let e: i32 = e.parse().unwrap_or(0);
        format!("{m}e{}{:02}", if e < 0 { '-' } else { '+' }, e.abs())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn whitespace_matches_python() {
        assert_eq!(split_ws(" a\u{1c}b\u{3000}c\u{a0}d \n"), vec!["a", "b", "c", "d"]);
        assert_eq!(join_ws("  가  나\t다 "), "가 나 다");
        assert_eq!(squash(" a b "), "ab");
    }

    #[test]
    fn splitlines_matches_python() {
        assert_eq!(splitlines("a\r\nb\rc\u{2028}d\n"), vec!["a", "b", "c", "d"]);
        assert_eq!(splitlines("a\n\nb"), vec!["a", "", "b"]);
        assert!(splitlines("").is_empty());
    }

    #[test]
    fn dumps_matches_python() {
        let v = json!({"a": [1, "가\n", {"b": null}], "c": {}, "d": []});
        assert_eq!(dumps(&v), r#"{"a": [1, "가\n", {"b": null}], "c": {}, "d": []}"#);
        assert_eq!(dumps_indent(&json!({"a": [1], "b": {}})), "{\n  \"a\": [\n    1\n  ],\n  \"b\": {}\n}");
        assert_eq!(dumps(&json!(1.0)), "1.0");
        assert_eq!(dumps(&json!(1e16)), "1e+16");
        assert_eq!(dumps(&json!(0.00001)), "1e-05");
    }

    #[test]
    fn int_and_str_match_python() {
        assert_eq!(int_of(&json!(" 3 ")), Some(3));
        assert_eq!(int_of(&json!(3.9)), Some(3));
        assert_eq!(int_of(&json!(true)), Some(1));
        assert_eq!(int_of(&json!("3.0")), None);
        assert_eq!(str_or_empty(Some(&json!(0))), "");
        assert_eq!(str_of(&json!([1, "a"])), "[1, 'a']");
    }
}
