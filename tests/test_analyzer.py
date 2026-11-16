"""4단계 분석기: 프롬프트, 결과 검증, 저장, 한 번에 한 건 (control_tui/analyzer.py). 실제 claude는 쓰지 않는다."""

import json
import time

import pytest

from control_tui import analyzer
from control_tui.transcript import Turn


def turn(i, request, response=""):
    return Turn(index=i, time="2026-11-09T01:00:00.000Z", request=request, response=response)


GOOD = json.dumps({
    "first_goal": "가격표 조사",
    "current_goal": "할인 조건 추가",
    "turns": [
        {"index": 1, "label": "시작", "summary": "가격표 조사", "response_summary": "세 곳 찾음"},
        {"index": 2, "label": "구체화", "summary": "할인 추가", "response_summary": "연간 기준 추가"},
        {"index": 9, "label": "없는 턴", "summary": "무시돼야 함", "response_summary": ""},
    ],
    "ledger": [
        {"id": "C1", "condition": "표로 정리", "from_turn": 1, "quote": "가격표", "status": "kept", "evidence": "표를 만들었다"},
        {"id": "C2", "condition": "할인 조건 포함", "from_turn": 2, "quote": "할인", "status": "maybe", "evidence": "애매함"},
        {"id": "C3", "condition": "출처 표시", "from_turn": 1, "quote": "조사해줘", "status": "missed", "evidence": "출처가 없다"},
    ],
    "forgotten": ["출처 링크"],
})


# ---------- 프롬프트 ----------

def test_prompt_contains_turns_and_the_label_rules():
    text = analyzer.build_prompt([turn(1, "가격표 조사해줘", "세 곳 찾음"), turn(2, "할인 추가")])
    assert "[턴 1] 요청: 가격표 조사해줘" in text
    assert "[턴 2] 요청: 할인 추가" in text
    for label in analyzer.RELATIONS:
        assert label in text


def test_prompt_cuts_long_text_and_keeps_only_recent_turns():
    long_req = "가" * 5000
    turns = [turn(i, long_req) for i in range(1, analyzer.MAX_TURNS + 6)]
    text = analyzer.build_prompt(turns)
    assert f"[턴 {analyzer.MAX_TURNS + 5}]" in text
    assert "[턴 1]" not in text
    assert "가" * (analyzer.REQUEST_CUT + 1) not in text


# ---------- 결과 검증 ----------

def test_parse_accepts_fenced_json_and_keeps_valid_values():
    result = analyzer.parse_result("```json\n" + GOOD + "\n```", {1, 2})
    assert result["first_goal"] == "가격표 조사"
    assert [t["label"] for t in result["turns"]] == ["시작", "구체화"]  # 없는 턴 9는 버린다


def test_parse_replaces_bad_status_and_label():
    result = analyzer.parse_result(GOOD, {1, 2})
    statuses = {c["id"]: c["status"] for c in result["ledger"]}
    assert statuses == {"C1": "kept", "C2": "unknown", "C3": "missed"}  # 'maybe'는 모름으로
    assert analyzer.missed_count(result) == 1


def test_parse_turns_out_of_range_label_becomes_empty():
    text = json.dumps({"turns": [{"index": 1, "label": "모르는 말", "summary": "x"}]})
    assert analyzer.parse_result(text, {1})["turns"][0]["label"] == ""


def test_parse_rejects_text_without_json():
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.parse_result("분석할 수 없습니다", {1})


def test_parse_rejects_broken_json():
    with pytest.raises(analyzer.AnalyzerError):
        analyzer.parse_result("{\"turns\": [", {1})


# ---------- 저장과 예약 ----------

def test_write_then_read_keeps_source_timestamp(tmp_path):
    result = analyzer.parse_result(GOOD, {1, 2})
    analyzer.write_analysis(tmp_path, result, "2026-11-09T01:05:00.000Z")
    got = analyzer.read_analysis(tmp_path)
    assert got["source_ts"] == "2026-11-09T01:05:00.000Z"
    assert got["current_goal"] == "할인 조건 추가"


def make_transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "uuid": "a", "timestamp": "2026-11-09T01:00:00.000Z",
         "message": {"role": "user", "content": "가격표 조사해줘"}},
        {"type": "assistant", "uuid": "b", "timestamp": "2026-11-09T01:01:00.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "찾았습니다"}]}},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def test_runner_is_called_once_and_result_is_saved(tmp_path):
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return GOOD

    session = tmp_path / "s1"
    session.mkdir()
    a = analyzer.Analyzer(runner=fake)
    assert a.request("s1", session, str(make_transcript(tmp_path)), "T1") is True
    a.wait_idle()
    assert len(calls) == 1
    assert analyzer.read_analysis(session)["source_ts"] == "T1"


def test_same_response_is_not_analyzed_twice(tmp_path):
    calls = []
    session = tmp_path / "s1"
    session.mkdir()
    a = analyzer.Analyzer(runner=lambda p: calls.append(p) or GOOD)
    tr = str(make_transcript(tmp_path))
    a.request("s1", session, tr, "T1")
    a.wait_idle()
    assert a.request("s1", session, tr, "T1") is False  # 이미 분석됨
    assert a.request("s1", session, tr, "T2") is True   # 새 응답이면 다시
    a.wait_idle()
    assert len(calls) == 2


def test_failure_is_recorded_and_nothing_is_written(tmp_path):
    def boom(prompt):
        raise analyzer.AnalyzerError("claude 종료 코드 1")

    session = tmp_path / "s1"
    session.mkdir()
    a = analyzer.Analyzer(runner=boom)
    a.request("s1", session, str(make_transcript(tmp_path)), "T1")
    a.wait_idle()
    assert analyzer.read_analysis(session) is None
    assert a.last_error["s1"] == "claude 종료 코드 1"


def test_missing_transcript_is_not_requested(tmp_path):
    session = tmp_path / "s1"
    session.mkdir()
    a = analyzer.Analyzer(runner=lambda p: GOOD)
    assert a.request("s1", session, "", "T1") is False


def test_only_one_analysis_runs_at_a_time(tmp_path):
    running = []
    peak = []

    def slow(prompt):
        running.append(1)
        peak.append(len(running))
        time.sleep(0.05)
        running.pop()
        return GOOD

    a = analyzer.Analyzer(runner=slow)
    tr = str(make_transcript(tmp_path))
    for n in range(3):
        session = tmp_path / f"s{n}"
        session.mkdir()
        a.request(f"s{n}", session, tr, "T1")
    a.wait_idle(timeout=10)
    assert max(peak) == 1
