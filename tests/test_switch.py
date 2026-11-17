"""관제·mod 오가기 (요구 이력 56, REQUIREMENTS R17, SCREEN §2 ② 머리·§3·§11, BUILD_PLAN §4.8)."""

import pytest

from control_tui.app import ControlApp

from tests.test_flow_screen import flow_analysis
from tests.test_flow_view import app_for, make_session, ready, text_of

ASKS = [
    {"id": "Q1", "turn": 2, "last_turn": 2, "summary": "색 고르기", "quote": "색은 어느 쪽으로 할까요?", "state": "open"},
    {"id": "Q2", "turn": 5, "last_turn": 5, "summary": "폭 정하기", "quote": "폭은 몇 칸으로 할지", "state": "partial"},
    {"id": "Q3", "turn": 6, "last_turn": 6, "summary": "창 높이 조절", "quote": "낮은 창에서는 줄일까요?", "state": "open"},
    {"id": "Q4", "turn": 3, "summary": "진행할지", "quote": "진행할까요?", "state": "answered", "by_blanket": True},
]


def with_asks(asks=ASKS):
    a = flow_analysis(shift_turns=(2, 4))
    a["flow"]["asks"] = [dict(q) for q in asks]
    return a


@pytest.mark.asyncio
async def test_head_shows_what_the_agent_asks_most_recent_first(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=with_asks())
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "에이전트가 묻는 것 3   k 전체 보기" in text
        assert "? 창 높이 조절 “낮은 창에서는 줄일까요?”" in text     # 최근에 물은 것부터 (mod와 같은 순서)
        assert "#5 · 일부 답함" in text
        assert "… 1개 더 · k" in text                            # 머리에는 2개까지
        assert "색 고르기" not in text


@pytest.mark.asyncio
async def test_k_opens_all_asks_and_escape_closes(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=with_asks())
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("k")
        await pilot.pause()
        text = text_of(app)
        assert "아직 답 없음 2" in text and "일부 답함 1" in text and "답함 1" in text
        assert "#2부터 답 없음" in text                          # 오래 남은 것
        assert "통째 승인으로 닫은 것 1" in text and "#3 · 통째 승인" in text
        assert "k·Esc" in str(app.keybar.render())            # 맨 아래 키 안내
        await pilot.press("escape")
        await pilot.pause()
        assert "아직 답 없음 2" not in text_of(app)


@pytest.mark.asyncio
async def test_korean_input_k_also_opens_all_asks(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=with_asks())
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("ㅏ")
        await pilot.pause()
        assert "아직 답 없음 2" in text_of(app)


@pytest.mark.asyncio
async def test_no_open_asks_says_none_and_old_flow_has_no_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=with_asks([ASKS[3]]))
    app = app_for(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        assert "에이전트가 묻는 것 없음" in text_of(app)

    home2, _, _ = make_session(tmp_path / "old", n=6, analysis=flow_analysis(shift_turns=(2,)))
    app2 = app_for(home2)
    async with app2.run_test(size=(160, 50)) as pilot:
        await ready(app2, pilot)
        assert "에이전트가 묻는 것" not in text_of(app2)          # 묻는 것을 뽑기 전 흐름


# ---------- p: 세션 패널로 (9b) ----------

class FocusTerminal:
    def __init__(self, fail=False):
        self.focused, self.fail = [], fail

    def send_text(self, target_id, text, enter=True):
        pass

    def focus(self, target_id):
        from control_tui.adapters.terminal_base import TerminalError
        if self.fail:
            raise TerminalError("패널을 찾지 못했습니다.")
        self.focused.append(target_id)


async def wait_until(pilot, cond, n=40):
    for _ in range(n):
        if cond():
            return True
        await pilot.pause(0.05)
    return cond()


@pytest.mark.asyncio
async def test_p_brings_the_selected_session_panel_to_front(tmp_path):
    home, _, _ = make_session(tmp_path, n=3)
    term = FocusTerminal()
    app = app_for(home, terminal=term)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("p")
        assert await wait_until(pilot, lambda: term.focused == ["PANEL-1"])
        assert await wait_until(pilot, lambda: "패널로 옮겼습니다" in app._message[0])


@pytest.mark.asyncio
async def test_p_in_korean_input_and_closed_panel(tmp_path):
    home, _, _ = make_session(tmp_path, n=3)
    term = FocusTerminal()
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(), terminal=term)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.session_list.focus()
        await pilot.press("ㅔ")
        await pilot.pause()
        assert term.focused == []                                 # Claude가 없는 패널로는 가지 않는다
        assert "Claude가 떠 있지 않습니다" in app._message[0]


# ---------- 돌아오기 (9c) ----------

import json as _json
import os
import time as _time

from textual import events as _events


def two_sessions(tmp_path):
    home, _, _ = make_session(tmp_path, n=3, sid="s1")
    make_session(tmp_path / "b", n=3, sid="s2")
    import shutil
    shutil.copytree(tmp_path / "b" / "home" / "sessions" / "s2", home / "sessions" / "s2")
    ev = home / "sessions" / "s2" / "events.jsonl"     # 세션마다 다른 패널 (같은 패널이면 앞 세션은 닫힌 것으로 본다)
    ev.write_text(ev.read_text(encoding="utf-8").replace("PANEL-1", "PANEL-2"), encoding="utf-8")
    return home


def app2(home):
    return ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: {"PANEL-1", "PANEL-2"})


def prompt(home, sid, ts):
    with open(home / "sessions" / sid / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(_json.dumps({"ts": ts, "session_id": sid, "event": "UserPromptSubmit", "cwd": f"/work/{sid}",
                             "iterm_session_id": "w0t0p0:" + ("PANEL-1" if sid == "s1" else "PANEL-2"), "data": {}}) + "\n")


def iso(epoch):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def leave_and_return(app, pilot, between=None):
    app.post_message(_events.AppBlur())
    await pilot.pause()
    if between:
        between()
    app.post_message(_events.AppFocus())
    await pilot.pause()
    await pilot.pause()


@pytest.mark.asyncio
async def test_return_selects_the_session_the_user_typed_in(tmp_path):
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        first = app.session_list.selected_id
        other = "s2" if first == "s1" else "s1"
        await leave_and_return(app, pilot, lambda: prompt(home, other, iso(_time.time() + 1)))
        assert app.session_list.selected_id == other
        assert "방금 입력한 세션" in app._message[0]


@pytest.mark.asyncio
async def test_return_keeps_the_session_when_a_draft_is_in_the_input(tmp_path):
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        first = app.session_list.selected_id
        other = "s2" if first == "s1" else "s1"
        app.input_box.insert("쓰던 글")
        await leave_and_return(app, pilot, lambda: prompt(home, other, iso(_time.time() + 1)))
        assert app.session_list.selected_id == first               # Enter가 다른 패널로 가지 않게
        assert "쓰던 글이 있어" in app._message[0]


@pytest.mark.asyncio
async def test_goto_from_the_mod_button_wins_and_is_consumed(tmp_path):
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        first = app.session_list.selected_id
        other = "s2" if first == "s1" else "s1"

        def press():
            (home / "goto").write_text(_json.dumps({"session": other, "at": _time.time() + 0.5}))
        await leave_and_return(app, pilot, press)
        assert app.session_list.selected_id == other
        assert "mod에서 관제로" in app._message[0]
        assert not (home / "goto").exists()


@pytest.mark.asyncio
async def test_no_blur_or_old_input_changes_nothing(tmp_path):
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        first = app.session_list.selected_id
        other = "s2" if first == "s1" else "s1"
        prompt(home, other, iso(_time.time() - 5))                 # 떠나기 전 입력
        app.post_message(_events.AppFocus())                        # 떠난 기록 없이 온 focus
        await pilot.pause()
        assert app.session_list.selected_id == first
        await leave_and_return(app, pilot)                          # 떠난 뒤 입력 없음 (그 전 입력은 무시)
        await pilot.pause()
        assert app.session_list.selected_id == first


@pytest.mark.asyncio
async def test_control_file_has_own_panel_and_is_removed_on_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w1t2p0:CTRL-UUID")
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        data = _json.loads((home / "control.json").read_text())
        assert data["iterm_session_id"] == "CTRL-UUID" and data["pid"] == os.getpid()
    assert not (home / "control.json").exists()


@pytest.mark.asyncio
async def test_input_the_control_sent_itself_is_not_a_return_target(tmp_path):
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        first = app.session_list.selected_id
        other = "s2" if first == "s1" else "s1"

        def control_sent():
            now = _time.time()
            app._last_sent[other] = iso(now + 1)                     # 관제가 보낸 글 (대기열 전송)
            prompt(home, other, iso(now + 2))                        # 그 글의 입력 기록
        await leave_and_return(app, pilot, control_sent)
        assert app.session_list.selected_id == first


@pytest.mark.asyncio
async def test_low_screen_keeps_only_the_asks_count_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=with_asks())
    app = app_for(home)
    async with app.run_test(size=(160, 30)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "에이전트가 묻는 것 3" in text
        assert "창 높이 조절" not in text and "… 1개 더 · k" not in text


async def test_goto_while_the_control_is_already_in_front(tmp_path):
    """관제가 이미 앞에 있을 때 mod '관제로'를 누르면 화면 전환 알림이 오지 않는다. 새로 고침에서 goto를 집는다."""
    import json, time
    home = two_sessions(tmp_path)
    app = app2(home)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.refresh_sessions()
        await pilot.pause()
        app._blurred_at = None          # 떠난 적 없음 (앞에 있음)
        (home / "goto").write_text(json.dumps({"session": "s2", "at": time.time()}))
        app.refresh_sessions()
        await pilot.pause()
        await pilot.pause()
        assert app.session_list.selected().session_id == "s2"
        assert not (home / "goto").exists()
