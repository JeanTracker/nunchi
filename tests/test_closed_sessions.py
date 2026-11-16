"""닫힌 세션: 종료 판정, 맨 아래 배치, 10분 뒤 숨김 (요청 35, REQUIREMENTS R10, BUILD_PLAN §3.1.1)."""

import json

import pytest

from control_tui import lifecycle, panels, store
from control_tui.app import ControlApp
from control_tui.store import SessionView

NOW = "2026-11-10T06:00:00.000Z"
# conftest가 테스트마다 panels.alive_panel_ids를 가짜로 바꾸므로, 원래 함수는 불러올 때 잡아 둔다
_REAL_ALIVE = panels.alive_panel_ids


def view(sid, state="responded", last="2026-11-10T05:59:00.000Z", panel="P1", ended=""):
    return SessionView(session_id=sid, cwd=f"/w/{sid}", state=state, last_ts=last,
                       responded_ts=last if state == "responded" else "",
                       iterm_session_id=f"w0t0p0:{panel}" if panel else "", ended_ts=ended)


# ---------- 종료 판정 ----------

def test_session_end_hook_sets_ended_time():
    v = store.summarize("s1", [
        {"ts": "2026-11-10T05:00:00.000Z", "event": "Stop"},
        {"ts": "2026-11-10T05:01:00.000Z", "event": "SessionEnd"}])
    assert v.state == "ended" and v.ended_ts == "2026-11-10T05:01:00.000Z"


def test_restart_clears_ended_time():
    v = store.summarize("s1", [
        {"ts": "2026-11-10T05:01:00.000Z", "event": "SessionEnd"},
        {"ts": "2026-11-10T05:02:00.000Z", "event": "SessionStart"}])
    assert v.state == "idle" and v.ended_ts == ""


def test_panel_without_claude_is_closed_at_notice_time():
    t = lifecycle.ClosedTracker()
    t.update_alive({"P2"}, "2026-11-10T05:59:30.000Z")
    vs = [view("a", panel="P1"), view("b", panel="P2")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "ended" and vs[0].ended_ts == NOW
    assert vs[1].state == "responded"


def test_failed_check_changes_nothing():
    t = lifecycle.ClosedTracker()
    t.update_alive(None, NOW)
    vs = [view("a")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "responded"


def test_failed_check_keeps_last_good_result():
    t = lifecycle.ClosedTracker()
    t.update_alive({"P1"}, "2026-11-10T05:59:30.000Z")
    t.update_alive(None, NOW)
    vs = [view("a")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "responded"


def test_session_newer_than_last_check_is_not_judged():
    """확인은 10초마다다. 확인 뒤에 막 켠 세션을 닫혔다고 보지 않는다."""
    t = lifecycle.ClosedTracker()
    t.update_alive(set(), "2026-11-10T05:59:00.000Z")
    vs = [view("new", last="2026-11-10T05:59:05.000Z", panel="P9")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "responded"


def test_older_session_in_same_panel_is_closed():
    """같은 패널에서 claude를 다시 켜면 앞 세션은 끝난 것이다."""
    t = lifecycle.ClosedTracker()
    vs = [view("old", last="2026-11-10T05:00:00.000Z"), view("new", last="2026-11-10T05:50:00.000Z")]
    t.mark(vs, now=NOW)
    assert [v.state for v in vs] == ["ended", "responded"]


def test_closed_before_control_started_uses_last_record_time():
    """관제를 켜기 전에 이미 닫힌 세션은 다시 10분 보이지 않는다."""
    t = lifecycle.ClosedTracker()
    vs = [view("old", last="2026-11-09T05:00:00.000Z"), view("new", last="2026-11-10T05:50:00.000Z")]
    t.mark(vs, now=NOW)
    assert vs[0].ended_ts == "2026-11-09T05:00:00.000Z"
    assert [v.session_id for v in lifecycle.arrange(vs, now=NOW)] == ["new"]


def test_notice_time_is_kept_across_refreshes():
    t = lifecycle.ClosedTracker()
    t.update_alive(set(), "2026-11-10T05:59:30.000Z")
    t.mark([view("a")], now=NOW)
    later = [view("a")]  # 다음 갱신에서 기록을 새로 읽은 것
    t.mark(later, now="2026-11-10T06:05:00.000Z")
    assert later[0].ended_ts == NOW


def test_session_comes_back_when_it_records_again():
    t = lifecycle.ClosedTracker()
    t.update_alive(set(), "2026-11-10T05:59:30.000Z")
    vs = [view("a")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "ended"
    t.update_alive({"P1"}, "2026-11-10T06:00:10.000Z")
    again = [view("a", last="2026-11-10T06:00:05.000Z")]
    t.mark(again, now="2026-11-10T06:00:11.000Z")
    assert again[0].state == "responded"


def test_sessions_outside_iterm_are_left_alone():
    t = lifecycle.ClosedTracker()
    t.update_alive(set(), "2026-11-10T05:59:30.000Z")
    vs = [view("a", panel="")]
    t.mark(vs, now=NOW)
    assert vs[0].state == "responded"


# ---------- 배치와 숨김 ----------

def test_ended_go_below_live_most_recent_first():
    vs = [view("e1", state="ended", ended="2026-11-10T05:55:00.000Z"),
          view("live"),
          view("e2", state="ended", ended="2026-11-10T05:58:00.000Z")]
    assert [v.session_id for v in lifecycle.arrange(vs, now=NOW)] == ["live", "e2", "e1"]


def test_ended_hidden_after_ten_minutes_unless_selected():
    vs = [view("live"), view("old", state="ended", ended="2026-11-10T05:49:00.000Z"),
          view("fresh", state="ended", ended="2026-11-10T05:51:00.000Z")]
    assert [v.session_id for v in lifecycle.arrange(vs, now=NOW)] == ["live", "fresh"]
    assert [v.session_id for v in lifecycle.arrange(vs, selected_id="old", now=NOW)] == ["live", "fresh", "old"]


# ---------- 앱에서 ----------

def write_session(home, sid, rows):
    d = home / "sessions" / sid
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def ev(sid, name, ts, panel):
    return {"ts": ts, "session_id": sid, "event": name, "cwd": f"/work/{sid}",
            "transcript_path": "", "iterm_session_id": f"w0t0p0:{panel}", "data": {}}


@pytest.mark.asyncio
async def test_app_marks_closed_panel_and_moves_it_down(tmp_path):
    home = tmp_path / "home"
    recent = lifecycle.now_iso()
    write_session(home, "closed1", [ev("closed1", "Stop", recent, "PA")])
    write_session(home, "alive1", [ev("alive1", "Stop", "2026-11-10T00:00:00.000Z", "PB")])
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: {"PB"},
                     liveness_checker=lambda: {"PB"})
    async with app.run_test(size=(160, 40)) as pilot:
        await app.workers.wait_for_complete()  # 켤 때 뒤에서 돈 패널 확인이 끝나기를 기다린다
        app.refresh_sessions()  # 기록은 확인보다 앞이라 판정 대상이다
        await pilot.pause()
        ids = [v.session_id for v in app.session_list.views]
        states = {v.session_id: v.state for v in app.session_list.views}
        assert ids == ["alive1", "closed1"]
        assert states["closed1"] == "ended"
        assert "종료" in str(app.session_list.render_text())


def test_alive_panel_ids_returns_none_when_check_fails(monkeypatch):
    """확인이 실패하면 빈 모음이 아니라 None이다 (모든 세션이 한꺼번에 종료로 바뀌지 않게)."""
    monkeypatch.setattr(panels, "iterm_running", lambda ps_comm=None: True)
    monkeypatch.setattr(panels, "_run", lambda args, script=None: "")
    assert _REAL_ALIVE() is None


@pytest.mark.asyncio
async def test_slow_panel_check_does_not_block_screen(tmp_path):
    """패널 확인은 0.5초쯤 걸린다. 화면 갱신이 그 시간을 기다리지 않아야 한다."""
    import threading, time
    release = threading.Event()

    def slow():
        release.wait(2)
        return set()

    home = tmp_path / "home"
    write_session(home, "s1", [ev("s1", "Stop", lifecycle.now_iso(), "PA")])
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(),
                     liveness_checker=slow)
    async with app.run_test(size=(160, 40)) as pilot:
        # 켤 때 시작한 확인이 아직 끝나지 않았는데도 화면이 떴고, 갱신도 기다리지 않는다
        assert app._alive_busy is True
        t = time.perf_counter()
        app.refresh_sessions()
        assert time.perf_counter() - t < 0.3
        assert [v.session_id for v in app.session_list.views] == ["s1"]
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._alive_busy is False
        app._last_alive_check = None
        app.refresh_sessions()  # 확인 결과(빈 모음)가 들어온 뒤에는 닫힘으로 본다
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.refresh_sessions()
        assert app.session_list.views[0].state == "ended"
