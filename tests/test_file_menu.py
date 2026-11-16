"""③ 입력줄의 @ 파일 목록 (control_tui/completion.py)."""

import json

import pytest

from control_tui import completion
from control_tui.app import ControlApp


class FakeTerminal:
    def __init__(self):
        self.sent = []

    def send_text(self, target_id, text, enter=True):
        self.sent.append(text)


def make_project(tmp_path):
    project = tmp_path / "work"
    (project / "src").mkdir(parents=True)
    (project / "src" / "app.py").write_text("x", encoding="utf-8")
    (project / "src" / "parser.py").write_text("x", encoding="utf-8")
    (project / "README.md").write_text("x", encoding="utf-8")
    (project / "node_modules" / "pkg").mkdir(parents=True)
    (project / "node_modules" / "pkg" / "index.js").write_text("x", encoding="utf-8")
    (project / ".hidden").mkdir()
    (project / ".hidden" / "secret.txt").write_text("x", encoding="utf-8")
    return project


def make_app(tmp_path, project):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    row = {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": "Stop",
           "cwd": str(project), "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1", "data": {}}
    (d / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], terminal=FakeTerminal(),
                      panel_checker=lambda: {"PANEL-1"}, skill_home=tmp_path / "userhome")


async def ready(app, pilot):
    await pilot.pause()
    app.input_box.focus()
    await pilot.pause()


# ---------- 순수 규칙 ----------

def test_file_token_is_the_last_word_starting_with_at():
    assert completion.file_token("고쳐줘 @src/ap") == "@src/ap"
    assert completion.file_token("@") == "@"
    assert completion.file_token("@src/app.py ") is None      # 공백 뒤면 목록을 닫는다
    assert completion.file_token("그냥 글") is None


def test_list_files_skips_hidden_and_dependency_folders(tmp_path):
    project = make_project(tmp_path)
    files = completion.list_files(project)
    assert "src/app.py" in files and "README.md" in files
    assert not any(f.startswith("node_modules") for f in files)
    assert not any(f.startswith(".hidden") for f in files)


def test_match_puts_prefix_matches_first():
    files = ["src/app.py", "docs/app-notes.md", "src/parser.py"]
    assert completion.match_files(files, "app")[0] == "src/app.py"
    assert "src/parser.py" in completion.match_files(files, "pars")


# ---------- 화면 ----------

@pytest.mark.asyncio
async def test_at_opens_the_file_list_and_filters(tmp_path):
    project = make_project(tmp_path)
    app = make_app(tmp_path, project)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("고쳐줘 @pars")
        await pilot.pause()
        assert app.input_box.menu_mode == "file"
        assert [n for n, _, _ in app.input_box.menu_items] == ["src/parser.py"]


@pytest.mark.asyncio
async def test_tab_completes_the_file_path_and_keeps_the_rest(tmp_path):
    project = make_project(tmp_path)
    app = make_app(tmp_path, project)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("고쳐줘 @pars")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert app.input_box.text == "고쳐줘 @src/parser.py "
        assert app.input_box.menu_items == []


@pytest.mark.asyncio
async def test_enter_sends_the_typed_text_not_the_selected_file(tmp_path):
    project = make_project(tmp_path)
    term = FakeTerminal()
    app = make_app(tmp_path, project)
    app.terminal = term
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("@pars")
        await pilot.press("enter")
        await pilot.pause()
    assert term.sent == ["@pars"]


@pytest.mark.asyncio
async def test_no_file_list_without_at(tmp_path):
    project = make_project(tmp_path)
    app = make_app(tmp_path, project)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("그냥 글 pars")
        await pilot.pause()
        assert app.input_box.menu_mode != "file" or app.input_box.menu_items == []
