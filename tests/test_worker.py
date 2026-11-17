"""관제 밖 분석기 (요구 이력 52·53, BUILD_PLAN §4.7, Phase 8a).

분석기를 실제로 띄우거나 claude -p를 부르지 않는다. 깨우기는 가짜 spawner로, 분석은 가짜 기록기로 본다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from control_tui import analyzer, worker
from tests.test_flow_chain import LEDGER, flow_answer
from tests.test_flow_view import make_session

ROOT = Path(__file__).resolve().parent.parent
EMIT = ROOT / "hooks" / "emit.py"


# ---------- 대기열 ----------

def test_enqueue_merges_to_the_latest_answer_and_keeps_force(tmp_path):
    worker.enqueue(tmp_path, "s1", "/t.jsonl", "2026-11-16T00:00:02.000Z", force=True)
    worker.enqueue(tmp_path, "s1", "/t.jsonl", "2026-11-16T00:00:01.000Z")   # 더 옛 응답은 덮지 않는다
    items = worker.pending(tmp_path)
    assert len(items) == 1 and items[0]["source_ts"] == "2026-11-16T00:00:02.000Z" and items[0]["force"]


def test_only_one_worker_takes_a_session(tmp_path):
    assert worker.claim(tmp_path, "s1")
    (worker.queue_dir(tmp_path) / "s1.claim").write_text("1")   # 살아 있는 다른 프로세스(launchd, PID 1)가 맡은 척
    assert not worker.claim(tmp_path, "s1")
    (worker.queue_dir(tmp_path) / "s1.claim").write_text("999999")   # 죽은 분석기의 표시는 걷어 낸다
    assert worker.claim(tmp_path, "s1")


def test_slots_follow_the_workers_setting(tmp_path):
    a = worker.take_slot(tmp_path, 1)
    assert a is not None and worker.take_slot(tmp_path, 1) is None      # 기본 1개
    b = worker.take_slot(tmp_path, 2)
    assert b is not None and worker.take_slot(tmp_path, 5) is None      # 최대 2개
    worker._unlock(a)
    worker._unlock(b)


# ---------- 관제 쪽 (QueueAnalyzer) ----------

def test_control_requests_wake_the_worker_and_show_queued(tmp_path):
    home, tr, stop = make_session(tmp_path)
    spawned = []
    q = worker.QueueAnalyzer(home, spawner=spawned.append)
    d = home / "sessions" / "s1"
    assert q.request("s1", d, str(tr), stop)
    assert spawned == [worker.worker_command(home)]   # 명령 모양은 test_worker_command_prefers_the_rust_engine에서 (엔진을 빌드했는지에 따라 다름)
    assert q.status("s1") == {"state": "queued", "ahead": 0, "source_ts": stop}
    assert not q.request("s1", d, str(tr), stop)            # 이미 줄에 있으면 또 쓰지 않는다
    q.prioritize("s1")
    assert (worker.queue_dir(home) / worker.PRIORITY_FILE).read_text() == "s1"


def test_control_reads_running_and_failed_from_the_status_file(tmp_path):
    home, tr, stop = make_session(tmp_path)
    d = home / "sessions" / "s1"
    q = worker.QueueAnalyzer(home, spawner=lambda cmd: None)
    analyzer.write_status(d, "running", 2, since="2026-11-16T00:00:00.000000Z", source_ts=stop)
    st = q.status("s1")
    assert st["state"] == "running" and st["turn"] == 2 and st["seconds"] > 0
    analyzer.write_status(d, "failed", error="시간 초과 (150초)", source_ts=stop, attempts=analyzer.MAX_ATTEMPTS)
    assert q.status("s1") == {"state": "failed", "error": "시간 초과 (150초)", "source_ts": stop}
    assert not q.request("s1", d, str(tr), stop)            # 횟수를 다 쓴 실패는 r로만
    assert q.request("s1", d, str(tr), stop, force=True)


def test_dead_worker_status_is_not_shown_as_running(tmp_path):
    home, tr, stop = make_session(tmp_path)
    d = home / "sessions" / "s1"
    (d / analyzer.STATUS_FILE).write_text(json.dumps({"state": "running", "turn": 1, "pid": 999999}))
    assert worker.QueueAnalyzer(home, spawner=lambda c: None).status("s1") == {"state": ""}


# ---------- 분석기 본체 ----------

def test_drain_analyzes_the_queue_and_ends_when_it_is_empty(tmp_path):
    home, tr, stop = make_session(tmp_path)
    worker.enqueue(home, "s1", str(tr), stop)
    done = worker.drain(home, runner=lambda p: LEDGER, flow_runner=flow_answer, poll=0.05, reply_wait=0, max_seconds=20)
    data = json.loads((home / "sessions" / "s1" / "analysis.json").read_text())
    assert done == 1 and data["flow"]["until"] == 3
    assert worker.pending(home) == []                                   # 줄이 비었다
    assert worker.take_slot(home, 1) is not None                        # 자리를 내놓고 끝났다
    assert (home / "sessions" / "s1" / "glossary.json").exists()       # 관제가 없어도 번호 풀이를 쓴다


def test_drain_does_nothing_when_every_slot_is_busy(tmp_path):
    home, tr, stop = make_session(tmp_path)
    worker.enqueue(home, "s1", str(tr), stop)
    held = worker.take_slot(home, 1)
    try:
        assert worker.drain(home, runner=lambda p: LEDGER, flow_runner=flow_answer, poll=0.05) == 0
        assert len(worker.pending(home)) == 1
    finally:
        worker._unlock(held)


def test_failed_analysis_is_retried_then_left_as_failed(tmp_path, monkeypatch):
    home, tr, stop = make_session(tmp_path)
    monkeypatch.setattr(analyzer, "RETRY_SECONDS", 0.0)
    worker.enqueue(home, "s1", str(tr), stop)

    def broken(p):
        raise analyzer.AnalyzerError("시간 초과 (150초)")
    worker.drain(home, runner=broken, flow_runner=broken, poll=0.05, reply_wait=0, max_seconds=20)
    st = analyzer.read_status(home / "sessions" / "s1")
    assert st["state"] == "failed" and st["attempts"] == analyzer.MAX_ATTEMPTS and "시간 초과" in st["error"]
    assert worker.pending(home) == []


# ---------- 훅 ----------

def emit(home, event, env=None, **payload):
    full = {**os.environ, "CONTROL_TUI_HOME": str(home), "CONTROL_TUI_WORKER": "0", **(env or {})}
    full.pop("CONTROL_TUI_ANALYZE", None)
    body = json.dumps({"session_id": "s9", "cwd": "/work", "transcript_path": "/t.jsonl",
                       "hook_event_name": event, **payload})
    return subprocess.run([sys.executable, str(EMIT)], input=body, capture_output=True, text=True, env=full, timeout=20)


def test_stop_queues_only_sessions_turned_on_with_nunchi(tmp_path):
    home = tmp_path / "home"
    emit(home, "Stop")
    assert worker.pending(home) == []                                   # 켜지 않은 세션은 분석하지 않는다
    (home / "sessions" / "s9" / "want").write_text("{}")
    emit(home, "Stop")
    items = worker.pending(home)
    assert len(items) == 1 and items[0]["session_id"] == "s9" and items[0]["transcript_path"] == "/t.jsonl"
    ts = json.loads((home / "sessions" / "s9" / "events.jsonl").read_text().splitlines()[-1])["ts"]
    assert items[0]["source_ts"] == ts                                  # 관제와 같은 응답 시각으로 묶는다


@pytest.mark.parametrize("config, queued", [({"analyze_scope": "all"}, 1), ({"analyze_scope": "off"}, 0),
                                            ({"analyze_when": "manual"}, 0)])
def test_stop_follows_the_scope_setting(tmp_path, config, queued):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text(json.dumps(config))
    (home / "sessions" / "s9").mkdir(parents=True)
    if config.get("analyze_scope") != "all":
        (home / "sessions" / "s9" / "want").write_text("{}")
    emit(home, "Stop")
    assert len(worker.pending(home)) == queued


def test_analyzer_runs_record_nothing_and_queue_nothing(tmp_path):
    home = tmp_path / "home"
    (home / "sessions" / "s9").mkdir(parents=True)
    (home / "sessions" / "s9" / "want").write_text("{}")
    emit(home, "Stop", env={"CONTROL_TUI_ANALYZER": "1"})
    assert worker.pending(home) == []


def test_drain_takes_the_session_chosen_in_the_control_first(tmp_path):
    home, tr1, stop = make_session(tmp_path, n=1, sid="s1")
    _, tr2, _ = make_session(tmp_path, n=1, sid="s2")
    worker.enqueue(home, "s1", str(tr1), stop)
    worker.enqueue(home, "s2", str(tr2), stop)                      # s1이 먼저 줄을 섰지만
    worker.QueueAnalyzer(home, spawner=lambda c: None).prioritize("s2")   # 관제에서 s2를 보고 있다
    worker.drain(home, runner=lambda p: LEDGER, flow_runner=flow_answer, poll=0.05, reply_wait=0, max_seconds=20)
    a1 = analyzer.read_analysis(home / "sessions" / "s1")
    a2 = analyzer.read_analysis(home / "sessions" / "s2")
    assert a1 and a2 and a2["analyzed_at"] < a1["analyzed_at"]        # 고른 세션이 먼저 끝났다


# ---------- /nunchi off (요구 이력 62) ----------

@pytest.mark.parametrize("config", [{}, {"analyze_scope": "all"}])
def test_stop_does_not_queue_a_session_turned_off(tmp_path, config):
    home = tmp_path / "home"
    (home / "sessions" / "s9").mkdir(parents=True)
    (home / "config.json").write_text(json.dumps(config))
    (home / "sessions" / "s9" / "want").write_text('{"on": false}')
    emit(home, "Stop")
    assert worker.pending(home) == []                                   # 설정이 all이어도 끈 세션은 넣지 않는다


def test_want_without_on_still_means_on(tmp_path):
    home = tmp_path / "home"
    (home / "sessions" / "s9").mkdir(parents=True)
    (home / "sessions" / "s9" / "want").write_text('{"at": "x", "by": "nunchi"}')   # 옛 표시
    assert worker.want_state(home, "s9") is True and worker.want_state(home, "none") is None
    emit(home, "Stop")
    assert len(worker.pending(home)) == 1


def test_drain_drops_hook_requests_of_a_turned_off_session_but_not_control_ones(tmp_path):
    home, tr1, stop = make_session(tmp_path, n=1, sid="s1")
    _, tr2, _ = make_session(tmp_path, n=1, sid="s2")
    for sid in ("s1", "s2"):
        (home / "sessions" / sid / "want").write_text('{"on": false}')
    worker.enqueue(home, "s1", str(tr1), stop)                                       # 훅이 넣은 것
    worker.QueueAnalyzer(home, spawner=lambda c: None).request("s2", home / "sessions" / "s2", str(tr2), stop)   # 관제가 고른 것
    assert {i["session_id"]: i["by"] for i in worker.pending(home)} == {"s1": "hook", "s2": "control"}
    worker.drain(home, runner=lambda p: LEDGER, flow_runner=flow_answer, poll=0.05, reply_wait=0, max_seconds=20)
    assert analyzer.read_analysis(home / "sessions" / "s1") is None                 # 끈 세션은 분석하지 않는다
    assert analyzer.read_analysis(home / "sessions" / "s2")                           # 관제에서 직접 고른 것은 분석
    assert worker.pending(home) == []


def test_worker_command_prefers_the_rust_engine(tmp_path, monkeypatch):
    """bin/nunchi-engine이 있으면 관제도 러스트 분석기를 깨운다 (요구 이력 68)."""
    from control_tui import worker as w
    monkeypatch.setattr(w, "REPO", tmp_path)
    assert w.worker_command(tmp_path / "home")[1:] == ["-m", "control_tui.worker", "--home", str(tmp_path / "home")]
    (tmp_path / "bin").mkdir()
    engine = tmp_path / "bin" / "nunchi-engine"
    engine.write_text("#!/bin/sh\n")
    engine.chmod(0o755)
    assert w.worker_command(tmp_path / "home") == [str(engine), "worker", "--home", str(tmp_path / "home")]
