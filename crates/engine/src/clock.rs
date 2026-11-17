//! 시각. 파이썬 엔진이 쓰던 글 꼴을 그대로 만든다 (외부 라이브러리 없이).

use std::time::{SystemTime, UNIX_EPOCH};

fn now_parts() -> (i64, u32) {
    let d = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    (d.as_secs() as i64, d.subsec_micros())
}

/// 1970-01-01부터 날 수 → (년, 월, 일)  (Howard Hinnant의 civil_from_days)
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y.rem_euclid(400);
    let mp = if m > 2 { m - 3 } else { m + 9 } as i64;
    let doy = (153 * mp + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// 1970년부터 초 → "YYYY-MM-DDTHH:MM:SS" (UTC)
pub fn stamp(secs: i64) -> String {
    let (y, mo, d) = civil(secs.div_euclid(86_400));
    let s = secs.rem_euclid(86_400);
    format!("{y:04}-{mo:02}-{d:02}T{:02}:{:02}:{:02}", s / 3600, s % 3600 / 60, s % 60)
}

/// `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")`
pub fn now_us() -> String {
    let (s, us) = now_parts();
    format!("{}.{us:06}Z", stamp(s))
}

/// 훅 기록 시각: 위 꼴에서 마이크로초를 밀리초로 자른 것
pub fn now_ms() -> String {
    let (s, us) = now_parts();
    format!("{}.{:03}Z", stamp(s), us / 1000)
}

/// `datetime.now(timezone.utc).isoformat()` (마이크로초가 0이면 뺀다)
pub fn now_iso() -> String {
    let (s, us) = now_parts();
    if us == 0 {
        format!("{}+00:00", stamp(s))
    } else {
        format!("{}.{us:06}+00:00", stamp(s))
    }
}

/// `datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()`. 못 읽으면 0.
/// 시간대가 없는 시각은 UTC로 본다 (파이썬은 이 맥의 지역 시각으로 본다. 대화 기록은 늘 Z라 쓰이지 않는 차이).
pub fn ts_value(ts: &str) -> f64 {
    parse(ts).unwrap_or(0.0)
}

fn parse(ts: &str) -> Option<f64> {
    let ts = ts.replace('Z', "+00:00");
    let b = ts.as_bytes();
    let num = |from: usize, len: usize| -> Option<i64> {
        let s = ts.get(from..from + len)?;
        if s.bytes().all(|c| c.is_ascii_digit()) { s.parse().ok() } else { None }
    };
    let y = num(0, 4)?;
    if b.get(4) != Some(&b'-') || b.get(7) != Some(&b'-') {
        return None;
    }
    let (mo, d) = (num(5, 2)? as u32, num(8, 2)? as u32);
    if !(1..=12).contains(&mo) || d == 0 || d > 31 {
        return None;
    }
    let mut secs = days_from_civil(y, mo, d) * 86_400;
    let mut frac = 0.0;
    let mut i = 10;
    if i < b.len() {
        if b[i] != b'T' && b[i] != b' ' {
            return None;
        }
        let h = num(i + 1, 2)?;
        i += 3;
        let mut mi = 0;
        let mut se = 0;
        if b.get(i) == Some(&b':') {
            mi = num(i + 1, 2)?;
            i += 3;
            if b.get(i) == Some(&b':') {
                se = num(i + 1, 2)?;
                i += 3;
                if b.get(i) == Some(&b'.') || b.get(i) == Some(&b',') {
                    let start = i + 1;
                    let mut j = start;
                    while j < b.len() && b[j].is_ascii_digit() {
                        j += 1;
                    }
                    if j == start {
                        return None;
                    }
                    frac = format!("0.{}", &ts[start..j]).parse().ok()?;
                    i = j;
                }
            }
        }
        if h > 23 || mi > 59 || se > 59 {
            return None;
        }
        secs += h * 3600 + mi * 60 + se;
        if i < b.len() {
            let sign = match b[i] {
                b'+' => 1,
                b'-' => -1,
                _ => return None,
            };
            let oh = num(i + 1, 2)?;
            let om = if b.get(i + 3) == Some(&b':') { num(i + 4, 2)? } else { num(i + 3, 2).unwrap_or(0) };
            secs -= sign * (oh * 3600 + om * 60);
        }
    }
    Some(secs as f64 + frac)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_transcript_times() {
        assert_eq!(ts_value("1970-01-01T00:00:01.500Z"), 1.5);
        assert_eq!(ts_value("2026-11-16T10:00:00+09:00"), ts_value("2026-11-16T01:00:00Z"));
        assert_eq!(ts_value("nope"), 0.0);
        assert_eq!(days_from_civil(2026, 11, 16), 20_773);
        assert_eq!(civil(20_773), (2026, 11, 16));
    }

    #[test]
    fn formats_like_python() {
        let s = now_us();
        assert_eq!(s.len(), "2026-11-16T10:00:00.123456Z".len());
        assert!(now_ms().ends_with('Z') && now_ms().len() == 24);
    }
}
