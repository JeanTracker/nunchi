"""분석기 변경 (BUILD_PLAN §4.1, 요청 25~30): 도구 끄기, 마지막 턴 전체, 순서, 합치기, 입력 고정, 재시도, 종료, 상태."""

import json
import threading
import time
from pathlib import Path

import pytest

from control_tui import analyzer, settings
from control_tui.transcript import Turn


def turn(i, request, response="", ts="2026-11-09T01:00:00.000Z"):
    t = Turn(index=i, time=ts, request=request, response=response)
    t.final_response = response
    return t


GOOD = json.dumps({"first_goal": "g", "current_goal": "g2", "next_action": "n",
                   "turns": [{"index": 1, "label": "시작", "summary": "s", "response_summary": "r"}],
                   "last_response_summary": "마지막 요약",
                   "ledger": [{"id": "C1", "condition": "출처", "from_turn": 1, "status": "missed", "evidence": "e"}]})


def transcript(path: Path, n=2, base_minute=0):
    rows = []
    for i in range(n):
        rows.append({"type": "user", "timestamp": f"2026-11-09T01:{base_minute + i * 2:02d}:00.000Z",
                     "message": {"role": "user", "content": f"요청 {i + 1}"}})
        rows.append({"type": "assistant", "timestamp": f"2026-11-09T01:{base_minute + i * 2 + 1:02d}:00.000Z",
                     "message": {"content": [{"type": "text", "text": f"응답 {i + 1}"}]}})
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


# ---------- 프롬프트와 실행 명령 ----------

def test_last_turn_sends_the_whole_response_and_earlier_turns_are_cut():
    long = "가" * 3000
    text = analyzer.build_prompt([turn(1, "a", long), turn(2, "b", long + "끝질문?")])
    assert "가" * (analyzer.RESPONSE_CUT + 1) not in text.split("[턴 2]")[0]  # 앞 턴은 잘림
    assert "끝질문?" in text                                              # 마지막 턴은 전체
    assert "last_response_summary" in text and "90자" in text


def test_very_long_last_response_is_not_cut():
    # 요청 46: 예전 6,000자 상한이면 끝의 결론·질문이 잘렸다
    long = "나" * 20000 + "마지막결론과질문?"
    text = analyzer.build_prompt([turn(1, "a", "짧음"), turn(2, "b", long)])
    assert "나" * 20000 + "마지막결론과질문?" in text
    assert not hasattr(analyzer, "LAST_RESPONSE_CUT")


def test_claude_is_run_with_all_tools_off_and_model(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

        def communicate(self, timeout=None):
            return json.dumps({"result": GOOD}), ""

        def poll(self):
            return 0

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        seen["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(analyzer.subprocess, "Popen", fake_popen)
    analyzer.run_claude("p", model="haiku")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == ""          # 도구 모두 끔
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert "--disallowedTools" not in cmd
    # 관제 패널의 터미널과 떼어서 띄운다 (관제 패널이 claude 패널로 잡히지 않게)
    assert seen["kw"]["start_new_session"] is True
    assert seen["kw"]["stdin"] == analyzer.subprocess.DEVNULL


def test_parse_keeps_last_response_summary_and_short_response_summary():
    long = json.dumps({"turns": [{"index": 1, "label": "시작", "response_summary": "가" * 300}],
                       "last_response_summary": "요약"})
    r = analyzer.parse_result(long, {1})
    assert len(r["turns"][0]["response_summary"]) <= analyzer.SUMMARY_CUT
    assert r["last_response_summary"] == "요약"


def test_diff_finds_new_missed_conditions_by_text():
    old = {"ledger": [{"condition": "A", "status": "missed"}], "next_action": "x", "current_goal": "g"}
    new = {"ledger": [{"condition": "A", "status": "missed"}, {"condition": "B", "status": "missed"}],
           "next_action": "y", "current_goal": "g"}
    d = analyzer.diff_analysis(old, new)
    assert d["missed_before"] == 1 and d["missed_after"] == 2 and d["new_missed"] == ["B"]
    assert not d["goal_changed"] and "next_changed" not in d  # '다음 할 일'은 요청 33에서 뺌
    assert analyzer.diff_analysis(None, new) == {}


# ---------- 순서·합치기·입력 고정 ----------

def _held_runner():
    gate = threading.Event()
    calls = []

    def run(prompt):
        calls.append(prompt)
        gate.wait(5)
        return GOOD
    return run, gate, calls


def test_selected_session_goes_first_and_status_shows_queue(tmp_path):
    run, gate, calls = _held_runner()
    a = analyzer.Analyzer(runner=run)
    tr = str(transcript(tmp_path / "t.jsonl"))
    dirs = {}
    for sid in ("s0", "s1", "s2"):
        dirs[sid] = tmp_path / sid
        dirs[sid].mkdir()
    a.request("s0", dirs["s0"], tr, "2026-11-09T01:03:00.000Z")   # 먼저 돌기 시작
    time.sleep(0.2)
    a.request("s1", dirs["s1"], tr, "2026-11-09T01:05:00.000Z")
    a.request("s2", dirs["s2"], tr, "2026-11-09T01:04:00.000Z")
    a.prioritize("s2")
    assert a.status("s0")["state"] == "running"
    assert a.status("s2") == {"state": "queued", "ahead": 1, "source_ts": "2026-11-09T01:04:00.000Z"}
    assert a.status("s1")["ahead"] == 2
    gate.set()
    a.wait_idle(10)
    order = [json.loads(p.split("\n")[0]) if False else p for p in calls]
    assert len(order) == 3
    assert analyzer.read_analysis(dirs["s2"])["analyzed_at"] < analyzer.read_analysis(dirs["s1"])["analyzed_at"]


def test_older_pending_request_is_replaced_by_newer(tmp_path):
    run, gate, calls = _held_runner()
    a = analyzer.Analyzer(runner=run)
    tr = str(transcript(tmp_path / "t.jsonl"))
    busy, s1 = tmp_path / "busy", tmp_path / "s1"
    busy.mkdir()
    s1.mkdir()
    a.request("busy", busy, tr, "2026-11-09T01:03:00.000Z")
    time.sleep(0.2)
    a.request("s1", s1, tr, "2026-11-09T01:01:00.000Z")
    a.request("s1", s1, tr, "2026-11-09T01:03:00.000Z")   # 같은 세션의 더 새 응답
    gate.set()
    a.wait_idle(10)
    assert len(calls) == 2
    assert analyzer.read_analysis(s1)["source_ts"] == "2026-11-09T01:03:00.000Z"


def test_turns_after_the_response_time_are_not_sent(tmp_path):
    seen = []
    a = analyzer.Analyzer(runner=lambda p: seen.append(p) or GOOD)
    tr = str(transcript(tmp_path / "t.jsonl", n=3))
    d = tmp_path / "s"
    d.mkdir()
    a.request("s", d, tr, "2026-11-09T01:01:00.000Z")   # 첫 턴 응답 시각까지만
    a.wait_idle()
    assert "[턴 1]" in seen[0] and "[턴 2]" not in seen[0]
    assert analyzer.read_analysis(d)["last_turn"] == 1


# ---------- 실패·종료 ----------

def test_failure_is_not_retried_every_second_but_force_retries(tmp_path):
    calls = []

    def boom(prompt):
        calls.append(1)
        raise analyzer.AnalyzerError("시간 초과 (150초)")

    a = analyzer.Analyzer(runner=boom)
    tr = str(transcript(tmp_path / "t.jsonl"))
    d = tmp_path / "s"
    d.mkdir()
    assert a.request("s", d, tr, "T1") is True
    a.wait_idle()
    assert a.request("s", d, tr, "T1") is False          # 바로 다시 줄 서지 않는다
    assert a.status("s")["state"] == "failed" and "시간 초과" in a.status("s")["error"]
    assert a.request("s", d, tr, "T1", force=True) is True   # r 키
    a.wait_idle()
    assert len(calls) == 2


def test_shutdown_drops_waiting_jobs_and_kills_running_claude(tmp_path):
    killed = []

    class Proc:
        def poll(self):
            return None

        def kill(self):
            killed.append(True)

    started = threading.Event()

    def slow(prompt):
        a._register(Proc())
        started.set()
        time.sleep(0.5)
        return GOOD

    a = analyzer.Analyzer(runner=slow)
    tr = str(transcript(tmp_path / "t.jsonl"))
    for sid in ("s1", "s2"):
        (tmp_path / sid).mkdir()
        a.request(sid, tmp_path / sid, tr, "T1")
    started.wait(5)
    a.shutdown()
    assert killed == [True]
    time.sleep(0.7)
    assert analyzer.read_analysis(tmp_path / "s2") is None   # 기다리던 일은 버림
    assert a.request("s3", tmp_path, tr, "T9") is False


# ---------- 설정 파일 ----------

def test_settings_defaults_and_bad_values(tmp_path):
    assert settings.load(tmp_path).analyze_scope == "selected"
    (tmp_path / "config.json").write_text(json.dumps({
        "analyze_scope": "all", "analyze_when": "manual", "analyze_model": " haiku ",
        "analyze_max_turns": 9999, "latest_view": "summary", "unknown": 1}), encoding="utf-8")
    s = settings.load(tmp_path)
    assert (s.analyze_scope, s.analyze_when, s.analyze_model, s.analyze_max_turns, s.latest_view) == \
        ("all", "manual", "haiku", 200, "summary")
    (tmp_path / "config.json").write_text('{"analyze_scope": "nope"', encoding="utf-8")
    assert settings.load(tmp_path).analyze_scope == "selected"


def test_reworded_conditions_and_goals_are_not_reported_as_new():
    """2026-11-10 실제 화면: 분석기가 같은 조건을 말만 바꿔 써서 '새 빠짐 2'가 잘못 나왔다."""
    old = {"ledger": [{"condition": "touch /tmp/control-tui-probe2.txt만 실행하기", "from_turn": 3, "status": "missed"}],
           "current_goal": "도구 없이 1~45의 제곱 목록 쓰기", "next_action": "세제곱 목록도 만들지 정하기"}
    new = {"ledger": [{"condition": "touch /tmp/control-tui-probe2.txt 실행", "from_turn": 3, "status": "missed"},
                      {"condition": "출처 링크 붙이기", "from_turn": 7, "status": "missed"}],
           "current_goal": "도구 없이 1부터 45까지 제곱 목록 쓰기", "next_action": "B사 견적서 받기"}
    d = analyzer.diff_analysis(old, new)
    assert d["new_missed"] == ["출처 링크 붙이기"]
    assert d["goal_changed"] is False


# ---------- Stop 뒤에 적히는 마지막 글 (SCREEN §8, 2026-11-10 실험) ----------

def _without_last_text(path: Path) -> list:
    """마지막 응답 글 줄만 뺀 기록. Stop 훅이 올 때의 모습."""
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    return lines


def test_waits_for_the_last_text_written_after_stop(tmp_path):
    seen = []
    a = analyzer.Analyzer(runner=lambda p: seen.append(p) or GOOD)
    path = transcript(tmp_path / "t.jsonl", n=2)
    lines = _without_last_text(path)
    d = tmp_path / "s"
    d.mkdir()
    a.request("s", d, str(path), "2026-11-09T01:03:00.500Z")   # Stop 시각: 마지막 글 시각보다 조금 뒤
    time.sleep(0.6)                                            # Claude Code가 늦게 적는 사이
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    a.wait_idle(timeout=10)
    assert "응답 2" in seen[0] and "(없음)" not in seen[0]


def test_turn_without_text_goes_on_after_the_wait(tmp_path):
    seen = []
    a = analyzer.Analyzer(runner=lambda p: seen.append(p) or GOOD, reply_wait=0.3)
    path = transcript(tmp_path / "t.jsonl", n=2)
    _without_last_text(path)                                   # 도구로 끝나 글이 끝내 안 오는 턴
    d = tmp_path / "s"
    d.mkdir()
    a.request("s", d, str(path), "2026-11-09T01:03:00.500Z")
    a.wait_idle(timeout=5)
    assert len(seen) == 1 and "(없음)" in seen[0]
