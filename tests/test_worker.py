"""관제 화면 쪽 분석 요청 (요구 이력 52·53·68, BUILD_PLAN §4.7·§4.13).

분석기 자체(대기열 처리, 자리·맡기, 훅)는 러스트 엔진이 하고 crates/engine/tests가 확인한다.
여기서는 관제 화면이 요청을 남기고, 분석기를 깨우고, 상태를 읽는 쪽을 본다. 분석기를 실제로 띄우지 않는다.
"""

import json
from pathlib import Path

import pytest

from control_tui import analyzer, worker
from tests.test_flow_view import make_session


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """깨울 엔진이 있는 것처럼 (실제로 띄우지는 않는다)"""
    exe = tmp_path / "engine-bin" / "nunchi-engine"
    monkeypatch.setattr(worker, "engine_path", lambda: exe)
    return exe


def status_file(d, **data):
    (d / analyzer.STATUS_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------- 대기열 ----------

def test_enqueue_merges_to_the_latest_answer_and_keeps_force(tmp_path):
    worker.enqueue(tmp_path, "s1", "/t.jsonl", "2026-11-16T00:00:02.000Z", force=True)
    worker.enqueue(tmp_path, "s1", "/t.jsonl", "2026-11-16T00:00:01.000Z")   # 더 옛 응답은 덮지 않는다
    items = worker.pending(tmp_path)
    assert len(items) == 1 and items[0]["source_ts"] == "2026-11-16T00:00:02.000Z" and items[0]["force"]


def test_slots_follow_the_workers_setting(tmp_path):
    a = worker.take_slot(tmp_path, 1)
    assert a is not None and worker.take_slot(tmp_path, 1) is None      # 기본 1개
    b = worker.take_slot(tmp_path, 2)
    assert b is not None and worker.take_slot(tmp_path, 5) is None      # 최대 2개
    worker._unlock(a)
    worker._unlock(b)


# ---------- 관제 쪽 (QueueAnalyzer) ----------

def test_control_requests_wake_the_worker_and_show_queued(tmp_path, engine):
    home, tr, stop = make_session(tmp_path)
    spawned = []
    q = worker.QueueAnalyzer(home, spawner=spawned.append)
    d = home / "sessions" / "s1"
    assert q.request("s1", d, str(tr), stop)
    assert spawned == [[str(engine), "worker", "--home", str(home)]]
    assert q.status("s1") == {"state": "queued", "ahead": 0, "source_ts": stop}
    assert not q.request("s1", d, str(tr), stop)            # 이미 줄에 있으면 또 쓰지 않는다
    q.prioritize("s1")
    assert (worker.queue_dir(home) / worker.PRIORITY_FILE).read_text() == "s1"


def test_without_any_engine_the_request_waits_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "engine_path", lambda: None)
    home, tr, stop = make_session(tmp_path)
    spawned = []
    q = worker.QueueAnalyzer(home, spawner=spawned.append)
    assert q.request("s1", home / "sessions" / "s1", str(tr), stop)
    assert spawned == [] and worker.pending(home)          # 요청은 남는다 (훅이 깨우는 분석기가 가져갈 수 있게)
    st = q.status("s1")
    assert st["state"] == "failed" and "분석 엔진 없음" in st["error"]


def test_control_reads_running_and_failed_from_the_status_file(tmp_path, engine):
    home, tr, stop = make_session(tmp_path)
    d = home / "sessions" / "s1"
    q = worker.QueueAnalyzer(home, spawner=lambda cmd: None)
    import os
    status_file(d, state="running", turn=2, pid=os.getpid(), since="2026-11-16T00:00:00.000000Z", source_ts=stop)
    st = q.status("s1")
    assert st["state"] == "running" and st["turn"] == 2 and st["seconds"] > 0
    status_file(d, state="failed", turn=0, error="시간 초과 (150초)", source_ts=stop, attempts=analyzer.MAX_ATTEMPTS)
    assert q.status("s1") == {"state": "failed", "error": "시간 초과 (150초)", "source_ts": stop}
    assert not q.request("s1", d, str(tr), stop)            # 횟수를 다 쓴 실패는 r로만
    assert q.request("s1", d, str(tr), stop, force=True)


def test_dead_worker_status_is_not_shown_as_running(tmp_path):
    home, tr, stop = make_session(tmp_path)
    d = home / "sessions" / "s1"
    status_file(d, state="running", turn=1, pid=999999)
    assert worker.QueueAnalyzer(home, spawner=lambda c: None).status("s1") == {"state": ""}


# ---------- 깨울 엔진 찾기 ----------

def test_engine_is_the_repository_build_then_the_installed_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "REPO", tmp_path / "repo")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    assert worker.engine_path() is None and worker.worker_command(tmp_path / "home") is None

    def exe(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path

    old = exe(tmp_path / "cache" / "0.3.0" / "bin" / "nunchi-engine")
    new = exe(tmp_path / "cache" / "0.3.1" / "bin" / "nunchi-engine")
    plugins = tmp_path / "claude" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
        "nunchi@nunchi": [{"installPath": str(old.parent.parent), "lastUpdated": "2026-11-16T00:00:00Z"},
                          {"installPath": str(new.parent.parent), "lastUpdated": "2026-11-17T00:00:00Z"}],
        "other@x": [{"installPath": "/nowhere"}]}}))
    assert worker.engine_path() == new                      # 설치된 플러그인 중 최근 것
    built = exe(tmp_path / "repo" / "bin" / "nunchi-engine")
    assert worker.engine_path() == built                    # 저장소에서 빌드한 것이 먼저
    assert worker.worker_command(tmp_path / "home") == [str(built), "worker", "--home", str(tmp_path / "home")]
