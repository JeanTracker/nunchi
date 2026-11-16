"""Phase 2 완료 확인: 기록을 읽어 목록과 대화를 만든다 (R1, R4, R10, R13)."""

import json
from pathlib import Path

import pytest

from control_tui import store, transcript
from control_tui.app import ControlApp


def ev(name, ts, **kw):
    base = {"ts": ts, "session_id": "s1", "event": name, "cwd": "/work/demo",
            "transcript_path": "", "iterm_session_id": "w0t0p0:AAA", "data": {}}
    base["data"].update(kw)
    return base


def write_events(home: Path, sid: str, rows: list):
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                    encoding="utf-8")


# ---------- 상태 계산 (BUILD_PLAN §3.1) ----------

def test_state_follows_last_meaningful_event():
    rows = [ev("SessionStart", "2026-11-09T00:00:01.000Z"),
            ev("UserPromptSubmit", "2026-11-09T00:00:02.000Z", prompt="hi"),
            ev("Stop", "2026-11-09T00:00:03.000Z")]
    v = store.summarize("s1", rows)
    assert v.state == "responded"
    assert v.responded_ts == "2026-11-09T00:00:03.000Z"


def test_idle_prompt_does_not_hide_unread_response():
    rows = [ev("Stop", "2026-11-09T00:00:03.000Z"),
            ev("Notification", "2026-11-09T00:00:09.000Z", notification_type="idle_prompt")]
    assert store.summarize("s1", rows).state == "responded"


def test_permission_prompt_sets_permission_state():
    rows = [ev("UserPromptSubmit", "2026-11-09T00:00:02.000Z"),
            ev("Notification", "2026-11-09T00:00:05.000Z", notification_type="permission_prompt")]
    assert store.summarize("s1", rows).state == "permission"


def test_current_tool_is_running_one_and_clears_when_done():
    running = [ev("PreToolUse", "2026-11-09T00:00:02.000Z", tool_name="Bash", tool_use_id="t1")]
    v = store.summarize("s1", running)
    assert v.current_tool == "Bash" and v.tools[0].status == "running"

    done = running + [ev("PostToolUse", "2026-11-09T00:00:03.000Z", tool_name="Bash", tool_use_id="t1")]
    v = store.summarize("s1", done)
    assert v.current_tool == "" and v.tools[0].status == "ok"


def test_failed_tool_is_marked_fail():
    rows = [ev("PreToolUse", "2026-11-09T00:00:02.000Z", tool_name="WebSearch", tool_use_id="t1"),
            ev("PostToolUseFailure", "2026-11-09T00:00:03.000Z", tool_name="WebSearch", tool_use_id="t1")]
    assert store.summarize("s1", rows).tools[0].status == "fail"


def test_order_puts_latest_response_first():
    a = store.summarize("a", [ev("Stop", "2026-11-09T00:00:05.000Z")])
    b = store.summarize("b", [ev("Stop", "2026-11-09T00:00:09.000Z")])
    c = store.summarize("c", [ev("UserPromptSubmit", "2026-11-09T00:00:10.000Z")])
    ordered = [v.session_id for v in store.sort_sessions([a, b, c])]
    assert ordered == ["b", "a", "c"]


def test_broken_lines_are_skipped(tmp_path):
    d = tmp_path / "sessions" / "s1"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(
        json.dumps(ev("Stop", "2026-11-09T00:00:01.000Z")) + "\n{깨진줄\n", encoding="utf-8")
    sessions = store.load_sessions(tmp_path)
    assert len(sessions) == 1 and sessions[0].state == "responded"


# ---------- 대화 턴 (BUILD_PLAN §3.2) ----------

def write_transcript(path: Path, rows: list):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_turns_group_request_tools_and_response(tmp_path):
    p = tmp_path / "t.jsonl"
    write_transcript(p, [
        {"type": "user", "timestamp": "2026-11-09T00:00:01.000Z", "message": {"content": "가격 조사해줘"}},
        {"type": "assistant", "timestamp": "2026-11-09T00:00:02.000Z", "message": {"content": [
            {"type": "text", "text": "웹에서 찾아볼게요."},
            {"type": "tool_use", "id": "u1", "name": "WebSearch", "input": {}}]}},
        {"type": "user", "timestamp": "2026-11-09T00:00:03.000Z", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u1", "content": "결과", "is_error": False}]}},
        {"type": "assistant", "timestamp": "2026-11-09T00:00:04.000Z", "message": {"content": [
            {"type": "text", "text": "가격표를 만들었습니다."}]}},
        {"type": "user", "timestamp": "2026-11-09T00:01:00.000Z", "message": {"content": "할인도 넣어줘"}},
    ])
    turns = transcript.parse_turns(p)
    assert [t.request for t in turns] == ["가격 조사해줘", "할인도 넣어줘"]
    assert turns[0].tools == [("WebSearch", True)]
    assert turns[0].response == "웹에서 찾아볼게요.\n\n가격표를 만들었습니다."


def test_failed_tool_result_is_marked(tmp_path):
    p = tmp_path / "t.jsonl"
    write_transcript(p, [
        {"type": "user", "timestamp": "t", "message": {"content": "해줘"}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [
            {"type": "tool_use", "id": "u1", "name": "Bash", "input": {}}]}},
        {"type": "user", "timestamp": "t", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "u1", "content": "err", "is_error": True}]}},
    ])
    assert transcript.parse_turns(p)[0].tools == [("Bash", False)]


def test_sidechain_lines_are_ignored(tmp_path):
    p = tmp_path / "t.jsonl"
    write_transcript(p, [
        {"type": "user", "timestamp": "t", "message": {"content": "질문"}},
        {"type": "assistant", "isSidechain": True, "timestamp": "t",
         "message": {"content": [{"type": "text", "text": "하위 에이전트 내부"}]}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [{"type": "text", "text": "답"}]}},
    ])
    t = transcript.parse_turns(p)[0]
    assert t.response == "답"
    assert "하위 에이전트 내부" not in t.response


# ---------- 화면 (SCREEN.md §1, §2 ①②) ----------

@pytest.mark.asyncio
async def test_screen_shows_session_and_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTROL_TUI_HOME", str(tmp_path / "home"))
    tr = tmp_path / "t.jsonl"
    write_transcript(tr, [
        {"type": "user", "timestamp": "2026-11-09T00:00:01.000Z", "message": {"content": "표 만들어줘"}},
        {"type": "assistant", "timestamp": "t", "message": {"content": [{"type": "text", "text": "완료했습니다."}]}},
    ])
    write_events(tmp_path / "home", "s1", [
        ev("UserPromptSubmit", "2026-11-09T00:00:01.000Z", prompt="표 만들어줘"),
        {**ev("Stop", "2026-11-09T00:00:05.000Z"), "transcript_path": str(tr)},
    ])
    app = ControlApp(home=tmp_path / "home")
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        text = str(app.session_list.render_text())
        assert "demo" in text and "응답" in text and "새 응답" in text
        conv = str(app.conversation.render_text())
        assert "표 만들어줘" in conv and "완료했습니다." in conv
        assert "판정 전" in conv


@pytest.mark.asyncio
async def test_screen_handles_no_sessions(tmp_path):
    app = ControlApp(home=tmp_path / "empty")
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert "아직 기록된 세션이 없습니다" in str(app.session_list.render_text())


@pytest.mark.asyncio
async def test_screen_updates_within_one_second(tmp_path):
    home = tmp_path / "home"
    app = ControlApp(home=home)
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        assert app.session_list.views == []
        write_events(home, "s9", [ev("Stop", "2026-11-09T00:00:05.000Z")])
        await pilot.pause(1.2)
        assert [v.session_id for v in app.session_list.views] == ["s9"]


# ---------- 거절 뒤 상태 복구 (2026-11-09 실험: 거절하면 훅이 더 오지 않는다) ----------

def _write_rows(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _session(tmp_path, transcript_rows, last_event="Notification"):
    tr = tmp_path / "t.jsonl"
    _write_rows(tr, transcript_rows)
    d = tmp_path / "home" / "sessions" / "s1"
    d.mkdir(parents=True)
    evs = [{"ts": "2026-11-09T13:32:40.000Z", "session_id": "s1", "event": "UserPromptSubmit", "cwd": "/w",
            "transcript_path": str(tr), "iterm_session_id": "", "data": {}},
           {"ts": "2026-11-09T13:32:41.000Z", "session_id": "s1", "event": "PreToolUse", "cwd": "/w",
            "transcript_path": str(tr), "iterm_session_id": "", "data": {"tool_name": "Bash", "tool_use_id": "u1"}}]
    if last_event == "Notification":
        evs.append({"ts": "2026-11-09T13:32:47.000Z", "session_id": "s1", "event": "Notification", "cwd": "/w",
                    "transcript_path": str(tr), "iterm_session_id": "",
                    "data": {"notification_type": "permission_prompt"}})
    _write_rows(d / "events.jsonl", evs)
    return tmp_path / "home"


DENIED_ROWS = [
    {"type": "user", "timestamp": "2026-11-09T13:32:40.000Z", "message": {"content": "touch 해줘"}},
    {"type": "assistant", "timestamp": "2026-11-09T13:32:41.000Z",
     "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash", "input": {}}]}},
    {"type": "user", "timestamp": "2026-11-09T13:32:50.000Z", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "u1", "is_error": True,
         "content": "The user doesn't want to proceed with this tool use. The tool use was rejected"}]}},
    {"type": "user", "timestamp": "2026-11-09T13:32:50.000Z",
     "message": {"content": [{"type": "text", "text": "[Request interrupted by user for tool use]"}]}},
]


@pytest.mark.parametrize("last_event, before", [("Notification", "permission"), ("PreToolUse", "working")])
def test_refusal_in_transcript_releases_stuck_state(tmp_path, last_event, before):
    home = _session(tmp_path, DENIED_ROWS, last_event)
    v = store.load_sessions(home)[0]
    assert v.state == "idle" and v.current_tool == ""


def test_old_refusal_does_not_release_a_new_permission_prompt(tmp_path):
    rows = [dict(r, timestamp="2026-11-09T13:00:00.000Z") for r in DENIED_ROWS]
    home = _session(tmp_path, rows)
    assert store.load_sessions(home)[0].state == "permission"


def test_refused_tool_does_not_stay_running_after_the_next_prompt():
    """2026-11-10 실제 화면: 거절한 도구는 끝 훅이 없어 다음 요청 중에도 ①에 'Bash'로 남았다."""
    rows = [ev("PreToolUse", "2026-11-09T00:00:02.000Z", tool_name="Bash", tool_use_id="t1"),
            ev("UserPromptSubmit", "2026-11-09T00:01:00.000Z")]
    v = store.summarize("s1", rows)
    assert v.state == "working" and v.current_tool == ""
