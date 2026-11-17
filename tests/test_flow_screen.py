"""관제 화면의 목표 흐름·요청 기록·진행 중 표시 (요청 40·41, 요구 이력 66, SCREEN §2 ② 머리).

화면 시험이라 분석 결과는 고정된 사전으로 만든다. 흐름을 이어 적는 엔진 시험은 러스트로 옮겼다
(crates/engine/tests, 요구 이력 68 R2). 예전 tests/test_flow_chain.py·test_in_progress.py의 화면 부분.
"""

import json

import pytest

from tests.test_flow_view import app_for, make_session, ready, text_of


def flow_analysis(shift_turns=(2,)):
    steps = []
    for k in range(1, 7):
        s = {"index": k, "label": "구체화", "summary": f"요약 {k}", "quote": f"요청 {k}번", "grounded": True,
             "shift": k in shift_turns, "fp": ""}
        if k in shift_turns:
            s.update(direction="옮김" if k % 2 else "넓힘", how=f"앞 목표에서 목표 {k}로 이어짐",
                     shift_quote=f"요청 {k}번에 있는 아주 긴 근거 구절입니다 끝까지", goal=f"목표 {k}", prev_goal="")
        steps.append(s)
    cur = max(shift_turns) if shift_turns else 1
    return {"first_goal": "목표 1", "current_goal": f"목표 {cur}", "turns": [], "ledger": [], "format": 2,
            "last_turn": 6, "flow": {"version": 1, "first_goal": {"text": "목표 1", "turn": 1, "quote": "요청 1번"},
                                     "current_goal": {"text": f"목표 {cur}", "turn": cur, "quote": f"요청 {cur}번"},
                                     "steps": steps, "until": 6}}


@pytest.mark.asyncio
async def test_screen_shows_shift_steps_with_direction_lines_and_source_quotes(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 4)))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "주제 이동과 결정" in text
        assert "◆ #2 넓힘 목표 2" in text and "◉ 지금 #4–6 넓힘 목표 4" in text   # 목표가 #4부터 #6까지 이어짐 (요청 42)
        assert "└ 앞 목표에서 목표 2로 이어짐 “요청 2번에 있는 아주 긴 근거 구절…”" in text   # 원문 구절은 20자까지
        assert "└ 앞 목표에서 목표 4로 이어짐" in text
        assert "방향이 바뀐 턴만" not in text


@pytest.mark.asyncio
async def test_many_shifts_fold_the_middle_with_a_summary_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 3, 4, 5, 6)))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "┊ #2–#3 2단계 · 목표 2 → 목표 3 · g 흐름 전체" in text   # 접힌 단계가 무엇인지 보인다 (요청 41)
        assert "◆ #4" in text and "◆ #5" in text and "◉ 지금 #6" in text
        assert "◆ #2" not in text


@pytest.mark.asyncio
async def test_no_shift_is_one_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=()))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "◉ #1–6 처음·지금 목표 1" in text and "◆" not in text


@pytest.mark.asyncio
async def test_low_screen_keeps_first_and_current_with_its_direction_line(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=flow_analysis(shift_turns=(2, 4)))
    app = app_for(home)
    async with app.run_test(size=(160, 30)) as pilot:   # ② 칸이 24줄보다 낮은 창
        await ready(app, pilot)
        text = text_of(app)
        assert "● #1 시작 목표 1" in text and "◉ 지금 #4–6 넓힘 목표 4" in text
        assert "└ 앞 목표에서 목표 4로 이어짐" in text      # 지금 목표가 어떻게 이어졌는지는 남는다
        assert "◆" not in text and "목표 2로 이어짐" not in text


def decided(analysis, turns=(3, 5), titles=None):
    for s in analysis["flow"]["steps"]:
        if s["index"] in turns:
            s.update(label="확정", decision=f"정한 것 {s['index']}", quote=f"요청 {s['index']}번")
        if titles and s["index"] in titles:
            s["title"] = titles[s["index"]]
    return analysis


@pytest.mark.asyncio
async def test_decision_turns_show_with_a_check_mark_and_after_the_goal_are_indented(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 4)), turns=(3, 5))
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "✔ #3 확정 정한 것 3 “요청 3번”" in text            # 지금 목표 앞의 결정
        assert "   ✔ #5 확정 정한 것 5 “요청 5번”" in text        # 지금 목표(#4) 뒤의 결정은 ◉ 아래 들여 씀


@pytest.mark.asyncio
async def test_g_opens_the_whole_flow_and_escape_closes(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 3, 4, 5, 6)), turns=(), titles={2: "짧은 이름 2"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        assert "짧은 이름 2 → 목표 3" in text_of(app)              # 분석이 낸 짧은 이름을 쓴다
        app.conversation.focus()
        await pilot.press("g")
        text = text_of(app)
        assert "목표 흐름 전체" in text and "◆ #2 넓힘 목표 2" in text and "◆ #3 옮김 목표 3" in text
        assert "◉ 지금 #6" in text
        await pilot.press("escape")
        assert "목표 흐름 전체" not in text_of(app)


@pytest.mark.asyncio
async def test_previous_turns_show_the_flow_summary_without_tools_and_enter_opens_the_raw_text(tmp_path):
    a = flow_analysis(shift_turns=(2,))
    for s in a["flow"]["steps"]:
        s["agent_summary"] = f"에이전트 {s['index']}"
    home, tr, _ = make_session(tmp_path, n=6, analysis=a)
    rows = [json.loads(x) for x in tr.read_text().splitlines()]
    rows[3]["message"]["content"].append({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}})
    tr.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "요약 요약 2 → 에이전트 2" in text                   # 요청 → 에이전트가 한 말·일
        assert "도구 1" not in text                                 # 이전 턴에는 도구 수를 두지 않는다
        app.conversation.focus()
        await pilot.press("up")
        await pilot.press("enter")
        assert "응답 5번 끝" in text_of(app) and "응답까지 한 일" not in text_of(app).split("마지막 대화")[0]


@pytest.mark.asyncio
async def test_while_analyzing_now_moves_to_the_last_turn_with_dots(tmp_path):
    """분석 중 (요청 42): '지금'을 마지막 턴으로 먼저 옮기고, 옛 지금 목표는 일반 단계. 블록 대신 같은 색 점."""
    a = flow_analysis(shift_turns=(2, 4))
    a["flow"]["until"] = 5
    a["flow"]["steps"] = a["flow"]["steps"][:5]
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        conv = app.conversation
        conv.show(conv.view, conv.turns, conv.analysis, status={"state": "running", "seconds": 3, "turn": 6})
        await pilot.pause()
        text = text_of(app)
        assert "◆ #4 넓힘 목표 4" in text                    # 옛 지금 목표는 일반 단계로
        assert "◉ 지금 #6 분석 중." in text                 # 지금은 마지막 턴, '분석 중'과 점으로
        assert "░" not in text and "▒" not in text and "반영 중" not in text
        assert "#6 분석 중." in text.split("요청 체크")[1].split("\n")[0]   # 요청 체크 줄 끝


def test_dots_cycle_and_keep_three_cells(monkeypatch):
    from control_tui.widgets import conversation as cv
    seen = set()
    for sec in (0, 1, 2):
        monkeypatch.setattr(cv.time, "time", lambda s=sec: float(s))
        d = cv.ConversationView._dots() if hasattr(cv, "ConversationView") else None
        if d is None:
            d = [v for v in vars(cv).values() if isinstance(v, type) and hasattr(v, "_dots")][0]._dots()
        assert d.startswith("분석 중") and len(d) == len("분석 중") + 3
        seen.add(d[len("분석 중"):].strip())
    assert seen == {".", "..", "..."}


@pytest.mark.asyncio
async def test_folded_line_breaks_only_between_steps(tmp_path):
    a = decided(flow_analysis(shift_turns=(2, 3, 4, 5, 6)), turns=(),
                titles={2: "Claude Code 확장", 3: "관제와 패널 오가기"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(110, 46)) as pilot:
        await ready(app, pilot)
        fold = [ln for ln in text_of(app).splitlines() if ln.lstrip().startswith("┊")]
        assert fold and all("Claude Code 확장" in ln or "Claude" not in ln for ln in fold)   # 이름 중간에서 끊지 않는다
        assert fold[-1].rstrip().endswith("g 흐름 전체")


def recorded(analysis):
    analysis["flow"]["requests"] = [
        {"id": "R1", "from_turn": 2, "summary": "설치 절 추가", "quote": "요청 2번", "state": "addressed", "tool_failed": True, "agent_quote": "추가했습니다"},
        {"id": "R2", "from_turn": 3, "summary": "CHANGELOG 만들기", "quote": "요청 3번", "state": "open", "tool_failed": False, "agent_quote": ""},
        {"id": "R3", "from_turn": 4, "summary": "테스트 돌리기", "quote": "요청 4번", "state": "deferred", "tool_failed": False, "agent_quote": "아직 못 돌렸습니다"},
        {"id": "R4", "from_turn": 4, "summary": "옛 요청", "quote": "요청 4번", "state": "superseded", "superseded_by": 5},
        {"id": "R5", "from_turn": 5, "summary": "한글로", "quote": "요청 5번", "state": "addressed", "tool_failed": False, "agent_quote": "한글로 씁니다"},
    ]
    analysis["flow"]["version"] = 2
    return analysis


@pytest.mark.asyncio
async def test_request_record_shows_remaining_facts_not_scores(tmp_path):
    home, _, _ = make_session(tmp_path, n=6, analysis=recorded(flow_analysis(shift_turns=(2,))))
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "요청 기록  누적 4개 · #6 기준  남은 것 2" in text
        assert "○ CHANGELOG 만들기 “요청 3번”" in text
        assert "⊘ 테스트 돌리기 — 에이전트: 못 했거나 미룸 “아직 못 돌렸습니다”" in text
        assert "△" not in text and "도구 실패" not in text      # 옛 기록의 tool_failed도 보이지 않는다 (요구 이력 48)
        assert "빠짐" not in text.split("──")[0] and "챙김" not in text
        assert app.session_list.selected() is not None
        app.conversation.focus()
        await pilot.press("c")
        text = text_of(app)
        for title in ("아직 다루지 않음 1", "못 했거나 미룸 1", "다룸 2", "뒤 요청이 대신함 1"):
            assert title in text
        assert "도구 실패" not in text
        assert "한글로 — 에이전트: “한글로 씁니다”" in text


@pytest.mark.asyncio
async def test_moved_flow_says_older_requests_are_not_recorded(tmp_path):
    a = recorded(flow_analysis(shift_turns=(2,)))
    a["flow"]["requests_from"] = 4
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(180, 46)) as pilot:
        await ready(app, pilot)
        assert "#3 이전 요청은 기록 전" in text_of(app)


async def test_control_shows_in_progress_with_its_mark(tmp_path):
    a = recorded(flow_analysis(shift_turns=(2,)))
    a["flow"]["requests"].append({"id": "R6", "from_turn": 5, "by_turn": 6, "summary": "취소 버튼", "quote": "요청 5번",
                                  "state": "in_progress", "agent_quote": "병합은 하지 않았습니다"})
    home, _, _ = make_session(tmp_path, n=6, analysis=a)
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        text = text_of(app)
        assert "남은 것 3" in text
        assert "◐ 취소 버튼 — 진행 중 “병합은 하지 않았습니다”" in text
        app.conversation.focus()
        await pilot.press("c")
        assert "진행 중 1" in text_of(app)
