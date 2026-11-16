"""③ 입력줄의 / 목록: 내장 명령, 스킬, 명령 파일 (control_tui/completion.py)."""

import json

import pytest

from control_tui import completion
from control_tui.app import ControlApp


class FakeTerminal:
    def __init__(self):
        self.sent = []

    def send_text(self, target_id, text, enter=True):
        self.sent.append(text)


def write_skill(root, folder, name, description):
    d = root / ".claude" / "skills" / folder
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n본문\n", encoding="utf-8")


def make_app(tmp_path, cwd):
    home = tmp_path / "home"
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    row = {"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1", "event": "Stop",
           "cwd": str(cwd), "transcript_path": "", "iterm_session_id": "w0t0p0:PANEL-1", "data": {}}
    (d / "events.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return ControlApp(home=home, panel_scanner=lambda ids: [], terminal=FakeTerminal(),
                      panel_checker=lambda: {"PANEL-1"}, skill_home=tmp_path / "userhome")


async def ready(app, pilot):
    await pilot.pause()
    app.input_box.focus()
    await pilot.pause()


# ---------- 순수 규칙 ----------

def test_slash_prefix_only_before_the_first_space():
    assert completion.slash_prefix("/comp") == "comp"
    assert completion.slash_prefix("/") == ""
    assert completion.slash_prefix("/compact 인자") is None
    assert completion.slash_prefix("그냥 글") is None


def test_gather_prefers_project_then_user_then_builtin(tmp_path):
    project = tmp_path / "proj"
    user = tmp_path / "userhome"
    write_skill(project, "compact", "compact", "프로젝트 판")
    write_skill(user, "review-helper", "review-helper", "사용자 스킬")
    items = completion.gather(user, project)
    names = [n for n, _, _ in items]
    assert names.count("compact") == 1
    assert ("compact", "프로젝트 판", "프로젝트 스킬") in items
    assert ("review-helper", "사용자 스킬", "사용자 스킬") in items
    assert ("help", "도움말과 명령 목록", "내장") in items


def test_builtin_list_has_only_names_checked_in_the_binary():
    names = {n for n, _ in completion.BUILTIN}
    for must in ("clear", "compact", "config", "help", "init", "memory", "model", "resume", "rewind", "skills"):
        assert must in names
    assert "stats" not in names  # 설치된 실행 파일에서 확인하지 못한 이름


# ---------- 화면 ----------

@pytest.mark.asyncio
async def test_slash_opens_the_list_and_filters_by_prefix(tmp_path):
    app = make_app(tmp_path, tmp_path / "work")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("/co")
        await pilot.pause()
        names = [n for n, _, _ in app.input_box.menu_items]
        assert {"compact", "config", "context", "copy"} <= set(names)
        assert "help" not in names


@pytest.mark.asyncio
async def test_tab_completes_the_selected_command_with_a_space(tmp_path):
    app = make_app(tmp_path, tmp_path / "work")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("/comp")
        await pilot.pause()
        assert [n for n, _, _ in app.input_box.menu_items] == ["compact"]
        await pilot.press("tab")
        await pilot.pause()
        assert app.input_box.text == "/compact "
        assert app.input_box.menu_items == []


@pytest.mark.asyncio
async def test_up_and_down_move_in_the_list_not_in_history(tmp_path):
    app = make_app(tmp_path, tmp_path / "work")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.remember("지난 글")
        app.input_box.insert("/co")
        await pilot.pause()
        first = app.input_box.menu_index
        await pilot.press("down")
        await pilot.pause()
        assert app.input_box.menu_index == (first + 1) % len(app.input_box.menu_items)
        assert app.input_box.text == "/co"  # 기록의 글로 바뀌지 않는다


@pytest.mark.asyncio
async def test_enter_sends_what_was_typed_not_the_selection(tmp_path):
    term = FakeTerminal()
    app = make_app(tmp_path, tmp_path / "work")
    app.terminal = term
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("/comp")
        await pilot.press("enter")
        await pilot.pause()
    assert term.sent == ["/comp"]


@pytest.mark.asyncio
async def test_escape_closes_the_list_and_keeps_the_text(tmp_path):
    app = make_app(tmp_path, tmp_path / "work")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("/co")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.input_box.menu_items == []
        assert app.input_box.text == "/co"


@pytest.mark.asyncio
async def test_user_and_project_skills_show_up_in_the_list(tmp_path):
    project = tmp_path / "work"
    write_skill(project, "proj-only", "proj-only", "이 폴더 전용")
    write_skill(tmp_path / "userhome", "review-helper", "review-helper", "사용자 스킬 설명")
    app = make_app(tmp_path, project)
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("/re")
        await pilot.pause()
        found = {n: src for n, _, src in app.input_box.menu_items}
        assert found.get("review-helper") == "사용자 스킬"
        assert found.get("resume") == "내장"
        app.input_box.clear()
        app.input_box.insert("/proj")
        await pilot.pause()
        assert {n: src for n, _, src in app.input_box.menu_items}.get("proj-only") == "프로젝트 스킬"


@pytest.mark.asyncio
async def test_no_list_for_normal_text(tmp_path):
    app = make_app(tmp_path, tmp_path / "work")
    async with app.run_test(size=(140, 40)) as pilot:
        await ready(app, pilot)
        app.input_box.insert("그냥 글")
        await pilot.pause()
        assert app.input_box.menu_items == []
