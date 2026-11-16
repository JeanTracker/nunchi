"""③ 입력줄: 한글 삭제, 파일 끌어다 놓기(붙여넣기), Tab으로 추천 문구 채우기."""

import json

import pytest
from textual import events

from control_tui.app import ControlApp
from control_tui.widgets.input_line import SUGGESTIONS, suggestion_for


class FakeTerminal:
    def __init__(self):
        self.sent = []

    def send_text(self, target_id, text, enter=True):
        self.sent.append(text)


def make_app(tmp_path, event_name="Stop"):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    row = {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": event_name,
           "cwd": "/work/demo", "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1",
           "data": {}}
    (d / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], terminal=FakeTerminal(),
                      panel_checker=lambda: {"PANEL-1"})


async def ready(app, pilot):
    await pilot.pause()
    app.input_box.focus()
    await pilot.pause()


# ---------- 한글 삭제 ----------

@pytest.mark.asyncio
async def test_backspace_removes_one_korean_syllable(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("한글")
        await pilot.press("backspace")
        await pilot.pause()
        assert app.input_box.text == "한"


@pytest.mark.asyncio
async def test_backspace_in_the_middle_of_korean_text(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("가나다")
        await pilot.press("left")
        await pilot.press("backspace")
        await pilot.pause()
        assert app.input_box.text == "가다"


@pytest.mark.asyncio
async def test_delete_key_removes_the_character_after_cursor(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("입력창")
        await pilot.press("home")
        await pilot.press("delete")
        await pilot.pause()
        assert app.input_box.text == "력창"


# ---------- 파일 끌어다 놓기 (붙여넣기) ----------

@pytest.mark.asyncio
async def test_dropped_file_path_is_inserted_as_text(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.post_message(events.Paste("/Users/me/Desktop/보고서 최종.pdf"))
        await pilot.pause()
        assert app.input_box.text == "/Users/me/Desktop/보고서 최종.pdf"


@pytest.mark.asyncio
async def test_several_dropped_files_keep_their_order(tmp_path):
    app = make_app(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.post_message(events.Paste("/a/first.png /b/second.png"))
        await pilot.pause()
        assert app.input_box.text == "/a/first.png /b/second.png"


# ---------- Tab 추천 문구 ----------

def test_no_suggestion_until_the_analyzer_stage():
    # 추천 문구는 4단계(분석기) 이후에 만든다 (BUILD_PLAN §7)
    assert SUGGESTIONS == {}
    for state in ("responded", "idle", "working", "permission"):
        assert suggestion_for(state) == ""


@pytest.mark.asyncio
async def test_tab_fills_a_suggestion_when_input_is_empty(tmp_path):
    # 채우기 동작 자체만 확인한다. 추천 문구의 내용은 4단계에서 정한다
    app = make_app(tmp_path, "Stop")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.set_suggestion("테스트용 추천")
        assert app.input_box.placeholder == "Tab: 테스트용 추천"
        await pilot.press("tab")
        await pilot.pause()
        assert app.input_box.text == "테스트용 추천"
        assert app.focused is app.input_box  # 추천을 채운 뒤에도 입력칸에 머문다


@pytest.mark.asyncio
async def test_tab_moves_focus_when_there_is_no_suggestion(tmp_path):
    app = make_app(tmp_path, "SessionStart")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is not app.input_box


@pytest.mark.asyncio
async def test_tab_moves_focus_when_the_input_already_has_text(tmp_path):
    app = make_app(tmp_path, "Stop")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("이미 쓴 글")
        await pilot.press("tab")
        await pilot.pause()
        assert app.input_box.text == "이미 쓴 글"
        assert app.focused is not app.input_box
