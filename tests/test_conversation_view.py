"""원문 펼쳐 보기, 턴 고르기, 정보 줄 (SCREEN.md §2 ②, §6)."""

import json
from pathlib import Path

import pytest

from control_tui import transcript
from control_tui.app import ControlApp


def write_transcript(path: Path, rows: list):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


LONG_REQUEST = "요청 " + "가나다라마바사 " * 12 + "끝"


def make_transcript(tmp_path: Path) -> Path:
    p = tmp_path / "t.jsonl"
    write_transcript(p, [
        {"type": "user", "timestamp": "2026-11-09T00:00:01.000Z", "message": {"content": LONG_REQUEST}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [
            {"type": "text", "text": "첫 줄 답변\n둘째 줄 상세 답변"},
            {"type": "tool_use", "id": "r1", "name": "WebSearch", "input": {"query": "x"}}]}},
        {"type": "user", "timestamp": "t", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": "검색 결과 열 글자입니다", "is_error": False}]}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [
            {"type": "tool_use", "id": "w1", "name": "Write", "input": {"content": "작성한 파일 내용"}}]}},
        {"type": "user", "timestamp": "t", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "w1", "content": "ok", "is_error": False}]}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [{"type": "text", "text": "끝났습니다."}]}},
        {"type": "user", "timestamp": "2026-11-09T00:02:00.000Z", "message": {"content": "두 번째 질문"}},
    ])
    return p


# ---------- 원문 보존과 정보 줄 ----------

def test_request_and_response_are_kept_in_full(tmp_path):
    turns = transcript.parse_turns(make_transcript(tmp_path))
    assert turns[0].request == LONG_REQUEST.strip()
    assert turns[0].response == "첫 줄 답변\n둘째 줄 상세 답변\n\n끝났습니다."


def test_totals_count_user_research_and_work_chars(tmp_path):
    turns = transcript.parse_turns(make_transcript(tmp_path))
    t = transcript.totals(turns)
    assert t["user"] == len(LONG_REQUEST.strip()) + len("두 번째 질문")
    assert t["research"] == len("검색 결과 열 글자입니다")
    assert t["work"] >= len("작성한 파일 내용")


# ---------- 화면 동작 ----------

@pytest.mark.asyncio
async def test_o_toggles_full_original(tmp_path):
    """o는 요청·응답 원문 전체를 펼치고 접는다 (SCREEN §3). Enter는 단계 카드로 바뀌었다 (요청 24)."""
    home = tmp_path / "home"
    tr = make_transcript(tmp_path)
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(json.dumps({
        "ts": "2026-11-09T00:02:00.000Z", "session_id": "s1", "event": "Stop", "cwd": "/work/demo",
        "transcript_path": str(tr), "iterm_session_id": "", "data": {}}) + "\n", encoding="utf-8")

    app = ControlApp(home=home)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.conversation.focus()
        app.conversation.selected = 0
        app.refresh_sessions()
        await pilot.pause()

        assert "── 원문" not in str(app.conversation.render_text())
        await pilot.press("o")
        assert 0 in app.conversation.raw
        expanded = str(app.conversation.render_text())
        assert "── 원문" in expanded
        assert LONG_REQUEST.strip()[-5:] in expanded  # 긴 요청도 끝까지 나온다
        assert "둘째 줄 상세 답변" in expanded

        await pilot.press("o")
        assert 0 not in app.conversation.raw
        assert "── 원문" not in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_arrow_keys_move_between_turns(tmp_path):
    home = tmp_path / "home"
    tr = make_transcript(tmp_path)
    d = home / "sessions" / "s1"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(json.dumps({
        "ts": "2026-11-09T00:02:00.000Z", "session_id": "s1", "event": "Stop", "cwd": "/work/demo",
        "transcript_path": str(tr), "iterm_session_id": "", "data": {}}) + "\n", encoding="utf-8")

    app = ControlApp(home=home)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.conversation.focus()
        app.refresh_sessions()
        await pilot.pause()
        assert app.conversation.selected == 1  # 처음에는 마지막 턴
        await pilot.press("up")
        assert app.conversation.selected == 0
        await pilot.press("up")
        assert app.conversation.selected == 0  # 맨 위에서 멈춘다
