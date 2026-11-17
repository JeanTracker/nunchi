"""관제 화면이 분석 결과를 읽는 쪽 (요구 이력 68 R2: 분석 엔진은 러스트로 옮기고, 읽는 함수는 관제 화면을 옮길 때까지 파이썬에 남는다).

예전 test_analyzer.py·test_request_check.py·test_flow_chain.py·test_in_progress.py에 섞여 있던 읽기 쪽 확인을 모았다.
"""

import json

from control_tui import analyzer, flow


def test_old_format_analysis_is_treated_as_not_analyzed(tmp_path):
    """옛 결과는 턴 번호와 원장 뜻이 달라 새 이름표로 보이면 틀린 말이 된다. 없는 것으로 본다."""
    (tmp_path / "analysis.json").write_text(json.dumps({"ledger": [], "source_ts": "T"}), encoding="utf-8")
    assert analyzer.read_analysis(tmp_path) is None
    (tmp_path / "analysis.json").write_text(json.dumps({"format": 2, "source_ts": "T", "current_goal": "할인"}), encoding="utf-8")
    got = analyzer.read_analysis(tmp_path)
    assert got["source_ts"] == "T" and got["current_goal"] == "할인"
    (tmp_path / "analysis.json").write_text("{깨짐", encoding="utf-8")
    assert analyzer.read_analysis(tmp_path) is None


def test_missed_count_counts_what_is_left_including_in_progress():
    f = {"requests": [{"id": "R1", "state": "addressed"}, {"id": "R2", "state": "open"},
                      {"id": "R3", "state": "deferred"}, {"id": "R4", "state": "superseded"},
                      {"id": "R5", "state": "in_progress"}]}
    assert analyzer.missed_count({"flow": f}) == 3            # 아직 다루지 않음·미룸·진행 중 (요구 이력 66)
    assert analyzer.missed_count({"flow": {"requests": []}}) == 0
    # 요청 기록이 없는 옛 결과는 빠짐 수
    assert analyzer.missed_count({"ledger": [{"status": "missed"}, {"status": "kept"}]}) == 1


def test_open_asks_are_the_unanswered_ones_latest_first():
    f = {"asks": [{"id": "Q1", "turn": 1, "last_turn": 1, "state": "answered"},
                  {"id": "Q2", "turn": 1, "last_turn": 2, "state": "open"},
                  {"id": "Q3", "turn": 3, "last_turn": 3, "state": "partial"}]}
    assert [a["id"] for a in flow.open_asks(f)] == ["Q3", "Q2"]
    assert flow.open_asks({"asks": [{"id": "Q1", "turn": 1, "state": "answered"}]}) == []
    assert flow.open_asks(None) == []
