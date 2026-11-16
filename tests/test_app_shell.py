"""Phase 0 완료 확인: 빈 세 구역이 뜨고 q로 끝난다 (SCREEN.md §1)."""

import pytest

from control_tui.app import ControlApp


@pytest.mark.asyncio
async def test_three_empty_zones_are_shown():
    app = ControlApp()
    async with app.run_test(size=(160, 40)) as pilot:
        sessions = app.query_one("#sessions")
        conversation = app.query_one("#conversation")
        input_line = app.query_one("#input")

        assert sessions.border_title == "① 세션 목록"
        assert conversation.border_title == "② 고른 세션의 대화"
        assert input_line.border_title == "③ 입력"

        # 넓은 화면: ① 왼쪽, ② 오른쪽, ③ 아래 전체 폭
        assert sessions.region.x < conversation.region.x
        assert input_line.region.width == app.size.width


@pytest.mark.asyncio
async def test_q_quits_the_app():
    app = ControlApp()
    async with app.run_test() as pilot:
        await pilot.press("q")
    assert app.return_code in (0, None)
