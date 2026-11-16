"""요청 36: 디자인 시스템(색 역할, 지금 구역 테두리, 구역별 맨 아래 키 안내)과 테마 7개 (SCREEN §10)."""

import json
import re
from pathlib import Path

import pytest

from control_tui import settings as settings_mod, theme
from control_tui.theme import C
from tests.test_flow_view import ANALYSIS, app_for, make_session, ready

WIDGETS = ["control_tui/app.py", "control_tui/widgets/conversation.py",
           "control_tui/widgets/session_list.py", "control_tui/widgets/input_line.py"]


def keybar(app) -> str:
    return str(app.keybar.render())


@pytest.fixture(autouse=True)
def back_to_default():
    yield
    C.use(theme.DEFAULT)


def test_seven_themes_fill_every_role_and_the_dropped_three_are_absent():
    assert list(theme.THEMES) == ["graphite", "midnight", "polar", "forest", "dusk", "contrast", "paper"]
    for name, values in theme.THEMES.items():
        for role in theme.ROLES:
            assert re.fullmatch(r"#[0-9a-f]{6}", values[role]), (name, role)
    for dropped in ("amber", "phosphor", "sand"):
        assert dropped not in theme.THEMES


def test_widgets_use_roles_not_color_names():
    """색 이름이 코드에 남으면 테마를 바꿔도 그 글자만 색이 안 바뀐다."""
    pattern = re.compile(r'"[^"\n]*\b(red|yellow|green|cyan|magenta|grey\d+)\b[^"\n]*"')
    for f in WIDGETS:
        for n, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            assert not pattern.search(line), f"{f}:{n}: {line.strip()}"


def test_palette_switches_and_unknown_names_fall_back():
    assert C.use("paper") == "paper" and C.bg == "#fbfaf7"
    assert C.get("err") == theme.THEMES["paper"]["err"]
    assert C.get("#123456") == "#123456"
    assert C.use("amber") == "graphite"


def test_settings_theme_is_normalized(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"theme": "dusk"}), encoding="utf-8")
    assert settings_mod.load(tmp_path).theme == "dusk"
    (tmp_path / "config.json").write_text(json.dumps({"theme": "sand"}), encoding="utf-8")
    assert settings_mod.load(tmp_path).theme == "graphite"


@pytest.mark.asyncio
async def test_config_theme_is_applied_at_start(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, analysis=ANALYSIS)
    (home / "config.json").write_text(json.dumps({"theme": "midnight"}), encoding="utf-8")
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert app.theme == "nunchi-midnight" and C.name == "midnight"


@pytest.mark.asyncio
async def test_changing_textual_theme_changes_rich_colors_too(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, analysis=ANALYSIS)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.theme = "nunchi-paper"     # 명령 팔레트의 테마 바꾸기와 같은 길
        await pilot.pause()
        assert C.name == "paper"
        app.theme = "textual-dark"     # Textual 기본 테마로 바꿔도 깨지지 않고 글자 색은 그대로
        await pilot.pause()
        assert C.name == "paper"


@pytest.mark.asyncio
async def test_focused_zone_gets_its_pane_color_heavy_border(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, analysis=ANALYSIS)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        zones = {1: app.query_one("#sessions"), 2: app.query_one("#conversation"), 3: app.query_one("#input")}
        for n, focus in ((1, app.session_list), (2, app.conversation), (3, app.input_box)):
            focus.focus()
            await pilot.pause()
            for k, zone in zones.items():
                kind, color = zone.styles.border_top
                if k == n:
                    assert kind == "heavy" and color.hex.lower() == theme.THEMES["graphite"][f"p{n}"], (n, k)
                else:
                    assert kind == "round" and color.hex.lower() == theme.THEMES["graphite"]["idle"], (n, k)


@pytest.mark.asyncio
async def test_keybar_follows_the_focused_zone(tmp_path):
    home, _, _ = make_session(tmp_path, n=3, analysis=ANALYSIS)
    app = app_for(home)
    async with app.run_test(size=(200, 46)) as pilot:
        await ready(app, pilot)
        text = keybar(app)
        assert text.startswith(" ① 세션 목록 ") and "↑↓ 세션 고르기" in text and text.rstrip().endswith("q 종료")
        await pilot.press("tab")
        text = keybar(app)
        assert text.startswith(" ② 대화 ") and "c 요청 전체" in text and "d 상세" in text
        await pilot.press("c")
        assert keybar(app).startswith(" ② 요청 전체 ") and "c·Esc 닫기" in keybar(app)
        await pilot.press("escape", "d")
        assert keybar(app).startswith(" ② 응답 상세 ") and "Esc 목록으로" in keybar(app) and "←→" not in keybar(app)  # 마지막 대화만 (요구 이력 41)
        await pilot.press("escape", "tab")
        text = keybar(app)
        assert text.startswith(" ③ 입력 ") and "Enter 보내기" in text and "^q 종료" in text
        assert " q 종료" not in text      # 입력줄에서 q는 글자


@pytest.mark.asyncio
async def test_permission_wait_puts_y_n_first(tmp_path):
    stop = "2026-11-09T00:02:40.000Z"
    events = [{"ts": "2026-11-09T00:02:50.000Z", "session_id": "s1", "event": "Notification", "cwd": "/work/demo",
               "transcript_path": str(tmp_path / "s1.jsonl"), "iterm_session_id": "w0t0p0:PANEL-1",
               "data": {"notification_type": "permission_prompt"}}]
    home, _, _ = make_session(tmp_path, n=2, analysis=ANALYSIS, events=events)
    app = app_for(home)
    async with app.run_test(size=(200, 46)) as pilot:
        await ready(app, pilot)
        assert app.session_list.selected().state == "permission"
        assert keybar(app).startswith(" ① 세션 목록   y 허용  n 거절")
