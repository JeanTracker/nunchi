"""Shift+Enter 줄바꿈, Shift+Tab 권한 모드 전환, 훅이 알려 준 모드 표시."""

import json
from pathlib import Path

import pytest

from control_tui.app import MODE_LABEL, SHIFT_TAB, ControlApp

ROOT = Path(__file__).resolve().parent.parent


class FakeTerminal:
    def __init__(self):
        self.sent = []

    def send_text(self, target_id, text, enter=True):
        self.sent.append((text, enter))


def make_app(tmp_path, rows, terminal, alive=("PANEL-1",)):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                    encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], terminal=terminal,
                      panel_checker=lambda: set(alive), skill_home=tmp_path / "userhome")


def row(event, data=None):
    return {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": event,
            "cwd": "/work/demo", "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1",
            "data": data or {}}


async def ready(app, pilot):
    await pilot.pause()
    app.input_box.focus()
    await pilot.pause()


# ---------- 줄바꿈 키 ----------

@pytest.mark.asyncio
async def test_shift_enter_makes_a_newline_and_does_not_send(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, [row("Stop")], term)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("첫 줄")
        await pilot.press("shift+enter")
        app.input_box.insert("둘째 줄")
        await pilot.pause()
        assert app.input_box.text == "첫 줄\n둘째 줄"
        assert term.sent == []


@pytest.mark.asyncio
async def test_alt_enter_makes_a_newline_and_does_not_send(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, [row("Stop")], term)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("가")
        await pilot.press("alt+enter")
        app.input_box.insert("나")
        await pilot.pause()
        assert app.input_box.text == "가\n나"
        assert term.sent == []


# ---------- Shift+Tab 권한 모드 ----------

@pytest.mark.asyncio
async def test_shift_tab_sends_the_mode_key_once_without_enter(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, [row("Stop")], term)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        await pilot.press("shift+tab")
        await pilot.pause()
    assert term.sent == [(SHIFT_TAB, False)]


@pytest.mark.asyncio
async def test_shift_tab_keeps_focus_in_the_input(tmp_path):
    app = make_app(tmp_path, [row("Stop")], FakeTerminal())
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused is app.input_box


@pytest.mark.asyncio
async def test_shift_tab_is_refused_when_no_claude_on_the_panel(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, [row("Stop")], term, alive=())
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        await pilot.press("shift+tab")
        await pilot.pause()
    assert term.sent == []
    assert "Claude가 떠 있지 않아" in str(app.info_line.render())


def test_mode_order_matches_the_installed_claude_code():
    # 2.1.319 실행 파일의 순서와 같은지 확인한다
    order = ["default", "acceptEdits", "plan", "auto", "bypassPermissions", "dontAsk"]
    assert set(order) == set(MODE_LABEL)


# ---------- 훅이 알려 준 모드 ----------





@pytest.mark.asyncio
async def test_info_line_shows_the_mode_from_the_last_hook(tmp_path):
    rows = [row("UserPromptSubmit", {"permission_mode": "acceptEdits"}),
            row("Stop", {"permission_mode": "auto"})]
    app = make_app(tmp_path, rows, FakeTerminal())
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        assert "모드 자동(auto)" in str(app.info_line.render())


@pytest.mark.asyncio
async def test_mode_is_unknown_until_a_hook_reports_it(tmp_path):
    app = make_app(tmp_path, [row("Stop")], FakeTerminal())
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        assert "모드 알 수 없음" in str(app.info_line.render())
