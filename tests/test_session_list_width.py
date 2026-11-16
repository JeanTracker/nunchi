"""① 세션 목록: 줄이 칸을 넘어 줄바꿈되지 않는다 (SCREEN.md §2 ①)."""

import json

import pytest
from rich.cells import cell_len

from control_tui.app import ControlApp
from control_tui.widgets.session_list import NEW_MARK, fit


def event(sid, name, ts, data=None):
    return {"ts": ts, "session_id": sid, "event": name,
            "cwd": "/Users/demo/work/a-very-long-project-folder-name-for-testing",
            "transcript_path": "", "iterm_session_id": f"w0t0p0:PANEL-{sid}", "data": data or {}}


def write(home, sid, rows):
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                    encoding="utf-8")


def test_fit_pads_and_truncates_by_cells():
    assert cell_len(fit("abc", 6)) == 6
    assert cell_len(fit("가나다라마바사", 6)) == 6          # 한글은 두 칸
    assert "…" in fit("가나다라마바사", 6)


@pytest.mark.asyncio
async def test_new_response_mark_stays_on_one_line_at_narrow_width(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for sid in ("aaaa1111", "bbbb2222", "cccc3333"):
        write(home, sid, [event(sid, "Stop", "2026-11-09T01:00:00.000Z")])
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        width = app.session_list.size.width
        lines = str(app.session_list.render_text()).split("\n")
        session_lines = [ln for ln in lines if ln.strip()]
        assert len(session_lines) == 3                      # 세션 하나가 한 줄
        for ln in session_lines:
            assert cell_len(ln) <= width, ln                # 칸 너비를 넘지 않아 한 줄로 남는다
            assert NEW_MARK.strip() in ln                   # 확인 안 한 응답 표시가 같은 줄에 남는다


@pytest.mark.asyncio
async def test_pending_label_is_not_cut(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        from control_tui import panels
        app.session_list.set_views([panels.to_pending_view(
            panels.Panel("PANEL-XYZ", "/dev/ttys009", ""), panels.ClaudeProc(1, "/dev/ttys009"), "/w/demo")])
        await pilot.pause()
        assert "연결 대기" in str(app.session_list.render_text())


@pytest.mark.asyncio
async def test_missed_mark_does_not_wrap_the_row(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for sid in ("aaaa1111", "bbbb2222"):
        write(home, sid, [event(sid, "Stop", "2026-11-09T01:00:00.000Z")])
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        app.session_list.views[0].missed = 12
        app.session_list.refresh_content()
        width = app.session_list.size.width
        lines = [ln for ln in str(app.session_list.render_text()).split("\n") if ln.strip()]
        assert len(lines) == 2
        assert "⚠12" in lines[0]
        assert all(cell_len(ln) <= width for ln in lines)
