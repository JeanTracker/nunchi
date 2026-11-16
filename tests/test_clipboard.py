"""끌어서 복사, 붙여넣기 (요청 32, REQUIREMENTS R11, SCREEN §3, BUILD_PLAN §5.1.1).

실제 맥 클립보드는 쓰지 않는다. 가짜 클립보드로 확인한다.
"""

import json

import pytest
from textual import events

from control_tui import clipboard
from control_tui.app import ControlApp

# conftest가 테스트마다 MacClipboard.write/read를 가짜로 바꾸므로, 원래 함수는 불러올 때 잡아 둔다
_REAL_WRITE = clipboard.MacClipboard.write
_REAL_READ = clipboard.MacClipboard.read


class FakeClipboard:
    def __init__(self, content=None, writable=True):
        self.content = content
        self.writable = writable
        self.writes = []

    def write(self, text):
        self.writes.append(text)
        if self.writable:
            self.content = text
        return self.writable

    def read(self):
        return self.content


def make_app(tmp_path, clip, data=None, event="Stop"):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    row = {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": event,
           "cwd": "/work/demo", "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1",
           "data": data or {}}
    (d / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: {"PANEL-1"},
                      clipboard=clip)


async def drag(pilot, widget, start, end):
    await pilot.mouse_down(widget, offset=start)
    await pilot.hover(widget, offset=end)
    await pilot.mouse_up(widget, offset=end)
    await pilot.pause()


def info_text(app):
    return str(app.info_line.render())


@pytest.mark.asyncio
async def test_drag_in_conversation_copies_on_release(tmp_path):
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await drag(pilot, app.conversation, (0, 0), (20, 1))
        assert clip.writes, "놓는 순간 맥 클립보드에 써야 한다"
        assert clip.writes[-1] == app.screen.get_selected_text()
        assert clip.writes[-1].strip()
        assert "복사했습니다" in info_text(app)


@pytest.mark.asyncio
async def test_plain_click_does_not_copy(tmp_path):
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await pilot.click(app.conversation, offset=(3, 1))
        await pilot.pause()
        assert clip.writes == []


@pytest.mark.asyncio
async def test_failed_system_copy_is_reported(tmp_path):
    clip = FakeClipboard(writable=False)
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await drag(pilot, app.conversation, (0, 0), (20, 1))
        assert "복사하지 못했습니다" in info_text(app)
        assert app.clipboard  # 관제 안 클립보드에는 남는다 (Ctrl+V로 붙여 넣을 수 있게)


@pytest.mark.asyncio
async def test_drag_inside_input_copies_its_selection(tmp_path):
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()
        app.input_box.insert("입력줄 글 복사")
        await pilot.pause()
        await drag(pilot, app.input_box, (0, 0), (6, 0))
        assert clip.writes and clip.writes[-1] == app.input_box.selected_text
        assert clip.writes[-1]


@pytest.mark.asyncio
async def test_cmd_v_paste_while_conversation_focused_goes_to_input(tmp_path):
    """②에서 끈 뒤에는 포커스가 ②에 있다. 그때 Cmd+V(터미널의 붙여넣기)도 입력줄에 들어가야 한다."""
    app = make_app(tmp_path, FakeClipboard())
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.conversation.focus()
        await pilot.pause()
        app.post_message(events.Paste("붙여 넣은 글"))  # 앱이 포커스된 구역으로 넘긴다 (실제 경로와 같음)
        await pilot.pause()
        assert app.input_box.text == "붙여 넣은 글"
        assert app.focused is app.input_box


@pytest.mark.asyncio
async def test_cmd_v_paste_in_input_is_inserted_once(tmp_path):
    app = make_app(tmp_path, FakeClipboard())
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()
        await pilot.pause()
        app.post_message(events.Paste("한 번만"))
        await pilot.pause()
        assert app.input_box.text == "한 번만"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["ctrl+v", "ctrl+ㅍ"])
async def test_ctrl_v_in_input_reads_mac_clipboard(tmp_path, key):
    app = make_app(tmp_path, FakeClipboard(content="맥에서 복사한 글"))
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.input_box.focus()
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()
        assert app.input_box.text == "맥에서 복사한 글"


@pytest.mark.asyncio
async def test_ctrl_v_outside_input_pastes_into_input(tmp_path):
    app = make_app(tmp_path, FakeClipboard(content="밖에서 붙여넣기"))
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        app.session_list.focus()
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert app.input_box.text == "밖에서 붙여넣기"
        assert app.focused is app.input_box


@pytest.mark.asyncio
async def test_paste_is_refused_while_waiting_for_permission(tmp_path):
    app = make_app(tmp_path, FakeClipboard(), event="Notification",
                   data={"notification_type": "permission_prompt"})
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert app.input_box.disabled is True
        app.post_message(events.Paste("y"))
        await pilot.pause()
        assert app.input_box.text == ""
        assert "붙여 넣지 않았습니다" in info_text(app)


def test_mac_clipboard_keeps_korean(monkeypatch):
    """pbcopy·pbpaste에 UTF-8 로캘을 넘겨 한글이 깨지지 않게 한다."""
    calls = []

    class R:
        returncode = 0
        stdout = "한글"

    def fake_run(args, **kw):
        calls.append((args, kw))
        return R()

    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    mc = clipboard.MacClipboard()
    assert _REAL_WRITE(mc, "한글") is True
    assert _REAL_READ(mc) == "한글"
    assert calls[0][0] == ["pbcopy"] and calls[0][1]["input"] == "한글"
    assert all(kw["env"]["LC_CTYPE"] == "UTF-8" for _, kw in calls)


@pytest.mark.asyncio
async def test_stray_release_does_not_recopy_old_selection(tmp_path):
    """②에서 복사한 뒤 다른 앱에서 복사하고 돌아와, 입력줄을 살짝 끌며 눌러도 옛 글로 덮어쓰지 않는다."""
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await drag(pilot, app.conversation, (0, 0), (20, 1))
        assert len(clip.writes) == 1
        clip.content = "다른 앱에서 복사한 글"
        await drag(pilot, app.input_box, (1, 0), (3, 0))  # 빈 입력줄에서 두 칸 끌린 클릭
        await drag(pilot, app.session_list, (2, 0), (2, 0))  # ①에서 제자리 클릭
        assert len(clip.writes) == 1, clip.writes
        assert clip.content == "다른 앱에서 복사한 글"


@pytest.mark.asyncio
async def test_drag_in_input_after_conversation_copy_takes_input_text(tmp_path):
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await drag(pilot, app.conversation, (0, 0), (20, 1))
        app.input_box.focus()
        app.input_box.insert("입력줄 쪽 글")
        await pilot.pause()
        await drag(pilot, app.input_box, (0, 0), (6, 0))
        assert clip.writes[-1] == app.input_box.selected_text
        assert clip.content == app.input_box.selected_text != ""


@pytest.mark.asyncio
async def test_drag_on_unselectable_widget_does_not_recopy(tmp_path):
    """바닥 줄(맨 아래 키 안내)이나 스크롤바처럼 고를 수 없는 곳을 끌어도 옛 글을 다시 복사하지 않는다.
    요청 36에서 Textual Footer를 직접 그리는 KeyBar로 바꿨다."""
    from control_tui.app import KeyBar as Footer
    clip = FakeClipboard()
    app = make_app(tmp_path, clip)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        await drag(pilot, app.conversation, (0, 0), (20, 1))
        assert len(clip.writes) == 1
        footer = app.query_one(Footer)
        await drag(pilot, footer, (2, 0), (9, 0))
        assert len(clip.writes) == 1, clip.writes
