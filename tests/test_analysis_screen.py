"""4단계 화면: ②에 목표·조건·관계 라벨, ①에 누락 수 (REQUIREMENTS R2, R8, R9)."""

import json
import threading

import pytest

from control_tui.app import ControlApp
from tests.fake_analyzer import FROZEN, FakeAnalyzer, make_transcript


def write_session(home, sid, rows):
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                    encoding="utf-8")


def stop_row(sid, tr, ts="2026-11-09T01:05:00.000Z"):
    return {"ts": ts, "session_id": sid, "event": "Stop", "cwd": "/work/viz",
            "transcript_path": str(tr), "iterm_session_id": "w0t0p0:PANEL-1", "data": {}}


async def settle(app, pilot):
    app.analyzer.wait_idle(timeout=10)
    await pilot.pause()
    app.refresh_sessions()
    await pilot.pause()


@pytest.mark.asyncio
async def test_goals_labels_and_missed_count_appear_after_analysis(tmp_path):
    tr = make_transcript(tmp_path)
    home = tmp_path / "home"
    write_session(home, "s1", [stop_row("s1", tr)])
    release = threading.Event()  # 분석이 끝나는 시점을 테스트가 정한다 (시간에 기대지 않는다)

    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(),
                     analyzer=FakeAnalyzer(result=FROZEN["GOOD"], gate=release))
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert "판정 전" in str(app.conversation.render_text())  # 요청 30: 판정 전은 미판정으로
        release.set()
        await settle(app, pilot)
        head = str(app.conversation.render_text())
        # 요청 33: 목표 흐름은 세로 단계, '다음 할 일'은 없고, 요청 체크는 빠짐만 펼친다
        # 요청이 하나뿐인 세션: 처음과 지금이 같은 턴이라 한 줄 (요청 37). 두 줄 흐름은 test_request_check에서 본다
        assert " ◉ #1   처음·지금 할인 조건 추가" in head and " ● " not in head
        assert "다음  " not in head
        assert "✘ 빠짐 1" in head and "· 추정" in head
        assert "  ✘ 출처 표시" in head
        assert "[시작]" in head and "⚠" not in head  # 턴별 빠짐 표시는 두지 않는다
        assert "⚠1" in str(app.session_list.render_text())


@pytest.mark.asyncio
async def test_analysis_failure_is_shown_in_the_conversation(tmp_path):
    tr = make_transcript(tmp_path)
    home = tmp_path / "home"
    write_session(home, "s1", [stop_row("s1", tr)])

    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(),
                     analyzer=FakeAnalyzer(error="claude 종료 코드 1"))
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await settle(app, pilot)
        assert "claude 종료 코드 1" in str(app.conversation.render_text())
        assert "⚠" not in str(app.session_list.render_text())


@pytest.mark.asyncio
async def test_no_analysis_request_for_a_session_that_has_not_responded(tmp_path):
    tr = make_transcript(tmp_path)
    home = tmp_path / "home"
    write_session(home, "s1", [{"ts": "2026-11-09T01:00:00.000Z", "session_id": "s1",
                                "event": "UserPromptSubmit", "cwd": "/work/viz",
                                "transcript_path": str(tr), "iterm_session_id": "", "data": {}}])
    calls = []
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(),
                     analyzer=FakeAnalyzer(result=FROZEN["GOOD"], calls=calls))
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.analyzer.wait_idle(timeout=5)
    assert calls == []


@pytest.mark.asyncio
async def test_shows_that_the_analyzer_is_off(tmp_path):
    tr = make_transcript(tmp_path)
    home = tmp_path / "home"
    write_session(home, "s1", [stop_row("s1", tr)])
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(), analyzer=None)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert "분석기 꺼짐" in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_analysis_is_not_run_again_for_the_same_answer(tmp_path):
    tr = make_transcript(tmp_path)
    home = tmp_path / "home"
    write_session(home, "s1", [stop_row("s1", tr)])
    calls = []
    app = ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: set(),
                     analyzer=FakeAnalyzer(result=FROZEN["GOOD"], calls=calls))
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        await settle(app, pilot)
        app.refresh_sessions()
        app.refresh_sessions()
        await pilot.pause()
    assert len(calls) == 1
