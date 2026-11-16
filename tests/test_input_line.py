"""Phase 3: ③ 입력줄 (SCREEN.md §4, BUILD_PLAN §5.1). 실제 iTerm에는 보내지 않는다."""

import json

import pytest

from control_tui import config, outbox, panels
from control_tui.adapters import iterm2_adapter
from control_tui.adapters.terminal_base import TerminalError
from control_tui.app import ControlApp
from control_tui.store import SessionView

ALIVE = {"PANEL-1111-2222"}  # 테스트에서 claude가 떠 있다고 보는 패널


# ---------- 순수 규칙 ----------

def view(sid, state, last_ts="t1", panel="PANEL-1111-2222"):
    return SessionView(session_id=sid, cwd="/work/demo", state=state, last_ts=last_ts,
                       iterm_session_id=f"w0t0p0:{panel}")


def test_decide_follows_screen_section_4():
    assert outbox.decide("idle") == outbox.SEND
    assert outbox.decide("responded") == outbox.SEND
    assert outbox.decide("working") == outbox.QUEUE
    assert outbox.decide("permission") == outbox.PERMISSION
    assert outbox.decide("ended") == outbox.REFUSE
    assert outbox.decide("pending") == outbox.REFUSE


def test_queue_waits_while_working_and_sends_when_responded():
    box = outbox.Outbox()
    box.enqueue("s1", "다음 지시")
    assert box.peek_ready([view("s1", "working")], now=0.0) == []
    ready = box.peek_ready([view("s1", "responded")], now=0.0)
    assert [(v.session_id, text) for v, text in ready] == [("s1", "다음 지시")]


def test_queue_sends_one_at_a_time_until_the_record_moves():
    box = outbox.Outbox()
    box.enqueue("s1", "첫째")
    box.enqueue("s1", "둘째")
    box.mark_sent("s1", last_ts="t1", now=0.0)
    # 보낸 직후 기록이 아직 안 바뀌었으면 또 보내지 않는다
    assert box.peek_ready([view("s1", "responded", last_ts="t1")], now=1.0) == []
    # 새 기록(UserPromptSubmit)이 보이고 다시 응답이 오면 다음 건을 보낸다
    assert box.peek_ready([view("s1", "responded", last_ts="t2")], now=5.0)[0][1] == "둘째"


def test_in_flight_gives_up_after_timeout():
    box = outbox.Outbox()
    box.enqueue("s1", "지시")
    box.enqueue("s1", "다음")
    box.mark_sent("s1", last_ts="t1", now=0.0)
    assert box.peek_ready([view("s1", "responded", last_ts="t1")],
                          now=outbox.IN_FLIGHT_SECONDS + 1)[0][1] == "다음"


def test_queue_count_is_per_session():
    box = outbox.Outbox()
    box.enqueue("s1", "a")
    box.enqueue("s1", "b")
    box.enqueue("s2", "c")
    assert (box.count("s1"), box.count("s2"), box.count("none")) == (2, 1, 0)


# ---------- iTerm 어댑터 (명령 모양만 확인) ----------

def test_iterm_send_passes_text_as_argument_not_script(monkeypatch):
    calls = []
    monkeypatch.setattr(iterm2_adapter, "_osascript", lambda args: calls.append(args) or "ok")
    danger = 'rm -rf "x" \\ end'
    iterm2_adapter.ITerm2Adapter().send_text("PANEL-1", danger)
    assert calls == [["PANEL-1", danger, "1"]]
    assert danger not in iterm2_adapter.SEND_SCRIPT


def test_iterm_send_without_enter_sets_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(iterm2_adapter, "_osascript", lambda args: calls.append(args) or "ok")
    iterm2_adapter.ITerm2Adapter().send_text("PANEL-1", "y", enter=False)
    assert calls[0][2] == "0"


def test_enter_is_carriage_return_not_newline_in_script():
    # Enter는 캐리지 리턴(ASCII 13)으로 따로 보낸다. 글 끝에 줄바꿈을 붙이지 않는다 (BUILD_PLAN §5.1)
    assert "ASCII character 13" in iterm2_adapter.SEND_SCRIPT
    assert "linefeed" not in iterm2_adapter.SEND_SCRIPT.lower()


def test_send_script_compiles_as_applescript(tmp_path):
    # 실행하지 않고 컴파일만 한다. iTerm에는 닿지 않는다.
    import shutil, subprocess
    if shutil.which("osacompile") is None:
        pytest.skip("osacompile 없음 (macOS 전용)")
    src = tmp_path / "send.applescript"
    src.write_text(iterm2_adapter.SEND_SCRIPT, encoding="utf-8")
    result = subprocess.run(["osacompile", "-o", str(tmp_path / "send.scpt"), str(src)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_iterm_missing_panel_raises(monkeypatch):
    monkeypatch.setattr(iterm2_adapter, "_osascript", lambda args: "missing")
    with pytest.raises(TerminalError):
        iterm2_adapter.ITerm2Adapter().send_text("PANEL-1", "hi")


def test_iterm_send_without_panel_id_raises():
    with pytest.raises(TerminalError):
        iterm2_adapter.ITerm2Adapter().send_text("", "hi")


# ---------- 화면 ----------

class FakeTerminal:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_text(self, target_id, text, enter=True):
        if self.fail:
            raise TerminalError("패널 없음")
        self.sent.append((target_id, text, enter))


def write_events(home, sid, rows):
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def event(sid, name, ts, panel="PANEL-1111-2222", data=None):
    return {"ts": ts, "session_id": sid, "event": name, "cwd": "/work/demo",
            "transcript_path": "", "iterm_session_id": f"w0t0p0:{panel}" if panel else "",
            "data": data or {}}


def setup_home(tmp_path, rows_by_session):
    home = tmp_path / "home"
    home.mkdir()
    for sid, rows in rows_by_session.items():
        write_events(home, sid, rows)
    return home


def make_app(home, term=None, alive=ALIVE):
    return ControlApp(home=home, panel_scanner=lambda ids: [],
                      terminal=term or FakeTerminal(), panel_checker=lambda: set(alive))


def info_text(app):
    return str(app.info_line.render())


def submit(app, text):
    app.input_box.value = text
    app.input_box.post_message(app.input_box.Submitted(app.input_box, text))


@pytest.mark.asyncio
async def test_enter_sends_directly_when_session_is_idle(tmp_path):
    home = setup_home(tmp_path, {"s1": [
        event("s1", "SessionStart", "2026-11-09T01:00:00.000Z"),
        event("s1", "Stop", "2026-11-09T01:01:00.000Z")]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "다음 지시")
        await pilot.pause()
    assert term.sent == [("PANEL-1111-2222", "다음 지시", True)]


@pytest.mark.asyncio
async def test_working_session_queues_and_sends_after_response(tmp_path):
    home = setup_home(tmp_path, {"s1": [
        event("s1", "UserPromptSubmit", "2026-11-09T01:00:00.000Z")]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "기다렸다가")
        await pilot.pause()
        assert term.sent == []
        assert app.outbox.count("s1") == 1
        assert "대기열 1건" in info_text(app)

        # 응답이 도착하면 한 건 보낸다
        write_events(home, "s1", [
            event("s1", "UserPromptSubmit", "2026-11-09T01:00:00.000Z"),
            event("s1", "Stop", "2026-11-09T01:02:00.000Z")])
        app.refresh_sessions()
        await pilot.pause()
    assert term.sent == [("PANEL-1111-2222", "기다렸다가", True)]
    assert app.outbox.count("s1") == 0


@pytest.mark.asyncio
async def test_queued_text_is_not_sent_when_panel_went_back_to_shell(tmp_path):
    home = setup_home(tmp_path, {"s1": [
        event("s1", "UserPromptSubmit", "2026-11-09T01:00:00.000Z")]})
    term = FakeTerminal()
    alive = set(ALIVE)
    app = make_app(home, term, alive=alive)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "셸에 들어가면 안 되는 글")
        await pilot.pause()
        # 기록은 아직 '작업 중'인데, 패널은 셸로 돌아갔다 (Stop 기록이 빠진 경우)
        alive.clear()
        write_events(home, "s1", [
            event("s1", "UserPromptSubmit", "2026-11-09T01:00:00.000Z"),
            event("s1", "Stop", "2026-11-09T01:02:00.000Z")])
        app.refresh_sessions()
        await pilot.pause()
    assert term.sent == []
    assert app.outbox.count("s1") == 1  # 글은 남는다
    assert "대기열 보류" in info_text(app)


@pytest.mark.asyncio
async def test_direct_send_refused_when_no_claude_on_panel(tmp_path):
    home = setup_home(tmp_path, {"s1": [event("s1", "Stop", "2026-11-09T01:01:00.000Z")]})
    term = FakeTerminal()
    app = make_app(home, term, alive=set())
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "rm -rf 해줘")
        await pilot.pause()
        assert term.sent == []
        assert app.input_box.value == "rm -rf 해줘"
        assert "Claude가 떠 있지 않아" in info_text(app)


@pytest.mark.asyncio
async def test_session_without_iterm_panel_is_refused(tmp_path):
    home = setup_home(tmp_path, {"s1": [event("s1", "Stop", "2026-11-09T01:01:00.000Z", panel=None)]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "안녕")
        await pilot.pause()
    assert term.sent == []
    assert "짝이 없어" in info_text(app)


@pytest.mark.asyncio
async def test_permission_locks_input_and_keys_wait_for_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PERMISSION_KEYS_VERIFIED", False)  # 확인 전 잠금 동작은 그대로 지킨다
    home = setup_home(tmp_path, {"s1": [
        event("s1", "UserPromptSubmit", "2026-11-09T01:00:00.000Z"),
        event("s1", "Notification", "2026-11-09T01:00:05.000Z",
              data={"notification_type": "permission_prompt"})]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert app.input_box.disabled is True
        await pilot.press("y")
        await pilot.pause()
    assert term.sent == []
    assert "실험 확인" in info_text(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("key, sent", [("n", "\x1b"), ("y", "1")])
async def test_permission_keys_send_verified_keys_without_enter(tmp_path, key, sent):
    """2026-11-09 실험: 허락 창은 y/n 글자를 무시한다. 1 = 한 번 허용, Esc = 거절. Enter는 1번(Yes)을 고르므로 보내지 않는다."""
    assert config.PERMISSION_KEYS_VERIFIED is True
    home = setup_home(tmp_path, {"s1": [
        event("s1", "Notification", "2026-11-09T01:00:05.000Z",
              data={"notification_type": "permission_prompt"})]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
    assert term.sent == [("PANEL-1111-2222", sent, False)]


@pytest.mark.asyncio
async def test_letters_do_not_type_into_input_during_permission(tmp_path):
    home = setup_home(tmp_path, {"s1": [
        event("s1", "Notification", "2026-11-09T01:00:05.000Z",
              data={"notification_type": "permission_prompt"})]})
    app = make_app(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.press("i", "x")
        await pilot.pause()
        assert app.input_box.value == ""


@pytest.mark.asyncio
async def test_typed_action_letters_stay_in_input_and_do_not_quit(tmp_path):
    # q y n i는 앱 단축키다. 입력칸에 포커스가 있으면 글자로만 들어가야 한다
    home = setup_home(tmp_path, {"s1": [event("s1", "Stop", "2026-11-09T01:01:00.000Z")]})
    app = make_app(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.press("q", "y", "n", "i")
        await pilot.pause()
        assert app.is_running
        assert app.focused is app.input_box
        assert app.input_box.value == "qyni"


@pytest.mark.asyncio
async def test_ended_and_pending_sessions_refuse_with_reason(tmp_path):
    # 방금 끝난 세션 (10분이 지난 종료 세션은 목록에서 숨는다, 요청 35)
    from control_tui.lifecycle import now_iso
    home = setup_home(tmp_path, {"s1": [
        event("s1", "SessionEnd", now_iso())]})
    term = FakeTerminal()
    app = make_app(home, term)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "안녕")
        await pilot.pause()
    assert term.sent == []
    assert "끝난 세션" in info_text(app)


@pytest.mark.asyncio
async def test_failed_send_keeps_text_and_reports_error(tmp_path):
    home = setup_home(tmp_path, {"s1": [event("s1", "Stop", "2026-11-09T01:01:00.000Z")]})
    app = make_app(home, FakeTerminal(fail=True))
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        submit(app, "남겨둘 글")
        await pilot.pause()
        assert app.input_box.value == "남겨둘 글"
        assert "보내지 못했습니다" in info_text(app)


@pytest.mark.asyncio
async def test_i_key_focuses_input(tmp_path):
    home = setup_home(tmp_path, {"s1": [event("s1", "Stop", "2026-11-09T01:01:00.000Z")]})
    app = make_app(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert app.focused is app.input_box
