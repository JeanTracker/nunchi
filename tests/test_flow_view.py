"""② 시간순 대화 흐름 (요청 25~31, SCREEN §2): 마지막 대화는 늘 보임, 묶음, 머리 고정, 분석 상태, 대기열."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_tui.app import ControlApp
from tests.fake_analyzer import FROZEN, FakeAnalyzer


def write(path: Path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def make_session(tmp_path, n=3, last_answer=None, analysis=None, events=None, sid="s1"):
    rows = []
    for i in range(1, n + 1):
        rows.append({"type": "user", "timestamp": f"2026-11-09T0{i // 60}:{i % 60:02d}:00.000Z",
                     "message": {"role": "user", "content": f"요청 {i}번"}})
        text = last_answer if (i == n and last_answer) else f"응답 {i}번 끝"
        rows.append({"type": "assistant", "timestamp": f"2026-11-09T0{i // 60}:{i % 60:02d}:30.000Z",
                     "message": {"content": [{"type": "text", "text": text}]}})
    home = tmp_path / "home"
    d = home / "sessions" / sid
    d.mkdir(parents=True, exist_ok=True)
    tr = tmp_path / f"{sid}.jsonl"
    write(tr, rows)
    stop = f"2026-11-09T0{n // 60}:{n % 60:02d}:40.000Z"
    evs = events or [{"ts": stop, "session_id": sid, "event": "Stop", "cwd": "/work/demo",
                      "transcript_path": str(tr), "iterm_session_id": "w0t0p0:PANEL-1", "data": {}}]
    for e in evs:
        e.setdefault("transcript_path", str(tr))
    write(d / "events.jsonl", evs)
    if analysis is not None:
        analysis.setdefault("source_ts", stop)
        (d / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    return home, tr, stop


def app_for(home, **kw):
    return ControlApp(home=home, panel_scanner=lambda ids: [], panel_checker=lambda: {"PANEL-1"}, **kw)


async def ready(app, pilot):
    await pilot.pause()
    app.refresh_sessions()
    await pilot.pause()


def text_of(app):
    return str(app.conversation.render_text())


# ---------- 마지막 대화는 늘 보인다 ----------

@pytest.mark.asyncio
async def test_last_turn_is_visible_in_a_66_turn_session_and_old_turns_are_grouped(tmp_path):
    home, _, _ = make_session(tmp_path, n=66)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "마지막 대화 · #66" in text and "요청 66번" in text and "응답 66번 끝" in text
        assert "#1–10" in text or "#51–60" in text   # 옛 대화는 10턴 묶음
        assert "요청 3번" not in text                 # 묶음 안의 턴은 접혀 있다


@pytest.mark.asyncio
async def test_long_last_answer_starts_at_its_request_and_pgdn_reaches_the_end(tmp_path):
    long = "\n".join(f"{k}번째 줄입니다" for k in range(1, 61)) + "\n마지막에 묻습니다: B사 출처를 알려 주세요"
    home, _, _ = make_session(tmp_path, n=5, last_answer=long)
    app = app_for(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "마지막 대화 · #5" in text and "1번째 줄입니다" in text
        assert "아래로" in text and "마지막에 묻습니다" not in text
        app.input_box.focus()
        app.input_box.load_text("쓰던 답")
        for _ in range(5):
            await pilot.press("pagedown")      # ③에 커서가 있어도 ②가 내려간다
        await pilot.pause()
        assert "마지막에 묻습니다" in text_of(app)
        assert app.input_box.value == "쓰던 답"
        assert "응답 끝" in text_of(app)


@pytest.mark.asyncio
async def test_scrolling_up_pins_a_one_line_marker_and_end_returns(tmp_path):
    home, _, _ = make_session(tmp_path, n=30)
    app = app_for(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("home")
        await pilot.press("enter")    # 첫 묶음 펼치기 (고른 것이 맨 마지막이므로 먼저 위로)
        for _ in range(40):
            await pilot.press("up")
        await pilot.press("enter")
        await pilot.press("home")
        await pilot.pause()
        text = text_of(app)
        assert "▼ 마지막 대화 #30" in text and "End로 돌아가기" in text
        await pilot.press("end")
        assert "▼ 마지막 대화" not in text_of(app) and "마지막 대화 · #30" in text_of(app)


# ---------- 머리와 분석 상태 ----------

ANALYSIS = {"first_goal": "가격표", "current_goal": "할인 추가", "next_action": "할인 확인",
            "turns": [{"index": 1, "label": "시작", "summary": "가격표", "response_summary": "세 곳 요약"},
                      {"index": 2, "label": "구체화", "summary": "할인", "response_summary": "할인 요약"}],
            "last_response_summary": "마지막 응답 요약입니다",
            "ledger": [{"id": "C1", "condition": "출처 표시", "from_turn": 1, "status": "missed", "evidence": "없음"},
                       {"id": "C2", "condition": "표", "from_turn": 1, "status": "kept", "evidence": "있음"}],
            "last_turn": 2, "format": 2}


@pytest.mark.asyncio
async def test_stale_analysis_is_kept_dim_with_its_basis_and_status(tmp_path):
    a = dict(ANALYSIS, source_ts="2026-11-09T00:02:40.000Z")   # #2 기준, 응답은 #3까지 옴
    home, _, _ = make_session(tmp_path, n=3, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "#2 응답 기준" in text and "#3 반영 전" in text
        assert "✘ 빠짐 1" in text and "(#2 기준)" in text and "✘ 출처 표시" in text
        assert "↻ 요약 준비 중" not in text   # #3은 마지막 대화라 원문 전체
        assert "[분석 대기]" not in text   # 분석기가 꺼져 있으면 기다리는 분석이 없다 (Liner 리뷰 1-d)


@pytest.mark.asyncio
async def test_previous_turn_without_summary_shows_raw_and_preparing(tmp_path):
    a = dict(ANALYSIS, source_ts="x")
    home, _, _ = make_session(tmp_path, n=4, analysis=a)
    gate = threading.Event()
    app = app_for(home, analyzer=FakeAnalyzer(result=FROZEN["EMPTY_4_TURNS"], gate=gate))  # 분석 중인 상태
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "요약 세 곳 요약" in text           # #1은 요약
        assert "원문 응답 3번 끝" in text and "요약 준비 중 (#3" in text
        gate.set()


@pytest.mark.asyncio
async def test_change_notice_after_analysis(tmp_path):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    a = dict(ANALYSIS, analyzed_at=now, changes={"missed_before": 0, "missed_after": 1,
                                                   "new_missed": ["출처 표시"], "goal_changed": True})
    home, _, _ = make_session(tmp_path, n=2, analysis=a)
    app = app_for(home, analyzer=FakeAnalyzer(result=FROZEN["EMPTY_4_TURNS"]))  # 이미 최신이라 다시 돌지 않는다
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "갱신됨 · 빠짐 0→1 · 새 빠짐 1 · 목표 바뀜" in text  # '다음 할 일'은 요청 33에서 뺌
        assert "✔ 분석 완료 · #2 기준" in text


@pytest.mark.asyncio
async def test_summary_view_keeps_question_lines_in_original(tmp_path):
    answer = "## 정리\n표를 만들었습니다.\n\n- A사 메모 추가\n\nB사 대체 출처가 있으면 알려 주세요."
    home, _, _ = make_session(tmp_path, n=2, last_answer=answer, analysis=dict(ANALYSIS))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert "정리" in text_of(app) and "## 정리" not in text_of(app)   # 기본: 전체, 마크다운 기호 정리
        app.conversation.focus()
        await pilot.press("s")
        text = text_of(app)
        assert "요약  마지막 응답 요약입니다" in text
        assert "❓ B사 대체 출처가 있으면 알려 주세요." in text and "o 전체 펼치기" in text
        await pilot.press("o")
        assert "표를 만들었습니다." in text_of(app)


@pytest.mark.asyncio
async def test_summary_view_falls_back_to_full_when_no_summary(tmp_path):
    home, _, _ = make_session(tmp_path, n=2)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("s")
        text = text_of(app)
        assert "분석 꺼짐 → 전체 표시" in text and "응답 2번 끝" in text


# ---------- 작업 중·대기열 ----------

@pytest.mark.asyncio
async def test_working_turn_and_queued_message_are_shown_in_the_flow(tmp_path):
    rows_events = [{"ts": "2026-11-09T00:01:40.000Z", "session_id": "s1", "event": "Stop", "cwd": "/work/demo",
                    "iterm_session_id": "w0t0p0:PANEL-1", "data": {}},
                   {"ts": "2026-11-09T00:03:00.000Z", "session_id": "s1", "event": "UserPromptSubmit",
                    "cwd": "/work/demo", "iterm_session_id": "w0t0p0:PANEL-1", "data": {}}]
    home, tr, _ = make_session(tmp_path, n=2, events=rows_events)
    rows = [json.loads(x) for x in tr.read_text().splitlines()][:-1]   # 마지막 응답 지움 → 작업 중
    write(tr, rows)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.outbox.enqueue("s1", "표 맨 아래에 합계 행도 넣어줘")
        app.refresh_sessions()
        await pilot.pause()
        text = text_of(app)
        assert "에이전트 작업 중" in text and "에이전트가 답하는 중" in text
        assert '⏳ 보낼 예정 (대기열 1건) "표 맨 아래에 합계 행도 넣어줘"' in text


# ---------- 분석 정책 ----------

@pytest.mark.asyncio
async def test_only_the_selected_session_is_analyzed_and_old_ones_are_not_on_start(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, sid="aaa")
    make_session(tmp_path, n=2, sid="bbb")
    calls = []
    a = FakeAnalyzer(result=FROZEN["ANALYSIS_2_TURNS"], calls=calls)
    app = app_for(home, analyzer=a)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        a.wait_idle(10)
    assert len(calls) == 1   # 고른 세션 하나만 (설정 기본: selected)


@pytest.mark.asyncio
async def test_manual_mode_waits_for_the_a_key(tmp_path):
    home, _, _ = make_session(tmp_path, n=2)
    (home / "config.json").write_text(json.dumps({"analyze_when": "manual"}), encoding="utf-8")
    calls = []
    a = FakeAnalyzer(result=FROZEN["ANALYSIS_2_TURNS"], calls=calls)
    app = app_for(home, analyzer=a)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        a.wait_idle(5)
        assert calls == [] and "a 키로 분석" in text_of(app)
        app.session_list.focus()
        await pilot.press("a")
        a.wait_idle(10)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_session_list_shows_analysis_marks(tmp_path):
    home, _, _ = make_session(tmp_path, n=2)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        lst = app.session_list
        assert lst.line_layout(1, False, "↻")[1] == " ⚠1↻"
        assert lst.line_layout(2, False, "새")[1] == " ⚠2 새"
        assert lst.line_layout(0, False, "·", judged=False)[1] == " ◌·"
        assert lst.line_layout(1, False, "!")[1] == " ⚠1!"


@pytest.mark.asyncio
async def test_quitting_shuts_the_analyzer_down(tmp_path):
    home, _, _ = make_session(tmp_path, n=2)
    stopped = []
    a = FakeAnalyzer(result=FROZEN["ANALYSIS_2_TURNS"])
    a.shutdown = lambda: stopped.append(True)
    app = app_for(home, analyzer=a)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
    assert stopped == [True]



@pytest.mark.asyncio
async def test_preparing_mark_is_not_shown_when_the_analyzer_is_off(tmp_path):
    home, _, _ = make_session(tmp_path, n=4, analysis=dict(ANALYSIS, source_ts="x"))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "원문 응답 3번 끝" in text and "요약 준비 중" not in text


@pytest.mark.asyncio
async def test_summary_arriving_does_not_collapse_the_full_answer_being_read(tmp_path):
    home, _, stop = make_session(tmp_path, n=2, last_answer="긴 응답 본문")
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("s")                      # 요약 보기를 켰지만 요약이 없어 전체
        assert "긴 응답 본문" in text_of(app)
        d = home / "sessions" / "s1"
        (d / "analysis.json").write_text(json.dumps(dict(ANALYSIS, source_ts=stop)), encoding="utf-8")
        app.refresh_sessions()
        await pilot.pause()
        text = text_of(app)
        assert "긴 응답 본문" in text and "요약이 도착했습니다" in text   # 자동으로 접지 않는다
        await pilot.press("o")
        assert "요약  마지막 응답 요약입니다" in text_of(app)


def test_records_after_the_response_time_are_not_read(tmp_path):
    from control_tui import transcript
    tr = tmp_path / "t.jsonl"
    write(tr, [{"type": "user", "timestamp": "2026-11-09T00:01:00.000Z", "message": {"content": "요청"}},
               {"type": "assistant", "timestamp": "2026-11-09T00:01:30.000Z",
                "message": {"content": [{"type": "text", "text": "먼저 답"}]}},
               {"type": "assistant", "timestamp": "2026-11-09T00:05:00.000Z",
                "message": {"content": [{"type": "text", "text": "나중에 붙은 답"}]}}])
    t = transcript.parse_turns(tr, until_ts="2026-11-09T00:02:00.000Z")[0]
    assert "먼저 답" in t.response and "나중에 붙은 답" not in t.response


@pytest.mark.asyncio
async def test_korean_jamo_work_as_shortcuts_outside_the_input(tmp_path):
    """한글 입력기 상태: ㅇ=d(상세), ㅑ=i(입력줄로). 입력줄 안에서는 글자 그대로."""
    home, _, _ = make_session(tmp_path, n=2)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("ㅇ")
        assert app.conversation.detail is True
        await pilot.press("escape")
        await pilot.press("ㅑ")
        assert app.focused is app.input_box
        await pilot.press("ㅂ")
        assert app.input_box.value == "ㅂ" and app.is_running


@pytest.mark.asyncio
async def test_after_paging_back_down_a_new_answer_is_followed(tmp_path):
    long = "\n".join(f"{k}줄" for k in range(1, 50))
    home, tr, _ = make_session(tmp_path, n=8, last_answer=long)
    app = app_for(home)
    async with app.run_test(size=(160, 40)) as pilot:
        await ready(app, pilot)
        app.conversation.focus()
        await pilot.press("pageup")
        await pilot.press("pagedown")           # 다시 마지막 대화 시작으로
        rows = [json.loads(x) for x in tr.read_text().splitlines()]
        rows += [{"type": "user", "timestamp": "2026-11-09T00:20:00.000Z", "message": {"content": "요청 9번"}},
                 {"type": "assistant", "timestamp": "2026-11-09T00:20:30.000Z",
                  "message": {"content": [{"type": "text", "text": "응답 9번 끝"}]}}]
        write(tr, rows)
        app.refresh_sessions()
        await pilot.pause()
        text = text_of(app)
        assert "마지막 대화 · #9" in text and "응답 9번 끝" in text


@pytest.mark.asyncio
async def test_waiting_label_follows_the_real_analysis_state(tmp_path):
    home, _, _ = make_session(tmp_path, n=2, analysis=dict(ANALYSIS, turns=[]))   # 분석은 끝났고 라벨만 없음
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert "[분석 대기]" not in text_of(app)


@pytest.mark.asyncio
async def test_korean_ctrl_combos_and_bracket_keys(tmp_path):
    """2026-11-10 실제 키 확인: 한글 상태 Ctrl+J=ctrl+ㅓ, Ctrl+Q=ctrl+ㅂ. Home/End 없는 키보드는 [ ]."""
    home, _, _ = make_session(tmp_path, n=30)
    app = app_for(home)
    async with app.run_test(size=(160, 36)) as pilot:
        await ready(app, pilot)
        app.input_box.focus()
        app.input_box.load_text("첫 줄")
        app.input_box.move_cursor(app.input_box.document.end)
        await pilot.press("ctrl+ㅓ")
        assert app.input_box.value == "첫 줄\n"
        app.conversation.focus()
        await pilot.press("left_square_bracket")
        assert app.conversation.scroll_top == 0
        await pilot.press("right_square_bracket")
        assert app.conversation.scroll_top is None
        await pilot.press("ctrl+ㅂ")
        await pilot.pause()
    assert not app.is_running
