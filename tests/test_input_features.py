"""③ 입력줄이 Claude Code 입력창의 기본 동작을 따르는지 (control_tui/widgets/input_line.py).

실제 iTerm에는 보내지 않는다. 전송 내용은 가짜 터미널로 확인한다.
"""

import json

import pytest

from control_tui.adapters import iterm2_adapter
from control_tui.app import ControlApp
from control_tui.widgets.input_line import CommandInput


class FakeTerminal:
    def __init__(self):
        self.sent = []

    def send_text(self, target_id, text, enter=True):
        self.sent.append(text)


def make_app(tmp_path, terminal):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    row = {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": "Stop",
           "cwd": "/work/demo", "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1",
           "data": {}}
    (d / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], terminal=terminal,
                      panel_checker=lambda: {"PANEL-1"})


# ---------- 입력 편집 ----------

@pytest.mark.asyncio
async def test_korean_text_is_kept_as_typed(tmp_path):
    app = make_app(tmp_path, FakeTerminal())
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert("한글 입력 테스트")
        await pilot.pause()
        assert app.input_box.text == "한글 입력 테스트"


@pytest.mark.asyncio
async def test_ctrl_j_makes_a_newline_without_sending(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, term)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert("첫 줄")
        await pilot.press("ctrl+j")
        app.input_box.insert("둘째 줄")
        await pilot.pause()
        assert app.input_box.text == "첫 줄\n둘째 줄"
        assert term.sent == []


@pytest.mark.asyncio
async def test_backslash_then_enter_makes_newline(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, term)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert("앞부분\\")
        await pilot.press("enter")
        await pilot.pause()
        assert app.input_box.text == "앞부분\n"
        assert term.sent == []


@pytest.mark.asyncio
async def test_escape_clears_and_up_recalls_last_sent_text(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, term)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert("첫 지시")
        await pilot.press("enter")
        await pilot.pause()
        assert term.sent == ["첫 지시"]
        app.input_box.insert("쓰다 만 글")
        await pilot.press("escape")
        await pilot.pause()
        assert app.input_box.text == ""
        # Esc로 지운 글도 기록에 남으므로 ↑는 그 글을 먼저 보여 준다
        await pilot.press("up")
        await pilot.pause()
        assert app.input_box.text == "쓰다 만 글"
        await pilot.press("up")
        await pilot.pause()
        assert app.input_box.text == "첫 지시"


@pytest.mark.asyncio
async def test_down_returns_to_the_unsent_draft(tmp_path):
    app = make_app(tmp_path, FakeTerminal())
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.remember("지난 글")
        app.input_box.insert("지금 쓰는 글")
        await pilot.press("up")
        await pilot.pause()
        assert app.input_box.text == "지난 글"
        await pilot.press("down")
        await pilot.pause()
        assert app.input_box.text == "지금 쓰는 글"


# ---------- 전송 내용은 바꾸지 않는다 ----------

@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "/review-pr 123",            # 스킬·슬래시 명령
    "@src/app.py 이 파일 고쳐줘",  # 파일 참조
    "!ls -la",                   # 셸 모드
    "#프로젝트 규칙 메모",          # 메모
    "한글 /명령 @파일 섞기",        # 섞여도 그대로
])
async def test_claude_commands_reach_the_session_unchanged(tmp_path, text):
    term = FakeTerminal()
    app = make_app(tmp_path, term)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert(text)
        await pilot.press("enter")
        await pilot.pause()
    assert term.sent == [text]


@pytest.mark.asyncio
async def test_multiline_text_is_sent_as_one_piece(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, term)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()  # 사용자가 ③을 고른 상태
        await pilot.pause()
        app.input_box.insert("1행\n2행\n3행")
        await pilot.press("enter")
        await pilot.pause()
    assert term.sent == ["1행\n2행\n3행"]


def test_multiline_send_is_wrapped_as_bracketed_paste(monkeypatch):
    calls = []
    monkeypatch.setattr(iterm2_adapter, "_osascript", lambda args: calls.append(args) or "ok")
    iterm2_adapter.ITerm2Adapter().send_text("PANEL-1", "가\n나")
    assert calls[0][1] == "\x1b[200~가\n나\x1b[201~"


def test_single_line_send_is_not_wrapped(monkeypatch):
    calls = []
    monkeypatch.setattr(iterm2_adapter, "_osascript", lambda args: calls.append(args) or "ok")
    iterm2_adapter.ITerm2Adapter().send_text("PANEL-1", "한 줄")
    assert calls[0][1] == "한 줄"


def test_command_input_is_a_text_area():
    from textual.widgets import TextArea
    assert issubclass(CommandInput, TextArea)
