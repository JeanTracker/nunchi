"""응답까지 한 일 (요청 24, SCREEN §2 ② 턴 목록·펼친 턴·응답 상세, BUILD_PLAN §3.2)."""

import json
from pathlib import Path

import pytest

from control_tui import transcript
from control_tui.app import ControlApp


def write(path: Path, rows: list) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def user(text, ts="2026-11-09T00:00:00.000Z", **extra):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}, **extra}


def say(text):
    return {"type": "assistant", "timestamp": "t", "message": {"content": [{"type": "text", "text": text}]}}


def tool(tid, name, inp):
    return {"type": "assistant", "timestamp": "t",
            "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def result(tid, ok=True):
    return {"type": "user", "timestamp": "t", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": "결과", "is_error": not ok}]}}


def pricing_rows():
    return [
        user("경쟁사 3곳 요금제 표로 정리해줘"),
        say("요금 페이지부터 찾겠습니다."),
        tool("t1", "WebSearch", {"query": "경쟁사 요금제"}), result("t1"),
        tool("t2", "WebFetch", {"url": "a.com/pricing"}), result("t2"),
        tool("t3", "WebFetch", {"url": "b.com/pricing"}), result("t3", ok=False),
        say("B사는 캐시 자료를 쓰겠습니다."),
        tool("t4", "Bash", {"command": "cat cache/b.json", "description": "캐시에서 B사 요금 읽기"}), result("t4"),
        say("세 곳의 요금제를 표로 정리했습니다."),
    ]


# ---------- 파서 ----------

def test_steps_and_final_response_are_split(tmp_path):
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", pricing_rows()))[0]
    assert t.final_response == "세 곳의 요금제를 표로 정리했습니다."
    assert [s.title for s in t.steps] == ["요금 페이지부터 찾겠습니다.", "B사는 캐시 자료를 쓰겠습니다."]
    assert [c.name for c in t.steps[0].calls] == ["WebSearch", "WebFetch", "WebFetch"]
    assert t.steps[1].calls[0].target == "캐시에서 B사 요금 읽기"  # description이 command보다 먼저
    assert t.failed_count == 1
    assert "요금 페이지부터" in t.response  # 원문·분석기 입력은 그대로 전체 글


def test_tools_without_a_leading_sentence_form_an_untitled_step(tmp_path):
    rows = [user("고쳐줘"), tool("t1", "Read", {"file_path": "/a/b.py"}), result("t1"), say("고쳤습니다.")]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert len(t.steps) == 1 and t.steps[0].title == ""
    assert t.steps[0].calls[0].target == "/a/b.py"


def test_turn_that_ends_with_a_tool_has_no_final_response(tmp_path):
    rows = [user("돌려줘"), say("실행합니다."), tool("t1", "Bash", {"command": "make"})]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert t.final_response == "" and t.ended_with_tool
    assert t.calls[0].ok is None


def test_command_records_and_interrupts_are_not_turns(tmp_path):
    rows = [
        user("<local-command-caveat>Caveat: ...</local-command-caveat>"),
        user("<command-name>/clear</command-name>\n<command-message>clear</command-message>"),
        user("<local-command-stdout></local-command-stdout>"),
        user("시스템 메시지", isMeta=True),
        user("진짜 요청"), say("답"),
        user("[Request interrupted by user]"),
    ]
    turns = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))
    assert [t.request for t in turns] == ["진짜 요청"]


def test_late_tool_result_attaches_to_its_own_turn(tmp_path):
    rows = [user("하나"), tool("t1", "Bash", {"command": "sleep 9"}),
            user("둘"), say("네"), result("t1", ok=False)]
    turns = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))
    assert turns[0].calls[0].ok is False and turns[0].tools == [("Bash", False)]
    assert turns[1].calls == []


def test_targets_drop_terminal_control_characters():
    assert transcript.target_of("Bash", {"command": "echo \x1b[31mred\x1b[0m\nsecond"}) == "echo red"


# ---------- 화면 ----------

def make_app(tmp_path, rows):
    tr = write(tmp_path / "t.jsonl", rows)
    d = tmp_path / "home" / "sessions" / "s1"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text(json.dumps({
        "ts": "2026-11-09T00:02:00.000Z", "session_id": "s1", "event": "Stop", "cwd": "/work/pricing",
        "transcript_path": str(tr), "iterm_session_id": "", "data": {}}) + "\n", encoding="utf-8")
    return ControlApp(home=tmp_path / "home")


async def ready(app, pilot):
    await pilot.pause()
    app.conversation.focus()
    app.refresh_sessions()
    await pilot.pause()


@pytest.mark.asyncio
async def test_list_shows_request_and_answer_but_no_tools(tmp_path):
    app = make_app(tmp_path, pricing_rows())
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        text = str(app.conversation.render_text())
        assert "경쟁사 3곳 요금제" in text
        assert "세 곳의 요금제를 표로 정리했습니다." in text  # 마지막 응답은 원문 전체 (요청 27)
        assert "도구 4" not in text and "✘1" not in text          # 도구 수·실패 수는 두지 않는다 (요구 이력 48)
        assert "WebFetch" not in text and "WebSearch" not in text


@pytest.mark.asyncio
async def test_enter_opens_step_cards_under_the_turn(tmp_path):
    app = make_app(tmp_path, pricing_rows())
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        text = str(app.conversation.render_text())
        assert "응답까지 한 일 · 단계 2" in text and "도구 4" not in text
        assert "1. 요금 페이지부터 찾겠습니다." in text and "2. B사는 캐시 자료를 쓰겠습니다." in text
        assert "WebFetch" not in text and "b.com/pricing" not in text and "✘" not in text   # 도구 줄은 두지 않는다 (요구 이력 48)
        await pilot.press("enter")
        assert "응답까지 한 일 · 단계" not in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_tool_only_work_shows_no_steps_and_no_tools(tmp_path):
    rows = [user("많이")]
    for n in range(9):
        rows += [tool(f"t{n}", "Read", {"file_path": f"f{n}.py"}), result(f"t{n}", ok=(n != 8))]
    rows.append(say("끝"))
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(160, 60)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        text = str(app.conversation.render_text())
        assert "응답까지 한 일: 중간에 한 말 없이 바로 답했습니다" in text   # 말 없이 도구만 쓴 구간은 단계로 세지 않는다
        assert "f0.py" not in text and "f8.py" not in text and "+3개" not in text
        await pilot.press("d")                          # 상세 화면에도 도구는 없다
        detail = str(app.conversation.render_text())
        assert "f5.py" not in detail and "Read" not in detail


@pytest.mark.asyncio
async def test_detail_screen_opens_with_d_and_escape_returns_to_same_turn(tmp_path):
    """응답 상세(d)는 마지막 대화에서만 연다 (요구 이력 41: 이전 턴의 단계·도구는 보지 않는다)."""
    rows = pricing_rows() + [user("두 번째", ts="2026-11-09T00:05:00.000Z"), say("두 번째 답")]
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        await pilot.press("d")
        text = str(app.conversation.render_text())
        assert "#2 응답 상세" in text
        await pilot.press("escape")
        text = str(app.conversation.render_text())
        assert "응답 상세" not in text and app.conversation.selected == 1
        assert app.session_list.selected_id == "s1"  # ①·③은 그대로
        await pilot.press("up")
        await pilot.press("d")                         # 이전 턴에서는 열리지 않는다
        assert "응답 상세" not in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_unfinished_answer_is_marked(tmp_path):
    rows = [user("돌려줘"), say("실행합니다."), tool("t1", "Bash", {"command": "make"})]
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        assert "최종 응답 없음: 진행 중이거나 중단됨" in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_korean_lines_do_not_wrap_in_a_narrow_pane(tmp_path):
    rows = [user("가" * 200), say("나" * 200)]
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(120, 40)) as pilot:
        await ready(app, pilot)
        width = app.conversation.content_size.width
        from rich.cells import cell_len
        lines = str(app.conversation.render_text()).splitlines()
        turn_lines = [ln for ln in lines if "가가" in ln or "나나" in ln]
        assert turn_lines and all(cell_len(ln) <= width for ln in turn_lines)


# ---------- Liner 구현 리뷰 지적 (review/out-impl24) ----------

def denied(tid, text):
    return {"type": "user", "timestamp": "t", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": True}]}}


def test_refused_tools_are_counted_apart_from_failures(tmp_path):
    rows = [user("지워줘"),
            tool("t1", "Bash", {"command": "rm -rf build"}),
            denied("t1", "The user doesn't want to proceed with this tool use. The tool use was rejected"),
            tool("t2", "Bash", {"command": "curl x"}),
            denied("t2", "Permission for this action was denied by the Claude Code auto mode classifier"),
            tool("t3", "Bash", {"command": "make"}), result("t3", ok=False),
            say("멈췄습니다.")]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert t.denied_count == 2 and t.failed_count == 1


def test_answer_after_a_command_record_is_not_added_to_the_previous_turn(tmp_path):
    rows = [user("A"), say("답A"),
            user("<command-name>/x</command-name>"),
            tool("t1", "Bash", {"command": "ls"}), result("t1"), say("답X")]
    turns = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))
    assert len(turns) == 1 and turns[0].final_response == "답A" and turns[0].calls == []


def test_parallel_tool_calls_in_one_message_get_their_own_results(tmp_path):
    rows = [user("둘 다"),
            {"type": "assistant", "timestamp": "t", "message": {"content": [
                {"type": "text", "text": "동시에 읽겠습니다."},
                {"type": "tool_use", "id": "p1", "name": "Read", "input": {"file_path": "a.py"}},
                {"type": "tool_use", "id": "p2", "name": "Read", "input": {"file_path": "b.py"}}]}},
            {"type": "user", "timestamp": "t", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "p2", "content": "x", "is_error": True},
                {"type": "tool_result", "tool_use_id": "p1", "content": "x", "is_error": False}]}},
            say("읽었습니다.")]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert [(c.target, c.ok) for c in t.steps[0].calls] == [("a.py", True), ("b.py", False)]


def test_two_sentences_in_a_row_become_one_step_title(tmp_path):
    rows = [user("해줘"), say("먼저 봅니다."), say("파일이 큽니다."),
            tool("t1", "Read", {"file_path": "a"}), result("t1"), say("끝")]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert len(t.steps) == 1 and t.steps[0].title == "먼저 봅니다.\n파일이 큽니다."


def test_more_control_sequences_are_removed():
    assert "\x1b" not in transcript.clean_line("x\x1b]0;unterminated title")
    assert transcript.clean_line("a\x1b(Bb") == "ab"
    assert transcript.clean_line("c​d‮e") == "cde"


def test_missing_timestamp_does_not_break_the_screen(tmp_path):
    rows = [{"type": "user", "timestamp": None, "message": {"content": "시간 없는 요청"}}, say("답")]
    turns = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))
    from control_tui.widgets.conversation import _clock
    assert _clock(turns[0].time) == "--:--" and _clock(None) == "--:--" and _clock(5) == "--:--"


@pytest.mark.asyncio
async def test_refused_and_failed_tools_are_not_shown(tmp_path):
    rows = [user("많이")]
    for n in range(8):
        rows.append(tool(f"t{n}", "Read", {"file_path": f"f{n}.py"}))
        rows.append(denied(f"t{n}", "The user doesn't want to proceed") if n == 6 else result(f"t{n}", ok=(n != 7)))
    rows.append(say("끝"))
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(160, 60)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        text = str(app.conversation.render_text())
        assert "f6.py" not in text and "f7.py" not in text  # 거절·실패한 도구도 보이지 않는다 (요구 이력 48)
        assert "거절됨" not in text and "도구 8" not in text


@pytest.mark.asyncio
async def test_escape_and_arrows_pass_through_when_not_in_detail(tmp_path):
    app = make_app(tmp_path, pricing_rows())
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        conv = app.conversation
        assert conv.check_action("close_detail", ()) is False
        assert conv.check_action("detail_move", ()) is False
        await pilot.press("d")
        assert conv.check_action("close_detail", ()) is True


@pytest.mark.asyncio
async def test_first_turn_is_selected_when_it_appears(tmp_path):
    app = make_app(tmp_path, [])
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        assert app.conversation.selected == -1
        write(tmp_path / "t.jsonl", [user("첫 요청"), say("첫 답")])
        app.refresh_sessions()
        await pilot.pause()
        assert app.conversation.selected == 0
        await pilot.press("enter")
        assert "중간에 한 말 없이 바로 답했습니다" in str(app.conversation.render_text())


@pytest.mark.asyncio
async def test_unanswered_turn_does_not_claim_an_answer(tmp_path):
    app = make_app(tmp_path, [user("방금 보낸 요청")])
    async with app.run_test(size=(160, 50)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        assert "아직 응답이 없습니다" in str(app.conversation.render_text())


@pytest.mark.asyncio
@pytest.mark.parametrize("cols", [70, 90])
async def test_cards_fit_in_narrow_panes(tmp_path, cols):
    rows = [user("좁은 화면"), say("한글로 된 아주 긴 중간 설명 문장입니다 " * 5),
            tool("t1", "mcp__playwright__browser_click", {"description": "가나다라마바사아자차카타파하 " * 6}),
            result("t1", ok=False), say("끝")]
    app = make_app(tmp_path, rows)
    async with app.run_test(size=(cols, 50)) as pilot:
        await ready(app, pilot)
        await pilot.press("enter")
        from rich.cells import cell_len
        width = app.conversation.content_size.width
        lines = str(app.conversation.render_text()).splitlines()
        steps = [ln for ln in lines if ln.lstrip().startswith("1. 한글로")]
        assert steps and all(cell_len(ln) <= width for ln in steps)          # 단계 줄이 좁은 화면에 맞는다
        assert "browser_c" not in str(app.conversation.render_text())      # 도구 이름은 보이지 않는다 (요구 이력 48)


def test_background_task_notifications_are_not_user_turns(tmp_path):
    """2026-11-09 실제 기록: 백그라운드 작업이 끝나면 origin.kind=task-notification인 사용자 줄이 생긴다."""
    rows = [user("요청", origin={"kind": "human"}), say("답"),
            user("<task-notification>\n<task-id>x</task-id>", origin={"kind": "task-notification"}),
            say("끝")]
    turns = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))
    assert [t.request for t in turns] == ["요청"]
    assert turns[0].final_response == "답"  # 알림 뒤의 '끝'이 앞 턴에 붙지 않는다


def test_refusal_is_the_same_in_tools_and_calls(tmp_path):
    rows = [user("지워줘"), tool("t1", "Bash", {"command": "rm x"}),
            denied("t1", "The user doesn't want to proceed with this tool use."), say("멈춤")]
    t = transcript.parse_turns(write(tmp_path / "t.jsonl", rows))[0]
    assert t.tools == [("Bash", None)] and t.calls[0].denied and t.calls[0].ok is None
